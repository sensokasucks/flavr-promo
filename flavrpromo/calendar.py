"""
The weekly calendar's data: which streams go in which day of a Sunday-to-Saturday week, for one
group (FlaVR or Friends). No drawing and no Discord here: flavrpromo/render.py draws a ``Week``,
flavrpromo/calendar_post.py posts it, and flavrpromo/web.py serves it as a page and an .ics feed.

Where each tile comes from
  past       a stream the watcher saw (sessions table) that has ended; picture = its VOD picture
             (Twitch VOD thumbnail / YouTube hqdefault), else the thumbnail seen while live
  live       a stream still open in the sessions table; picture = the live preview
  community  group "community" also gets the streams members added from their posts
             (flavrpromo/promo.py ``tiles``), on top of any people put in that group
  scheduled  a Twitch schedule segment or a YouTube waiting room (scheduled table), or a weekly
             time set by hand (/friend schedule, manual_schedule table); picture = the game's box
             art or YouTube's own thumbnail, else the person's profile picture

Reviews (owner 2026-11-20; they replace the old Saturday 11 PM recap): a review is a Week with
``recap`` on, ``label`` "week" or "weekend" and only its own days (``review_range``):
  week     Monday to Thursday, posted Friday (default 10 AM)
  weekend  Friday to Sunday, posted Monday (default 10 AM)
so the two cover every day once. Its ``uploads`` are the non-stream videos of those days (YouTube
videos, Shorts and premieres, Twitch uploads and highlights; store table "uploads", flavrpromo/watcher.py
fills it), listed under the streams in the post, the share text and the X Article.

Rules (from the plan doc, decided with the owner):
  * the week runs Sunday 00:00 to Saturday 23:59 in TZ; a stream past midnight stays on the day
    it started;
  * a scheduled item is dropped once a real stream by that person starts within MATCH_WINDOW of
    it (the stream replaces it), or once it is more than STALE_AFTER in the past without one;
  * the same person scheduled on several platforms within MERGE_WINDOW = one tile with several
    badges (multistream);
  * LATE NOTICE (recap only): a stream with no scheduled item seen at least LATE_NOTICE before it
    started (never for streams filled in from VODs: nobody was looking for schedules then);
  * people marked hidden (/friend hide) are left out;
  * a confirmed collab (flavrpromo/collabs.py, owner 2026-11-22) carries its partners' names in
    ``Tile.collab``, and everything that draws the calendar highlights it.

Times are unix seconds everywhere; ``tz`` is a ZoneInfo (Settings.timezone).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import groups
from .store import PLATFORMS, Store

MATCH_WINDOW = 3 * 3600.0       # a stream this close to a scheduled time "is" that scheduled stream
MERGE_WINDOW = 30 * 60.0        # scheduled on two platforms this close = one multistream tile
STALE_AFTER = 3600.0            # a scheduled time this far gone with no stream drops off
LATE_NOTICE = 3600.0            # scheduled less than this ahead (or not at all) = LATE NOTICE
DAY_NAMES = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")


@dataclass
class Tile:
    """One stream on the calendar (one person; several platforms when multistreaming)."""
    kind: str                       # "past" | "live" | "scheduled"
    name: str
    at: float                       # start (or scheduled start)
    end: Optional[float] = None     # past streams only
    title: str = ""
    game: str = ""
    url: str = ""                   # main link: VOD, live channel, or the scheduled page
    thumb: str = ""
    avatar: str = ""
    platforms: List[str] = field(default_factory=list)
    links: Dict[str, str] = field(default_factory=dict)
    viewers: int = 0
    restarts: int = 0
    late: bool = False
    person_id: int = 0
    from_vod: bool = False          # filled in afterwards from the platform (Watcher.backfill)
    # a confirmed collab: the partners' names (groups, people, outside @handles), set by
    # flavrpromo/collabs.py ``mark``; render.py / calendar_post.py / share.py / web.py highlight it
    collab: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable id for spotting changes between two looks at the calendar (pings)."""
        return f"{self.kind}:{self.person_id}:{int(self.at // 60)}"

    @property
    def length(self) -> float:
        return max(0.0, float(self.end or self.at) - self.at)


