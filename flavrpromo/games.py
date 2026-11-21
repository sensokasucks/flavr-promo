"""
Game history: which game a stream is on, the games of one stream in order, and a tag that says what
that game means for this person (owner 2026-11-20, plan doc "FlaVR Bot presenter plan": "help infer if
it's part of a playthrough series, new game, or staple of the channel ... it might help drive
viewership").

Which game:
  * Twitch and Kick say it (the stream's category). With several platforms live, the main
    platform's game wins, else any platform that has one.
  * YouTube has no category, so its title is matched against the games this person (else anyone
    the bot follows) played before: the longest known game name found in the title wins
    ("Valheim w/ friends - day 3" → Valheim). A brand-new game on a YouTube-only stream can't be
    known that way; ``/friend game`` sets it by hand for the stream that's on, and it is remembered.
  * Nothing found = "" (the stream's game stays as it was; an empty answer never ends a game).

Games of one stream (store table ``segments``): ``track`` opens a row when the stream starts and
whenever the game changes, closing the one before; ``finish`` closes the last when the stream ends.
flavrpromo/watcher.py calls both and asks for a card edit (on_change) when the game changes.

Tags (``tag``), worked out once when a game starts, from this person's earlier streams:
  NEW GAME     never streamed it before
  STAPLE       STAPLE_STREAMS or more earlier streams with it, spread over STAPLE_SPAN_DAYS or more
  BACK AGAIN   played before, but not for BACK_AFTER_DAYS
  PART n       otherwise: their n-th stream of it (a playthrough)
Categories that aren't games (Just Chatting, Art, Music ...) get no tag. History includes streams
from before this file existed (sessions.game, imported from FlaVR Bot), so tags are right from day one.

Shown on the go-live card ("Playing: Valheim · 🆕 NEW GAME", "Earlier: Schedule I 1 h 20 min") and
the "was live" card ("Played: Schedule I 1 h 20 min → Valheim 2 h"), flavrpromo/bot.py.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from .store import Store

STAPLE_STREAMS = 6          # earlier streams with the game ...
STAPLE_SPAN_DAYS = 60       # ... spread over at least this many days = a staple of the channel
BACK_AFTER_DAYS = 60        # played before, but not for this long = back again
MIN_MATCH = 4               # shortest game name matched inside a YouTube title (characters)

# Twitch / Kick categories that aren't a game (no tag; they still show as "Playing")
NON_GAMES = {
    "just chatting", "art", "music", "irl", "asmr", "talk shows & podcasts", "science & technology",
    "software and game development", "makers & crafting", "special events", "food & drink",
    "travel & outdoors", "sports", "fitness & health", "politics", "pools, hot tubs, and beaches",
    "beauty & body art", "animals, aquariums, and zoos", "co-working & studying", "dj", "games + demos",
}

TAG_LABEL = {"new": "🆕 NEW GAME", "staple": "⭐ STAPLE", "back": "🔁 BACK AGAIN", "part": "📖 PART {n}"}


def _norm(text: str) -> str:
    """Lower case, letters and digits only, single spaces ("Schedule I: Co-op!" → "schedule i co op")."""
    return " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())


def from_title(title: str, known: List[str]) -> str:
    """The longest known game whose name appears in ``title`` as whole words ("" when none)."""
    t = f" {_norm(title)} "
    best = ""
    for g in known:
        n = _norm(g)
        if len(n) >= MIN_MATCH and f" {n} " in t and len(n) > len(_norm(best)):
            best = g
    return best


def detect(store: Store, person: Dict[str, Any], live_on: Dict[str, Dict[str, Any]], main: str) -> str:
    """The game this person is on right now (see the file's top). ``live_on``: {platform: live info},
    ``main``: the platform the card shows (flavrpromo/watcher.py main_platform)."""
    order = [main] + [p for p in live_on if p != main]
    for p in order:
        g = str((live_on.get(p) or {}).get("game") or "").strip()
        if g:
            return g
    title = str((live_on.get(main) or {}).get("title") or "")
    return from_title(title, store.known_games(person["id"])) or from_title(title, store.known_games())


def tag(store: Store, person_id: int, game: str, at: float, session_id: Optional[int] = None) -> str:
    """The history tag for ``game`` starting at ``at`` (unix s): "new", "staple", "back", "part:<n>"
    or "" (no game / not a game). Streams before ``at`` count, this stream (``session_id``) doesn't."""
    if not game or game.lower() in NON_GAMES:
        return ""
    key = game.lower()
    seen = sorted({r["session_id"]: float(r["at"]) for r in store.game_history(person_id, at, session_id)
                   if (r["game"] or "").lower() == key}.values())
    if not seen:
        return "new"
    if len(seen) >= STAPLE_STREAMS and seen[-1] - seen[0] >= STAPLE_SPAN_DAYS * 86400:
        return "staple"
    if at - seen[-1] >= BACK_AFTER_DAYS * 86400:
        return "back"
    return f"part:{len(seen) + 1}"


def label(t: str) -> str:
    """"part:8" → "📖 PART 8", "new" → "🆕 NEW GAME" ("" stays "")."""
    if t.startswith("part:"):
        return TAG_LABEL["part"].format(n=t.split(":", 1)[1])
    return TAG_LABEL.get(t, "")


def track(store: Store, session_id: int, person_id: int, game: str, at: float) -> bool:
    """Keep the stream's games up to date; True when a new game started (the card should change).
    An empty ``game`` changes nothing."""
    if not game:
        return False
    segs = store.segments(session_id)
    cur = next((s for s in reversed(segs) if s["ended_at"] is None), None)
    if cur and cur["game"].lower() == game.lower():
        return False
    store.segment_close(session_id, at)
    store.segment_add(session_id, person_id, game, at, tag(store, person_id, game, at, session_id))
    return True


def finish(store: Store, session_id: int, at: float) -> None:
    """The stream ended at ``at``: close its last game."""
    store.segment_close(session_id, at)


def length(sec: float) -> str:
    m = int(max(0, sec)) // 60
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def now_playing(store: Store, session_id: Optional[int]) -> Dict[str, Any]:
    """For the live card: {"game", "tag" (label), "earlier": "Schedule I 1 h 20 min · ..."} ({} = no games)."""
    segs = store.segments(session_id) if session_id else []
    if not segs:
        return {}
    cur, before = segs[-1], segs[:-1]
    return {"game": cur["game"], "tag": label(cur["tag"]),
            "earlier": " · ".join(f"{s['game']} {length(float(s['ended_at'] or cur['started_at']) - float(s['started_at']))}"
                                  for s in before)}


def played(store: Store, session_id: Optional[int], ended_at: Optional[float] = None) -> str:
    """For the "was live" card: "Schedule I 1 h 20 min → Valheim 2 h" ("" with fewer than one game)."""
    segs = store.segments(session_id) if session_id else []
    end = float(ended_at or time.time())
    parts = []
    for s in segs:
        t = label(s["tag"])
        parts.append(f"{s['game']}{' (' + t + ')' if t else ''} "
                     f"{length(float(s['ended_at'] or end) - float(s['started_at']))}")
    return " → ".join(parts)


def history(store: Store, person_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """/friend games: this person's games, most streams first: {game, streams, last (unix s)}."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in store.game_history(person_id, time.time() + 1):
        k = (r["game"] or "").lower()
        if not k:
            continue
        row = out.setdefault(k, {"game": r["game"], "streams": set(), "last": 0.0})
        row["streams"].add(r["session_id"])
        row["last"] = max(row["last"], float(r["at"]))
    rows = [{"game": v["game"], "streams": len(v["streams"]), "last": v["last"]} for v in out.values()]
    return sorted(rows, key=lambda r: (-r["streams"], -r["last"]))[:limit]
