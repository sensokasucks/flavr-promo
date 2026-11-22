"""
Game details: genre, a one-line summary and a store link for the game someone is streaming (plan
doc "FlaVR Bot presenter plan": Steam look-ups for game details; owner 2026-11-21 "start building").

Where they come from: IGDB (api.igdb.com, Twitch's official, documented game database), signed in
with the same TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET the go-live watcher uses (an app token from
flavrpromo/platforms/twitch.py). Steam's store pages have no documented API, so the Steam link
comes from IGDB's list of the game's websites (store.steampowered.com), else IGDB's own page.
  POST https://api.igdb.com/v4/games   search "<name>"; fields <FIELDS>
Polite: one look-up per game, remembered in kv game_info.<name lower case> for KEEP_DAYS (a game
not found is asked again after MISS_DAYS). Without Twitch keys, or for non-games (Just Chatting ...),
nothing is looked up.

What is kept (``shape``): name, genres, a short summary (the cards), the link, and for the hosts' game
talk (owner 2026-11-22: "a good way to get the host to talk a little about the game") a longer text
``about``, themes, game modes, the release year and who made it. A row kept before those existed
(no "v") is asked for once more the next time it is looked up.

The owner's own search (owner 2026-11-22: "if it can't detect the game automatically, can it let me
select and/or search for it?"): ``search`` lists IGDB's matches for the tall picture builder's game
picker and ``keep`` remembers the picked one (flavrpromo/tall_page.py).

Also guesses the game of a YouTube stream from its title (``guess``, owner 2026-11-21): the title's
parts are searched on IGDB and a part that is a game's name counts (flavrpromo/games.py).

Used by: flavrpromo/tall_page.py (the game picker) and flavrpromo/recipes.py (the facts for a remark),
through poster.game_info; flavrpromo/watcher.py (``guess``, through its guess_game hook), flavrpromo/bot.py (the go-live card's "Playing" line links the game and shows its genres;
the host's new-game line can say the genre), flavrpromo/hosts.py facts (a new game's summary for
KoboldCpp's review lines, flavrpromo/kobold.py). Made by flavrpromo/__main__.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import games
from .games import NON_GAMES

log = logging.getLogger("flavrpromo.gameinfo")

IGDB_URL = "https://api.igdb.com/v4/games"
KEEP_DAYS = 30              # a found game is looked up again after this long
MISS_DAYS = 7               # a game IGDB didn't know is asked again after this long
RETRY_GUESS = 15 * 60.0     # a title whose IGDB guess failed (IGDB unreachable) is tried again after (s)
SUMMARY_MAX = 200           # characters of the summary kept (a sentence or two)
ABOUT_MAX = 600             # characters of the longer text kept for the hosts' game talk
DETAIL = 2                  # version of a kept row; a found row with less is asked for again (2 = about, themes ...)
SEARCH_MAX = 8              # games listed for one search of the owner's
# what IGDB is asked for (its documented field names); ``shape`` reads them
FIELDS = ("name,summary,storyline,genres.name,themes.name,game_modes.name,first_release_date,"
          "involved_companies.company.name,involved_companies.developer,url,websites.url")


def _key(game: str) -> str:
    return f"game_info.{game.strip().lower()}"


def cached(store: Any, game: str) -> Dict[str, Any]:
    """What's remembered about ``game`` ({} = nothing, or IGDB didn't know it)."""
    if not game:
        return {}
    row = store.get(_key(game)) or {}
    return row if row.get("name") else {}


def best(results: list, game: str) -> Optional[Dict[str, Any]]:
    """The IGDB result that is ``game``: the exact name (any case) first, else the first one."""
    if not results:
        return None
    want = game.strip().lower()
    return next((r for r in results if str(r.get("name") or "").strip().lower() == want), results[0])


def _cut(text: Any, longest: int) -> str:
    """``text`` on one line, cut at a word with "…" when longer than ``longest`` characters."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= longest else text[:longest].rsplit(" ", 1)[0] + "…"


