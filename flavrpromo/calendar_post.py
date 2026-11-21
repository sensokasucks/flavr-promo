"""
Keeps each group's weekly calendar post in Discord, plus the Friday and Monday reviews and the
owner's calendar pings. The data is flavrpromo/calendar.py, the picture flavrpromo/render.py.

The week's rhythm (times in TZ; CALENDAR_PREVIEW_HOUR, review times with /setup review-times):
  Sunday 10 AM   a NEW post for the new week: the picture + a day-by-day list with links.
                 Before 10 AM on Sunday last week's post stays up (it gets its final edits).
  all week       that post is edited in place whenever the board changes (someone schedules,
                 goes live, ends), checked every minute and right after a go-live / end; while
                 someone is live it is also redrawn every LIVE_REDRAW for a fresh live preview.
  Friday 10 AM   the WEEK review: Monday to Thursday, every stream with real start and end times,
                 length, VOD links and the LATE NOTICE tag, and the videos / Shorts / premieres
                 ("Also this week").
  Monday 10 AM   the WEEKEND review: Friday to Sunday, the same way. (Owner 2026-11-20: weekends
                 are the busy days and people have time for VODs; this replaced the Saturday 11 PM
                 recap. The two cover every day once; calendar.py REVIEWS / review_range.)
  With hosts on (/host setup on) a review waits at its time for the owner's picks on the picker
  page, then posts as host opener card, board, host desk card (flavrpromo/host_picker.py). The
  Sunday board waits the same way for the week-ahead opener card (owner 2026-11-21), but only up
  to the wait limit (kv host_preview_wait hours, default 3; 0 = for ever): then it posts without
  the host. Last week's post keeps its edits while it waits.
A group's posts only start once /setup calendar-channel picks its channel (posted at once, even
mid-week). If the post is deleted, the next change makes a new one.

Calendar pings (the "calendar" kind in /pings): what changed on the board ("Lulu scheduled Thu
7 PM", "Pippa went live", "new week posted"), collected for PING_BATCH and sent as one DM per
group with THAT group's board ("VTC calendar updated: Mumkey Dee ended" comes with the VTC board;
fixed 2026-11-20, it used to always attach FlaVR's). During quiet hours they wait like other pings
(text only).

Saved in the database (kv):
  calendar_channel.<group>  channel id (/setup calendar-channel)
  calendar_post.<group>     {week, channel, message, sig, drawn_at}: the live board post
  calendar_review.<label>.<group>  the first day (ISO date) of the newest review posted
  preview_opened.<group>    the week (ISO date) whose host preview opener went out (posted once)
  preview_host.<group>      who presented that preview (the week's board is drawn in their look)
  host_board                draw boards in the presenting host's look (default on with hosts on;
                            settings page, Hosts). The week's host is kept in calendar_post.<group>
                            "host"; a review's board takes the review's host.
  review_times              {"week": minutes, "weekend": minutes or None = off} (/setup review-times;
                            default 10 AM both: REVIEW_DEFAULTS)
  backfill.<week>           when that week (ISO date of its Sunday) was last filled in from the
                            platforms (``ensure_backfill``; the bot only knows what it saw live)

Filling in (``backfill``, set by flavrpromo/__main__.py to Watcher.backfill): last week and this week
once at start-up, a past week the first time someone looks at it (/calendar view, the web page),
again once a week is over, and right before each review. /calendar refresh does it by hand.

Who calls it: flavrpromo/__main__.py builds one and runs ``run()``; the watcher's start / end /
scheduled callbacks call ``poke()``; flavrpromo/bot.py's /calendar and /setup calendar-channel use
``view_png``, ``embed`` and ``refresh``. ``discord`` is the bot (PromoBot, flavrpromo/bot.py): it must offer
``cal_send(channel, embed, png, name)`` → message id or "", ``cal_edit(channel, message, embed,
png, name)`` → True/False, ``dm_owner(text, png=None)`` and ``dm_share(messages, png, user_id=0)``;
``cal_pin(channel, message, on)`` is optional (talent week cards are pinned with it).

Talent channels (flavrpromo/talent.py): ``tick`` also keeps each person's own week card and recap.
Focus posts (flavrpromo/focus.py): ``tick`` also keeps the automatic "Today" / "This weekend" posts.

Share (flavrpromo/share.py): after the Sunday post and each review, when the /pings switch
"share" is on, the owner gets copy-ready text for other Discords and X (held until quiet hours
end). /calendar share sends it any time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .calendar import UPLOAD_ICONS, UPLOAD_NAMES, UPLOADS_HEAD, Tile, Week, build_week, changes, review_range, week_start
from .share import X_STYLES, article, channel_url, discord_parts, x_posts
from .render import COVER_H, COVER_W, ImageCache, Screenshotter, cover, day_card, logo_data_url, page
from . import groups, host_cards, host_picker, hosts, talent
from .store import Store

log = logging.getLogger("flavrpromo.calendar_post")
LIVE_REDRAW = 20 * 60.0         # while someone is live, redraw this often (fresh live preview)
PING_BATCH = 10 * 60.0          # calendar pings: changes within this window arrive as one DM
TICK = 60.0                     # how often the loop looks (a poke wakes it early)
DOTS = {"youtube": "▶️", "twitch": "🟣", "kick": "🟢"}
FIELD_MAX = 1024                # Discord: one embed field's text
EMBED_MAX = 5600                # Discord: 6000 for a whole embed, minus room for title / footer
REVIEW_DEFAULTS = {"week": 600, "weekend": 600}    # minutes after midnight: Friday / Monday 10 AM
REVIEW_WEEKDAY = {"week": 4, "weekend": 0}          # Python weekday the review posts on: Friday, Monday


def _safe(text: str, n: int = 60) -> str:
    """A title fit for a markdown link: no brackets / backticks, cut to ``n`` characters."""
    t = (text or "").replace("[", "(").replace("]", ")").replace("`", "'").replace("*", "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _hm(sec: float) -> str:
    m = int(sec) // 60
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def line(t: Tile, recap: bool) -> str:
    """One stream in the text list under the picture. <t:…:t> shows in each reader's own time zone."""
    dots = "".join(DOTS.get(p, "") for p in t.platforms)
    when = f"<t:{int(t.at)}:t>"
    title = _safe(t.title or t.game)
    if t.kind == "live":
        watch = f"[{title or 'watch'}]({t.url})" if t.url else title
        return f"🔴 {when} **{t.name}** {dots} live now · {watch}"
    if t.kind == "past":
        tail = f"[{title or 'VOD'}]({t.url})" if t.url else title
        late = " · ⏰ late notice" if recap and t.late else ""
        return f"✅ {when}–<t:{int(t.end or t.at)}:t> **{t.name}** {dots} {_hm(t.length)}{late}" + (f" · {tail}" if tail else "")
    tail = f"[{title or 'stream'}]({t.url})" if t.url else title
    return f"🗓️ {when} **{t.name}** {dots}" + (f" · {tail}" if tail else "")


