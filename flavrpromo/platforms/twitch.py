"""
Twitch for the go-live watcher: Helix with an app sign-in (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET
from dev.twitch.tv → Your Console → Register Your Application; no user sign-in needed).

Calls (all documented Helix endpoints):
  POST id.twitch.tv/oauth2/token            client_credentials → app token (about 60 days; renewed on 401)
  GET  helix/users?login=a&login=b          up to 100 per call: id, display name, picture
  GET  helix/streams?user_id=..&type=live   up to 100 per call: who is live, title, game, viewers, start
  GET  helix/schedule?broadcaster_id=       one person's upcoming segments (/schedule, the calendar
                                            every 6 h: flavrpromo/watcher.py refresh_schedules)
  GET  helix/games?id=a&id=b                box art of the scheduled games (calendar tiles)
  GET  helix/videos?user_id=&type=archive   the newest VOD after a stream ends
  GET  helix/videos?id=                     one VOD a member posted (community calendar, flavrpromo/promo.py)
  GET  helix/videos?user_id=                uploads and highlights for the reviews (every 6 h per person)

Rate: Helix allows 800 points a minute for an app; the watcher uses one streams call per 100
people every TWITCH_EVERY_SEC (default 2 minutes).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from . import UA, Live

log = logging.getLogger("flavrpromo.twitch")
HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


def iso_ts(s: str) -> Optional[float]:
    """"2026-11-17T19:00:00Z" → unix seconds (None when empty or unreadable)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def duration_sec(s: str) -> float:
    """Helix video duration "3h2m1s" / "45m" / "12s" → seconds (0 when unreadable)."""
    total = 0.0
    for n, unit in re.findall(r"(\d+)([hms])", s or ""):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def chunks(items: List[Any], n: int) -> List[List[Any]]:
    return [items[i:i + n] for i in range(0, len(items), n)]


