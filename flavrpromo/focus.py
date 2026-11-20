"""
Focus posts: the calendar for just one day or the weekend (Sen asked 2026-11-19: "a calendar post
that just focuses on a specific day, like today's streams or tomorrow's, or the weekend streams").

What it shows: the same streams as the weekly board (flavrpromo/calendar.py build_week: past streams
with their VOD, who's live, what's scheduled), cut down to the chosen days, as
  * a picture: big tiles for those days (flavrpromo/render.py ``tiles_card``; the weekend picture
    puts the weekday in front of each time),
  * a list under it with links, one block per day (flavrpromo/calendar_post.py ``line``; times show
    in each reader's own time zone).

Which days (``pick_days``, local time in TZ):
  today / tomorrow     that date
  weekend              Friday + Saturday + Sunday (Sen 2026-11-20: weekends include Friday): the
                       coming one Monday to Thursday, this one Friday to Sunday
                       (the board's week runs Sunday to Saturday, so the two days can sit in two weeks)
  sunday ... saturday  the next one, today included

Two ways to get one:
  /calendar focus when [group] [post]   (flavrpromo/bot.py) only you see it; ``post`` puts it in the
                       channel (owner or Manage Server). In a talent channel: only that person.
  Automatic, per group, OFF until /setup day-posts picks a channel; each time can be set or "off":
    today     a "Today" post at that time (TZ, default 10 AM), only on days with something on it
    tomorrow  an evening "Tomorrow" preview (default off), only when tomorrow has something on it
    weekend   a "This weekend" post on ``weekend_day`` (default Friday) at that time (default 10 AM)
    Each post is edited in place until its last day ends (planned → live → done with length and
    VOD link), like the weekly board: on a change, and every LIVE_REDRAW while someone is live.
    With the /pings switch "share" on, each automatic post is followed by the copy-ready share
    DM for those days (held during quiet hours), like the weekly post.

Share: ``share`` / ``as_week`` give /calendar share's `when` option the same copy-ready Discord and X
texts as the weekly share (flavrpromo/share.py), for just those days. The X Article style needs a
whole week's page, so focus shares fall back to the "post + links reply" style.

Saved in kv:
  day_posts.<group>        {channel, today, tomorrow, weekend, weekend_day}   (/setup day-posts; the
                           three times are minutes after midnight in TZ or None = off; weekend_day 0 = Sunday)
  day_post.<group>.<kind>  {key, label, dates, channel, message, sig, drawn_at, until}  kind = today /
                           tomorrow / weekend; ``key`` = the first date (ISO), so each posts once

Who calls it: CalendarPoster.tick (flavrpromo/calendar_post.py) runs ``tick`` every minute inside its
lock; flavrpromo/bot.py's /calendar focus uses ``pick_days``, ``build`` , ``embed`` and ``png``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import groups
from .calendar import Tile, Week
from .render import logo_data_url, tiles_card

log = logging.getLogger("flavrpromo.focus")

WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
WHEN = ("today", "tomorrow", "weekend") + WEEKDAYS          # /calendar focus choices
DEFAULT_TIME = 10 * 60                                      # automatic posts: minutes after midnight, TZ
DEFAULT_WEEKEND_DAY = 5                                     # Friday (0 = Sunday)
KINDS = ("today", "tomorrow", "weekend")                    # automatic post kinds, in posting order
LIVE_REDRAW = 20 * 60.0                                     # same rhythm as the weekly board
FIELD_MAX = 1024                                            # Discord: one embed field


@dataclass
class Focus:
    group: str
    tz: ZoneInfo
    label: str                      # "Today", "Tomorrow", "This weekend", "Saturday"
    dates: List[date]
    days: List[List[Tile]]          # one list per date, sorted by time

    def tiles(self) -> List[Tile]:
        return [t for d in self.days for t in d]

    @property
    def date_text(self) -> str:
        """"Thu Nov 19" for one day, "Nov 21–22" / "Nov 28 – Dec 1" for more."""
        a, b = self.dates[0], self.dates[-1]
        if a == b:
            return f"{a:%a} {a:%b} {a.day}"
        return f"{a:%b} {a.day}–{b.day}" if a.month == b.month else f"{a:%b} {a.day} – {b:%b} {b.day}"

    def signature(self) -> str:
        """What the post shows minus ticking numbers: unchanged = no need to redraw."""
        rows = [(t.kind, t.name, int(t.at), int(t.end or 0), t.title, t.game, t.url, tuple(t.platforms))
                for t in self.tiles()]
        return json.dumps([self.group, [d.isoformat() for d in self.dates], rows])


def pick_days(when: str, now: float, tz: ZoneInfo) -> Tuple[str, List[date]]:
    """``when`` (one of WHEN) → (label, dates). See the module notes."""
    today = datetime.fromtimestamp(now, tz).date()
    wday = (today.weekday() + 1) % 7                        # 0 = Sunday, like the board
    if when == "tomorrow":
        return "Tomorrow", [today + timedelta(days=1)]
    if when == "weekend":
        # Friday of this weekend: the coming one Mon-Thu (wday 1-4), today on Friday, 1 / 2 days back on Sat / Sun
        fri = today + timedelta(days=5 - wday) if 1 <= wday <= 5 else today - timedelta(days=1 if wday == 6 else 2)
        return "This weekend", [fri + timedelta(days=k) for k in range(3)]
    if when in WEEKDAYS:
        d = today + timedelta(days=(WEEKDAYS.index(when) - wday) % 7)
        return ("Today" if d == today else when.title()), [d]
    return "Today", [today]


def build(poster: Any, group: str, label: str, dates: List[date], person_id: int = 0) -> Focus:
    """The chosen days' streams from the weekly board (``poster``: CalendarPoster). ``person_id``:
    only that person (a talent channel)."""
    weeks: Dict[datetime, Week] = {}
    days: List[List[Tile]] = []
    for d in dates:
        start = poster.week_of(0, datetime(d.year, d.month, d.day, 12, tzinfo=poster.tz).timestamp())
        if start not in weeks:
            weeks[start] = poster.build(group, start)
        tiles = weeks[start].days[(d - start.date()).days]
        days.append([t for t in tiles if not person_id or t.person_id == person_id])
    return Focus(group, poster.tz, label, list(dates), days)


def title(f: Focus, who: str = "") -> str:
    """"Today on FlaVR · Thu Nov 19", "This weekend with Friends · Nov 20–22", "Lulu today · ..."."""
    if who:
        return f"{who}: {f.label.lower() if f.label != 'This weekend' else 'this weekend'} · {f.date_text}"
    joiner = "on" if f.group == "flavr" else "with"
    return f"{f.label} {joiner} {groups.name(f.group)} · {f.date_text}"


def embed(f: Focus, who: str = "") -> Dict[str, Any]:
    """The post's text as embed data (flavrpromo/bot.py make_embed): one field per day."""
    from .calendar_post import line         # late import: calendar_post imports this module
    fields: List[Tuple[str, str]] = []
    for d, tiles in zip(f.dates, f.days):
        if not tiles and len(f.dates) == 1:
            continue
        lines: List[str] = []
        used = 0
        for n, t in enumerate(tiles):
            text = line(t, False)
            if used + len(text) + 12 > FIELD_MAX:
                lines.append(f"+{len(tiles) - n} more")
                break
            lines.append(text)
            used += len(text) + 1
        fields.append((f"{d:%A} {d:%b} {d.day}", "\n".join(lines) or "Nothing on the calendar yet"))
    data: Dict[str, Any] = {"title": title(f, who), "colour": groups.colour_int(f.group), "fields": fields,
                            "footer": "Times below are in your own time zone"}
    if not f.tiles():
        data["description"] = "Nothing on the calendar yet."
    return data


