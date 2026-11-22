"""
Colour schemes for the article's pictures (owner 2026-11-22: "we can certainly do with more color
schemes for article images").

Until now a picture's colours came from its host alone: Colette's plum and hot pink, Clark's cocoa and
cream. A scheme is another set of the same colours by ROLE (ROLES below): three background shades, an
accent, a second accent ("gold"), paper and ink, the text colour on the background, and four pastel
note colours. Picking one keeps the host's layout, pictures and lettering and only changes the colours.

Two ways a scheme reaches a picture:
  * Tall pictures (flavrpromo/tall.py) are drawn from a theme by role already, so ``theme`` / ``bands``
    simply build that theme from the scheme.
  * The cards of flavrpromo/host_cards.py (opener, desk, day pictures, cover) have their colours
    written into the page. ``recolour`` goes over the finished page and swaps every colour for the
    scheme's colour of the same role: each colour is matched to the nearest of the hosts' own role
    colours (ANCHORS) and moved by the same step in lightness and strength, so a darker shade of
    Clark's cocoa becomes a darker shade of the scheme's background. Greys, black, white, the
    platform badges and a few fixed colours (KEEP) are left alone. Only colours inside style="..."
    and <style> are touched, never a "#beef" in someone's stream title.

Which scheme a picture gets: the article draft's p["scheme"] ("" = the host's own colours, a SCHEMES
key, "random" = one for the whole article from the draft's seed, "mix" = a different one per picture)
and p["schemes"] {picture: key} for one picture's own choice (``of``). Set on the article editor's
Look card and on each picture's card (flavrpromo/article_editor.py, flavrpromo/tall_page.py).

Who calls it: flavrpromo/article_editor.py (``of``, ``recolour``, the menus), flavrpromo/tall.py
(``theme``, ``bands``), flavrpromo/tall_page.py (``of``).

Keep in sync: BASE must list the colours flavrpromo/host_cards.py and tall.THEMES really use for each
role; a colour added there that is far from every anchor is left unchanged by ``recolour``.
"""

from __future__ import annotations

import colorsys
import re
import zlib
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .render import PLATFORM_BADGE

# the roles every scheme fills in; "notes" is a tuple of four (sticky notes, tape, strips)
ROLES = ("bg0", "bg1", "bg2", "accent", "gold", "paper", "ink", "fg")

# each host's own colours by role: what host_cards.py and tall.THEMES are written in. Also offered as
# schemes to the OTHER host ("Clark's colours" on Colette's pictures and the other way round).
BASE: Dict[str, Dict[str, Any]] = {
    "colette": {"name": "Colette's plum and pink", "bg0": "#1b1018", "bg1": "#3d1233", "bg2": "#521b4c",
                "accent": "#f72ca2", "gold": "#f8cf33", "paper": "#ffffff", "ink": "#1a1a1a", "fg": "#ffffff",
                "notes": ("#fbe48a", "#b7ef33", "#2ae0d4", "#ff9ad5")},
    "clark": {"name": "Clark's cocoa and cream", "bg0": "#1c130d", "bg1": "#3a2416", "bg2": "#563520",
              "accent": "#e0782e", "gold": "#d9b88a", "paper": "#f4ead8", "ink": "#2b1d12", "fg": "#f3e6d3",
              "notes": ("#e9c46a", "#a3c48f", "#e8907a", "#9dbcd0")},
}

