"""
The article editor: http://<this PC>:3871/settings/article (owner 2026-11-21: "a little article
editor ... so i can build articles section by section by having it regen sections, letting pick the
pictures being brought in (hosts), and grabbing new lines from kobold").

An X Article (flavrpromo/share.py ``article``, the same text /calendar/article shows) is cut into
sections: summary, who streamed, one per day, uploads, the hashtag line. The editor adds two host
sections around them, the host intro (Colette or Clark opens) and the host outro (their sign-off),
and the owner's own text sections. For each section the owner can:
  * leave it in or out, move it up or down;
  * Regen: a calendar section is built again from the latest calendar (new streams, VODs, titles);
    a host section gets its template lines shuffled and, with KoboldCpp set up, new ✨ lines asked
    for in the background (flavrpromo/host_picker.py ``start_ai``, only that section's slots);
  * "+ Add a tall picture": a tall section built from chunks (header, host moment, stream, stats, a
    day's pictures ...), each set with menus on its own builder page (flavrpromo/tall_page.py, picture
    drawn by flavrpromo/tall.py, at most 1600 x 2133 so X shows it whole); drafts keep them in p["talls"];
  * ✨ beside one line: KoboldCpp rewrites just that line (``redo_line``, one request), in place;
  * host sections: pick one of the lines (or type their own) and the picture: the opener card (with
    the regular / chibi switch: which one is big and which one peeks), the desk card (regular or
    chibi), any one of the host's pictures on its own, or none. Card pictures are drawn with
    Chromium like the review cards (flavrpromo/host_cards.py).
Day pictures come in the host's look by default (owner 2026-11-21: the board-look day pictures
"dont follow the color scheme and fancy format the hosts come in with"): host_cards.day draws
Colette's taped polaroids or Clark's filed photos, with the host's line about that day (picked from
hosts.day_line, editable per day, ↻ for another). "Board look" at the top switches back to
render.day_card (/calendar/day.png). In the host's look a day picture has a layout
(host_cards.DAY_LAYOUTS: pinned wall, timeline, spotlight; owner 2026-11-21 "one or two more
alternative layouts so i can pick from them"): one for the whole article at the top, and each day
can pick its own. Drafts: p["day_look"] "host" / "board", p["day_layout"] the article's layout,
p["day_layouts"] {day: layout, "" = the article's}.

Every line (round 2, owner 2026-11-21: "a better way to regen the open/close cards ... kobold regen
lines in each section so i dont have to scroll to the top and get forced to change all the lines")
is its own slot with its own buttons: ↻ shuffles in another template line for just that slot, ✨ asks
KoboldCpp for new lines for just that slot (one request, the page waits for it) and picks the first
one; the other slots keep their picks. A day picture's line is slot "day<N>" in p["candidates"]
(its template facts in p["day_facts"][N], the KoboldCpp facts sentence in p["day_text"][N]).
The cover (/settings/article/cover) comes in the host's look too (host_cards.cover; p["cover_look"]
"host" / "board", p["cover_figure"] which picture stands on it).
"Open the finished article" shows it on the copy page (flavrpromo/web.py ``article_html``): the host
pictures sit in Save blocks like the day pictures (X can't fetch pictures from the home network).

Drafts live in kv article_draft.<group>.<which> (which: week / weekend for the reviews, week0 /
week-1 / week1 for this / last / next week) until "Start over". A draft has the same fields as a
pending review on the picker page (host, facts, notes, candidates, picks, ai, opener_kind, desk_kind),
so host_picker's card drawing and KoboldCpp writing work on it unchanged, plus sections, pics,
texts, heading and pose. No password, like the rest of port 3871 (home network only).
Who calls it: flavrpromo/__main__.py (``add_routes`` on the web server).
"""

from __future__ import annotations

import html
import random
import re
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from aiohttp import web

from . import groups, host_cards, host_picker, hosts, kobold, tall
from .render import COVER_H, COVER_W, clock
from .settings_page import _e, frame
from .web import article_html, article_query, build_article, get_week

PREFIX = "article_draft."
# which article: (key, label shown, review label, week offset)
WHICH: Tuple[Tuple[str, str, str, int], ...] = (
    ("week", "Week review (Mon to Thu)", "week", 0), ("weekend", "Weekend review (Fri to Sun)", "weekend", 0),
    ("week0", "This week", "", 0), ("week-1", "Last week (the full recap)", "", -1), ("week1", "Next week", "", 1))
WEEK_HEADINGS = {0: "This Week", -1: "Last Week", 1: "Next Week"}
HOST_SECTIONS = {"intro": "Host intro", "outro": "Host outro"}
# a host section's slots (host_picker / hosts.review_candidates names) and the KoboldCpp slots it asks for
SLOTS = {"intro": ("opener", "note"), "outro": ("desk_highlight", "desk_nudge", "desk_signoff")}
# picture choices for a host section: the two cards, or one of the host's pictures on its own
# ("pic:<kind>", hosts.KINDS; the prefix keeps the desk card apart from the plain desk picture)
CARD_PICS = {"opener": "Opener card", "desk": "Desk card", "none": "No picture"}
MAX_TEXT = 3000             # characters in one of the owner's own text sections


def draft_key(group: str, which: str) -> str:
    return f"{PREFIX}{group}.{which}"


def _which(which: str) -> Tuple[str, str, str, int]:
    return next((w for w in WHICH if w[0] == which), WHICH[0])


def _slots_of(sec: str, p: Dict[str, Any]) -> List[str]:
    return [s for s in (p.get("candidates") or {}) if any(s.startswith(x) for x in SLOTS[sec])]


