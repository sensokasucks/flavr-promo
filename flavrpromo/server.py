"""
FlaVR Promo's little web server on the home network (port LISTEN_PORT, default 3871).

  GET /health      {"ok": true}  (no password; Docker's health check)
  GET /live.json   {"owner_live": true | false | null, "live": [{"name", "platforms", "since"}]}
                   who the go-live watcher sees live right now. FlaVR Bot can ask this (its
                   PROMO_URL setting) so its "Stream Core stopped answering" alarm stays quiet when
                   the owner is offline everywhere. null = no owner is followed (/friend add ... owner: True).
  GET /calendar... the calendar pages, picture, .ics feed and X Article (flavrpromo/web.py)

No password: everything here is public anyway (stream titles and times). Never forward the port on
the router. Before the split (2026-11-20) these pages were served by FlaVR Bot's Stream Core
listener on 3870; FlaVR Promo has its own port so both stacks can run on the same PC.

Who calls it: flavrpromo/__main__.py makes one ``Server``, appends web.add_routes to ``extra_routes``,
sets ``owner_live`` to the watcher's answer and calls ``start`` / ``stop``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, List, Optional

from aiohttp import web

from .store import Store

log = logging.getLogger("flavrpromo.server")


class Server:
    def __init__(self, store: Store):
        self.store = store
        # the watcher's view of the owner: True live somewhere, False offline everywhere, None unknown
        # (set by flavrpromo/__main__.py to Watcher.owner_live)
        self.owner_live: Callable[[], Optional[bool]] = lambda: None
        # more pages on the same port: each is called with the aiohttp app (flavrpromo/web.py add_routes)
        self.extra_routes: List[Callable[[web.Application], None]] = []
        self._runner: Optional[web.AppRunner] = None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/health", self._health)
        app.router.add_get("/live.json", self._live)
        for add in self.extra_routes:
            add(app)
        return app

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _live(self, request: web.Request) -> web.Response:
        rows = []
        for r in self.store.live_now():
            plats = r.get("platforms")
            if isinstance(plats, str):
                try:
                    plats = json.loads(plats)
                except ValueError:
                    plats = []
            rows.append({"name": r.get("name"), "platforms": plats or [],
                         "since": float(r.get("started_at") or time.time())})
        return web.json_response({"owner_live": self.owner_live(), "live": rows})

    async def start(self, host: str, port: int) -> None:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        log.info("Calendar pages on %s:%s", host, port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
