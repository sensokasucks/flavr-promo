"""
The hosts' review cards as HTML pages, screenshotted at 1600 x 900 like the board (X shows a single
16:9 picture whole; owner 2026-11-20: no cropping, names and faces 40 px or more from every edge).

  opener  posted before the review's board: the host in a pose (flavrpromo/hosts.py ``pose``), their
          line in a speech bubble (Colette) or on a filed report (Clark), and up to 3 highlights,
          each with a short comment: tilted sticky notes for Colette, a neat table for Clark. Their
          chibi in the same mood peeks over the bubble / report's top-right edge.
  desk    posted after the board: the host's desk picture with a highlight, a nudge for next time
          and their sign-off ("From Colette's desk" / "Closing notes").

Looks follow the mock-ups the owner approved (project files bot-presenter/two-characters/). Without a
picture the card still works: the bubble / report just gets the whole width. All text is escaped.
  day     one day of an article in the host's look instead of the board's (owner 2026-11-21: the
          day pictures "dont follow the color scheme and fancy format the hosts come in with"):
          Colette pins each stream up as a taped polaroid on her purple wall, Clark files them as
          clipped photos on a cream report page. Their chibi sits in a corner with a line about the
          day (hosts.day_line). Same 1600 x 900 and the same tile sizes as render.day_card.

  cover   the X Article cover (1500 x 600, like render.cover) in the host's look (owner 2026-11-21:
          "the article cover is still in the old style when the hosts are on"): heading and numbers,
          the people's pictures as coloured cards, the host standing on the right.

Who calls it: flavrpromo/host_picker.py (the review posts and the picker page's previews) and /host
preview (flavrpromo/bot.py).
"""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any, Callable, Dict, List

from . import hosts
from .render import COVER_H, COVER_W, DAY_MAX, _plats, clock, cover_people, cover_stats, hm, logo_data_url, tile_layout

BASE = ("*{box-sizing:border-box;margin:0}"
        "body{width:1600px;height:900px;position:relative;overflow:hidden;font-family:'DejaVu Sans',sans-serif}"
        ".note{position:absolute;background:#fbe48a;color:#2a2116;padding:18px 22px;font-size:25px;line-height:1.3;"
        "box-shadow:4px 6px 14px #0006;font-weight:600}"
        ".bub{position:absolute;background:#fff;color:#1a1a1a;border-radius:30px;padding:26px 32px;font-size:30px;"
        "line-height:1.32;font-weight:700;box-shadow:0 8px 30px #0007}"
        ".serif{font-family:'DejaVu Serif',serif}")
NOTE_COLOURS = ("#fbe48a", "#b7ef33", "#2ae0d4")       # Colette's sticky notes (FlaVR yellow, lime, teal)
NOTE_TILT = ("-3deg", "2deg", "-1.5deg")


def _e(text: str) -> str:
    return html.escape(str(text or ""))


def _doc(body_style: str, inner: str) -> str:
    return f"<!doctype html><html><head><meta charset=utf-8><style>{BASE}</style></head><body style=\"{body_style}\">{inner}</body></html>"


def _fit(text: str, size: int) -> int:
    """The font size (px) for a host line in a box drawn for ``size`` px: a long line (the settings
    page's Chattiness "chatty", or the owner's own text up to kobold.MAX_CHARS) is set smaller so it
    still ends above what is drawn under it."""
    n = len(text or "")
    return size if n <= 260 else int(size * 0.88) if n <= 360 else int(size * 0.78)


def _reply(key: str, text: str, style: str) -> str:
    """Banter (owner 2026-11-22): host ``key``'s short answer, drawn on the OTHER host's opener card in
    ``key``'s own look: a taped sticky note for Colette, a cream memo slip for Clark, each with their
    head. ``style``: where it sits (absolute position and width). "" when there is no reply."""
    if not text or key not in hosts.HOSTS:
        return ""
    head = hosts.data_url(key, "head") or hosts.data_url(key, "chibi_head")
    face = (f'<img src="{head}" style="width:84px;height:84px;border-radius:50%;object-fit:cover;flex:none;'
            f'border:4px solid #fff;box-shadow:0 3px 8px #0006">') if head else ""
    name = hosts.HOSTS[key]["name"].split()[0]
    words = _e(text if len(text) <= 190 else text[:190].rsplit(" ", 1)[0] + "…")
    if key == "clark":
        return (f'<div class=serif style="position:absolute;{style};display:flex;gap:16px;align-items:center;background:#f4ead8;'
                f'color:#2b1d12;border-left:8px solid #e0782e;padding:12px 20px;font-size:22px;line-height:1.3;'
                f'box-shadow:4px 6px 14px #0007;transform:rotate(-1deg)">{face}<div><div style="font-size:15px;'
                f'letter-spacing:2px;color:#8a5a33">MEMO FROM {_e(name.upper())}</div>{words}</div></div>')
    return (f'<div style="position:absolute;{style};display:flex;gap:16px;align-items:center;background:#ff9ad5;color:#2a1026;'
            f'font-family:\'DejaVu Sans\',sans-serif;'       # her own type, also on Clark's serif report
            f'padding:12px 20px;font-size:22px;line-height:1.3;font-weight:700;box-shadow:4px 6px 14px #0007;'
            f'transform:rotate(1.2deg)">{face}<div><div style="font-size:15px;letter-spacing:2px;color:#7a1050">'
            f'{_e(name.upper())} SAYS</div>{words}</div></div>')