# The schemes on offer. Rules they follow (tests/test_schemes.py checks them): dark backgrounds and
# light paper like the hosts' own, text colours that read on their background, and an accent that
# works both as lettering on the background and as a filled chip with white lettering on it.
SCHEMES: Dict[str, Dict[str, Any]] = {
    "ocean": {"name": "Ocean", "bg0": "#06141f", "bg1": "#0b2c44", "bg2": "#124a66",
              "accent": "#1c9fd0", "gold": "#ffd166", "paper": "#eef8fc", "ink": "#0f2230", "fg": "#e8f6ff",
              "notes": ("#ffe08a", "#8ef0d0", "#7fd4ff", "#ffb3c7")},
    "forest": {"name": "Forest", "bg0": "#0c1a10", "bg1": "#17351f", "bg2": "#24532f",
               "accent": "#3fae4a", "gold": "#f4c95d", "paper": "#f3f7e9", "ink": "#17241a", "fg": "#eef6e6",
               "notes": ("#ffe08a", "#b9f27c", "#8fe3c9", "#ffc09f")},
    "sunset": {"name": "Sunset", "bg0": "#15102e", "bg1": "#35195a", "bg2": "#6b2456",
               "accent": "#fb6a3c", "gold": "#ffd23f", "paper": "#fff4e6", "ink": "#2a1420", "fg": "#fff1e0",
               "notes": ("#ffd97a", "#ffb38a", "#ff9ec4", "#c9b6ff")},
    "midnight": {"name": "Midnight", "bg0": "#0a0c1c", "bg1": "#171b3d", "bg2": "#262c63",
                 "accent": "#8f7bff", "gold": "#5fe3ff", "paper": "#f1f2ff", "ink": "#14162b", "fg": "#e9ebff",
                 "notes": ("#c7bcff", "#8fe9ff", "#ffd6f2", "#b9f5d0")},
    "cherry": {"name": "Cherry soda", "bg0": "#1c0a0d", "bg1": "#45111a", "bg2": "#6e1b28",
               "accent": "#f2476a", "gold": "#ffc857", "paper": "#fff3ee", "ink": "#2a1215", "fg": "#ffeae6",
               "notes": ("#ffd97a", "#ffb0a8", "#ff9ec4", "#a8e6cf")},
    "mint": {"name": "Mint chocolate", "bg0": "#17110e", "bg1": "#2e211a", "bg2": "#46332a",
             "accent": "#1fae8b", "gold": "#f0d9a8", "paper": "#f1fbf6", "ink": "#1f1814", "fg": "#ecf7f1",
             "notes": ("#f0d9a8", "#a8ecd0", "#7fd8c4", "#f5b9a0")},
    "royal": {"name": "Royal", "bg0": "#120a24", "bg1": "#2a1458", "bg2": "#3f1f85",
              "accent": "#a866f5", "gold": "#f5c542", "paper": "#f7f1ff", "ink": "#1c1230", "fg": "#f1e9ff",
              "notes": ("#f5d76e", "#d9c2ff", "#9fd8ff", "#ffb3de")},
    "slate": {"name": "Slate and orange", "bg0": "#111418", "bg1": "#232a33", "bg2": "#36414f",
              "accent": "#f07f2e", "gold": "#9fd3ff", "paper": "#f3f5f7", "ink": "#1a1f26", "fg": "#eef2f6",
              "notes": ("#ffd28a", "#b8e0c8", "#9fd3ff", "#ffb8a0")},
    "arcade": {"name": "Arcade", "bg0": "#07070d", "bg1": "#141230", "bg2": "#231d52",
               "accent": "#f23fc4", "gold": "#5cf5a0", "paper": "#f4fff8", "ink": "#0d0f1a", "fg": "#eafff3",
               "notes": ("#fff275", "#5cf5a0", "#59d8ff", "#ff8fe0")},
    "peach": {"name": "Peach tea", "bg0": "#2a1612", "bg1": "#5a2c22", "bg2": "#8a4632",
              "accent": "#ef7654", "gold": "#ffe0a3", "paper": "#fff6ec", "ink": "#2e1a14", "fg": "#fff0e4",
              "notes": ("#ffe0a3", "#ffc2a8", "#f7a6b8", "#b9e3c6")},
    "lavender": {"name": "Lavender haze", "bg0": "#1a1426", "bg1": "#352a52", "bg2": "#50417a",
                 "accent": "#b07cf0", "gold": "#ffd1e8", "paper": "#f8f4ff", "ink": "#221a33", "fg": "#f2ecff",
                 "notes": ("#ffe6a8", "#d6c4ff", "#ffc4e1", "#b8e8f0")},
    "teal": {"name": "Teal and coral", "bg0": "#08191a", "bg1": "#0e3b3d", "bg2": "#155a5c",
             "accent": "#f2695c", "gold": "#ffd98a", "paper": "#f0faf8", "ink": "#10272a", "fg": "#e6f7f5",
             "notes": ("#ffd98a", "#8fe3d4", "#ffb0a3", "#b5d8ff")},
}
RANDOM, MIX = "random", "mix"       # p["scheme"]: one scheme per article by its seed / another for each picture

