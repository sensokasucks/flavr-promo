"""
Owner DMs ("pings"): Discord DMs from FlaVR Promo to the streamer (OWNER_ID). The Discord app on the
phone turns each DM into a notification, so no other app is needed.

Kinds (each can be switched with /pings; the defaults are in KINDS):
  friends  someone the go-live watcher follows went live (sent as one list every 10 minutes)
  calendar the weekly calendar changed: new schedules, go-lives, ends, new week / review posted
           (collected for 10 minutes, sent with the picture; flavrpromo/calendar_post.py)
  share    copy-ready calendar text for other Discords and X, after the Sunday post and the
           Friday / Monday review (flavrpromo/share.py; waits for the end of quiet hours)
  collab   a possible collab: a stream title @mentions a friend or group (flavrpromo/collabs.py), one DM
           each with Confirm / Not a collab buttons (waits for the end of quiet hours)

The Stream Core pings (stream started / dropped, Core stopped answering, raids, big tips, the
after-stream recap, chat moments) and the server's growth DM stay in FlaVR Bot, which has the Core
link and server care (split 2026-11-20).

Quiet hours (QUIET_HOURS, default 3-11 in TZ): pings wait and arrive as one message when quiet hours
end. While the go-live watcher sees the owner live, quiet hours don't apply (you're clearly awake).

Who calls it: flavrpromo/__main__.py makes one ``Pinger`` (``live`` = the watcher's "is the owner
live" answer) and runs ``run()`` (flushes held / batched pings every minute); flavrpromo/bot.py calls
``friend_live`` from the go-live post; flavrpromo/calendar_post.py calls ``ping("calendar", ...)``.
``send`` is the bot's "DM the owner".
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Tuple
from zoneinfo import ZoneInfo

from .store import Store

log = logging.getLogger("flavrpromo.pings")

# kind -> (what /pings shows, on by default)
KINDS: Dict[str, Tuple[str, bool]] = {
    "friends": ("Friends going live (every 10 minutes, in one message)", False),
    "calendar": ("Calendar changes, with the new picture (every 10 minutes at most)", True),
    "share": ("Copy-ready calendar text for other Discords and X (Sunday + reviews)", True),
    # flavrpromo/calendar_post.py collab_tick: a title @mentions a friend / group → Confirm / Not a collab
    "collab": ("Possible collabs to confirm (a title @mentions a friend or group)", True),
}
FRIENDS_EVERY = 600.0       # seconds between "Live now: ..." lists

Send = Callable[[str], Awaitable[None]]


def length(sec: Any) -> str:
    m = int(sec or 0) // 60
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


class Pinger:
    def __init__(self, store: Store, send: Send, tz: str = "America/New_York",
                 quiet: Tuple[int, int] = (3, 11),
                 live: Callable[[], bool] = lambda: False, clock: Callable[[], float] = time.time):
        self.store = store
        self.send = send
        try:
            self.tz = ZoneInfo(tz)
        except Exception:
            log.warning("Unknown TZ %r; using America/New_York", tz)
            self.tz = ZoneInfo("America/New_York")
        self.quiet = quiet
        self.live = live
        self.clock = clock
        self._friends: List[str] = []
        self._friends_at = 0.0

    # ── switches ───────────────────────────────────────────────────────
    def switches(self) -> Dict[str, bool]:
        saved = self.store.get("pings", {}) or {}
        return {k: bool(saved.get(k, d)) for k, (_, d) in KINDS.items()}

    def set(self, kind: str, on: bool) -> None:
        saved = self.store.get("pings", {}) or {}
        saved[kind] = bool(on)
        self.store.put("pings", saved)

    def set_quiet(self, start: int, end: int) -> None:
        self.quiet = (start % 24, end % 24)
        self.store.put("quiet_hours", list(self.quiet))

    def load_quiet(self) -> None:
        q = self.store.get("quiet_hours")
        if isinstance(q, list) and len(q) == 2:
            self.quiet = (int(q[0]) % 24, int(q[1]) % 24)

    def quiet_now(self) -> bool:
        start, end = self.quiet
        if start == end or self.live():
            return False
        hour = datetime.fromtimestamp(self.clock(), self.tz).hour
        return start <= hour < end if start < end else (hour >= start or hour < end)

    # ── sending ────────────────────────────────────────────────────────
    async def ping(self, kind: str, text: str, urgent: bool = False) -> None:
        if not self.switches().get(kind, False):
            return
        if not urgent and self.quiet_now():
            held = self.store.get("held_pings", []) or []
            held.append(f"{datetime.fromtimestamp(self.clock(), self.tz):%H:%M} {text}")
            self.store.put("held_pings", held[-50:])
            return
        await self._send(("🚨 " if urgent else "") + text)

    async def _send(self, text: str) -> None:
        try:
            await self.send(text[:1900])
        except Exception:
            log.exception("could not DM the owner")

    async def flush(self) -> None:
        """Send what quiet hours held back, and the friends list every FRIENDS_EVERY seconds."""
        if self.quiet_now():
            return
        held = self.store.get("held_pings", []) or []
        if held:
            self.store.put("held_pings", [])
            await self._send("While you were away:\n" + "\n".join(held))
        if self._friends and self.clock() - self._friends_at >= FRIENDS_EVERY:
            names, self._friends = self._friends, []
            self._friends_at = self.clock()
            await self._send("🟣 Live now: " + ", ".join(names))

    async def run(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.flush()
            except Exception:
                log.exception("ping flush failed")

    # ── events ─────────────────────────────────────────────────────────
    def friend_live(self, name: str, where: str) -> None:
        """The watcher saw someone start; collected and sent as one list (flush)."""
        if self.switches().get("friends"):
            self._friends.append(f"{name} ({where})")
