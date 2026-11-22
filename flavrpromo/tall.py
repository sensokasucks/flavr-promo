"""
Tall pictures built from chunks (owner 2026-11-21: "break the image down into chunks, then let me use
menus to assemble each chunk, and have the tall image built from those saved chunks").

An X Article shows a picture whole up to 1600 x 2133 (3:4; taller ones are cropped from the middle,
the owner's test 2026-11-21), so a tall picture is a stack of full-width strips, ``chunks``, that
add up to at most MAX_H pixels. This file is the model and the drawing; the builder page (menus,
saving) is flavrpromo/tall_page.py, and the article editor adds a tall picture as a section
(flavrpromo/article_editor.py).

A chunk is a dict: {"id", "type", "size" (0 small, 1 medium, 2 large), "cut", "slope", "band", ...fields of its type}.
``band`` is the chunk's own background colour (a BAND_COLOURS key or "#rrggbb"; "" = automatic).
``cut`` is the shape of the chunk's bottom edge: "" straight, "down" slanting down to the right, "up"
slanting down to the left, "v" / "peak" a corner in the middle, and (owner 2026-11-22) "zig" a zigzag,
"wave" a wave (``teeth`` = how many teeth / waves), "arc" / "hill" one curve dipping / rising in the middle
(drawn from the sampled points of ``edge``). Owner 2026-11-21: diagonal cuts "add a more fun feel". ``slope`` 0 / 1 / 2 is
how steep (SLOPES px). A chunk with a cut, and the one under it, get their own background colour (BANDS)
and a stripe is drawn along the seam; the stack's height does not change (the cut eats into the chunk's
own bottom, so its content gets a little less room).
  header   a title and a line under it (blank = the article's heading and date range)     title, sub
  host     a host picture on one side, a speech bubble with their line on the other      host, kind, var, side, line
  stream   one stream: thumbnail, name, game, time, title, a remark, a host picture         ref ("d<day>:<n>"), show, line, host, kind, var
  game     one game played this week: who played it, how many streams, history tags (new / staple /
           part 4), genre and what it is (IGDB), a remark                                      game, show, line, host, kind, var
  stats    the review's highlight numbers side by side (hosts.notes of the draft's facts)
  grid     one day's thumbnails (up to 6) under the day's name                              day (0-6)
  hero     a big opening: a small word on top ("Meet"), the host's name huge, their job, a tagline, and
           the host picture large on an angled colour panel                                  top, title, sub, tag, host, kind, var
  chat     speech-bubble rows, two hosts talking (alternating, each with their head as the avatar)
                                                                                              lines (one per row), host, other
  quote    one big line of text                                                              text
  footer   a closing strip: the host's small picture and a sign-off line                    host, kind, var, line
Host pictures (owner 2026-11-22: "the character image turned out really small. would be nice if i can
scale, rotate, flip them. and being able to add a host image in each chunk"): every chunk type can carry
one. Host / footer / hero chunks always have theirs, stream and game chunks when "host" is ticked in
``show``, and header / stats / grid / quote chunks when ``pic`` is on (``side`` left or right; it sits on
top of the chunk's content). Any of them takes ``pscale`` (size in %, 100 = as built), ``prot`` (degrees,
clockwise), ``pflip`` (mirrored), ``px`` / ``py`` (moved right / down in px) and ``ppop`` (may stick out
over the neighbouring chunks instead of being cut off at this chunk's edges). ``figure`` works out where
the picture goes; ``document`` draws it in its own layer.
``look`` (stream chunks; owner 2026-11-22: "is there a good way to add the article styles, like this, to the chunk
stacks as well?"): "" = the plain row, "strip" = a colourful tilted strip like the day pictures' (host_cards.py
``_strip``): a time pill, the thumbnail in a white frame with its platform badges, "Name · length" and the title, the
remark under them; every other strip swings to the right and carries its thumbnail on that side, and the strips
take the host's note colours (or the colour scheme's) in turn. ``document`` numbers the strip chunks (``strip_k``)
for that; the chunk's background stays the stack's own, so the strips sit on it like notes on a wall.
``show`` (stream and game chunks only; owner 2026-11-21 "mix n match the sort of content that goes into
each segment") lists which parts are drawn, from SHOW; a chunk saved before it existed shows DEFAULT_SHOW.
The "game" chunks and the stream chunks are what flavrpromo/recipes.py stacks into whole tall sections
(games this week, one day in detail, one person's week); their remarks come from KoboldCpp
(recipes.write_line). ``host`` empty = the draft's host; ``kind`` is a hosts.POOLED picture kind (happy, chibi_happy ...,
so one picture can mix regular and chibi pictures for more emotion); ``var`` pins one picture of
that kind's pool ("" = the draft's automatic pick, hosts.look). Chunks can be saved by name
(kv "tall_chunks" {name: chunk}) and whole stacks too (kv "tall_templates" {name: [chunk]}).

Colours: the host's own THEMES / BANDS, or a colour scheme (ctx["scheme"], a flavrpromo/schemes.py key
picked in the article editor) in the host's lettering; a chunk's own ``band`` colour wins either way.

Who calls it: flavrpromo/tall_page.py (builder, preview) and flavrpromo/article_editor.py
(the picture inside the article). Pure functions: no network, no Discord.
"""