def opener(key: str, heading: str, range_text: str, line: str, notes: List[Dict[str, str]],
           comments: List[str], pose: str, chibi_main: bool = False, preview: bool = False,
           reply: str = "", reply_key: str = "", fx: str = "") -> str:
    """The opener card. ``notes``: hosts.notes() rows; ``comments``: the picked comment for each.
    ``reply`` / ``reply_key``: banter, the other host's short answer and who that is (``_reply``; it
    takes the place of the "board follows" footer's spot, which moves down a little).
    ``preview``: the Sunday preview's opener (hosts.preview_notes rows; the board follows, no desk
    card after it, so the footer and Clark's report header say so).
    ``chibi_main``: the big figure is the chibi and the regular pose peeks (picker page "opener
    picture"; Sen 2026-11-21: chibis mixed in with the regular pictures).
    ``fx``: CSS (transform and origin) for the big figure's size / turn / mirror / move (tall.picture_fx; the article
    editor's "Host picture" boxes, p["figs"]); "" = as designed."""
    big, small = (f"chibi_{pose}", pose) if chibi_main else (pose, f"chibi_{pose}")
    pic = hosts.data_url(key, big) or hosts.data_url(key, small)
    # the other style in the same mood peeks over the top-right edge of the bubble / report: drawn
    # before it, so the card covers its lower half (no such picture = nothing)
    chibi = hosts.data_url(key, small) if hosts.data_url(key, big) else ""
    # (cut off just under the card's top edge at y 170, so a short bubble never shows the chibi's feet)
    peek = (f'<div style="position:absolute;right:90px;top:24px;width:260px;height:156px;overflow:hidden">'
            f'<img src="{chibi}" style="display:block;margin:0 auto;height:290px;max-width:260px;object-fit:contain">'
            f'</div>') if chibi else ""
    left = 470 if pic else 60
    width = 1540 - left
    # the big figure stands in a box that reaches from the card's left edge to the report / bubble (x 470),
    # centred and on the floor of it: a wide picture (arms out) gets the whole width, a tall one the height
    rows = list(zip(notes, comments + [""] * len(notes)))
    if key == "clark":
        img = f'<img src="{pic}" style="position:absolute;left:14px;top:170px;height:690px;width:450px;object-fit:contain;object-position:bottom;{fx}">' if pic else ""
        table = "".join(
            f'<tr style="border-bottom:1px solid #d8c3a3"><td style="padding:9px 0;color:#8a5a33">{_e(n["label"].title())}</td>'
            f'<td style="text-align:right"><b>{_e(n["value"])}</b>{(" · <i>" + _e(c) + "</i>") if c else ""}</td></tr>'
            for n, c in rows)
        inner = (f'<div class=serif style="position:absolute;left:44px;top:34px;font-size:56px;color:#e0782e">{_e(heading)}</div>'
                 f'<div style="position:absolute;left:46px;top:106px;font-size:22px;letter-spacing:2px;color:#d9b88a">'
                 f'FILED BY CLARK · DIVISION CLERK</div>{img}{peek}'
                 f'<div class=serif style="position:absolute;left:{left}px;top:170px;width:{width}px;height:660px;background:#f4ead8;'
                 f'color:#2b1d12;border-radius:6px;box-shadow:0 10px 30px #000a;padding:36px 44px">'
                 f'<div style="display:flex;justify-content:space-between;font-size:20px;letter-spacing:2px;color:#8a5a33;'
                 f'border-bottom:2px solid #c9a77c;padding-bottom:10px"><span>{"SCHEDULE" if preview else "REPORT"} · {_e(range_text.upper())}</span>'
                 f'<span>STATUS: {"ON FILE" if preview else "IN ORDER"} 🍎</span></div>'
                 f'<div style="font-size:{_fit(line, 30)}px;line-height:1.45;margin-top:22px">{_e(line)}</div>'
                 f'<table style="margin-top:26px;font-size:24px;border-collapse:collapse;width:100%">{table}</table>'
                 # the other host's answer: stuck on the bottom of the report, left of the "board follows" line
                 f'{_reply(reply_key, reply, "left:36px;bottom:22px;width:" + str(width - 400) + "px")}'
                 f'<div style="position:absolute;right:40px;bottom:30px;font-size:21px;color:#8a5a33;font-style:italic">'
                 f'{"The week\'s board follows. — C." if preview else "The full board follows. — C."}</div></div>')
        return _doc("background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3", inner)
    # Colette
    img = f'<img src="{pic}" style="position:absolute;left:14px;top:160px;height:700px;width:450px;object-fit:contain;object-position:bottom;{fx}">' if pic else ""
    step = (width - 20) // 3
    stickies = "".join(
        f'<div class=note style="left:{left + 10 + i * step}px;top:{480 + (i % 2) * 30}px;transform:rotate({NOTE_TILT[i]});'
        f'width:{step - 30}px;background:{NOTE_COLOURS[i]}">📌 {_e(n["label"])}<br><b style="font-size:28px">{_e(n["value"])}</b>'
        + (f'<br><span style="font-size:19px">"{_e(c)}"</span>' if c else "") + "</div>"
        for i, (n, c) in enumerate(rows))
    inner = (f'<img src="{logo_data_url()}" style="position:absolute;left:40px;top:30px;height:66px">'
             f'<div style="position:absolute;left:270px;top:36px;font-size:50px;font-weight:900;letter-spacing:3px">{_e(heading.upper())}</div>'
             f'<div style="position:absolute;left:272px;top:98px;font-size:22px;color:#f8cf33;font-weight:700">'
             f'with Colette Cappuccino · Marketing · {_e(range_text)}</div>{img}{peek}'
             f'<div class=bub style="left:{left}px;top:170px;width:{width}px;border:5px solid #f72ca2;'
             f'font-size:{_fit(line, 30)}px">{_e(line)}</div>'
             # the other host's answer sits under the sticky notes; the "next picture" line moves below it
             f'{stickies}{_reply(reply_key, reply, f"left:{left + 20}px;top:706px;width:{width - 60}px")}'
             f'<div style="position:absolute;left:{left + 20}px;top:{828 if reply else 790}px;font-size:{22 if reply else 24}px;color:#ddd">'
             f'{"This week\'s board in the next picture ↓ &nbsp; See you there!!" if preview else "Full board in the next picture ↓ &nbsp; My notes at the end!"}</div>')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff", inner)


def desk(key: str, highlight: str, nudge: str, signoff: str, kind: str = "desk", fx: str = "") -> str:
    """The closing desk card. ``fx``: CSS for the desk picture's size / turn / mirror / move, as in ``opener``."""
    # ``kind``: "desk" or "chibi_desk" (picked on the picker page, flavrpromo/host_picker.py). The picture
    # fills its panel and is kept at the top (object-position), so a taller one loses desk, not hair.
    pic = hosts.data_url(key, kind) or hosts.data_url(key, "desk")
    if key == "clark":
        left = 700 if pic else 60
        img = f'<img src="{pic}" style="position:absolute;left:0;top:0;width:700px;height:900px;object-fit:cover;object-position:top;{fx}">' if pic else ""
        text = "<br><br>".join(_e(x) for x in (highlight, nudge) if x)
        inner = (f'{img}<div style="position:absolute;left:{left}px;top:0;right:0;height:900px;background:linear-gradient(135deg,#2a1c12,#3b2416)"></div>'
                 f'<div class=serif style="position:absolute;left:{left + 70}px;top:60px;font-size:30px;color:#e0782e">Closing notes</div>'
                 f'<div class=serif style="position:absolute;left:{left + 70}px;top:120px;right:60px;background:#f4ead8;color:#2b1d12;'
                 f'padding:34px 40px;font-size:28px;line-height:1.5;box-shadow:0 10px 30px #000a;border-radius:4px">{text}</div>'
                 f'<div class=serif style="position:absolute;right:80px;bottom:90px;font-size:34px;color:#e0b07a;font-style:italic">'
                 f'{_e(signoff)}</div>')
        return _doc("background:#1c130d", inner)
    left = 960 if pic else 60
    img = (f'<img src="{pic}" style="position:absolute;left:0;top:0;width:960px;height:900px;object-fit:cover;object-position:top;{fx}">'
           f'<div style="position:absolute;left:900px;top:0;width:700px;height:900px;'
           f'background:linear-gradient(90deg,#1b101800,#2a1026 12%)"></div>') if pic else ""
    inner = (f'{img}<div style="position:absolute;left:{left + 30}px;top:50px;font-size:26px;color:#f8cf33;font-weight:800;'
             f'letter-spacing:2px">FROM COLETTE\'S DESK</div>'
             f'<div class=bub style="left:{left}px;top:110px;right:40px;font-size:27px;border:5px solid #f72ca2">{_e(highlight)}</div>'
             + (f'<div class=note style="left:{left + 40}px;top:520px;right:60px;transform:rotate(-2deg);font-size:22px">'
                f'To do for next time:<br>☐ {_e(nudge)}</div>' if nudge else "")
             + f'<div style="position:absolute;left:{left + 40}px;top:770px;font-size:24px;color:#ddd;font-style:italic">'
               f'— {_e(signoff)}</div>')
    return _doc("background:linear-gradient(135deg,#1b1018,#2a1026)", inner)


DAY_HOST_W = 300        # px on the right of a host day card kept for the chibi and their line
TAPE = ("#f8cf33cc", "#b7ef33cc", "#2ae0d4cc", "#f72ca2cc")     # Colette's tape colours (FlaVR, see-through)
TILT = ("-2deg", "1.5deg", "-1deg", "2.2deg", "-1.6deg", "1deg")


# the day picture layouts the article editor offers (owner 2026-11-21: "one or two more alternative
# layouts so i can pick from them"); each one in both hosts' looks. Keep in step with ``day``.
DAY_LAYOUTS = {"wall": "Pinned wall (every stream the same size)",
               "timeline": "Timeline (in time order, with stream titles)",
               "spotlight": "Spotlight (the longest stream big, the rest beside it)",
               "columns": "Two columns of colour strips (busy days)",
               "zigzag": "Zigzag colour strips (bigger pictures)",
               "cards": "Colour cards (time on top, title under)"}


