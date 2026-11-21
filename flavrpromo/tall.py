"""
Tall pictures built from chunks (owner 2026-11-21: "break the image down into chunks, then let me use
menus to assemble each chunk, and have the tall image built from those saved chunks").

An X Article shows a picture whole up to 1600 x 2133 (3:4; taller ones are cropped from the middle,
the owner's test 2026-11-21), so a tall picture is a stack of full-width strips, ``chunks``, that
add up to at most MAX_H pixels. This file is the model and the drawing; the builder page (menus,
saving) is flavrpromo/tall_page.py, and the article editor adds a tall picture as a section
(flavrpromo/article_editor.py).

A chunk is a dict: {"id", "type", "size" (0 small, 1 medium, 2 large), ...fields of its type}.
  header   a title and a line under it (blank = the article's heading and date range)     title, sub
  host     a host picture on one side, a speech bubble with their line on the other      host, kind, var, side, line
  stream   one stream: thumbnail, name, game, time, and a line                              ref ("d<day>:<n>"), line
  stats    the review's highlight numbers side by side (hosts.notes of the draft's facts)
  grid     one day's thumbnails (up to 6) under the day's name                              day (0-6)
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
    "footer": ("Sign-off strip", (260, 340, 440)),
}
SIDES = {"left": "Host on the left", "right": "Host on the right"}
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
    base: Dict[str, Any] = {"id": f"c{n}", "type": ctype if ctype in TYPES else "quote", "size": 1}
    defaults = {"header": {"title": "", "sub": ""},
                "host": {"host": "", "kind": "happy", "var": "", "side": "left", "line": ""},
                "stream": {"ref": "", "line": ""}, "stats": {}, "grid": {"day": 0}, "quote": {"text": ""},
                "footer": {"host": "", "kind": "chibi_happy", "var": "", "line": ""}}
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


def _draw(c: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    th, week, img = ctx["theme"], ctx["week"], ctx["img"]
    h, kind = height(c), c.get("type")
    box = f'position:relative;height:{h}px;overflow:hidden;padding:0 70px;'
    if kind == "header":
        title = c.get("title") or ctx.get("heading") or ""
        sub = c.get("sub") or ctx.get("range") or ""
        logo = f'<img src="{logo_data_url()}" style="height:{h - 90}px;margin-right:34px">' if ctx["host"] == "colette" else ""
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
        return (f'<div style="{box}display:flex;gap:34px;align-items:center">'
                f'<div style="width:{th_w}px;height:{h - 40}px;flex:none;border-radius:8px;background:#2a1026 center/cover;{bg}'
                f'box-shadow:0 6px 18px #0009"></div><div style="flex:1;min-width:0"><div style="font-size:44px;font-weight:900">'
                f'{_e(t.name)}</div><div style="font-size:28px;color:{th["gold"]};font-weight:700;margin:4px 0 8px">'
                f'{_e(" · ".join(x for x in (week.day_name(day_i), when, t.game) if x))}</div>'
                f'<div style="font-size:24px;opacity:.85;font-style:italic;white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis">{_e(t.title)}</div>'
                + (f'<div style="margin-top:12px;font-size:26px;font-weight:700;color:{th["accent"]}">“{_e(c["line"])}”</div>'
                   if c.get("line") else "") + '</div></div>')
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
    # quote
    return (f'<div style="{box}display:flex;align-items:center;justify-content:center;text-align:center;font-size:'
            f'{50 if h > 200 else 42}px;font-weight:900;line-height:1.25;color:{th["gold"]}">'
            f'<span style="color:{th["accent"]};font-size:90px;margin-right:16px">“</span>{_e(c.get("text") or "…")}'
            f'<span style="color:{th["accent"]};font-size:90px;margin-left:16px">”</span></div>')


def document(chunks: List[Dict[str, Any]], ctx: Dict[str, Any]) -> str:
    """The whole tall picture as one HTML page, 1600 px wide and as tall as its chunks add up to
    (screenshot it at size=(WIDTH, total(chunks))). ``ctx``: host (the draft's), week, img (render.ImageCache.data_url),
    heading, range, notes, facts, seed, pins (the draft's picture choices, hosts.look)."""
    ctx = dict(ctx, theme=THEMES.get(ctx["host"], THEMES["colette"]))
    th = ctx["theme"]
    rows = "".join(_draw(c, ctx) for c in chunks)
    return (f'<!doctype html><html><head><meta charset=utf-8><style>*{{box-sizing:border-box;margin:0}}'
            f'body{{width:{WIDTH}px;height:{max(1, total(chunks))}px;overflow:hidden;background:{th["bg"]};color:{th["fg"]};'
            f'font-family:{th["font"]}}}</style></head><body>{rows}</body></html>')


__all__ = ["WIDTH", "MAX_H", "TYPES", "SIDES", "BUILTIN", "height", "total", "new_chunk", "renumber", "document",
           "tile_choices"]
