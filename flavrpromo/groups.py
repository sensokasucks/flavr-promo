"""
Groups of people: FlaVR, Friends and Community are built in, more can be added with /group add (owner or
Manage Server). Each group has its own go-live channel, calendar post, recap and share text, all
keyed by the group's key (a short lower-case slug of its name, e.g. "Art Pals" → "art-pals").

Saved in the database (kv ``groups``): {key: {"name": shown name, "colour": "#rrggbb"}} for the
custom groups only; the built-in three are in DEFAULTS and can't be removed (their colour and name
can be changed). Removing a custom group moves its people to Friends.

Who reads it: everything that used to know only "flavr" / "friends": flavrpromo/bot.py (commands,
group autocomplete, go-live colours), calendar.py (board title), calendar_post.py (one post per
group), render.py (the board's colours; only FlaVR gets the logo and its four colours), share.py,
web.py (?group=). ``init(store)`` is called once at start by flavrpromo/__main__.py (and by tests);
before that only the defaults exist.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Dict[str, str]] = {
    "flavr": {"name": "FlaVR", "colour": "#f72ca2"},       # the logo's pink (it also uses lime, yellow, teal)
    "friends": {"name": "Friends", "colour": "#2ae0d4"},   # plain teal
    # streams members add from their self-promo posts (flavrpromo/promo.py); its board only posts once
    # /community report-channel (or /setup calendar-channel) picks a channel. People can be put in it
    # too (/friend group), and are then followed like anyone else.
    "community": {"name": "Community", "colour": "#9b6bff"},   # violet: not one of the FlaVR logo's colours
}
MAX_GROUPS = 20             # Discord autocomplete shows 25 choices; leave room
_store: Any = None


def init(store: Any) -> None:
    global _store
    _store = store


def _saved() -> Dict[str, Dict[str, str]]:
    return dict((_store.get("groups") or {}) if _store is not None else {})


def all_groups() -> Dict[str, Dict[str, Any]]:
    """{key: {name, colour, builtin}} in order: FlaVR, Friends, then custom ones by name."""
    saved = _saved()
    out: Dict[str, Dict[str, Any]] = {}
    for k, d in DEFAULTS.items():
        out[k] = {**d, **saved.get(k, {}), "builtin": True}
    for k in sorted((k for k in saved if k not in DEFAULTS), key=lambda k: saved[k].get("name", k).lower()):
        out[k] = {"name": saved[k].get("name") or k, "colour": saved[k].get("colour") or "#2ae0d4", "builtin": False}
    return out


def keys() -> List[str]:
    return list(all_groups())


def name(key: str) -> str:
    return all_groups().get(key, {}).get("name") or key.title()


def colour(key: str) -> str:
    """"#rrggbb" for this group (unknown → teal)."""
    return all_groups().get(key, {}).get("colour") or "#2ae0d4"


def colour_int(key: str) -> int:
    return int(colour(key).lstrip("#"), 16)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30]


def find(text: Optional[str], default: str = "flavr") -> Optional[str]:
    """A group's key from what someone typed (its key or its name, any case); ``default`` when blank,
    None when there's no such group."""
    if not (text or "").strip():
        return default
    g = all_groups()
    t = text.strip().lower()
    for k, info in g.items():
        if t in (k, info["name"].lower(), slug(info["name"])):
            return k
    return None


def parse_colour(text: str) -> Optional[str]:
    """"#ff8800" / "ff8800" / "f80" → "#ff8800" (None when it isn't a colour)."""
    t = (text or "").strip().lstrip("#").lower()
    if re.fullmatch(r"[0-9a-f]{3}", t):
        t = "".join(c * 2 for c in t)
    return "#" + t if re.fullmatch(r"[0-9a-f]{6}", t) else None


def add(display: str, col: str = "#2ae0d4") -> str:
    """Make a custom group; returns its key ("" when the name is empty, taken, or there are too many)."""
    key = slug(display)
    if not key or find(display, default="") or key in all_groups() or len(all_groups()) >= MAX_GROUPS:
        return ""
    saved = _saved()
    saved[key] = {"name": display.strip()[:40], "colour": col}
    _store.put("groups", saved)
    return key


def update(key: str, display: Optional[str] = None, col: Optional[str] = None) -> None:
    """Rename a group or change its colour (the built-in three too); the key never changes."""
    saved = _saved()
    cur = dict(saved.get(key, {}))
    if display:
        cur["name"] = display.strip()[:40]
    if col:
        cur["colour"] = col
    saved[key] = cur
    _store.put("groups", saved)


def remove(key: str) -> bool:
    """Delete a custom group (False for FlaVR / Friends or an unknown one)."""
    saved = _saved()
    if key in DEFAULTS or key not in saved:
        return False
    saved.pop(key)
    _store.put("groups", saved)
    return True


def title(key: str, recap: bool, label: str = "") -> str:
    """The board's heading: FlaVR keeps "THIS WEEK" (its logo says the rest). ``label`` "weekend" = the
    weekend review (flavrpromo/calendar.py REVIEWS; "week" reads like the old recap)."""
    what = "WEEKEND IN REVIEW" if label == "weekend" else "WEEK IN REVIEW"
    if key == "flavr":
        return what if recap else "THIS WEEK"
    n = name(key).upper()
    if recap:
        return f"{n}: {what}"
    if key == "community":
        return f"{n} STREAMS THIS WEEK"
    return f"THIS WEEK WITH {n}"


def heading(key: str, recap: bool, label: str = "") -> str:
    """Plain-text heading for posts and share text: "This week in FlaVR", "Art Pals week in review",
    "FlaVR weekend in review" (``label`` "weekend")."""
    n = name(key)
    if recap:
        return f"{n} {'weekend' if label == 'weekend' else 'week'} in review"
    if key == "community":
        return f"{n} streams this week"
    return f"This week in {n}" if key == "flavr" else f"This week with {n}"


__all__ = ["DEFAULTS", "init", "all_groups", "keys", "name", "colour", "colour_int", "find", "add", "update",
           "remove", "title", "heading", "parse_colour", "slug"]