def day(key: str, week: Any, i: int, img: Callable[[str], str], line: str = "", chibi_kind: str = "",
        layout: str = "wall", fx: str = "") -> str:
    """Day ``i`` of ``week`` (flavrpromo/calendar.py Week) in host ``key``'s look. ``img``: a picture
    address for a thumbnail / avatar URL (render.ImageCache.data_url). ``line``: what the host says
    about the day ("" = no bubble). ``chibi_kind``: which picture stands in the corner (default
    their happy chibi). ``layout``: one of DAY_LAYOUTS (unknown = wall). ``fx``: CSS
    (transform and origin) for the host picture's size / turn / mirror / move (tall.picture_fx; "" = as designed).
    Called by flavrpromo/article_editor.py (/settings/article/day)."""
    if layout in DAY_LAYOUTS and layout != "wall":
        return _day_alt(key, week, i, img, line, chibi_kind, layout, fx)
    date = week.start + timedelta(days=i)
    tiles = list(week.days[i])
    shown = tiles if len(tiles) <= DAY_MAX else tiles[:DAY_MAX - 1]
    count = len(shown) + (len(tiles) > len(shown))
    area_w = 1600 - 80 - DAY_HOST_W
    cols, rows, tw, label = tile_layout(max(1, count), area_w - 40)
    # the polaroid / photo frames, tilt and the heading take room the board's plain tiles don't: a bit
    # smaller, and one stream never wider than a photo should be (it would run off the bottom)
    tw = min(int(tw * 0.86), 820)
    pic = hosts.data_url(key, chibi_kind or "chibi_happy") or hosts.data_url(key, "chibi_happy")
    cells = []
    for k, t in enumerate(shown):
        src = img(t.thumb) or img(t.avatar)
        bg = f"background-image:url(&quot;{_e(src)}&quot;)" if src else ""
        when = clock(t.at, week.tz) + (f" · {hm(t.length)}" if t.kind == "past" and t.end else
                                       " · LIVE" if t.kind == "live" else "")
        cells.append((k, t, bg, when))
    n_word = f"{len(tiles)} stream{'' if len(tiles) == 1 else 's'}"
    if key == "clark":
        photos = "".join(
            f'<div class=ph style="width:{tw}px"><i style="{bg}">{_plats(t)}</i><div class=clip></div>'
            f'<b style="font-size:{label}px">{_e(t.name)}</b><span style="font-size:{label - 4}px">{_e(when)}</span></div>'
            for k, t, bg, when in cells)
        if len(tiles) > len(shown):
            photos += f'<div class=ph style="width:{tw}px;font-size:26px;color:#8a5a33">+{len(tiles) - len(shown)} more on file</div>'
        if not tiles:
            photos = '<div style="font-size:34px;color:#8a5a33;margin:auto">Nothing on file for this day.</div>'
        css = (".pg{position:absolute;left:40px;top:150px;width:" + str(area_w) + "px;height:710px;background:#f4ead8;"
               "border-radius:6px;box-shadow:0 10px 30px #000a;padding:26px 20px;display:flex;flex-wrap:wrap;"
               "justify-content:center;align-content:center;gap:28px 18px}"
               ".ph{background:#fffaf0;padding:8px 8px 6px;box-shadow:0 3px 8px #0004;position:relative;color:#2b1d12}"
               ".ph i{display:block;aspect-ratio:16/9;background:#d9c7a8 center/cover no-repeat;position:relative}"
               ".ph b{display:block;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
               ".ph span{display:block;color:#8a5a33;white-space:nowrap}"
               ".clip{position:absolute;top:-12px;left:22px;width:16px;height:40px;border:4px solid #9aa3ad;border-radius:9px}"
               ".plat{position:absolute;top:6px;right:6px;width:24px;height:24px;border-radius:5px;font:800 13px sans-serif;"
               "display:inline-flex;align-items:center;justify-content:center}.ph i .plat+.plat{right:34px}")
        side = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:40px;width:{DAY_HOST_W - 20}px;height:380px;'
                f'object-fit:contain;object-position:bottom;{fx}">' if pic else "")
        say = (f'<div class=serif style="position:absolute;right:30px;bottom:{440 if pic else 60}px;width:{DAY_HOST_W - 20}px;'
               f'background:#f4ead8;color:#2b1d12;padding:18px 20px;font-size:22px;line-height:1.4;border-radius:4px;'
               f'box-shadow:0 8px 20px #0009;font-style:italic">{_e(line)}<div style="text-align:right;margin-top:6px">— C.</div></div>'
               if line else "")
        inner = (f'<style>{css}</style>'
                 f'<div class=serif style="position:absolute;left:44px;top:30px;font-size:54px;color:#e0782e">'
                 f'{_e(f"{date:%A}, {date:%B} {date.day}")}</div>'
                 f'<div style="position:absolute;left:46px;top:102px;font-size:21px;letter-spacing:2px;color:#d9b88a">'
                 f'DAY REPORT · {_e(n_word.upper())} · FILED BY CLARK</div>'
                 f'<div class="pg serif">{photos}</div>{side}{say}')
        return _doc("background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3", inner)
    # Colette: taped polaroids on her purple wall
    shots = "".join(
        f'<div class=po style="width:{tw + 20}px;transform:rotate({TILT[k % len(TILT)]})">'
        f'<div class=tape style="background:{TAPE[k % len(TAPE)]}"></div><i style="{bg}">{_plats(t)}</i>'
        f'<b style="font-size:{label}px">{_e(t.name)}</b><span style="font-size:{label - 4}px">{_e(when)}</span></div>'
        for k, t, bg, when in cells)
    if len(tiles) > len(shown):
        shots += (f'<div class=note style="position:static;width:{tw}px;transform:rotate(2deg)">'
                  f'+{len(tiles) - len(shown)} more!!</div>')
    if not tiles:
        shots = '<div class=note style="position:static;font-size:34px;transform:rotate(-2deg)">Nothing on the board yet!</div>'
    css = (".wall{position:absolute;left:40px;top:150px;width:" + str(area_w) + "px;height:720px;display:flex;flex-wrap:wrap;"
           "justify-content:center;align-content:center;gap:22px 24px}"
           ".po{background:#fff;padding:10px 10px 8px;box-shadow:4px 8px 18px #0008;position:relative;color:#1a1a1a}"
           ".po i{display:block;aspect-ratio:16/9;background:#2a1026 center/cover no-repeat;position:relative}"
           ".po b{display:block;margin-top:6px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
           ".po span{display:block;color:#c21c80;font-weight:700;white-space:nowrap}"
           ".tape{position:absolute;top:-14px;left:50%;width:110px;height:30px;margin-left:-55px;transform:rotate(-3deg);"
           "box-shadow:0 1px 3px #0003}"
           ".plat{position:absolute;top:6px;right:6px;width:24px;height:24px;border-radius:5px;font:800 13px sans-serif;"
           "display:inline-flex;align-items:center;justify-content:center}.po i .plat+.plat{right:34px}")
    side = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:30px;width:{DAY_HOST_W - 20}px;height:380px;'
            f'object-fit:contain;object-position:bottom;{fx}">' if pic else "")
    say = (f'<div class=bub style="right:30px;bottom:{420 if pic else 60}px;width:{DAY_HOST_W - 10}px;font-size:22px;'
           f'border:5px solid #f72ca2">{_e(line)}</div>' if line else "")
    inner = (f'<style>{css}</style><img src="{logo_data_url()}" style="position:absolute;left:40px;top:30px;height:66px">'
             f'<div style="position:absolute;left:270px;top:32px;font-size:52px;font-weight:900;letter-spacing:3px">'
             f'{_e(f"{date:%A} · {date:%b} {date.day}".upper())}</div>'
             f'<div style="position:absolute;left:272px;top:98px;font-size:22px;color:#f8cf33;font-weight:700">'
             f'{_e(n_word)} · pinned up by Colette ☕</div><div class=wall>{shots}</div>{side}{say}')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff", inner)


