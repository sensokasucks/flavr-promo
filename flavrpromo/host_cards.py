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

Who calls it: flavrpromo/host_picker.py (the review posts and the picker page's previews) and /host
preview (flavrpromo/bot.py).
"""

from __future__ import annotations

import html
from datetime import timedelta
from typing import Any, Callable, Dict, List

from . import hosts
from .render import DAY_MAX, _plats, clock, hm, logo_data_url, tile_layout

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


def opener(key: str, heading: str, range_text: str, line: str, notes: List[Dict[str, str]],
           comments: List[str], pose: str, chibi_main: bool = False) -> str:
    """The opener card. ``notes``: hosts.notes() rows; ``comments``: the picked comment for each.
    ``chibi_main``: the big figure is the chibi and the regular pose peeks (picker page "opener
    picture"; Sen 2026-11-21: chibis mixed in with the regular pictures)."""
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
    rows = list(zip(notes, comments + [""] * len(notes)))
    if key == "clark":
        img = f'<img src="{pic}" style="position:absolute;left:60px;top:170px;height:690px;max-width:400px;object-fit:contain;object-position:bottom">' if pic else ""
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
                 f'border-bottom:2px solid #c9a77c;padding-bottom:10px"><span>REPORT · {_e(range_text.upper())}</span>'
                 f'<span>STATUS: IN ORDER 🍎</span></div>'
                 f'<div style="font-size:30px;line-height:1.45;margin-top:22px">{_e(line)}</div>'
                 f'<table style="margin-top:26px;font-size:24px;border-collapse:collapse;width:100%">{table}</table>'
                 f'<div style="position:absolute;right:40px;bottom:30px;font-size:21px;color:#8a5a33;font-style:italic">'
                 f'The full board follows. — C.</div></div>')
        return _doc("background:linear-gradient(135deg,#1c130d,#3a2416 70%,#4a2a14);color:#f3e6d3", inner)
    # Colette
    img = f'<img src="{pic}" style="position:absolute;left:40px;top:160px;height:700px;max-width:420px;object-fit:contain;object-position:bottom">' if pic else ""
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
             f'<div class=bub style="left:{left}px;top:170px;width:{width}px;border:5px solid #f72ca2">{_e(line)}</div>'
             f'{stickies}<div style="position:absolute;left:{left + 20}px;top:790px;font-size:24px;color:#ddd">'
             f'Full board in the next picture ↓ &nbsp; My notes at the end!</div>')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff", inner)


def desk(key: str, highlight: str, nudge: str, signoff: str, kind: str = "desk") -> str:
    """The closing desk card."""
    # ``kind``: "desk" or "chibi_desk" (picked on the picker page, flavrpromo/host_picker.py)
    pic = hosts.data_url(key, kind) or hosts.data_url(key, "desk")
    if key == "clark":
        left = 700 if pic else 60
        img = f'<img src="{pic}" style="position:absolute;left:0;top:0;width:700px;height:900px;object-fit:cover">' if pic else ""
        text = "<br><br>".join(_e(x) for x in (highlight, nudge) if x)
        inner = (f'{img}<div style="position:absolute;left:{left}px;top:0;right:0;height:900px;background:linear-gradient(135deg,#2a1c12,#3b2416)"></div>'
                 f'<div class=serif style="position:absolute;left:{left + 70}px;top:60px;font-size:30px;color:#e0782e">Closing notes</div>'
                 f'<div class=serif style="position:absolute;left:{left + 70}px;top:120px;right:60px;background:#f4ead8;color:#2b1d12;'
                 f'padding:34px 40px;font-size:28px;line-height:1.5;box-shadow:0 10px 30px #000a;border-radius:4px">{text}</div>'
                 f'<div class=serif style="position:absolute;right:80px;bottom:90px;font-size:34px;color:#e0b07a;font-style:italic">'
                 f'{_e(signoff)}</div>')
        return _doc("background:#1c130d", inner)
    left = 960 if pic else 60
    img = (f'<img src="{pic}" style="position:absolute;left:0;top:0;width:960px;height:900px;object-fit:cover">'
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
               "spotlight": "Spotlight (the longest stream big, the rest beside it)"}


