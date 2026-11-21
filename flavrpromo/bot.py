"""
The Discord side of FlaVR Promo: slash commands, DMs to the owner, and the go-live posts.

FlaVR Promo was split from FlaVR Bot on 2026-11-20. Its commands are the ones FlaVR Bot had for the
watcher, calendar, talent channels and community calendar, with the same names, so nobody has to
learn new ones. The Stream Core ones (/points, /queue, /core, /wake, /said), server care and the
after-stream recap (/setup recap-channel) stayed in FlaVR Bot.

Commands (registered on GUILD_ID at once when it is set, else globally, which Discord can take
up to an hour to show the first time):

  Anyone
    /live               who you follow is live right now
    /schedule [name]    upcoming streams (Twitch schedule + YouTube scheduled streams); default the owner
    /friend list        everyone the watcher follows
    /calendar view [group] [week] [when]   the weekly calendar picture (last week = the recap); when =
                        just today / tomorrow / the weekend / a weekday (the same as /calendar focus)
  Owner (OWNER_ID) or Manage Server
    /friend add name platform handle [group] [owner]   follow a channel (adds the person if new)
    /friend remove name    /friend main name platform   /friend import list
    /friend edit name platform handle   change (or add) one of someone's channels
    /friend drop name platform   stop following one of someone's platforms, keep the rest
    /friend schedule name day time [title]   a regular weekly time by hand (Kick, no-schedule people)
    /friend unschedule name    /friend hide name hidden   (keep someone off the calendar)
    /friend group name group   move someone to another group
    /group add name [colour]   /group edit group [name] [colour]   /group remove group   /group list
                        custom groups next to FlaVR and Friends (flavrpromo/groups.py); group options
                        everywhere are typed with suggestions (autocomplete)
    /setup live-channel group channel                   where go-live posts go for a group
    /setup calendar-channel group channel               where the weekly calendar + recap go
    /setup review-times [week] [weekend]   when the reviews post: Friday (Monday to Thursday) and Monday
                        (Friday to Sunday), a time or "off" (default 10 AM both; flavrpromo/calendar_post.py)
    /calendar view|post|share review:week|weekend   the newest review, any time
    /setup youtube-check off|daily|48h|weekly   the YouTube deep check for streams scheduled far ahead
                        (search.list, 100 quota units per channel a run; off by default; flavrpromo/platforms/youtube.py)
    /calendar post [group] [when]  a fresh calendar post now (when: just today / tomorrow / the weekend /
                        a weekday, as an extra post in the group's calendar channel)
    /calendar focus when [group] [post]   just today / tomorrow / the weekend / a weekday (flavrpromo/focus.py);
                        anyone sees it themselves, post (owner or Manage Server) puts it in the channel
    /setup day-posts group [channel] [today] [tomorrow] [weekend] [weekend_day]   automatic Today / evening
                        Tomorrow / This weekend posts, each time typed ("10am", "8pm") or "off"
    /calendar share ... [when]   the same copy-ready text for just today / tomorrow / the weekend / a weekday
    /calendar refresh [week]  fill a week in again from the channels' past streams (VODs)
    /calendar share [group] [week] [style]   DMs you copy-ready text for other Discords and X (flavrpromo/share.py)
    /setup share-style style [bold_days] [hashtags]   the X text's default layout (post + links reply /
                        one post / 280 thread), bold-looking day headings, a hashtag line
    /friend x name handle   their X handle ("-" removes it); tagged only with /setup share-style tag_people
    /friend game name game   set the game of someone's live stream by hand (YouTube has no category)
    /friend games name      someone's games: streams each and when last (anyone)
    /friend signoff add name line [emoji] | remove name number | list name   the lines someone ends their
                        stream with; one goes on each "was live" card (flavrpromo/signoff.py)
  Hosts Colette and Clark (flavrpromo/hosts.py, host_cards.py, host_picker.py; owner or Manage Server)
    /host setup on [only]   hosts on / off; only = always one host (else turns, never 3 in a row).
                        On: a host line above go-live cards, and reviews wait for picks on /hosts/pick
    /host picture host kind file   upload a pose (happy, pointing, sleepy), desk or head picture
    /host list | preview host review card [group]   which pictures exist; draw an opener / desk card
  Community calendar (flavrpromo/promo.py): streams members add from their self-promo posts
    message menu (long-press / right-click a post → Apps) "Add to community calendar" and
        "Remove from community calendar": your own posts with an allowed role; moderators any post
    /community schedule link [when] | list [week] | remove number      (the same, typed)
    /community roles add|remove|list role | report-channel channel   (owner or Manage Server)
  Talent channels (flavrpromo/talent.py)
    /talent channel name [channel] | link name [user] | options name [group_channel] [own_channel] | list
                        someone's own channel: go-live cards there too, a pinned week card, their recap;
                        /live, /schedule, /calendar view|share used there show only them
    /me schedule day time [title] | unschedule | main platform | x handle | hide [hidden] |
        posts [group_channel] [own_channel] | share [week] | signoff add|remove|list   the linked person's own entry
  Owner only (answers only you can see)
    /status             the go-live watcher and this PC
    /pings view | set kind on | quiet start end          DM switches (friends, calendar, share) and quiet hours

Every message sets allowed_mentions to nothing, so a stream title can't ping @everyone.
Commands answer "only you can see this" (ephemeral) unless they are meant for the channel.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands

from . import focus, sysinfo
from .calendar import DAY_NAMES, REVIEW_NAMES
from .config import Settings
from . import games, host_picker, hosts, promo, signoff, talent
from .pings import KINDS, Pinger, length
from .share import X_STYLES
from . import groups
from .store import PLATFORMS, Store
from .watcher import Watcher, main_platform

log = logging.getLogger("flavrpromo.bot")
NO_PINGS = discord.AllowedMentions.none()
# FlaVR brand colours (the logo's pink and teal); the friends group gets teal
ENDED_COLOUR = 0x5B5F66
PLATFORM_ICONS = {"youtube": "▶️ YouTube", "twitch": "🟣 Twitch", "kick": "🟢 Kick"}


def parse_time(text: str) -> Optional[int]:
    """"7 PM", "7:30pm", "19:30", "9" → minutes after midnight (None when unreadable)."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*", (text or "").lower())
    if not m:
        return None
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")[:1]
    if mins > 59 or h > 23 or (ampm and not 1 <= h <= 12):
        return None
    if ampm == "p" and h != 12:
        h += 12
    elif ampm == "a" and h == 12:
        h = 0
    return h * 60 + mins


def make_embed(data: Dict[str, Any], picture: str = "") -> discord.Embed:
    """flavrpromo/calendar_post.py ``embed()`` data → a discord.Embed (with the attached picture)."""
    e = discord.Embed(title=data["title"][:256], colour=data.get("colour") or groups.colour_int("flavr"))
    for name, value in data.get("fields") or []:
        e.add_field(name=name[:256], value=value[:1024], inline=False)
    if data.get("empty"):
        e.description = "Nothing on the calendar yet this week."
    if data.get("description"):                     # flavrpromo/focus.py: a day with nothing on it
        e.description = data["description"][:4096]
    if data.get("footer"):
        e.set_footer(text=data["footer"][:2048])
    if picture:
        e.set_image(url=f"attachment://{picture}")
    return e


def ago(ts: Optional[float]) -> str:
    if not ts:
        return "never"
    sec = int(time.time() - ts)
    if sec < 90:
        return f"{sec} s ago"
    if sec < 5400:
        return f"{sec // 60} min ago"
    return f"{sec // 3600} h ago"


def parse_import(text: str) -> List[Tuple[str, str, str, str]]:
    """``/friend import`` text → [(name, platform, handle, group)].

    One line per channel: ``Name, platform, handle[, group]`` (commas or tabs), e.g.
    ``Lulu, youtube, @luluteala, flavr``. Lines starting with # and blank lines are skipped."""
    out = []
    for line in (text or "").replace("\t", ",").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or parts[1].lower() not in PLATFORMS:
            continue
        group = (groups.find(parts[3]) if len(parts) > 3 else None) or "flavr"     # key or name; unknown → FlaVR
        out.append((parts[0], parts[1].lower(), parts[2], group))
    return out


