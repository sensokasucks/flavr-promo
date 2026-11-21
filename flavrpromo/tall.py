"""
Tall pictures built from chunks (owner 2026-11-21: "break the image down into chunks, then let me use
menus to assemble each chunk, and have the tall image built from those saved chunks").

An X Article shows a picture whole up to 1600 x 2133 (3:4; taller ones are cropped from the middle,
the owner's test 2026-11-21), so a tall picture is a stack of full-width strips, ``chunks``, that
add up to at most MAX_H pixels. This file is the model and the drawing; the builder page (menus,
saving) is flavrpromo/tall_page.py, and the article editor adds a tall picture as a section
(flavrpromo/article_editor.py).

A chunk is a dict: {"id", "type", "size" (0 small, 1 medium, 2 large), "cut", "slope", ...fields of its type}.
``cut`` is the shape of the chunk's bottom edge: "" straight, "down" slanting down to the right, "up"
slanting down to the left (owner 2026-11-21: diagonal cuts "add a more fun feel"); ``slope`` 0 / 1 / 2 is
how steep (SLOPES px). A chunk with a cut, and the one under it, get their own background colour (BANDS)
and a stripe is drawn along the seam; the stack's height does not change (the cut eats into the chunk's
own bottom, so its content gets a little less room).
  header   a title and a line under it (blank = the article's heading and date range)     title, sub
  host     a host picture on one side, a speech bubble with their line on the other      host, kind, var, side, line
  stream   one stream: thumbnail, name, game, time, and a line                              ref ("d<day>:<n>"), line
  stats    the review's highlight numbers side by side (hosts.notes of the draft's facts)
  grid     one day's thumbnails (up to 6) under the day's name                              day (0-6)
  hero     a big opening: a small word on top ("Meet"), the host's name huge, their job, a tagline, and
           the host picture large on an angled colour panel                                  top, title, sub, tag, host, kind, var
  chat     speech-bubble rows, two hosts talking (alternating, each with their head as the avatar)
                                                                                              lines (one per row), host, other
  quote    one big line of text                                                              text
  footer   a closing strip: the host's small picture and a sign-off line                    host, kind, var, line
``host`` empty = the draft's host; ``kind`` is a hosts.POOLED picture kind (happy, chibi_happy ...,
so one picture can mix regular and chibi pictures for more emotion); ``var`` pins one picture of
that kind's pool ("" = the draft's automatic pick, hosts.look). Chunks can be saved by name
(kv "tall_chunks" {name: chunk}) and whole stacks too (kv "tall_templates" {name: [chunk]}).

Who calls it: flavrpromo/tall_page.py (builder, preview) and flavrpromo/article_editor.py
(the picture inside the article). Pure functions: no network, no Discord.
"""

from __future__ import annotations

import copy
import html
from typing import Any, Dict, List, Tuple

from . import hosts
from .render import clock, hm, logo_data_url

WIDTH = 1600
MAX_H = 2133                         # px: the tallest picture X shows whole (3:4 at this width)
# type → (label, heights small / medium / large in px)
TYPES: Dict[str, Any] = {
    "header": ("Header", (180, 240, 300)),
    "host": ("Host moment", (380, 520, 660)),
    "stream": ("One stream", (200, 250, 310)),
    "stats": ("Highlight numbers", (150, 200, 260)),
    "grid": ("A day's pictures", (400, 540, 700)),
    "quote": ("Big line", (170, 220, 300)),
    "hero": ("Hero opening", (420, 520, 640)),
    "chat": ("Chat bubbles", (300, 420, 560)),
    "footer": ("Sign-off strip", (260, 340, 440)),
}
SIDES = {"left": "Host on the left", "right": "Host on the right"}
CUTS = {"": "Straight edge", "down": "Slants down to the right ↘", "up": "Slants down to the left ↙",
        "v": "V shape ⌄ (dips in the middle)", "peak": "Peak ⌃ (rises in the middle)"}