from __future__ import annotations

import copy
import html
import math
from typing import Any, Dict, List, Tuple

from . import hosts, schemes
from .render import PLATFORM_BADGE, clock, hm, logo_data_url

CHUNKS_KEY, TEMPLATES_KEY = "tall_chunks", "tall_templates"   # kv: saved chunks {name: chunk}, saved stacks {name: [chunk]}
WEEK_FIELDS = ("ref", "game", "line", "lines", "hint")   # what belongs to one week: a stack saved as a template drops these
WIDTH = 1600
MAX_H = 2133                         # px: the tallest picture X shows whole (3:4 at this width)
# type → (label, heights small / medium / large in px)
TYPES: Dict[str, Any] = {
    "header": ("Header", (180, 240, 300)),
    "host": ("Host moment", (380, 520, 660)),
    "stream": ("One stream", (200, 250, 310)),
    "game": ("A game", (200, 250, 320)),
    "stats": ("Highlight numbers", (150, 200, 260)),
    "grid": ("A day's pictures", (400, 540, 700)),
    "quote": ("Big line", (170, 220, 300)),
    "hero": ("Hero opening", (420, 520, 640)),
    "chat": ("Chat bubbles", (300, 420, 560)),
    "footer": ("Sign-off strip", (260, 340, 440)),
}
# what a stream / game chunk can show (the builder's tick boxes) and what a new one shows
SHOW: Dict[str, Dict[str, str]] = {
    "stream": {"thumb": "Stream picture", "name": "Name", "when": "Day and time", "game": "Game", "title": "Stream title",
               "hashtags": "Hashtags in the title", "line": "Remark", "host": "Host picture"},
    "game": {"people": "Who played it", "count": "Number of streams", "tags": "History tags (new, part 4 ...)",
             "genre": "Genre", "about": "What it is (IGDB)", "line": "Remark", "host": "Host picture"},
}
DEFAULT_SHOW: Dict[str, Tuple[str, ...]] = {
    "stream": ("thumb", "name", "when", "game", "title", "line"),
    "game": ("people", "count", "tags", "genre", "about", "line"),
}
# the band colour menu of every chunk (``band``: a key here, or "#rrggbb" from the colour box; "" = automatic:
# the theme background, or the host's BANDS in turn next to a cut). Owner 2026-11-22: "a colour menu per chunk".
BAND_COLOURS = {"plum": ("Plum", "#2a0f2a"), "berry": ("Berry", "#521b4c"), "wine": ("Wine", "#3d1233"),
                "night": ("Night", "#15101a"), "pink": ("Hot pink", "#b3187a"), "navy": ("Navy", "#14213d"),
                "teal": ("Teal", "#0e4a4c"), "forest": ("Forest", "#173a24"), "cocoa": ("Cocoa", "#3a2416"),
                "rust": ("Rust", "#7a3a14"), "gold": ("Gold", "#f8cf33"), "paper": ("Paper", "#f4ead8")}
LOOKS = {"": "Plain row", "strip": "Colour strip (like the day pictures)"}     # a stream chunk's ``look``
STRIP_SWING = 180                    # px a strip steps in from the left when it swings (every other one), as the day pictures do
PIC_TYPES = ("header", "stats", "grid", "quote")      # chunk types whose host picture is optional (``pic``)
# the picture controls every chunk has: field → (lowest, highest, default); see the docstring
PIC_NUMBERS = {"pscale": (30, 400, 100), "prot": (-180, 180, 0), "px": (-1600, 1600, 0), "py": (-1200, 1200, 0)}
TAG_WORDS = {"new": "NEW GAME", "staple": "STAPLE", "back": "BACK AGAIN"}     # "part:4" reads PART 4
SIDES = {"left": "Host on the left", "right": "Host on the right"}
CUTS = {"": "Straight edge", "down": "Slants down to the right ↘", "up": "Slants down to the left ↙",
        "v": "V shape ⌄ (dips in the middle)", "peak": "Peak ⌃ (rises in the middle)",
        "zig": "Zigzag ⩘ (teeth)", "wave": "Wave ∿", "arc": "Curve dipping in the middle ◡",
        "hill": "Curve rising in the middle ◠"}
SHAPED = ("zig", "wave", "arc", "hill")   # cuts drawn from sampled points (``edge``), not from two or three corners
TEETH = {"zig": (2, 24, 8), "wave": (1, 12, 3)}    # ``teeth``: how many teeth / waves across the width (min, max, default)
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
                "stream": {"ref": "", "line": "", "host": "", "kind": "happy", "var": ""},
                "game": {"game": "", "line": "", "host": "", "kind": "happy", "var": ""}, "stats": {}, "grid": {"day": 0}, "quote": {"text": ""},
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