# ── the other two day layouts: the same host skins (heading, frames, chibi + line) ─────────
def _skin(key: str, date: Any, n_word: str, pic: str, line: str, fx: str = "") -> Dict[str, str]:
    """A host's look for a day picture: page background, heading, the chibi + line on the right and
    the CSS for frames (.fr), names (.nm), times (.tm) and titles (.tt)."""
    plat = (".plat{position:absolute;top:6px;right:6px;width:24px;height:24px;border-radius:5px;font:800 13px sans-serif;"
            "display:inline-flex;align-items:center;justify-content:center}.fr i .plat+.plat{right:34px}"
            ".fr i{display:block;aspect-ratio:16/9;background-repeat:no-repeat;background-size:cover;background-position:center;"
            "position:relative}")
    if key == "clark":
        side = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:40px;width:{DAY_HOST_W - 20}px;height:380px;'
                f'object-fit:contain;object-position:bottom;{fx}">' if pic else "")
        say = (f'<div class=serif style="position:absolute;right:30px;bottom:{440 if pic else 60}px;width:{DAY_HOST_W - 20}px;'
               f'background:#f4ead8;color:#2b1d12;padding:18px 20px;font-size:22px;line-height:1.4;border-radius:4px;'
               f'box-shadow:0 8px 20px #0009;font-style:italic">{_e(line)}<div style="text-align:right;margin-top:6px">— C.</div></div>'
               if line else "")
        return {"body": "background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3",
                "head": (f'<div class=serif style="position:absolute;left:44px;top:30px;font-size:54px;color:#e0782e">'
                         f'{_e(f"{date:%A}, {date:%B} {date.day}")}</div>'
                         f'<div style="position:absolute;left:46px;top:102px;font-size:21px;letter-spacing:2px;color:#d9b88a">'
                         f'DAY REPORT · {_e(n_word.upper())} · FILED BY CLARK</div>'),
                "side": side + say, "font": "serif", "accent": "#e0782e",
                "css": (plat + ".pg{position:absolute;left:40px;top:150px;width:" + str(1520 - DAY_HOST_W) + "px;height:710px;"
                        "background:#f4ead8;border-radius:6px;box-shadow:0 10px 30px #000a;color:#2b1d12}"
                        ".fr{background:#fffaf0;padding:8px;box-shadow:0 3px 8px #0004;position:relative}"
                        ".fr i{background-color:#d9c7a8}"
                        ".clip{position:absolute;top:-12px;left:22px;width:16px;height:40px;border:4px solid #9aa3ad;border-radius:9px}"
                        ".nm{font-weight:700;color:#2b1d12}.tm{color:#8a5a33}.tt{color:#5a4030;font-style:italic}"
                        ".stamp{position:absolute;border:4px solid #b8402a;color:#b8402a;font:700 24px 'DejaVu Serif',serif;"
                        "letter-spacing:3px;padding:6px 14px;transform:rotate(-6deg);background:#f4ead8cc}")}
    side = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:30px;width:{DAY_HOST_W - 20}px;height:380px;'
            f'object-fit:contain;object-position:bottom;{fx}">' if pic else "")
    say = (f'<div class=bub style="right:30px;bottom:{420 if pic else 60}px;width:{DAY_HOST_W - 10}px;font-size:22px;'
           f'border:5px solid #f72ca2">{_e(line)}</div>' if line else "")
    return {"body": "background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff",
            "head": (f'<img src="{logo_data_url()}" style="position:absolute;left:40px;top:30px;height:66px">'
                     f'<div style="position:absolute;left:270px;top:32px;font-size:52px;font-weight:900;letter-spacing:3px">'
                     f'{_e(f"{date:%A} · {date:%b} {date.day}".upper())}</div>'
                     f'<div style="position:absolute;left:272px;top:98px;font-size:22px;color:#f8cf33;font-weight:700">'
                     f'{_e(n_word)} · pinned up by Colette ☕</div>'),
            "side": side + say, "font": "", "accent": "#f72ca2",
            "css": (plat + ".pg{position:absolute;left:40px;top:150px;width:" + str(1520 - DAY_HOST_W) + "px;height:720px}"
                    ".fr{background:#fff;padding:10px;box-shadow:4px 8px 18px #0008;position:relative;color:#1a1a1a}"
                    ".fr i{background-color:#2a1026}"
                    ".tape{position:absolute;top:-14px;left:50%;width:110px;height:30px;margin-left:-55px;transform:rotate(-3deg)}"
                    ".nm{font-weight:900;color:#1a1a1a}.tm{color:#c21c80;font-weight:700}.tt{color:#444}"
                    ".stamp{position:absolute;background:#f8cf33;color:#2a2116;font:900 24px sans-serif;padding:10px 16px;"
                    "transform:rotate(-5deg);box-shadow:3px 5px 10px #0007}")}


