"""
The community calendar: streams members add from their own self-promo posts, shown on their own
"Community" board and Friday / Monday reviews (the built-in group "community", flavrpromo/groups.py),
separate from FlaVR and Friends. Asked for by the owner 2026-11-20.

How a stream gets on it (opt-in per post; the bot never reads a channel on its own)
  * Message menu: long-press (phone) or right-click (PC) a post → Apps → "Add to community calendar".
    A post with a Twitch / Kick channel link first asks "When?" (blank = live now, or soon).
  * /community schedule link [when]: the same, typed.
  Who may: members with one of the roles picked with /community roles (kv "promo.roles"), for their
  OWN posts; moderators (owner, Manage Server, Manage Messages) for anyone's and with no limit. With
  no roles picked, only moderators can add. Each person can add PROMO_WEEKLY_LIMIT streams in 7 days.

Which links count (anything else is ignored; the bot never opens a link, it asks the platform's
official API about it)
  youtube.com/watch?v=ID, youtu.be/ID, youtube.com/live/ID   a stream: scheduled, live or finished
                                                            (a plain upload is refused)
  twitch.tv/videos/ID                                       a past broadcast (VOD)
  twitch.tv/NAME, kick.com/NAME                              a channel: live now → that stream; a time
                                                            given → planned then; Twitch only: its
                                                            next schedule segment; else it waits
                                                            PROMO_WAIT_HOURS for them to go live

Each row (store table "promo") then moves waiting → scheduled → live → past. ``Promo.run`` checks
the open ones every CHECK_EVERY seconds: Twitch and Kick channels only while live, waiting or near
their planned time (one Helix /streams or Kick /channels call for all of them), YouTube videos
every YOUTUBE_EVERY (one videos.list, 1 quota unit per 50). A finished Twitch stream gets its VOD
link and picture; a finished Kick stream links the channel's videos page, because Kick's official
API has no list of past broadcasts. A planned time that passes by STALE_AFTER with no stream drops off.

Safety: duplicates merge (the same video or the same channel within MATCH_WINDOW = one row), a
deleted post drops its streams, a moderator can take any off (/community remove, or the menu's
"Remove from community calendar"), and nothing the bot posts pings anyone.

Who calls it: flavrpromo/bot.py (the menu entries, /community, a deleted post), flavrpromo/__main__.py
(``run``), flavrpromo/calendar.py ``build_week`` (``tiles`` for the "community" board).
Settings: PROMO_WEEKLY_LIMIT, PROMO_WAIT_HOURS (flavrpromo/config.py, .env.example).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from .calendar import MATCH_WINDOW, MERGE_WINDOW, STALE_AFTER, Tile

log = logging.getLogger("flavrpromo.promo")

GROUP = "community"             # the board these streams go on (flavrpromo/groups.py DEFAULTS)
CHECK_EVERY = 180               # seconds between checks of Twitch / Kick channels
YOUTUBE_EVERY = 600             # seconds between YouTube checks (quota: 1 unit per 50 videos)
SOON = 30 * 60                  # a planned Twitch / Kick stream is checked from this long before its time
LIVE_GONE = 8 * 60              # a live channel not seen live this long = the stream ended
ROLES_KEY = "promo.roles"       # kv: [role id, ...] allowed to add their own posts

# ── links ─────────────────────────────────────────────────────────────
_URL = re.compile(r"https?://[^\s<>()\[\]]+", re.I)
_YT = re.compile(r"^(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/)|youtu\.be/)([\w-]{11})", re.I)
_TW_VOD = re.compile(r"^(?:www\.|m\.)?twitch\.tv/videos/(\d+)", re.I)
_TW = re.compile(r"^(?:www\.|m\.)?twitch\.tv/([a-z0-9_]{3,25})/?(?:[?#].*)?$", re.I)
_KICK = re.compile(r"^(?:www\.)?kick\.com/([a-z0-9_-]{3,25})/?(?:[?#].*)?$", re.I)
_TW_NOT_CHANNELS = {"videos", "directory", "settings", "downloads", "p", "jobs", "search", "subscriptions",
                    "inventory", "wallet", "drops", "turbo", "prime"}
_KICK_NOT_CHANNELS = {"categories", "browse", "following", "search", "video", "videos", "clips", "settings",
                      "dashboard", "terms-of-service", "privacy-policy", "community-guidelines"}


@dataclass
class Link:
    platform: str               # "youtube" | "twitch" | "kick"
    kind: str                   # "video" (YouTube stream or Twitch VOD: the time comes from the platform) | "channel"
    ident: str                  # video id / VOD id / channel name (lower case)
    url: str                    # as posted


def parse_link(url: str) -> Optional[Link]:
    """One URL → what it points at (None for anything that isn't a stream or channel we can look up)."""
    rest = re.sub(r"^https?://", "", (url or "").strip().rstrip(".,!?;:'\""), flags=re.I)
    m = _YT.match(rest)
    if m:
        return Link("youtube", "video", m.group(1), url)
    m = _TW_VOD.match(rest)
    if m:
        return Link("twitch", "video", m.group(1), url)
    m = _TW.match(rest)
    if m and m.group(1).lower() not in _TW_NOT_CHANNELS:
        return Link("twitch", "channel", m.group(1).lower(), url)
    m = _KICK.match(rest)
    if m and m.group(1).lower() not in _KICK_NOT_CHANNELS:
        return Link("kick", "channel", m.group(1).lower(), url)
    return None


def find_links(text: str, limit: int = 4) -> List[Link]:
    """The stream / channel links in a post, in order, each once (at most ``limit``: a post is one
    stream, maybe on a few platforms at once)."""
    out: List[Link] = []
    for raw in _URL.findall(text or ""):
        link = parse_link(raw)
        if link and not any((x.platform, x.ident) == (link.platform, link.ident) for x in out):
            out.append(link)
    return out[:limit]


# ── "when?" ───────────────────────────────────────────────────────────
_DAYS = {"sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}


def parse_when(text: str, now: float, tz: ZoneInfo) -> Optional[float]:
    """What someone typed in "When?" → unix seconds (None when unreadable). Times are the bot's time
    zone (TZ); the answer shows a Discord timestamp, which every reader sees in their own zone, so a
    wrong guess is easy to spot.

      "8pm", "20:30"                  today, or tomorrow when that time has passed
      "sat 8pm", "saturday 8:30 pm"   the next such day (today when it's still ahead)
      "today 9pm", "tonight 9", "tomorrow 7pm"
      "<t:1763600000:F>" or "1763600000"   a Discord timestamp (exact, any time zone)"""
    t = (text or "").strip().lower()
    m = re.fullmatch(r"<t:(\d{9,11})(?::\w)?>|(\d{9,11})", t)
    if m:
        return float(m.group(1) or m.group(2))
    m = re.fullmatch(r"(?:(today|tonight|tomorrow|tmrw?|sun|mon|tue|wed|thu|fri|sat)[a-z]*\.?,?\s*(?:at\s+)?)?"
                     r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?", t)
    if not m:
        return None
    day, h, mins, ampm = m.group(1) or "", int(m.group(2)), int(m.group(3) or 0), m.group(4) or ""
    if mins > 59 or h > 23 or (ampm and not 1 <= h <= 12):
        return None
    if ampm == "p" and h != 12:
        h += 12
    elif ampm == "a" and h == 12:
        h = 0
    elif not ampm and day == "tonight" and h < 12:
        h += 12                         # "tonight 9" = 9 PM
    local = datetime.fromtimestamp(now, tz)
    base = local.date()
    if day.startswith("tom") or day.startswith("tmr"):
        base += timedelta(days=1)
    elif day[:3] in _DAYS:
        base += timedelta(days=(_DAYS[day[:3]] - local.weekday()) % 7)
    at = datetime(base.year, base.month, base.day, h, mins, tzinfo=tz).timestamp()
    if at < now - 1800 and day not in ("today", "tonight"):     # passed (by more than "I'm a bit late"): the next one
        at = (datetime(base.year, base.month, base.day, h, mins, tzinfo=tz) + timedelta(days=7 if day[:3] in _DAYS else 1)).timestamp()
    return at


# ── the calendar's tiles ──────────────────────────────────────────────
def tiles(store: Any, a: float, b: float, now: float, recap: bool) -> List[Tile]:
    """Community streams in [a, b) as calendar tiles (flavrpromo/calendar.py build_week, group "community").
    The same person on several platforms within MERGE_WINDOW = one tile with several badges. Planned
    ones are left out of the recap and once STALE_AFTER past. person_id is the poster's Discord id,
    negative, so it never meets a followed person's id."""
    out: List[Tile] = []
    for r in store.promo_between(a, b):
        kind = {"past": "past", "live": "live"}.get(r["state"], "scheduled")
        if r["state"] == "waiting":
            continue                    # not live yet and no time: nothing to show
        if kind == "scheduled" and (recap or float(r["at"]) < now - STALE_AFTER):
            continue
        pid = -int(r["author_id"]) if str(r.get("author_id") or "").isdigit() else -1_000_000 - int(r["id"])
        url = r.get("url") or ""
        twin = next((t for t in out if t.person_id == pid and t.kind == kind and abs(t.at - float(r["at"])) < MERGE_WINDOW), None)
        if twin:
            if r["platform"] not in twin.platforms:
                twin.platforms.append(r["platform"])
                twin.links[r["platform"]] = url
            twin.thumb = twin.thumb or r.get("thumb") or ""
            twin.end = max(twin.end or 0, float(r["end_at"] or 0)) or twin.end
            continue
        out.append(Tile(kind=kind, name=r.get("name") or "someone", person_id=pid, at=float(r["at"]),
                        end=float(r["end_at"]) if kind == "past" and r.get("end_at") else None,
                        title=r.get("title") or "", game=r.get("game") or "", url=url, thumb=r.get("thumb") or "",
                        avatar=r.get("avatar") or "", platforms=[r["platform"]], links={r["platform"]: url},
                        from_vod=True))         # never a LATE NOTICE: the bot can't see their schedule
    return out


PLATFORM_NAMES = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}


class Promo:
    """One per bot (flavrpromo/__main__.py). ``checkers``: the watcher's platform clients
    (flavrpromo/platforms: Twitch, YouTube, Kick); ``poke``: redraw the calendar posts now."""

    def __init__(self, store: Any, checkers: Dict[str, Any], tz: ZoneInfo, weekly_limit: int = 7,
                 wait_hours: int = 6, poke: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.checkers = checkers
        self.tz = tz
        self.weekly_limit = weekly_limit
        self.wait = wait_hours * 3600.0
        self.poke = poke or (lambda: None)
        self.clock = clock
        self._yt_checked = 0.0

    # ── who may ────────────────────────────────────────────────────────
    def roles(self) -> List[int]:
        return [int(r) for r in (self.store.get(ROLES_KEY) or [])]

    def set_role(self, role_id: int, on: bool) -> None:
        have = [r for r in self.roles() if r != role_id] + ([role_id] if on else [])
        self.store.put(ROLES_KEY, have)

    def may_add(self, member_role_ids: List[int], is_mod: bool, own_post: bool) -> str:
        """"" when this member may add this post, else the reason in plain words."""
        if is_mod:
            return ""
        if not own_post:
            return "You can only add your own posts. A moderator can add anyone's."
        allowed = set(self.roles())
        if not allowed:
            return "Nobody has been allowed yet: a moderator picks the roles with /community roles add."
        if not allowed & set(member_role_ids):
            return "Adding to the community calendar is for members with one of the allowed roles."
        return ""

    def over_limit(self, author_id: str, is_mod: bool) -> bool:
        return not is_mod and self.store.promo_added_since(str(author_id), self.clock() - 7 * 86400) >= self.weekly_limit

    # ── adding ─────────────────────────────────────────────────────────
    async def add(self, links: List[Link], when: Optional[float], *, author_id: str, name: str, avatar: str,
                  added_by: str, post_channel: str = "", post_message: str = "",
                  is_mod: bool = False) -> List[str]:
        """Look each link up and add it. Returns one plain line per link ("Added: ..." or why not),
        for the "only you can see this" answer. Duplicates aren't errors: "already on"."""
        out = []
        for link in links:
            if self.over_limit(author_id, is_mod):
                out.append(f"Not added: you've added {self.weekly_limit} streams in the last 7 days, the most "
                           "allowed. Older ones free up a spot as they pass a week.")
                break
            try:
                line = await self._add_one(link, when, author_id=author_id, name=name, avatar=avatar,
                                           added_by=added_by, post_channel=post_channel, post_message=post_message)
            except Exception as e:                  # a platform hiccup: say so, never crash the command
                log.warning("community link %s failed: %s", link.url, e)
                line = f"{PLATFORM_NAMES[link.platform]}: couldn't ask {PLATFORM_NAMES[link.platform]} just now. Try again in a few minutes."
            out.append(line)
        if any(x.startswith("Added") for x in out):
            self.poke()
        return out

    def _when_words(self, at: float) -> str:
        return f"<t:{int(at)}:F>"

    async def _add_one(self, link: Link, when: Optional[float], **who: Any) -> str:
        now = self.clock()
        plat = PLATFORM_NAMES[link.platform]
        checker = self.checkers.get(link.platform)
        if checker is None or not checker.ready:
            return f"{plat}: this bot has no {plat} key set, so it can't look {plat} links up."
        row: Dict[str, Any] = {"platform": link.platform, "added_at": now, **who}
        if link.platform == "youtube":
            v = (await checker.videos([link.ident])).get(link.ident)
            if not v:
                return "YouTube: that video isn't public, or doesn't exist."
            if v["state"] == "upload":
                return "YouTube: that's a video upload, not a stream. Only streams go on the calendar."
            if not v["at"]:
                return "YouTube: that stream has no start time yet. Add it again once it's scheduled."
            state = {"upcoming": "scheduled"}.get(v["state"], v["state"])
            row.update(item_key=link.ident, channel=v["channel_id"], platform_id=v["channel_id"], state=state,
                       at=v["at"], end_at=v["end"], title=v["title"], url=v["url"], thumb=v["thumb"],
                       name=v["channel"] or who["name"], last_seen=now)
        elif link.platform == "twitch" and link.kind == "video":
            v = await checker.video(link.ident)
            if not v or not v["started_at"]:
                return "Twitch: that VOD isn't public, or doesn't exist."
            if v["type"] != "archive":
                return "Twitch: that's a highlight or upload, not a past broadcast. Post the stream's VOD instead."
            row.update(item_key=f"vod:{link.ident}", channel=v["login"], platform_id=v["user_id"], state="past",
                       at=v["started_at"], end_at=v["ended_at"], title=v["title"], url=v["url"], thumb=v["thumb"],
                       name=v["display"] or who["name"])
        else:
            row.update(await self._channel_now(link, when, now, who["name"]) or {})
            if "state" not in row:
                return f"{plat}: there's no channel called {link.ident}."
        # the same stream added before (another post, a channel link and then its VOD): one row
        twin = (self.store.promo_twin(link.platform, row["channel"], row["at"], MATCH_WINDOW) if row.get("channel")
                else None)
        if twin and twin["state"] != "past" and row["state"] == "past" and twin["platform"] == "twitch":
            self.store.promo_update(twin["id"], **{k: row[k] for k in ("state", "at", "end_at", "title", "url", "thumb")})
            return "Twitch: that stream was already on; it now links this VOD."
        if twin:
            return f"{plat}: already on the community calendar ({self._when_words(twin['at'])})."
        if not self.store.promo_add(**row):
            return f"{plat}: already on the community calendar."
        what = {"scheduled": f"planned {self._when_words(row['at'])}",
                "live": "live now",
                "past": f"streamed {self._when_words(row['at'])}",
                "waiting": f"not live yet. I'll watch for them to go live in the next {int(self.wait // 3600)} hours; "
                           "if you meant a later time, remove it and add it again with a time"}[row["state"]]
        title = f" · {row['title'][:80]}" if row.get("title") else ""
        return f"Added: {row.get('name') or link.ident} on {plat}, {what}{title}."

    async def _channel_now(self, link: Link, when: Optional[float], now: float, name: str) -> Optional[Dict[str, Any]]:
        """A Twitch / Kick channel link: live now, a given time, Twitch's own schedule, else waiting."""
        checker = self.checkers[link.platform]
        base: Dict[str, Any] = {"channel": link.ident, "name": name, "url": f"https://{'twitch.tv' if link.platform == 'twitch' else 'kick.com'}/{link.ident}"}
        if link.platform == "twitch":
            info = (await checker.resolve([link.ident])).get(link.ident)
            if not info:
                return None
            base.update(platform_id=info["platform_id"], name=info.get("display") or name, avatar=info.get("avatar") or "")
            live = (await checker.live([{"platform_id": info["platform_id"]}])).get(info["platform_id"])
        else:
            found = await checker.channels([link.ident])
            if not found:
                return None
            base.update(platform_id=link.ident, name=str(found[0].get("slug") or link.ident))
            live = (await checker.live([{"platform_id": link.ident}])).get(link.ident)
        if live and (when is None or abs(when - (live.get("started_at") or now)) < MATCH_WINDOW):
            at = float(live.get("started_at") or now)
            return {**base, "item_key": f"{link.ident}@{int(at)}", "state": "live", "at": at, "last_seen": now,
                    "title": live.get("title") or "", "game": live.get("game") or "", "thumb": live.get("thumb") or ""}
        if when is not None:
            return {**base, "item_key": f"{link.ident}@{int(when)}", "state": "scheduled", "at": when}
        if link.platform == "twitch":
            soon = [s for s in await checker.schedule(base["platform_id"], 3)
                    if s.get("at") and now - STALE_AFTER < s["at"] < now + 7 * 86400]
            if soon:
                s = soon[0]
                return {**base, "item_key": f"{link.ident}@{int(s['at'])}", "state": "scheduled", "at": float(s["at"]),
                        "title": s.get("title") or "", "game": s.get("game") or "", "thumb": s.get("thumb") or ""}
        return {**base, "item_key": f"{link.ident}@w{int(now)}", "state": "waiting", "at": now, "until": now + self.wait}

    # ── removing ───────────────────────────────────────────────────────
    def remove_post(self, message_id: str, user_id: str, is_mod: bool) -> Tuple[int, int]:
        """The menu's "Remove from community calendar": → (removed, not yours)."""
        gone = blocked = 0
        for r in self.store.promo_for_message(message_id):
            if is_mod or r["author_id"] == str(user_id):
                gone += self.store.promo_remove(r["id"])
            else:
                blocked += 1
        if gone:
            self.poke()
        return gone, blocked

    def remove(self, pid: int, user_id: str, is_mod: bool) -> str:
        """/community remove: "" when removed, else why not."""
        r = self.store.promo_get(pid)
        if not r:
            return f"There's no community stream number {pid}. /community list shows them."
        if not is_mod and r["author_id"] != str(user_id):
            return "That one was added by someone else. A moderator can remove it."
        self.store.promo_remove(pid)
        self.poke()
        return ""

    def post_deleted(self, message_id: str) -> int:
        """A deleted post takes its streams with it (flavrpromo/bot.py on_raw_message_delete)."""
        rows = self.store.promo_for_message(message_id)
        for r in rows:
            self.store.promo_remove(r["id"])
        if rows:
            self.poke()
        return len(rows)

    def listing(self, a: float, b: float) -> List[str]:
        """/community list: one line per stream in [a, b), with the number /community remove takes."""
        icon = {"waiting": "⏳", "scheduled": "🗓️", "live": "🔴", "past": "✅"}
        return [f"`{r['id']}` {icon.get(r['state'], '')} <t:{int(r['at'])}:f> · {PLATFORM_NAMES.get(r['platform'], '')} · "
                f"{r.get('name') or 'someone'}" + (f" · {r['title'][:60]}" if r.get("title") else "")
                + (f" (post by <@{r['author_id']}>)" if r.get("author_id") else "")
                for r in self.store.promo_between(a, b)]

    # ── following each stream ──────────────────────────────────────────
    async def run(self) -> None:
        while True:
            try:
                if await self.tick():
                    self.poke()
            except Exception:
                log.exception("community calendar check failed")
            await asyncio.sleep(CHECK_EVERY)

    async def tick(self) -> bool:
        """One look at every open row; True when something changed (the calendar redraws)."""
        now = self.clock()
        changed = False
        rows = self.store.promo_active()
        for r in rows:
            # waited long enough, or a planned time long gone with no stream: drop it
            if (r["state"] == "waiting" and float(r["until"] or 0) < now) or \
               (r["state"] == "scheduled" and r["platform"] != "youtube" and float(r["at"]) < now - STALE_AFTER):
                self.store.promo_remove(r["id"])
                changed = True
        rows = self.store.promo_active()
        for plat in ("twitch", "kick"):
            checker = self.checkers.get(plat)
            due = [r for r in rows if r["platform"] == plat and r["platform_id"] and
                   (r["state"] in ("waiting", "live") or float(r["at"]) - SOON < now)]
            if not due or checker is None or not checker.ready:
                continue
            live = await checker.live([{"platform_id": pid} for pid in {r["platform_id"] for r in due}])
            for r in due:
                changed |= await self._follow(r, live.get(r["platform_id"]), now)
        yt = [r for r in rows if r["platform"] == "youtube"]
        checker = self.checkers.get("youtube")
        if yt and checker is not None and checker.ready and now - self._yt_checked >= YOUTUBE_EVERY:
            self._yt_checked = now
            found = await checker.videos([r["item_key"] for r in yt])
            for r in yt:
                v = found.get(r["item_key"])
                if not v or v["state"] == "upload" or not v["at"]:
                    self.store.promo_remove(r["id"])       # made private, deleted, or turned into an upload
                    changed = True
                    continue
                state = {"upcoming": "scheduled"}.get(v["state"], v["state"])
                if (state, v["at"], v["end"], v["title"]) != (r["state"], r["at"], r["end_at"], r["title"]):
                    self.store.promo_update(r["id"], state=state, at=v["at"], end_at=v["end"], title=v["title"], last_seen=now)
                    changed = True
        return changed

    async def _follow(self, r: Dict[str, Any], live: Optional[Dict[str, Any]], now: float) -> bool:
        """One Twitch / Kick row against what the platform says now."""
        if live:
            at = float(live.get("started_at") or now)
            if r["state"] == "scheduled" and abs(at - float(r["at"])) > MATCH_WINDOW:
                return False            # live, but not the stream they planned (that one's later)
            fields = {"state": "live", "last_seen": now, "title": live.get("title") or r["title"],
                      "game": live.get("game") or r["game"], "thumb": live.get("thumb") or r["thumb"]}
            if r["state"] != "live":
                fields.update(at=at, item_key=f"{r['channel']}@{int(at)}")
            if not self.store.promo_update(r["id"], **fields):
                self.store.promo_remove(r["id"])      # someone else's post already has this stream
            return r["state"] != "live"
        if r["state"] != "live" or now - float(r["last_seen"] or now) < LIVE_GONE:
            return False
        end = float(r["last_seen"] or now)
        fields = {"state": "past", "end_at": end}
        if r["platform"] == "twitch":
            vods = await self.checkers["twitch"].past_streams(r["platform_id"], float(r["at"]) - 1800, float(r["at"]) + 1800)
            if vods:
                v = min(vods, key=lambda x: abs(x["started_at"] - float(r["at"])))
                fields.update(url=v["url"] or r["url"], thumb=v["thumb"] or r["thumb"], end_at=v["ended_at"] or end)
        else:
            fields["url"] = f"https://kick.com/{r['channel']}/videos"     # no VOD API: the channel's videos page
        self.store.promo_update(r["id"], **fields)
        return True


# ── Discord side: the message menu entries and /community (registered by flavrpromo/bot.py) ──
ADDED_NOTE = "It shows on the community calendar and in the next review (Friday for Monday to Thursday, Monday for the weekend)."


def is_mod(bot: Any, inter: Any) -> bool:
    """A moderator for the community calendar: the owner, Manage Server or Manage Messages. (FlaVR Bot
    keeps the same check for /said in its flavrbot/said.py; this copy came with the split, 2026-11-20.)"""
    perms = getattr(inter.user, "guild_permissions", None)
    return bot.may_manage(inter) or bool(perms and perms.manage_messages)


def register(tree: Any, bot: Any, managers_only: Callable[[Any], Awaitable[bool]]) -> None:
    """Message menu "Add to community calendar" / "Remove from community calendar" and /community.
    ``bot.promo`` is the Promo (set by flavrpromo/__main__.py); answers are "only you can see this"."""
    no_pings = discord.AllowedMentions.none()

    def member_roles(inter: Any) -> List[int]:
        return [r.id for r in getattr(inter.user, "roles", []) or []]

    async def not_ready(inter: Any) -> bool:
        if bot.promo is None:
            await inter.response.send_message("The community calendar is still starting. Try again in a minute.",
                                              ephemeral=True)
            return True
        return False

    async def add_and_answer(inter: Any, links: List[Link], when: Optional[float], message: Any = None) -> None:
        """Look the links up (can take a few seconds, so the answer comes as a follow-up)."""
        if not inter.response.is_done():
            await inter.response.defer(ephemeral=True, thinking=True)
        author = message.author if message is not None else inter.user
        lines = await bot.promo.add(
            links, when, author_id=str(author.id), name=getattr(author, "display_name", "") or str(author),
            avatar=str(author.display_avatar.url) if getattr(author, "display_avatar", None) else "",
            added_by=str(inter.user), post_channel=str(message.channel.id) if message is not None else "",
            post_message=str(message.id) if message is not None else "", is_mod=is_mod(bot, inter))
        added = any(x.startswith("Added") for x in lines)
        await inter.followup.send("\n".join(lines) + (f"\n{ADDED_NOTE}" if added else ""), ephemeral=True,
                                  allowed_mentions=no_pings)
        if added and message is not None:
            try:
                await message.add_reaction("\N{SPIRAL CALENDAR PAD}")     # 🗓 so people see it was picked up
            except discord.HTTPException:
                pass                    # no Add Reactions permission there: the answer above is enough

    class WhenForm(discord.ui.Modal, title="Add to community calendar"):
        """Asked only for a Twitch / Kick channel link: a channel link alone doesn't say when."""
        when = discord.ui.TextInput(label="When? Leave empty if they're live now", required=False, max_length=40,
                                    placeholder="sat 8pm · tomorrow 7:30pm · tonight 9")

        def __init__(self, links: List[Link], message: Any):
            super().__init__()
            self.links, self.message = links, message

        async def on_submit(self, inter: Any) -> None:
            text = str(self.when.value or "").strip()
            at = parse_when(text, time.time(), bot.promo.tz) if text else None
            if text and at is None:
                await inter.response.send_message(f"I couldn't read \"{text}\" as a time. Try \"sat 8pm\", "
                                                  "\"tomorrow 7:30pm\" or \"9pm\".", ephemeral=True)
                return
            await add_and_answer(inter, self.links, at, self.message)

    @tree.context_menu(name="Add to community calendar")
    async def menu_add(inter: discord.Interaction, message: discord.Message):
        if await not_ready(inter):
            return
        why = bot.promo.may_add(member_roles(inter), is_mod(bot, inter), message.author.id == inter.user.id)
        if why:
            await inter.response.send_message(why, ephemeral=True)
            return
        # the post's text and its link previews (a message menu always gets the text, even without
        # the Message Content switch)
        links = find_links(" ".join([message.content or ""] + [e.url or "" for e in message.embeds]))
        if not links:
            await inter.response.send_message("That post has no YouTube, Twitch or Kick stream link.", ephemeral=True)
            return
        if any(x.kind == "channel" for x in links):
            await inter.response.send_modal(WhenForm(links, message))
            return
        await add_and_answer(inter, links, None, message)

    @tree.context_menu(name="Remove from community calendar")
    async def menu_remove(inter: discord.Interaction, message: discord.Message):
        if await not_ready(inter):
            return
        gone, blocked = bot.promo.remove_post(str(message.id), str(inter.user.id), is_mod(bot, inter))
        if gone:
            text = f"Removed {gone} stream{'s' if gone > 1 else ''} from the community calendar."
            try:
                await message.remove_reaction("\N{SPIRAL CALENDAR PAD}", bot.user)
            except (discord.HTTPException, AttributeError):
                pass
        elif blocked:
            text = "Only the person who posted it, or a moderator, can take it off."
        else:
            text = "Nothing from that post is on the community calendar."
        await inter.response.send_message(text, ephemeral=True)

    community = app_commands.Group(name="community", description="The community calendar: streams from members' posts")

    @community.command(name="schedule", description="Put one of your streams on the community calendar")
    @app_commands.describe(link="A YouTube stream, Twitch VOD, or Twitch / Kick channel link",
                           when="For a channel link: when you'll be live (sat 8pm, tomorrow 7pm). Empty = live now")
    async def community_schedule(inter: discord.Interaction, link: str, when: Optional[str] = None):
        if await not_ready(inter):
            return
        why = bot.promo.may_add(member_roles(inter), is_mod(bot, inter), True)
        if why:
            await inter.response.send_message(why, ephemeral=True)
            return
        links = find_links(link if "://" in link else "https://" + link.strip())
        if not links:
            await inter.response.send_message("That isn't a YouTube stream, Twitch or Kick link.", ephemeral=True)
            return
        at = parse_when(when, time.time(), bot.promo.tz) if (when or "").strip() else None
        if (when or "").strip() and at is None:
            await inter.response.send_message(f"I couldn't read \"{when}\" as a time. Try \"sat 8pm\", "
                                              "\"tomorrow 7:30pm\" or \"9pm\".", ephemeral=True)
            return
        await add_and_answer(inter, links, at)

    @community.command(name="list", description="The community streams of a week, with their numbers")
    @app_commands.choices(week=[app_commands.Choice(name="This week", value=0), app_commands.Choice(name="Next week", value=1),
                                app_commands.Choice(name="Last week", value=-1)])
    async def community_list(inter: discord.Interaction, week: Optional[app_commands.Choice[int]] = None):
        if await not_ready(inter):
            return
        from .calendar import week_start
        start = week_start(time.time(), bot.promo.tz) + timedelta(days=7 * (week.value if week else 0))
        lines = bot.promo.listing(start.timestamp(), (start + timedelta(days=7)).timestamp())
        text = "\n".join(lines) if lines else "No community streams that week."
        await inter.response.send_message(text[:1990], ephemeral=True, allowed_mentions=no_pings)

    @community.command(name="remove", description="Take a stream off (yours, or anyone's for moderators)")
    @app_commands.describe(number="Its number from /community list")
    async def community_remove(inter: discord.Interaction, number: int):
        if await not_ready(inter):
            return
        why = bot.promo.remove(number, str(inter.user.id), is_mod(bot, inter))
        await inter.response.send_message(why or "Removed from the community calendar.", ephemeral=True)

    roles = app_commands.Group(name="roles", description="Who may add their own posts (owner or Manage Server)",
                               parent=community)

    @roles.command(name="add", description="Members with this role may add their own posts")
    async def roles_add(inter: discord.Interaction, role: discord.Role):
        if not await managers_only(inter) or await not_ready(inter):
            return
        bot.promo.set_role(role.id, True)
        await inter.response.send_message(f"Members with {role.mention} can now add their own posts.",
                                          ephemeral=True, allowed_mentions=no_pings)

    @roles.command(name="remove", description="Stop letting this role add posts")
    async def roles_remove(inter: discord.Interaction, role: discord.Role):
        if not await managers_only(inter) or await not_ready(inter):
            return
        bot.promo.set_role(role.id, False)
        await inter.response.send_message(f"{role.mention} can no longer add posts (what's on stays on).",
                                          ephemeral=True, allowed_mentions=no_pings)

    @roles.command(name="list", description="The roles that may add their own posts")
    async def roles_list(inter: discord.Interaction):
        if await not_ready(inter):
            return
        have = bot.promo.roles()
        text = ("Members with " + ", ".join(f"<@&{r}>" for r in have) + " can add their own posts. Moderators can "
                "add anyone's.") if have else "No roles yet: only moderators can add. /community roles add picks one."
        await inter.response.send_message(text, ephemeral=True, allowed_mentions=no_pings)

    @community.command(name="report-channel", description="Where the community calendar and week in review go")
    async def community_channel(inter: discord.Interaction, channel: discord.TextChannel):
        if not await managers_only(inter):
            return
        # the same settings /setup calendar-channel group:Community writes (flavrpromo/calendar_post.py reads them)
        bot.store.put(f"calendar_channel.{GROUP}", str(channel.id))
        bot.store.put(f"calendar_post.{GROUP}", {})
        if bot.calendar:
            bot.calendar.poke()
        await inter.response.send_message(f"The community calendar goes to {channel.mention}; the first post comes "
                                          "within a minute, the reviews on Friday and Monday.", ephemeral=True)

    tree.add_command(community)


__all__ = ["GROUP", "Link", "parse_link", "find_links", "parse_when", "tiles", "Promo", "register"]