V_AT = 53                            # % of the width where a V / peak turns
SLOPES = (60, 110, 170)              # px the slanted edge drops over the 1600 px width: gentle / normal / steep
BANDS = {                            # background colours of chunks next to a cut (taken in turn)
    "colette": ("#2a0f2a", "#521b4c", "#1b1018", "#3d1233"),
    "clark": ("#2a1b10", "#563520", "#33220f", "#6a4528"),
}
THEMES = {
    "colette": {"bg": "linear-gradient(160deg,#1b1018,#3d1233 55%,#2a0f2a)", "fg": "#fff", "accent": "#f72ca2",
                "gold": "#f8cf33", "paper": "#fff", "ink": "#1a1a1a", "font": "'DejaVu Sans',sans-serif"},
    "clark": {"bg": "linear-gradient(160deg,#1c130d,#3a2416 65%,#4a2a14)", "fg": "#f3e6d3", "accent": "#e0782e",
              "gold": "#d9b88a", "paper": "#f4ead8", "ink": "#2b1d12", "font": "'DejaVu Serif',serif"},
}


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def height(chunk: Dict[str, Any]) -> int:
    """A chunk's height in px from its type and size."""
    sizes = TYPES.get(chunk.get("type"), TYPES["quote"])[1]
    return sizes[max(0, min(2, int(chunk.get("size", 1) or 0)))]


def total(chunks: List[Dict[str, Any]]) -> int:
    return sum(height(c) for c in chunks)


