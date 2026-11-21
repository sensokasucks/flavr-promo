"""
Draws the weekly calendar: a ``Week`` (flavrpromo/calendar.py) → an HTML page → a 1600 x 900 PNG.

The same HTML is used three ways, so they always look the same:
  * flavrpromo/calendar_post.py screenshots it (headless Chromium through Playwright) for Discord
    and the owner's DM; pictures are inlined as data: URLs so the browser needs no network;
  * flavrpromo/web.py serves it as a page on the home network (also the OBS Browser Source), with
    pictures from /calendar/img/... and a reload every 5 minutes.

Pictures (thumbnails, box art, profile pictures) are downloaded once by ``ImageCache`` into
DATA_DIR/cache/img and reused; anything over PRUNE_DAYS old is deleted. Live previews carry a
"?t=" that changes every 5 minutes, so they refresh by themselves.

Looks (decided with the owner, plan doc "Weekly FlaVR calendar plan"):
  FlaVR    the logo + its colours: pink #f72ca2, lime #b7ef33, yellow #f8cf33, teal #2ae0d4; day
           numbers cycle through them; today outlined teal with a yellow TODAY tag
  Friends  the same layout in plain teal with a text title, so the two never get mixed up
  Each day column picks its own size so it fills down to the bottom edge: up to BIG_TILES streams
  get big picture tiles, up to COMPACT_MAX get rows with a small picture, up to SLIM_MAX get slim
  rows (platform dot, name, time, no picture); past that the day ends with "+N more" (the text
  list under the Discord post always has every stream). COMPACT_MAX / SLIM_MAX were measured in
  Chromium for the 735 px grid: change them together with .grid height, .row and .slim CSS.

Chromium: CHROMIUM_PATH if set, else Playwright's own (the Docker image installs it).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import mimetypes
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import aiohttp

from . import groups
from .calendar import DAY_NAMES, Tile, Week

log = logging.getLogger("flavrpromo.render")
ASSETS = Path(__file__).resolve().parent / "assets"
WIDTH, HEIGHT = 1600, 900
BIG_TILES = 3           # up to this many streams a day: big picture tiles
COMPACT_MAX = 9         # rows with a small picture that fit in one day's column (59 px + 10 px gap)
SLIM_MAX = 16           # slim rows that fit (36 px + 5 px gap); past this "+N more"
PRUNE_DAYS = 21
MAX_PICTURE = 3 * 1024 * 1024
PLATFORM_BADGE = {"youtube": ("Y", "#ff0033", "#fff"), "twitch": ("T", "#9146ff", "#fff"), "kick": ("K", "#53fc18", "#000")}
TZ_WORDS = {"America/New_York": "Eastern time", "America/Chicago": "Central time", "America/Denver": "Mountain time",
            "America/Los_Angeles": "Pacific time", "Europe/London": "UK time"}


# ── pictures ───────────────────────────────────────────────────────────
class ImageCache:
    """Downloads each picture once (who: render + web). ``path(url)`` is where it would be."""

    def __init__(self, folder: Path, http: Optional[aiohttp.ClientSession] = None):
        self.folder = Path(folder)
        self.http = http
        self._fail: dict[str, float] = {}         # url → when it last failed (retried after an hour)

    def name(self, url: str) -> str:
        ext = Path(url.split("?", 1)[0]).suffix.lower()
        ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".img"
        return hashlib.sha1(url.encode()).hexdigest()[:24] + ext

    def path(self, url: str) -> Path:
        return self.folder / self.name(url)

    async def fetch(self, url: str) -> Optional[Path]:
        if not url or not url.startswith(("https://", "http://")):
            return None
        p = self.path(url)
        if p.exists():
            return p
        if self.http is None or time.time() - self._fail.get(url, 0) < 3600:
            return None
        try:
            async with self.http.get(url) as r:
                if r.status != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
                    raise ValueError(f"HTTP {r.status} {r.headers.get('Content-Type', '')}")
                body = b""
                async for chunk in r.content.iter_chunked(64 * 1024):     # read() alone may stop at one chunk
                    body += chunk
                    if len(body) > MAX_PICTURE:
                        raise ValueError("picture too big")
        except Exception as e:
            self._fail[url] = time.time()
            log.info("picture %s not fetched: %s", url[:80], e)
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(p)
        return p

    async def fetch_all(self, week: Week) -> None:
        urls = {u for t in week.tiles() for u in (t.thumb, t.avatar) if u}
        await asyncio.gather(*(self.fetch(u) for u in urls))

    def prune(self) -> None:
        if not self.folder.exists():
            return
        old = time.time() - PRUNE_DAYS * 86400
        for f in self.folder.iterdir():
            try:
                if f.stat().st_mtime < old:
                    f.unlink()
            except OSError:
                pass

    def data_url(self, url: str) -> str:
        """The cached picture as a data: URL ("" when it isn't cached)."""
        p = self.path(url) if url else None
        if not p or not p.exists():
            return ""
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def logo_data_url() -> str:
    return "data:image/png;base64," + base64.b64encode((ASSETS / "flavr_logo.png").read_bytes()).decode()


# ── text helpers ───────────────────────────────────────────────────────
def clock(ts: float, tz, short: bool = False) -> str:
    """8:02p (short) or 8:02 PM; whole hours drop ":00" in the long form."""
    d = datetime.fromtimestamp(ts, tz)
    h = (d.hour % 12) or 12
    if short:
        return f"{h}:{d.minute:02d}{'a' if d.hour < 12 else 'p'}"
    return f"{h}{':%02d' % d.minute if d.minute else ''} {'AM' if d.hour < 12 else 'PM'}"


def hm(sec: float) -> str:
    m = int(sec) // 60
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def viewers(n: int) -> str:
    return f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else str(n)


def tz_words(tz) -> str:
    return TZ_WORDS.get(getattr(tz, "key", ""), getattr(tz, "key", "local time"))


# ── the page ───────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;margin:0} html,body{background:#0e0f14}
body{width:1600px;height:900px;overflow:hidden;font-family:"DejaVu Sans","Noto Sans","Noto Sans CJK JP",Arial,sans-serif;color:#eef;padding:28px 36px;
 background-image:radial-gradient(circle at 85% -10%,var(--glow1) 0,transparent 40%),radial-gradient(circle at 0% 110%,var(--glow2) 0,transparent 40%)}
header{display:flex;align-items:flex-end;gap:20px;margin-bottom:18px;height:66px}
h1{display:flex;align-items:center;gap:18px;font-size:44px;letter-spacing:2px;font-weight:800;white-space:nowrap}
.logo{height:62px;filter:drop-shadow(0 0 1px #fff) drop-shadow(0 0 1px #fff)}
.range{font-size:20px;color:#aab;padding-bottom:6px;white-space:nowrap} .stats{margin-left:auto;font-size:17px;color:#ccd;padding-bottom:6px;white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px;height:735px}
.day{background:#ffffff0a;border:1px solid #ffffff14;border-radius:14px;padding:10px;display:flex;flex-direction:column;gap:10px;overflow:hidden;min-width:0}
.day.today{border:2px solid var(--today);background:var(--today-bg);box-shadow:0 0 30px var(--today-glow)}
.day.past{opacity:.93}
.dh{display:flex;align-items:baseline;gap:8px} .dh span{font-size:15px;color:#aab;letter-spacing:2px} .dh b{font-size:26px}
.d0 .dh b{color:var(--c1)} .d1 .dh b{color:var(--c2)} .d2 .dh b{color:var(--c3)} .d3 .dh b{color:var(--c4)}
.dh em{margin-left:auto;font-style:normal;font-size:12px;background:var(--tag);color:#1a1400;padding:3px 7px;border-radius:6px;font-weight:700}
.tile{background:#00000050;border-radius:11px;overflow:hidden;border:1px solid #ffffff14;flex:none}
.tile.live{outline:2px solid #e5312f} .tile.scheduled .thumb{filter:saturate(.8)}
.thumb{position:relative;aspect-ratio:16/9;background:#1b1d26 center/cover no-repeat}
.thumb.art{background-size:contain;background-color:#1b1d26}
.thumb .noart{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 10px;
 font-size:15px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:#ffffff70}
.badge{position:absolute;bottom:6px;right:6px;font-size:12px;font-weight:700;padding:2px 7px;border-radius:5px;background:#000d;color:#fff}
.badge.live{background:#e5312f;left:6px;right:auto;top:6px;bottom:auto} .badge.scheduled{background:#fffffff0;color:#111}
.plats{position:absolute;top:6px;right:6px;display:flex;gap:3px}
.plat{width:20px;height:20px;border-radius:5px;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center}
.late{position:absolute;left:6px;bottom:6px;font-size:10px;font-weight:800;padding:2px 6px;border-radius:5px;background:var(--tag);color:#1a1400;letter-spacing:.5px}
.who{display:flex;gap:8px;align-items:flex-start;padding:8px 9px}
.av{width:30px;height:30px;border-radius:50%;flex:none;border:2px solid #ffffff30;object-fit:cover;background:#2a2d3a;
 display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;color:#ccd}
.who>div{min-width:0} .who b{display:block;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.who i{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-style:normal;font-size:11.5px;color:#aab;line-height:1.3}
.who u{display:block;text-decoration:none;font-size:11.5px;color:#cfe;margin-top:3px;white-space:nowrap}
.row{display:flex;gap:8px;align-items:center;background:#00000050;border:1px solid #ffffff14;border-radius:9px;padding:5px;flex:none;min-width:0}
.row.live{outline:2px solid #e5312f}
.row .mini{width:64px;height:36px;border-radius:6px;flex:none;background:#1b1d26 center/cover no-repeat;position:relative}
.row .mini .plat{position:absolute;top:2px;right:2px;width:14px;height:14px;font-size:8px;border-radius:4px}
.row>div{min-width:0} .row b{display:block;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row i{display:block;font-style:normal;font-size:11px;color:#aab;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .t{font-size:11px;font-weight:700;color:#fff} .row .t.live{color:#ff6b69}
.day.slim{gap:5px}
.slim .row{padding:3px 7px;gap:6px;border-radius:7px}
.slim .row .dots{display:flex;flex-direction:column;gap:2px;flex:none}
.slim .row .dot{width:7px;height:7px;border-radius:50%}
.slim .row b{font-size:12px;line-height:15px} .slim .row .t{display:block;line-height:14px}
.more{font-size:13px;color:#aab;text-align:center;padding-top:2px}
.empty{color:#667;font-size:14px;text-align:center;margin-top:30px}
footer{margin-top:12px;display:flex;justify-content:space-between;gap:30px;color:#99a;font-size:15px;white-space:nowrap}
footer span:first-child{overflow:hidden;text-overflow:ellipsis}
"""
# FlaVR's board keeps the logo's four colours; every other group is built by theme() from its one colour
THEMES = {
    "flavr": "--c1:#f72ca2;--c2:#b7ef33;--c3:#f8cf33;--c4:#2ae0d4;--today:#2ae0d4;--today-bg:#2ae0d414;"
             "--today-glow:#2ae0d433;--tag:#f8cf33;--glow1:#f72ca255;--glow2:#2ae0d444",
}



def theme(group: str) -> str:
    """The board's colours: FlaVR's four logo colours; every other group (Friends, /group add ones) one
    colour throughout, its /group colour (flavrpromo/groups.py; Friends = teal)."""
    if group == "flavr":
        return THEMES["flavr"]
    c = groups.colour(group)
    return (f"--c1:{c};--c2:{c};--c3:{c};--c4:{c};--today:{c};--today-bg:{c}14;--today-glow:{c}33;"
            f"--tag:{c};--glow1:{c}33;--glow2:{c}22")


Img = Callable[[str], str]      # picture URL → what goes in src / url() ("" = no picture)


def _plats(t: Tile, cls: str = "plat") -> str:
    out = ""
    for p in t.platforms:
        letter, bg, fg = PLATFORM_BADGE.get(p, ("?", "#888", "#000"))
        out += f'<span class="{cls}" style="background:{bg};color:{fg}">{letter}</span>'
    return out


def _avatar(t: Tile, img: Img) -> str:
    src = img(t.avatar)
    if src:
        return f'<img class="av" src="{html.escape(src, quote=True)}">'
    initials = "".join(w[0] for w in t.name.split()[:2]).upper() or "?"
    return f'<span class="av">{html.escape(initials)}</span>'


def _badge(t: Week | Tile, week: Week) -> str:
    assert isinstance(t, Tile)
    if t.kind == "live":
        return f'<span class="badge live">LIVE{" · " + viewers(t.viewers) if t.viewers else ""}</span>'
    if t.kind == "scheduled":
        return f'<span class="badge scheduled">{clock(t.at, week.tz)}</span>'
    return f'<span class="badge">{hm(t.length)}</span>'


def _tile(t: Tile, week: Week, img: Img) -> str:
    thumb = img(t.thumb) or img(t.avatar)
    art = " art" if t.kind == "scheduled" and t.thumb and "box_art" in t.thumb.lower() else ""
    style = f' style="background-image:url(&quot;{html.escape(thumb, quote=True)}&quot;)"' if thumb else ""
    noart = "" if thumb else f'<div class="noart">{html.escape(t.game or t.title or t.name)[:40]}</div>'
    late = '<span class="late">LATE NOTICE</span>' if week.recap and t.late else ""
    line3 = ""
    if t.kind == "past":
        line3 = f"<u>{clock(t.at, week.tz, True)}–{clock(t.end or t.at, week.tz, True)}" \
                f"{' · %d restart%s' % (t.restarts, 's' if t.restarts > 1 else '') if t.restarts else ''}</u>"
    elif t.kind == "live":
        line3 = f"<u>since {clock(t.at, week.tz, True)}</u>"
    sub = t.title or t.game
    return (f'<div class="tile {t.kind}"><div class="thumb{art}"{style}>{noart}{_badge(t, week)}'
            f'<span class="plats">{_plats(t)}</span>{late}</div>'
            f'<div class="who">{_avatar(t, img)}<div><b>{html.escape(t.name)}</b>'
            f'<i>{html.escape(sub)}</i>{line3}</div></div></div>')


def _row(t: Tile, week: Week, img: Img) -> str:
    thumb = img(t.thumb) or img(t.avatar)
    style = f' style="background-image:url(&quot;{html.escape(thumb, quote=True)}&quot;)"' if thumb else ""
    if t.kind == "live":
        when = '<span class="t live">LIVE</span>'
    elif t.kind == "past":
        when = f'<span class="t">{clock(t.at, week.tz, True)} · {hm(t.length)}</span>'
    else:
        when = f'<span class="t">{clock(t.at, week.tz)}</span>'
    return (f'<div class="row {t.kind}"><span class="mini"{style}>{_plats(t)}</span><div>'
            f'<b>{html.escape(t.name)}</b>{when}<i>{html.escape(t.game or t.title)}</i></div></div>')


def _slim(t: Tile, week: Week) -> str:
    """A slim row for packed days (more than COMPACT_MAX): a dot per platform, name, time · length."""
    dots = "".join(f'<span class="dot" style="background:{PLATFORM_BADGE[p][1]}"></span>'
                   for p in t.platforms if p in PLATFORM_BADGE)
    if t.kind == "live":
        when = '<span class="t live">LIVE</span>'
    elif t.kind == "past":
        when = f'<span class="t">{clock(t.at, week.tz, True)} · {hm(t.length)}</span>'
    else:
        when = f'<span class="t">{clock(t.at, week.tz)}</span>'
    return f'<div class="row {t.kind}"><span class="dots">{dots}</span><div><b>{html.escape(t.name)}</b>{when}</div></div>'


def day_layout(n: int) -> tuple:
    """(size, how many shown) for a day with n streams: "big", "row" or "slim" (see the top of
    this file). When they don't all fit, one slot goes to the "+N more" line."""
    if n <= BIG_TILES:
        return "big", n
    if n <= COMPACT_MAX:
        return "row", n
    return "slim", (n if n <= SLIM_MAX else SLIM_MAX - 1)


def page(week: Week, img: Img, logo: str = "", footer_note: str = "", refresh: int = 0) -> str:
    """The whole calendar as one HTML document (1600 x 900)."""
    today = week.today_index()
    cols = ""
    for i, tiles in enumerate(week.days):
        day = week.start.replace(day=week.start.day) if i == 0 else None
        date = (week.start.date().fromordinal(week.start.date().toordinal() + i))
        state = "today" if i == today else ("past" if 0 <= today and i < today or week.recap else "")
        size, fit = day_layout(len(tiles))
        if size == "big":
            body = "".join(_tile(t, week, img) for t in tiles)
        else:
            body = "".join(_row(t, week, img) if size == "row" else _slim(t, week) for t in tiles[:fit])
            if len(tiles) > fit:
                body += f'<div class="more">+{len(tiles) - fit} more</div>'
        if size == "slim":
            state += " slim"
        if not tiles:
            gone = week.recap or (0 <= today and i < today)
            body = f'<div class="empty">{"No streams" if gone else "Nothing scheduled yet"}</div>'
        del day
        cols += (f'<div class="day d{i % 4} {state}"><div class="dh"><span>{week.day_name(i)}</span><b>{date.day}</b>'
                 f'{"<em>TODAY</em>" if i == today else ""}</div>{body}</div>')
    if week.recap:
        stats = f"{week.stream_count} streams · {week.hours_live:.0f} hours live"
    else:
        sched = sum(1 for t in week.tiles() if t.kind == "scheduled")
        stats = f"{week.stream_count} streamed · {sched} scheduled"
    head = (f'<img class="logo" src="{html.escape(logo, quote=True)}"> ' if logo and week.group == "flavr" else "") \
        + f"<span>{html.escape(week.title)}</span>"
    quiet = ""
    if week.quiet:
        lead = "No streams this week" if week.recap else "Nothing on yet"
        quiet = f"{lead}: {', '.join(week.quiet)}"
    updated = datetime.fromtimestamp(week.now, week.tz)
    foot = footer_note or ("Every VOD link is in the list under this picture" if week.recap else
                           f"Updated {DAY_NAMES[(updated.weekday() + 1) % 7].title()} {clock(week.now, week.tz)}")
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{meta}<title>{html.escape(week.title.title())}</title>'
            f'<style>:root{{{theme(week.group)}}}{CSS}</style></head><body>'
            f'<header><h1>{head}</h1><div class="range">{html.escape(week.range_text)} · {html.escape(tz_words(week.tz))}</div>'
            f'<div class="stats">{stats}</div></header>'
            # a review has 4 or 3 day columns instead of 7 (CSS default: 7)
            f'<div class="grid"{"" if len(week.days) == 7 else f" style=grid-template-columns:repeat({len(week.days)},minmax(0,1fr))"}>{cols}</div>'
            f'<footer><span>{html.escape(quiet)}</span><span>{html.escape(foot)}</span></footer></body></html>')


# ── the X Article cover (5:2) ──────────────────────────────────────────
COVER_W, COVER_H = 1500, 600        # X Articles want a 5:2 cover; keep text away from the edges (phones trim)
COVER_PICS = 8                      # thumbnails on the cover (4 x 2)


def cover_people(week: Week) -> list:
    """Who goes on the cover, called by cover() below. One row per person, at most COVER_PICS:
    {"tile": the stream whose picture is shown, "hours": hours live (past streams only),
     "streams": how many streams that week (done in a recap, planned in a preview)}.
    Order: recap = most hours first (ties: who streamed first), preview = order of first stream.
    Picture: recap = the longest stream that has a thumbnail; preview = the first one with a thumbnail;
    a person's profile picture only when none of their streams has a thumbnail. The numbers show
    under each name on the cover (Sen asked 2026-11-18) so the order explains itself."""
    by: dict = {}
    for t in week.tiles():
        r = by.setdefault(t.person_id, {"tile": t, "hours": 0.0, "streams": 0, "first": t.at})
        r["streams"] += 1
        r["hours"] += t.length / 3600 if t.kind == "past" else 0
        cur = r["tile"]
        if t.thumb and not cur.thumb:                     # a thumbnail always beats none
            r["tile"] = t
        elif week.recap and t.length > cur.length and (t.thumb or not cur.thumb):
            r["tile"] = t                                 # longer stream, never trading a thumbnail away
    rows = sorted(by.values(), key=lambda r: (-r["hours"], r["first"]) if week.recap else (r["first"],))
    return rows[:COVER_PICS]


def cover_stats(row: dict, recap: bool) -> str:
    """The small line under a name on the cover: "24h · 6 streams" (recap) or "3 planned" (preview)."""
    n = row["streams"]
    if not recap:
        return f"{n} planned"
    h = row["hours"]
    hours = f"{h:.0f}h" if h >= 10 else f"{h:.1f}".rstrip("0").rstrip(".") + "h"
    return f"{hours} · {n} stream{'s' if n != 1 else ''}"


def cover(week: Week, img: Img, logo: str = "") -> str:
    """The X Article cover, 1500 x 600, the board's look: logo (FlaVR) or group name, the board title,
    the dates and numbers on the left; the people's stream pictures (thumbnail, else profile picture)
    with their names and numbers (cover_stats) on the right. flavrpromo/web.py /calendar/cover.png screenshots it."""
    e = html.escape
    if week.recap:
        stats = f"{week.stream_count} streams · {week.hours_live:.0f} hours live"
    else:
        stats = f"{sum(len(d) for d in week.days)} streams this week"
    title = groups.title(week.group, week.recap)
    name = "" if (logo and week.group == "flavr") else e(groups.name(week.group).upper())
    head = f'<img class="logo" src="{e(logo, quote=True)}">' if logo and week.group == "flavr" else f"<b>{name}</b>"
    if week.group != "flavr":
        title = "WEEK IN REVIEW" if week.recap else "THIS WEEK"
    pics = ""
    for i, row in enumerate(cover_people(week)):
        t = row["tile"]
        src = img(t.thumb) or img(t.avatar)
        style = f' style="background-image:url(&quot;{e(src, quote=True)}&quot;)"' if src else ""
        pics += (f'<div class="p"><i class="c{i % 4}"{style}></i><span>{e(t.name)}</span>'
                 f'<em>{e(cover_stats(row, week.recap))}</em></div>')
    css = (":root{" + theme(week.group) + "}*{box-sizing:border-box;margin:0}"
           f"html,body{{background:#0e0f14}}body{{width:{COVER_W}px;height:{COVER_H}px;overflow:hidden;"
           'font-family:"DejaVu Sans","Noto Sans","Noto Sans CJK JP",Arial,sans-serif;color:#eef;display:flex;'
           "align-items:center;gap:44px;padding:0 70px;background-image:radial-gradient(circle at 85% -10%,var(--glow1) 0,"
           "transparent 45%),radial-gradient(circle at 0% 110%,var(--glow2) 0,transparent 45%)}"
           ".l{flex:0 0 470px}.logo{height:120px;filter:drop-shadow(0 0 1px #fff) drop-shadow(0 0 1px #fff)}"
           ".l>b{font-size:54px;letter-spacing:2px;color:var(--c1)}"
           "h1{font-size:50px;font-weight:800;letter-spacing:2px;margin-top:18px;line-height:1.05}"
           ".d{font-size:30px;color:#ccd;margin-top:14px}.s{font-size:24px;color:var(--c4);margin-top:10px;font-weight:700}"
           ".g{flex:1;display:grid;grid-template-columns:repeat(4,1fr);gap:16px 14px}"
           ".p i{display:block;aspect-ratio:16/9;border-radius:12px;background:#1b1d26 center/cover no-repeat;"
           "border:3px solid var(--c1)}.p i.c1{border-color:var(--c2)}.p i.c2{border-color:var(--c3)}.p i.c3{border-color:var(--c4)}"
           ".p span{display:block;font-size:17px;font-weight:700;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
           ".p em{display:block;font-style:normal;font-size:15px;font-weight:700;color:var(--c4);margin-top:2px}")
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>'
            f'<div class="l">{head}<h1>{e(title)}</h1><div class="d">{e(week.range_text)}</div>'
            f'<div class="s">{e(stats)}</div></div><div class="g">{pics}</div></body></html>')


# ── one day as a picture (X Article: one picture per day) ──────────────
DAY_MAX = 20                        # streams drawn on a day picture; past that "+N more" (the links list all)


def day_columns(n: int) -> int:
    """Grid columns for n streams on a 16:9 day picture (rows follow): 1, 2, 2, 2, 3 ... 5."""
    return 1 if n <= 1 else 2 if n <= 4 else 3 if n <= 9 else 4 if n <= 16 else 5


def day_card(week: Week, i: int, img: Img, logo: str = "") -> str:
    """Day ``i`` of the week as a 1600 x 900 picture in the board's look: "SUNDAY · NOV 15" and the
    group's title on top, then that day's streams in a grid (thumbnail, name, time and length). X
    Articles allow only so many pictures, so the article uses one of these per day instead of one per
    stream (flavrpromo/share.py ``article``; flavrpromo/web.py /calendar/day.png)."""
    date = week.start + timedelta(days=i)
    return tiles_card(week.group, f"{date:%A} · {date:%b}".upper() + f" {date.day}", week.days[i], week.tz, img, logo)


GRID_W, GRID_H = WIDTH - 80, 750      # the tile area under the heading (body padding 40 px a side)
GRID_GAP_X, GRID_GAP_Y = 18, 16


def tile_layout(n: int, grid_w: int = GRID_W) -> tuple:
    """(columns, rows, tile width px, label font px) for ``n`` tiles on a day / focus picture.
    Every tile keeps the 16:9 shape of a stream thumbnail (a wider box would crop the picture's top
    and bottom, Sen 2026-11-19), so the columns are picked to make the tiles as big as fits, and the
    grid is centred (empty space at the sides or bottom rather than cut-off thumbnails). ``grid_w``:
    the width the tiles may use (less when a day post's host takes the right-hand column)."""
    n = max(1, n)
    best = (1, 1, 0, 24)
    for cols in range(1, min(n, 6) + 1):
        rows = -(-n // cols)
        label = 24 if rows <= 2 else 20 if rows <= 3 else 16
        under = 2 * label + 12                                  # name + time lines under each tile
        high = (GRID_H - GRID_GAP_Y * (rows - 1)) / rows - under
        wide = (grid_w - GRID_GAP_X * (cols - 1)) / cols
        w = int(min(wide, high * 16 / 9))
        if w > best[2]:
            best = (cols, rows, w, label)
    return best


HOST_W = 330        # px column on the right for a day post's host (chibi + bubble) ...
HOST_MAX_TILES = 4  # ... with this many tiles or fewer; more tiles = a small header badge instead


def tiles_card(group: str, heading: str, tiles: List[Tile], tz, img: Img, logo: str = "",
               show_day: bool = False, host: Optional[Dict[str, str]] = None) -> str:
    """Streams in a 16:9 grid under a big ``heading``: the day picture above (``day_card``) and the
    focus pictures ("TODAY · THU NOV 19", "THIS WEEKEND", flavrpromo/focus.py). ``show_day``: each
    stream's time starts with its weekday (a picture covering more than one day). ``host``: a day
    post's host (flavrpromo/focus.py): {"chibi": data URL or "", "line", "accent"}; with few tiles the
    chibi stands in the free side space under a speech bubble, else a small chibi + line sit in the
    header (owner 2026-11-20 mock-ups bot-presenter/live-and-daily/)."""
    e = html.escape
    shown = tiles if len(tiles) <= DAY_MAX else tiles[:DAY_MAX - 1]
    count = len(shown) + (len(tiles) > len(shown))
    big_host = bool(host and host.get("line")) and count <= HOST_MAX_TILES
    cols, rows, tw, label = tile_layout(count, GRID_W - (HOST_W if big_host else 0))
    grid_w = cols * tw + (cols - 1) * GRID_GAP_X
    # centred in the space left of the host column (or in the whole width without one)
    grid_left = ((GRID_W - (HOST_W if big_host else 0)) - grid_w) // 2
    cells = ""
    for k, t in enumerate(shown):
        src = img(t.thumb) or img(t.avatar)
        style = f' style="background-image:url(&quot;{e(src, quote=True)}&quot;)"' if src else ""
        day = f"{datetime.fromtimestamp(t.at, tz):%a} " if show_day else ""
        when = day + clock(t.at, tz) + (f" · {hm(t.length)}" if t.kind == "past" and t.end else
                                        " · LIVE" if t.kind == "live" else "")
        cells += (f'<div class="c"><i class="k{k % 4}"{style}>{_plats(t)}</i>'
                  f'<b>{e(t.name)}</b><span>{e(when)}</span></div>')
    if len(tiles) > len(shown):
        cells += f'<div class="c more">+{len(tiles) - len(shown)} more</div>'
    if not tiles:
        cells = '<div class="c more">Nothing on the calendar yet</div>'
    head = (f'<img class="logo" src="{e(logo, quote=True)}">' if logo and group == "flavr" else
            f"<em>{e(groups.name(group))}</em>")
    corner = badge = ""
    if host and host.get("line"):
        acc = e(host.get("accent") or "#f72ca2", quote=True)
        chibi = (f'<img src="{e(host["chibi"], quote=True)}" style="{{pos}};object-fit:contain">'
                 if host.get("chibi") else "")
        if big_host:
            w = HOST_W - 20
            corner = (chibi.replace("{pos}", f"position:absolute;right:40px;bottom:40px;width:{w}px;height:360px;"
                                             "object-position:bottom")
                      + f'<div class="hb" style="right:40px;bottom:{410 if chibi else 60}px;width:{w}px;'
                        f'border-color:{acc}">{e(host["line"])}</div>')
        else:
            badge = (chibi.replace("{pos}", "height:64px;max-width:90px")
                     + f'<div class="hs" style="border-color:{acc}">{e(host["line"])}</div>')
    css = (":root{" + theme(group) + "}*{box-sizing:border-box;margin:0}html,body{background:#0e0f14}"
           f"body{{width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;padding:30px 40px;color:#eef;"
           'font-family:"DejaVu Sans","Noto Sans","Noto Sans CJK JP",Arial,sans-serif;'
           "background-image:radial-gradient(circle at 85% -10%,var(--glow1) 0,transparent 40%),"
           "radial-gradient(circle at 0% 110%,var(--glow2) 0,transparent 40%)}"
           "header{display:flex;align-items:center;gap:22px;height:70px;margin-bottom:20px}"
           ".logo{height:60px;filter:drop-shadow(0 0 1px #fff) drop-shadow(0 0 1px #fff)} header em{font-style:normal;"
           "font-size:34px;font-weight:800;color:var(--c4)} h1{font-size:46px;font-weight:800;letter-spacing:3px;color:var(--c1)}"
           "header span{margin-left:auto;font-size:22px;color:#aab}"
           # a wrapping row exactly ``cols`` tiles wide, centred both ways: a short last row sits in the middle
           f".g{{display:flex;flex-wrap:wrap;justify-content:center;align-content:center;gap:{GRID_GAP_Y}px {GRID_GAP_X}px;"
           f"height:{GRID_H}px;width:{grid_w}px;margin:0 0 0 {grid_left}px}}"
           f".c{{display:flex;flex-direction:column;width:{tw}px}}"
           ".c i{display:block;aspect-ratio:16/9;border-radius:12px;background:#1b1d26 center/cover no-repeat;"
           "border:3px solid var(--c1);position:relative}"
           ".c i.k1{border-color:var(--c2)}.c i.k2{border-color:var(--c3)}.c i.k3{border-color:var(--c4)}"
           f".c b{{font-size:{label}px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}"
           f".c span{{font-size:{label - 4}px;color:#ccd;white-space:nowrap}}"
           f".c.more{{align-items:center;justify-content:center;font-size:28px;color:#aab;height:{round(tw * 9 / 16)}px}}"
           ".plat{position:absolute;top:8px;right:8px;width:26px;height:26px;border-radius:6px;font-size:14px;font-weight:800;"
           "display:inline-flex;align-items:center;justify-content:center;margin-left:4px}"
           ".c i .plat+.plat{right:38px}"
           # the host's speech bubble (corner) and header line (badge)
           ".hb{position:absolute;background:#fff;color:#1a1a1a;border:4px solid;border-radius:22px;padding:14px 18px;"
           "font-size:21px;line-height:1.3;font-weight:700}"
           ".hs{max-width:520px;font-size:18px;line-height:1.25;color:#eef;border-left:4px solid;padding-left:10px;"
           "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}")
    # the header's right end: the host badge (busy days) or the stream count
    right = (f'<span style="display:flex;align-items:center;gap:10px">{badge}</span>' if badge else
             f'<span>{len(tiles)} stream{"s" if len(tiles) != 1 else ""}</span>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>'
            f'<header>{head}<h1>{e(heading)}</h1>'
            f'{right}</header>'
            f'<div class="g">{cells}</div>{corner}</body></html>')


# ── the picture ────────────────────────────────────────────────────────
class Screenshotter:
    """One headless Chromium, started on first use and kept (a render is then ~0.3 s)."""

    def __init__(self, chromium_path: str = ""):
        self.chromium_path = chromium_path
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _start(self):
        from playwright.async_api import async_playwright     # only the picture needs it
        self._pw = await async_playwright().start()
        kw = {"executable_path": self.chromium_path} if self.chromium_path else {}
        self._browser = await self._pw.chromium.launch(args=["--no-sandbox"], **kw)

    async def png(self, doc: str, size: tuple = (WIDTH, HEIGHT)) -> bytes:
        """``doc`` as a PNG of ``size`` (the board 1600 x 900; the X Article cover COVER_W x COVER_H)."""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                await self._start()
            page = await self._browser.new_page(viewport={"width": size[0], "height": size[1]})
            try:
                await page.set_content(doc, wait_until="load", timeout=30_000)
                return await page.screenshot(type="png", full_page=False)
            finally:
                await page.close()

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = self._pw = None
