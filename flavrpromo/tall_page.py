"""
The tall picture builder: http://<this PC>:3871/settings/tall?d=<article draft>&t=<tall id>
(owner 2026-11-21: build the image piece by piece, each chunk set with menus, chunks and whole
stacks saved to use again). Chunk types and the drawing are in flavrpromo/tall.py.

A tall picture belongs to an article draft (flavrpromo/article_editor.py): p["talls"][tid] =
{"chunks": [...]}, and the draft has a section with that id ("tall1", "tall2" ...) where the picture
sits in the article. The editor's "+ Add a tall picture" makes one from a built-in stack; this page
edits it:
  * a height meter (the picture is at most tall.MAX_H = 2133 px tall on X; more is cropped from the middle),
  * a preview (/settings/tall/picture, drawn with Chromium like the other card pictures),
  * for each chunk: its size, the shape of its bottom edge (straight, a diagonal cut, a zigzag, a wave or a curve, gentle to steep,
    with a stripe along the seam), its menus (host, pose or chibi, which pooled picture, side, day, stream,
    a line picked from the article's own lines or typed), ↑ ↓ duplicate remove, "save this chunk as",
  * stream and game chunks: tick boxes for what they show (tall.SHOW: picture, name, time, genre, host
    picture ...; "mix n match the content of each segment") and a ✨ that has KoboldCpp write the remark
    from that stream's / game's facts (flavrpromo/recipes.py); "✨ Write all remarks" does every empty one
    in the background,
  * the page saves itself and redraws the preview as menus change (flavrpromo/panel.py SCRIPT, "data-live");
    each chunk is a folding card whose bar can be dragged to reorder (↑ ↓ still work), with a colour menu
    for its background (tall.BAND_COLOURS or any colour),
  * a host picture on any chunk (always there on host moment / hero / sign-off, a tick box on the others)
    with its own size %, turn in degrees, mirror, move right / down, and "let it stick out" over the
    neighbouring chunks (tall.figure),
  * add a chunk, insert a saved chunk, start from a built-in or saved stack, save the stack as a
    template (the layout; this week's streams, games and remarks are dropped and refilled when it's used), delete saved chunks / stacks.
Saved chunks: kv "tall_chunks" {name: chunk}; saved stacks: kv "tall_templates" {name: [chunk]}.
No password, like the rest of port 3871 (home network only).
"""

from __future__ import annotations

import copy
import time
from typing import Any, Dict, List
from urllib.parse import quote

from aiohttp import web

from . import article_editor, host_picker, hosts, kobold, recipes, tall
from .panel import _e, frame

CHUNKS_KEY, TEMPLATES_KEY = tall.CHUNKS_KEY, tall.TEMPLATES_KEY
CHAT_MAX = 900              # characters kept of a chat chunk's rows (up to 5 lines; KoboldCpp writes 4)
NAME_MAX = 40


def _name(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:NAME_MAX]


def line_options(p: Dict[str, Any]) -> List[str]:
    """Every candidate line of the article draft (opener, notes, desk lines, day lines), once each, for the
    "use a line from the article" menus."""
    seen: List[str] = []
    for lines in (p.get("candidates") or {}).values():
        for x in lines:
            if x and x not in seen:
                seen.append(x)
    return seen[:60]


def _opts(items: Any, cur: Any) -> str:
    return "".join(f'<option value="{_e(v)}"{" selected" if str(v) == str(cur) else ""}>{_e(n)}</option>' for v, n in items)


def _line_field(c: Dict[str, Any], field: str, lines: List[str], label: str) -> str:
    """A line: a menu of the article's lines (picking one copies it in) plus a text box to type your own."""
    pick = _opts([("", "(type my own below)")] + [(x, x[:70] + ("…" if len(x) > 70 else "")) for x in lines], "")
    return (f'<label>{_e(label)} <select name="{c["id"]}__pick_{field}">{pick}</select></label>'
            f'<textarea name="{c["id"]}__{field}" rows=2 maxlength={kobold.MAX_CHARS}>{_e(c.get(field))}</textarea>')