@dataclass
class Week:
    group: str
    start: datetime                 # the first day 00:00 local (a Sunday for the weekly board)
    tz: ZoneInfo
    now: float
    recap: bool
    days: List[List[Tile]]          # one list per day (7 for the board, 4 / 3 for a review), each sorted by time
    quiet: List[str]                # people with nothing on the board this week
    label: str = ""                 # "" = the weekly board / old full-week recap; "week" / "weekend" = a review
    uploads: List[Dict[str, Any]] = field(default_factory=list)    # reviews: videos, Shorts, premieres (not streams)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(days=len(self.days))

    def date_of(self, i: int):
        """The calendar date of day ``i`` (DST-safe: dates, not 24 h steps)."""
        return self.start.date().fromordinal(self.start.date().toordinal() + i)

    def day_name(self, i: int) -> str:
        """"SUN" ... "SAT" for day ``i`` (by its real weekday: a review can start on any day)."""
        return DAY_NAMES[(self.date_of(i).weekday() + 1) % 7]

    @property
    def title(self) -> str:
        return groups.title(self.group, self.recap, self.label)    # flavrpromo/groups.py (custom groups too)

    @property
    def range_text(self) -> str:
        last = self.start + timedelta(days=len(self.days) - 1)
        right = f"{last:%b} {last.day}" if last.month != self.start.month else str(last.day)
        return f"{self.start:%b} {self.start.day} – {right}"

    def tiles(self) -> List[Tile]:
        return [t for d in self.days for t in d]

    @property
    def stream_count(self) -> int:
        return sum(1 for t in self.tiles() if t.kind != "scheduled")

    @property
    def hours_live(self) -> float:
        return sum(t.length for t in self.tiles() if t.kind == "past") / 3600.0

    def today_index(self) -> int:
        """The index of today when ``now`` is inside these days, else -1."""
        d = (datetime.fromtimestamp(self.now, self.tz).date() - self.start.date()).days
        return d if 0 <= d < len(self.days) else -1

    def signature(self) -> str:
        """What the picture shows, minus things that tick (viewers, live picture refresh):
        unchanged signature = no need to redraw."""
        rows = [(t.kind, t.name, int(t.at), int(t.end or 0), t.title, t.game, t.url, tuple(t.platforms), t.late,
                 tuple(t.collab))
                for t in self.tiles()]
        return json.dumps([self.group, self.start.isoformat(), self.recap, self.label, self.today_index(), rows,
                           [u.get("video_id") for u in self.uploads]])


def week_start(ts: float, tz: ZoneInfo) -> datetime:
    """The Sunday 00:00 (local) that starts the week holding ``ts``."""
    d = datetime.fromtimestamp(ts, tz)
    back = (d.weekday() + 1) % 7          # Python: Monday = 0 ... Sunday = 6
    day = (d - timedelta(days=back)).date()
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def _avatars(people: List[Dict[str, Any]]) -> Dict[int, str]:
    """person id → a profile picture (main platform's first, then YouTube, Twitch, Kick)."""
    out = {}
    for p in people:
        accs = sorted(p.get("accounts") or [], key=lambda a: (a["platform"] != p.get("main_platform"),
                                                             PLATFORMS.index(a["platform"]) if a["platform"] in PLATFORMS else 9))
        out[p["id"]] = next((a["avatar"] for a in accs if a.get("avatar")), "")
    return out


def _links(raw: Any) -> Dict[str, str]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        return dict(json.loads(raw or "{}"))
    except (ValueError, TypeError):
        return {}


# a review's "Also this week" videos (store table "uploads"; kinds from platforms/youtube.py upload_info
# and platforms/twitch.py recent_uploads), used by calendar_post.py embeds and share.py
UPLOAD_ICONS = {"video": "🎬", "short": "📱", "premiere": "🎞️", "highlight": "✂️"}
UPLOAD_NAMES = {"video": "video", "short": "Short", "premiere": "premiere", "highlight": "highlight"}
UPLOADS_HEAD = "Also this week: videos, Shorts and premieres"
REVIEWS = {"week": (1, 4), "weekend": (5, 3)}     # label → (first day: 1 = Monday, 5 = Friday; how many days)
REVIEW_NAMES = {"week": "Week in review (Mon to Thu)", "weekend": "Weekend in review (Fri to Sun)"}


def review_range(label: str, now: float, tz: ZoneInfo) -> tuple:
    """(first day 00:00, number of days) of the newest review of that kind that has STARTED by ``now``:
    "week" = the latest Monday to Thursday, "weekend" = the latest Friday to Sunday. Friday's automatic
    post asks on Friday (→ this week's Mon-Thu), Monday's on Monday (→ the weekend just gone)."""
    first, n = REVIEWS[label]
    d = datetime.fromtimestamp(now, tz).date()
    back = (d.weekday() - (first - 1)) % 7          # Python: Monday = 0; ``first`` is 1 = Monday, 5 = Friday
    day = d.fromordinal(d.toordinal() - back)
    return datetime(day.year, day.month, day.day, tzinfo=tz), n