# colours ``recolour`` never touches: the platform badges (flavrpromo/render.py PLATFORM_BADGE), the red
# "live" clock on the boards and Clark's red stamp. Greys, black and white are skipped by ``_plain``.
KEEP = frozenset({c for _, c, _ in PLATFORM_BADGE.values()} | {"#e5312f", "#c0392b", "#b8402a"})
# shades host_cards.py uses that sit between two roles and would be matched to the wrong one by
# distance alone: the rule lines and small print on Clark's paper belong to the paper, not to "gold".
# "line" and "muted" are made from each scheme's paper and ink (``_derived``).
# Each is measured against the first colour of its role here (EXTRA_REF), so a darker one stays darker.
EXTRA_ANCHORS = {"#d8c3a3": "line", "#d9c7a8": "line", "#c9a77c": "line", "#e0d0b4": "line", "#e9dcc4": "line",
                 "#8a5a33": "muted", "#6b4a2e": "muted", "#5a3a20": "muted", "#5a4030": "muted"}
EXTRA_REF = {"line": "#d8c3a3", "muted": "#8a5a33"}
FAR = 150.0                         # a colour further than this from every anchor is left alone (``_distance`` units)
_HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z])")
# the only places a page's colours are written: style="..." attributes and <style> blocks
_STYLED = re.compile(r'style="[^"]*"|style=\'[^\']*\'|<style>.*?</style>', re.S)


def names(host: str = "") -> List[Tuple[str, str]]:
    """The scheme menu as (key, name): the built-in schemes, then the other host's own colours.
    ``host`` = whose pictures (their own colours are the menu's first, empty choice, not listed here)."""
    out = [(k, s["name"]) for k, s in SCHEMES.items()]
    return out + [(k, b["name"]) for k, b in BASE.items() if k != host]


def get(key: str) -> Optional[Dict[str, Any]]:
    """A scheme by its key (a SCHEMES key or a host's own colours), None for "" or an unknown key."""
    return SCHEMES.get(key) or BASE.get(key)


def of(p: Dict[str, Any], part: str = "") -> str:
    """The scheme key for one picture of article draft ``p`` ("" = the host's own colours). ``part`` names
    the picture ("" = the cover, "intro", "day3", "tall2" ...): its own choice in p["schemes"] wins, then
    the article's p["scheme"]; "random" and "mix" pick from the draft's seed, so a draft keeps its
    colours until 🎲 re-rolls (article_editor "reroll_pics" changes the seed)."""
    own = (p.get("schemes") or {}).get(part, "")
    choice = own if own and (get(own) or own == "host") else str(p.get("scheme") or "")
    if choice == "host":                 # this picture keeps the host's colours whatever the article says
        return ""
    keys = [k for k, _ in names(p.get("host", ""))]
    if choice == RANDOM:
        return keys[zlib.crc32(f"{p.get('seed')}".encode()) % len(keys)]
    if choice == MIX:
        return keys[zlib.crc32(f"{p.get('seed')}|{part}".encode()) % len(keys)]
    return choice if get(choice) and choice != p.get("host") else ""


# ── colour arithmetic ──────────────────────────────────────────────────
def _rgb(colour: str) -> Tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in (r, g, b))


def mix(a: str, b: str, t: float) -> str:
    """Colour ``a`` moved ``t`` (0..1) of the way to ``b``."""
    return _hex(*(x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))))