def _picture_menus(c: Dict[str, Any], p: Dict[str, Any]) -> str:
    key = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
    have = hosts.pictures(key)
    kinds = [(k, k.replace("_", " ")) for k in hosts.POOLED if have.get(k)]
    # which picture of the kind's pool: the main one, a built-in extra ("b<n>", hosts._builtin_pool) or an upload ("<n>")
    vars_ = [("", "auto (the draft's pick)")] + [
        (v, "main" if v == "main" else f"built-in {v[1:]}" if v.startswith("b") else f"#{v}")
        for v, _ in hosts.variants(key, c.get("kind") or "happy")]
    hopts = [("", f"The article's host ({hosts.HOSTS[p['host']]['name']})")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
    return (f'<label>Host <select name="{c["id"]}__host">{_opts(hopts, c.get("host") or "")}</select></label> '
            f'<label>Pose <select name="{c["id"]}__kind">{_opts(kinds, c.get("kind"))}</select></label> '
            f'<label>Which picture <select name="{c["id"]}__var">{_opts(vars_, c.get("var") or "")}</select></label>'
            f'<small>Change the host or pose, press Save, then the picture menu shows that pose\'s pool.</small>')


def _choices(c: Dict[str, Any]) -> str:
    """KoboldCpp's remarks for this chunk to pick from (the ✨ button, recipes.write_choices); picking one
    puts it in the Remark box."""
    got = [x for x in c.get("choices") or [] if x]
    if not got:
        return ""
    rows = "".join(f'<label class=tick><input type=radio name="{c["id"]}__choice" value="{i}"'
                   f'{" checked" if x == c.get("line") else ""}> {_e(x)}</label>' for i, x in enumerate(got))
    return f'<div class=choices><small>✨ KoboldCpp wrote these; pick one (or type your own above):</small>{rows}</div>'


def _figure_controls(c: Dict[str, Any], p: Dict[str, Any]) -> str:
    """The host picture box every chunk but the chat has: the tick box (and side, host, pose) on chunk types
    where the picture is optional, then size / turn / mirror / move / stick out once there is a picture."""
    cid, t = c["id"], c["type"]
    if t == "chat":
        return ""
    out = f'<input type=hidden name="{cid}__figed" value=1>'
    if t in tall.PIC_TYPES:
        out += (f'<label class=tick><input type=checkbox name="{cid}__pic" value=1{" checked" if c.get("pic") else ""}> '
                f'Add a host picture</label> ')
        if c.get("pic"):
            out += (f'<label>Side <select name="{cid}__side">{_opts(tall.SIDES.items(), c.get("side") or "right")}</select></label>'
                    + _picture_menus(c, p))
    if not tall.has_figure(c):
        return (f'<div class=fig>{out}<small>Tick it and press Save for the picture\'s menus.</small></div>'
                if t in tall.PIC_TYPES else "")
    num = lambda f, label, unit: (  # noqa: E731
        f'<label>{label} <input type=number name="{cid}__{f}" value="{tall._num(c, f)}" min={tall.PIC_NUMBERS[f][0]} '
        f'max={tall.PIC_NUMBERS[f][1]} step={5 if f != "pscale" else 10} style="width:5.5em"> {unit}</label> ')
    return (f'<div class=fig><b>Host picture</b> {out}'
            + num("pscale", "Size", "%") + num("prot", "Turn", "°") + num("px", "Move right", "px") + num("py", "Move down", "px")
            + f'<label class=tick><input type=checkbox name="{cid}__pflip" value=1{" checked" if c.get("pflip") else ""}> Mirror</label> '
            f'<label class=tick><input type=checkbox name="{cid}__ppop" value=1{" checked" if c.get("ppop") else ""}> '
            f'Let it stick out over the next chunks</label>'
            f'<small>100% is the built-in size; it grows from its feet. Negative numbers move it left / up.</small></div>')


def _fields(c: Dict[str, Any], p: Dict[str, Any], week: Any, lines: List[str]) -> str:
    t, cid = c["type"], c["id"]
    if t == "header":
        return (f'<label>Title <input name="{cid}__title" value="{_e(c.get("title"))}" placeholder="(the article heading)"></label>'
                f'<label>Line under it <input name="{cid}__sub" value="{_e(c.get("sub"))}" placeholder="(the date range)"></label>')
    if t in ("host", "footer"):
        side = (f'<label>Side <select name="{cid}__side">{_opts(tall.SIDES.items(), c.get("side") or "left")}</select></label>'
                if t == "host" else "")
        return _picture_menus(c, p) + side + _line_field(c, "line", lines, "Line from the article")
    if t == "hero":
        return (f'<label>Small word on top <input name="{cid}__top" value="{_e(c.get("top"))}"></label>'
                f'<label>Big title <input name="{cid}__title" value="{_e(c.get("title"))}" placeholder="(the host\'s first name)"></label>'
                f'<label>Under it <input name="{cid}__sub" value="{_e(c.get("sub"))}" placeholder="(the host\'s job)"></label>'
                f'<label>Tagline <input name="{cid}__tag" value="{_e(c.get("tag"))}" placeholder="(the date range)"></label>'
                + _picture_menus(c, p))
    if t == "chat":
        hopts = [("", "The article's host")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
        oopts = [("", "The other host")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
        return (f'<label>First speaker <select name="{cid}__host">{_opts(hopts, c.get("host") or "")}</select></label> '
                f'<label>Answers <select name="{cid}__other">{_opts(oopts, c.get("other") or "")}</select></label>'
                f'<label>Lines, one per row (they take turns)</label>'
                f'<textarea name="{cid}__lines" rows=5 maxlength={CHAT_MAX}>{_e(c.get("lines"))}</textarea>'
                # banter: KoboldCpp writes the whole back-and-forth, each line with the speaker's own card
                f'<p><button name=action value="ai:{cid}" class=alt>✨ Write the chat</button> <small>(KoboldCpp has the '
                f'two hosts answer each other about this review, {recipes.CHAT_TURNS} lines; it replaces what is '
                f'typed above and the page waits for it)</small></p>')
    if t in ("stream", "game"):
        if t == "stream":
            refs = [("", "(pick a stream)")] + [(x["ref"], x["label"]) for x in tall.tile_choices(week)]
            pick = f'<label>Stream <select name="{cid}__ref">{_opts(refs, c.get("ref") or "")}</select></label>'
        else:
            rows = recipes.game_rows(p.get("facts") or {}, week)
            names = [("", "(pick a game)")] + [(r["game"], r["game"]) for r in rows]
            pick = f'<label>Game <select name="{cid}__game">{_opts(names, c.get("game") or "")}</select></label>'
        ticks = "".join(f'<label class=tick><input type=checkbox name="{cid}__show_{k}" value=1'
                        f'{" checked" if tall.shown(c, k) else ""}> {_e(n)}</label>' for k, n in tall.SHOW[t].items())
        more = _picture_menus(c, p) if tall.shown(c, "host") else ""
        return (pick + f'<p class=ticks><input type=hidden name="{cid}__showed" value=1>{ticks}</p>' + more
                + _line_field(c, "line", lines, "Remark") + _choices(c)
                + f'<p><button name=action value="ai:{cid}" class=alt>✨ Write the remark</button> '
                f'<small>(KoboldCpp writes a few from this {t}\'s facts to pick from; the page waits for it)</small></p>')
    if t == "grid":
        days = [(str(i), week.day_name(i)) for i in range(len(week.days))]
        return f'<label>Day <select name="{cid}__day">{_opts(days, c.get("day") or 0)}</select></label>'
    if t == "quote":
        return _line_field(c, "text", lines, "Line from the article")
    return '<small>Filled from the review\'s highlight numbers.</small>'


def _what(c: Dict[str, Any], p: Dict[str, Any], week: Any) -> str:
    """A few words on what a chunk holds, for its folded bar ("Lulu · MON · Valheim", the start of a line ...)."""
    t = c["type"]
    if t == "stream":
        return next((x["label"] for x in tall.tile_choices(week) if x["ref"] == c.get("ref")), "no stream picked")
    if t == "game":
        return c.get("game") or "no game picked"
    if t == "grid":
        return week.day_name(int(c.get("day") or 0)) if getattr(week, "days", None) else ""
    if t == "chat":
        return str(c.get("lines") or "").split("\n")[0]
    return str(c.get("title") or c.get("line") or c.get("text") or "")


def _band_menu(c: Dict[str, Any]) -> str:
    """The chunk's colour: automatic, one of tall.BAND_COLOURS, or any colour from the colour box."""
    cid, cur = c["id"], str(c.get("band") or "")
    custom = cur if cur.startswith("#") and tall.band_colour(c) else ""
    opts = [("", "Automatic")] + [(k, n) for k, (n, _) in tall.BAND_COLOURS.items()] + [("custom", "My own colour →")]
    return (f'<label>Colour <select name="{cid}__band">{_opts(opts, "custom" if custom else cur)}</select></label> '
            f'<input type=color name="{cid}__bandhex" value="{_e(custom or tall.band_colour(c) or "#3d1233")}" '
            f'title="used when the menu says My own colour">')


def page(p: Dict[str, Any], dkey: str, tid: str, week: Any, store: Any, saved: str = "") -> str:
    chunks = p["talls"][tid]["chunks"]
    used = tall.total(chunks)
    over = used > tall.MAX_H
    pct = min(100, int(used * 100 / tall.MAX_H))
    meter = (f'<div class="meter{" over" if over else ""}"><div style="width:{pct}%"></div></div>'
             f'<p><b>{used} / {tall.MAX_H} px</b> '
             + (f'<span class=bad>X would crop {used - tall.MAX_H} px from the middle. Remove or shrink a chunk.</span>'
                if over else f'<small>{tall.MAX_H - used} px left before X would crop it</small>') + '</p>')
    lines = line_options(p)
    saved_chunks = store.get(CHUNKS_KEY) or {}
    templates = store.get(TEMPLATES_KEY) or {}
    blocks = []
    for i, c in enumerate(chunks):
        cid, label = c["id"], tall.TYPES[c["type"]][0]
        sizes = [("0", f"Small ({tall.TYPES[c['type']][1][0]} px)"), ("1", f"Medium ({tall.TYPES[c['type']][1][1]} px)"),
                 ("2", f"Large ({tall.TYPES[c['type']][1][2]} px)")]
        # one folding card per chunk: the bar (drag it to reorder) says what it is; the menus are inside
        blocks.append(
            f'<details class="card chunk" id="{cid}"><summary><span class=grip title="drag to reorder">⠿</span>'
            f'<b>{i + 1}. {_e(label)}</b> <span class=what>{_e(_what(c, p, week))}</span> '
            f'<small>{tall.height(c)} px</small><span class=acts>'
            f'<button name=action value="up:{cid}" class=alt{" disabled" if i == 0 else ""}>↑</button> '
            f'<button name=action value="down:{cid}" class=alt{" disabled" if i == len(chunks) - 1 else ""}>↓</button> '
            f'<button name=action value="dup:{cid}" class=alt>Duplicate</button> '
            f'<button name=action value="del:{cid}" class=alt>Remove</button></span></summary><div class=inner>'
            f'<p><label>Size <select name="{cid}__size">{_opts(sizes, c.get("size", 1))}</select></label> {_band_menu(c)}</p>'
            f'{_fields(c, p, week, lines)}{_figure_controls(c, p)}'
            + ("" if i == len(chunks) - 1 else
               f'<p><label>Bottom edge <select name="{cid}__cut">{_opts(tall.CUTS.items(), c.get("cut") or "")}</select></label> '
               f'<label>Slope <select name="{cid}__slope">{_opts([("0", "Gentle"), ("1", "Normal"), ("2", "Steep")], c.get("slope", 1))}'
               f'</select></label>'
               + (f' <label>Teeth / waves <input type=number name="{cid}__teeth" value="{tall.teeth(c)}" '
                  f'min={tall.TEETH[c["cut"]][0]} max={tall.TEETH[c["cut"]][1]} style="width:5em"></label>'
                  if c.get("cut") in tall.TEETH else "") + '</p>')
            + f'<p class=savebox data-nolive><input name="{cid}__savename" placeholder="save this chunk as…" maxlength={NAME_MAX}> '
            f'<button name=action value="savechunk:{cid}" class=alt>Save chunk</button></p></div></details>')
    add = _opts([(k, v[0]) for k, v in tall.TYPES.items()], "quote")
    ins = _opts([(n, n) for n in sorted(saved_chunks)], "")
    stacks = _opts([(f"b:{n}", f"{n} (built-in)") for n in tall.BUILTIN] + [(f"t:{n}", n) for n in sorted(templates)], "")
    dels = _opts([(f"c:{n}", f"chunk: {n}") for n in sorted(saved_chunks)] + [(f"t:{n}", f"stack: {n}") for n in sorted(templates)], "")
    state = (p["talls"][tid].get("ai_state") or "")
    ai_tools = ('<p><button name=action value=aiall class=alt>✨ Write all empty remarks and chats</button> '
                + (f'<small>KoboldCpp: {_e(recipes.AI_STATES.get(state, state))}</small>' if state else
                   '<small>one request each, in the background; refresh to see them</small>') + '</p>'
                if any(c["type"] in recipes.LINE_TYPES or c["type"] == "chat" for c in chunks) else "")
    tools = (
        f'<section class=tools data-nolive>{ai_tools}<p><select name=newtype>{add}</select> <button name=action value=add>+ Add a chunk</button></p>'
        + (f'<p><select name=insert>{ins}</select> <button name=action value=insert class=alt>Insert my saved chunk</button></p>'
           if saved_chunks else "")
        + f'<p><select name=stack>{stacks}</select> <button name=action value=load class=alt>Start from this stack</button> '
        f'<small>(replaces the chunks above)</small></p>'
        f'<p><input name=tplname placeholder="save this whole stack as…" maxlength={NAME_MAX}> '
        f'<button name=action value=savetpl class=alt>Save stack</button></p>'
        + (f'<p><select name=delwhat>{dels}</select> <button name=action value=delsaved class=alt>Delete saved</button></p>'
           if (saved_chunks or templates) else "") + '</section>')
    home = f'day{p["talls"][tid]["day"]}' if p["talls"][tid].get("day") is not None else tid   # a day's own tall picture
    back = f'/settings/article?group={quote(p["group"])}&which={quote(p["which"])}#s-{home}'
    pic = f'/settings/tall/picture?d={quote(dkey)}&t={tid}&v={article_editor.stamp(p, tid)}'
    # data-live: the form saves itself and the parts marked data-swap are refreshed (flavrpromo/panel.py SCRIPT);
    # the chunk list is a data-draglist: dropping a card posts action=order with the ids in the hidden "order"
    body = (f'<p><a href="{back}">← back to the article</a></p>'
            f'<form method=post action=/settings/tall data-live data-foldkey="{_e(dkey)}:{_e(tid)}">'
            f'<input type=hidden name=d value="{_e(dkey)}"><input type=hidden name=t value="{_e(tid)}">'
            f'<input type=hidden name=order value="">'
            f'<div data-swap=always data-swap-id=meter>{meter}</div>'
            f'<p><button name=action value=save>Save and preview</button> <span class=livestatus>Changes save and '
            f'redraw on their own.</span> <button type=button class=link data-foldall=close>Fold all</button><button type=button class=link data-foldall=open>Open all</button></p>'
            f'<div class=prev data-swap=always data-swap-id=prev><a href="{pic}" target=_blank title="open full size">'
            f'<img src="{pic}" alt="preview"></a></div>'
            f'<div class=chunks data-swap=rebuild data-swap-id=chunks data-draglist>{"".join(blocks)}</div>{tools}</form>'
            # ✨ on one chunk waits for KoboldCpp: show it's working instead of a page that looks stuck
            "<script>document.querySelector('form[data-live]').addEventListener('submit',e=>{const b=e.submitter;"
            "if(b&&/^ai:/.test(b.value)){b.textContent='✨ writing… (up to a minute)';"
            "setTimeout(()=>document.querySelectorAll('button').forEach(x=>x.disabled=true),0)}});</script>")
    style = (".meter{height:14px;background:#0e0f14;border-radius:8px;overflow:hidden}.meter div{height:100%;background:#2ae0d4}"
             ".meter.over div{background:#e5312f}.bad{color:#ff7a7a;font-weight:bold}"
             ".prev img{width:100%;border-radius:8px;border:2px solid #3d2a3b;display:block;margin:10px 0}.prev{max-width:520px}"
             ".chunk label{display:inline-block;margin:6px 10px 6px 0}.chunk select{width:auto}"
             ".ticks label.tick,.choices label.tick{margin:2px 14px 2px 0;font-size:15px}.choices label.tick{display:block}"
             ".fig{border-top:1px dashed #3d2a3b;margin-top:8px;padding-top:6px}.fig small{display:block}"
             ".chunk textarea{display:block}.chunk input:not([type]){width:min(480px,90%)}.tools p{margin:8px 0}"
             "@media(min-width:1100px){.prev{position:sticky;top:8px;float:right;margin-left:20px;width:420px;"
             "max-height:calc(100vh - 16px);overflow:auto}form .chunks,form .tools{margin-right:450px}}")
    return frame("Tall picture", "🧱 Tall picture builder", body, saved, style=style)


def _apply(c: Dict[str, Any], form: Any, p: Dict[str, Any], week: Any) -> None:
    """Take one chunk's menus and boxes from the posted form (unknown values are ignored)."""
    cid, t = c["id"], c["type"]
    get = lambda f: form.get(f"{cid}__{f}")  # noqa: E731
    if get("size") in ("0", "1", "2"):
        c["size"] = int(get("size"))
    if get("cut") in tall.CUTS:
        c["cut"] = get("cut")
    if get("slope") in ("0", "1", "2"):
        c["slope"] = int(get("slope"))
    if get("teeth") is not None and c.get("cut") in tall.TEETH:     # how many teeth (zigzag) / waves
        c["teeth"] = tall.teeth(dict(c, teeth=get("teeth")))
    if get("band") is not None:                 # the colour menu; "custom" takes the colour box next to it
        want = str(get("bandhex") or "") if get("band") == "custom" else str(get("band"))
        c["band"] = want if tall.band_colour({"band": want}) else ""
    before = c.get("line")                      # to tell a newly picked ✨ choice from an edited remark (below)
    if t == "hero":
        for f in ("top", "title", "sub", "tag"):
            if get(f) is not None:
                c[f] = " ".join(str(get(f)).split())[:80]
    if t == "chat":
        if get("host") is not None:
            c["host"] = get("host") if get("host") in hosts.HOSTS else ""
        if get("other") is not None:
            c["other"] = get("other") if get("other") in hosts.HOSTS else ""
        if get("lines") is not None:
            c["lines"] = "\n".join(" ".join(x.split())[:kobold.MAX_CHARS] for x in str(get("lines")).splitlines() if x.strip())[:CHAT_MAX]
    if t == "header":
        c["title"], c["sub"] = " ".join(str(get("title") or "").split())[:120], " ".join(str(get("sub") or "").split())[:120]
    if t in ("host", "footer", "hero"):
        if get("host") is not None:
            c["host"] = get("host") if get("host") in hosts.HOSTS else ""
        if get("kind") in hosts.POOLED:
            c["kind"] = get("kind")
        key = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
        if get("var") is not None:
            ids = [v for v, _ in hosts.variants(key, c.get("kind") or "happy")]
            c["var"] = get("var") if get("var") in ids else ""
        if t == "host" and get("side") in tall.SIDES:
            c["side"] = get("side")
    if t in tall.PIC_TYPES:                     # the optional host picture: tick box, side, host, pose, which one
        if get("figed"):
            c["pic"] = bool(get("pic"))
        if get("side") in tall.SIDES:
            c["side"] = get("side")
        if get("host") is not None:
            c["host"] = get("host") if get("host") in hosts.HOSTS else ""
        if get("kind") in hosts.POOLED:
            c["kind"] = get("kind")
        key = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
        if get("var") is not None:
            c["var"] = get("var") if get("var") in [v for v, _ in hosts.variants(key, c.get("kind") or "happy")] else ""
    if t != "chat":                             # size / turn / move / mirror / stick out of any host picture
        for f in tall.PIC_NUMBERS:
            if get(f) is not None:
                c[f] = tall._num({f: get(f)}, f)
        if get("figed"):                        # tick boxes only count when they were on the page
            c["pflip"], c["ppop"] = bool(get("pflip")), bool(get("ppop"))
    if t == "stream" and get("ref") is not None:
        c["ref"] = get("ref") if get("ref") in {x["ref"] for x in tall.tile_choices(week)} else ""
    if t == "game" and get("game") is not None:
        c["game"] = get("game") if get("game") in {r["game"] for r in recipes.game_rows(p.get("facts") or {}, week)} else ""
    if t in recipes.LINE_TYPES:
        if get("showed"):                       # the tick boxes were on the page (a partial post leaves them be)
            c["show"] = [k for k in tall.SHOW[t] if get(f"show_{k}")]
        if get("host") is not None:
            c["host"] = get("host") if get("host") in hosts.HOSTS else ""
        if get("kind") in hosts.POOLED:
            c["kind"] = get("kind")
        key = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
        if get("var") is not None:
            c["var"] = get("var") if get("var") in [v for v, _ in hosts.variants(key, c.get("kind") or "happy")] else ""
    if t == "grid" and str(get("day") or "").isdigit():
        c["day"] = max(0, min(len(week.days) - 1, int(get("day"))))
    for field in ("line", "text"):
        if field in c or (field == "line" and t in ("host", "footer", "stream")) or (field == "text" and t == "quote"):
            pick = get(f"pick_{field}")
            if pick:
                c[field] = str(pick)[:kobold.MAX_CHARS]
            elif get(field) is not None:
                c[field] = " ".join(str(get(field)).split())[:kobold.MAX_CHARS]
    # a ✨ choice picked (radio): it goes in the Remark box, unless the box itself was edited in the same save
    got, n = c.get("choices") or [], str(get("choice") or "")
    if n.isdigit() and int(n) < len(got) and got[int(n)] != before and c.get("line") == before:
        c["line"] = got[int(n)]


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store

    def _load(dkey: str, tid: str) -> Dict[str, Any]:
        p = store.get(dkey) if dkey.startswith(article_editor.PREFIX) else None
        if not p or tid not in (p.get("talls") or {}):
            raise web.HTTPNotFound(text="That tall picture isn't in a draft any more.")
        article_editor.migrate(p)
        return p

    def _back(dkey: str, tid: str, note: str, anchor: str = "") -> web.HTTPSeeOther:
        return web.HTTPSeeOther(f"/settings/tall?d={quote(dkey)}&t={quote(tid)}&saved={quote(note)}"
                                + (f"#{anchor}" if anchor else ""))

    async def get(request: web.Request) -> web.Response:
        dkey, tid = request.query.get("d", ""), request.query.get("t", "")
        p = _load(dkey, tid)
        week, _ = await article_editor._article(poster, p)
        return web.Response(text=page(p, dkey, tid, week, store, request.query.get("saved", "")), content_type="text/html")

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        dkey, tid = str(form.get("d") or ""), str(form.get("t") or "")
        p = _load(dkey, tid)
        week, _ = await article_editor._article(poster, p)
        chunks: List[Dict[str, Any]] = p["talls"][tid]["chunks"]
        for c in chunks:
            _apply(c, form, p, week)
        verb, _, cid = str(form.get("action") or "save").partition(":")
        i = next((k for k, c in enumerate(chunks) if c["id"] == cid), -1)
        note, anchor = "Saved.", ""
        mine, stacks = dict(store.get(CHUNKS_KEY) or {}), dict(store.get(TEMPLATES_KEY) or {})
        if verb in ("up", "down") and i >= 0:
            j = i - 1 if verb == "up" else i + 1
            if 0 <= j < len(chunks):
                chunks[i], chunks[j] = chunks[j], chunks[i]
                note = "Moved."
            anchor = cid
        elif verb == "del" and i >= 0:
            chunks.pop(i)
            note = "Removed that chunk."
        elif verb == "dup" and i >= 0:
            twin = copy.deepcopy(chunks[i])
            twin["id"] = tall.new_chunk("quote", chunks)["id"]
            chunks.insert(i + 1, twin)
            note, anchor = "Duplicated.", twin["id"]
        elif verb == "add":
            c = tall.new_chunk(str(form.get("newtype") or ""), chunks)
            chunks.append(c)
            note, anchor = f"Added a {tall.TYPES[c['type']][0].lower()} chunk at the bottom.", c["id"]
        elif verb == "insert" and str(form.get("insert") or "") in mine:
            c = copy.deepcopy(mine[str(form.get("insert"))])
            c["id"] = tall.new_chunk("quote", chunks)["id"]
            chunks.append(c)
            note, anchor = "Inserted your saved chunk at the bottom.", c["id"]
        elif verb == "savechunk" and i >= 0:
            name = _name(form.get(f"{cid}__savename"))
            if name:
                mine[name] = copy.deepcopy(chunks[i])
                store.put(CHUNKS_KEY, mine)
                note = f"Saved this chunk as “{name}”."
            else:
                note = "Type a name to save the chunk under."
            anchor = cid
        elif verb == "savetpl":
            name = _name(form.get("tplname"))
            if name:
                stacks[name] = tall.strip(chunks)       # the layout, not this week's streams
                store.put(TEMPLATES_KEY, stacks)
                note = f"Saved the stack as “{name}”."
            else:
                note = "Type a name to save the stack under."
        elif verb == "load":
            kind, _, name = str(form.get("stack") or "").partition(":")
            src = tall.BUILTIN.get(name) if kind == "b" else stacks.get(name) if kind == "t" else None
            if src:
                p["talls"][tid]["chunks"] = tall.renumber(src)
                recipes.fill(p["talls"][tid]["chunks"], p, week)      # this week's streams / games go in
                note = f"Started from “{name}”."
            else:
                note = "Pick a stack first."
        elif verb == "order":                   # cards dragged into a new order (panel.SCRIPT): "c3,c1,c2"
            ids = [x for x in str(form.get("order") or "").split(",") if x]
            by = {c["id"]: c for c in chunks}
            if sorted(ids) == sorted(by):
                chunks[:] = [by[x] for x in ids]
                note = "Moved."
        elif verb == "ai" and i >= 0 and chunks[i]["type"] == "chat":   # ✨ a chat chunk: the hosts' back-and-forth
            text, note = await recipes.write_chat(poster, p, chunks[i])
            if text:
                chunks[i]["lines"] = text[:CHAT_MAX]
            anchor = cid
        elif verb == "ai" and i >= 0:           # ✨ one chunk's remark: a few to pick from (the page waits)
            got, note = await recipes.write_choices(poster, p, week, chunks[i])
            if got:
                chunks[i]["choices"], chunks[i]["line"] = got, got[0]
            anchor = cid
        elif verb == "aiall":
            store.put(dkey, p)                  # the posted menus first, then the writer re-reads the draft
            note = ("KoboldCpp is writing the empty remarks; refresh in a minute or two."
                    if recipes.start_lines(poster, dkey, tid, week) else
                    "KoboldCpp isn't set up." if getattr(poster, "kobold", None) is None else
                    "KoboldCpp is still writing; refresh in a minute.")
            raise _back(dkey, tid, note)
        elif verb == "delsaved":
            kind, _, name = str(form.get("delwhat") or "").partition(":")
            if kind == "c" and mine.pop(name, None) is not None:
                store.put(CHUNKS_KEY, mine)
                note = f"Deleted the saved chunk “{name}”."
            elif kind == "t" and stacks.pop(name, None) is not None:
                store.put(TEMPLATES_KEY, stacks)
                note = f"Deleted the saved stack “{name}”."
        p["saved_at"] = time.time()
        store.put(dkey, p)
        raise _back(dkey, tid, note, anchor)

    async def picture(request: web.Request) -> web.Response:
        """The tall picture itself, drawn with Chromium at its real height."""
        dkey, tid = request.query.get("d", ""), request.query.get("t", "")
        p = _load(dkey, tid)
        if poster.shooter is None:
            raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
        week, _ = await article_editor._article(poster, p)
        await poster.images.fetch_all(week)
        f = p.get("facts") or {}
        chunks = p["talls"][tid]["chunks"]
        ctx = {"host": p["host"], "week": week, "img": poster.images.data_url, "facts": f, "notes": p.get("notes"),
               "heading": host_picker.heading_of(p, "Week in Review"), "range": f.get("range") or "",
               "seed": p.get("seed"), "pins": p.get("pins"), "scheme": article_editor.scheme_for(p, tid),
               **recipes.drawing_context(store, p, week, chunks)}
        png = await poster.shooter.png(tall.document(chunks, ctx), size=(tall.WIDTH, max(1, tall.total(chunks))))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    app.router.add_get("/settings/tall", get)
    app.router.add_post("/settings/tall", post)
    app.router.add_get("/settings/tall/picture", picture)


__all__ = ["add_routes", "page", "line_options"]
