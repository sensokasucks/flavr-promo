"""
Start FlaVR Promo: ``python -m flavrpromo`` (the Docker image's command).

Builds, in order: settings (environment), the database (copied once from FlaVR Bot's on the first
start, flavrpromo/import_old.py), the web server (calendar pages, /live.json), the owner's DMs, the
go-live watcher with its platform checkers, the Discord client, the weekly calendar (its posts and
its pages) and the community calendar (flavrpromo/promo.py, streams members add from their posts),
and runs them all on one event loop until the container stops.

Split from FlaVR Bot on 2026-11-20: Stream Core, Wake-on-LAN, server care and the after-stream recap
stay there; everything about other people's streams, the calendar and the reports lives here.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from zoneinfo import ZoneInfo
from pathlib import Path

import aiohttp
import discord

from . import config, groups, host_picker, hosts, settings_page
from .bot import PromoBot
from .calendar_post import CalendarPoster
from .import_old import maybe_import
from .gameinfo import GameInfo
from .pings import Pinger
from .promo import Promo
from .platforms.kick import Kick
from .platforms.twitch import Twitch
from .platforms.youtube import DEEP_CHECK, YouTube
from .render import ImageCache, Screenshotter
from .server import Server
from .store import Store
from .watcher import Watcher
from .web import add_routes

log = logging.getLogger("flavrpromo")
DB_NAME = "flavr_promo.db"          # in DATA_DIR (/data in Docker, a named volume)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = config.load()
    for p in config.problems(s):
        log.error("%s", p)
    if not s.discord_token or not s.owner_id:
        return 2                # nothing works without these; the log says what to set
    db_path = Path(s.data_dir) / DB_NAME
    try:
        maybe_import(db_path, Path(s.import_dir))     # first start only: FlaVR Bot's calendar data
    except Exception:
        log.exception("Couldn't copy FlaVR Bot's data; starting with an empty calendar")
    store = Store(db_path)
    groups.init(store)                      # custom groups (/group add) live in this database
    folded = store.merge_overlaps()         # streams counted twice by an older version (or a long outage)
    if folded:
        log.info("Merged %d stream(s) that had been counted twice", folded)
    server = Server(store)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
        checkers = {
            "twitch": Twitch(http, s.twitch_client_id, s.twitch_client_secret),
            "youtube": YouTube(http, s.youtube_api_key),
            "kick": Kick(http, s.kick_client_id, s.kick_client_secret),
        }
        # the YouTube deep check (/setup youtube-check; off unless the owner picked daily / 48h / weekly)
        checkers["youtube"].search_every = DEEP_CHECK.get(str(store.get("youtube_deep_check") or "off"), 0.0)
        watcher = Watcher(store, checkers, {"twitch": s.twitch_every, "youtube": s.youtube_every, "kick": s.kick_every})
        server.owner_live = watcher.owner_live
        bot: PromoBot

        async def send(text: str) -> None:
            await bot.dm_owner(text)

        # quiet hours don't apply while the watcher sees the owner live (owner_live True)
        pinger = Pinger(store, send, tz=s.timezone, quiet=s.quiet_hours, live=lambda: watcher.owner_live() is True)
        pinger.load_quiet()         # quiet hours changed with /pings quiet win over QUIET_HOURS
        bot = PromoBot(s, store, pinger, watcher)
        shooter = Screenshotter(s.chromium_path)
        poster = CalendarPoster(store, bot, ImageCache(Path(s.data_dir) / "cache" / "img", http), shooter,
                                tz=s.timezone, preview_hour=s.calendar_preview_hour,
                                ping=lambda: pinger.switches().get("calendar", False), quiet=pinger.quiet_now,
                                hold=lambda text: pinger.ping("calendar", text), backfill=watcher.backfill,
                                share_on=lambda: pinger.switches().get("share", False))
        bot.calendar = poster
        # community calendar (flavrpromo/promo.py): streams members add from their posts, followed with the
        # same platform clients; settings PROMO_WEEKLY_LIMIT, PROMO_WAIT_HOURS
        bot.promo = Promo(store, checkers, ZoneInfo(s.timezone), weekly_limit=s.promo_weekly_limit,
                          wait_hours=s.promo_wait_hours, poke=poster.poke)
        poster.web_url = s.web_address or web_address(s.listen_port)    # the X Article link in share DMs
        server.extra_routes.append(lambda app: add_routes(app, poster))
        # Colette and Clark (flavrpromo/hosts.py): their pictures in DATA_DIR/hosts, and the review
        # line picker page /hosts/pick on the same web server (flavrpromo/host_picker.py)
        hosts.init(Path(s.data_dir) / "hosts")
        # KoboldCpp's extra lines on the picker page (flavrpromo/kobold.py): KOBOLD_URL / KOBOLD_KEY, unless
        # the settings page (/settings, flavrpromo/settings_page.py) saved its own; also loads edited host lines
        poster.http = http
        poster.kobold_env = {"url": s.kobold_url, "key": s.kobold_key}
        settings_page.apply(poster)
        server.extra_routes.append(lambda app: settings_page.add_routes(app, poster))
        # game genres / summary / store link from IGDB with the Twitch keys (flavrpromo/gameinfo.py)
        bot.game_info = GameInfo(store, checkers["twitch"])
        server.extra_routes.append(lambda app: host_picker.add_routes(app, poster))

        # go-live posts first, then a nudge so the calendar redraws within seconds
        async def on_start(person, session, live_on):
            out = await bot.post_start(person, session, live_on)
            poster.poke()
            return out

        async def on_end(person, session):
            await bot.post_end(person, session)
            poster.poke()

        watcher.on_start = on_start
        watcher.on_change = bot.post_change
        watcher.on_end = on_end
        watcher.on_scheduled = poster.on_scheduled

        await server.start(s.listen_host, s.listen_port)

        async def watch(platform: str) -> None:
            await bot.ready_event.wait()        # posts need the Discord channels loaded
            await watcher.run_platform(platform)

        async def after_ready(job):
            await bot.ready_event.wait()        # posts need the Discord channels loaded
            await job()

        async def fill_in() -> None:
            # the bot only knows streams it saw live: fill last week and this week from the platforms
            # (after the first checks have found everyone's channel ids)
            await asyncio.sleep(120)
            for off in (-1, 0):
                await poster.ensure_backfill(poster.week_of(off), force=True)

        tasks = [asyncio.create_task(pinger.run(), name="pings"),
                 asyncio.create_task(after_ready(fill_in), name="backfill"),
                 asyncio.create_task(after_ready(poster.run), name="calendar"),
                 asyncio.create_task(after_ready(watcher.run_schedules), name="schedules"),
                 asyncio.create_task(after_ready(bot.promo.run), name="community")]
        for platform, checker in checkers.items():
            if checker.ready:
                tasks.append(asyncio.create_task(watch(platform), name=f"watch-{platform}"))
            else:
                log.info("%s watcher off: its keys aren't set (.env.example)", platform.title())
        try:
            await bot.start(s.discord_token)
        except discord.LoginFailure:
            log.error("Discord refused DISCORD_TOKEN. Copy a fresh one: developer portal → your app → Bot → Reset Token.")
            return 3
        finally:
            for t in tasks:
                t.cancel()
            await server.stop()
            await shooter.close()
            await bot.close()
    return 0


def web_address(port: int) -> str:
    """This PC's home network address as "http://192.168.0.20:3871". A UDP "connect" sends nothing; it
    only asks the system which address it would use (the stack uses host networking, so this is the
    Linux PC's own). Falls back to a placeholder the owner can read; WEB_ADDRESS overrides it."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
            so.connect(("10.255.255.255", 1))
            return f"http://{so.getsockname()[0]}:{port}"
    except OSError:
        return f"http://<this PC>:{port}"


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
