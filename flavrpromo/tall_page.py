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
  * for each chunk: its size, its menus (host, pose or chibi, which pooled picture, side, day, stream,
    a line picked from the article's own lines or typed), ↑ ↓ duplicate remove, "save this chunk as",
  * add a chunk, insert a saved chunk, start from a built-in or saved stack, save the stack as a
    template, delete saved chunks / stacks.
Saved chunks: kv "tall_chunks" {name: chunk}; saved stacks: kv "tall_templates" {name: [chunk]}.
No password, like the rest of port 3871 (home network only).
"""

from __future__ import annotations

import copy
import time
from typing import Any, Dict, List
from urllib.parse import quote

from aiohttp import web

from . import article_editor, host_picker, hosts, kobold, tall
from .panel import _e, frame

CHUNKS_KEY, TEMPLATES_KEY = "tall_chunks", "tall_templates"
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
    vars_ = [("", "auto (the draft's pick)")] + [(v, "main" if v == "main" else f"#{v}")
                                                 for v, _ in hosts.variants(key, c.get("kind") or "happy")]
    hopts = [("", f"The article's host ({hosts.HOSTS[p['host']]['name']})")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
    return (f'<label>Host <select name="{c["id"]}__host">{_opts(hopts, c.get("host") or "")}</select></label> '
            f'<label>Pose <select name="{c["id"]}__kind">{_opts(kinds, c.get("kind"))}</select></label> '
            f'<label>Which picture <select name="{c["id"]}__var">{_opts(vars_, c.get("var") or "")}</select></label>'
            f'<small>Change the host or pose, press Save, then the picture menu shows that pose\'s pool.</small>')


def _fields(c: Dict[str, Any], p: Dict[str, Any], week: Any, lines: List[str]) -> str:
    t, cid = c["type"], c["id"]
    if t == "header":
        return (f'<label>Title <input name="{cid}__title" value="{_e(c.get("title"))}" placeholder="(the article heading)"></label>'
                f'<label>Line under it <input name="{cid}__sub" value="{_e(c.get("sub"))}" placeholder="(the date range)"></label>')
    if t in ("host", "footer"):
        side = (f'<label>Side <select name="{cid}__side">{_opts(tall.SIDES.items(), c.get("side") or "left")}</select></label>'
                if t == "host" else "")
        return _picture_menus(c, p) + side + _line_field(c, "line", lines, "Line from the article")
    if t == "stream":
        refs = [("", "(pick a stream)")] + [(x["ref"], x["label"]) for x in tall.tile_choices(week)]
        return (f'<label>Stream <select name="{cid}__ref">{_opts(refs, c.get("ref") or "")}</select></label>'
                + _line_field(c, "line", lines, "Remark under it"))
    if t == "grid":
        days = [(str(i), week.day_name(i)) for i in range(len(week.days))]
        return f'<label>Day <select name="{cid}__day">{_opts(days, c.get("day") or 0)}</select></label>'
    if t == "quote":
        return _line_field(c, "text", lines, "Line from the article")
    return '<small>Filled from the review\'s highlight numbers.</small>'


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
        blocks.append(
            f'<section class=chunk id="{cid}"><div class=head><b>{i + 1}. {_e(label)}</b> '
            f'<label>Size <select name="{cid}__size">{_opts(sizes, c.get("size", 1))}</select></label>'
            f'<span><button name=action value="up:{cid}" class=alt{" disabled" if i == 0 else ""}>↑</button> '
            f'<button name=action value="down:{cid}" class=alt{" disabled" if i == len(chunks) - 1 else ""}>↓</button> '
            f'<button name=action value="dup:{cid}" class=alt>Duplicate</button> '
            f'<button name=action value="del:{cid}" class=alt>Remove</button></span></div>'
            f'{_fields(c, p, week, lines)}'
            f'<p class=savebox><input name="{cid}__savename" placeholder="save this chunk as…" maxlength={NAME_MAX}> '
            f'<button name=action value="savechunk:{cid}" class=alt>Save chunk</button></p></section>')
    add = _opts([(k, v[0]) for k, v in tall.TYPES.items()], "quote")
    ins = _opts([(n, n) for n in sorted(saved_chunks)], "")
    stacks = _opts([(f"b:{n}", f"{n} (built-in)") for n in tall.BUILTIN] + [(f"t:{n}", n) for n in sorted(templates)], "")
    dels = _opts([(f"c:{n}", f"chunk: {n}") for n in sorted(saved_chunks)] + [(f"t:{n}", f"stack: {n}") for n in sorted(templates)], "")
    tools = (
        f'<section class=tools><p><select name=newtype>{add}</select> <button name=action value=add>+ Add a chunk</button></p>'
        + (f'<p><select name=insert>{ins}</select> <button name=action value=insert class=alt>Insert my saved chunk</button></p>'
           if saved_chunks else "")
        + f'<p><select name=stack>{stacks}</select> <button name=action value=load class=alt>Start from this stack</button> '
        f'<small>(replaces the chunks above)</small></p>'
        f'<p><input name=tplname placeholder="save this whole stack as…" maxlength={NAME_MAX}> '
        f'<button name=action value=savetpl class=alt>Save stack</button></p>'
        + (f'<p><select name=delwhat>{dels}</select> <button name=action value=delsaved class=alt>Delete saved</button></p>'
           if (saved_chunks or templates) else "") + '</section>')
    back = f'/settings/article?group={quote(p["group"])}&which={quote(p["which"])}#s-{tid}'
    body = (f'<p><a href="{back}">← back to the article</a></p>{meter}'
            f'<form method=post action=/settings/tall><input type=hidden name=d value="{_e(dkey)}">'
            f'<input type=hidden name=t value="{_e(tid)}">'
            f'<p><button name=action value=save>Save and preview</button></p>'
            f'<div class=prev><img src="/settings/tall/picture?d={quote(dkey)}&t={tid}&v={int(p.get("saved_at") or 0)}" '
            f'alt="preview" loading=lazy></div>{"".join(blocks)}{tools}</form>')
    style = (".meter{height:14px;background:#0e0f14;border-radius:8px;overflow:hidden}.meter div{height:100%;background:#2ae0d4}"
             ".meter.over div{background:#e5312f}.bad{color:#ff7a7a;font-weight:bold}"
             ".prev img{max-width:520px;width:100%;border-radius:8px;border:2px solid #3d2a3b;display:block;margin:10px 0}"
             ".chunk{border:1px solid #3d2a3b;border-radius:10px;padding:8px 14px;margin:10px 0}"
             ".chunk .head{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}"
             ".chunk label{display:inline-block;margin:6px 10px 6px 0}.chunk textarea{display:block}"
             ".chunk input:not([type]){width:min(480px,90%)}.tools p{margin:8px 0}"
             "@media(min-width:1100px){.prev{position:sticky;top:8px;float:right;margin-left:20px;width:380px}"
             "form .chunk,form .tools{margin-right:410px}}")
    return frame("Tall picture", "🧱 Tall picture builder", body, saved, style=style)


def _apply(c: Dict[str, Any], form: Any, p: Dict[str, Any], week: Any) -> None:
    """Take one chunk's menus and boxes from the posted form (unknown values are ignored)."""
    cid, t = c["id"], c["type"]
    get = lambda f: form.get(f"{cid}__{f}")  # noqa: E731
    if get("size") in ("0", "1", "2"):
        c["size"] = int(get("size"))
    if t == "header":
        c["title"], c["sub"] = " ".join(str(get("title") or "").split())[:120], " ".join(str(get("sub") or "").split())[:120]
    if t in ("host", "footer"):
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
    if t == "stream" and get("ref") is not None:
        c["ref"] = get("ref") if get("ref") in {x["ref"] for x in tall.tile_choices(week)} else ""
    if t == "grid" and str(get("day") or "").isdigit():
        c["day"] = max(0, min(len(week.days) - 1, int(get("day"))))
    for field in ("line", "text"):
        if field in c or (field == "line" and t in ("host", "footer", "stream")) or (field == "text" and t == "quote"):
            pick = get(f"pick_{field}")
            if pick:
                c[field] = str(pick)[:kobold.MAX_CHARS]
            elif get(field) is not None:
                c[field] = " ".join(str(get(field)).split())[:kobold.MAX_CHARS]


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
                stacks[name] = tall.renumber(chunks)
                store.put(TEMPLATES_KEY, stacks)
                note = f"Saved the stack as “{name}”."
            else:
                note = "Type a name to save the stack under."
        elif verb == "load":
            kind, _, name = str(form.get("stack") or "").partition(":")
            src = tall.BUILTIN.get(name) if kind == "b" else stacks.get(name) if kind == "t" else None
            if src:
                p["talls"][tid]["chunks"] = tall.renumber(src)
                note = f"Started from “{name}”."
            else:
                note = "Pick a stack first."
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
               "seed": p.get("seed"), "pins": p.get("pins")}
        png = await poster.shooter.png(tall.document(chunks, ctx), size=(tall.WIDTH, max(1, tall.total(chunks))))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    app.router.add_get("/settings/tall", get)
    app.router.add_post("/settings/tall", post)
    app.router.add_get("/settings/tall/picture", picture)


__all__ = ["add_routes", "page", "line_options"]