def new_chunk(ctype: str, existing: List[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    """A fresh chunk of type ``ctype`` with an id not used in ``existing`` and its defaults."""
    n = 1 + max([int(c["id"][1:]) for c in existing if str(c.get("id", "")).startswith("c") and c["id"][1:].isdigit()] or [0])
    base: Dict[str, Any] = {"id": f"c{n}", "type": ctype if ctype in TYPES else "quote", "size": 1, "cut": "", "slope": 1}
    defaults = {"header": {"title": "", "sub": ""},
                "host": {"host": "", "kind": "happy", "var": "", "side": "left", "line": ""},
                "stream": {"ref": "", "line": ""}, "stats": {}, "grid": {"day": 0}, "quote": {"text": ""},
                "footer": {"host": "", "kind": "chibi_happy", "var": "", "line": ""},
                "hero": {"top": "Meet", "title": "", "sub": "", "tag": "", "host": "", "kind": "happy", "var": ""},
                "chat": {"lines": "", "host": "", "other": ""}}
    base.update(defaults.get(base["type"], {}))
    base.update(fields)
    return base


def renumber(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copies of ``chunks`` with ids c1, c2, ... (a template or saved stack put into a draft)."""
    out = copy.deepcopy(chunks)
    for i, c in enumerate(out, 1):
        c["id"] = f"c{i}"
    return out


# Built-in stacks to start from (each is ≤ MAX_H); the owner's own are saved in kv "tall_templates".
BUILTIN: Dict[str, List[Dict[str, Any]]] = {
    "Week overview": [
        {"id": "c1", "type": "header", "size": 1, "title": "", "sub": ""},
        {"id": "c2", "type": "host", "size": 1, "host": "", "kind": "happy", "var": "", "side": "left", "line": ""},
        {"id": "c3", "type": "stats", "size": 1},
        {"id": "c4", "type": "footer", "size": 0, "host": "", "kind": "chibi_happy", "var": "", "line": ""},
    ],
    "Week overview (diagonal)": [
        {"id": "c1", "type": "header", "size": 1, "cut": "down", "title": "", "sub": ""},
        {"id": "c2", "type": "host", "size": 1, "cut": "up", "host": "", "kind": "happy", "var": "", "side": "left", "line": ""},
        {"id": "c3", "type": "stats", "size": 1, "cut": "down"},
        {"id": "c4", "type": "footer", "size": 0, "host": "", "kind": "chibi_happy", "var": "", "line": ""},
    ],
    "Hero and chat (diagonal)": [
        {"id": "c1", "type": "hero", "size": 1, "cut": "v", "top": "Meet", "title": "", "sub": "", "tag": "Your week, pinned up.",
         "host": "", "kind": "happy", "var": ""},
        {"id": "c2", "type": "chat", "size": 1, "cut": "up", "lines": "", "host": "", "other": ""},
        {"id": "c3", "type": "stats", "size": 1, "cut": "peak"},
        {"id": "c4", "type": "footer", "size": 0, "host": "", "kind": "chibi_happy", "var": "", "line": ""},
    ],
    "Day in detail": [
        {"id": "c1", "type": "header", "size": 0, "title": "", "sub": ""},
        {"id": "c2", "type": "grid", "size": 1, "day": 0},
        {"id": "c3", "type": "host", "size": 0, "host": "", "kind": "chibi_pointing", "var": "", "side": "right", "line": ""},
        {"id": "c4", "type": "quote", "size": 0, "text": ""},
    ],
}


def _pic(ctx: Dict[str, Any], key: str, kind: str, var: str) -> str:
    """The data: URL of host ``key``'s picture of ``kind`` (``var`` pins one picture of its pool, else the
    draft's automatic pick), "" when none."""
    seed, pins = ctx.get("seed"), dict(ctx.get("pins") or {})
    if var:
        pins[kind] = var
    with hosts.look(seed, pins):
        return hosts.data_url(key, kind) or ""


def _host_of(c: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return c.get("host") if c.get("host") in hosts.HOSTS else ctx["host"]


def _bubble(text: str, th: Dict[str, str], accent: str, extra: str = "") -> str:
    if not text:
        return ""
    return (f'<div style="background:{th["paper"]};color:{th["ink"]};border:5px solid {accent};border-radius:30px;'
            f'padding:26px 34px;font-size:32px;line-height:1.32;font-weight:700;box-shadow:0 8px 26px #0007;{extra}">'
            f'{_e(text)}</div>')


def _tile_of(ref: str, week: Any) -> Tuple[int, Any]:
    """(day index, Tile) for a "d<day>:<n>" reference, or (0, None) when it points at nothing now."""
    try:
        d, _, n = str(ref).lstrip("d").partition(":")
        return int(d), week.days[int(d)][int(n)]
    except (ValueError, IndexError, AttributeError):
        return 0, None


def tile_choices(week: Any) -> List[Dict[str, str]]:
    """Every stream of the week as {ref, label} for the "One stream" menu."""
    out = []
    for d, tiles in enumerate(getattr(week, "days", [])):
        for n, t in enumerate(tiles):
            out.append({"ref": f"d{d}:{n}", "label": f"{week.day_name(d)} · {t.name} · {t.game or t.title or 'stream'}"})
    return out


def cut_depth(chunks: List[Dict[str, Any]], i: int) -> int:
    """How many px the bottom edge of chunk ``i`` drops (0 = straight or the last chunk; at most 40% of its height)."""
    c = chunks[i]
    if i == len(chunks) - 1 or c.get("cut") not in ("down", "up", "v", "peak"):
        return 0
    try:
        d = SLOPES[max(0, min(2, int(c.get("slope", 1))))]
    except (TypeError, ValueError):
        d = SLOPES[1]
    return max(0, min(d, int(height(c) * 0.4)))          # the content keeps at least 60% of the chunk


def _draw(c: Dict[str, Any], ctx: Dict[str, Any], h: int) -> str:
    """One chunk's content in a box ``h`` px tall (its height minus what a cut takes off the bottom)."""
    th, week, img = ctx["theme"], ctx["week"], ctx["img"]
    kind = c.get("type")
    box = f'position:relative;height:{h}px;overflow:hidden;padding:0 70px;'
    if kind == "header":
        title = c.get("title") or ctx.get("heading") or ""
        sub = c.get("sub") or ctx.get("range") or ""
        logo = f'<img src="{logo_data_url()}" style="height:{max(70, h - 90)}px;margin-right:34px">' if ctx["host"] == "colette" else ""
        return (f'<div style="{box}display:flex;align-items:center">{logo}<div><div style="font-size:{min(78, h // 3)}px;'
                f'font-weight:900;letter-spacing:3px;text-transform:uppercase">{_e(title)}</div>'
                f'<div style="font-size:30px;color:{th["gold"]};font-weight:700;margin-top:6px">{_e(sub)}</div></div></div>')
    if kind in ("host", "footer"):
        key = _host_of(c, ctx)
        pic = _pic(ctx, key, c.get("kind") or "happy", c.get("var") or "")
        acc = THEMES.get(key, th)["accent"]
        right = c.get("side") == "right" and kind == "host"
        img_h = h - 30
        figure = (f'<img src="{pic}" style="height:{img_h}px;width:{int(img_h * 0.8)}px;object-fit:contain;'
                  f'object-position:bottom;align-self:flex-end">' if pic else "")
        who = f'<div style="margin-top:12px;font-size:24px;color:{th["gold"]};font-weight:700">— {_e(hosts.HOSTS[key]["name"])}</div>'
        say = (f'<div style="flex:1">{_bubble(c.get("line") or "", th, acc)}{who if c.get("line") else ""}</div>')
        parts = [say, figure] if right else [figure, say]
        return (f'<div style="{box}display:flex;gap:40px;align-items:center;'
                f'{"border-top:6px solid " + acc + ";" if kind == "footer" else ""}">{"".join(parts)}</div>')
    if kind == "stream":
        day_i, t = _tile_of(c.get("ref") or "", week)
        if t is None:
            return (f'<div style="{box}display:flex;align-items:center;font-size:30px;color:{th["gold"]}">'
                    f'Pick a stream from the menu.</div>')
        src = img(t.thumb) or img(t.avatar)
        bg = f'background-image:url(&quot;{_e(src)}&quot;);' if src else ""
        when = clock(t.at, week.tz) + (f" · {hm(t.length)}" if t.kind == "past" and t.end else
                                       " · LIVE" if t.kind == "live" else "")
        th_w = int((h - 40) * 16 / 9)
        f = min(1.0, h / 230)                     # a stream chunk with a deep cut has less room: smaller type
        place = " · ".join(x for x in (week.day_name(day_i), when, t.game) if x)
        return (f'<div style="{box}display:flex;gap:34px;align-items:center">'
                f'<div style="width:{th_w}px;height:{h - 40}px;flex:none;border-radius:8px;background:#2a1026 center/cover;{bg}'
                f'box-shadow:0 6px 18px #0009"></div><div style="flex:1;min-width:0"><div style="font-size:{int(44 * f)}px;'
                f'font-weight:900">{_e(t.name)}</div><div style="font-size:{int(28 * f)}px;color:{th["gold"]};font-weight:700;'
                f'margin:2px 0 {int(8 * f)}px">{_e(place)}</div>'
                f'<div style="font-size:{int(24 * f)}px;opacity:.85;font-style:italic;white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis">{_e(t.title)}</div>'
                + (f'<div style="margin-top:{int(12 * f)}px;font-size:{int(26 * f)}px;font-weight:700;color:{th["accent"]}">'
                   f'“{_e(c["line"])}”</div>' if c.get("line") else "") + '</div></div>')
    if kind == "stats":
        rows = list(ctx.get("notes") or [])[:4]
        if not rows:
            f = ctx.get("facts") or {}
            rows = [{"label": "STREAMS", "value": str(f.get("streams", 0))}, {"label": "HOURS", "value": str(f.get("hours", 0))}]
        cells = "".join(
            f'<div style="flex:1;background:{th["paper"]};color:{th["ink"]};border-radius:14px;padding:18px 20px;'
            f'box-shadow:0 6px 16px #0008;border-top:8px solid {th["accent"]}"><div style="font-size:20px;letter-spacing:2px;'
            f'font-weight:700;color:{th["accent"]}">{_e(r["label"])}</div><div style="font-size:{34 if h > 170 else 28}px;'
            f'font-weight:900;margin-top:6px">{_e(r["value"])}</div></div>' for r in rows)
        return f'<div style="{box}display:flex;gap:26px;align-items:center">{cells}</div>'
    if kind == "grid":
        try:
            d = max(0, min(len(week.days) - 1, int(c.get("day") or 0)))
        except ValueError:
            d = 0
        tiles = list(week.days[d])[:6] if getattr(week, "days", None) else []
        cols = 3 if len(tiles) > 2 else max(1, len(tiles))
        cw = (WIDTH - 140 - 24 * (cols - 1)) // cols
        cells = ""
        for t in tiles:
            src = img(t.thumb) or img(t.avatar)
            bg = f'background-image:url(&quot;{_e(src)}&quot;);' if src else ""
            cells += (f'<div style="width:{cw}px;background:{th["paper"]};color:{th["ink"]};padding:8px 8px 6px;border-radius:4px;'
                      f'box-shadow:0 5px 14px #0009"><div style="aspect-ratio:16/9;background:#2a1026 center/cover;{bg}"></div>'
                      f'<div style="font-size:22px;font-weight:800;margin-top:6px;white-space:nowrap;overflow:hidden;'
                      f'text-overflow:ellipsis">{_e(t.name)} <span style="font-weight:400">· {_e(t.game or "")}</span></div></div>')
        head = week.day_name(d) if getattr(week, "days", None) else ""
        n = len(list(week.days[d])) if getattr(week, "days", None) else 0
        body = cells or f'<div style="font-size:30px;color:{th["gold"]}">Nothing on this day.</div>'
        return (f'<div style="{box}padding-top:18px"><div style="font-size:34px;font-weight:900;color:{th["gold"]};margin-bottom:14px">'
                f'{_e(head)} · {n} stream{"" if n == 1 else "s"}</div><div style="display:flex;flex-wrap:wrap;gap:20px 24px">'
                f'{body}</div></div>')
    if kind == "hero":
        key = _host_of(c, ctx)
        pic = _pic(ctx, key, c.get("kind") or "happy", c.get("var") or "")
        acc = THEMES.get(key, th)["accent"]
        title = c.get("title") or hosts.HOSTS[key]["name"].split()[0]
        sub = c.get("sub") or hosts.HOSTS[key]["role"]
        tag = c.get("tag") or ctx.get("range") or ""
        big = min(210, int(h * 0.42), int(WIDTH * 0.47 / (0.8 * max(4, len(title)))))      # a long name must stay off the panel
        panel = (f'<div style="position:absolute;right:0;top:0;width:{int(WIDTH * 0.52)}px;height:100%;background:{acc};'
                 f'clip-path:polygon(24% 0,100% 0,100% 100%,0 100%)"></div>')
        figure = (f'<img src="{pic}" style="position:absolute;right:50px;bottom:0;height:{int(h * 0.98)}px;max-width:{int(WIDTH * 0.46)}px;'
                  f'object-fit:contain;object-position:bottom">' if pic else "")
        return (f'<div style="position:relative;height:{h}px;overflow:hidden">{panel}{figure}'
                f'<div style="position:absolute;left:70px;top:0;height:100%;width:{int(WIDTH * 0.52)}px;display:flex;flex-direction:column;'
                f'justify-content:center"><div style="font-size:{int(big * 0.42)}px;font-weight:800">{_e(c.get("top"))}</div>'
                f'<div style="font-size:{big}px;line-height:1;font-weight:900;color:{acc};letter-spacing:-2px;text-transform:uppercase;'
                f'text-shadow:0 4px 0 #0005">{_e(title)}</div><div style="font-size:{int(big * 0.3)}px;font-weight:800;margin-top:6px">'
                f'{_e(sub)}</div><div style="font-size:{int(big * 0.2)}px;color:{th["gold"]};font-weight:700;margin-top:12px">'
                f'{_e(tag)}</div></div></div>')
    if kind == "chat":
        a = _host_of(c, ctx)
        b = c.get("other") if c.get("other") in hosts.HOSTS and c.get("other") != a else next((k for k in hosts.HOSTS if k != a), a)
        rows = [x.strip() for x in str(c.get("lines") or "").splitlines() if x.strip()][:5] or ["Type the chat lines in the builder."]
        row_h = max(70, (h - 40) // len(rows))
        out = ""
        for n, text in enumerate(rows):
            who = a if n % 2 == 0 else b
            avatar = _pic(ctx, who, "head", "") or _pic(ctx, who, "chibi_head", "")
            acc = THEMES.get(who, th)["accent"]
            mine = n % 2 == 0
            av = (f'<div style="width:{min(96, row_h - 10)}px;height:{min(96, row_h - 10)}px;border-radius:50%;flex:none;'
                  f'background:{acc}{f' center/cover url({avatar})' if avatar else ''};border:4px solid #fff;box-shadow:0 4px 10px #0007"></div>')
            bub = (f'<div style="max-width:{int(WIDTH * 0.66)}px;background:{acc if mine else th["paper"]};'
                   f'color:{"#fff" if mine else th["ink"]};border-radius:30px;padding:{max(10, row_h // 6)}px 30px;'
                   f'font-size:{min(34, max(22, row_h // 3))}px;font-weight:700;line-height:1.25;box-shadow:0 5px 14px #0006">{_e(text)}</div>')
            out += (f'<div style="height:{row_h}px;display:flex;align-items:center;gap:20px;'
                    f'{"" if mine else "flex-direction:row-reverse;"}">{av}{bub}</div>')
        return f'<div style="position:relative;height:{h}px;overflow:hidden;padding:20px 70px">{out}</div>'
    # quote
    return (f'<div style="{box}display:flex;align-items:center;justify-content:center;text-align:center;font-size:'
            f'{50 if h > 200 else 42}px;font-weight:900;line-height:1.25;color:{th["gold"]}">'
            f'<span style="color:{th["accent"]};font-size:90px;margin-right:16px">“</span>{_e(c.get("text") or "…")}'
            f'<span style="color:{th["accent"]};font-size:90px;margin-left:16px">”</span></div>')


def document(chunks: List[Dict[str, Any]], ctx: Dict[str, Any]) -> str:
    """The whole tall picture as one HTML page, 1600 px wide and as tall as its chunks add up to
    (screenshot it at size=(WIDTH, total(chunks))). ``ctx``: host (the draft's), week, img (render.ImageCache.data_url),
    heading, range, notes, facts, seed, pins (the draft's picture choices, hosts.look).
    Chunks are laid out one under the other; a chunk with a diagonal cut is clipped along its slanted
    bottom edge and the next chunk's background shows through the gap (it starts that much higher)."""
    ctx = dict(ctx, theme=THEMES.get(ctx["host"], THEMES["colette"]))
    th = ctx["theme"]
    bands = BANDS.get(ctx["host"], BANDS["colette"])
    cuts = [cut_depth(chunks, i) for i in range(len(chunks))]
    n, y, rows, seams = len(chunks), 0, [], []
    for i, c in enumerate(chunks):
        h, d, above = height(c), cuts[i], (cuts[i - 1] if i else 0)
        bg = f"background:{bands[i % len(bands)]};" if (d or above) else ""
        clip = ""
        if d:
            kind = c.get("cut")
            poly = {"down": f"0 0,100% 0,100% 100%,0 calc(100% - {d}px)",
                    "up": f"0 0,100% 0,100% calc(100% - {d}px),0 100%",
                    "v": f"0 0,100% 0,100% calc(100% - {d}px),{V_AT}% 100%,0 calc(100% - {d}px)",
                    "peak": f"0 0,100% 0,100% 100%,{V_AT}% calc(100% - {d}px),0 100%"}[kind]
            clip = f"clip-path:polygon({poly});"
            seams.append((y + h, d, kind))
        rows.append(f'<div style="position:absolute;left:0;top:{y - above}px;width:{WIDTH}px;height:{h + above}px;'
                    f'z-index:{n - i};{bg}{clip}"><div style="position:absolute;left:0;top:{above}px;width:{WIDTH}px;'
                    f'height:{h - d}px">{_draw(c, ctx, h - d)}</div></div>')
        y += h
    stripes = ""
    for bottom, d, kind in seams:
        mid = int(WIDTH * V_AT / 100)
        pts = {"down": [(0, bottom - d), (WIDTH, bottom)], "up": [(0, bottom), (WIDTH, bottom - d)],
               "v": [(0, bottom - d), (mid, bottom), (WIDTH, bottom - d)],
               "peak": [(0, bottom), (mid, bottom - d), (WIDTH, bottom)]}[kind]
        line = " ".join(f"{x},{yy}" for x, yy in pts)
        stripes += (f'<polyline points="{line}" fill="none" stroke="#fff" stroke-width="18"/>'
                    f'<polyline points="{line}" fill="none" stroke="{th["accent"]}" stroke-width="7"/>')
    svg = (f'<svg style="position:absolute;left:0;top:0;z-index:99" width="{WIDTH}" height="{max(1, y)}" '
           f'viewBox="0 0 {WIDTH} {max(1, y)}">{stripes}</svg>') if stripes else ""
    return (f'<!doctype html><html><head><meta charset=utf-8><style>*{{box-sizing:border-box;margin:0}}'
            f'body{{position:relative;width:{WIDTH}px;height:{max(1, y)}px;overflow:hidden;background:{th["bg"]};color:{th["fg"]};'
            f'font-family:{th["font"]}}}</style></head><body>{"".join(rows)}{svg}</body></html>')


__all__ = ["WIDTH", "MAX_H", "TYPES", "SIDES", "CUTS", "SLOPES", "cut_depth", "BUILTIN", "height", "total", "new_chunk", "renumber", "document",
           "tile_choices"]