async def _article(poster: Any, p: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    """The draft's week and its share.article (with the owner's tags and handles)."""
    week = await get_week(poster, p["group"], p.get("label") or "", int(p.get("off") or 0))
    return week, build_article(poster, week, article_query(p["group"], p.get("label") or "", int(p.get("off") or 0)))


def _host_lines(p: Dict[str, Any], shuffle: bool = False, only: Tuple[str, ...] = ()) -> None:
    """(Re)fill the draft's template lines for its host; ``shuffle`` = Regen (a new first pick);
    ``only`` limits it to those slot starts (one section's slots). The owner's picks in them go."""
    fresh = hosts.review_candidates(p["host"], p["facts"])
    for slot, lines in fresh.items():
        if only and not any(slot.startswith(o) for o in only):
            continue
        if shuffle:
            lines = random.sample(lines, len(lines))
        p["candidates"][slot] = lines
        (p.get("picks") or {}).pop(slot, None)


async def new_draft(poster: Any, group: str, which: str, host: str = "") -> Dict[str, Any]:
    """A fresh draft: the article's sections between the host intro and outro, all in."""
    _, _name, label, off = _which(which)
    week, a = await _article(poster, {"group": group, "label": label, "off": off})
    only = str(poster.store.get("hosts_only") or "")
    key = host if host in hosts.HOSTS else (only if only in hosts.HOSTS else random.choice(list(hosts.HOSTS)))
    f = hosts.facts(poster.store, week)
    p = {"group": group, "which": which, "label": label, "off": off, "host": key, "facts": f,
         "notes": hosts.notes(f), "candidates": {}, "picks": {}, "ai": [], "built_at": time.time(),
         "heading": "" if label else WEEK_HEADINGS.get(off, "This Week"), "pose": "",
         "opener_kind": "pose", "desk_kind": "desk", "pics": {"intro": "opener", "outro": "desk"}, "texts": {},
         "sections": [{"id": "intro", "title": HOST_SECTIONS["intro"], "on": True}]
         + [dict(s, on=True) for s in a["sections"]]
         + [{"id": "outro", "title": HOST_SECTIONS["outro"], "on": True}]}
    p["day_look"], p["cover_look"], p["cover_figure"] = "host", "host", "happy"
    p["seed"], p["pins"] = random.randrange(1_000_000), {}
    _host_lines(p)
    _day_lines(p, week)
    return p


def _day_lines(p: Dict[str, Any], week: Any, only: str = "") -> None:
    """The host's line for each day picture (hosts.day_line with that day's first stream); ``only``:
    just that day's index (its Regen), else every day (a new draft, a new host, Regen all)."""
    for i, tiles in enumerate(week.days):
        if (only and str(i) != only) or not tiles:
            continue
        first = min(tiles, key=lambda t: t.at)
        date = week.start + timedelta(days=i)
        # hosts.day_line's own blanks, but "on Tuesday" for {when_lower} (its day posts say "today")
        facts = {"when": f"{date:%A}", "when_lower": f"on {date:%A}", "count": len(tiles),
                 "first_name": first.name, "first_time": clock(first.at, week.tz)}
        p.setdefault("day_facts", {})[str(i)] = facts
        # who, with the game when known ("Lulu: Valheim"), for KoboldCpp's day lines (owner 2026-11-21)
        names = ", ".join(dict.fromkeys(f"{t.name}: {t.game}" if t.game else t.name
                                        for t in sorted(tiles, key=lambda t: t.at)))
        p.setdefault("day_text", {})[str(i)] = (f"{date:%A}: {len(tiles)} stream{'' if len(tiles) == 1 else 's'} "
                                                f"({names}), {first.name} first at {facts['first_time']}.")
        slot = f"day{i}"
        p.setdefault("candidates", {})[slot] = random.sample(_day_templates(p, i), len(_day_templates(p, i)))
        (p.get("picks") or {}).pop(slot, None)


def _day_templates(p: Dict[str, Any], i: int) -> List[str]:
    """Every template line for day ``i``'s picture in the draft host's voice."""
    f = (p.get("day_facts") or {}).get(str(i)) or {}
    return hosts.lines(p["host"], "day_one" if f.get("count") == 1 else "day_many", f) or hosts.lines(p["host"], "day_many", f)


def migrate(p: Dict[str, Any]) -> Dict[str, Any]:
    """A draft from before per-slot lines (p["day_lines"] {N: line}) → candidates day<N>."""
    for k, v in (p.pop("day_lines", None) or {}).items():
        p.setdefault("candidates", {}).setdefault(f"day{k}", [v] if v else [])
    p.setdefault("cover_look", "host")
    p.setdefault("cover_figure", "happy")
    p.setdefault("seed", int(p.get("built_at") or 0))    # which pool picture each kind shows (hosts.look)
    p.setdefault("pins", {})                              # {picture kind: pool picture id} chosen by hand
    p.setdefault("talls", {})                             # {section id "tall1": {"chunks": [...]}} (flavrpromo/tall.py)
    return p


def _looks(p: Dict[str, Any]) -> Any:
    """``with _looks(p):`` the draft's picture choices (seed + pins) apply to every host picture drawn
    inside it, so a draft keeps its pictures until the owner re-rolls or pins one (flavrpromo/hosts.py ``look``)."""
    return hosts.look(p.get("seed"), p.get("pins"))


def slot_section(slot: str) -> str:
    """Which section a slot's lines belong to (the page jumps back there after its buttons)."""
    if slot.startswith("day"):
        return slot
    return "intro" if slot.startswith(("opener", "note")) else "outro"


def reroll(p: Dict[str, Any], slot: str) -> str:
    """↻ for one slot: its template lines shuffled, a different one picked. Returns the page note."""
    if slot.startswith("day"):
        fresh = _day_templates(p, int(slot[3:]))
    else:
        fresh = hosts.review_candidates(p["host"], p["facts"]).get(slot) or []
    if not fresh:
        return "No other template lines for that one."
    cur = host_picker.chosen(p, slot)
    ai = [x for x in (p.get("candidates") or {}).get(slot) or [] if x in set(p.get("ai") or [])]
    order = random.sample(fresh, len(fresh))
    order.sort(key=lambda x: x == cur)              # the current line goes last, so something new is picked
    p["candidates"][slot] = order + [x for x in ai if x not in order]
    p.setdefault("picks", {})[slot] = order[0]
    return "Another line." if order[0] != cur else "That's the only template line for it."


def _ask_of(p: Dict[str, Any], slot: str) -> Tuple[str, str]:
    """(ask, facts sentence) KoboldCpp gets for one slot: a day picture uses that day's facts, a note
    names its highlight, the rest the review's facts."""
    a = kobold.asks()
    if slot.startswith("day"):
        return a["day"], (p.get("day_text") or {}).get(slot[3:], "")
    facts = kobold.facts_text(p.get("facts") or {})
    if slot.startswith("note"):
        n = (p.get("notes") or [{}] * 4)[int(slot[4:])]
        return a["note"].replace("{note}", f"{n.get('label', '').lower()}: {n.get('value', '')}"), facts
    return a.get(slot, a["opener"]), facts


async def ask_slot(poster: Any, p: Dict[str, Any], slot: str) -> str:
    """✨ for one slot: per_slot fresh lines from KoboldCpp, one request each (a request = one whole
    line, a few sentences are fine; owner 2026-11-21). The page waits. They replace the slot's
    earlier ✨ lines (the template lines stay below), and the first is picked."""
    kob = getattr(poster, "kobold", None)
    if kob is None:
        return "KoboldCpp isn't set up (Settings → KoboldCpp)."
    ask, facts = _ask_of(p, slot)
    new = await kob.lines(p["host"], ask, host_picker.heading_of(p, "review"), facts)
    if new is None:
        return "KoboldCpp couldn't be reached."
    if not new:
        return f"KoboldCpp answered, but with no usable line. Try ✨ again. Its answer: {kob.last_raw[:200]}"
    ai = set(p.get("ai") or [])
    kept = [x for x in (p.get("candidates") or {}).get(slot) or [] if x not in ai and x not in new]
    p["candidates"][slot] = new + kept
    p["ai"] = [x for x in p.get("ai") or [] if x in sum((p["candidates"].values()), [])] + new
    p.setdefault("picks", {})[slot] = new[0]
    return f"✨ {len(new)} new line{'' if len(new) == 1 else 's'} from KoboldCpp (the first one is picked)."


async def redo_line(poster: Any, p: Dict[str, Any], slot: str, i: int) -> str:
    """The ✨ next to one line: KoboldCpp rewrites just that one (one request); it stays in its place,
    and stays picked if it was."""
    kob = getattr(poster, "kobold", None)
    cands = (p.get("candidates") or {}).get(slot) or []
    if kob is None or not 0 <= i < len(cands):
        return "KoboldCpp isn't set up (Settings → KoboldCpp)." if kob is None else "That line is gone."
    ask, facts = _ask_of(p, slot)
    new = await kob.line(p["host"], ask, host_picker.heading_of(p, "review"), facts)
    if new is None:
        return "KoboldCpp couldn't be reached."
    if not new or new in cands:
        return f"KoboldCpp answered, but with no new usable line. Try again. Its answer: {kob.last_raw[:200]}"
    old = cands[i]
    cands[i] = new
    p["ai"] = [x for x in p.get("ai") or [] if x != old] + [new]
    if host_picker.chosen(p, slot) == old:
        p.setdefault("picks", {})[slot] = new
    return "✨ Rewrote that line."


def _refresh(p: Dict[str, Any], a: Dict[str, Any], only: str = "") -> str:
    """Put a fresh share.article's sections in the draft: just ``only`` (one section's Regen) or all
    (new days join before the outro, vanished ones go, the owner's order and in/out stay)."""
    fresh = {s["id"]: s for s in a["sections"]}
    if only:
        sec = next((s for s in p["sections"] if s["id"] == only), None)
        if sec is None:
            return "That section isn't in this draft."
        if only not in fresh:
            return f"“{sec['title']}” isn't in the article any more (nothing there now); left as it was."
        sec.update(title=fresh[only]["title"], html=fresh[only]["html"])
        return f"Rebuilt “{sec['title']}” from the calendar."
    mine = {"intro", "outro"} | set(p.get("texts") or {}) | set(p.get("talls") or {})
    out = []
    for s in p["sections"]:
        if s["id"] in mine:
            out.append(s)
        elif s["id"] in fresh:
            out.append(dict(s, title=fresh[s["id"]]["title"], html=fresh[s["id"]]["html"]))
    have = {s["id"] for s in out}
    new = [dict(s, on=True) for s in a["sections"] if s["id"] not in have]
    at = next((i for i, s in enumerate(out) if s["id"] == "outro"), len(out))
    p["sections"] = out[:at] + new + out[at:]
    p["built_at"] = time.time()
    return "Rebuilt every calendar section." + (f" New: {', '.join(s['title'] for s in new)}." if new else "")


# ── what each section looks like in the article ────────────────────────────
def _pic_url(dkey: str, sec: str, p: Dict[str, Any]) -> str:
    return f"/settings/article/picture?d={quote(dkey)}&sec={sec}&t={int(p.get('saved_at') or 0)}"


def _pic_name(p: Dict[str, Any], sec: str) -> str:
    return f"{sec}-{p['host']}-{(p.get('pics') or {}).get(sec, 'none').replace('pic:', '')}.png"


def section_html(dkey: str, p: Dict[str, Any], s: Dict[str, Any]) -> str:
    """One section's HTML in the finished article (calendar sections: their saved snapshot)."""
    sid = s["id"]
    if sid in HOST_SECTIONS:
        h = hosts.HOSTS[p["host"]]
        e = html.escape
        pic = (p.get("pics") or {}).get(sid, "none")
        block = ""
        if pic != "none":
            url = e(_pic_url(dkey, sid, p), quote=True)
            block = (f'<div class="nocopy"><img src="{url}" alt="{e(h["name"])}">'
                     f'<p>{e(h["name"])} · <a href="{url}" download="{_pic_name(p, sid)}">Save</a> · '
                     "put it here with X's picture button</p></div>")
        who = f"<b>{e(h['emoji'])} {e(h['name'])}:</b> "
        if sid == "intro":
            line = host_picker.chosen(p, "opener")
            return block + (f"<p>{who}{e(line)}</p>" if line else "")
        rows = [host_picker.chosen(p, x) for x in SLOTS["outro"]]
        rows = [x for x in rows if x]
        return block + "".join(f"<p>{who if i == 0 else ''}{'<i>' if i == len(rows) - 1 and i else ''}{e(x)}"
                               f"{'</i>' if i == len(rows) - 1 and i else ''}</p>" for i, x in enumerate(rows))
    if sid.startswith("day") and p.get("day_look", "host") == "host":
        # the snapshot's board-look day picture (/calendar/day.png...day=N) → the host's look
        url = f"/settings/article/day?d={quote(dkey)}&day={sid[3:]}&t={int(p.get('saved_at') or 0)}"
        return re.sub(r'/calendar/day\.png[^"]*?day=\d', html.escape(url, quote=True), s.get("html") or "")
    if sid in (p.get("talls") or {}):
        url = html.escape(f"/settings/tall/picture?d={quote(dkey)}&t={sid}&v={int(p.get('saved_at') or 0)}", quote=True)
        return (f'<div class="nocopy"><img src="{url}" alt="tall picture">'
                f'<p>Tall picture · <a href="{url}" download="{sid}.png">Save</a> · put it here with X\'s picture button</p></div>')
    if sid in (p.get("texts") or {}):
        paras = [x.strip() for x in str(p["texts"][sid]).split("\n\n") if x.strip()]
        return "".join(f"<p>{html.escape(x).replace(chr(10), '<br>')}</p>" for x in paras)
    return s.get("html") or ""


def finished(dkey: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """The draft as share.article's shape (title, html) for the copy page: the sections that are in."""
    parts = [section_html(dkey, p, s) for s in p["sections"] if s.get("on")]
    title = p.get("title") or ""
    return {"title": title, "html": "\n".join(x for x in parts if x), "pictures": []}


# ── the page ───────────────────────────────────────────────────────────────
def _picker(store: Any, group: str, which: str) -> str:
    """The "which article" form at the top."""
    gopts = "".join(f'<option value="{_e(g)}"{" selected" if g == group else ""}>{_e(groups.name(g))}</option>'
                    for g in groups.keys())
    wopts = "".join(f'<option value="{w}"{" selected" if w == which else ""}>{_e(t)}</option>' for w, t, _, _ in WHICH)
    return (f'<form method=get action=/settings/article class=row><label>Group <select name=group>{gopts}</select></label>'
            f'<label>Article <select name=which>{wopts}</select></label><button>Open</button></form>')


def _line_choices(p: Dict[str, Any], slot: str, title: str, ai_on: bool = False, none: str = "") -> str:
    """One slot's lines as radio buttons, "your own", and its own ↻ / ✨ buttons in the legend.
    ``none``: a label for a "no line" choice (day pictures: no bubble)."""
    cands = (p.get("candidates") or {}).get(slot) or []
    cur = host_picker.chosen(p, slot)
    ai = set(p.get("ai") or [])
    # a ✨ on every line rewrites just that one (redo_line; owner 2026-11-21: "regenerate them individually")
    redo = (lambda i: f' <button name=action value="redo:{slot}:{i}" class="alt mini ask" title="Rewrite this line '
            f'with KoboldCpp">✨</button>') if ai_on else (lambda i: "")
    opts = "".join(f'<label><input type=radio name="{slot}" value="{_e(c)}"{" checked" if c == cur else ""}> '
                   f'{"✨ " if c in ai else ""}{_e(c)}{redo(i)}</label>' for i, c in enumerate(cands))
    custom = cur if cur and cur not in cands else ""
    opts += (f'<label><input type=radio name="{slot}" value="__custom"{" checked" if custom else ""}> your own: '
             f'<input name="{slot}__text" value="{_e(custom)}" maxlength={kobold.MAX_CHARS}></label>')
    if none:
        off = slot in (p.get("picks") or {}) and not p["picks"][slot]
        opts += f'<label><input type=radio name="{slot}" value="__none"{" checked" if off else ""}> {_e(none)}</label>'
    btns = (f' <button name=action value="reroll:{slot}" class="alt mini" title="Another template line">↻</button>'
            + (f' <button name=action value="ask:{slot}" class="alt mini ask" title="New lines from KoboldCpp">✨</button>'
               if ai_on else ""))
    return f"<fieldset><legend>{_e(title)}{btns}</legend>{opts}</fieldset>"


def _host_controls(dkey: str, p: Dict[str, Any], sid: str, ai_on: bool) -> str:
    rows = []
    for slot in _slots_of(sid, p):
        title = slot.replace("_", " ")
        if slot.startswith("note"):
            n = (p.get("notes") or [])[int(slot[4:])] if int(slot[4:]) < len(p.get("notes") or []) else {}
            title = f"opener card note: {n.get('label', '').lower()} ({n.get('value', '')})"
        rows.append(_line_choices(p, slot, title, ai_on))
    cur = (p.get("pics") or {}).get(sid, "none")
    pics = list(CARD_PICS.items()) + [(f"pic:{k}", f"Just the picture: {k.replace('_', ' ')}")
                                      for k, v in hosts.pictures(p["host"]).items() if v]
    sel = "".join(f'<option value="{v}"{" selected" if v == cur else ""}>{_e(n)}</option>' for v, n in pics)
    swap = ""
    if cur == "opener":
        swap = host_picker._switch(p, "opener_kind", "opener card: which one is big",
                                   (("pose", "regular big, chibi peeks"), ("chibi", "chibi big, regular peeks")))
        pose = p.get("pose") or ""
        swap += ("<label>Pose <select name=pose>"
                 + "".join(f'<option value="{v}"{" selected" if v == pose else ""}>{_e(n)}</option>'
                           for v, n in (("", "fits the week (auto)"), ("happy", "happy"), ("pointing", "pointing"),
                                        ("sleepy", "sleepy")))
                 + "</select></label>")
    elif cur == "desk":
        swap = host_picker._switch(p, "desk_kind", "desk card picture", (("desk", "regular"), ("chibi_desk", "chibi")))
    ai = (f'<button name=action value="ai:{sid}" class=alt>✨ New lines for every slot here (in the background)</button>'
          if ai_on else "")
    return (f'<div class=two><div>{"".join(rows)}</div><div><label>Picture <select name="pic_{sid}">{sel}</select>'
            f'</label>{swap}<p>{ai}</p></div></div>')


def page(poster: Any, dkey: str, p: Dict[str, Any], saved: str = "") -> str:
    ai_on = getattr(poster, "kobold", None) is not None
    secs = []
    last = len(p["sections"]) - 1
    for i, s in enumerate(p["sections"]):
        sid = s["id"]
        kind = ("host" if sid in HOST_SECTIONS else "text" if sid in (p.get("texts") or {})
                else "tall" if sid in (p.get("talls") or {}) else "calendar")
        buttons = (f'<button name=action value="up:{sid}" class=alt{" disabled" if i == 0 else ""}>↑</button> '
                   f'<button name=action value="down:{sid}" class=alt{" disabled" if i == last else ""}>↓</button> ')
        if kind == "calendar":
            buttons += f'<button name=action value="regen:{sid}">↻ Regen from the calendar</button>'
            line = ""
            if sid.startswith("day") and p.get("day_look", "host") == "host":
                mine = (p.get("day_layouts") or {}).get(sid[3:], "")
                lay = "".join(f'<option value="{v}"{" selected" if v == mine else ""}>{_e(n)}</option>'
                              for v, n in [("", "Layout: same as the article")] + list(host_cards.DAY_LAYOUTS.items()))
                line = (f'<label>Layout <select name="daylayout_{sid[3:]}">{lay}</select></label>'
                        + _line_choices(p, sid, f'{hosts.HOSTS[p["host"]]["name"]}\'s line on this picture', ai_on,
                                        none="no line (no bubble)"))
            body = line + f'<div class=box>{section_html(dkey, p, s)}</div>'
        elif kind == "host":
            buttons += f'<button name=action value="regen:{sid}">↻ New lines</button>'
            body = _host_controls(dkey, p, sid, ai_on) + f'<div class=box>{section_html(dkey, p, s)}</div>'
        elif kind == "tall":
            n = len(p["talls"][sid]["chunks"])
            buttons += (f'<button name=action value="remove:{sid}" class=alt>Remove</button>')
            body = (f'<p><a class=btn href="/settings/tall?d={quote(dkey)}&t={sid}">🧱 Edit the chunks ({n}, '
                    f'{tall.total(p["talls"][sid]["chunks"])} px tall)</a></p><div class=box>{section_html(dkey, p, s)}</div>')
        else:
            buttons += f'<button name=action value="remove:{sid}" class=alt>Remove</button>'
            body = (f'<textarea name="text_{sid}" rows=4 maxlength={MAX_TEXT} placeholder="Your own words. '
                    f'A blank line starts a new paragraph.">{_e(p["texts"][sid])}</textarea>')
        secs.append(f'<section class="sec{"" if s.get("on") else " off"}" id="s-{sid}"><div class=head>'
                    f'<label><input type=checkbox name="on_{sid}" value=1{" checked" if s.get("on") else ""}> '
                    f'<b>{_e(s["title"])}</b> <small class=kind>{kind}</small></label><span>{buttons}</span></div>{body}</section>')
    hopts = "".join(f'<option value="{k}"{" selected" if k == p["host"] else ""}>{_e(x["emoji"])} {_e(x["name"])}</option>'
                    for k, x in hosts.HOSTS.items())
    ai_note = (f'<p class=ai>✨ KoboldCpp: {_e(host_picker.AI_STATES.get(p.get("ai_state") or "", "ready"))}</p>'
               + (f'<pre class=help style="white-space:pre-wrap">{_e(p.get("ai_raw"))}</pre>'
                  if p.get("ai_state") == "nolines" and p.get("ai_raw") else "")
               if ai_on else '<p class=help>Set a KoboldCpp address on <a href="/settings#kobold">Settings</a> for ✨ lines.</p>')
    built = time.strftime("%H:%M", time.localtime(float(p.get("built_at") or 0)))
    look = p.get("day_look", "host")
    lopts = "".join(f'<option value="{v}"{" selected" if v == look else ""}>{_e(n)}</option>'
                    for v, n in (("host", "In the host's look (with their line)"), ("board", "Board look")))
    alls = "".join(f'<option value="{v}"{" selected" if v == p.get("day_layout", "wall") else ""}>{_e(n)}</option>'
                   for v, n in host_cards.DAY_LAYOUTS.items())
    cov = p.get("cover_look", "host")
    copts = "".join(f'<option value="{v}"{" selected" if v == cov else ""}>{_e(n)}</option>'
                    for v, n in (("host", "In the host's look"), ("board", "Board look")))
    fig = p.get("cover_figure", "happy")
    fopts = "".join(f'<option value="{k}"{" selected" if k == fig else ""}>{_e(k.replace("_", " "))}</option>'
                    for k, v in hosts.pictures(p["host"]).items() if v and k not in ("head", "chibi_head"))
    cover = (f'<div class=covrow><p>Cover <select name=cover_look>{copts}</select> '
             + (f'<select name=cover_figure>{fopts}</select> ' if cov == "host" else "")
             + f'<button name=action value=save class=alt>Apply</button></p>'
             f'<img class=cov src="{_e(_cover_url(dkey, p))}" alt="cover" loading=lazy></div>')
    head = (f'<p>Host <select name=host>{hopts}</select> <button name=action value=host class=alt>Change host</button> '
            f'<small>Changing the host gives new lines for both host sections and the day pictures.</small></p>'
            f'<p>Day pictures <select name=day_look>{lopts}</select> <select name=day_layout>{alls}</select> <button name=action value=save class=alt>Apply</button></p>{cover}{ai_note}'
            f'{_variation_picker(p)}'
            f'<p class=help>Calendar sections are as of {built}. <button name=action value=regen_all class=alt>↻ Regen every '
            f'calendar section</button> <button name=action value=add_text class=alt>+ Add a text section</button> '
            f'<button name=action value=reset class=alt>Start over</button></p>')
    view = f'/settings/article/view?d={quote(dkey)}'
    body = (_picker(poster.store, p["group"], p["which"])
            + f'<form method=post action=/settings/article><input type=hidden name=d value="{_e(dkey)}">{head}'
            + "".join(secs)
            + f'<p class=bar><button name=action value=save>Save</button> '
              f'<a class=btn href="{view}" target=_blank>Open the finished article ↗</a></p></form>')
    style = (".variations{border:1px solid #3d2a3b;border-radius:10px;padding:6px 12px;margin:10px 0}"
             ".varrow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0}.varrow b{width:110px}"
             ".var{display:inline-flex;align-items:center;gap:3px;margin:0}.var img{width:56px;height:56px;object-fit:contain;"
             "background:#0e0f14;border-radius:6px}"
             ".row{display:flex;gap:12px;flex-wrap:wrap;align-items:end}.row label{margin:0}.row select{width:auto}"
             ".sec{border:1px solid #555;border-radius:10px;padding:10px 14px;margin:12px 0;border-bottom:1px solid #555}"
             ".sec.off{opacity:.55}.head{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center}"
             ".head label{margin:0}.kind{display:inline;color:#889}.box{background:#fff;color:#111;border-radius:8px;"
             "padding:10px 16px;margin-top:8px}.box a{color:#1d9bf0}.box img{max-width:100%;border-radius:6px}"
             ".box .nocopy{font-size:13px;color:#667}.two{display:grid;grid-template-columns:3fr 2fr;gap:14px}"
             "@media(max-width:800px){.two{grid-template-columns:1fr}}.hostpic{width:100%;border-radius:8px;margin-top:8px;"
             "background:#0e0f14}fieldset{border:1px solid #555;border-radius:8px;margin:8px 0}"
             "fieldset label{margin:4px 0}.ai{color:#b7ef33}a.btn{background:#2a2d3a;color:#fff;padding:8px 12px;"
             "border-radius:8px;text-decoration:none;font-weight:bold}.bar{position:sticky;bottom:0;background:#1b1018;"
             "padding:10px 0;margin:0}button[disabled]{opacity:.35}legend .mini{padding:2px 9px;margin-left:4px;font-size:14px}"
             ".cov{width:min(600px,100%);border-radius:8px;display:block}")
    # ✨ waits for KoboldCpp (one request): show that it's working instead of a page that looks stuck
    body += ("<script>document.querySelector('form[method=post]').addEventListener('submit',e=>{const b=e.submitter;"
             "if(b&&/^(ask|ai):/.test(b.value)){b.textContent='✨ writing… (up to a minute)';"
             "setTimeout(()=>document.querySelectorAll('button').forEach(x=>x.disabled=true),0)}});</script>")
    return frame("Article editor", "📰 Article editor", body, saved, style)


def _variation_picker(p: Dict[str, Any]) -> str:
    """The "Picture variations" box: for each picture kind of the host with a pool (more than one
    picture, Hosts > Pictures), small thumbnails to pin one by hand, "automatic" = the draft's seed
    picks, and 🎲 to re-roll the automatic ones. Empty when no kind has a pool."""
    rows = []
    for kind in hosts.POOLED:
        opts = hosts.variants(p["host"], kind)
        if len(opts) < 2:
            continue
        cur = (p.get("pins") or {}).get(kind, "")
        cells = [f'<label class=var><input type=radio name="pin_{kind}" value=""{" checked" if not cur else ""}> '
                 f'<span>auto</span></label>']
        for vid, _ in opts:
            img = (f'<img src="/settings/picture/{p["host"]}/{kind}?v={vid}" loading=lazy alt="">'
                   if hosts.exact(p["host"], kind, vid) else "")
            cells.append(f'<label class=var><input type=radio name="pin_{kind}" value="{vid}"'
                         f'{" checked" if cur == vid else ""}>{img}</label>')
        rows.append(f'<div class=varrow><b>{_e(kind.replace("_", " "))}</b> {"".join(cells)}</div>')
    if not rows:
        return ""
    return ('<div class=variations><p><b>🖼️ Picture variations</b> <small>auto = the system picks one of the '
            'pictures from the pool and keeps it for this draft</small> '
            '<button name=action value=reroll_pics class=alt>🎲 Re-roll the automatic ones</button> '
            '<button name=action value=save class=alt>Apply picks</button></p>' + "".join(rows) + '</div>')


def _cover_url(dkey: str, p: Dict[str, Any]) -> str:
    """The cover picture for the page and the copy page: the host's look, or the board's."""
    if p.get("cover_look", "host") == "host":
        return f"/settings/article/cover?d={quote(dkey)}&t={int(p.get('saved_at') or 0)}"
    return "/calendar/cover.png" + article_query(p["group"], p.get("label") or "", int(p.get("off") or 0))


def _save_form(p: Dict[str, Any], form: Any) -> None:
    """Every field of the editor form into the draft (each button saves first, then acts)."""
    for s in p["sections"]:
        s["on"] = bool(form.get(f"on_{s['id']}"))
    for sid in HOST_SECTIONS:
        v = str(form.get(f"pic_{sid}") or "")
        if v in CARD_PICS or (v.startswith("pic:") and v[4:] in hosts.KINDS):
            p.setdefault("pics", {})[sid] = v
    picks = dict(p.get("picks") or {})
    for slot in p.get("candidates") or {}:
        if f"{slot}" not in form:
            continue
        v = str(form.get(slot) or "")
        if v == "__none":
            picks[slot] = ""                    # a day picture without a bubble
            continue
        if v == "__custom":
            v = " ".join(str(form.get(f"{slot}__text") or "").split())[:kobold.MAX_CHARS]
        if v:
            picks[slot] = v
        else:
            picks.pop(slot, None)
    p["picks"] = picks
    for kind in hosts.POOLED:                       # the pool pictures pinned by hand (variation picker)
        if f"pin_{kind}" in form:
            v = str(form.get(f"pin_{kind}") or "")
            if v and v in [vid for vid, _ in hosts.variants(p["host"], kind)]:
                p.setdefault("pins", {})[kind] = v
            else:
                p.setdefault("pins", {}).pop(kind, None)       # "" = automatic (the draft's seed)
    if str(form.get("cover_look") or "") in ("host", "board"):
        p["cover_look"] = str(form.get("cover_look"))
    if str(form.get("cover_figure") or "") in hosts.KINDS:
        p["cover_figure"] = str(form.get("cover_figure"))
    if str(form.get("opener_kind") or "") in ("pose", "chibi"):
        p["opener_kind"] = str(form.get("opener_kind"))
    if str(form.get("desk_kind") or "") in ("desk", "chibi_desk"):
        p["desk_kind"] = str(form.get("desk_kind"))
    if "pose" in form:
        v = str(form.get("pose") or "")
        p["pose"] = v if v in hosts.POSES else ""
    if str(form.get("day_look") or "") in ("host", "board"):
        p["day_look"] = str(form.get("day_look"))
    if str(form.get("day_layout") or "") in host_cards.DAY_LAYOUTS:
        p["day_layout"] = str(form.get("day_layout"))
    for i in range(7):
        v = str(form.get(f"daylayout_{i}") or "")
        if f"daylayout_{i}" in form and (v in host_cards.DAY_LAYOUTS or not v):
            p.setdefault("day_layouts", {})[str(i)] = v
    for sid in list(p.get("texts") or {}):
        if f"text_{sid}" in form:
            p["texts"][sid] = str(form.get(f"text_{sid}") or "").replace("\r\n", "\n").strip()[:MAX_TEXT]
    p["saved_at"] = time.time()


def _move(p: Dict[str, Any], sid: str, step: int) -> None:
    secs = p["sections"]
    i = next((n for n, s in enumerate(secs) if s["id"] == sid), None)
    if i is not None and 0 <= i + step < len(secs):
        secs[i], secs[i + step] = secs[i + step], secs[i]


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store

    async def _load(group: str, which: str) -> Tuple[str, Dict[str, Any]]:
        dkey = draft_key(group, which)
        p = store.get(dkey)
        if not p:
            p = await new_draft(poster, group, which)
            store.put(dkey, p)
        return dkey, migrate(p)

    async def get(request: web.Request) -> web.Response:
        group = groups.find(request.query.get("group", "")) or "flavr"
        which = _which(request.query.get("which", ""))[0]
        dkey, p = await _load(group, which)
        return web.Response(text=page(poster, dkey, p, request.query.get("saved", "")), content_type="text/html")

    def _back(p: Dict[str, Any], note: str, anchor: str = "") -> web.HTTPSeeOther:
        return web.HTTPSeeOther(f"/settings/article?group={quote(p['group'])}&which={quote(p['which'])}"
                                f"&saved={quote(note)}" + (f"#s-{anchor}" if anchor else ""))

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        dkey = str(form.get("d") or "")
        p = store.get(dkey) if dkey.startswith(PREFIX) else None
        if not p:
            raise web.HTTPSeeOther("/settings/article?saved=" + quote("That draft is gone; here's a fresh one."))
        migrate(p)
        action = str(form.get("action") or "save")
        verb, _, sid = action.partition(":")
        _save_form(p, form)
        note, anchor = "Saved.", sid
        if verb == "reset":
            store.delete(dkey)
            raise _back(p, "Started over: a fresh draft from the calendar.")
        if verb in ("up", "down"):
            _move(p, sid, -1 if verb == "up" else 1)
            note = "Moved."
        elif verb == "remove" and sid in (p.get("texts") or {}):
            p["texts"].pop(sid)
            p["sections"] = [s for s in p["sections"] if s["id"] != sid]
            note, anchor = "Text section removed.", ""
        elif verb == "remove" and sid in (p.get("talls") or {}):
            p["talls"].pop(sid)
            p["sections"] = [s for s in p["sections"] if s["id"] != sid]
            note, anchor = "Tall picture removed.", ""
        elif verb == "add_tall":
            n = 1 + max([int(k[4:]) for k in (p.get("talls") or {}) if k[4:].isdigit()] or [0])
            sid = f"tall{n}"
            p.setdefault("talls", {})[sid] = {"chunks": tall.renumber(tall.BUILTIN["Week overview"])}
            at = next((i for i, s in enumerate(p["sections"]) if s["id"] == "outro"), len(p["sections"]))
            p["sections"].insert(at, {"id": sid, "title": f"Tall picture {n}", "on": True})
            note, anchor = "Added a tall picture (before the outro). Open its chunks to build it.", sid
        elif verb == "add_text":
            n = 1 + max([int(k[4:]) for k in (p.get("texts") or {}) if k[4:].isdigit()] or [0])
            sid = f"text{n}"
            p.setdefault("texts", {})[sid] = ""
            at = next((i for i, s in enumerate(p["sections"]) if s["id"] == "outro"), len(p["sections"]))
            p["sections"].insert(at, {"id": sid, "title": f"Your text {n}", "on": True})
            note, anchor = "Added a text section (before the outro; move it with ↑ ↓).", sid
        elif verb == "host":
            new = str(form.get("host") or "")
            if new in hosts.HOSTS and new != p["host"]:
                p["host"], p["ai"], p["picks"] = new, [], {}
                p["candidates"] = {}
                _host_lines(p)
                week, _ = await _article(poster, p)
                _day_lines(p, week)                 # the day pictures' lines in the new host's voice
                note = f"{hosts.HOSTS[new]['name']} presents this one now."
        elif verb == "reroll_pics":             # 🎲: every automatic pool pick changes (pinned ones stay)
            p["seed"] = int(p.get("seed") or 0) + 1
            note = "Re-rolled the automatic pictures."
        elif verb == "reroll" and sid in (p.get("candidates") or {}):
            note, anchor = reroll(p, sid), slot_section(sid)
        elif verb == "ask" and sid in (p.get("candidates") or {}):
            note, anchor = await ask_slot(poster, p, sid), slot_section(sid)
        elif verb == "redo":                    # "redo:<slot>:<index>": one line rewritten
            slot, _, idx = sid.rpartition(":")
            if slot in (p.get("candidates") or {}) and idx.isdigit():
                note, anchor = await redo_line(poster, p, slot, int(idx)), slot_section(slot)
        elif verb == "regen" and sid in HOST_SECTIONS:
            _host_lines(p, shuffle=True, only=SLOTS[sid])
            note = "New lines."
        elif verb in ("regen", "regen_all"):
            week, a = await _article(poster, p)
            note = _refresh(p, a, sid if verb == "regen" else "")
            if sid.startswith("day") or verb == "regen_all":
                _day_lines(p, week, sid[3:] if verb == "regen" else "")
            if verb == "regen_all":         # the facts (and so the host lines' numbers) may have moved too
                p["facts"] = hosts.facts(store, week)
                p["notes"] = hosts.notes(p["facts"])
        p["saved_at"] = time.time()
        store.put(dkey, p)
        if verb == "ai" and sid in HOST_SECTIONS:
            if host_picker.start_ai(poster, dkey, SLOTS[sid]):
                note = "KoboldCpp is writing new lines; refresh in a minute or two."
            else:
                note = "KoboldCpp isn't set up." if getattr(poster, "kobold", None) is None else \
                    "KoboldCpp is still writing; refresh in a minute."
        raise _back(p, note, anchor)

    async def picture(request: web.Request) -> web.StreamResponse:
        """A host section's picture: a card drawn with Chromium, or one of the host's pictures as it is."""
        dkey = request.query.get("d", "")
        p = store.get(dkey) if dkey.startswith(PREFIX) else None
        sec = request.query.get("sec", "")
        if not p or sec not in HOST_SECTIONS:
            raise web.HTTPNotFound()
        pic = (p.get("pics") or {}).get(sec, "none")
        if pic in ("opener", "desk"):
            if poster.shooter is None:
                raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
            migrate(p)
            with _looks(p):
                png = await poster.shooter.png(host_picker.card_html(p, pic))
            return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})
        kind = pic[4:] if pic.startswith("pic:") else ""
        migrate(p)
        with _looks(p):
            path: Optional[Any] = hosts.picture(p["host"], kind) if kind in hosts.KINDS else None
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def day_picture(request: web.Request) -> web.Response:
        """A day picture in the host's look (host_cards.day), with the draft's line for that day."""
        dkey = request.query.get("d", "")
        p = store.get(dkey) if dkey.startswith(PREFIX) else None
        if p:
            migrate(p)
        try:
            i = int(request.query.get("day", ""))
        except ValueError:
            raise web.HTTPNotFound()
        if not p or not 0 <= i <= 6:
            raise web.HTTPNotFound()
        if poster.shooter is None:
            raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
        week, _ = await _article(poster, p)
        await poster.images.fetch_all(week)         # the stream thumbnails, cached like the board's
        with _looks(p):
            png = await poster.shooter.png(host_cards.day(
                p["host"], week, i, poster.images.data_url, host_picker.chosen(p, f"day{i}"),
                layout=(p.get("day_layouts") or {}).get(str(i)) or p.get("day_layout", "wall")))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    async def cover_picture(request: web.Request) -> web.Response:
        """The X Article cover in the host's look (host_cards.cover), 5:2 like the board's cover."""
        dkey = request.query.get("d", "")
        p = store.get(dkey) if dkey.startswith(PREFIX) else None
        if not p:
            raise web.HTTPNotFound()
        migrate(p)
        if poster.shooter is None:
            raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
        week, _ = await _article(poster, p)
        await poster.images.fetch_all(week)
        heading = host_picker.heading_of(p, "Week in Review")
        with _looks(p):
            png = await poster.shooter.png(host_cards.cover(p["host"], week, poster.images.data_url, heading,
                                                            p.get("cover_figure") or "happy"), size=(COVER_W, COVER_H))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    async def view(request: web.Request) -> web.Response:
        """The finished article on the copy page (flavrpromo/web.py ``article_html``)."""
        dkey = request.query.get("d", "")
        p = store.get(dkey) if dkey.startswith(PREFIX) else None
        if not p:
            raise web.HTTPNotFound()
        migrate(p)
        week, a = await _article(poster, p)
        out = finished(dkey, p)
        out["title"], out["pictures"] = a["title"], a["pictures"]
        q = article_query(p["group"], p.get("label") or "", int(p.get("off") or 0))
        back = (f'<p class="tip"><a style="color:#2ae0d4" href="/settings/article?group={quote(p["group"])}'
                f'&which={quote(p["which"])}">← back to the article editor</a></p>')
        # the zip holds the board-look day pictures, so it's only offered when the article uses those
        zip_url = "/calendar/article.zip" + q if p.get("day_look", "host") == "board" else ""
        return web.Response(text=article_html(out, "/calendar.png" + q, zip_url,
                                              _cover_url(dkey, p), top=back),
                            content_type="text/html", charset="utf-8")

    app.router.add_get("/settings/article", get)
    app.router.add_post("/settings/article", post)
    app.router.add_get("/settings/article/picture", picture)
    app.router.add_get("/settings/article/view", view)
    app.router.add_get("/settings/article/day", day_picture)
    app.router.add_get("/settings/article/cover", cover_picture)


__all__ = ["add_routes", "new_draft", "finished", "section_html", "draft_key"]