def upload_line(u: Dict[str, Any]) -> str:
    """One "Also this week" line: icon, when (each reader's own time zone), who, the linked title."""
    title = _safe(u.get("title") or UPLOAD_NAMES.get(u["kind"], "video"))
    tail = f"[{title}]({u['url']})" if u.get("url") else title
    return f"{UPLOAD_ICONS.get(u['kind'], '🎬')} <t:{int(u['at'])}:d> **{u['name']}** · {tail}"


def embed(week: Week) -> Dict[str, Any]:
    """The post's text as plain data (flavrpromo/bot.py turns it into a discord.Embed):
    {title, colour, fields: [(name, value)], footer}. Days with nothing are left out; a day too
    long for one field ends with "+N more"."""
    # recap posts keep their old "FlaVR: week in review" wording; previews read "This week in FlaVR" /
    # "This week with Art Pals" (groups.heading, also used by share.py)
    title = (f"{groups.heading(week.group, True, week.label)} · {week.range_text}" if week.label
             else f"{groups.name(week.group)}: week in review · {week.range_text}" if week.recap
             else f"{groups.heading(week.group, False)} · {week.range_text}")
    fields: List[Tuple[str, str]] = []
    total = len(title)
    today = week.today_index()
    for i, tiles in enumerate(week.days):
        if not tiles:
            continue
        date = week.date_of(i)
        head = f"{week.day_name(i).title()} {date:%b} {date.day}" + (" · today" if i == today and not week.recap else "")
        lines: List[str] = []
        used = 0
        for n, t in enumerate(tiles):
            text = line(t, week.recap)
            if used + len(text) + 12 > FIELD_MAX or total + used + len(text) > EMBED_MAX:
                lines.append(f"+{len(tiles) - n} more")
                break
            lines.append(text)
            used += len(text) + 1
        value = "\n".join(lines)
        total += len(head) + len(value)
        fields.append((head, value))
    if week.uploads:
        # a review's videos / Shorts / premieres, after the days ("Also this week")
        lines, used = [], 0
        for n, u in enumerate(week.uploads):
            text = upload_line(u)
            if used + len(text) + 12 > FIELD_MAX or total + used + len(text) > EMBED_MAX:
                lines.append(f"+{len(week.uploads) - n} more")
                break
            lines.append(text)
            used += len(text) + 1
        fields.append((UPLOADS_HEAD, "\n".join(lines)))
    if week.recap:
        foot = f"{week.stream_count} streams · {week.hours_live:.0f} hours live"
    else:
        foot = "Times below are in your own time zone"
    if week.quiet:
        foot += (" · no streams: " if week.recap else " · nothing on yet: ") + ", ".join(week.quiet)
    return {"title": title, "colour": groups.colour_int(week.group), "fields": fields,
            "footer": foot[:2000], "empty": not fields}


