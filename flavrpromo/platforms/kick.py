"""
Kick for the go-live watcher: Kick's public API with an app sign-in (KICK_CLIENT_ID /
KICK_CLIENT_SECRET from kick.com → Settings → Developer → Create app; no user sign-in needed).

  POST id.kick.com/oauth/token                       client_credentials → app token
  GET  api.kick.com/public/v1/channels?slug=a&slug=b up to 50 per call: live or not, title,
                                                     category, viewers, start time, thumbnail

Kick has no schedule or VOD API, so Kick streams show on /live but not on /schedule. The community
calendar (flavrpromo/promo.py) uses ``channels`` too, and links a finished Kick stream to the
channel's videos page (kick.com/<name>/videos, a plain link, no API call).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from . import UA, Live
from .twitch import chunks, iso_ts

log = logging.getLogger("flavrpromo.kick")
TOKEN_URL = "https://id.kick.com/oauth/token"
API = "https://api.kick.com/public/v1"


class Kick:
    platform = "kick"

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
                raise RuntimeError(f"Kick sign-in refused (HTTP {r.status}): check KICK_CLIENT_ID / SECRET")
        self._token = str(data.get("access_token") or "")
        self._token_until = time.time() + float(data.get("expires_in") or 3600)
        return self._token

    async def channels(self, slugs: List[str]) -> List[Dict[str, Any]]:
        out = []
        for part in chunks(slugs, 50):
            for attempt in (1, 2):
                token = await self._app_token()
                async with self.http.get(API + "/channels", params=[("slug", s) for s in part],
                                         headers={"Authorization": f"Bearer {token}", "User-Agent": UA}) as r:
                    if r.status == 401 and attempt == 1:
                        self._token = ""
                        continue
                    if r.status != 200:
                        raise RuntimeError(f"Kick channels answered HTTP {r.status}")
                    out.extend((await r.json(content_type=None)).get("data") or [])
                    break
        return out

    async def resolve(self, handles: List[str]) -> Dict[str, Optional[Dict[str, str]]]:
        found = {str(c.get("slug") or "").lower(): c for c in await self.channels([h.lower().lstrip("@") for h in handles])}
        out: Dict[str, Optional[Dict[str, str]]] = {}
        for h in handles:
            c = found.get(h.lower().lstrip("@"))
            out[h] = {"platform_id": str(c.get("slug") or ""), "display": str(c.get("slug") or ""),
                      "avatar": ""} if c else None
        return out

    async def live(self, accounts: List[Dict[str, Any]]) -> Dict[str, Live]:
        slugs = [a["platform_id"] for a in accounts if a.get("platform_id")]
        out: Dict[str, Live] = {}
        for c in await self.channels(slugs) if slugs else []:
            st = c.get("stream") or {}
            if not st.get("is_live"):
                continue
            slug = str(c.get("slug") or "")
            out[slug] = {"title": str(c.get("stream_title") or ""), "game": str((c.get("category") or {}).get("name") or ""),
                         "viewers": int(st.get("viewer_count") or 0), "started_at": iso_ts(str(st.get("start_time") or "")),
                         "url": f"https://kick.com/{slug}", "thumb": str(st.get("thumbnail") or "")}
        return out