def _names(rows: Any, most: int) -> List[str]:
    """The names of an IGDB list field ([{"name": ...}, ...]), at most ``most``."""
    return [str(g["name"]) for g in rows or [] if isinstance(g, dict) and g.get("name")][:most]


def shape(r: Dict[str, Any]) -> Dict[str, Any]:
    """An IGDB game as kept in kv: name, genres (list), summary (short), link (Steam, else IGDB), and for
    the hosts' game talk: about (the summary at more length, else the storyline), themes, modes, year
    (first release, "" when unknown), maker (the developer). "v" = DETAIL."""
    sites = [str(w.get("url") or "") for w in r.get("websites") or [] if isinstance(w, dict)]
    steam = next((u for u in sites if "store.steampowered.com/app/" in u), "")
    try:
        year = str(datetime.fromtimestamp(float(r["first_release_date"]), timezone.utc).year)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        year = ""
    makers = [c for c in r.get("involved_companies") or [] if isinstance(c, dict) and isinstance(c.get("company"), dict)]
    maker = next((str(c["company"].get("name") or "") for c in sorted(makers, key=lambda c: not c.get("developer"))), "")
    return {"name": str(r.get("name") or ""), "genres": _names(r.get("genres"), 3),
            "summary": _cut(r.get("summary"), SUMMARY_MAX), "steam": steam, "link": steam or str(r.get("url") or ""),
            "about": _cut(r.get("summary") or r.get("storyline"), ABOUT_MAX), "themes": _names(r.get("themes"), 4),
            "modes": _names(r.get("game_modes"), 3), "year": year, "maker": maker, "v": DETAIL}


def talk(info: Dict[str, Any]) -> str:
    """What is known about a game as a sentence for KoboldCpp's game talk (flavrpromo/recipes.py): genres,
    themes, modes, year, maker and the longer text ("" = nothing known)."""
    if not info.get("name"):
        return ""
    bits = [f"genres: {', '.join(info['genres'])}" if info.get("genres") else "",
            f"themes: {', '.join(info['themes'])}" if info.get("themes") else "",
            f"modes: {', '.join(info['modes'])}" if info.get("modes") else "",
            f"released in {info['year']}" if info.get("year") else "",
            f"made by {info['maker']}" if info.get("maker") else ""]
    head = "; ".join(b for b in bits if b)
    text = info.get("about") or info.get("summary") or ""
    if not head and not text:
        return ""
    return f"About the game {info['name']}" + (f" ({head})" if head else "") + (f": {text}" if text else "")


def genre_word(info: Dict[str, Any]) -> str:
    """The first genre in lower case for a host line ("role-playing (rpg)" → "role-playing")."""
    g = (info.get("genres") or [""])[0]
    return g.split("(")[0].strip().lower()