def day(key: str, week: Any, i: int, img: Callable[[str], str], line: str = "", chibi_kind: str = "",
        layout: str = "wall") -> str:
    """Day ``i`` of ``week`` (flavrpromo/calendar.py Week) in host ``key``'s look. ``img``: a picture
    address for a thumbnail / avatar URL (render.ImageCache.data_url). ``line``: what the host says
    about the day ("" = no bubble). ``chibi_kind``: which picture stands in the corner (default
    their happy chibi). ``layout``: one of DAY_LAYOUTS (unknown = wall).
    Called by flavrpromo/article_editor.py (/settings/article/day)."""
    if layout in ("timeline", "spotlight"):
        return _day_alt(key, week, i, img, line, chibi_kind, layout)
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
                f'object-fit:contain;object-position:bottom">' if pic else "")
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
            f'object-fit:contain;object-position:bottom">' if pic else "")
    say = (f'<div class=bub style="right:30px;bottom:{420 if pic else 60}px;width:{DAY_HOST_W - 10}px;font-size:22px;'
           f'border:5px solid #f72ca2">{_e(line)}</div>' if line else "")
    inner = (f'<style>{css}</style><img src="{logo_data_url()}" style="position:absolute;left:40px;top:30px;height:66px">'
             f'<div style="position:absolute;left:270px;top:32px;font-size:52px;font-weight:900;letter-spacing:3px">'
             f'{_e(f"{date:%A} · {date:%b} {date.day}".upper())}</div>'
             f'<div style="position:absolute;left:272px;top:98px;font-size:22px;color:#f8cf33;font-weight:700">'
             f'{_e(n_word)} · pinned up by Colette ☕</div><div class=wall>{shots}</div>{side}{say}')
    return _doc("background:linear-gradient(135deg,#1b1018,#3d1233 60%,#2a0f2a);color:#fff", inner)


# ── the other two day layouts: the same host skins (heading, frames, chibi + line) ─────────
def _skin(key: str, date: Any, n_word: str, pic: str, line: str) -> Dict[str, str]:
    """A host's look for a day picture: page background, heading, the chibi + line on the right and
    the CSS for frames (.fr), names (.nm), times (.tm) and titles (.tt)."""
    plat = (".plat{position:absolute;top:6px;right:6px;width:24px;height:24px;border-radius:5px;font:800 13px sans-serif;"
            "display:inline-flex;align-items:center;justify-content:center}.fr i .plat+.plat{right:34px}"
            ".fr i{display:block;aspect-ratio:16/9;background-repeat:no-repeat;background-size:cover;background-position:center;"
            "position:relative}")
    if key == "clark":
        side = (f'<img src="{pic}" style="position:absolute;right:30px;bottom:40px;width:{DAY_HOST_W - 20}px;height:380px;'
                f'object-fit:contain;object-position:bottom">' if pic else "")
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
            f'object-fit:contain;object-position:bottom">' if pic else "")
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


def _day_alt(key: str, week: Any, i: int, img: Callable[[str], str], line: str, chibi_kind: str, layout: str) -> str:
    """The timeline and spotlight layouts of ``day``.
    timeline   one row per stream in time order: a time chip, the thumbnail, the name, the stream
               title and its length (Colette: sticky-note strips in turn; Clark: a ruled ledger page).
               At most TIMELINE_MAX rows, then "+N more".
    spotlight  the day's longest stream (else the first) big on the left with a "top pick" / "featured
               entry" stamp, the others smaller in two columns beside it (at most SPOT_MAX)."""
    date = week.start + timedelta(days=i)
    tiles = sorted(week.days[i], key=lambda t: t.at)
    n_word = f"{len(tiles)} stream{'' if len(tiles) == 1 else 's'}"
    pic = hosts.data_url(key, chibi_kind or "chibi_happy") or hosts.data_url(key, "chibi_happy")
    sk = _skin(key, date, n_word, pic, line)
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
SPOT_MAX = 6            # small pictures beside a spotlight day picture's big one