def luminance(colour: str) -> float:
    """Relative luminance 0..1 (WCAG), for ``contrast``."""
    def lin(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours, 1 (the same) to 21 (black on white)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _distance(a: str, b: str) -> float:
    """How different two colours look, roughly ("redmean": weighted RGB, 0 to about 765)."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    rm = (r1 + r2) / 2
    return ((2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2) ** 0.5


def _plain(colour: str) -> bool:
    """Grey, black or white (no colour to speak of): ``recolour`` leaves these as they are."""
    _, light, sat = colorsys.rgb_to_hls(*(v / 255 for v in _rgb(colour)))
    return sat < 0.12 or light < 0.03 or light > 0.985


def _derived(s: Dict[str, Any]) -> Dict[str, str]:
    """A scheme's roles plus the two made from them: "line" (rule lines on paper) and "muted" (small
    print on paper)."""
    out = {r: s[r] for r in ROLES}
    out["line"] = mix(s["paper"], s["ink"], 0.2)
    out["muted"] = mix(mix(s["ink"], s["paper"], 0.38), s["accent"], 0.18)
    return out


@lru_cache(maxsize=1)
def _anchors() -> Tuple[Tuple[str, str, int, str], ...]:
    """Every colour of the hosts' own looks with its role: (colour, role, note number or -1, the colour a
    shade matched to it is measured against)."""
    out: List[Tuple[str, str, int, str]] = []
    for base in BASE.values():
        out += [(base[r], r, -1, base[r]) for r in ROLES if not _plain(base[r])]
        out += [(c, "notes", i, c) for i, c in enumerate(base["notes"])]
    return tuple(out + [(c, role, -1, EXTRA_REF[role]) for c, role in EXTRA_ANCHORS.items()])


@lru_cache(maxsize=4096)
def swap(colour: str, key: str) -> str:
    """One "#rrggbb" colour of a host card as scheme ``key`` has it. The nearest anchor decides the role;
    the result is the scheme's colour of that role, moved by the same step in lightness and strength
    as ``colour`` is from its anchor (a note colour maps straight to the scheme's note of that number)."""
    s = get(key)
    colour = colour.lower()
    if s is None or colour in KEEP or _plain(colour):
        return colour
    near, role, note, ref = min(_anchors(), key=lambda a: _distance(colour, a[0]))
    if _distance(colour, near) > FAR:
        return colour
    if role == "notes":
        return s["notes"][note] if colour == near else colour
    target = _derived(s)[role]
    _, lc, sc = colorsys.rgb_to_hls(*(v / 255 for v in _rgb(colour)))
    _, la, sa = colorsys.rgb_to_hls(*(v / 255 for v in _rgb(ref)))
    ht, lt, st = colorsys.rgb_to_hls(*(v / 255 for v in _rgb(target)))
    light = max(0.0, min(1.0, lt + (lc - la)))
    sat = max(0.0, min(1.0, st * max(0.5, min(1.35, sc / sa)))) if sa > 0.05 else st
    return _hex(*(v * 255 for v in colorsys.hls_to_rgb(ht, light, sat)))


def recolour(page: str, key: str) -> str:
    """A finished host card page (flavrpromo/host_cards.py) in scheme ``key``'s colours; "" or an unknown
    key gives the page back unchanged. See the top of this file for what is and isn't touched."""
    if get(key) is None:
        return page

    def one(m: "re.Match[str]") -> str:
        h = m.group(1)
        if len(h) in (3, 4):                              # "#abc" / "#abcd" → six digits (+ two for the alpha)
            h = "".join(ch * 2 for ch in h)
        return swap("#" + h[:6], key) + h[6:]             # the see-through part, if any, stays

    return _STYLED.sub(lambda m: _HEX.sub(one, m.group(0)), page)


# ── tall pictures ──────────────────────────────────────────────────────
def theme(key: str, font: str) -> Optional[Dict[str, str]]:
    """Scheme ``key`` as a tall picture theme (the shape of flavrpromo/tall.py THEMES), None for the
    host's own. ``font`` is the host's lettering, which a scheme never changes."""
    s = get(key)
    if s is None:
        return None
    return {"bg": f"linear-gradient(160deg,{s['bg0']},{s['bg1']} 55%,{mix(s['bg0'], s['bg1'], 0.5)})",
            "fg": s["fg"], "accent": s["accent"], "gold": s["gold"], "paper": s["paper"], "ink": s["ink"], "font": font}


def bands(key: str) -> Optional[Tuple[str, ...]]:
    """The background colours a scheme's tall picture gives chunks next to a cut, taken in turn (the shape
    of flavrpromo/tall.py BANDS); None for the host's own."""
    s = get(key)
    return None if s is None else (mix(s["bg0"], s["bg1"], 0.5), s["bg2"], s["bg0"], s["bg1"])


def swatch(key: str, host: str = "") -> List[str]:
    """Five colours that show a scheme at a glance on the settings pages (background, band, accent,
    second accent, paper); ``key`` "" = ``host``'s own colours."""
    s = get(key) or BASE.get(host) or BASE["colette"]
    return [s["bg0"], s["bg2"], s["accent"], s["gold"], s["paper"]]


__all__ = ["ROLES", "BASE", "SCHEMES", "RANDOM", "MIX", "KEEP", "names", "get", "of", "mix", "luminance", "contrast",
           "swap", "recolour", "theme", "bands", "swatch"]