async def png(poster: Any, f: Focus) -> Optional[bytes]:
    """The picture, or None without Chromium (the post goes out as text then)."""
    if poster.shooter is None:
        return None
    try:
        await poster.images.fetch_all(f)        # ImageCache only reads .tiles()
        heading = f"{f.label} · {f.date_text}".upper()
        return await poster.shooter.png(tiles_card(f.group, heading, f.tiles(), f.tz, poster.images.data_url,
                                                   logo_data_url(), show_day=len(f.dates) > 1))
    except Exception as e:
        log.warning("focus picture failed: %s", e)
        return None


def settings(store: Any, group: str) -> Dict[str, Any]:
    """/setup day-posts for a group ({} = off)."""
    s = store.get(f"day_posts.{group}") or {}
    return s if s.get("channel") else {}


def due(s: Dict[str, Any], kind: str, local: datetime) -> bool:
    """Is ``kind``'s time today reached (and, for the weekend post, is it its day)?"""
    at = s.get(kind)
    if at is None:
        return False
    if kind == "weekend" and (local.weekday() + 1) % 7 != int(s.get("weekend_day", DEFAULT_WEEKEND_DAY)):
        return False
    return local.hour * 60 + local.minute >= int(at)


async def tick(poster: Any) -> None:
    """Every minute (CalendarPoster.tick): new automatic posts when due, edits to the running ones."""
    now = poster.clock()
    local = datetime.fromtimestamp(now, poster.tz)
    for g in groups.keys():
        s = settings(poster.store, g)
        for kind in KINDS:
            key = f"day_post.{g}.{kind}"
            post = poster.store.get(key) or {}
            if post.get("message") and now < float(post.get("until") or 0) + 3600:
                await _edit(poster, g, key, post, final=now >= float(post.get("until") or 0))
            if not s or not due(s, kind, local):
                continue
            label, dates = pick_days(kind, now, poster.tz)
            if post.get("key") == dates[0].isoformat():
                continue                                        # already posted (or found empty)
            f = build(poster, g, label, dates)
            post = {"key": dates[0].isoformat()}
            if f.tiles():                                       # no "nothing on" posts
                pic = await png(poster, f)
                msg = await poster.discord.cal_send(s["channel"], embed(f), pic, f"{kind}-{post['key']}.png")
                if not msg:
                    continue                                    # try again next minute
                end = dates[-1] + timedelta(days=1)
                post.update(label=label, dates=[d.isoformat() for d in dates], channel=s["channel"], message=str(msg),
                            sig=f.signature(), drawn_at=now,
                            until=datetime(end.year, end.month, end.day, tzinfo=poster.tz).timestamp())
                poster._share_later(as_week(f), pic)            # the share DM, when /pings share is on
            poster.store.put(key, post)


