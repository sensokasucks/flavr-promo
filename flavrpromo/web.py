"""
The calendar on the home network, served by FlaVR Promo's little web server
(flavrpromo/server.py, port LISTEN_PORT, default 3871). No password: these pages only show
what is public anyway (stream titles and times). Never forward the port on the router.

  GET /calendar                  this week's board as a live page (reloads every 5 minutes). Also
                                 the OBS Browser Source: 1600 x 900, ?group=friends for the friends
                                 board (or any /group add group's key or name), ?week=next /
                                 ?week=last (last week = the old full-week recap), ?review=week (the
                                 newest Monday-Thursday review) / ?review=weekend (Friday-Sunday)
  GET /calendar.png              the same board as a picture (needs Chromium, like the Discord post)
  GET /calendar.ics              calendar feed (Google Calendar, Apple Calendar, phones: "add by URL"):
                                 this week's and next week's streams, past and scheduled, ?group=
  GET /calendar/img/<file>       the cached pictures the page shows
  GET /calendar/article          the week as an X Article (flavrpromo/share.py ``article``): the title,
                                 the formatted text with a Copy button (rich text, so it pastes into
                                 X's Article editor as headings, bold and links) and the picture for
                                 the cover; ?group= ?week= ?review= as above. The share DM links here.
                                 A review's article ends with its videos, Shorts and premieres.
                                 Each day has its picture with the streams' VOD links under it.
  GET /calendar/cover.png        the X Article cover: 1500 x 600 (5:2, what X asks for), the board's look
  GET /calendar/day.png?day=0-6  one day as a 16:9 picture (that day's thumbnails in a grid): X
                                 Articles allow only so many pictures, so it's one per day
  GET /calendar/article.zip      the cover and the day pictures, numbered in the article's order

Who calls it: flavrpromo/__main__.py ``add_routes(app, poster)`` through Server.extra_routes.
"""

from __future__ import annotations

import html
import io
import zipfile
from datetime import datetime, timezone
from typing import List

from aiohttp import web

from .calendar import REVIEWS, Tile, Week
from .calendar_post import CalendarPoster
from .render import logo_data_url, page
from .share import article, channel_url
from . import groups

REFRESH_SEC = 300


def _group(request: web.Request) -> str:
    return groups.find(request.query.get("group", "")) or "flavr"


def _review(request: web.Request) -> str:
    """?review=week / weekend → that label (flavrpromo/calendar.py REVIEWS), else ""."""
    r = request.query.get("review", "").lower()
    return r if r in REVIEWS else ""


def _offset(request: web.Request) -> int:
    return {"next": 1, "last": -1}.get(request.query.get("week", "").lower(), 0)


def _ics_text(s: str) -> str:
    """RFC 5545 text: escape \\ ; , and newlines."""
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics(weeks: List[Week], now: float) -> str:
    """Every tile of ``weeks`` as VEVENTs. Scheduled / live streams get a 2-hour placeholder length."""
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FlaVR Promo//calendar//EN", "CALSCALE:GREGORIAN",
           "X-WR-CALNAME:" + _ics_text(weeks[0].title.title() if weeks else "FlaVR"), "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    seen = set()
    for w in weeks:
        for t in w.tiles():
            uid = f"{t.person_id}-{int(t.at // 60)}@flavr-promo"
            if uid in seen:
                continue
            seen.add(uid)
            end = t.end if t.kind == "past" and t.end else t.at + 2 * 3600
            what = {"past": "", "live": " (live now)", "scheduled": ""}[t.kind]
            out += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_stamp(now)}", f"DTSTART:{_stamp(t.at)}", f"DTEND:{_stamp(end)}",
                    "SUMMARY:" + _ics_text(f"{t.name}: {t.title or t.game or 'stream'}{what}"),
                    "DESCRIPTION:" + _ics_text(" ".join(f"{p}: {u}" for p, u in t.links.items() if u) or t.url)]
            if t.url:
                out.append("URL:" + t.url)
            out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