def build_week(store: Store, group: str, start: datetime, now: float, tz: ZoneInfo,
               recap: bool = False, days: int = 7, label: str = "") -> Week:
    """Everything on one group's calendar for ``days`` days from ``start`` (a Sunday 00:00 for the
    weekly board; a review's first day with ``label`` "week" / "weekend", flavrpromo/calendar_post.py)."""
    end_day = start.date().fromordinal(start.date().toordinal() + days)
    a, b = start.timestamp(), datetime(end_day.year, end_day.month, end_day.day, tzinfo=tz).timestamp()
    people = [p for p in store.people(group) if not p.get("hidden")]
    ids = {p["id"] for p in people}
    avatar = _avatars(people)

    tiles: List[Tile] = []
    sessions = [s for s in store.sessions_between(a, b, group) if s["person_id"] in ids]
    for s in sessions:
        live = s.get("ended_at") is None
        links = _links(s.get("links"))
        tiles.append(Tile(
            kind="live" if live else "past", name=s["name"], person_id=s["person_id"],
            at=float(s["started_at"]), end=None if live else float(s["ended_at"]),
            title=s.get("title") or "", game=s.get("game") or "",
            url=(s.get("url") if live else (s.get("vod_url") or s.get("url"))) or "",
            thumb=(s.get("thumb") if live else (s.get("vod_thumb") or s.get("thumb"))) or "",
            avatar=avatar.get(s["person_id"], ""), platforms=json.loads(s.get("platforms") or "[]"),
            links=links, viewers=int(s.get("viewers") or 0), restarts=int(s.get("restarts") or 0),
            from_vod=s.get("source") == "vod"))

    # every scheduled item (platform + by hand), for this week and the LATE NOTICE check
    sched = [dict(r) for r in store.scheduled_between(a - 86400, b, group) if r["person_id"] in ids]
    for m in store.manual(group):
        if m["person_id"] not in ids:
            continue
        day = start + timedelta(days=int(m["weekday"]))
        at = datetime(day.year, day.month, day.day, int(m["minute"]) // 60, int(m["minute"]) % 60, tzinfo=tz).timestamp()
        sched.append({"person_id": m["person_id"], "name": m["name"], "platform": m.get("platform") or "",
                      "at": at, "title": m.get("title") or "", "game": "", "url": "", "thumb": "",
                      "first_seen": a - 7 * 86400})        # a standing weekly time is never "late"

    if recap:
        for t in tiles:
            ahead = [x for x in sched if x["person_id"] == t.person_id and abs(float(x["at"]) - t.at) < MATCH_WINDOW
                     and float(x["first_seen"]) <= t.at - LATE_NOTICE]
            # a stream filled in from its VOD had no watcher looking for schedules then: never "late"
            t.late = not ahead and not t.from_vod
    else:
        started = [(t.person_id, t.at) for t in tiles]
        merged: List[Tile] = []
        for x in sorted(sched, key=lambda r: float(r["at"])):
            at = float(x["at"])
            if not (a <= at < b) or at < now - STALE_AFTER:
                continue
            if any(pid == x["person_id"] and abs(at - st) < MATCH_WINDOW for pid, st in started):
                continue                                    # the real stream took its place
            plat = x.get("platform") or ""
            twin = next((t for t in merged if t.person_id == x["person_id"] and abs(t.at - at) < MERGE_WINDOW), None)
            if twin:
                if plat and plat not in twin.platforms:
                    twin.platforms.append(plat)
                    twin.links[plat] = x.get("url") or ""
                twin.thumb = twin.thumb or x.get("thumb") or ""
                twin.game = twin.game or x.get("game") or ""
                continue
            merged.append(Tile(kind="scheduled", name=x["name"], person_id=x["person_id"], at=at,
                               title=x.get("title") or "", game=x.get("game") or "", url=x.get("url") or "",
                               thumb=x.get("thumb") or "", avatar=avatar.get(x["person_id"], ""),
                               platforms=[plat] if plat else [], links={plat: x.get("url") or ""} if plat else {}))
        tiles += merged

    from . import collabs, promo        # late imports: both import from here
    collabs.mark(store, tiles)          # confirmed collabs get their partners' names (the highlight)
    if group == promo.GROUP:
        tiles += promo.tiles(store, a, b, now, recap)

    by_day: List[List[Tile]] = [[] for _ in range(days)]
    for t in tiles:
        i = (datetime.fromtimestamp(t.at, tz).date() - start.date()).days
        if 0 <= i < days:
            by_day[i].append(t)
    for d in by_day:
        d.sort(key=lambda t: t.at)
        for t in d:
            t.platforms.sort(key=lambda p: PLATFORMS.index(p) if p in PLATFORMS else 9)
    on = {t.person_id for d in by_day for t in d}
    # a review lists the non-stream videos of its days too (people on this board, not hidden)
    uploads = [u for u in store.uploads_between(a, b) if u["person_id"] in ids] if label else []
    return Week(group=group, start=start, tz=tz, now=now, recap=recap, days=by_day,
                quiet=[p["name"] for p in people if p["id"] not in on], label=label, uploads=uploads)


def changes(before: Dict[str, Tile], after: Dict[str, Tile], tz: ZoneInfo) -> List[str]:
    """Plain lines for the owner's calendar ping: what's new on the board since the last look.

    ``before`` / ``after`` are {tile.key: tile} of the same week. A scheduled tile turning into
    a live one reads "went live", not "removed"."""
    out = []
    for k, t in after.items():
        if k in before:
            continue
        when = datetime.fromtimestamp(t.at, tz)
        clock = f"{(when.hour % 12) or 12}{':%02d' % when.minute if when.minute else ''} {'AM' if when.hour < 12 else 'PM'}"
        if t.kind == "scheduled":
            out.append(f"{t.name} scheduled {DAY_NAMES[(when.weekday() + 1) % 7].title()} {clock}")
        elif t.kind == "live":
            out.append(f"{t.name} went live")
    for t in before.values():
        # a scheduled tile that disappears (cancelled, or its time passed) isn't worth a ping
        if t.kind == "live" and f"past:{t.person_id}:{int(t.at // 60)}" in after:
            out.append(f"{t.name} ended")
    return out
