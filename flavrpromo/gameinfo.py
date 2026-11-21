"""
Game details: genre, a one-line summary and a store link for the game someone is streaming (plan
doc "FlaVR Bot presenter plan": Steam look-ups for game details; owner 2026-11-21 "start building").

Where they come from: IGDB (api.igdb.com, Twitch's official, documented game database), signed in
with the same TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET the go-live watcher uses (an app token from
flavrpromo/platforms/twitch.py). Steam's store pages have no documented API, so the Steam link
comes from IGDB's list of the game's websites (store.steampowered.com), else IGDB's own page.
  POST https://api.igdb.com/v4/games   search "<name>"; fields name,summary,genres.name,url,websites.url
Polite: one look-up per game, remembered in kv game_info.<name lower case> for KEEP_DAYS (a game
not found is asked again after MISS_DAYS). Without Twitch keys, or for non-games (Just Chatting ...),
nothing is looked up.

Used by: flavrpromo/bot.py (the go-live card's "Playing" line links the game and shows its genres;
the host's new-game line can say the genre), flavrpromo/hosts.py facts (a new game's summary for
KoboldCpp's review lines, flavrpromo/kobold.py). Made by flavrpromo/__main__.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from .games import NON_GAMES

log = logging.getLogger("flavrpromo.gameinfo")

IGDB_URL = "https://api.igdb.com/v4/games"
KEEP_DAYS = 30              # a found game is looked up again after this long
MISS_DAYS = 7               # a game IGDB didn't know is asked again after this long
SUMMARY_MAX = 200           # characters of the summary kept (a sentence or two)


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


def shape(r: Dict[str, Any]) -> Dict[str, Any]:
    """An IGDB game as kept in kv: name, genres (list), summary (short), link (Steam, else IGDB)."""
    sites = [str(w.get("url") or "") for w in r.get("websites") or [] if isinstance(w, dict)]
    steam = next((u for u in sites if "store.steampowered.com/app/" in u), "")
    summary = " ".join(str(r.get("summary") or "").split())
    if len(summary) > SUMMARY_MAX:
        summary = summary[:SUMMARY_MAX].rsplit(" ", 1)[0] + "…"
    return {"name": str(r.get("name") or ""), "genres": [str(g.get("name") or "") for g in r.get("genres") or []
                                                        if isinstance(g, dict) and g.get("name")][:3],
            "summary": summary, "steam": steam, "link": steam or str(r.get("url") or "")}


def genre_word(info: Dict[str, Any]) -> str:
    """The first genre in lower case for a host line ("role-playing (rpg)" → "role-playing")."""
    g = (info.get("genres") or [""])[0]
    return g.split("(")[0].strip().lower()


class GameInfo:
    """Look-ups through IGDB with the Twitch checker's app token (``twitch``: platforms/twitch.py Twitch)."""

    def __init__(self, store: Any, twitch: Any):
        self.store = store
        self.twitch = twitch

    async def lookup(self, game: str) -> Dict[str, Any]:
        """``game``'s details, from kv when fresh, else IGDB ({} when unknown or IGDB can't be asked)."""
        game = (game or "").strip()
        if not game or game.lower() in NON_GAMES or not getattr(self.twitch, "ready", False):
            return {}
        row = self.store.get(_key(game)) or {}
        age = time.time() - float(row.get("at") or 0)
        if row and age < (KEEP_DAYS if row.get("name") else MISS_DAYS) * 86400:
            return row if row.get("name") else {}
        try:
            token = await self.twitch._app_token()
            body = (f'search "{game.replace(chr(34), "")}"; fields name,summary,genres.name,url,websites.url; '
                    f"limit 5;")
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
