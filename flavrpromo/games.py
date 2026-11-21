"""
Game history: which game a stream is on, the games of one stream in order, and a tag that says what
that game means for this person (owner 2026-11-20, plan doc "FlaVR Bot presenter plan": "help infer if
it's part of a playthrough series, new game, or staple of the channel ... it might help drive
viewership").

Which game:
  * Twitch and Kick say it (the stream's category). With several platforms live, the main
    platform's game wins, else any platform that has one.
  * YouTube has no category, so its title is used (owner 2026-11-21, "game detection for YouTube"),
    in this order (``detect_how`` says which one answered):
      fix      a title the owner set by hand before (``/friend game`` remembers the stream's title
               → game, kv title_games.<person id>): the same title again means the same game
      words    the person's own title words for a game (``/friend game words:``, kv
               game_words.<person id>: "cooking" → Schedule I)
      known    the games this person (else anyone the bot follows) played before: the longest known
               game name found in the title wins ("Valheim w/ friends - day 3" → Valheim)
      igdb     a brand-new game: the title's parts ("SCHEDULE I | first time!" → "schedule i") looked
               up on IGDB in the background (flavrpromo/gameinfo.py ``guess``, asked once per title,
               kv title_guess.<title>); a part that IS a game's name (or starts with a long one) counts
      similar  none of those, but an earlier stream of theirs in the last SIMILAR_DAYS had nearly the
               same title (SIMILAR share of the words): its game (a series with a fixed title)
    flavrpromo/watcher.py asks for the IGDB guess when nothing better than "similar" answered.
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
from typing import Any, Dict, List, Optional, Tuple

from .store import Store

STAPLE_STREAMS = 6          # earlier streams with the game ...
STAPLE_SPAN_DAYS = 60       # ... spread over at least this many days = a staple of the channel
BACK_AFTER_DAYS = 60        # played before, but not for this long = back again
MIN_MATCH = 4               # shortest game name matched inside a YouTube title (characters)
SIMILAR = 0.6               # an earlier title sharing this much of its words (Jaccard) = the same series
SIMILAR_DAYS = 60           # how far back "similar" looks (days)
KEEP_FIXES = 200            # titles remembered per person (kv title_games.<id>; oldest dropped)
# words that don't name a game on their own: a title part made only of these is never looked up
FILLER = set("""a an the and or with w ft feat x vs of in on at to for my our your is it its this that be
stream streaming live chill chilling cozy comfy late night morning day days part ep episode eps first time
lets let s play playing plays playthrough blind new game games gaming chat chatting collab friends friend
together vod vtuber vtubers en jp id ttv yt subathon marathon birthday special announcement update
finale final finally more again back return returns continue continued continues run runs attempt try
trying im i m we re are ok okay no yes hi hello hey come join us sub subs sunday monday tuesday wednesday
thursday friday saturday weekend tonight today dev devlog test testing discord socials merch kofi ko fi
patreon tiktok twitter youtube twitch kick members membership throne tips donate shorts clips""".split())

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
    return detect_how(store, person, live_on, main)[0]


def detect_how(store: Store, person: Dict[str, Any], live_on: Dict[str, Dict[str, Any]], main: str,
               now: Optional[float] = None) -> Tuple[str, str]:
    """(game, how) with how one of "platform", "fix", "words", "known", "igdb", "similar" or ""
    (nothing). flavrpromo/watcher.py starts an IGDB guess when how is "" or "similar"."""
    order = [main] + [p for p in live_on if p != main]
    for p in order:
        g = str((live_on.get(p) or {}).get("game") or "").strip()
        if g:
            return g, "platform"
    title = str((live_on.get(main) or {}).get("title") or "")
    if not _norm(title):
        return "", ""
    pid = person["id"]
    g = (store.get(f"title_games.{pid}") or {}).get(_norm(title))
    if g:
        return g, "fix"
    g = from_words(title, store.get(f"game_words.{pid}") or {})
    if g:
        return g, "words"
    g = from_title(title, store.known_games(pid)) or from_title(title, store.known_games())
    if g:
        return g, "known"
    g = str((store.get(guess_key(title)) or {}).get("game") or "")
    if g:
        return g, "igdb"
    g = similar(store, pid, title, now if now is not None else time.time())
    return (g, "similar") if g else ("", "")


def from_words(title: str, words: Dict[str, str]) -> str:
    """The game for the longest of the person's own words found in ``title`` (whole words; "" = none)."""
    t = f" {_norm(title)} "
    hits = [w for w in words if w and f" {w} " in t]
    return words[max(hits, key=len)] if hits else ""


