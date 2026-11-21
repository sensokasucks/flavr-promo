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
Who calls it: flavrpromo/host_picker.py (the review posts and the picker page's previews) and /host
preview (flavrpromo/bot.py).
"""

from __future__ import annotations

import html
from typing import Dict, List

from . import hosts
from .render import logo_data_url

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
           comments: List[str], pose: str) -> str:
    """The opener card. ``notes``: hosts.notes() rows; ``comments``: the picked comment for each."""
    pic = hosts.data_url(key, pose)
    # the chibi in the same mood peeks over the top-right edge of the bubble / report: drawn before
    # it, so the card covers the chibi's lower half (no chibi uploaded = nothing)
    chibi = hosts.data_url(key, f"chibi_{pose}")
    # (cut off just under the card's top edge at y 170, so a short bubble never shows the chibi's feet)
    peek = (f'<div style="position:absolute;right:90px;top:24px;width:260px;height:156px;overflow:hidden">'
            f'<img src="{chibi}" style="display:block;margin:0 auto;height:290px;max-width:260px;object-fit:contain">'
            f'</div>') if chibi else ""
    left = 470 if pic else 60
    width = 1540 - left
    rows = list(zip(notes, comments + [""] * len(notes)))
    if key == "clark":
        img = f'<img src="{pic}" style="position:absolute;left:60px;top:170px;height:690px;max-width:400px;object-fit:contain">' if pic else ""
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
    img = f'<img src="{pic}" style="position:absolute;left:40px;top:160px;height:700px;max-width:420px;object-fit:contain">' if pic else ""
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


def desk(key: str, highlight: str, nudge: str, signoff: str) -> str:
    """The closing desk card."""
    pic = hosts.data_url(key, "desk")
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