async def get_week(poster: CalendarPoster, group: str, label: str = "", off: int = 0) -> Week:
    """A group's week (off -1 / 0 / 1) or review (label week / weekend). A past week or a review is
    filled in from the platforms first (once). Called by the routes below and flavrpromo/article_editor.py."""
    if label:
        await poster.backfill_review(label)
        return poster.build_review(group, label)
    if off < 0:
        await poster.ensure_backfill(poster.week_of(off))     # last week: fill in from the platforms once
    return poster.build(group, poster.week_of(off), recap=off < 0)


def article_query(group: str, label: str = "", off: int = 0) -> str:
    """The ?group=&review= / ?group=&week= part of the article and picture addresses."""
    q = f"?group={group}"
    if label:
        return q + f"&review={label}"
    return q + ({1: "&week=next", -1: "&week=last"}.get(off, ""))


def build_article(poster: CalendarPoster, week: Week, q: str) -> dict:
    """share.article for a week with the owner's settings (X handles, hashtag line, tagging) and one
    picture per day (/calendar/day.png + ``q``). Called by the article page and the article editor."""
    people = poster.store.people(week.group)
    save = lambda day: f"/calendar/day.png{q}{'&' if q else '?'}day={day}"  # noqa: E731
    return article(week, {p["id"]: p.get("x_handle") or "" for p in people},
                   tags=str(poster.store.get("share_x_tags") or ""), tag_people=bool(poster.store.get("share_x_tag")),
                   channels={p["id"]: channel_url(p) for p in people}, save=save)