def guess_key(title: str) -> str:
    """kv key of a title's IGDB guess (flavrpromo/gameinfo.py ``guess`` writes it)."""
    return f"title_guess.{_norm(title)[:200]}"


def parts(title: str) -> List[str]:
    """A title's parts that could be a game's name, for the IGDB guess: split at | - : [ ] ( ) ! ? /
    • ~ # and dashes, normalized, filler-only parts left out, at most 4 ("SCHEDULE I | first time!" →
    ["schedule i"])."""
    out: List[str] = []
    title = re.sub(r"!\w+", " ", title or "")        # chat commands (!discord !socials) aren't games
    for piece in re.split(r"[|\[\]():!?/•~#—–]| - |\bw/", title or ""):
        n = _norm(piece)
        words = n.split()
        if len(n) < MIN_MATCH or not words or all(w in FILLER or w.isdigit() for w in words) or n in NON_GAMES:
            continue
        if n not in out:
            out.append(n)
    return out[:4]


def names_part(name: str, part: str) -> bool:
    """Does an IGDB game ``name`` fit a title ``part``? The whole part, or the part starting / ending
    with the name when everything else in it is filler ("minecraft with chat" → Minecraft;
    "building a longhouse with chat" is not the game "Building")."""
    n, p = _norm(name), _norm(part)
    if not n or len(n) < MIN_MATCH:
        return False
    if n == p:
        return True
    rest = p[len(n):] if p.startswith(n + " ") else p[:-len(n)] if p.endswith(" " + n) else None
    return rest is not None and all(w in FILLER or w.isdigit() for w in rest.split())


def similar(store: Store, person_id: int, title: str, now: float) -> str:
    """The game of this person's latest earlier stream with nearly the same title ("" = none)."""
    words = {w for w in _norm(title).split() if not w.isdigit()}
    if len(words) < 2:
        return ""
    rows = [r for r in store.sessions_between(now - SIMILAR_DAYS * 86400, now)
            if r["person_id"] == person_id and r.get("game") and r.get("ended_at") is not None]
    for r in reversed(rows):
        other = {w for w in _norm(r.get("title") or "").split() if not w.isdigit()}
        if other and len(words & other) / len(words | other) >= SIMILAR:
            return str(r["game"])
    return ""


def remember_fix(store: Store, person_id: int, title: str, game: str) -> None:
    """/friend game: this title means this game from now on (the newest KEEP_FIXES titles kept)."""
    key = _norm(title)
    if not key:
        return
    fixes = dict(store.get(f"title_games.{person_id}") or {})
    fixes.pop(key, None)
    fixes[key] = game
    store.put(f"title_games.{person_id}", dict(list(fixes.items())[-KEEP_FIXES:]))


def set_words(store: Store, person_id: int, words: str, game: str) -> str:
    """/friend game words: — their own word(s) for a game ("" game = forget them). Returns the words
    as kept (normalized), "" when too short."""
    w = _norm(words)
    if len(w) < 3:
        return ""
    kept = dict(store.get(f"game_words.{person_id}") or {})
    if game:
        kept[w] = game
    else:
        kept.pop(w, None)
    store.put(f"game_words.{person_id}", kept)
    return w


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