class PromoBot(discord.Client):
    """FlaVR Promo's Discord client. Made once by flavrpromo/__main__.py.

    Needs no privileged intents (Message Content / Server Members): the community calendar's message
    menu gets the post's text from the interaction itself, and nothing else reads messages."""

    def __init__(self, settings: Settings, store: Store, pinger: Pinger, watcher: Watcher):
        super().__init__(intents=discord.Intents.default(), allowed_mentions=NO_PINGS)
        self.settings = settings
        self.store = store
        self.pinger = pinger
        self.watcher = watcher
        self.tree = app_commands.CommandTree(self)
        # the weekly calendar (flavrpromo/calendar_post.py); set by flavrpromo/__main__.py
        self.calendar: Any = None
        # the community calendar (flavrpromo/promo.py Promo); set by flavrpromo/__main__.py
        self.promo: Any = None
        # set once Discord says we're in; the go-live watcher waits for it so its first posts don't get lost
        self.ready_event = asyncio.Event()
        self._register()

    # ── helpers ────────────────────────────────────────────────────────
    async def dm_owner(self, text: str, png: Optional[bytes] = None) -> None:
        """flavrpromo/pings.py's ``send`` (and the calendar pings, with the picture): one DM to OWNER_ID."""
        user = self.get_user(self.settings.owner_id) or await self.fetch_user(self.settings.owner_id)
        files = [discord.File(io.BytesIO(png), filename="calendar.png")] if png else []
        await user.send(text, files=files, allowed_mentions=NO_PINGS)

    async def dm_share(self, messages: List[str], png: Optional[bytes] = None, user_id: int = 0) -> None:
        """flavrpromo/calendar_post.py's share package: the picture with the first message, then one DM
        per text so each copies on its own. No link previews (they'd hide the text on a phone).
        ``user_id``: who gets it (a talent's own share, flavrpromo/talent.py); 0 = the owner."""
        uid = int(user_id or self.settings.owner_id)
        user = self.get_user(uid) or await self.fetch_user(uid)
        for i, text in enumerate(messages):
            files = [discord.File(io.BytesIO(png), filename="calendar.png")] if png and i == 0 else []
            await user.send(text[:2000], files=files, allowed_mentions=NO_PINGS, suppress_embeds=True)

    # ── calendar posts (flavrpromo/calendar_post.py calls these) ─────────
    async def cal_send(self, channel_id: str, data: Dict[str, Any], png: Optional[bytes], name: str) -> str:
        """A new calendar / recap post; returns its message id ("" when it couldn't)."""
        channel = self.get_channel(int(channel_id))
        if channel is None:
            return ""
        files = [discord.File(io.BytesIO(png), filename=name)] if png else []
        try:
            msg = await channel.send(embed=make_embed(data, name if png else ""), files=files,
                                     allowed_mentions=NO_PINGS)
        except discord.HTTPException as e:
            log.warning("calendar post failed: %s", e)
            return ""
        return str(msg.id)

    async def cal_edit(self, channel_id: str, message_id: str, data: Dict[str, Any], png: Optional[bytes],
                       name: str) -> bool:
        """Edit a calendar post in place (new picture too). False when the post is gone."""
        channel = self.get_channel(int(channel_id))
        if channel is None:
            return False
        try:
            msg = channel.get_partial_message(int(message_id))
            kw: Dict[str, Any] = {"embed": make_embed(data, name if png else ""), "allowed_mentions": NO_PINGS}
            if png:
                kw["attachments"] = [discord.File(io.BytesIO(png), filename=name)]
            await msg.edit(**kw)
            return True
        except (discord.NotFound, discord.Forbidden):
            # Forbidden: a post another bot made (FlaVR Bot posted the calendar before the split,
            # 2026-11-20); bots can only edit their own messages, so it's treated as gone and
            # flavrpromo/calendar_post.py posts a fresh one
            return False
        except discord.HTTPException as e:
            log.warning("calendar edit failed: %s", e)
            return True         # a hiccup, not a deleted post: keep it and try again next change

    async def cal_pin(self, channel_id: str, message_id: str, on: bool) -> None:
        """Pin (or unpin) a post: a talent's week card (flavrpromo/talent.py). Needs the bot's Pin
        Messages / Manage Messages permission in that channel; without it the card just isn't pinned."""
        channel = self.get_channel(int(channel_id))
        if channel is None:
            return
        try:
            msg = channel.get_partial_message(int(message_id))
            await (msg.pin() if on else msg.unpin())
        except discord.HTTPException as e:
            log.info("couldn't %s a talent card: %s", "pin" if on else "unpin", e)

    def is_owner_id(self, user: discord.abc.User) -> bool:
        return user.id == self.settings.owner_id

    def may_manage(self, inter: discord.Interaction) -> bool:
        perms = getattr(inter.user, "guild_permissions", None)
        return self.is_owner_id(inter.user) or bool(perms and perms.manage_guild)

    async def setup_hook(self) -> None:
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Discord: logged in as %s", self.user)
        self.ready_event.set()

    # ── Discord events ─────────────────────────────────────────────────
    async def on_raw_message_delete(self, p: discord.RawMessageDeleteEvent) -> None:
        if self.promo is not None:
            self.promo.post_deleted(str(p.message_id))     # a deleted self-promo post leaves the community calendar

    # ── go-live posts (Watcher callbacks) ──────────────────────────────
    def live_embed(self, person: Dict[str, Any], session: Dict[str, Any],
                   live_on: Dict[str, Dict[str, Any]]) -> discord.Embed:
        main = main_platform(person, live_on)
        info = live_on.get(main) or {}
        e = discord.Embed(title=f"{person['name']} is live", description=session.get("title") or info.get("title") or "",
                          url=info.get("url") or session.get("url") or None,
                          colour=groups.colour_int(person.get("grp") or "flavr"))
        links = " · ".join(f"[{PLATFORM_ICONS.get(p, p)}]({i.get('url')})" for p, i in live_on.items())
        e.add_field(name="Watch", value=links or "—", inline=False)
        # the game with its history tag, and the games before it in this stream (flavrpromo/games.py)
        now = games.now_playing(self.store, session.get("id"))
        game = now.get("game") or session.get("game")
        if game:
            tag = now.get("tag") if now.get("game") else ""
            e.add_field(name="Playing", value=f"{game} · {tag}" if tag else game, inline=True)
        if now.get("earlier"):
            e.add_field(name="Earlier", value=now["earlier"][:1024], inline=False)
        if session.get("restarts"):
            e.add_field(name="Restarts", value=str(session["restarts"]), inline=True)
        if info.get("thumb"):
            e.set_image(url=info["thumb"])
        if info.get("avatar"):
            e.set_thumbnail(url=info["avatar"])
        if session.get("started_at"):
            e.timestamp = datetime.fromtimestamp(float(session["started_at"]))
            e.set_footer(text="Started")
        # the host presenting this card (flavrpromo/hosts.py): name and job on top, their face when
        # /host picture head was uploaded (sent with the first post as host.<ext>, kept on every edit)
        key = self._host_of(session)
        if key:
            h, face = hosts.HOSTS[key], hosts.picture(key, "head")
            e.set_author(name=f"{h['name']} · {h['role']}", icon_url=f"attachment://host{face.suffix}" if face else None)
        return e

    # ── the host's line above go-live cards (flavrpromo/hosts.py; off until /host setup on) ──
    @staticmethod
    def _host_of(session: Dict[str, Any]) -> str:
        """The session's host key ("" = no host: hosts were off when it started)."""
        key = str(session.get("host") or "")
        return key if key in hosts.HOSTS else ""

    @staticmethod
    def _host_face(key: str) -> List[discord.File]:
        """The host's head picture as a fresh attachment (a discord.File can only be sent once)."""
        face = hosts.picture(key, "head") if key else None
        return [discord.File(str(face), filename=f"host{face.suffix}")] if face else []

    def _host_say(self, key: str, event: str, person: Dict[str, Any], game: str = "", tag: str = "",
                  length_s: float = 0, signoff_text: str = "") -> str:
        """The message text above the card: "☕ **Colette Cappuccino:** <line>" (markdown in names escaped)."""
        esc = discord.utils.escape_markdown
        line = hosts.live_line(key, event, esc(person["name"]), esc(game), tag, length_s, signoff_text)
        return f"{hosts.speaker(key)} {line}"[:2000] if line else ""

    async def post_start(self, person, session, live_on) -> Tuple[str, str]:
        """The go-live card, in every place talent.live_channels picks: the group's live channel and
        the person's own talent channel (either can be switched off per person). Returns the first
        post (the watcher saves it as post_channel / post_message); the others are saved in the
        session's extra_posts, so post_change / post_end update every copy."""
        main = main_platform(person, live_on)
        if not person.get("is_owner"):
            self.pinger.friend_live(person["name"], PLATFORM_ICONS.get(main, main))
        # the host (when /host setup on): chosen once per stream and saved, so every edit keeps them
        content, key = None, ""
        if hosts.enabled(self.store):
            key = hosts.choose(self.store)
            segs = self.store.segments(session["id"]) if session.get("id") else []
            game = segs[-1]["game"] if segs else str(session.get("game") or "")
            content = self._host_say(key, "start", person, game, segs[-1]["tag"] if segs else "") or None
            session = {**session, "host": key, "host_game": game}
            if session.get("id"):
                self.store.update_session(session["id"], host=key, host_game=game)
        posted: List[List[str]] = []
        for channel_id in talent.live_channels(self.store, person):
            channel = self.get_channel(int(channel_id))
            if channel is None:
                continue
            try:
                msg = await channel.send(content=content, embed=self.live_embed(person, session, live_on),
                                         files=self._host_face(key), allowed_mentions=NO_PINGS)
            except discord.HTTPException as e:
                log.warning("go-live post in %s failed: %s", channel_id, e)
                continue
            posted.append([str(channel.id), str(msg.id)])
        if not posted:
            return "", ""
        if len(posted) > 1 and session.get("id"):
            self.store.update_session(session["id"], extra_posts=posted[1:])
        return posted[0][0], posted[0][1]

    async def _messages(self, session) -> List[discord.Message]:
        """Every copy of a session's go-live card that still exists (main post + extra_posts)."""
        pairs = [[session.get("post_channel"), session.get("post_message")]]
        try:
            pairs += json.loads(session.get("extra_posts") or "[]") if isinstance(session.get("extra_posts"), str) \
                else list(session.get("extra_posts") or [])
        except ValueError:
            pass
        out = []
        for channel_id, message_id in pairs:
            if not channel_id or not message_id:
                continue
            channel = self.get_channel(int(channel_id))
            if channel is None:
                continue
            try:
                out.append(await channel.fetch_message(int(message_id)))
            except discord.HTTPException:
                continue
        return out

    async def post_change(self, person, session, live_on) -> None:
        kw: Dict[str, Any] = {}
        key = self._host_of(session)
        if key and session.get("id"):
            # a new host line only when the game changed since their last line (sessions.host_game)
            segs = self.store.segments(session["id"])
            game = segs[-1]["game"] if segs else ""
            if game and game.lower() != str(session.get("host_game") or "").lower():
                said = self._host_say(key, "change", person, game, segs[-1]["tag"])
                if said:
                    kw["content"] = said
                self.store.update_session(session["id"], host_game=game)
        for msg in await self._messages(session):
            await self._edit(msg, embed=self.live_embed(person, session, live_on), **kw)

    async def _edit(self, msg: discord.Message, **kw: Any) -> None:
        """Edit one go-live card; a card that can't be edited is skipped. That's a card FlaVR Bot posted
        before the split (2026-11-20): bots can only edit their own messages, so a stream that was live
        during the switch keeps its old card as it was."""
        if self.user is not None and msg.author.id != self.user.id:
            return
        try:
            await msg.edit(allowed_mentions=NO_PINGS, **kw)
        except discord.HTTPException as e:
            log.info("couldn't edit a go-live card: %s", e)

    async def post_end(self, person, session) -> None:
        line = signoff.pick(self.store, person["id"], session.get("id"))
        # the host's closing line; when it reads out the sign-off line, the card doesn't repeat it
        kw: Dict[str, Any] = {}
        key = self._host_of(session)
        if key:
            said = self._host_say(key, "end", person, length_s=float(session["ended_at"]) - float(session["started_at"]),
                                  signoff_text=signoff.text(line) if line is not None else "")
            if said:
                kw["content"] = said
                if line is not None and signoff.text(line) in said:
                    line = None
        for msg in await self._messages(session):
            e = msg.embeds[0] if msg.embeds else discord.Embed()
            e.title = f"{person['name']} was live"
            e.colour = ENDED_COLOUR
            # the live fields "Playing" / "Earlier" become one "Played" line, every game in order
            kept = [f for f in e.fields if f.name not in ("Playing", "Earlier", "Played")]
            e.clear_fields()
            for f in kept:
                e.add_field(name=f.name, value=f.value, inline=f.inline)
            trail = games.played(self.store, session.get("id"), session.get("ended_at"))
            if trail:
                e.add_field(name="Played", value=trail[:1024], inline=False)
            e.set_footer(text=f"Live for {length(float(session['ended_at']) - float(session['started_at']))}")
            # the VOD the watcher found (flavrpromo/watcher.py find_vod: Twitch archive / YouTube stream page)
            if session.get("vod_url"):
                e.add_field(name="VOD", value=f"[Watch the VOD]({session['vod_url']})", inline=False)
            if line is not None:
                # their sign-off line (flavrpromo/signoff.py; one per stream, never the same twice in a row)
                e.add_field(name="\u200b", value=f"*{signoff.text(line)}*"[:1024], inline=False)
            await self._edit(msg, embed=e, **kw)

    # ── commands ───────────────────────────────────────────────────────
    def _register(self) -> None:
        tree = self.tree
        bot = self

        async def owner_only(inter: discord.Interaction) -> bool:
            if bot.is_owner_id(inter.user):
                return True
            await inter.response.send_message("Only the streamer can use this.", ephemeral=True)
            return False

        async def managers_only(inter: discord.Interaction) -> bool:
            if bot.may_manage(inter):
                return True
            await inter.response.send_message("Only the streamer or people with Manage Server can use this.",
                                              ephemeral=True)
            return False

        @tree.command(name="status", description="The go-live watcher and this PC (owner only)")
        async def status(inter: discord.Interaction):
            # Stream Core's side of /status stayed in FlaVR Bot (split 2026-11-20)
            if not await owner_only(inter):
                return
            lines = []
            si = sysinfo.info(bot.settings.data_dir)
            if si:
                up = length(si.get("uptime_sec", 0))
                lines.append(f"**This PC:** up {up} · load {si.get('load', '?')} · "
                             f"{si.get('disk_free_gb', '?')} GB free ({si.get('disk_used_pct', '?')}% used)")
            ws = bot.watcher.status()
            parts = []
            for p, s in ws["platforms"].items():
                mark = "⚠️" if s["error"] else ("✅" if s["ready"] else "➖ no key")
                parts.append(f"{p.title()} {mark} {ago(s['last_check']) if s['ready'] else ''}".strip())
            lines.append(f"**Watcher:** {ws['people']} people · " + " · ".join(parts))
            live = bot.store.live_now()
            lines.append(f"**Live now:** {len(live)}")
            await inter.response.send_message("\n".join(lines), ephemeral=True)

        pings = app_commands.Group(name="pings", description="DMs from FlaVR Promo: friends live, calendar, share text (owner only)")

        @pings.command(name="view", description="Which pings are on, and quiet hours")
        async def pings_view(inter: discord.Interaction):
            if not await owner_only(inter):
                return
            sw = bot.pinger.switches()
            a, b = bot.pinger.quiet
            lines = [f"{'✅' if sw[k] else '➖'} `{k}`: {label}" for k, (label, _) in KINDS.items()]
            lines.append(f"Quiet hours: {a}:00 to {b}:00 ({bot.settings.timezone})" if a != b else "Quiet hours: off")
            await inter.response.send_message("\n".join(lines), ephemeral=True)

        @pings.command(name="set", description="Switch one kind of ping on or off")
        @app_commands.choices(kind=[app_commands.Choice(name=f"{k}: {v[0]}"[:100], value=k) for k, v in KINDS.items()])
        async def pings_set(inter: discord.Interaction, kind: app_commands.Choice[str], on: bool):
            if not await owner_only(inter):
                return
            bot.pinger.set(kind.value, on)
            await inter.response.send_message(f"`{kind.value}` pings {'on' if on else 'off'}.", ephemeral=True)

        @pings.command(name="quiet", description="Quiet hours (0-23); the same number twice turns them off")
        async def pings_quiet(inter: discord.Interaction, start: app_commands.Range[int, 0, 23],
                              end: app_commands.Range[int, 0, 23]):
            if not await owner_only(inter):
                return
            bot.pinger.set_quiet(start, end)
            await inter.response.send_message("Quiet hours off." if start == end else
                                              f"Quiet hours {start}:00 to {end}:00. (While the watcher sees you live, they never apply.)",
                                              ephemeral=True)

        tree.add_command(pings)


        @tree.command(name="live", description="Who's live right now")
        async def live(inter: discord.Interaction):
            rows = bot.store.live_now()
            here = talent.person_for_channel(bot.store, inter.channel_id)     # in a talent channel: only them
            if here:
                rows = [r for r in rows if r["person_id"] == here["id"]]
            if not rows:
                await inter.response.send_message(f"{here['name']} isn't live right now." if here else
                                                  "Nobody on the list is live right now.", ephemeral=True)
                return
            lines = [f"🔴 **{r['name']}** for {length(time.time() - float(r['started_at']))}: [{r['title'] or 'live'}]({r['url']})"
                     for r in rows]
            await inter.response.send_message("\n".join(lines)[:1900], allowed_mentions=NO_PINGS, suppress_embeds=True)

        @tree.command(name="schedule", description="Upcoming streams (Twitch schedule and YouTube scheduled streams)")
        async def schedule(inter: discord.Interaction, name: Optional[str] = None):
            people = bot.store.people()
            # no name: the person whose talent channel this is (flavrpromo/talent.py), else the owner
            here = talent.person_for_channel(bot.store, inter.channel_id)
            person = (bot.store.person(name) if name else here or next((p for p in people if p["is_owner"]), None))
            if not person:
                await inter.response.send_message("Who? Add them with /friend add (or mark yourself with owner: True).",
                                                  ephemeral=True)
                return
            await inter.response.defer()
            items = await bot.watcher.schedule(person)
            if not items:
                await inter.followup.send(f"Nothing scheduled for {person['name']}.", allowed_mentions=NO_PINGS)
                return
            lines = [f"<t:{int(s['at'])}:F> (<t:{int(s['at'])}:R>) {PLATFORM_ICONS.get(s['platform'], '')}: "
                     f"{s.get('title') or 'stream'}" + (f" · {s['game']}" if s.get("game") else "") for s in items[:10]]
            await inter.followup.send(f"**{person['name']}**\n" + "\n".join(lines), allowed_mentions=NO_PINGS)

        friend = app_commands.Group(name="friend", description="People the go-live watcher follows")
        plat_choices = [app_commands.Choice(name=p.title(), value=p) for p in PLATFORMS]
        # groups come from flavrpromo/groups.py (FlaVR, Friends + /group add ones), so the group option is
        # typed with suggestions (autocomplete) instead of a fixed list
        async def group_auto(inter: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
            cur = current.lower()
            return [app_commands.Choice(name=g["name"], value=k) for k, g in groups.all_groups().items()
                    if cur in k or cur in g["name"].lower()][:25]

        async def pick_group(inter: discord.Interaction, text: Optional[str]) -> Optional[str]:
            """The group key for what was typed (blank = FlaVR); answers "no such group" and returns None."""
            g = groups.find(text)
            if g is None:
                await inter.response.send_message(f"There's no group called {text}. /group list shows them; "
                                                  "/group add makes one.", ephemeral=True)
            return g

        @friend.command(name="add", description="Follow a channel (adds the person if new)")
        @app_commands.choices(platform=plat_choices)
        @app_commands.autocomplete(group=group_auto)
        async def friend_add(inter: discord.Interaction, name: str, platform: app_commands.Choice[str], handle: str,
                             group: Optional[str] = None, owner: bool = False):
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            pid = bot.store.add_person(name, g, owner, str(inter.user))
            if not bot.store.add_account(pid, platform.value, handle.strip()):
                await inter.response.send_message(f"{platform.name} {handle} is already on the list.", ephemeral=True)
                return
            await inter.response.send_message(f"Following {name} on {platform.name} ({handle}). "
                                              "The first check runs within a few minutes.", ephemeral=True)

        @friend.command(name="remove", description="Stop following someone (all their channels)")
        async def friend_remove(inter: discord.Interaction, name: str):
            if not await managers_only(inter):
                return
            ok = bot.store.remove_person(name)
            await inter.response.send_message(f"Removed {name}." if ok else f"No one called {name}.", ephemeral=True)

        async def person_auto(inter: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
            # names typed with suggestions for /friend edit and /friend drop
            cur = current.lower()
            return [app_commands.Choice(name=p["name"][:100], value=p["name"][:100])
                    for p in bot.store.people() if cur in p["name"].lower()][:25]

        @friend.command(name="edit", description="Change someone's channel on a platform (adds it if they have none)")
        @app_commands.choices(platform=plat_choices)
        @app_commands.autocomplete(name=person_auto)
        @app_commands.describe(handle="The new channel: @handle, channel name, or YouTube channel id (UC...)")
        async def friend_edit(inter: discord.Interaction, name: str, platform: app_commands.Choice[str], handle: str):
            # store.change_account: the watcher looks the new channel up at its next check
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}. /friend list shows everyone.", ephemeral=True)
                return
            what = bot.store.change_account(p["id"], platform.value, handle.strip())
            if what == "taken":
                await inter.response.send_message(f"{platform.name} {handle} already belongs to someone else on the list.",
                                                  ephemeral=True)
                return
            await inter.response.send_message(
                f"{p['name']}'s {platform.name} is now {handle.strip()}" + (" (added)" if what == "added" else "")
                + ". The bot looks it up at its next check, within a few minutes.", ephemeral=True)

        @friend.command(name="drop", description="Stop following one of someone's platforms (keeps the others)")
        @app_commands.choices(platform=plat_choices)
        @app_commands.autocomplete(name=person_auto)
        async def friend_drop(inter: discord.Interaction, name: str, platform: app_commands.Choice[str]):
            # store.remove_account: past streams stay on the calendar, upcoming ones from it go
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}. /friend list shows everyone.", ephemeral=True)
                return
            if not any(a["platform"] == platform.value for a in p["accounts"]):
                await inter.response.send_message(f"{p['name']} has no {platform.name} on the list.", ephemeral=True)
                return
            if len(p["accounts"]) == 1:
                await inter.response.send_message(f"That's {p['name']}'s only platform. To stop following them, use "
                                                  "/friend remove; to switch channels, /friend edit.", ephemeral=True)
                return
            bot.store.remove_account(p["id"], platform.value)
            left = ", ".join(a["platform"].title() for a in p["accounts"] if a["platform"] != platform.value)
            await inter.response.send_message(f"No longer following {p['name']} on {platform.name}. Still on: {left}.",
                                              ephemeral=True)

        @friend.command(name="main", description="Which platform a person's posts link to first")
        @app_commands.choices(platform=plat_choices)
        async def friend_main(inter: discord.Interaction, name: str, platform: app_commands.Choice[str]):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}.", ephemeral=True)
                return
            bot.store.set_main(p["id"], platform.value)
            await inter.response.send_message(f"{name}'s posts now lead with {platform.name}.", ephemeral=True)

        @friend.command(name="list", description="Everyone the watcher follows")
        async def friend_list(inter: discord.Interaction):
            people = bot.store.people()
            if not people:
                await inter.response.send_message("Nobody yet. Add people with /friend add or /friend import.", ephemeral=True)
                return
            lines = []
            for g in groups.keys():
                rows = [p for p in people if p["grp"] == g]
                if rows:
                    lines.append(f"**{groups.name(g)}** ({len(rows)})")
                    for p in rows:
                        accs = ", ".join(f"{a['platform']}:{a['handle']}" + ("" if a["platform_id"] else " (not found yet)")
                                         for a in p["accounts"])
                        lines.append(f"• {p['name']}{' ⭐' if p['is_owner'] else ''}: {accs}")
            await inter.response.send_message("\n".join(lines)[:1900], ephemeral=True)

        @friend.command(name="import", description="Add many: one line each, 'Name, platform, handle, group'")
        async def friend_import(inter: discord.Interaction, lines: str):
            if not await managers_only(inter):
                return
            # Discord's text box keeps line breaks out of slash options, so ";" also separates lines
            rows = parse_import(lines.replace(";", "\n"))
            added = 0
            for name, plat, handle, group in rows:
                pid = bot.store.add_person(name, group, False, str(inter.user))
                added += bot.store.add_account(pid, plat, handle)
            await inter.response.send_message(f"Added {added} channel(s) from {len(rows)} line(s). "
                                              "Example line: `Lulu, youtube, @luluteala, flavr` (separate lines with ;).",
                                              ephemeral=True)

        day_choices = [app_commands.Choice(name=d.title(), value=i) for i, d in enumerate(DAY_NAMES)]

        @friend.command(name="schedule", description="A regular weekly stream time by hand (for the calendar)")
        @app_commands.choices(day=day_choices)
        @app_commands.describe(time="Like 7 PM or 19:30, in the bot's time zone (TZ)", title="Optional, e.g. the game")
        async def friend_schedule(inter: discord.Interaction, name: str, day: app_commands.Choice[int], time: str,
                                  title: Optional[str] = None):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            minute = parse_time(time)
            if not p or minute is None:
                await inter.response.send_message(f"No one called {name}." if not p else
                                                  "Couldn't read that time. Try 7 PM or 19:30.", ephemeral=True)
                return
            bot.store.add_manual(p["id"], day.value, minute, (title or "").strip()[:100])
            if bot.calendar:
                bot.calendar.poke()
            await inter.response.send_message(f"{p['name']} is on the calendar every {day.name} at {time.strip()} "
                                              f"({bot.settings.timezone}).", ephemeral=True)

        @friend.command(name="unschedule", description="Remove someone's hand-set weekly times")
        async def friend_unschedule(inter: discord.Interaction, name: str):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            n = bot.store.clear_manual(p["id"]) if p else 0
            if bot.calendar:
                bot.calendar.poke()
            await inter.response.send_message(f"Removed {n} weekly time(s) for {name}." if p else f"No one called {name}.",
                                              ephemeral=True)

        @friend.command(name="hide", description="Keep someone off the calendar and recap (still watched)")
        async def friend_hide(inter: discord.Interaction, name: str, hidden: bool = True):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}.", ephemeral=True)
                return
            bot.store.set_hidden(p["id"], hidden)
            if bot.calendar:
                bot.calendar.poke()
            await inter.response.send_message(f"{p['name']} is {'off' if hidden else 'back on'} the calendar.",
                                              ephemeral=True)

        @friend.command(name="x", description="Their X / Twitter handle, so the copy-ready X text tags them")
        @app_commands.describe(handle="Like @luluteala; - removes it")
        async def friend_x(inter: discord.Interaction, name: str, handle: str):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}.", ephemeral=True)
                return
            h = "" if handle.strip() in ("-", "none", "") else handle.strip().lstrip("@")
            if h and not re.fullmatch(r"\w{1,15}", h):
                await inter.response.send_message("That isn't an X handle (letters, numbers and _ only, 15 at most).",
                                                  ephemeral=True)
                return
            bot.store.set_x(p["id"], h)
            await inter.response.send_message(f"{p['name']} is tagged as @{h} in the X text." if h else
                                              f"{p['name']} is written by name in the X text.", ephemeral=True)

        @friend.command(name="group", description="Move someone to another group (FlaVR, Friends or one of yours)")
        @app_commands.autocomplete(group=group_auto)
        async def friend_group(inter: discord.Interaction, name: str, group: str):
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}.", ephemeral=True)
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            bot.store.set_group(p["id"], g)
            if bot.calendar:
                bot.calendar.poke()
            await inter.response.send_message(f"{p['name']} is in {groups.name(g)} now.", ephemeral=True)

        @friend.command(name="game", description="Set the game of someone's stream that's on now (YouTube shows none)")
        @app_commands.autocomplete(name=person_auto)
        @app_commands.describe(game="Like Valheim; remembered, so their next YouTube titles that name it are found")
        async def friend_game(inter: discord.Interaction, name: str, game: str):
            # flavrpromo/games.py: a new segment with its history tag, then the live card is edited
            if not await managers_only(inter):
                return
            p = bot.store.person(name)
            s = bot.store.open_session(p["id"]) if p else None
            game = " ".join(game.split())[:100]
            if not p or not s or not game:
                await inter.response.send_message(f"{name} isn't live right now." if p else f"No one called {name}.",
                                                  ephemeral=True)
                return
            bot.store.update_session(s["id"], game=game)
            games.track(bot.store, s["id"], p["id"], game, time.time())
            live_on = bot.watcher.live_on(p)
            if live_on:
                await bot.post_change(p, {**s, "game": game}, live_on)
            tag = games.now_playing(bot.store, s["id"]).get("tag")
            await inter.response.send_message(f"{p['name']} is playing {game}" + (f" ({tag})." if tag else "."),
                                              ephemeral=True, allowed_mentions=NO_PINGS)

        @friend.command(name="games", description="Someone's games: how many streams each, and when last")
        @app_commands.autocomplete(name=person_auto)
        async def friend_games(inter: discord.Interaction, name: str):
            p = bot.store.person(name)
            if not p:
                await inter.response.send_message(f"No one called {name}.", ephemeral=True)
                return
            rows = games.history(bot.store, p["id"], limit=15)
            if not rows:
                await inter.response.send_message(f"No games seen for {p['name']} yet.", ephemeral=True)
                return
            lines = [f"**{discord.utils.escape_markdown(r['game'])}**: {r['streams']} stream(s), last <t:{int(r['last'])}:R>"
                     for r in rows]
            await inter.response.send_message(f"{p['name']}'s games\n" + "\n".join(lines), ephemeral=True,
                                              allowed_mentions=NO_PINGS)

        # /friend signoff add|remove|list (flavrpromo/signoff.py)
        signoff.register_friend(friend, bot, managers_only, person_auto)
        tree.add_command(friend)

        # /group: make your own groups next to FlaVR and Friends (flavrpromo/groups.py keeps the list).
        # Each group gets its own go-live channel, calendar post, recap and share text once its channels
        # are picked with /setup live-channel and /setup calendar-channel.
        group_cmd = app_commands.Group(name="group", description="Groups of people (owner or Manage Server)")

        @group_cmd.command(name="add", description="Make a new group next to FlaVR and Friends")
        @app_commands.describe(name="Shown on the calendar, e.g. Art Pals", colour="Like #ff8800 (default teal)")
        async def group_add(inter: discord.Interaction, name: str, colour: Optional[str] = None):
            if not await managers_only(inter):
                return
            col = groups.parse_colour(colour) if colour else "#2ae0d4"
            if col is None:
                await inter.response.send_message("That isn't a colour. Try #ff8800.", ephemeral=True)
                return
            key = groups.add(name, col)
            if not key:
                why = ("That name is taken." if groups.find(name, default="") or groups.slug(name) in groups.keys()
                       else f"There are already {groups.MAX_GROUPS} groups." if groups.slug(name)
                       else "The name needs a letter or number.")
                await inter.response.send_message(why, ephemeral=True)
                return
            await inter.response.send_message(
                f"Made **{groups.name(key)}**. Next: put people in it with /friend add or /friend group, then pick "
                "its channels with /setup live-channel and /setup calendar-channel.", ephemeral=True)

        @group_cmd.command(name="edit", description="Rename a group or change its colour (FlaVR and Friends too)")
        @app_commands.autocomplete(group=group_auto)
        @app_commands.describe(colour="Like #ff8800")
        async def group_edit(inter: discord.Interaction, group: str, name: Optional[str] = None,
                             colour: Optional[str] = None):
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            col = groups.parse_colour(colour) if colour else None
            if colour and col is None:
                await inter.response.send_message("That isn't a colour. Try #ff8800.", ephemeral=True)
                return
            other = groups.find(name, default="") if name else ""
            if other and other != g:
                await inter.response.send_message("Another group already has that name.", ephemeral=True)
                return
            groups.update(g, name, col)
            if bot.calendar:
                bot.calendar.poke()                 # redraw the board with the new name / colour
            await inter.response.send_message(f"**{groups.name(g)}** is {groups.colour(g)}.", ephemeral=True)

        @group_cmd.command(name="remove", description="Delete one of your groups (its people move to Friends)")
        @app_commands.autocomplete(group=group_auto)
        async def group_remove(inter: discord.Interaction, group: str):
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            shown = groups.name(g)
            if not groups.remove(g):
                await inter.response.send_message("FlaVR, Friends and Community stay (you can rename them with /group edit).",
                                                  ephemeral=True)
                return
            moved = bot.store.move_group(g, "friends")
            for k in ("live_channel", "calendar_channel", "calendar_post"):
                bot.store.delete(f"{k}.{g}")        # its channels and post are forgotten (the post stays up)
            await inter.response.send_message(f"Removed {shown}; {moved} person/people moved to Friends.",
                                              ephemeral=True)

        @group_cmd.command(name="list", description="All groups, how many people, and their channels")
        async def group_list(inter: discord.Interaction):
            people = bot.store.people()
            lines = []
            for k, info in groups.all_groups().items():
                n = sum(1 for p in people if p["grp"] == k)
                live_ch, cal_ch = bot.store.get(f"live_channel.{k}"), bot.store.get(f"calendar_channel.{k}")
                lines.append(f"**{info['name']}** ({info['colour']}{', built in' if info['builtin'] else ''}): "
                             f"{n} people · go-live {f'<#{live_ch}>' if live_ch else 'not set'} · "
                             f"calendar {f'<#{cal_ch}>' if cal_ch else 'not set'}")
            await inter.response.send_message("\n".join(lines)[:1900], ephemeral=True, allowed_mentions=NO_PINGS)

        tree.add_command(group_cmd)

        calendar = app_commands.Group(name="calendar", description="The weekly stream calendar")
        style_choices = [app_commands.Choice(name=label, value=k) for k, (label, _) in X_STYLES.items()]
        week_choices = [app_commands.Choice(name="This week", value=0), app_commands.Choice(name="Next week", value=1),
                        app_commands.Choice(name="Last week (recap)", value=-1)]
        # the reviews (flavrpromo/calendar.py REVIEWS): Friday's Mon-Thu, Monday's Fri-Sun; the newest one
        review_choices = [app_commands.Choice(name=n, value=k) for k, n in REVIEW_NAMES.items()]

        focus_choices = [app_commands.Choice(name=n, value=v) for n, v in
                         [("Today", "today"), ("Tomorrow", "tomorrow"), ("This weekend (Fri to Sun)", "weekend")] +
                         [(d.title(), d) for d in focus.WEEKDAYS]]

        async def show_focus(inter: discord.Interaction, when: str, group: Optional[str], post: bool,
                             channel_id: str = "") -> None:
            """Just today / tomorrow / the weekend / a weekday (flavrpromo/focus.py): picture + list.
            Used by /calendar focus, and by /calendar view and /calendar post when their ``when`` is picked.
            In a talent channel (no group typed) only that person. ``post``: for everyone, in this channel,
            or in ``channel_id`` (/calendar post: the group's calendar channel)."""
            here = talent.person_for_channel(bot.store, inter.channel_id) if not group else None
            g = here.get("grp") or "flavr" if here else await pick_group(inter, group)
            if g is None:
                return
            await inter.response.defer(ephemeral=not post or bool(channel_id), thinking=True)
            label, dates = focus.pick_days(when, bot.calendar.clock(), bot.calendar.tz)
            f = focus.build(bot.calendar, g, label, dates, here["id"] if here else 0)
            png = await focus.png(bot.calendar, f)
            name = f"{when}.png"
            data = focus.embed(f, here["name"] if here else "")
            if channel_id:
                ok = await bot.cal_send(channel_id, data, png, name)
                await inter.followup.send("Posted." if ok else "Couldn't post in the calendar channel (deleted, or the "
                                          "bot can't write there).", ephemeral=True)
                return
            files = [discord.File(io.BytesIO(png), filename=name)] if png else []
            await inter.followup.send(embed=make_embed(data, name if png else ""),
                                      files=files, ephemeral=not post, allowed_mentions=NO_PINGS)

        async def show_review(inter: discord.Interaction, label: str, group: Optional[str], channel_id: str = "") -> None:
            """The newest week (Mon-Thu) or weekend (Fri-Sun) review: picture + list with its videos.
            Only to you, or posted in ``channel_id`` (/calendar post review:)."""
            g = await pick_group(inter, group)
            if g is None:
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            from .calendar_post import embed as cal_embed
            w, png = await bot.calendar.review_png(g, label)
            name = f"{label}-review.png"
            if channel_id:
                ok = await bot.cal_send(channel_id, cal_embed(w), png, name)
                await inter.followup.send("Posted." if ok else "Couldn't post in the calendar channel.", ephemeral=True)
                return
            files = [discord.File(io.BytesIO(png), filename=name)] if png else []
            await inter.followup.send(embed=make_embed(cal_embed(w), name if png else ""), files=files,
                                      ephemeral=True, allowed_mentions=NO_PINGS)

        @calendar.command(name="view", description="The calendar picture and list (only you see it)")
        @app_commands.choices(week=week_choices, when=focus_choices, review=review_choices)
        @app_commands.autocomplete(group=group_auto)
        @app_commands.describe(when="Just today, tomorrow, the weekend or a weekday instead of the whole week",
                               review="The newest week review (Mon to Thu) or weekend review (Fri to Sun)")
        async def calendar_view(inter: discord.Interaction, group: Optional[str] = None,
                                week: Optional[app_commands.Choice[int]] = None,
                                when: Optional[app_commands.Choice[str]] = None,
                                review: Optional[app_commands.Choice[str]] = None):
            if not bot.calendar:
                await inter.response.send_message("The calendar isn't running.", ephemeral=True)
                return
            if review:
                await show_review(inter, review.value, group)
                return
            if when:                                    # the focus view (flavrpromo/focus.py); ``week`` doesn't apply
                await show_focus(inter, when.value, group, False)
                return
            here = talent.person_for_channel(bot.store, inter.channel_id)
            if here and not group:
                # in a talent channel: that person's week as the text card (flavrpromo/talent.py)
                off = week.value if week else 0
                start = bot.calendar.week_of(off)
                if off < 0:
                    await inter.response.defer(ephemeral=True, thinking=True)
                    await bot.calendar.ensure_backfill(start)
                w = talent.only(bot.calendar.build(here.get("grp") or "flavr", start, recap=off < 0), here["id"])
                card = make_embed(talent.week_card(w, here["name"]))
                if inter.response.is_done():
                    await inter.followup.send(embed=card, ephemeral=True, allowed_mentions=NO_PINGS)
                else:
                    await inter.response.send_message(embed=card, ephemeral=True, allowed_mentions=NO_PINGS)
                return
            g = await pick_group(inter, group)          # answers "no such group" itself, so before the defer
            if g is None:
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            from .calendar_post import embed as cal_embed
            w, png = await bot.calendar.view_png(g, week.value if week else 0)
            name = "calendar.png"
            files = [discord.File(io.BytesIO(png), filename=name)] if png else []
            await inter.followup.send(embed=make_embed(cal_embed(w), name if png else ""), files=files,
                                      ephemeral=True, allowed_mentions=NO_PINGS)

        @calendar.command(name="focus", description="Just one day or the weekend: today, tomorrow, a weekday")
        @app_commands.choices(when=focus_choices)
        @app_commands.autocomplete(group=group_auto)
        @app_commands.describe(post="Post it in this channel for everyone (owner or Manage Server)")
        async def calendar_focus(inter: discord.Interaction, when: app_commands.Choice[str], group: Optional[str] = None,
                                 post: Optional[bool] = False):
            # flavrpromo/focus.py: the board's streams for those days, picture + list; in a talent channel only them
            if not bot.calendar:
                await inter.response.send_message("The calendar isn't running.", ephemeral=True)
                return
            if post and not await managers_only(inter):
                return
            await show_focus(inter, when.value, group, bool(post))

        @calendar.command(name="post", description="Post a fresh calendar now (owner or Manage Server)")
        @app_commands.autocomplete(group=group_auto)
        @app_commands.choices(when=focus_choices, review=review_choices)
        @app_commands.describe(when="Post just today, tomorrow, the weekend or a weekday (an extra post; the week stays)",
                               review="Post the newest week review (Mon to Thu) or weekend review (Fri to Sun) now")
        async def calendar_post_now(inter: discord.Interaction, group: Optional[str] = None,
                                    when: Optional[app_commands.Choice[str]] = None,
                                    review: Optional[app_commands.Choice[str]] = None):
            if not await managers_only(inter):
                return
            g = groups.find(group)
            if g is None:
                await pick_group(inter, group)          # answers "no such group"
                return
            if not bot.calendar or not bot.store.get(f"calendar_channel.{g}"):
                await inter.response.send_message("Pick its channel first: /setup calendar-channel.", ephemeral=True)
                return
            if review:
                await show_review(inter, review.value, g, channel_id=str(bot.store.get(f"calendar_channel.{g}")))
                return
            if when:
                # a one-off focus post in the group's calendar channel (the automatic ones: /setup day-posts)
                await show_focus(inter, when.value, g, True, channel_id=str(bot.store.get(f"calendar_channel.{g}")))
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            async with bot.calendar._lock:
                await bot.calendar.refresh(g, force_new=True)
            await inter.followup.send("Posted.", ephemeral=True)

        @calendar.command(name="refresh", description="Fill a week in from the channels' past streams (VODs)")
        @app_commands.choices(week=week_choices[::2])
        async def calendar_refresh(inter: discord.Interaction, week: Optional[app_commands.Choice[int]] = None):
            if not await managers_only(inter):
                return
            if not bot.calendar:
                await inter.response.send_message("The calendar isn't running.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            off = week.value if week else -1
            # by hand: YouTube is asked about everyone, not only people the free checks saw active
            added = await bot.calendar.ensure_backfill(bot.calendar.week_of(off), force=True, everyone=True)
            await inter.followup.send(f"Found {added} stream(s) the bot hadn't seen. Twitch keeps past broadcasts "
                                      "7 days (60 for partners); Kick has no list of past streams.", ephemeral=True)

        @calendar.command(name="share", description="DMs you copy-ready text for other Discords and X")
        @app_commands.choices(week=week_choices, style=style_choices, when=focus_choices, review=review_choices)
        @app_commands.autocomplete(group=group_auto)
        @app_commands.describe(style="X layout this time (default: /setup share-style)",
                               when="Just these days instead of the week (today, tomorrow, the weekend, a weekday)",
                               review="The newest week review (Mon to Thu) or weekend review (Fri to Sun)")
        async def calendar_share(inter: discord.Interaction, group: Optional[str] = None,
                                 week: Optional[app_commands.Choice[int]] = None,
                                 style: Optional[app_commands.Choice[str]] = None,
                                 when: Optional[app_commands.Choice[str]] = None,
                                 review: Optional[app_commands.Choice[str]] = None):
            here = talent.person_for_channel(bot.store, inter.channel_id)
            if here and not group and bot.calendar and (bot.may_manage(inter) or here.get("discord_user") == str(inter.user.id)):
                # in a talent channel: that person's own share text, DMed to whoever asked (flavrpromo/talent.py)
                await inter.response.defer(ephemeral=True, thinking=True)
                if when:            # just those days (flavrpromo/focus.py)
                    ok = await focus.share(bot.calendar, here.get("grp") or "flavr", when.value, "",
                                           here["id"], inter.user.id)
                else:
                    ok = await bot.calendar.share_person(here, week.value if week else 0, inter.user.id)
                await inter.followup.send("Sent to your DMs." if ok else "Couldn't DM you. Discord → this server → "
                                          "Privacy Settings → allow direct messages.", ephemeral=True)
                return
            if not await owner_only(inter):
                return
            if not bot.calendar:
                await inter.response.send_message("The calendar isn't running.", ephemeral=True)
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            if review:              # the review's package, its X Article included (?review= on the article page)
                ok = await bot.calendar.share_review(g, review.value, style.value if style else "")
            elif when:              # just those days (flavrpromo/focus.py); the X Article style falls back to "reply"
                ok = await focus.share(bot.calendar, g, when.value, style.value if style else "")
            else:
                ok = await bot.calendar.share(g, week.value if week else 0,
                                              style.value if style else "")
            await inter.followup.send("Sent to your DMs." if ok else "Couldn't DM you. Discord → this server → Privacy "
                                      "Settings → allow direct messages.", ephemeral=True)

        tree.add_command(calendar)

        # /host: Colette and Clark (flavrpromo/hosts.py, host_cards.py, host_picker.py). Pictures live in
        # DATA_DIR/hosts; kv hosts_on / hosts_only are the switches.
        host_cmd = app_commands.Group(name="host", description="Colette and Clark, the hosts who present the posts")
        host_choices = [app_commands.Choice(name=h["name"], value=k) for k, h in hosts.HOSTS.items()]
        kind_choices = [app_commands.Choice(name=n, value=k) for k, n in
                        [("happy", "Pose: happy (busy weeks)"), ("pointing", "Pose: pointing (a new game)"),
                         ("sleepy", "Pose: sleepy (quiet weeks)"), ("desk", "Desk (the sign-off card)"),
                         ("head", "Head (small face on go-live cards)")]]

        @host_cmd.command(name="picture", description="Upload a host's picture (a pose, their desk or their head)")
        @app_commands.choices(host=host_choices, kind=kind_choices)
        @app_commands.describe(kind="Which picture this is", file="PNG, JPG or WebP, up to 8 MB (see-through PNG is best)")
        async def host_picture(inter: discord.Interaction, host: app_commands.Choice[str],
                               kind: app_commands.Choice[str], file: discord.Attachment):
            if not await managers_only(inter):
                return
            if file.size > hosts.MAX_PICTURE:
                await inter.response.send_message("That picture is over 8 MB.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            err = hosts.save_picture(host.value, kind.value, await file.read(), file.filename)
            await inter.followup.send(err or f"Saved {host.name}'s {kind.value} picture.", ephemeral=True)

        @host_cmd.command(name="list", description="Whether hosts are on, and which pictures each host has")
        async def host_list(inter: discord.Interaction):
            only = str(bot.store.get("hosts_only") or "")
            lines = [f"Hosts are **{'on' if hosts.enabled(bot.store) else 'off'}**"
                     + (f", always {hosts.HOSTS[only]['name']}" if only in hosts.HOSTS else ", taking turns") + "."]
            for k, h in hosts.HOSTS.items():
                have = hosts.pictures(k)
                lines.append(f"{h['emoji']} **{h['name']}** ({h['role']}): "
                             + " · ".join(f"{kind} {'✅' if ok else '—'}" for kind, ok in have.items()))
            waiting = host_picker.waiting(bot.store)
            if waiting and bot.calendar:
                lines.append(f"{len(waiting)} review(s) waiting for your picks: {host_picker.link(bot.calendar)}")
            await inter.response.send_message("\n".join(lines), ephemeral=True, allowed_mentions=NO_PINGS)

        @host_cmd.command(name="preview", description="A host's opener or desk card for the newest review (only you see it)")
        @app_commands.choices(host=host_choices, review=review_choices,
                              card=[app_commands.Choice(name="Opener (before the board)", value="opener"),
                                    app_commands.Choice(name="Desk sign-off (after the board)", value="desk")])
        @app_commands.autocomplete(group=group_auto)
        async def host_preview(inter: discord.Interaction, host: app_commands.Choice[str],
                               review: app_commands.Choice[str], card: app_commands.Choice[str],
                               group: Optional[str] = None):
            if not bot.calendar:
                await inter.response.send_message("The calendar isn't running.", ephemeral=True)
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            await inter.response.defer(ephemeral=True, thinking=True)
            # the first candidate line in each slot, like the picker page before anything is picked
            p = host_picker.make(bot.store, g, review.value, bot.calendar.build_review(g, review.value), "", host.value)
            png = None
            if bot.calendar.shooter is not None:
                try:
                    png = await bot.calendar.shooter.png(host_picker.card_html(p, card.value))
                except Exception as e:                  # no Chromium: say so instead of failing
                    log.warning("host preview failed: %s", e)
            if not png:
                await inter.followup.send("Couldn't draw the card (Chromium isn't available).", ephemeral=True)
                return
            await inter.followup.send(files=[discord.File(io.BytesIO(png), filename=f"{host.value}-{card.value}.png")],
                                      ephemeral=True)

        @host_cmd.command(name="setup", description="Turn the hosts on or off, or always use one of them")
        @app_commands.choices(only=[app_commands.Choice(name="Take turns (random, never 3 in a row)", value="any")]
                              + host_choices)
        @app_commands.describe(on="On: hosts speak on go-live cards, and reviews wait for your picks on the picker page",
                               only="Take turns, or always the same host")
        async def host_setup(inter: discord.Interaction, on: bool, only: Optional[app_commands.Choice[str]] = None):
            if not await managers_only(inter):
                return
            bot.store.put("hosts_on", bool(on))
            if only is not None:
                bot.store.put("hosts_only", "" if only.value == "any" else only.value)
            text = ("Hosts are on. Go-live cards get a host line, and the Friday / Monday reviews wait for your "
                    f"picks at {host_picker.link(bot.calendar) if bot.calendar else '/hosts/pick'} "
                    "(I DM you the link when one is ready)." if on else
                    "Hosts are off. Cards and reviews post as before.")
            await inter.response.send_message(text, ephemeral=True)

        tree.add_command(host_cmd)

        setup = app_commands.Group(name="setup", description="Bot settings (owner or Manage Server)")

        @setup.command(name="live-channel", description="Where go-live posts for a group go")
        @app_commands.autocomplete(group=group_auto)
        async def setup_live(inter: discord.Interaction, group: str, channel: discord.TextChannel):
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            bot.store.put(f"live_channel.{g}", str(channel.id))
            await inter.response.send_message(f"{groups.name(g)} go-live posts go to {channel.mention}.", ephemeral=True)

        @setup.command(name="calendar-channel", description="Where the weekly calendar and recap go")
        @app_commands.autocomplete(group=group_auto)
        async def setup_calendar(inter: discord.Interaction, group: str, channel: discord.TextChannel):
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            bot.store.put(f"calendar_channel.{g}", str(channel.id))
            bot.store.put(f"calendar_post.{g}", {})       # a fresh post in the new channel
            if bot.calendar:
                bot.calendar.poke()
            await inter.response.send_message(f"The {groups.name(g)} calendar goes to {channel.mention}; the first post "
                                              "comes within a minute.", ephemeral=True)

        def time_words(minutes: Optional[int]) -> str:
            if minutes is None:
                return "off"
            h, m = divmod(int(minutes), 60)
            return f"{(h % 12) or 12}{f':{m:02d}' if m else ''} {'AM' if h < 12 else 'PM'}"

        weekday_choices = [app_commands.Choice(name=d.title(), value=i) for i, d in enumerate(focus.WEEKDAYS)]

        @setup.command(name="day-posts", description="Automatic Today / Tomorrow / This weekend posts and their times")
        @app_commands.autocomplete(group=group_auto)
        @app_commands.choices(weekend_day=weekday_choices)
        @app_commands.describe(channel="Where they go (left out: stop them all)",
                               today='Time of the Today post, like "10am" or "off" (default 10 AM)',
                               tomorrow='Time of an evening Tomorrow preview, like "8pm" (default off)',
                               weekend='Time of the This weekend post, or "off" (default 10 AM)',
                               weekend_day="Day of the This weekend post (default Friday)")
        async def setup_day_posts(inter: discord.Interaction, group: str, channel: Optional[discord.TextChannel] = None,
                                  today: Optional[str] = None, tomorrow: Optional[str] = None,
                                  weekend: Optional[str] = None,
                                  weekend_day: Optional[app_commands.Choice[int]] = None):
            # kv day_posts.<group>, read by flavrpromo/focus.py tick (every minute, inside the calendar loop);
            # times are minutes after midnight in TZ, None = off
            if not await managers_only(inter):
                return
            g = await pick_group(inter, group)
            if g is None:
                return
            old = bot.store.get(f"day_posts.{g}") or {}
            if channel is None:
                bot.store.put(f"day_posts.{g}", {})
                await inter.response.send_message(f"No more automatic day posts for {groups.name(g)}.", ephemeral=True)
                return
            s: Dict[str, Any] = {"channel": str(channel.id),
                                 "weekend_day": weekend_day.value if weekend_day else
                                 int(old.get("weekend_day", focus.DEFAULT_WEEKEND_DAY))}
            for kind, typed, default in (("today", today, focus.DEFAULT_TIME), ("tomorrow", tomorrow, None),
                                         ("weekend", weekend, focus.DEFAULT_TIME)):
                if typed is None:
                    s[kind] = old.get(kind, default) if old.get("channel") else default
                elif typed.strip().lower() in ("off", "no", "none", "-"):
                    s[kind] = None
                else:
                    m = parse_time(typed)
                    if m is None:
                        await inter.response.send_message(f"Couldn't read '{typed}' as a time. Try 10am, 6:30pm, "
                                                          "18:30 or off.", ephemeral=True)
                        return
                    s[kind] = m
            bot.store.put(f"day_posts.{g}", s)
            day = focus.WEEKDAYS[s["weekend_day"]].title()
            await inter.response.send_message(
                f"{groups.name(g)} day posts in {channel.mention} (only when something's on):\n"
                f"• Today: {time_words(s['today'])}\n• Tomorrow preview: {time_words(s['tomorrow'])}\n"
                f"• This weekend: {day + 's ' + time_words(s['weekend']) if s['weekend'] is not None else 'off'}\n"
                "Each is updated as people go live and end. With /pings share on, the copy-ready text follows "
                "each one in your DMs.", ephemeral=True)

        @setup.command(name="share-style", description="Default layout of the copy-ready X text")
        @app_commands.choices(style=[app_commands.Choice(name=label, value=k) for k, (label, _) in X_STYLES.items()])
        @app_commands.describe(bold_days="Day headings in bold-looking letters (screen readers skip them)",
                               hashtags="A line at the end, like #FlaVR #vtuber (- removes it)",
                               tag_people="Turn the X handles from /friend x into real tags (default off)")
        async def setup_share_style(inter: discord.Interaction, style: app_commands.Choice[str],
                                    bold_days: Optional[bool] = None, hashtags: Optional[str] = None,
                                    tag_people: Optional[bool] = None):
            if not await owner_only(inter):
                return
            bot.store.put("share_x_style", style.value)
            if bold_days is not None:
                bot.store.put("share_x_bold", bold_days)
            if tag_people is not None:
                bot.store.put("share_x_tag", tag_people)
            if hashtags is not None:
                tags = " ".join(t if t.startswith("#") else "#" + t for t in hashtags.replace(",", " ").split()
                                if t not in ("-", "none"))
                bot.store.put("share_x_tags", tags[:200])
            extra = []
            if bot.store.get("share_x_bold"):
                extra.append("bold day headings")
            if bot.store.get("share_x_tags"):
                extra.append(f"ending with {bot.store.get('share_x_tags')}")
            extra.append("tagging people's X handles" if bot.store.get("share_x_tag") else "nobody tagged")
            await inter.response.send_message(f"X text: {X_STYLES[style.value][1]}" + (f"; {', '.join(extra)}" if extra
                                              else "") + ".", ephemeral=True)

        @setup.command(name="review-times", description="When the Friday week review and Monday weekend review post")
        @app_commands.describe(week="Friday's review of Monday to Thursday: a time (10am) or off",
                               weekend="Monday's review of Friday to Sunday: a time (10am) or off")
        async def setup_review_times(inter: discord.Interaction, week: Optional[str] = None, weekend: Optional[str] = None):
            # flavrpromo/calendar_post.py review_times (kv "review_times"; default 10 AM both)
            if not await managers_only(inter):
                return
            have = dict(bot.store.get("review_times") or {})
            for label, text in (("week", week), ("weekend", weekend)):
                if text is None:
                    continue
                if text.strip().lower() in ("off", "none", "no"):
                    have[label] = None
                    continue
                m = parse_time(text)
                if m is None:
                    await inter.response.send_message(f"I couldn't read \"{text}\" as a time. Try 10am or 6:30pm.",
                                                      ephemeral=True)
                    return
                have[label] = m
            bot.store.put("review_times", have)
            t = bot.calendar.review_times() if bot.calendar else {}
            words = lambda m: "off" if m is None else time_words(m)      # noqa: E731
            await inter.response.send_message(f"Week review (Monday to Thursday): Friday {words(t.get('week'))}. "
                                              f"Weekend review (Friday to Sunday): Monday {words(t.get('weekend'))}.",
                                              ephemeral=True)

        @setup.command(name="youtube-check", description="YouTube deep check for streams scheduled far ahead (100 quota units each)")
        @app_commands.choices(how_often=[app_commands.Choice(name="Off (default)", value="off"),
                                         app_commands.Choice(name="Daily", value="daily"),
                                         app_commands.Choice(name="Every 48 hours", value="48h"),
                                         app_commands.Choice(name="Weekly", value="weekly")])
        async def setup_youtube_check(inter: discord.Interaction, how_often: app_commands.Choice[str]):
            # flavrpromo/platforms/youtube.py DEEP_CHECK: one search.list per followed YouTube channel each run;
            # the cheap uploads-list check (every 6 h, 1 unit) runs either way. Saved in kv "youtube_deep_check";
            # flavrpromo/__main__.py reads it at start.
            if not await managers_only(inter):
                return
            from .platforms.youtube import DEEP_CHECK
            bot.store.put("youtube_deep_check", how_often.value)
            yt = bot.watcher.checkers.get("youtube")
            if yt is not None:
                yt.search_every = DEEP_CHECK[how_often.value]
            n = len([a for a in bot.store.accounts("youtube") if a.get("platform_id")])
            cost = (f" Each run asks about {n} YouTube channel(s): about {n * 100} of the 10,000 free daily quota units."
                    if how_often.value != "off" else "")
            await inter.response.send_message(
                f"YouTube deep check: **{how_often.name}**.{cost} Either way, each channel's 50 newest videos are "
                "read every 6 hours (1 unit), which catches streams scheduled weeks ahead in most cases.", ephemeral=True)


        tree.add_command(setup)


        talent.register(tree, bot, managers_only, day_choices, parse_time)     # /talent and /me
        promo.register(tree, bot, managers_only)    # community calendar: message menu + /community (flavrpromo/promo.py)