class CalendarPoster:
    def __init__(self, store: Store, discord: Any, images: ImageCache, shooter: Optional[Screenshotter],
                 tz: str = "America/New_York", preview_hour: int = 10,
                 ping: Optional[Callable[[], bool]] = None, quiet: Optional[Callable[[], bool]] = None,
                 hold: Optional[Callable[[str], Any]] = None, clock: Callable[[], float] = time.time,
                 backfill: Optional[Callable[[float, float], Awaitable[int]]] = None,
                 share_on: Optional[Callable[[], bool]] = None):
        self.store = store
        self.discord = discord
        self.images = images
        self.shooter = shooter              # None = text-only posts (no Chromium)
        try:
            self.tz = ZoneInfo(tz)
        except Exception:
            self.tz = ZoneInfo("America/New_York")
        self.preview_hour = preview_hour    # CALENDAR_PREVIEW_HOUR (Sunday)
        self.ping_on = ping or (lambda: False)      # Pinger switch "calendar"
        self.quiet = quiet or (lambda: False)       # Pinger.quiet_now
        self.hold = hold                            # Pinger.ping("calendar", text): held during quiet hours
        self.clock = clock
        self.backfill = backfill                    # Watcher.backfill(start, end, everyone) → sessions added
        self.share_on = share_on or (lambda: False)  # Pinger switch "share"
        self._shares: List[Tuple[Week, Optional[bytes]]] = []    # waiting for quiet hours to end
        # the bot's own web address on the home network ("http://192.168.0.20:3871"), for the X Article
        # page link in the share DM; set by flavrpromo/__main__.py from WEB_ADDRESS (or found by itself)
        self.web_url = ""
        self.kobold = None                  # flavrpromo/kobold.py Kobold when KoboldCpp is set up (settings_page.apply)
        self.kobold_env: dict = {}          # KOBOLD_URL / KOBOLD_KEY from the environment (flavrpromo/__main__.py)
        self.http = None                    # the shared aiohttp session (flavrpromo/__main__.py), for Kobold
        self._poke = asyncio.Event()
        self._lock = asyncio.Lock()
        self._seen: Dict[str, Tuple[str, Dict[str, Tile]]] = {}    # group → (week, {key: tile}) last look
        self._pending: Dict[str, List[str]] = {}      # group → change lines waiting for the next DM
        self._pending_at = 0.0
        self._png: Dict[str, bytes] = {}                # group → its newest board picture (for that DM)
        self.errors: Dict[str, str] = {}

    # ── outside calls ──────────────────────────────────────────────────
    def poke(self, *_: Any) -> None:
        """Something changed (go-live, end, new schedule): look again within a few seconds."""
        self._poke.set()

    async def on_scheduled(self, person: Dict[str, Any], item: Dict[str, Any]) -> None:
        self.poke()

    def week_of(self, offset: int = 0, now: Optional[float] = None) -> datetime:
        """Sunday 00:00 of this week (0), last week (-1) or next week (1)."""
        start = week_start(self.clock() if now is None else now, self.tz)
        if offset:
            d = (start + timedelta(days=7 * offset)).date()
            start = datetime(d.year, d.month, d.day, tzinfo=self.tz)    # DST-safe
        return start

    def build(self, group: str, start: datetime, recap: bool = False) -> Week:
        return build_week(self.store, group, start, self.clock(), self.tz, recap=recap)

    def review_times(self) -> Dict[str, Optional[int]]:
        """When the reviews post (minutes after midnight on Friday / Monday; None = not by itself)."""
        return {**REVIEW_DEFAULTS, **(self.store.get("review_times") or {})}

    def build_review(self, group: str, label: str, now: Optional[float] = None) -> Week:
        """The newest "week" (Mon-Thu) or "weekend" (Fri-Sun) review of a group (calendar.review_range)."""
        start, n = review_range(label, self.clock() if now is None else now, self.tz)
        return build_week(self.store, group, start, self.clock(), self.tz, recap=True, days=n, label=label)

    async def backfill_review(self, label: str) -> None:
        """Fill in the board weeks a review's days fall in (a weekend review spans two)."""
        start, n = review_range(label, self.clock(), self.tz)
        last = start + timedelta(days=n - 1)
        for w in {week_start(start.timestamp(), self.tz), week_start(last.timestamp(), self.tz)}:
            await self.ensure_backfill(w, force=True)

    async def review_png(self, group: str, label: str) -> Tuple[Week, Optional[bytes]]:
        """/calendar view review: (the review, its picture), filled in from the platforms first."""
        await self.backfill_review(label)
        week = self.build_review(group, label)
        return week, await self.png(week)

    def board_host(self, key: str = "") -> str:
        """``key`` when boards are drawn in the host's look (hosts on and kv host_board not off), else ""."""
        ok = key in hosts.HOSTS and hosts.enabled(self.store) and self.store.get("host_board") is not False
        return key if ok else ""

    async def png(self, week: Week, host: str = "") -> Optional[bytes]:
        """The picture, or None when Chromium isn't there / fails (posts go out as text then).
        ``host``: draw it in that host's look (flavrpromo/host_cards.py ``board``; checked with board_host)."""
        if self.shooter is None:
            return None
        try:
            await self.images.fetch_all(week)
            host = self.board_host(host)
            if host:
                return await self.shooter.png(host_cards.board(host, week, self.images.data_url, logo=logo_data_url()))
            return await self.shooter.png(page(week, self.images.data_url, logo=logo_data_url()))
        except Exception as e:
            self.errors["picture"] = str(e) or type(e).__name__
            log.warning("calendar picture failed: %s", self.errors["picture"])
            return None

    async def cover_png(self, week: Week) -> Optional[bytes]:
        """The 5:2 X Article cover (render.cover), or None without Chromium. flavrpromo/web.py serves it."""
        if self.shooter is None:
            return None
        try:
            await self.images.fetch_all(week)
            return await self.shooter.png(cover(week, self.images.data_url, logo=logo_data_url()), (COVER_W, COVER_H))
        except Exception as e:
            log.warning("cover picture failed: %s", e)
            return None

    async def day_png(self, week: Week, day: int) -> Optional[bytes]:
        """Day ``day`` (0 = Sunday) as one 16:9 picture (render.day_card), for the X Article."""
        if self.shooter is None:
            return None
        try:
            await self.images.fetch_all(week)
            return await self.shooter.png(day_card(week, day, self.images.data_url, logo=logo_data_url()))
        except Exception as e:
            log.warning("day picture failed: %s", e)
            return None

    async def ensure_backfill(self, start: datetime, force: bool = False, everyone: bool = False) -> int:
        """Fill the week starting ``start`` from the platforms' past streams, unless that was already
        done after the week ended (a week still running is done again once it's over). ``force``:
        always (start-up, before each review, /calendar refresh). ``everyone``: YouTube (quota) for
        every person, not only the ones active those days (/calendar refresh; Watcher.backfill).
        Returns how many streams were added."""
        if self.backfill is None:
            return 0
        now = self.clock()
        if start.timestamp() > now:
            return 0                                # a future week has no past streams
        key = f"backfill.{start.date().isoformat()}"
        end = (start + timedelta(days=7)).timestamp()
        if not force and float(self.store.get(key) or 0) >= min(end, now - 6 * 3600):
            return 0
        try:
            added = await self.backfill(start.timestamp(), min(end, now), everyone)
        except Exception:
            log.exception("filling in past streams failed")
            return 0
        self.store.put(key, now)
        if added:
            self.poke()
        return added

    async def view_png(self, group: str, offset: int = 0) -> Tuple[Week, Optional[bytes]]:
        """/calendar: (the week, its picture). Last week is shown as a recap."""
        start = self.week_of(offset)
        if offset < 0:
            await self.ensure_backfill(start)
        week = self.build(group, start, recap=offset < 0)
        post = self.store.get(f"calendar_post.{group}") or {}
        host = str(post.get("host") or "") if offset == 0 and post.get("week") == start.date().isoformat() else ""
        return week, await self.png(week, host)        # this week: in its host's look, like the post

    def share_messages(self, week: Week, style: str = "") -> List[str]:
        """The copy-ready texts: a short note, the Discord version, then each X post. ``style``: an X
        style (flavrpromo/share.py X_STYLES); "" = the saved default (/setup share-style)."""
        style = style if style in X_STYLES else (self.store.get("share_x_style") or "reply")
        if style == "article" and getattr(week, "heading", ""):
            style = "reply"         # a focus share (flavrpromo/focus.py): the Article page shows whole weeks only
        people = self.store.people(week.group)
        handles = {p["id"]: p.get("x_handle") or "" for p in people}
        if style == "article":
            # X Articles take rich text, which a DM can't hold: link the page that has a Copy button
            # (flavrpromo/web.py /calendar/article); share.article builds what that page shows
            title = article(week)["title"]
            off = round((week.start - self.week_of(0)).days / 7)
            q = f"?group={week.group}" + (f"&review={week.label}" if week.label else
                                          {1: "&week=next", -1: "&week=last"}.get(off, ""))
            url = f"{self.web_url or 'http://<this PC>:3870'}/calendar/article{q}"
            dc = discord_parts(week)
            note = ("📋 Copy-ready calendar. Long-press (phone) or right-click (PC) a message → Copy Text. "
                    f"Next: the Discord version{'' if len(dc) == 1 else f', one message per day ({len(dc)})'}, "
                    "then the X Article.")
            return [note] + dc + [f"📰 **X Article:** {title}\nOpen <{url}> on your home network, press "
                                  "**Copy article**, and paste it into a new Article on X (Write → Article). "
                                  "The page also has the title and the picture for the cover."]
        xs = x_posts(week, handles, style, bold=bool(self.store.get("share_x_bold")),
                     tags=str(self.store.get("share_x_tags") or ""), channels={p["id"]: channel_url(p) for p in people},
                     tag_people=bool(self.store.get("share_x_tag")))
        after = {"reply": f"the X post, then {len(xs) - 1} links post(s), one per day, to paste as replies."
                 if len(xs) > 1 else "the X post.",
                 "one": "the X post.", "thread": f"an X thread of {len(xs)} posts." if len(xs) > 1 else "the X post."}
        dc = discord_parts(week)
        dc_what = "the Discord version" if len(dc) == 1 else f"the Discord version, one message per day ({len(dc)}, paste them in order)"
        note = ("📋 Copy-ready calendar. Long-press (phone) or right-click (PC) a message → Copy Text. "
                f"Next: {dc_what}, then " + after.get(style, "the X post."))
        return [note] + dc + xs

    async def share(self, group: str, offset: int = 0, style: str = "") -> bool:
        """/calendar share: DM the package for this (0), next (1) or last (-1, the recap) week now."""
        start = self.week_of(offset)
        if offset < 0:
            await self.ensure_backfill(start)
        week = self.build(group, start, recap=offset < 0)
        return await self._send_share(week, await self.png(week), style)

    async def share_review(self, group: str, label: str, style: str = "") -> bool:
        """/calendar share review: DM the package for the newest week / weekend review now."""
        week, png = await self.review_png(group, label)
        return await self._send_share(week, png, style)

    async def share_person(self, person: Dict[str, Any], offset: int = 0, user_id: int = 0) -> bool:
        """/me share and /calendar share in a talent channel (flavrpromo/talent.py): the package for one
        person's week, DMed to ``user_id`` (the one who asked; 0 = the owner). No picture (the board
        with one person on it is mostly empty) and never the X Article style (its page shows a whole
        group): the saved X style, else "reply"."""
        start = self.week_of(offset)
        if offset < 0:
            await self.ensure_backfill(start)
        week = talent.only(self.build(person.get("grp") or "flavr", start, recap=offset < 0), person["id"])
        style = self.store.get("share_x_style") or "reply"
        style = "reply" if style == "article" else style
        try:
            await self.discord.dm_share(self.share_messages(week, style), None, user_id=user_id)
            return True
        except Exception:
            log.exception("talent share DM failed")
            return False

    async def _send_share(self, week: Week, png: Optional[bytes], style: str = "") -> bool:
        try:
            await self.discord.dm_share(self.share_messages(week, style), png)
            return True
        except Exception:
            log.exception("calendar share DM failed")
            return False

    def _share_later(self, week: Week, png: Optional[bytes]) -> None:
        """After an automatic post: queue the package if the switch is on (sent by flush_shares)."""
        if self.share_on():
            self._shares.append((week, png))

    async def flush_shares(self) -> None:
        if self._shares and not self.quiet():
            todo, self._shares = self._shares, []
            for week, png in todo:
                await self._send_share(week, png)

    # ── the loop ───────────────────────────────────────────────────────
    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("calendar update failed")
            try:
                await asyncio.wait_for(self._poke.wait(), timeout=TICK)
                await asyncio.sleep(5)          # let a burst of changes settle into one edit
            except asyncio.TimeoutError:
                pass
            self._poke.clear()

    async def tick(self) -> None:
        async with self._lock:
            for g in groups.keys():         # FlaVR, Friends and any /group add ones
                if self.store.get(f"calendar_channel.{g}"):
                    await self.refresh(g)
            await talent.refresh_all(self)  # each talent channel's week card + recap (flavrpromo/talent.py)
            from . import focus             # late import: focus.py imports this module's ``line``
            await focus.tick(self)          # automatic "Today" / "This weekend" posts (/setup day-posts)
            self.images.prune()
            await self.flush_pings()
            await self.flush_shares()

    async def refresh(self, group: str, force_new: bool = False) -> None:
        """Bring one group's posts up to date (see the module notes for the rhythm)."""
        channel = str(self.store.get(f"calendar_channel.{group}") or "")
        if not channel:
            return
        now = self.clock()
        local = datetime.fromtimestamp(now, self.tz)
        this_week = self.week_of(0, now)
        post = self.store.get(f"calendar_post.{group}") or {}
        wday = (local.weekday() + 1) % 7               # 0 = Sunday

        # Friday: the week review (Mon-Thu); Monday: the weekend review (Fri-Sun); once each
        for label, at in self.review_times().items():
            if at is None or local.weekday() != REVIEW_WEEKDAY[label] or local.hour * 60 + local.minute < at:
                continue
            start, _ = review_range(label, now, self.tz)
            key = f"calendar_review.{label}.{group}"
            if self.store.get(key) == start.date().isoformat():
                continue
            # hosts on (/host setup on): the review waits for the owner's picks on the picker page
            # (flavrpromo/host_picker.py; the first wait DMs the link, one nudge after an hour), then
            # goes out as the host's opener card, the board, and the host's desk sign-off card
            picked = None
            if hosts.enabled(self.store):
                picked = await host_picker.ready(self, group, label, start.date().isoformat())
                if picked is None:
                    continue
                if not picked.get("opener_sent"):     # once, even if the board has to try again next tick
                    await host_picker.post_card(self, channel, picked, "opener")
                    picked["opener_sent"] = True
                    self.store.put(host_picker.key_of(label, group), picked)
            else:
                await self.backfill_review(label)       # streams missed while the bot was down (ready() does it too)
            week = self.build_review(group, label)
            png = await self.png(week, picked["host"] if picked else "")
            if await self.discord.cal_send(channel, embed(week), png, f"{label}-review-{start:%Y-%m-%d}.png"):
                self.store.put(key, start.date().isoformat())
                self._note(group, f"{groups.heading(group, True, label)} posted", png)
                self._share_later(week, png)
                if picked is not None:
                    await host_picker.post_card(self, channel, picked, "desk")
                    host_picker.done(self.store, picked)

        # which week the live board shows: a new post for a new week from Sunday PREVIEW_HOUR on
        posted_week = post.get("week") or ""
        new_week_due = posted_week != this_week.date().isoformat() and (wday > 0 or local.hour >= self.preview_hour)
        if new_week_due and posted_week and not force_new and hosts.enabled(self.store) \
                and not await self._preview_host(group, channel, this_week.date().isoformat()):
            await self._edit(group, post)               # still waiting for the picks: last week's post stays
            return
        if force_new or not post.get("message") or new_week_due:
            if post.get("message") and posted_week and posted_week != this_week.date().isoformat():
                await self._edit(group, post, final=True)       # last week's post: its final state
            week = self.build(group, this_week)
            # the week's host (the week-ahead opener's, else a fresh pick), kept all week in the post record
            host = ""
            if hosts.enabled(self.store) and self.store.get("host_board") is not False:
                host = (self.store.get(f"preview_host.{group}") if self.store.get(f"preview_opened.{group}")
                        == this_week.date().isoformat() else "") or hosts.choose(self.store)
            png = await self.png(week, host)
            msg = await self.discord.cal_send(channel, embed(week), png, f"calendar-{this_week:%Y-%m-%d}.png")
            if msg:
                self.store.put(f"calendar_post.{group}", {"week": this_week.date().isoformat(), "channel": channel,
                                                          "message": str(msg), "sig": week.signature(), "drawn_at": now,
                                                          "host": host})
                self._seen[group] = (this_week.date().isoformat(), {t.key: t for t in week.tiles()})
                if new_week_due and posted_week:
                    self._note(group, f"New {groups.name(group)} week posted", png)
                    self._share_later(week, png)
            return
        await self._edit(group, post)

    async def _preview_host(self, group: str, channel: str, week_iso: str) -> bool:
        """The Sunday preview's host opener (flavrpromo/host_picker.py, label "preview"): True = go on
        and post the new board (the opener went out just now, or the wait limit passed: then the
        pending preview is dropped and the owner told), False = still waiting for the picks."""
        if self.store.get(f"preview_opened.{group}") == week_iso:
            return True                                 # opener already out; the board failed last time
        picked = await host_picker.ready(self, group, "preview", week_iso)
        if picked is not None:
            await host_picker.post_card(self, channel, picked, "opener")
            host_picker.done(self.store, picked)
            self.store.put(f"preview_opened.{group}", week_iso)
            self.store.put(f"preview_host.{group}", picked["host"])
            return True
        p = self.store.get(host_picker.key_of("preview", group)) or {}
        wait = host_picker.preview_wait(self.store)
        if not wait or self.clock() - float(p.get("asked_at") or self.clock()) < wait * 3600:
            return False
        if p:
            host_picker.done(self.store, p)
        try:
            await self.discord.dm_owner(f"🗓️ No picks for the {host_picker.post_title(group, 'preview')} after "
                                        f"{wait:g} h, so the new board went up without the host.")
        except Exception as e:
            log.info("preview DM failed: %s", e)
        return True

    async def _edit(self, group: str, post: Dict[str, Any], final: bool = False) -> None:
        """Redraw the board post when what it shows changed (or a live preview is stale)."""
        start = datetime.fromisoformat(post["week"]).replace(tzinfo=self.tz)
        week = self.build(group, start)
        now = self.clock()
        sig = week.signature()
        live = any(t.kind == "live" for t in week.tiles())
        stale = live and now - float(post.get("drawn_at") or 0) >= LIVE_REDRAW
        self._diff(group, post["week"], week)
        if sig == post.get("sig") and not stale and not final:
            return
        png = await self.png(week, str(post.get("host") or ""))       # the week's host (kept in the record)
        ok = await self.discord.cal_edit(post["channel"], post["message"], embed(week), png,
                                         f"calendar-{start:%Y-%m-%d}.png")
        if ok:
            self.store.put(f"calendar_post.{group}", {**post, "sig": sig, "drawn_at": now})
            if png:
                self._png[group] = png
        elif not final:
            # the post (or its channel) is gone: forget it, the next look makes a new one
            self.store.put(f"calendar_post.{group}", {})

    # ── pings ──────────────────────────────────────────────────────────
    def _diff(self, group: str, week_key: str, week: Week) -> None:
        now_tiles = {t.key: t for t in week.tiles()}
        before = self._seen.get(group)
        self._seen[group] = (week_key, now_tiles)
        if not before or before[0] != week_key:
            return                              # first look since start, or a new week: no diff
        for text in changes(before[1], now_tiles, self.tz):
            self._note(group, text)

    def _note(self, group: str, text: str, png: Optional[bytes] = None) -> None:
        """One change line for ``group``'s next calendar DM (``png``: a picture that goes with it, e.g. the
        week in review; else the group's newest board)."""
        if not self.ping_on():
            return
        if not self._pending:
            self._pending_at = self.clock()
        self._pending.setdefault(group, []).append(text)
        if png:
            self._png[group] = png

    async def flush_pings(self) -> None:
        """Send the collected calendar changes once the oldest is PING_BATCH old."""
        if not self._pending or self.clock() - self._pending_at < PING_BATCH:
            return
        pending, self._pending = self._pending, {}
        for group, lines in pending.items():
            # one DM per group, with that group's own board ("FlaVR" stays unnamed: it's the main one)
            label = "" if group == "flavr" else f"{groups.name(group)} "
            text = f"🗓️ {label}{'calendar' if label else 'Calendar'} updated: " + "; ".join(lines)
            if self.quiet() and self.hold:
                await self.hold(text)           # held like other pings; sent when quiet hours end
                continue
            png = self._png.get(group)
            if png is None and self.shooter is not None:
                png = await self.png(self.build(group, self.week_of(0)))    # no post drawn yet this run
            try:
                await self.discord.dm_owner(text[:1900], png)
            except Exception:
                log.exception("calendar ping failed")