def strip(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A stack as a reusable template (owner 2026-11-21): the layout (types, sizes, cuts, show boxes, hosts,
    poses, headers, big lines) kept, what belongs to one week (the chosen stream or game, the remarks, the
    chat lines) emptied. recipes.fill puts this week's streams and games in when it is used."""
    out = renumber(chunks)
    for c in out:
        c.pop("choices", None)                    # KoboldCpp's alternatives for this week's remark
        c.pop("found", None), c.pop("found_q", None)      # the game picker's search (flavrpromo/tall_page.py)
        for k in WEEK_FIELDS:
            if k in c:
                c[k] = ""
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
    "Colour strips": [                  # four streams as the day pictures' colour strips (recipes.fill puts the streams in)
        {"id": "c1", "type": "header", "size": 0, "title": "", "sub": ""},
        {"id": "c2", "type": "stream", "size": 1, "look": "strip", "ref": "", "line": "", "host": "", "kind": "happy", "var": ""},
        {"id": "c3", "type": "stream", "size": 1, "look": "strip", "ref": "", "line": "", "host": "", "kind": "happy", "var": ""},
        {"id": "c4", "type": "stream", "size": 1, "look": "strip", "ref": "", "line": "", "host": "", "kind": "happy", "var": ""},
        {"id": "c5", "type": "stream", "size": 1, "look": "strip", "ref": "", "line": "", "host": "", "kind": "happy", "var": ""},
        {"id": "c6", "type": "footer", "size": 0, "host": "", "kind": "chibi_happy", "var": "", "line": ""},
    ],
    "Day in detail": [
        {"id": "c1", "type": "header", "size": 0, "title": "", "sub": ""},
        {"id": "c2", "type": "grid", "size": 1, "day": 0},
        {"id": "c3", "type": "host", "size": 0, "host": "", "kind": "chibi_pointing", "var": "", "side": "right", "line": ""},
        {"id": "c4", "type": "quote", "size": 0, "text": ""},
    ],
}


def band_colour(c: Dict[str, Any]) -> str:
    """The chunk's own background colour as "#rrggbb", "" when it is left automatic (or the value is nonsense)."""
    b = str(c.get("band") or "")
    if b in BAND_COLOURS:
        return BAND_COLOURS[b][1]
    return b.lower() if len(b) == 7 and b[0] == "#" and all(x in "0123456789abcdefABCDEF" for x in b[1:]) else ""


def _is_light(colour: str) -> bool:
    """Whether dark text reads better on ``colour`` ("#rrggbb"): its perceived brightness is over 60%."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6


def shown(c: Dict[str, Any], part: str) -> bool:
    """Whether a stream / game chunk draws ``part`` (a key of SHOW): its own ``show`` list, else the default."""
    show = c["show"] if isinstance(c.get("show"), list) else DEFAULT_SHOW.get(c.get("type"), ())
    return part in show


def tag_words(tags: List[str]) -> List[str]:
    """History tags as the words drawn on a game chunk: ["new", "part:4"] → ["NEW GAME", "PART 4"]."""
    return [TAG_WORDS.get(t) or t.replace("part:", "PART ").upper() for t in tags or []]


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


def _accent(who: str, ctx: Dict[str, Any]) -> str:
    """The accent colour for host ``who`` on this picture: their own (THEMES) in the hosts' own colours.
    Under a colour scheme (ctx["scheme"], flavrpromo/schemes.py) the picture's host gets the scheme's
    accent and the other host its second accent, so two speakers still tell apart."""
    th = ctx["theme"]
    if not ctx.get("scheme"):
        return THEMES.get(who, th)["accent"]
    return th["accent"] if who == ctx["host"] else th["gold"]


def _bubble(text: str, th: Dict[str, str], accent: str, extra: str = "") -> str:
    if not text:
        return ""
    return (f'<div style="background:{th["paper"]};color:{th["ink"]};border:5px solid {accent};border-radius:30px;'
            f'padding:26px 34px;font-size:32px;line-height:1.32;font-weight:700;box-shadow:0 8px 26px #0007;{extra}">'
            f'{_e(text)}</div>')


def _remark(c: Dict[str, Any], th: Dict[str, str], f: float) -> str:
    """The host's remark under a stream / game chunk (when "line" is ticked and there is one)."""
    if not (shown(c, "line") and c.get("line")):
        return ""
    return (f'<div style="margin-top:{int(12 * f)}px;font-size:{int(26 * f)}px;font-weight:700;color:{th["accent"]}">'
            f'“{_e(c["line"])}”</div>')


def _side_host(c: Dict[str, Any], ctx: Dict[str, Any], h: int) -> str:
    """Room at the right end of a stream / game chunk for its host picture (when "host" is ticked; the
    picture itself is drawn by ``document`` from ``figure``)."""
    fig = figure(c, ctx, h)
    return f'<div style="width:{fig["room"]}px;flex:none"></div>' if fig else ""