class GameInfo:
    """Look-ups through IGDB with the Twitch checker's app token (``twitch``: platforms/twitch.py Twitch)."""

    def __init__(self, store: Any, twitch: Any):
        self.store = store
        self.twitch = twitch
        self._tried: Dict[str, float] = {}         # title guess key → when IGDB last failed on it

    @property
    def ready(self) -> bool:
        """Can IGDB be asked at all (the Twitch keys are set)? The game picker hides its search without."""
        return bool(getattr(self.twitch, "ready", False))

    async def lookup(self, game: str) -> Dict[str, Any]:
        """``game``'s details, from kv when fresh, else IGDB ({} when unknown or IGDB can't be asked)."""
        game = (game or "").strip()
        if not game or game.lower() in NON_GAMES or not getattr(self.twitch, "ready", False):
            return {}
        row = self.store.get(_key(game)) or {}
        age = time.time() - float(row.get("at") or 0)
        old = bool(row.get("name")) and int(row.get("v") or 0) < DETAIL      # kept before the game-talk details
        if row and not old and age < (KEEP_DAYS if row.get("name") else MISS_DAYS) * 86400:
            return row if row.get("name") else {}
        try:
            token = await self.twitch._app_token()
            body = f'search "{game.replace(chr(34), "")}"; fields {FIELDS}; limit 5;'
            async with self.twitch.http.post(IGDB_URL, data=body, headers={
                    "Client-ID": self.twitch.client_id, "Authorization": f"Bearer {token}",
                    "Accept": "application/json"}) as r:
                if r.status != 200:
                    log.info("IGDB answered HTTP %s for %s", r.status, game)
                    return cached(self.store, game)
                results = await r.json(content_type=None)
        except Exception as e:
            log.info("IGDB look-up for %s failed: %s", game, e)
            return cached(self.store, game)
        hit = best(results if isinstance(results, list) else [], game)
        row = {**shape(hit), "at": time.time()} if hit else {"at": time.time()}
        self.store.put(_key(game), row)
        return row if row.get("name") else {}

    async def _search(self, text: str, limit: int = 5) -> Optional[list]:
        """IGDB games for a search (None = IGDB couldn't be asked)."""
        try:
            token = await self.twitch._app_token()
            body = f'search "{text.replace(chr(34), "")}"; fields {FIELDS}; limit {limit};'
            async with self.twitch.http.post(IGDB_URL, data=body, headers={
                    "Client-ID": self.twitch.client_id, "Authorization": f"Bearer {token}",
                    "Accept": "application/json"}) as r:
                if r.status != 200:
                    log.info("IGDB answered HTTP %s for %s", r.status, text)
                    return None
                got = await r.json(content_type=None)
                return got if isinstance(got, list) else []
        except Exception as e:
            log.info("IGDB search for %s failed: %s", text, e)
            return None

    async def search(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """The owner's own search (the tall picture builder's game picker): IGDB's games for ``text`` as
        ``shape`` rows, the best match first, at most SEARCH_MAX. None = IGDB couldn't be asked (no
        Twitch keys, or it didn't answer); [] = it knows no such game. One request."""
        text = " ".join((text or "").split())[:100]
        if not self.ready:
            return None
        if not text:
            return []
        got = await self._search(text, SEARCH_MAX)
        if got is None:
            return None
        out: List[Dict[str, Any]] = []
        for r in got:
            row = shape(r) if isinstance(r, dict) else {}
            if row.get("name") and row["name"].lower() not in {x["name"].lower() for x in out}:
                out.append(row)
        return out

    def keep(self, info: Dict[str, Any]) -> None:
        """Remember a game the owner picked from ``search`` (kv game_info.<name>), so its details show at
        once and ``lookup`` doesn't ask again for KEEP_DAYS."""
        if info.get("name"):
            self.store.put(_key(info["name"]), {**info, "at": time.time()})

    async def guess(self, title: str) -> str:
        """The game a YouTube title names, from IGDB (flavrpromo/games.py ``parts`` / ``names_part``);
        asked once per title (kv title_guess.<title>, "" = none found; again after MISS_DAYS when IGDB
        couldn't be reached). Called in the background by flavrpromo/watcher.py; the next watcher
        round picks the answer up (games.detect_how "igdb"). The found game's details are kept like
        ``lookup``'s, so the card can show them at once."""
        if not getattr(self.twitch, "ready", False):
            return ""
        key = games.guess_key(title)
        if time.time() - self._tried.get(key, 0) < RETRY_GUESS:
            return ""                               # IGDB failed on this title a moment ago
        row = self.store.get(key) or {}
        if row and (row.get("game") or time.time() - float(row.get("at") or 0) < MISS_DAYS * 86400):
            return str(row.get("game") or "")
        found = ""
        for part in games.parts(title):
            results = await self._search(part)
            if results is None:
                self._tried[key] = time.time()      # IGDB unreachable: try again after RETRY_GUESS
                return ""
            hit = next((r for r in results if games.names_part(str(r.get("name") or ""), part)), None)
            if hit:
                found = str(hit["name"]).strip()
                self.store.put(_key(found), {**shape(hit), "at": time.time()})
                break
        self.store.put(key, {"game": found, "at": time.time()})
        if found:
            log.info("YouTube title %r: guessed %s from IGDB", title[:80], found)
        return found