# ── share text (flavrpromo/share.py works on a Week) ─────────────────────
@dataclass
class FocusWeek(Week):
    """A Focus dressed as a Week for flavrpromo/share.py: ``days`` are just the focused dates (they are
    consecutive, so ``start + i days`` still finds each one's date), with its own heading and dates."""
    heading: str = ""
    dates_text: str = ""

    @property
    def range_text(self) -> str:            # "Thu Nov 19" / "Nov 21–22" instead of the week's range
        return self.dates_text


def as_week(f: Focus) -> FocusWeek:
    d = f.dates[0]
    joiner = "on" if f.group == "flavr" else "with"
    return FocusWeek(group=f.group, start=datetime(d.year, d.month, d.day, tzinfo=f.tz), tz=f.tz, now=0.0,
                     recap=False, days=f.days, quiet=[], heading=f"{f.label} {joiner} {groups.name(f.group)}",
                     dates_text=f.date_text)


async def share(poster: Any, group: str, when: str, style: str = "", person_id: int = 0, user_id: int = 0) -> bool:
    """/calendar share with ``when``: DM the copy-ready texts for just those days to ``user_id``
    (0 = the owner). ``person_id``: only that person (a talent channel; no picture then)."""
    label, dates = pick_days(when, poster.clock(), poster.tz)
    f = build(poster, group, label, dates, person_id)
    pic = None if person_id else await png(poster, f)
    try:
        await poster.discord.dm_share(poster.share_messages(as_week(f), style), pic, user_id=user_id)
        return True
    except Exception:
        log.exception("focus share DM failed")
        return False


async def _edit(poster: Any, group: str, key: str, post: Dict[str, Any], final: bool) -> None:
    """Redraw a running automatic post when what it shows changed (or a live picture is stale).
    ``final``: its days are over; one last look, then it's left as it is."""
    f = build(poster, group, post["label"], [date.fromisoformat(d) for d in post["dates"]])
    now = poster.clock()
    sig = f.signature()
    stale = any(t.kind == "live" for t in f.tiles()) and now - float(post.get("drawn_at") or 0) >= LIVE_REDRAW
    if sig != post.get("sig") or stale:
        pic = await png(poster, f)
        ok = await poster.discord.cal_edit(post["channel"], post["message"], embed(f), pic, "focus.png")
        if not ok:
            poster.store.put(key, {"key": post.get("key")})     # deleted: don't make a new one for these days
            return
        post = {**post, "sig": sig, "drawn_at": now}
    if final:
        post = {**post, "message": ""}                          # done; keep ``key`` so it isn't posted again
    poster.store.put(key, post)