def _num(c: Dict[str, Any], field: str) -> int:
    lo, hi, default = PIC_NUMBERS[field]
    try:
        return max(lo, min(hi, int(c.get(field, default))))
    except (TypeError, ValueError):
        return default


def has_figure(c: Dict[str, Any]) -> bool:
    """Whether the chunk shows a host picture (so the builder offers its size / rotate / flip controls)."""
    t = c.get("type")
    return t in ("host", "footer", "hero") or (t in SHOW and shown(c, "host")) or (t in PIC_TYPES and bool(c.get("pic")))


def figure(c: Dict[str, Any], ctx: Dict[str, Any], h: int) -> Dict[str, Any]:
    """Where the chunk's host picture goes in a box ``h`` px tall: {src, x, w, h (the picture's own box, standing
    on the chunk's bottom edge), room, css (its transform), pop}; {} when the chunk has none or the picture is missing.
    The box is the size the chunk was designed with; ``pscale`` etc. are applied on top as a CSS transform
    around the picture's feet, so the text next to it stays where it is. ``h`` is the part the text uses
    (chunk height minus the seam depth); ``document`` moves the feet down to the seam where the picture stands
    (``seam_up``)."""
    if not has_figure(c):
        return {}
    src = _pic(ctx, _host_of(c, ctx), c.get("kind") or "happy", c.get("var") or "")
    if not src:
        return {}
    t = c.get("type")
    room = 0                                          # px of the row kept free for it (pictures beside the text only)
    if t == "hero":
        ph = int(h * 0.98)
        pw = int(min(WIDTH * 0.46, ph * 0.9))
        x = WIDTH - 50 - pw
    elif t in PIC_TYPES:
        ph = h - 10
        pw = int(ph * 0.8)
        x = 40 if c.get("side") == "left" else WIDTH - 40 - pw
    else:
        # beside the text (host moment, sign-off, stream, game): the room kept free for it grows and shrinks with
        # its size, so a bigger host pushes the bubble / text aside instead of covering it (at most 45% of the width)
        ph = h - (24 if t in SHOW else 30)
        pw = int(ph * 0.8)
        room = max(40, min(int(WIDTH * 0.45), pw * _num(c, "pscale") // 100))
        left = 70 if not (t in SHOW or (t == "host" and c.get("side") == "right")) else WIDTH - 70 - room
        x = left + (room - pw) // 2
    css = (f"translate({_num(c, 'px')}px,{_num(c, 'py')}px) rotate({_num(c, 'prot')}deg) "
           f"scale({_num(c, 'pscale') / 100:.2f})" + (" scaleX(-1)" if c.get("pflip") else ""))
    return {"src": src, "x": x, "w": pw, "h": ph, "room": room, "css": css, "pop": bool(c.get("ppop"))}


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
    if i == len(chunks) - 1 or c.get("cut") not in ("down", "up", "v", "peak") + SHAPED:
        return 0
    try:
        d = SLOPES[max(0, min(2, int(c.get("slope", 1))))]
    except (TypeError, ValueError):
        d = SLOPES[1]
    return max(0, min(d, int(height(c) * 0.4)))          # the content keeps at least 60% of the chunk


def teeth(c: Dict[str, Any]) -> int:
    """How many teeth (zigzag) or waves the chunk's bottom edge has; 0 for the other cuts."""
    if c.get("cut") not in TEETH:
        return 0
    lo, hi, default = TEETH[c["cut"]]
    try:
        return max(lo, min(hi, int(c.get("teeth") or default)))
    except (TypeError, ValueError):
        return default


def edge(kind: str, d: int, n: int = 0) -> List[Tuple[float, float]]:
    """A zigzag / curved bottom edge (owner 2026-11-22) as points left to right: (x in % of the width, how
    many px the edge is above the chunk's bottom line there, 0..d). ``n``: teeth or waves (``teeth``).
    zig: sharp teeth; wave: a smooth sine; arc: one curve lowest in the middle; hill: highest in the middle."""
    if kind == "zig":
        n = n or TEETH["zig"][2]
        return [(100 * i / (2 * n), float(d if i % 2 == 0 else 0)) for i in range(2 * n + 1)]
    steps = 16 * (n or TEETH["wave"][2]) if kind == "wave" else 48
    out = []
    for i in range(steps + 1):
        x = i / steps
        up = (d / 2 * (1 + math.cos(2 * math.pi * (n or TEETH["wave"][2]) * x)) if kind == "wave"
              else d * (1 - math.sin(math.pi * x)) if kind == "arc" else d * math.sin(math.pi * x))
        out.append((100 * x, round(up, 1)))
    return out


def seam_up(c: Dict[str, Any], d: int, x: float) -> float:
    """How many px above the chunk's bottom line its slanted / shaped bottom edge is at ``x`` px from the left
    (0 for a straight edge or ``d`` = 0). ``document`` stands a chunk's host picture on the edge at the
    picture's centre, so a picture on the low side of a diagonal reaches the seam instead of stopping short of it."""
    if not d:
        return 0.0
    kind = c.get("cut")
    pts = edge(kind, d, teeth(c)) if kind in SHAPED else \
        {"down": [(0, d), (100, 0)], "up": [(0, 0), (100, d)],
         "v": [(0, d), (V_AT, 0), (100, d)], "peak": [(0, 0), (V_AT, d), (100, 0)]}.get(kind)
    if not pts:
        return 0.0
    at = 100 * max(0.0, min(float(WIDTH), x)) / WIDTH
    for (x0, u0), (x1, u1) in zip(pts, pts[1:]):         # the points run left to right: interpolate between two
        if x0 <= at <= x1:
            return u0 + (u1 - u0) * ((at - x0) / (x1 - x0) if x1 > x0 else 0)
    return float(pts[-1][1])


def _strip_colours(ctx: Dict[str, Any]) -> Tuple[str, ...]:
    """The strips' colours in turn: the colour scheme's note colours, else the picture's host's own."""
    s = schemes.get(str(ctx.get("scheme") or "")) or schemes.BASE.get(ctx["host"]) or schemes.BASE["colette"]
    return tuple(s["notes"])


def _strip_row(c: Dict[str, Any], ctx: Dict[str, Any], h: int, t: Any, day_i: int, box: str) -> str:
    """A stream chunk in the "strip" look (see the docstring): one coloured strip in a box ``h`` px tall.
    ``ctx["strip_k"]`` = how many strips came before in the stack (set by ``document``): it picks the colour and
    which strips swing. Shows what the chunk's ``show`` ticks say (time pill, picture, name and length, day and
    game, title, remark). Clark's strips are straight with square corners (his file-folder tabs), Colette's tilt."""
    th, week, img = ctx["theme"], ctx["week"], ctx["img"]
    clark = ctx["host"] == "clark"
    k = int(ctx.get("strip_k") or 0)
    flip = k % 2 == 1
    sh = max(60, h - 30)                              # the strip's height: a little air above and below it
    fs = max(18, min(34, sh // 6))
    fig = figure(c, ctx, h)                           # a host picture ("document" draws it) stands at the right end:
    width = WIDTH - 140 - STRIP_SWING - (fig["room"] if fig else 0)     # the strip stops short of its room
    src = img(t.thumb) or img(t.avatar)
    bg = f'background-image:url(&quot;{_e(src)}&quot;);' if src else ""
    length = hm(t.length) if t.kind == "past" and t.end else "LIVE" if t.kind == "live" else "scheduled"
    title = t.title if shown(c, "hashtags") else " ".join(w for w in str(t.title).split() if not w.startswith("#"))
    chip = (f'<div style="flex:none;width:{int(fs * 5.8)}px;background:{th["accent"]};color:#fff;font-size:{fs}px;font-weight:900;white-space:nowrap;'
            f'text-align:center;padding:5px 0;border-radius:{6 if clark else 30}px">{_e(clock(t.at, week.tz))}</div>'
            if shown(c, "when") else "")
    badges = "".join(
        f'<span style="position:absolute;top:10px;right:{10 + 28 * n}px;width:24px;height:24px;border-radius:5px;'
        f'font:800 13px sans-serif;display:flex;align-items:center;justify-content:center;background:{bgc};color:{fgc}">{letter}</span>'
        for n, (letter, bgc, fgc) in enumerate(PLATFORM_BADGE[p] for p in t.platforms if p in PLATFORM_BADGE))
    pic = (f'<div style="position:relative;flex:none;width:{min(460, int((sh - 26) * 16 / 9))}px;height:{sh - 16}px;padding:5px;'
           f'background:#fff;box-shadow:3px 6px 14px #0008"><div style="width:100%;height:100%;background:#2a1026 center/cover '
           f'no-repeat;{bg}"></div>{badges}</div>' if shown(c, "thumb") else "")
    place = " · ".join(x for x in ((week.day_name(day_i),) if shown(c, "when") else ()) + ((t.game,) if shown(c, "game") else ()) if x)
    text = ((f'<div style="font-size:{fs + 4}px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
             f'{_e(t.name)}<span style="font-size:{fs - 4}px;font-weight:700;opacity:.7"> · {_e(length)}</span></div>'
             if shown(c, "name") else "")
            + (f'<div style="font-size:{fs - 6}px;font-weight:800;opacity:.75;white-space:nowrap;overflow:hidden;'
               f'text-overflow:ellipsis">{_e(place)}</div>' if place else "")
            + (f'<div style="font-size:{fs - 4}px;font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
               f'{_e(title)}</div>' if shown(c, "title") and title else "")
            + (f'<div style="margin-top:4px;font-size:{fs - 4}px;font-weight:700;display:-webkit-box;-webkit-line-clamp:2;'
               f'-webkit-box-orient:vertical;overflow:hidden">“{_e(c["line"])}”</div>'
               if shown(c, "line") and c.get("line") else ""))
    inner = chip + ((f'<div style="flex:1;min-width:0">{text}</div>' + pic) if flip else (pic + f'<div style="flex:1;min-width:0">{text}</div>'))
    pal = _strip_colours(ctx)
    tilt = 0.0 if clark else (-0.6 if flip else 0.5)
    return (f'<div style="{box}display:flex;align-items:center">'
            f'<div style="display:flex;align-items:center;gap:18px;flex:none;width:{width}px;height:{sh}px;'
            f'margin-left:{STRIP_SWING if flip else 0}px;padding:8px 16px;background:{pal[k % len(pal)]};color:{th["ink"]};'
            f'border-radius:{4 if clark else 0}px;transform:rotate({tilt}deg);box-shadow:3px 5px 12px #0007">{inner}</div></div>')


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
        acc = _accent(key, ctx)
        right = c.get("side") == "right" and kind == "host"
        fig = figure(c, ctx, h)                 # the picture is drawn by ``document``; here only its room
        spacer = f'<div style="width:{fig["room"]}px;flex:none"></div>' if fig else ""
        who = f'<div style="margin-top:12px;font-size:24px;color:{th["gold"]};font-weight:700">— {_e(hosts.HOSTS[key]["name"])}</div>'
        say = (f'<div style="flex:1">{_bubble(c.get("line") or "", th, acc)}{who if c.get("line") else ""}</div>')
        parts = [say, spacer] if right else [spacer, say]
        return (f'<div style="{box}display:flex;gap:40px;align-items:center;'
                f'{"border-top:6px solid " + acc + ";" if kind == "footer" else ""}">{"".join(parts)}</div>')
    if kind == "stream":
        day_i, t = _tile_of(c.get("ref") or "", week)
        if t is None:
            return (f'<div style="{box}display:flex;align-items:center;font-size:30px;color:{th["gold"]}">'
                    f'Pick a stream from the menu.</div>')
        if c.get("look") == "strip":
            return _strip_row(c, ctx, h, t, day_i, box)
        src = img(t.thumb) or img(t.avatar)
        bg = f'background-image:url(&quot;{_e(src)}&quot;);' if src else ""
        when = clock(t.at, week.tz) + (f" · {hm(t.length)}" if t.kind == "past" and t.end else
                                       " · LIVE" if t.kind == "live" else "")
        th_w = int((h - 40) * 16 / 9)
        # "#FlaVR #vtuber ..." at the end of a title is noise in a picture: dropped unless "hashtags" is ticked
        title = t.title if shown(c, "hashtags") else " ".join(w for w in str(t.title).split() if not w.startswith("#"))
        f = min(1.0, h / 230)                     # a stream chunk with a deep cut has less room: smaller type
        place = " · ".join(x for x in ((week.day_name(day_i), when) if shown(c, "when") else ()) + ((t.game,) if shown(c, "game") else ()) if x)
        thumb = (f'<div style="width:{th_w}px;height:{h - 40}px;flex:none;border-radius:8px;background:#2a1026 center/cover;{bg}'
                 f'box-shadow:0 6px 18px #0009"></div>' if shown(c, "thumb") else "")
        text = ((f'<div style="font-size:{int(44 * f)}px;font-weight:900">{_e(t.name)}</div>' if shown(c, "name") else "")
                + (f'<div style="font-size:{int(28 * f)}px;color:{th["gold"]};font-weight:700;margin:2px 0 {int(8 * f)}px">'
                   f'{_e(place)}</div>' if place else "")
                + (f'<div style="font-size:{int(24 * f)}px;opacity:.85;font-style:italic;white-space:nowrap;overflow:hidden;'
                   f'text-overflow:ellipsis">{_e(title)}</div>' if shown(c, "title") and title else "")
                + _remark(c, th, f))
        return (f'<div style="{box}display:flex;gap:34px;align-items:center">{thumb}'
                f'<div style="flex:1;min-width:0">{text}</div>{_side_host(c, ctx, h)}</div>')
    if kind == "game":
        g = str(c.get("game") or "")
        if not g:
            return (f'<div style="{box}display:flex;align-items:center;font-size:30px;color:{th["gold"]}">'
                    f'Pick a game from the menu.</div>')
        row = (ctx.get("games") or {}).get(g.lower()) or {}
        info = (ctx.get("info") or {}).get(g.lower()) or {}
        f = min(1.0, h / 230)
        n = int(row.get("streams") or 0)
        meta = " · ".join(x for x in (
            (", ".join(row.get("people") or []) if shown(c, "people") else ""),
            (f"{n} stream{'' if n == 1 else 's'}" if shown(c, "count") and n else "")) if x)
        genre = ", ".join(info.get("genres") or [])
        tags = tag_words(row.get("tags") or []) if shown(c, "tags") else []
        badge = "".join(f'<div style="background:{th["gold"]};color:{th["ink"]};font-size:{int(26 * f)}px;font-weight:900;'
                        f'letter-spacing:2px;padding:4px 14px;border-radius:6px;margin:4px 0">{_e(x)}</div>' for x in tags)
        about = info.get("summary") or ""
        body = (f'<div style="font-size:{int(46 * f)}px;font-weight:900;line-height:1.1">{_e(g)}</div>'
                + (f'<div style="font-size:{int(28 * f)}px;color:{th["gold"]};font-weight:700;margin-top:4px">{_e(meta)}</div>' if meta else "")
                + (f'<div style="font-size:{int(24 * f)}px;color:{th["accent"]};font-weight:800;text-transform:uppercase;'
                   f'letter-spacing:2px;margin-top:4px">{_e(genre)}</div>' if shown(c, "genre") and genre else "")
                + (f'<div style="font-size:{int(23 * f)}px;opacity:.85;font-style:italic;margin-top:6px;max-height:{int(62 * f)}px;'
                   f'overflow:hidden">{_e(about)}</div>' if shown(c, "about") and about else "")
                + _remark(c, th, f))
        return (f'<div style="{box}display:flex;gap:34px;align-items:center">'
                + (f'<div style="width:{int(WIDTH * 0.2)}px;flex:none;display:flex;flex-direction:column;align-items:flex-start;'
                   f'border-left:10px solid {th["accent"]};padding-left:18px">{badge}</div>' if badge else "")
                + f'<div style="flex:1;min-width:0">{body}</div>{_side_host(c, ctx, h)}</div>')
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
        acc = _accent(key, ctx)
        title = c.get("title") or hosts.HOSTS[key]["name"].split()[0]
        sub = c.get("sub") or hosts.HOSTS[key]["role"]
        tag = c.get("tag") or ctx.get("range") or ""
        big = min(210, int(h * 0.42), int(WIDTH * 0.47 / (0.8 * max(4, len(title)))))      # a long name must stay off the panel
        panel = (f'<div style="position:absolute;right:0;top:0;width:{int(WIDTH * 0.52)}px;height:100%;background:{acc};'
                 f'clip-path:polygon(24% 0,100% 0,100% 100%,0 100%)"></div>')
        return (f'<div style="position:relative;height:{h}px;overflow:hidden">{panel}'
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
        # the bubbles' type size: as big as the row allows while the LONGEST line still fits in its row
        # (KoboldCpp's chat lines run to two rows of text; before, two-row bubbles ran into each other)
        bub_w = int(WIDTH * 0.66)
        fs, pad = min(34, max(22, row_h // 3)), max(10, row_h // 6)
        longest = max(len(x) for x in rows)
        while fs > 17:
            per_row = max(1, int((bub_w - 60) / (fs * 0.6)))            # characters per row of text, roughly
            if -(-longest // per_row) * fs * 1.25 + 2 * pad + 10 <= row_h:
                break
            fs, pad = fs - 1, max(6, pad - 1)
        out = ""
        for n, text in enumerate(rows):
            who = a if n % 2 == 0 else b
            avatar = _pic(ctx, who, "head", "") or _pic(ctx, who, "chibi_head", "")
            acc = _accent(who, ctx)
            mine = n % 2 == 0
            av = (f'<div style="width:{min(96, row_h - 10)}px;height:{min(96, row_h - 10)}px;border-radius:50%;flex:none;'
                  f'background:{acc}{f' center/cover url({avatar})' if avatar else ''};border:4px solid #fff;box-shadow:0 4px 10px #0007"></div>')
            bub = (f'<div style="max-width:{bub_w}px;background:{acc if mine else th["paper"]};'
                   f'color:{"#fff" if mine else th["ink"]};border-radius:30px;padding:{pad}px 30px;'
                   f'font-size:{fs}px;font-weight:700;line-height:1.25;box-shadow:0 5px 14px #0006">{_e(text)}</div>')
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
    # the colours: the host's own theme, or a colour scheme in the host's lettering (ctx["scheme"], a
    # flavrpromo/schemes.py key from the article draft; "" or unknown = the host's own)
    own = THEMES.get(ctx["host"], THEMES["colette"])
    scheme = ctx.get("scheme") if schemes.get(str(ctx.get("scheme") or "")) else ""
    ctx = dict(ctx, theme=schemes.theme(scheme, own["font"]) or own, scheme=scheme)
    th = ctx["theme"]
    bands = schemes.bands(scheme) or BANDS.get(ctx["host"], BANDS["colette"])
    cuts = [cut_depth(chunks, i) for i in range(len(chunks))]
    n, y, rows, seams, pops, strips_before = len(chunks), 0, [], [], "", 0
    for i, c in enumerate(chunks):
        h, d, above = height(c), cuts[i], (cuts[i - 1] if i else 0)
        own = band_colour(c)                      # the owner's pick wins over the automatic bands
        bg = (f"background:{own};" + (f"color:{th['ink']};" if _is_light(own) else "") if own
              else f"background:{bands[i % len(bands)]};" if (d or above) else "")
        clip = ""
        if d:
            kind = c.get("cut")
            pts = edge(kind, d, teeth(c)) if kind in SHAPED else []
            poly = ("0 0,100% 0," + ",".join(f"{x:g}% calc(100% - {up:g}px)" for x, up in reversed(pts))) if pts else \
                   {"down": f"0 0,100% 0,100% 100%,0 calc(100% - {d}px)",
                    "up": f"0 0,100% 0,100% calc(100% - {d}px),0 100%",
                    "v": f"0 0,100% 0,100% calc(100% - {d}px),{V_AT}% 100%,0 calc(100% - {d}px)",
                    "peak": f"0 0,100% 0,100% 100%,{V_AT}% calc(100% - {d}px),0 100%"}[kind]
            clip = f"clip-path:polygon({poly});"
            seams.append((y + h, d, kind, pts))
        # the host picture: standing on the chunk's bottom edge, turned / scaled around its feet. It is sized for
        # the part the text uses (h - d) but stands on the seam where its centre is (``seam_up``): on the low
        # side of a diagonal the chunk goes down to the seam, and a picture standing on h - d would stop short
        # of it (owner 2026-11-22, the chibi beside Cara's stream). Inside the chunk it is cut off at the chunk's
        # top and along its seam (the row's clip-path); with ``ppop`` it goes in a layer over the whole picture.
        fig, inside = figure(c, ctx, h - d), ""
        if fig:
            feet = h - round(seam_up(c, d, fig["x"] + fig["w"] / 2 + _num(c, "px")))      # y of its feet inside the chunk
            img = (f'<img src="{fig["src"]}" style="position:absolute;left:{fig["x"]}px;top:@TOP@px;width:{fig["w"]}px;'
                   f'height:{fig["h"]}px;object-fit:contain;object-position:bottom;transform-origin:50% 100%;'
                   f'transform:{fig["css"]}">')
            if fig["pop"]:
                pops += img.replace("@TOP@", str(y + feet - fig["h"]), 1)
            else:
                inside = (f'<div style="position:absolute;left:0;top:{above}px;width:{WIDTH}px;height:{h}px;overflow:hidden">'
                          + img.replace("@TOP@", str(feet - fig["h"]), 1) + "</div>")
        rows.append(f'<div style="position:absolute;left:0;top:{y - above}px;width:{WIDTH}px;height:{h + above}px;'
                    f'z-index:{n - i};{bg}{clip}"><div style="position:absolute;left:0;top:{above}px;width:{WIDTH}px;'
                    f'height:{h - d}px;overflow:hidden">{_draw(c, dict(ctx, strip_k=strips_before), h - d)}</div>{inside}</div>')
        strips_before += c.get("type") == "stream" and c.get("look") == "strip"
        y += h
    stripes = ""
    for bottom, d, kind, shaped in seams:
        mid = int(WIDTH * V_AT / 100)
        pts = [(round(WIDTH * x / 100, 1), round(bottom - up, 1)) for x, up in shaped] if shaped else \
              {"down": [(0, bottom - d), (WIDTH, bottom)], "up": [(0, bottom), (WIDTH, bottom - d)],
               "v": [(0, bottom - d), (mid, bottom), (WIDTH, bottom - d)],
               "peak": [(0, bottom), (mid, bottom - d), (WIDTH, bottom)]}[kind]
        line = " ".join(f"{x:g},{yy:g}" for x, yy in pts)
        stripes += (f'<polyline points="{line}" fill="none" stroke="#fff" stroke-width="18" stroke-linejoin="round"/>'
                    f'<polyline points="{line}" fill="none" stroke="{th["accent"]}" stroke-width="7" stroke-linejoin="round"/>')
    svg = (f'<svg style="position:absolute;left:0;top:0;z-index:99" width="{WIDTH}" height="{max(1, y)}" '
           f'viewBox="0 0 {WIDTH} {max(1, y)}">{stripes}</svg>') if stripes else ""
    return (f'<!doctype html><html><head><meta charset=utf-8><style>*{{box-sizing:border-box;margin:0}}'
            f'body{{position:relative;width:{WIDTH}px;height:{max(1, y)}px;overflow:hidden;background:{th["bg"]};color:{th["fg"]};'
            f'font-family:{th["font"]}}}</style></head><body>{"".join(rows)}{svg}'
            f'<div style="position:absolute;left:0;top:0;z-index:100">{pops}</div></body></html>')


__all__ = ["WIDTH", "MAX_H", "TYPES", "SIDES", "CHUNKS_KEY", "TEMPLATES_KEY", "strip", "SHOW", "DEFAULT_SHOW", "shown", "has_figure", "figure", "PIC_TYPES", "PIC_NUMBERS", "BAND_COLOURS", "band_colour", "tag_words", "CUTS", "SHAPED", "TEETH", "teeth", "edge", "SLOPES", "cut_depth", "seam_up", "LOOKS", "BUILTIN", "height", "total", "new_chunk", "renumber", "document",
           "tile_choices"]