def _day_alt(key: str, week: Any, i: int, img: Callable[[str], str], line: str, chibi_kind: str, layout: str, fx: str = "") -> str:
    """The timeline and spotlight layouts of ``day``.
    timeline   one row per stream in time order: a time chip, the thumbnail, the name, the stream
               title and its length (Colette: sticky-note strips in turn; Clark: a ruled ledger page).
               At most TIMELINE_MAX rows, then "+N more".
    spotlight  the day's longest stream (else the first) big on the left with a "top pick" / "featured
               entry" stamp, the others smaller in two columns beside it (at most SPOT_MAX).
    columns    coloured strips like Colette's timeline in two columns (busy days, COLUMNS_MAX).
    zigzag     one bigger coloured strip per stream, swinging left and right (ZIGZAG_MAX).
    cards      tall coloured cards side by side: time on top, picture, name, length, title (CARDS_MAX).
    The colourful ones use COLETTE_COLOURS / CLARK_COLOURS (Sen 2026-11-21)."""
    date = week.start + timedelta(days=i)
    tiles = sorted(week.days[i], key=lambda t: t.at)
    n_word = f"{len(tiles)} stream{'' if len(tiles) == 1 else 's'}"
    pic = hosts.data_url(key, chibi_kind or "chibi_happy") or hosts.data_url(key, "chibi_happy")
    sk = _skin(key, date, n_word, pic, line, fx)
    clark = key == "clark"
    area_w = 1520 - DAY_HOST_W

    def bg(t: Any) -> str:
        src = img(t.thumb) or img(t.avatar)
        return f"background-image:url(&quot;{_e(src)}&quot;)" if src else ""

    def when(t: Any) -> str:
        return clock(t.at, week.tz) + (f" · {hm(t.length)}" if t.kind == "past" and t.end else
                                       " · LIVE" if t.kind == "live" else "")

    def deco(k: int) -> str:
        return '<div class=clip></div>' if clark else f'<div class=tape style="background:{TAPE[k % len(TAPE)]}"></div>'

    if not tiles:
        body = (f'<div class=pg style="display:flex;align-items:center;justify-content:center;font-size:34px">'
                f'{"Nothing on file for this day." if clark else "Nothing on the board yet!"}</div>')
    elif layout == "timeline":
        shown = tiles if len(tiles) <= TIMELINE_MAX else tiles[:TIMELINE_MAX - 1]
        n = len(shown) + (len(tiles) > len(shown))
        row_h = min(150, (680 - 12 * (n - 1)) // n)
        thumb_w = int((row_h - 16) * 16 / 9)
        fs = max(18, min(30, row_h // 4))
        rows = []
        for k, t in enumerate(shown):
            title = _e((t.title or t.game or "")[:90])
            if clark:
                box = "border-bottom:2px solid #d8c3a3;padding:6px 18px"
            else:
                box = (f"background:{NOTE_COLOURS[k % 3]};padding:8px 18px;transform:rotate({'-0.6' if k % 2 else '0.5'}deg);"
                       "box-shadow:3px 5px 12px #0007;color:#2a2116")
            chip = (f'<div class=tm style="width:150px;font-size:{fs}px;flex:none">{_e(clock(t.at, week.tz))}</div>' if clark else
                    f'<div style="width:150px;flex:none;font:900 {fs}px sans-serif;color:#fff;background:#f72ca2;'
                    f'border-radius:30px;text-align:center;padding:6px 0">{_e(clock(t.at, week.tz))}</div>')
            rows.append(f'<div style="display:flex;align-items:center;gap:20px;height:{row_h}px;{box}">{chip}'
                        f'<div class=fr style="width:{thumb_w}px;padding:4px;flex:none"><i style="{bg(t)}">{_plats(t)}</i></div>'
                        f'<div style="min-width:0"><div class=nm style="font-size:{fs + 2}px">{_e(t.name)}'
                        f'<span class=tm style="font-size:{fs - 4}px"> · {_e(when(t).split(" · ", 1)[1] if " · " in when(t) else "")}</span></div>'
                        f'<div class=tt style="font-size:{fs - 6}px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{title}</div></div></div>')
        if len(tiles) > len(shown):
            rows.append(f'<div class=tm style="font-size:24px;padding:4px 18px">+{len(tiles) - len(shown)} more</div>')
        pad = "padding:20px 30px" if clark else "padding:10px 0"
        body = f'<div class="pg {sk["font"]}" style="display:flex;flex-direction:column;justify-content:center;gap:12px;{pad}">{"".join(rows)}</div>'
    elif layout in ("columns", "zigzag"):
        # coloured strips like Colette's timeline (Sen 2026-11-21: "pretty clean and colorful"), both hosts
        if layout == "columns":     # two columns of strips: room for a busy day
            cap = COLUMNS_MAX
            shown = tiles if len(tiles) <= cap else tiles[:cap - 1]
            n = len(shown) + (len(tiles) > len(shown))
            per = -(-n // 2) if n > 3 else n
            row_h = min(170, (660 - 12 * (per - 1)) // per)
            width = (area_w - 60) // 2 if n > 3 else area_w - 40
        else:                       # one strip per stream, swinging left and right, bigger pictures
            cap = ZIGZAG_MAX
            shown = tiles if len(tiles) <= cap else tiles[:cap - 1]
            n = len(shown) + (len(tiles) > len(shown))
            row_h = min(200, (680 - 14 * (n - 1)) // n)
            width = area_w - 200
        strips = []
        for k, t in enumerate(shown):
            tilt = 0.0 if clark else (-0.6 if k % 2 else 0.5)
            flip = layout == "zigzag" and k % 2 == 1
            strip = _strip(t, k, row_h, width, clark, img, week.tz, tilt, flip)
            if layout == "zigzag":
                strip = f'<div style="margin-left:{180 if flip else 0}px">{strip}</div>'
            strips.append(strip)
        if len(tiles) > len(shown):
            strips.append(f'<div class=tm style="font-size:24px;padding:4px 18px;width:{width}px">+{len(tiles) - len(shown)} more</div>')
        if layout == "columns" and n > 3:
            box = (f"display:grid;grid-template-columns:{width}px {width}px;grid-auto-flow:column;"
                   f"grid-template-rows:repeat({per},{row_h}px);gap:12px 20px;align-content:center;justify-content:center")
        else:
            box = "display:flex;flex-direction:column;justify-content:center;gap:14px;padding-left:20px"
        body = f'<div class="pg {sk["font"]}" style="{box};{"padding:10px" if clark else ""}">{"".join(strips)}</div>'
    elif layout == "cards":
        # a row (or two) of tall coloured cards: the time on top, the picture, the name, the title
        shown = tiles if len(tiles) <= CARDS_MAX else tiles[:CARDS_MAX - 1]
        n = len(shown) + (len(tiles) > len(shown))
        cols = n if n <= 5 else -(-n // 2)
        rows_n = -(-n // cols)
        cw = min(400, (area_w - 40 - 18 * (cols - 1)) // cols)
        pal = CLARK_COLOURS if clark else COLETTE_COLOURS

        def card_h(w: int) -> float:
            """A card's height in px at width ``w`` (padding, chip, picture, name, length, title)."""
            f = 30 if w >= 300 else 24 if w >= 210 else 19
            return 24 + (f + 12) + 18 + (w - 34) * 9 / 16 + 1.3 * (f - 2) + 1.3 * (f - 8) + 2 * (f - 6) + 10

        while cw > 120 and rows_n * card_h(cw) + 24 * (rows_n - 1) > 690:
            cw -= 10                                # two rows must fit under the heading
        fs = 30 if cw >= 300 else 24 if cw >= 210 else 19
        cards = []
        for k, t in enumerate(shown):
            tilt = "" if clark else f"transform:rotate({TILT[k % len(TILT)]});"
            cards.append(
                f'<div style="width:{cw}px;background:{pal[k % len(pal)]};border-radius:{6 if clark else 14}px;'
                f'padding:12px;box-shadow:4px 7px 16px #0007;color:#2a2116;{tilt}">'
                f'{_chip(clock(t.at, week.tz), fs, clark, block=True)}'
                f'<div class=fr style="padding:5px;margin:10px 0 8px"><i style="{_bg(t, img)}">{_plats(t)}</i></div>'
                f'<div class=nm style="font-size:{fs - 2}px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{_e(t.name)}</div>'
                f'<div style="font-size:{fs - 8}px;font-weight:700;color:#5a2a3a">{_e(_length(t))}</div>'
                f'<div style="font-size:{fs - 10}px;color:#3a3028;height:{2 * (fs - 6)}px;overflow:hidden;line-height:1.25">'
                f'{_e((t.title or t.game or "")[:80])}</div></div>')
        if len(tiles) > len(shown):
            cards.append(f'<div class=tm style="width:{cw}px;font-size:26px;align-self:center;text-align:center">'
                         f'+{len(tiles) - len(shown)} more</div>')
        body = (f'<div class="pg {sk["font"]}" style="display:flex;flex-wrap:wrap;justify-content:center;align-content:center;'
                f'gap:{24 if rows_n > 1 else 0}px 18px;padding:10px">{"".join(cards)}</div>')
    else:
        star = max(tiles, key=lambda t: t.length if t.kind == "past" and t.end else -1) \
            if any(t.kind == "past" and t.end for t in tiles) else tiles[0]
        rest = [t for t in tiles if t is not star]
        more = len(rest) - SPOT_MAX
        rest = rest[:SPOT_MAX - 1] if more > 0 else rest
        big_w = 900 if not rest else 820 if len(rest) <= 2 else 740     # more beside it = a smaller star
        stamp = "FEATURED ENTRY" if clark else "⭐ TOP PICK!"
        big = (f'<div class=fr style="position:absolute;left:{20 if rest else (area_w - big_w) // 2}px;top:70px;width:{big_w}px;'
               f'{"" if clark else "transform:rotate(-1.5deg);"}">{deco(0)}<i style="{bg(star)}">{_plats(star)}</i>'
               f'<div class=nm style="font-size:34px;margin-top:8px">{_e(star.name)}</div>'
               f'<div class=tm style="font-size:24px">{_e(when(star))}</div>'
               f'<div class=tt style="font-size:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
               f'{_e((star.title or star.game or "")[:90])}</div>'
               f'<div class=stamp style="left:-16px;top:-22px">{stamp}</div></div>')
        small_w = (area_w - big_w - 90 - 20) // 2      # two columns in the space beside it (box left big_w+60, right 10)
        cells = "".join(
            f'<div class=fr style="width:{small_w}px;{"" if clark else f"transform:rotate({TILT[k % len(TILT)]});"}">'
            f'{deco(k + 1)}<i style="{bg(t)}">{_plats(t)}</i><div class=nm style="font-size:18px;margin-top:4px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{_e(t.name)}</div>'
            f'<div class=tm style="font-size:15px">{_e(when(t))}</div></div>' for k, t in enumerate(rest))
        if more > 0:
            cells += f'<div class=tm style="width:{small_w}px;font-size:24px;align-self:center">+{more + 1} more</div>'
        side = (f'<div style="position:absolute;left:{big_w + 60}px;top:40px;right:10px;bottom:20px;display:flex;'
                f'flex-wrap:wrap;align-content:center;gap:30px 20px">{cells}</div>') if rest else ""
        body = f'<div class="pg {sk["font"]}">{big}{side}</div>'
    return _doc(sk["body"], f'<style>{sk["css"]}</style>{sk["head"]}{body}{sk["side"]}')


TIMELINE_MAX = 7        # rows on a timeline day picture; more = "+N more" (the article lists them all)
COLUMNS_MAX = 12        # strips on a two-column day picture
ZIGZAG_MAX = 7          # strips on a zigzag day picture (bigger pictures, fewer fit)
CARDS_MAX = 10          # cards on a cards day picture (two rows of five)
# the strip / card colours: Colette's FlaVR sticky notes and pink; Clark's 90s file-folder tabs
# (mustard, sage, terracotta, dusty blue)
COLETTE_COLOURS = ("#fbe48a", "#b7ef33", "#2ae0d4", "#ff9ad5")
CLARK_COLOURS = ("#e9c46a", "#a3c48f", "#e8907a", "#9dbcd0")


def _bg(t: Any, img: Callable[[str], str]) -> str:
    """A tile's thumbnail (else the person's picture) as a CSS background for the frame's <i>."""
    src = img(t.thumb) or img(t.avatar)
    return f"background-image:url(&quot;{_e(src)}&quot;)" if src else ""


def _length(t: Any) -> str:
    return hm(t.length) if t.kind == "past" and t.end else "LIVE" if t.kind == "live" else "scheduled"


def _chip(text: str, fs: int, clark: bool, block: bool = False) -> str:
    """The time label: Colette's pink pill, Clark's dark brown tab with cream serif letters."""
    look = ("background:#3b2416;color:#f4ead8;font-family:'DejaVu Serif',serif;border-radius:6px" if clark else
            "background:#f72ca2;color:#fff;border-radius:30px")
    size = "width:100%" if block else "width:150px;flex:none"
    return (f'<div style="{size};{look};font-weight:900;font-size:{fs}px;text-align:center;padding:5px 0">'
            f'{_e(text)}</div>')


def _strip(t: Any, k: int, h: int, w: int, clark: bool, img: Callable[[str], str], tz: Any, tilt: float,
           flip: bool = False) -> str:
    """One coloured strip (columns and zigzag layouts): time chip, thumbnail, name · length, title.
    ``flip``: the thumbnail on the right (zigzag's every other row)."""
    pal = CLARK_COLOURS if clark else COLETTE_COLOURS
    fs = max(16, min(30, h // 4))
    narrow = w < 800                    # a two-column strip: smaller picture and chip, more room for the name
    thumb_w = int((h - 16) * (0.72 if narrow else 1) * 16 / 9)
    chip_w = 100 if narrow else 150
    fs = min(fs, 24) if narrow else fs
    text = (f'<div style="min-width:0;flex:1"><div class=nm style="font-size:{fs + 2}px;white-space:nowrap;overflow:hidden;'
            f'text-overflow:ellipsis">{_e(t.name)}<span style="font-size:{fs - 4}px;color:#5a2a3a;font-weight:700">'
            f' · {_e(_length(t))}</span></div><div style="font-size:{fs - 6}px;color:#3a3028;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">{_e((t.title or t.game or "")[:90])}</div></div>')
    pic = f'<div class=fr style="width:{thumb_w}px;padding:4px;flex:none"><i style="{_bg(t, img)}">{_plats(t)}</i></div>'
    chip = _chip(clock(t.at, tz), fs, clark).replace("width:150px", f"width:{chip_w}px")
    inner = chip + (text + pic if flip else pic + text)
    return (f'<div style="display:flex;align-items:center;gap:18px;width:{w}px;height:{h}px;background:{pal[k % len(pal)]};'
            f'padding:8px 16px;border-radius:{4 if clark else 0}px;transform:rotate({tilt}deg);box-shadow:3px 5px 12px #0007;'
            f'color:#2a2116">{inner}</div>')
SPOT_MAX = 6            # small pictures beside a spotlight day picture's big one


def cover(key: str, week: Any, img: Callable[[str], str], heading: str, figure: str = "") -> str:
    """The X Article cover in host ``key``'s look, COVER_W x COVER_H (screenshot with that size).
    ``heading``: "Week in Review", "This Week" ... ; ``figure``: which host picture stands on the right
    (a hosts.KINDS kind; default their happy pose). The people and their numbers are render.cover's
    (cover_people / cover_stats). Called by flavrpromo/article_editor.py (/settings/article/cover)."""
    clark = key == "clark"
    pic = hosts.data_url(key, figure or "happy") or hosts.data_url(key, "chibi_happy")
    if week.recap:
        stats = f"{week.stream_count} streams · {week.hours_live:.0f} hours live"
    else:
        stats = f"{sum(len(d) for d in week.days)} streams this week"
    pal = CLARK_COLOURS if clark else COLETTE_COLOURS
    cards = "".join(
        f'<div class=cc style="background:{pal[k % len(pal)]};{"" if clark else f"transform:rotate({TILT[k % len(TILT)]});"}">'
        f'<i style="{_bg(r["tile"], img)}"></i><b>{_e(r["tile"].name)}</b><span>{_e(cover_stats(r, week.recap))}</span></div>'
        for k, r in enumerate(cover_people(week)))
    fig = (f'<img src="{pic}" style="position:absolute;right:20px;bottom:0;height:{COVER_H - 20}px;max-width:300px;'
           f'object-fit:contain;object-position:bottom">' if pic else "")
    grid_w = COVER_W - 480 - (330 if pic else 60)
    css = (f"body{{width:{COVER_W}px;height:{COVER_H}px}}"
           f".g{{position:absolute;left:470px;top:60px;width:{grid_w}px;height:480px;display:grid;"
           "grid-template-columns:repeat(4,1fr);gap:18px 14px;align-content:center}"
           ".cc{padding:7px;border-radius:" + ("4px" if clark else "10px") + ";box-shadow:3px 5px 12px #0007;color:#2a2116;min-width:0}"
           ".cc i{display:block;aspect-ratio:16/9;background:#0005 center/cover no-repeat;border-radius:" + ("2px" if clark else "6px") + "}"
           ".cc b{display:block;font-size:17px;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
           ".cc span{display:block;font-size:14px;font-weight:700;color:#5a2a3a}")
    if clark:
        left = (f'<div class=serif style="position:absolute;left:60px;top:90px;width:390px">'
                f'<div style="font-size:20px;letter-spacing:3px;color:#d9b88a">FLAVR · FILED BY CLARK</div>'
                f'<div style="font-size:58px;color:#e0782e;line-height:1.05;margin-top:14px">{_e(heading)}</div>'
                f'<div style="font-size:28px;color:#f3e6d3;margin-top:16px">{_e(week.range_text)}</div>'
                f'<div style="display:inline-block;margin-top:22px;background:#f4ead8;color:#2b1d12;padding:10px 16px;'
                f'font-size:22px;border-radius:4px;box-shadow:0 6px 16px #0008">{_e(stats)}</div></div>')
        return _doc("background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3",
                    f"<style>{css}</style>{left}<div class='g serif'>{cards}</div>{fig}")
    left = (f'<div style="position:absolute;left:60px;top:80px;width:390px">'
            f'<img src="{logo_data_url()}" style="height:90px">'
            f'<div style="font-size:50px;font-weight:900;letter-spacing:2px;line-height:1.05;margin-top:16px">{_e(heading.upper())}</div>'
            f'<div style="font-size:26px;color:#f8cf33;font-weight:800;margin-top:12px">{_e(week.range_text)}</div>'
            f'<div class=note style="position:static;display:inline-block;margin-top:20px;transform:rotate(-2deg);font-size:22px">'
            f'{_e(stats)}</div></div>')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff",
                f"<style>{css}</style>{left}<div class=g>{cards}</div>{fig}")


# ── the end-of-stream recap card (owner 2026-11-21) ──────────────────────────────────────
PLATFORM_NAMES = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}


def recap_pose(r: Dict[str, Any]) -> str:
    """The host's mood on a recap: sleepy after a marathon (hosts.LONG_STREAM), pointing at a new
    game, else happy."""
    if float(r.get("length_s") or 0) >= hosts.LONG_STREAM:
        return "sleepy"
    return "pointing" if any("NEW" in (g.get("tag") or "") for g in r.get("played") or []) else "happy"


def recap(key: str, r: Dict[str, Any], chibi_main: bool = False) -> str:
    """The recap picture that replaces the stream picture on an ended go-live card (1600 x 900).
    ``r`` (flavrpromo/bot.py ``_recap_data``): name, title, when ("Sat Nov 21 · 7 PM – 10:20 PM"),
    length ("3 h 20 min"), length_s (seconds), played [{game, tag, length}], platforms [names],
    viewers (peak, 0 = unknown), signoff (their sign-off line, "" = none), vod (True = a VOD link is
    on the card), thumb / avatar (data: URLs or ""), line (what the host says about it).
    Colette pins the stream up as a taped polaroid next to sticky notes; Clark files it as a stream
    report with a clipped photo and a neat table. ``chibi_main``: the chibi stands instead of the pose.
    Called by flavrpromo/bot.py (``post_end``) and /settings previews."""
    pose = recap_pose(r)
    pic = hosts.data_url(key, f"chibi_{pose}" if chibi_main else pose) or hosts.data_url(key, pose) \
        or hosts.data_url(key, f"chibi_{pose}")
    thumb = r.get("thumb") or r.get("avatar") or ""
    shot = f"background-image:url(&quot;{_e(thumb)}&quot;)" if thumb else ""
    played = list(r.get("played") or [])[:4]
    more = len(r.get("played") or []) - len(played)
    plats = " · ".join(PLATFORM_NAMES.get(str(p), str(p).title()) for p in r.get("platforms") or [])
    peak = f"{r['viewers']:,} peak" if int(r.get("viewers") or 0) > 0 else ""
    if key == "clark":
        rows = [("Length", _e(r.get("length"))), ("Aired", _e(r.get("when")))]
        rows += [("Game" if len(played) == 1 else f"Game {i + 1}",
                  f'<b>{_e(g["game"])}</b>{(" · " + _e(g["tag"])) if g.get("tag") else ""} · '
                  f'<span style="white-space:nowrap">{_e(g["length"])}</span>')
                 for i, g in enumerate(played)]
        if more > 0:
            rows.append(("", f"+{more} more on file"))
        if plats or peak:
            rows.append(("Channels", _e(" · ".join(x for x in (plats, peak) if x))))
        rows.append(("VOD", "on file, link below" if r.get("vod") else "pending"))
        table = "".join(f'<tr style="border-bottom:1px solid #d8c3a3"><td style="padding:8px 14px 8px 0;color:#8a5a33;'
                        f'white-space:nowrap;vertical-align:top">{a}</td><td style="text-align:right">{b}</td></tr>'
                        for a, b in rows)
        sign = (f'<div style="margin-top:18px;font-size:24px;font-style:italic;color:#5a3a20">“{_e(r["signoff"])}”</div>'
                if r.get("signoff") else "")
        img = (f'<img src="{pic}" style="position:absolute;left:40px;bottom:0;height:640px;max-width:360px;'
               f'object-fit:contain;object-position:bottom">' if pic else "")
        left = 420 if pic else 60
        inner = (f'<div class=serif style="position:absolute;left:44px;top:30px;font-size:56px;color:#e0782e">Stream Report</div>'
                 f'<div style="position:absolute;left:46px;top:102px;font-size:22px;letter-spacing:2px;color:#d9b88a">'
                 f'FILED BY CLARK · DIVISION CLERK</div>{img}'
                 f'<div class=serif style="position:absolute;left:{left}px;top:160px;width:{1560 - left}px;height:700px;'
                 f'background:#f4ead8;color:#2b1d12;border-radius:6px;box-shadow:0 10px 30px #000a;padding:30px 40px">'
                 f'<div style="display:flex;justify-content:space-between;font-size:20px;letter-spacing:2px;color:#8a5a33;'
                 f'border-bottom:2px solid #c9a77c;padding-bottom:10px"><span>FILE · {_e(str(r.get("name")).upper())}</span>'
                 f'<span>STATUS: CLOSED 🍎</span></div>'
                 f'<div style="display:flex;gap:30px;margin-top:22px">'
                 f'<div style="flex:0 0 470px;position:relative"><div style="background:#fffaf0;padding:10px;box-shadow:0 3px 8px #0004">'
                 f'<i style="display:block;aspect-ratio:16/9;background:#d9c7a8 center/cover no-repeat;{shot}"></i>'
                 f'<div style="margin-top:8px;font-size:21px;line-height:1.3;max-height:56px;overflow:hidden">{_e(r.get("title"))}</div></div>'
                 f'<div style="position:absolute;top:-14px;left:26px;width:18px;height:46px;border:4px solid #9aa3ad;border-radius:9px"></div>'
                 f'<div style="margin-top:22px;font-size:26px;line-height:1.45">{_e(r.get("line"))}</div></div>'
                 f'<div style="flex:1;min-width:0"><div style="font-size:40px;font-weight:bold">{_e(r.get("name"))}</div>'
                 f'<table style="margin-top:12px;font-size:22px;border-collapse:collapse;width:100%">{table}</table>{sign}</div></div>'
                 f'<div style="position:absolute;right:40px;bottom:26px;font-size:21px;color:#8a5a33;font-style:italic">'
                 f'Filed and closed. — C.</div></div>')
        return _doc("background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3", inner)
    # Colette: the stream as a taped polaroid, sticky notes for the numbers, her line in a bubble
    notes = [("LIVE FOR", r.get("length") or "", "")]
    if played:
        notes.append(("PLAYED", " → ".join(g["game"] for g in played) + (f" +{more}" if more > 0 else ""),
                      next((g["tag"] for g in played if g.get("tag")), "")))
    notes.append(("VOD", "link below!" if r.get("vod") else "coming soon", peak))
    stickies = "".join(
        f'<div class=note style="position:static;width:300px;transform:rotate({NOTE_TILT[i]});background:{NOTE_COLOURS[i]}">'
        f'📌 {_e(a)}<br><b style="font-size:27px;display:block;max-height:108px;overflow:hidden">{_e(b)}</b>'
        + (f'<span style="font-size:19px">{_e(c)}</span>' if c else "") + "</div>"
        for i, (a, b, c) in enumerate(notes))
    img = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:0;height:640px;max-width:380px;'
           f'object-fit:contain;object-position:bottom">' if pic else "")
    sign = (f'<div style="position:absolute;left:60px;top:800px;font-size:26px;color:#f8cf33;font-weight:700;'
            f'font-style:italic;max-width:1050px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'“{_e(r["signoff"])}”</div>' if r.get("signoff") else "")
    inner = (f'<img src="{logo_data_url()}" style="position:absolute;left:40px;top:30px;height:66px">'
             f'<div style="position:absolute;left:270px;top:32px;font-size:50px;font-weight:900;letter-spacing:3px">'
             f'THAT\'S A WRAP!</div>'
             f'<div style="position:absolute;left:272px;top:96px;font-size:22px;color:#f8cf33;font-weight:700">'
             f'{_e(r.get("name"))} · {_e(r.get("when"))}{(" · " + _e(plats)) if plats else ""}</div>'
             f'<div style="position:absolute;left:70px;top:170px;width:640px;background:#fff;padding:14px 14px 10px;'
             f'transform:rotate(-2deg);box-shadow:4px 8px 18px #0008;color:#1a1a1a">'
             f'<div style="position:absolute;top:-16px;left:50%;width:130px;height:32px;margin-left:-65px;transform:rotate(-3deg);'
             f'background:{TAPE[0]}"></div>'
             f'<i style="display:block;aspect-ratio:16/9;background:#2a1026 center/cover no-repeat;{shot}"></i>'
             f'<b style="display:block;margin-top:8px;font-size:30px;font-weight:900">{_e(r.get("name"))}</b>'
             f'<span style="display:block;color:#c21c80;font-weight:700;font-size:21px;white-space:nowrap;overflow:hidden;'
             f'text-overflow:ellipsis">{_e(r.get("title"))}</span></div>'
             f'<div class=bub style="left:770px;top:200px;width:{430 if pic else 780}px;border:5px solid #f72ca2;font-size:33px;'
             f'padding:32px 36px">'
             f'{_e(r.get("line"))}</div>'
             f'<div style="position:absolute;left:70px;top:610px;width:{1140 if pic else 1460}px;display:flex;gap:26px">{stickies}</div>'
             f'{sign}{img}')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff", inner)


# ── the weekly board in the host's look (owner 2026-11-21) ───────────────────────────────
# The plain board (render.page) with a host's skin on top: the same columns, tiles and sizes, so
# everything that fits on the board still fits. Colette: her purple wall, FlaVR colours, white
# polaroid frames, tape on each day's heading. Clark: his brown desk, each day a cream report page,
# serif type, photos with a white border. Their chibi head and name sit at the right of the header.
BOARD_CSS = {
    "colette": (
        "body{background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a)}"
        "h1{font-weight:900;letter-spacing:3px}.range{color:#f8cf33;font-weight:700}.stats{color:#fff;font-weight:700}"
        ".day{background:#ffffff0d;border:2px dashed #ffffff26;border-radius:16px;position:relative;padding-top:20px}"
        ".dh{position:relative}.dh:before{content:'';position:absolute;left:-4px;top:-14px;width:70px;height:18px;"
        "background:var(--tape);transform:rotate(-4deg);opacity:.85}"
        ".d0{--tape:#f8cf33}.d1{--tape:#b7ef33}.d2{--tape:#2ae0d4}.d3{--tape:#f72ca2}"
        ".dh b{font-weight:900}.day.today{border:3px solid #f72ca2;background:#f72ca218;box-shadow:0 0 30px #f72ca255}"
        ".dh em{background:#f72ca2;color:#fff}"
        ".tile{background:#fff;border:0;border-radius:3px;padding:6px 6px 0;box-shadow:3px 6px 12px #0009;color:#1a1a1a}"
        ".day .tile:nth-child(odd){transform:rotate(-1.2deg)}.day .tile:nth-child(even){transform:rotate(1deg)}"
        ".tile .thumb{border-radius:2px}.who b{color:#1a1a1a;font-weight:900}.who i{color:#555}.who u{color:#c21c80;font-weight:700}"
        ".row{background:#fff;border:0;border-radius:4px;color:#1a1a1a;box-shadow:2px 4px 8px #0008}"
        ".row b{color:#1a1a1a;font-weight:900}.row i{color:#555}.row .t{color:#c21c80}.row .t.live{color:#e5312f}"
        ".thumb{background-color:#2a1026}.thumb .noart{color:#ffffff99}"
        ".more{color:#f8cf33;font-weight:700}.empty{color:#f8cf33aa;font-weight:700}"
        "footer{color:#f8cf33cc;font-weight:700}"
        ".host{display:flex;align-items:flex-end;gap:10px;padding-bottom:2px;margin-left:18px}"
        ".host img{height:78px;margin-bottom:-12px}.host span{font-size:15px;color:#f8cf33;font-weight:700;padding-bottom:6px;"
        "white-space:nowrap}"),
    "clark": (
        "body{background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3}"
        "body,h1,.who,.row{font-family:'DejaVu Serif',serif}"
        "h1{color:#e0782e;font-weight:normal;letter-spacing:1px}.range{color:#d9b88a;letter-spacing:1px}.stats{color:#f3e6d3}"
        ".day{background:#f4ead8;border:0;border-radius:4px;box-shadow:0 8px 20px #000a;color:#2b1d12}"
        ".dh span{color:#8a5a33}.day .dh b,.d0 .dh b,.d1 .dh b,.d2 .dh b,.d3 .dh b{color:#2b1d12}"
        ".dh{border-bottom:2px solid #c9a77c;padding-bottom:4px}"
        ".day.today{border:0;outline:3px solid #e0782e;background:#fbf3e3;box-shadow:0 0 30px #e0782e55}"
        ".day.past{opacity:1;background:#e9dcc4}.dh em{background:#e0782e;color:#fff}"
        ".tile{background:#fffaf0;border:0;border-radius:2px;padding:6px 6px 0;box-shadow:0 3px 8px #0004}"
        ".who b{color:#2b1d12}.who i{color:#6b4a2e}.who u{color:#8a5a33}"
        ".av{border-color:#c9a77c;background:#e0d0b4;color:#5a3a20}"
        ".row{background:#fffaf0;border:1px solid #d8c3a3;color:#2b1d12}.row b{color:#2b1d12}.row i{color:#6b4a2e}"
        ".row .t{color:#8a5a33}.row .t.live{color:#c0392b}"
        ".thumb{background-color:#d9c7a8}.thumb .noart{color:#8a5a33}"
        ".more{color:#8a5a33}.empty{color:#8a5a33;font-style:italic}"
        "footer{color:#d9b88a;font-style:italic}"
        ".host{display:flex;align-items:flex-end;gap:10px;padding-bottom:2px;margin-left:18px}"
        ".host img{height:78px;margin-bottom:-12px}.host span{font-size:15px;color:#d9b88a;letter-spacing:1px;padding-bottom:6px;"
        "white-space:nowrap}"),
}


def board(key: str, week: Any, img: Callable[[str], str], logo: str = "") -> str:
    """The weekly board (or a review's board) in host ``key``'s look: render.page with BOARD_CSS and
    the host's chibi head + name in the header. Called by flavrpromo/calendar_post.py (``png`` with a
    host, kv host_board on) and the settings page preview."""
    from .render import page
    pic = hosts.data_url(key, "chibi_head") or hosts.data_url(key, "head")
    who = "pinned up by Colette ☕" if key == "colette" else "FILED BY CLARK 🍎"
    head = f'<div class=host>{f"<img src={chr(34)}{pic}{chr(34)}>" if pic else ""}<span>{_e(who)}</span></div>'
    return page(week, img, logo=logo, extra_css=BOARD_CSS.get(key, ""), extra_head=head)