def add_routes(app: web.Application, poster: CalendarPoster) -> None:
    async def _week(request: web.Request):
        """The week (or review) a request asks for: ?group= ?week= ?review=."""
        return await get_week(poster, _group(request), _review(request), _offset(request))

    async def board(request: web.Request) -> web.Response:
        week = await _week(request)
        await poster.images.fetch_all(week)
        img = lambda u: f"/calendar/img/{poster.images.name(u)}" if u and poster.images.path(u).exists() else ""  # noqa: E731
        return web.Response(text=page(week, img, logo=logo_data_url(), refresh=REFRESH_SEC),
                            content_type="text/html", charset="utf-8")

    async def picture(request: web.Request) -> web.Response:
        png = await poster.png(await _week(request))
        if not png:
            return web.Response(status=503, text="The picture needs Chromium (see the README).")
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=60"})

    async def cover_picture(request: web.Request) -> web.Response:
        png = await poster.cover_png(await _week(request))
        if not png:
            return web.Response(status=503, text="The picture needs Chromium (see the README).")
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=60"})

    async def feed(request: web.Request) -> web.Response:
        g = _group(request)
        weeks = [poster.build(g, poster.week_of(0)), poster.build(g, poster.week_of(1))]
        return web.Response(text=ics(weeks, poster.clock()), content_type="text/calendar", charset="utf-8")

    def _query(request: web.Request) -> str:
        q = "&".join(f"{k}={v}" for k, v in request.query.items() if k in ("group", "week", "review"))
        return "?" + q if q else ""

    async def _article(request: web.Request) -> dict:
        """share.article for ?group= ?week=, with one picture per day (/calendar/day.png)."""
        return build_article(poster, await _week(request), _query(request))

    async def article_page(request: web.Request) -> web.Response:
        a = await _article(request)
        q = _query(request)
        return web.Response(text=article_html(a, "/calendar.png" + q, "/calendar/article.zip" + q,
                                              "/calendar/cover.png" + q),
                            content_type="text/html", charset="utf-8")

    async def day_picture(request: web.Request) -> web.Response:
        try:
            day = int(request.query.get("day", "0"))
        except ValueError:
            raise web.HTTPNotFound()
        if not 0 <= day <= 6:
            raise web.HTTPNotFound()
        png = await poster.day_png(await _week(request), day)
        if not png:
            return web.Response(status=503, text="The picture needs Chromium (see the README).")
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=60"})

    async def article_zip(request: web.Request) -> web.Response:
        """The cover and every day picture, numbered in the article's order (00-cover.png, 01-sun.png ...)."""
        week = await _week(request)
        a = await _article(request)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:        # PNGs are compressed already
            png = await poster.cover_png(week)
            if png:
                z.writestr("00-cover.png", png)
            for _, name, day in a["pictures"]:
                png = await poster.day_png(week, day)
                if png:
                    z.writestr(name, png)
        return web.Response(body=buf.getvalue(), content_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="article-pictures.zip"'})

    async def image(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if "/" in name or "\\" in name or name.startswith("."):
            raise web.HTTPNotFound()
        p = poster.images.folder / name
        if not p.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Cache-Control": "max-age=3600"})

    app.router.add_get("/calendar", board)
    app.router.add_get("/calendar.png", picture)
    app.router.add_get("/calendar.ics", feed)
    app.router.add_get("/calendar/cover.png", cover_picture)
    app.router.add_get("/calendar/img/{name}", image)
    app.router.add_get("/calendar/article", article_page)
    app.router.add_get("/calendar/article.zip", article_zip)
    app.router.add_get("/calendar/day.png", day_picture)


def article_html(a: dict, png_url: str, zip_url: str = "", cover_url: str = "", top: str = "") -> str:
    """The copy page around share.article's text (also the article editor's finished article, with
    ``top``: a line of HTML above the title, its "back to the editor" link). Copying uses a selection + execCommand("copy"):
    the newer clipboard API only works on https or localhost, and this page is plain http on the home
    network. Copying a selection keeps it as rich text, which is what X's Article editor wants. The
    "Picture N · Save" lines (class nocopy) are taken out of the copy."""
    t = html.escape(a["title"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>X Article · {t}</title><style>
body{{margin:0;background:#15161c;color:#eef;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px 60px}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0}}
button,a.btn{{background:#f72ca2;color:#fff;border:0;border-radius:8px;padding:9px 14px;font:600 15px system-ui;cursor:pointer;text-decoration:none}}
button.alt,a.btn.alt{{background:#2a2d3a}}
.box{{background:#fff;color:#111;border-radius:10px;padding:18px 22px}}
.box h2{{font-size:20px;margin:22px 0 6px}} .box ul{{margin:0;padding-left:22px}} .box a{{color:#1d9bf0}}
#title{{font-size:22px;font-weight:700;background:#fff;color:#111;border-radius:10px;padding:12px 16px}}
.box img{{width:100%;border-radius:8px;display:block}} .box p{{margin:6px 0}}
.box .nocopy{{font-size:13px;color:#667;margin:8px 0 10px}} .box .nocopy p{{margin-top:4px}}
.tip{{color:#aab;font-size:14px}} #done{{color:#b7ef33;font-weight:600}} img{{max-width:100%;border-radius:10px}}
</style></head><body><main>{top}
<p class="tip">On X: Write → <b>Article</b>. Put the cover picture in the box at the top, copy the title into the
title box, then copy the article into the body.</p>
<div id="title">{t}</div>
<div class="bar"><button class="alt" onclick="copy('title')">Copy title</button>
<button onclick="copy('body')">Copy article</button>
{f'<a class="btn alt" href="{html.escape(cover_url, quote=True)}" download="cover.png">Save the cover (5:2)</a>' if cover_url else ""}
<a class="btn alt" href="{html.escape(png_url, quote=True)}" download="calendar.png">Save the full calendar</a>
{f'<a class="btn alt" href="{html.escape(zip_url, quote=True)}">Cover + {len(a.get("pictures") or [])} day pictures (.zip)</a>' if zip_url and a.get("pictures") else ""}
<span id="done"></span></div>
<p class="tip">X can't fetch pictures from your home network, so Copy article leaves them out: after pasting, put
each day's picture under its heading with X's picture button (the zip has them numbered in order).</p>
<div class="box" id="body">{a["html"]}</div>
<p class="tip">Cover picture (5:2):</p><img src="{html.escape(cover_url or png_url, quote=True)}" alt="">
</main><script>
function copy(id){{const src=document.getElementById(id),el=src.cloneNode(true);
el.querySelectorAll('.nocopy').forEach(n=>n.remove());el.style.cssText='position:fixed;left:-9999px;top:0';
document.body.appendChild(el);const r=document.createRange();r.selectNodeContents(el);
const s=getSelection();s.removeAllRanges();s.addRange(r);const ok=document.execCommand('copy');s.removeAllRanges();el.remove();
document.getElementById('done').textContent=ok?'Copied ✓':'Select it and press Ctrl+C';}}
</script></body></html>"""


__all__ = ["add_routes", "ics", "article_html", "get_week", "build_article", "article_query", "Tile"]
