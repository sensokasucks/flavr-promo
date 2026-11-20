"""
FlaVR Promo settings, read once at start from environment variables.

In Docker these come from the stack's environment (Portainer: Stacks → flavr-promo → Environment
variables, or a .env file next to docker-compose.yml). Every name and its meaning is listed in
.env.example; keep the two in sync. Secrets (tokens, keys, the Core password) only ever live in
the environment, never in the database or the logs.

Who reads it: flavrpromo/__main__.py builds one Settings and hands it to every part.

Split from FlaVR Bot on 2026-11-20 (owner: "this docker stack handles the calendar, stream updates,
and reports"): the Stream Core link, Wake-on-LAN, server care and the after-stream recap stayed in
FlaVR Bot, so their settings (FLAVR_CORE_KEY, STREAM_PC_MAC, BIG_TIP, SCAM_TIMEOUT_MIN, RAID_JOINS,
RECAP_DELAY_MIN, OLLAMA_URL ...) are not read here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(str(env.get(key, "")).strip() or default)
    except ValueError:
        return default


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = str(env.get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _hours(raw: str, default: tuple[int, int]) -> tuple[int, int]:
    """"3-11" → (3, 11): quiet hours from 3 AM to 11 AM; "" or "off" → (0, 0) = no quiet hours."""
    raw = (raw or "").strip().lower()
    if not raw:
        return default
    if raw in ("off", "none", "0"):
        return (0, 0)
    try:
        a, b = raw.split("-", 1)
        return (int(a) % 24, int(b) % 24)
    except ValueError:
        return default


@dataclass
class Settings:
    # Discord
    discord_token: str = ""
    owner_id: int = 0                   # the streamer's Discord user id: owner-only commands + DM pings
    guild_id: int = 0                   # optional: register slash commands on this server at once
    # This bot's little web server (calendar pages, OBS source, .ics feed, /health). Its own port, so
    # it can run on the same PC as FlaVR Bot (3870): both stacks use host networking.
    listen_host: str = "0.0.0.0"        # home network only: never forward this port on the router
    listen_port: int = 3871
    web_address: str = ""               # how phones / PCs at home reach this bot's pages ("" = found by itself)
    # Platform look-ups for the go-live watcher (official APIs only)
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""
    kick_client_id: str = ""
    kick_client_secret: str = ""
    # How often each platform is checked (seconds); kept polite on purpose
    twitch_every: int = 120
    youtube_every: int = 600
    kick_every: int = 180
    # The owner's DMs (flavrpromo/pings.py: friends going live, calendar changes, share text)
    timezone: str = "America/New_York"
    quiet_hours: tuple[int, int] = (3, 11)
    # Weekly calendar (flavrpromo/calendar_post.py): Sunday preview hour (TZ, 0-23); the Friday / Monday
    # reviews' times are set in Discord (/setup review-times)
    calendar_preview_hour: int = 10
    chromium_path: str = ""             # blank = Playwright's own Chromium (the Docker image has it)
    # Community calendar (flavrpromo/promo.py): streams people add from their self-promo posts
    promo_weekly_limit: int = 7         # posts one person can add in 7 days (mods have no limit)
    promo_wait_hours: int = 6           # a channel link added while offline (no time given) waits this long to go live
    # Storage
    data_dir: str = "/data"
    # One-time move of FlaVR Bot's calendar data (flavrpromo/import_old.py): the folder holding FlaVR
    # Bot's flavr_bot.db, mounted read-only. Used only while this bot has no database of its own yet.
    import_dir: str = "/import"
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def watcher_ready(self) -> Dict[str, bool]:
        """Which platforms the go-live watcher can ask (their keys are set)."""
        return {"twitch": bool(self.twitch_client_id and self.twitch_client_secret),
                "youtube": True,      # RSS needs no key; the API key only makes live checks exact
                "kick": bool(self.kick_client_id and self.kick_client_secret)}


def load(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Settings from ``env`` (default: os.environ)."""
    env = os.environ if env is None else env
    g = lambda k, d="": str(env.get(k, d) or d).strip()  # noqa: E731
    return Settings(
        discord_token=g("DISCORD_TOKEN"),
        owner_id=_int(env, "OWNER_ID", 0),
        guild_id=_int(env, "GUILD_ID", 0),
        listen_host=g("LISTEN_HOST", "0.0.0.0"),
        listen_port=_int(env, "LISTEN_PORT", 3871),
        web_address=g("WEB_ADDRESS").rstrip("/"),
        twitch_client_id=g("TWITCH_CLIENT_ID"),
        twitch_client_secret=g("TWITCH_CLIENT_SECRET"),
        youtube_api_key=g("YOUTUBE_API_KEY"),
        kick_client_id=g("KICK_CLIENT_ID"),
        kick_client_secret=g("KICK_CLIENT_SECRET"),
        twitch_every=max(60, _int(env, "TWITCH_EVERY_SEC", 120)),
        youtube_every=max(300, _int(env, "YOUTUBE_EVERY_SEC", 600)),
        kick_every=max(120, _int(env, "KICK_EVERY_SEC", 180)),
        timezone=g("TZ", "America/New_York"),
        quiet_hours=_hours(g("QUIET_HOURS"), (3, 11)),
        calendar_preview_hour=_int(env, "CALENDAR_PREVIEW_HOUR", 10) % 24,
        chromium_path=g("CHROMIUM_PATH"),
        promo_weekly_limit=max(1, _int(env, "PROMO_WEEKLY_LIMIT", 7)),
        promo_wait_hours=max(1, min(48, _int(env, "PROMO_WAIT_HOURS", 6))),
        data_dir=g("DATA_DIR", "/data"),
        import_dir=g("IMPORT_DIR", "/import"),
    )


def problems(s: Settings) -> list[str]:
    """Plain-words setup problems; the bot refuses to start while the first one is there."""
    out = []
    if not s.discord_token:
        out.append("DISCORD_TOKEN is empty: paste the bot token from the Discord developer portal.")
    if not s.owner_id:
        out.append("OWNER_ID is empty: your own Discord user id (Discord → Settings → Advanced → "
                   "Developer Mode, then right-click your name → Copy User ID).")
    return out