class Twitch:
    platform = "twitch"

    def __init__(self, http: aiohttp.ClientSession, client_id: str, client_secret: str):
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._token_until = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _app_token(self) -> str:
        if self._token and time.time() < self._token_until - 300:
            return self._token
        async with self.http.post(TOKEN_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                                   "grant_type": "client_credentials"}) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(f"Twitch sign-in refused (HTTP {r.status}): check TWITCH_CLIENT_ID / SECRET")
        self._token = str(data.get("access_token") or "")
        self._token_until = time.time() + float(data.get("expires_in") or 3600)
        return self._token

    async def _get(self, path: str, params: List[tuple]) -> Dict[str, Any]:
        for attempt in (1, 2):
            token = await self._app_token()
            async with self.http.get(HELIX + path, params=params, headers={
                    "Client-Id": self.client_id, "Authorization": f"Bearer {token}", "User-Agent": UA}) as r:
                if r.status == 401 and attempt == 1:
                    self._token = ""
                    continue
                if r.status != 200:
                    raise RuntimeError(f"Twitch {path} answered HTTP {r.status}")
                return await r.json(content_type=None)
        return {}

    async def resolve(self, handles: List[str]) -> Dict[str, Optional[Dict[str, str]]]:
        out: Dict[str, Optional[Dict[str, str]]] = {h: None for h in handles}
        for part in chunks([h.lower().lstrip("@") for h in handles], 100):
            data = await self._get("/users", [("login", h) for h in part])
            for u in data.get("data") or []:
                for h in handles:
                    if h.lower().lstrip("@") == str(u.get("login") or "").lower():
                        out[h] = {"platform_id": str(u.get("id") or ""), "display": str(u.get("display_name") or ""),
                                  "avatar": str(u.get("profile_image_url") or "")}
        return out

    async def live(self, accounts: List[Dict[str, Any]]) -> Dict[str, Live]:
        ids = [a["platform_id"] for a in accounts if a.get("platform_id")]
        out: Dict[str, Live] = {}
        for part in chunks(ids, 100):
            data = await self._get("/streams", [("type", "live"), ("first", "100")] + [("user_id", i) for i in part])
            for s in data.get("data") or []:
                login = str(s.get("user_login") or "")
                out[str(s.get("user_id"))] = {
                    "title": str(s.get("title") or ""), "game": str(s.get("game_name") or ""),
                    "viewers": int(s.get("viewer_count") or 0), "started_at": iso_ts(str(s.get("started_at") or "")),
                    "url": f"https://twitch.tv/{login}",
                    "thumb": str(s.get("thumbnail_url") or "").replace("{width}", "640").replace("{height}", "360")
                    + f"?t={int(time.time() // 300)}",      # Twitch caches the picture; a new one every 5 min
                }
        return out

    async def schedule(self, platform_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Upcoming schedule segments (Twitch answers 404 when the channel has no schedule).

        Each: {key (segment id; a repeating slot's id differs per week), at, title, game,
        thumb (the game's box art, "" when no category), platform}."""
        try:
            data = await self._get("/schedule", [("broadcaster_id", platform_id), ("first", str(limit))])
        except RuntimeError:
            return []
        segs = [s for s in ((data.get("data") or {}).get("segments")) or [] if not s.get("canceled_until")]
        art = await self.box_art([str((s.get("category") or {}).get("id") or "") for s in segs])
        return [{"key": str(s.get("id") or ""), "title": str(s.get("title") or ""),
                 "at": iso_ts(str(s.get("start_time") or "")),
                 "game": str((s.get("category") or {}).get("name") or ""),
                 "thumb": art.get(str((s.get("category") or {}).get("id") or ""), ""), "platform": "twitch"}
                for s in segs]

    async def box_art(self, game_ids: List[str]) -> Dict[str, str]:
        """{game id: box art URL at 285 x 380} for the calendar's scheduled tiles."""
        ids = sorted({i for i in game_ids if i})
        out: Dict[str, str] = {}
        for part in chunks(ids, 100):
            try:
                data = await self._get("/games", [("id", i) for i in part])
            except RuntimeError:
                continue
            for g in data.get("data") or []:
                out[str(g.get("id"))] = str(g.get("box_art_url") or "").replace("{width}", "285").replace("{height}", "380")
        return out

    async def last_vod(self, platform_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = await self._get("/videos", [("user_id", platform_id), ("type", "archive"), ("first", "1")])
        except RuntimeError:
            return None
        rows = data.get("data") or []
        if not rows:
            return None
        v = rows[0]
        return {"url": str(v.get("url") or ""), "title": str(v.get("title") or ""),
                "created_at": iso_ts(str(v.get("created_at") or "")),
                "thumb": str(v.get("thumbnail_url") or "").replace("%{width}", "640").replace("%{height}", "360")}

    async def past_streams(self, platform_id: str, since: float, until: float) -> List[Dict[str, Any]]:
        """Finished streams that started in [since, until), from the channel's past broadcasts
        (Helix /videos type=archive, 1 call of up to 100). Used by Watcher.backfill to fill weeks
        the bot wasn't watching. Twitch deletes these after 7 days (60 for partners, Turbo, Prime),
        so older weeks can come back partly empty. → [{started_at, ended_at, title, url, thumb}]"""
        data = await self._get("/videos", [("user_id", platform_id), ("type", "archive"), ("first", "100")])
        out = []
        for v in data.get("data") or []:
            start = iso_ts(str(v.get("created_at") or ""))
            length = duration_sec(str(v.get("duration") or ""))
            if start is None or not (since <= start < until) or length <= 0:
                continue
            thumb = str(v.get("thumbnail_url") or "")
            out.append({"started_at": start, "ended_at": start + length, "title": str(v.get("title") or ""),
                        "url": str(v.get("url") or ""),
                        # a VOD still being made has a placeholder picture with no size in it
                        "thumb": thumb.replace("%{width}", "640").replace("%{height}", "360") if "%{width}" in thumb else ""})
        return out

    async def video(self, video_id: str) -> Optional[Dict[str, Any]]:
        """One VOD by its id (twitch.tv/videos/<id>), for a community post (flavrpromo/promo.py). Helix
        /videos?id=, 1 call. → {type ("archive" = a past broadcast), started_at, ended_at, title, url,
        thumb, user_id, login, display} or None when Twitch doesn't know it (deleted, private)."""
        try:
            data = await self._get("/videos", [("id", video_id)])
        except RuntimeError:
            return None
        rows = data.get("data") or []
        if not rows:
            return None
        v = rows[0]
        start = iso_ts(str(v.get("created_at") or ""))
        thumb = str(v.get("thumbnail_url") or "")
        return {"type": str(v.get("type") or ""), "started_at": start,
                "ended_at": (start or 0) + duration_sec(str(v.get("duration") or "")),
                "title": str(v.get("title") or ""), "url": str(v.get("url") or ""),
                "thumb": thumb.replace("%{width}", "640").replace("%{height}", "360") if "%{width}" in thumb else "",
                "user_id": str(v.get("user_id") or ""), "login": str(v.get("user_login") or ""),
                "display": str(v.get("user_name") or "")}

    async def recent_uploads(self, platform_id: str, since: float) -> List[Dict[str, Any]]:
        """Uploads and highlights (not past broadcasts) published since ``since``, for the reviews'
        "Also this week" list. Helix /videos?user_id= (all types, newest 20), 1 call; flavrpromo/watcher.py
        asks once per refresh_schedules round. → [{video_id, kind ("video" / "highlight"), at, title,
        url, thumb, length}]"""
        data = await self._get("/videos", [("user_id", platform_id), ("first", "20")])
        out = []
        for v in data.get("data") or []:
            kind = {"upload": "video", "highlight": "highlight"}.get(str(v.get("type") or ""))
            at = iso_ts(str(v.get("published_at") or v.get("created_at") or ""))
            if not kind or not at or at < since:
                continue
            thumb = str(v.get("thumbnail_url") or "")
            out.append({"video_id": str(v.get("id") or ""), "kind": kind, "at": at, "title": str(v.get("title") or ""),
                        "url": str(v.get("url") or ""), "length": duration_sec(str(v.get("duration") or "")),
                        "thumb": thumb.replace("%{width}", "640").replace("%{height}", "360") if "%{width}" in thumb else ""})
        return out
