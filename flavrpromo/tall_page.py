"""
The tall picture builder: http://<this PC>:3871/settings/tall?d=<article draft>&t=<tall id>
(owner 2026-11-21: build the image piece by piece, each chunk set with menus, chunks and whole
stacks saved to use again). Chunk types and the drawing are in flavrpromo/tall.py.

The list page http://<this PC>:3871/settings/talls ("🧱 Tall pictures" in the panel's menu; owner 2026-11-22:
"jump right to a stack editor directly instead of having to go through the menus to make an article") shows a
week's tall pictures and makes a new one from a stack or a recipe, then opens it here. A picture made there
is NOT ticked into the article (its section is off) until the owner ticks it in the article editor.

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
  * a stream chunk's game (owner 2026-11-22: "if it can't detect the game automatically, can it let me
    select and/or search for it?"): the chunk says which game the stream has, with a box to type it (known
    games are suggested), "Set game", and "🔎 Search IGDB" (flavrpromo/gameinfo.py ``search``; an empty box
    searches the stream's title) whose results are buttons to pick from. Setting it is flavrpromo/games.py
    ``set_stream``: the stream's own row and "this title means this game" for next time. These boxes are
    data-nolive: only their buttons act on them.
  * what a remark is about (owner 2026-11-22: "a good way to get the host to talk a little about the game"):
    "The remark is about" (the stream, or the game itself) and "Tell the host" (a few words to work in);
    flavrpromo/recipes.py ``ask_kind`` / ``chunk_facts`` read them (chunk keys ``about`` and ``hint``),
  * host moments and the sign-off strip have a ✨ too (owner 2026-11-22): KoboldCpp reads the picture's other
    chunks and writes a few lines that sum it up (recipes.stack_facts), with the same "Tell the host" box,
  * a Look card for the whole stack (owner 2026-11-22: "a way to change the stack style and color scheme"):
    its colour scheme (the picture's own entry in the draft's p["schemes"], flavrpromo/schemes.py), its host
    style (p["talls"][tid]["host"]: whose lettering, colours and pictures; recipes.as_tall) and one kind of
    bottom edge for every chunk at once (recipes.apply_seams); it also sets the "look" of every stream chunk
    (the plain row or the day pictures' colour strip, tall.LOOKS / recipes.apply_look) and each stream chunk
    has its own Look menu (owner 2026-11-22: "add the article styles ... to the chunk stacks as well"),
  * a stream chunk links to the stream itself (VOD, live page or planned page) so it can be checked,
  * "↻ Redraw" under the preview draws the picture again without changing anything,
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

from . import article_editor, gameinfo, games, groups, host_picker, hosts, kobold, recipes, schemes, tall
from .panel import _e, frame

CHUNKS_KEY, TEMPLATES_KEY = tall.CHUNKS_KEY, tall.TEMPLATES_KEY
CHAT_MAX = 900              # characters kept of a chat chunk's rows (up to 5 lines; KoboldCpp writes 4)
NAME_MAX = 40
LIST_TAB = "🧱 Tall pictures"       # the list page's label in flavrpromo/panel.py NAV (the builder shows under its tab)
KNOWN_MAX = 400             # known games offered as suggestions in the game box (a <datalist>)
TITLE_PARTS = 3             # parts of a stream's title searched on IGDB when the game box is empty (one request each)


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
    hopts = [("", f"The stack's host ({hosts.HOSTS[p['host']]['name']})")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
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
    # "chosen": which choice the box held when the page was drawn. The radio stays ticked in the browser after
    # the box is edited by hand, so ``_apply`` only takes a radio that differs from this (else every later
    # save put the old choice back over the owner's own words: owner 2026-11-22 "if i edit the line manually,
    # it doesn't save").
    chosen = next((str(i) for i, x in enumerate(got) if x == c.get("line")), "")
    return (f'<div class=choices><input type=hidden name="{c["id"]}__chosen" value="{chosen}">'
            f'<small>✨ KoboldCpp wrote these; pick one (or type your own above):</small>{rows}</div>')


def _hint_field(c: Dict[str, Any]) -> str:
    """"Tell the host": a few words of the owner's that ✨ works into the line (chunk key ``hint``)."""
    return (f'<label class=hint>Tell the host <input name="{c["id"]}__hint" value="{_e(c.get("hint"))}" '
            f'maxlength={recipes.HINT_MAX} placeholder="optional, like “they finally beat the boss”"></label>')


def _watch_links(t: Any) -> str:
    """Links to the stream itself (owner 2026-11-22: "give me VOD links so i can double check the streams
    myself"): the tile's main link (the VOD of a past stream, the live page, a planned stream's page) and
    each platform's own link where it differs. Only http(s) addresses; they open in a new tab."""
    main = {"past": "VOD", "live": "live now"}.get(t.kind, "planned stream")
    seen, out = set(), []
    for label, url in [(main, t.url)] + [(plat, u) for plat, u in (t.links or {}).items()]:
        url = str(url or "")
        if url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            out.append(f'<a href="{_e(url)}" target=_blank rel=noopener>{_e(label)} ↗</a>')
    return ('<small class=watch>Check the stream: ' + " · ".join(out) + '</small>' if out else
            '<small class=watch>No link is saved for this stream.</small>')


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


def _game_box(c: Dict[str, Any], week: Any, store: Any, igdb: bool) -> str:
    """A stream chunk's game: which one the stream has (with its genres and year once IGDB knew it) and the
    way to set it by hand: a box to type it (the page's known-games list suggests), "Set game", and the IGDB
    search with its results as buttons (``c["found"]`` and the words searched ``c["found_q"]``, put there by
    the "findgame" action; the box keeps those words while the results show). ``igdb``: can IGDB be asked (the Twitch keys are set)? "" until a stream is picked."""
    cid = c["id"]
    _, t = tall._tile_of(c.get("ref") or "", week)
    if t is None:
        return ""
    if t.game:
        info = gameinfo.cached(store, t.game)
        extra = " · ".join(x for x in (", ".join(info.get("genres") or []), str(info.get("year") or "")) if x)
        have = f'<b>{_e(t.game)}</b>' + (
            f' <small>{_e(extra)}</small>' if extra else
            "" if info or t.game.lower() in games.NON_GAMES else " <small>(no details from IGDB yet: search to pick the right entry)</small>")
    else:
        have = '<span class=bad>none found</span> <small>the title didn\'t name a game the bot knows</small>'
    rows = ""
    for i, g in enumerate(c.get("found") or []):
        meta = " · ".join(x for x in (str(g.get("year") or ""), ", ".join(g.get("genres") or [])) if x)
        rows += (f'<button name=action value="pickgame:{cid}:{i}" class="alt pick"><b>{_e(g.get("name"))}</b>'
                 + (f' <span>{_e(meta)}</span>' if meta else "")
                 + (f'<small>{_e(gameinfo._cut(g.get("summary"), 140))}</small>' if g.get("summary") else "") + '</button>')
    found = f'<div class=found><small>IGDB found these; press the right one:</small>{rows}</div>' if rows else ""
    search = (f'<button name=action value="findgame:{cid}" class=alt>🔎 Search IGDB</button>' if igdb else "")
    return (f'<div class=gamebox data-nolive>{_watch_links(t)}<span class=gamehave>Game: {have}</span>'
            f'<p><input name="{cid}__gamename" list=known-games value="{_e(c.get("found_q") if rows else t.game)}" placeholder="type the game\'s name" '
            f'maxlength=100 data-enter="setgame:{cid}" autocomplete=off> '
            f'<button name=action value="setgame:{cid}" class=alt>Set game</button> {search}</p>'
            f'<small>Set game keeps it for this stream and for this title next time (an empty box = no game). '
            + ("Search looks up what is in the box; with the box empty it tries the stream's title."
               if igdb else "Searching IGDB needs the Twitch keys (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET).")
            + f'</small>{found}</div>')


def _fields(c: Dict[str, Any], p: Dict[str, Any], week: Any, lines: List[str], store: Any = None, igdb: bool = False) -> str:
    t, cid = c["type"], c["id"]
    if t == "header":
        return (f'<label>Title <input name="{cid}__title" value="{_e(c.get("title"))}" placeholder="(the article heading)"></label>'
                f'<label>Line under it <input name="{cid}__sub" value="{_e(c.get("sub"))}" placeholder="(the date range)"></label>')
    if t in ("host", "footer"):
        side = (f'<label>Side <select name="{cid}__side">{_opts(tall.SIDES.items(), c.get("side") or "left")}</select></label>'
                if t == "host" else "")
        what = "sign-off" if t == "footer" else "line"
        return (_picture_menus(c, p) + side + _line_field(c, "line", lines, "Line from the article") + _choices(c)
                + f'<p class=steer>{_hint_field(c)}</p>'
                f'<p><button name=action value="ai:{cid}" class=alt>✨ Write the {what}</button> '
                f'<small>(KoboldCpp reads the other chunks of this picture and writes a few that sum it up; '
                f'the page waits for it)</small></p>')
    if t == "hero":
        return (f'<label>Small word on top <input name="{cid}__top" value="{_e(c.get("top"))}"></label>'
                f'<label>Big title <input name="{cid}__title" value="{_e(c.get("title"))}" placeholder="(the host\'s first name)"></label>'
                f'<label>Under it <input name="{cid}__sub" value="{_e(c.get("sub"))}" placeholder="(the host\'s job)"></label>'
                f'<label>Tagline <input name="{cid}__tag" value="{_e(c.get("tag"))}" placeholder="(the date range)"></label>'
                + _picture_menus(c, p))
    if t == "chat":
        hopts = [("", "The stack's host")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
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
            pick = (f'<label>Stream <select name="{cid}__ref">{_opts(refs, c.get("ref") or "")}</select></label>'
                    + (_game_box(c, week, store, igdb) if store is not None else ""))
        else:
            rows = recipes.game_rows(p.get("facts") or {}, week)
            names = [("", "(pick a game)")] + [(r["game"], r["game"]) for r in rows]
            pick = f'<label>Game <select name="{cid}__game">{_opts(names, c.get("game") or "")}</select></label>'
        looks = (f'<label>Look <select name="{cid}__look">{_opts(tall.LOOKS.items(), c.get("look") or "")}</select></label>'
                 if t == "stream" else "")
        ticks = "".join(f'<label class=tick><input type=checkbox name="{cid}__show_{k}" value=1'
                        f'{" checked" if tall.shown(c, k) else ""}> {_e(n)}</label>' for k, n in tall.SHOW[t].items())
        more = _picture_menus(c, p) if tall.shown(c, "host") else ""
        # what ✨ writes about: a reaction, or the game itself; plus a few words of the owner's to work in
        about = recipes.ABOUT if t == "stream" else recipes.ABOUT_GAME
        steer = (f'<p class=steer><label>The remark is about <select name="{cid}__about">'
                 f'{_opts(about.items(), c.get("about") or "")}</select></label> {_hint_field(c)}</p>')
        return (pick + looks + f'<p class=ticks><input type=hidden name="{cid}__showed" value=1>{ticks}</p>' + more
                + _line_field(c, "line", lines, "Remark") + _choices(c) + steer
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


def page(p: Dict[str, Any], dkey: str, tid: str, week: Any, store: Any, saved: str = "", igdb: bool = False) -> str:
    """The builder page. ``igdb``: can IGDB be searched (poster.game_info is ready)? Shows the game box's
    search button."""
    whole, p = p, recipes.as_tall(p, tid)         # the chunks see the picture's own host style; ``whole`` = the draft
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
            f'{_fields(c, p, week, lines, store, igdb)}{_figure_controls(c, p)}'
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
    # the game boxes' suggestions: every game the bot has seen someone play
    known = "".join(f'<option value="{_e(g)}">' for g in store.known_games()[:KNOWN_MAX])
    home = f'day{p["talls"][tid]["day"]}' if p["talls"][tid].get("day") is not None else tid   # a day's own tall picture
    back = f'/settings/article?group={quote(p["group"])}&which={quote(p["which"])}#s-{home}'
    pic = f'/settings/tall/picture?d={quote(dkey)}&t={tid}&v={article_editor.stamp(p, tid)}'
    # data-live: the form saves itself and the parts marked data-swap are refreshed (flavrpromo/panel.py SCRIPT);
    # the chunk list is a data-draglist: dropping a card posts action=order with the ids in the hidden "order"
    every = f'/settings/talls?group={quote(p["group"])}&which={quote(p["which"])}'
    body = (f'<p><a href="{every}">← all tall pictures</a> · <a href="{back}">the article it belongs to</a></p>'
            f'<form method=post action=/settings/tall data-live data-foldkey="{_e(dkey)}:{_e(tid)}">'
            f'<input type=hidden name=d value="{_e(dkey)}"><input type=hidden name=t value="{_e(tid)}">'
            f'<input type=hidden name=order value="">'
            f'<div data-swap=always data-swap-id=meter>{meter}</div>'
            f'<p><button name=action value=save>Save and preview</button> <span class=livestatus>Changes save and '
            f'redraw on their own.</span> <button type=button class=link data-foldall=close>Fold all</button><button type=button class=link data-foldall=open>Open all</button></p>'
            f'<div class=prev data-swap=always data-swap-id=prev><a href="{pic}" target=_blank title="open full size">'
            f'<img src="{pic}" alt="preview"></a><p class=prevtools><button type=button class=link data-redraw>↻ Redraw</button> '
            f'<a href="{pic}" download="{_e(tid)}.png">⬇ Save the picture</a></p></div>'
            f'<div data-swap=always data-swap-id=look>{_look_card(whole, tid)}</div>'
            f'<div class=chunks data-swap=rebuild data-swap-id=chunks data-draglist>{"".join(blocks)}</div>{tools}'
            f'<datalist id=known-games>{known}</datalist></form>'
            # ✨ on one chunk waits for KoboldCpp: show it's working instead of a page that looks stuck
            "<script>document.querySelector('form[data-live]').addEventListener('submit',e=>{const b=e.submitter;"
            "if(b&&/^ai:/.test(b.value)){b.textContent='✨ writing… (up to a minute)';"
            "setTimeout(()=>document.querySelectorAll('button').forEach(x=>x.disabled=true),0)}});"
            # Enter in a box with data-enter presses that box's own button (the game box: "Set game"), not Save
            "document.querySelector('form[data-live]').addEventListener('keydown',e=>{const t=e.target;"
            "if(e.key==='Enter'&&t.dataset&&t.dataset.enter){e.preventDefault();"
            "const b=t.form.querySelector('button[value=\"'+t.dataset.enter+'\"]');if(b)b.click()}});"
            # ↻ Redraw: fetch the preview again (a new address, so nothing cached is shown)
            "document.addEventListener('click',e=>{const b=e.target.closest('[data-redraw]');if(!b)return;"
            "const i=document.querySelector('.prev img');i.src=i.src.replace(/&r=\\d+$/,'')+'&r='+Date.now()});</script>")
    style = (".meter{height:14px;background:#0e0f14;border-radius:8px;overflow:hidden}.meter div{height:100%;background:#2ae0d4}"
             ".meter.over div{background:#e5312f}.bad{color:#ff7a7a;font-weight:bold}"
             ".prev img{width:100%;border-radius:8px;border:2px solid #3d2a3b;display:block;margin:10px 0}.prev{max-width:520px}"
             ".chunk label{display:inline-block;margin:6px 10px 6px 0}.chunk select{width:auto}"
             ".ticks label.tick,.choices label.tick{margin:2px 14px 2px 0;font-size:15px}.choices label.tick{display:block}"
             ".fig{border-top:1px dashed #3d2a3b;margin-top:8px;padding-top:6px}.fig small{display:block}"
             ".chunk textarea{display:block}.chunk input:not([type]){width:min(480px,90%)}.tools p{margin:8px 0}"
             ".gamebox{border:1px dashed #3d2a3b;border-radius:8px;padding:8px 10px;margin:6px 0}.gamebox p{margin:6px 0}"
             ".gamebox small{display:block}.gamehave small{display:inline}.gamebox input:not([type]){width:300px;max-width:55%}"
             ".found .pick{display:block;width:100%;text-align:left;margin:4px 0;font-weight:400}.found .pick span{opacity:.8}"
             ".steer label.hint{display:block}.steer input:not([type]){width:min(520px,100%)}"
             ".gamebox small.watch{margin-bottom:6px}.prevtools{margin:0 0 10px}.prevtools a{margin-left:14px}"
             ".lookcard label{display:inline-block;margin:6px 14px 6px 0}.lookcard select{width:auto}.lookcard small{display:block}"
             ".sw{display:inline-flex;gap:3px;vertical-align:middle;margin-left:6px}.sw i{width:14px;height:14px;border-radius:50%;"
             "border:1px solid #0006;display:inline-block}"
             "@media(min-width:1100px){.prev{position:sticky;top:8px;float:right;margin-left:20px;width:420px;"
             "max-height:calc(100vh - 16px);overflow:auto}form .chunks,form .tools,form [data-swap-id=look]{margin-right:450px}}")
    return frame("Tall picture", "🧱 Tall picture builder", body, saved, style=style, tab=LIST_TAB)


def _look_card(p: Dict[str, Any], tid: str) -> str:
    """The Look card: what holds for the whole stack (owner 2026-11-22: "a way to change the stack style and
    color scheme would be great for the stack editor"). ``p`` = the draft itself (not ``recipes.as_tall``).
      Colours      this picture's own colour scheme (name "scheme_<part>", the same entry the article editor's
                   menu for this picture sets; article_editor.scheme_part)
      Host style   whose lettering, colours and pictures the stack is drawn in (name "stack_host"; "" = the
                   article's host); chunks set to "the article's host" follow it
      Bottom edges one kind of seam for every chunk at once (name "stack_seams" + the "seams" button)
      Streams      the plain row or the day pictures' colour strip for every stream chunk (name "stack_look" +
                   the "looks" button; each stream chunk also has its own Look menu)"""
    q = recipes.as_tall(p, tid)
    part = article_editor.scheme_part(p, tid)
    hopts = [("", f"The article's host ({hosts.HOSTS[p['host']]['name']})")] + [(k, h["name"]) for k, h in hosts.HOSTS.items()]
    seams = [(k, v.replace(" seams", "")) for k, v in recipes.SEAMS.items()]
    return (f'<details class="card lookcard" id=look open><summary><b>🎨 Look of the whole stack</b> '
            f'<span class=what>colours, host style, bottom edges, stream look</span></summary><div class=inner>'
            f'{article_editor._scheme_menu(q, part)} '
            f'<label>Host style <select name=stack_host>{_opts(hopts, p["talls"][tid].get("host") or "")}</select></label> '
            f'<span data-nolive><label>Bottom edges <select name=stack_seams>{_opts(seams, "")}</select></label>'
            f'<button name=action value=seams class=alt>Set every edge</button></span> '
            f'<span data-nolive><label>Streams <select name=stack_look>{_opts(tall.LOOKS.items(), "")}</select></label>'
            f'<button name=action value=looks class=alt>Set every stream</button></span>'
            f'<small>Each chunk still has its own colour and bottom edge below. For another layout, use '
            f'“Start from this stack” at the bottom of the page.</small></div></details>')


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
    if t == "header":                           # only boxes that were sent: a post without them keeps the title
        for f in ("title", "sub"):
            if get(f) is not None:
                c[f] = " ".join(str(get(f)).split())[:120]
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
        ref = get("ref") if get("ref") in {x["ref"] for x in tall.tile_choices(week)} else ""
        if ref != (c.get("ref") or ""):
            c.pop("found", None), c.pop("found_q", None)                # the game search results belonged to the other stream
        c["ref"] = ref
    if t == "game" and get("game") is not None:
        c["game"] = get("game") if get("game") in {r["game"] for r in recipes.game_rows(p.get("facts") or {}, week)} else ""
    if t in recipes.LINE_TYPES + recipes.SUMMARY_TYPES and get("hint") is not None:     # the owner's few words for ✨
        c["hint"] = " ".join(str(get("hint")).split())[:recipes.HINT_MAX]
    if t == "stream" and get("look") is not None:       # the plain row or the colour strip (tall.LOOKS)
        c["look"] = get("look") if get("look") in tall.LOOKS else ""
    if t in recipes.LINE_TYPES:
        if get("about") is not None:            # what ✨ writes about (recipes.ask_kind)
            c["about"] = "game" if get("about") == "game" else ""
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
    # a ✨ choice picked (radio): it goes in the box, unless the box itself was edited in the same save. Only a
    # radio that CHANGED counts ("chosen" = the one the page was drawn with, ``_choices``): the old one stays
    # ticked in the browser while the owner types their own words, and must not come back over them.
    got, n = c.get("choices") or [], str(get("choice") or "")
    if (n.isdigit() and int(n) < len(got) and n != str(get("chosen") or "") and got[int(n)] != before
            and c.get("line") == before):
        c["line"] = got[int(n)]


def _tidy_old(chunks: List[Dict[str, Any]]) -> None:
    """Clean the lines KoboldCpp wrote before kobold.tidy knew a mark (a "]" in front, a whole list inside
    one line): each chunk's ✨ choices, and its line when the line is one of them. The owner's own words
    (a line that is none of the choices) are never touched. Called when a tall picture is loaded."""
    for c in chunks:
        old = [str(x) for x in c.get("choices") or []]
        new = [kobold.tidy(x) or x for x in old]
        if new != old:
            if c.get("line") in old:
                c["line"] = new[old.index(c["line"])]
            c["choices"] = new


def talls_page(poster: Any, group: str, which: str, p: Any, week: Any, saved: str = "") -> str:
    """The list page /settings/talls: pick a group and a week, see that week's tall pictures (each with
    "Edit the chunks", save and remove) and make a new one from a stack or a recipe. ``p``: the week's
    article draft, None when there is none yet (making a picture makes it)."""
    store = poster.store
    dkey = article_editor.draft_key(group, which)
    gopts = _opts([(g, groups.name(g)) for g in groups.keys()], group)
    wopts = _opts([(w, t) for w, t, _, _ in article_editor.WHICH], which)
    picker = (f'<form method=get action=/settings/talls class=row><label>Group <select name=group>{gopts}</select></label>'
              f'<label>Week <select name=which>{wopts}</select></label><button>Open</button></form>')
    cards = []
    talls = (p or {}).get("talls") or {}
    titles = {s["id"]: s for s in (p or {}).get("sections") or []}
    for tid in sorted(talls, key=lambda k: int(k[4:]) if k[4:].isdigit() else 0):
        chunks = talls[tid].get("chunks") or []
        day = talls[tid].get("day")
        sec = titles.get(tid)
        if day is not None:                       # made for a day of the article (article_editor.ensure_day_talls)
            title, where = f"{week.date_of(int(day)).strftime('%A')}'s day picture", "the article's picture for that day"
        else:
            title = (sec or {}).get("title") or tid
            where = "in the article" if (sec or {}).get("on") else "not in the article (tick it in the article editor to add it)"
        pic = f'/settings/tall/picture?d={quote(dkey)}&t={tid}&v={article_editor.stamp(p, tid)}'
        edit = f'/settings/tall?d={quote(dkey)}&t={tid}'
        remove = ("" if day is not None else
                  f' <button name=action value="remove:{tid}" class=alt>Remove</button>')
        cards.append(
            f'<div class=tallcard><a href="{edit}"><img src="{pic}" alt="" loading=lazy></a><div><b>{_e(title)}</b>'
            f'<small>{len(chunks)} chunks · {tall.total(chunks)} px tall · {_e(where)}</small>'
            f'<p><a href="{edit}"><b>✏️ Edit the chunks</b></a> <a href="{pic}" download="{_e(tid)}.png">⬇ Save the picture</a>'
            f'{remove}</p></div></div>')
    have = "".join(cards) or "<p><small>No tall pictures for this week yet. Make one below.</small></p>"
    article = f'/settings/article?group={quote(group)}&which={quote(which)}'
    body = (f'{picker}<form method=post action=/settings/talls>'
            f'<input type=hidden name=group value="{_e(group)}"><input type=hidden name=which value="{_e(which)}">'
            f'<section><h2>This week\'s tall pictures</h2>{have}</section>'
            f'<section><h2>Make a new one</h2><p class=help>It opens in the builder straight away. A picture made here '
            f'is for a post of its own: it stays out of <a href="{article}">the article</a> until you tick it there.</p>'
            f'{article_editor._recipe_row(week, store)}</section></form>')
    style = (".tallcard{display:flex;gap:16px;align-items:flex-start;border:1px solid #3d2a3b;border-radius:10px;"
             "padding:10px;margin:10px 0}.tallcard img{width:150px;max-height:200px;object-fit:cover;object-position:top;"
             "border-radius:6px;display:block}.tallcard small{display:block;margin:4px 0}.tallcard a{margin-right:12px}"
             ".row{display:flex;gap:12px;flex-wrap:wrap;align-items:end}.row label{margin:0}.row select{width:auto}"
             ".recipe select,.recipe input{width:auto}.recipe label{display:inline-block;margin:0 6px}")
    return frame("Tall pictures", LIST_TAB, body, saved, style=style)


def _apply_look(p: Dict[str, Any], tid: str, form: Any) -> None:
    """Take the Look card's menus from the posted form (``_look_card``): the stack's host style and this
    picture's colour scheme. Unknown values are ignored; a form without them changes nothing."""
    if "stack_host" in form:
        v = str(form.get("stack_host") or "")
        p["talls"][tid]["host"] = v if v in hosts.HOSTS and v != p["host"] else ""
    part = article_editor.scheme_part(p, tid)
    if f"scheme_{part}" in form:                # "" = the article's choice, "host" = the host's own colours
        v, host = str(form.get(f"scheme_{part}") or ""), recipes.as_tall(p, tid)["host"]
        if v == "host" or (schemes.get(v) and v != host):
            p.setdefault("schemes", {})[part] = v
        else:
            p.setdefault("schemes", {}).pop(part, None)


def _set_game(store: Any, t: Any, game: str) -> str:
    """Set stream ``t``'s game by hand (flavrpromo/games.py ``set_stream``); the note for the page."""
    if not t.person_id:
        return "That stream isn't one of this bot's people, so its game can't be set here."
    sid = hosts._session_id(store, t) if t.kind in ("past", "live") else None
    game = games.set_stream(store, t.person_id, t.title, game, sid, live=t.kind == "live")
    if not game:
        return f"{t.name}'s stream has no game now."
    return f"{t.name}'s stream is {game} now" + (", and that title means it from now on." if t.title else ".")


async def _find_games(gi: Any, typed: str, title: str) -> Any:
    """IGDB's games for the game box: what was typed, else the stream's title part by part (TITLE_PARTS
    requests at most). (rows, what was searched); rows None = IGDB couldn't be asked."""
    asked = [typed] if typed else games.parts(title)[:TITLE_PARTS]
    rows, reached = [], False
    for text in asked:
        got = await gi.search(text)
        if got is None:
            continue
        reached = True
        rows += [g for g in got if g["name"].lower() not in {x["name"].lower() for x in rows}]
    return (rows[:gameinfo.SEARCH_MAX] if reached else None), (typed or "the stream's title")


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store
    game_info = lambda: getattr(poster, "game_info", None)       # noqa: E731  (set after the routes, __main__.py)
    igdb = lambda: bool(getattr(game_info(), "ready", False))    # noqa: E731

    def _load(dkey: str, tid: str) -> Dict[str, Any]:
        p = store.get(dkey) if dkey.startswith(article_editor.PREFIX) else None
        if not p or tid not in (p.get("talls") or {}):
            raise web.HTTPNotFound(text="That tall picture isn't in a draft any more.")
        article_editor.migrate(p)
        _tidy_old(p["talls"][tid].get("chunks") or [])
        return p

    def _back(dkey: str, tid: str, note: str, anchor: str = "") -> web.HTTPSeeOther:
        return web.HTTPSeeOther(f"/settings/tall?d={quote(dkey)}&t={quote(tid)}&saved={quote(note)}"
                                + (f"#{anchor}" if anchor else ""))

    async def get(request: web.Request) -> web.Response:
        dkey, tid = request.query.get("d", ""), request.query.get("t", "")
        p = _load(dkey, tid)
        week, _ = await article_editor._article(poster, p)
        return web.Response(text=page(p, dkey, tid, week, store, request.query.get("saved", ""), igdb()),
                            content_type="text/html")

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        dkey, tid = str(form.get("d") or ""), str(form.get("t") or "")
        p = _load(dkey, tid)
        week, _ = await article_editor._article(poster, p)
        chunks: List[Dict[str, Any]] = p["talls"][tid]["chunks"]
        whole = p                               # the draft itself: what is saved
        _apply_look(whole, tid, form)           # the Look card first: the chunks' menus depend on the host style
        p = recipes.as_tall(whole, tid)         # ... and this is the draft as the picture sees it (its own host)
        for c in chunks:
            _apply(c, form, p, week)
        verb, _, cid = str(form.get("action") or "save").partition(":")
        cid, _, arg = cid.partition(":")        # "pickgame:c3:0": the chunk, then which search result
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
        elif verb == "seams":                   # the Look card: one kind of bottom edge for every chunk
            recipes.apply_seams(chunks, str(form.get("stack_seams") or ""))
            note = "Set every bottom edge."
        elif verb == "looks":                   # the Look card: the plain row or colour strips for every stream chunk
            recipes.apply_look(chunks, str(form.get("stack_look") or ""))
            note = "Set every stream's look." if any(x["type"] == "stream" for x in chunks) else "This stack has no stream chunks."
        elif verb == "ai" and i >= 0 and chunks[i]["type"] not in recipes.LINE_TYPES + recipes.SUMMARY_TYPES:
            note = "That kind of chunk has no ✨."
        elif verb == "ai" and i >= 0:           # ✨ one chunk's remark / line: a few to pick from (the page waits)
            got, note = await recipes.write_choices(poster, p, week, chunks[i], chunks)
            if got:
                chunks[i]["choices"], chunks[i]["line"] = got, got[0]
            anchor = cid
        elif verb in ("setgame", "findgame", "pickgame") and i >= 0 and chunks[i]["type"] == "stream":
            # the game box of a stream chunk (``_game_box``): typed, searched on IGDB, or picked from the search
            c, anchor = chunks[i], cid
            _, t = tall._tile_of(c.get("ref") or "", week)
            typed = " ".join(str(form.get(f"{cid}__gamename") or "").split())[:100]
            found = c.get("found") or []
            if t is None:
                note = "Pick a stream for that chunk first."
            elif verb == "setgame":
                note = _set_game(store, t, typed)
                c.pop("found", None), c.pop("found_q", None)
                if typed and igdb():            # its genres and summary, for the chunk and the remarks
                    await recipes._details(poster, typed)
            elif verb == "pickgame" and arg.isdigit() and int(arg) < len(found):
                if game_info() is not None:     # its details, as IGDB gave them with the search
                    game_info().keep(found[int(arg)])
                note = _set_game(store, t, found[int(arg)]["name"])
                c.pop("found", None), c.pop("found_q", None)
            elif verb == "findgame" and not igdb():
                note = "Searching IGDB needs the Twitch keys (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)."
            elif verb == "findgame":
                rows, what = await _find_games(game_info(), typed, t.title)
                if rows is None:
                    note = "IGDB couldn't be reached. Try again in a moment, or type the game and press Set game."
                elif not rows:
                    c.pop("found", None), c.pop("found_q", None)
                    note = f"IGDB found no game for {what}. Type the name as its store page spells it and search again."
                else:
                    c["found"], c["found_q"] = rows, typed
                    note = f"IGDB found {len(rows)} for {what}. Press the right one."
        elif verb == "aiall":
            store.put(dkey, whole)              # the posted menus first, then the writer re-reads the draft
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
        whole["saved_at"] = time.time()
        store.put(dkey, whole)
        raise _back(dkey, tid, note, anchor)

    async def picture(request: web.Request) -> web.Response:
        """The tall picture itself, drawn with Chromium at its real height."""
        dkey, tid = request.query.get("d", ""), request.query.get("t", "")
        p = _load(dkey, tid)
        if poster.shooter is None:
            raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
        week, _ = await article_editor._article(poster, p)
        await poster.images.fetch_all(week)
        p = recipes.as_tall(p, tid)             # the picture's own host style, when it has one
        f = p.get("facts") or {}
        chunks = p["talls"][tid]["chunks"]
        ctx = {"host": p["host"], "week": week, "img": poster.images.data_url, "facts": f, "notes": p.get("notes"),
               "heading": host_picker.heading_of(p, "Week in Review"), "range": f.get("range") or "",
               "seed": p.get("seed"), "pins": p.get("pins"), "scheme": article_editor.scheme_for(p, tid),
               **recipes.drawing_context(store, p, week, chunks)}
        png = await poster.shooter.png(tall.document(chunks, ctx), size=(tall.WIDTH, max(1, tall.total(chunks))))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    def _which_week(q: Any) -> Any:
        """(group, which) from a query or form, as the article editor reads them."""
        return (groups.find(str(q.get("group") or "")) or "flavr",
                article_editor._which(str(q.get("which") or ""))[0])

    async def talls_get(request: web.Request) -> web.Response:
        """The list page: this week's tall pictures and "make a new one" (``talls_page``)."""
        group, which = _which_week(request.query)
        p = store.get(article_editor.draft_key(group, which))
        if p:
            article_editor.migrate(p)
        _, _name, label, off = article_editor._which(which)
        week, _ = await article_editor._article(poster, p or {"group": group, "label": label, "off": off})
        return web.Response(text=talls_page(poster, group, which, p, week, request.query.get("saved", "")),
                            content_type="text/html")

    async def talls_post(request: web.Request) -> web.Response:
        """Make a tall picture for a week without going through the article editor (the week's article
        draft is made quietly when there is none: a tall picture lives in it), or remove one. A new
        picture's section is off, so it is not part of the article. Then straight to the builder."""
        form = await request.post()
        group, which = _which_week(form)
        dkey = article_editor.draft_key(group, which)
        p = store.get(dkey) or await article_editor.new_draft(poster, group, which)
        article_editor.migrate(p)
        week, _ = await article_editor._article(poster, p)
        verb, _, tid = str(form.get("action") or "").partition(":")
        here = f"/settings/talls?group={quote(group)}&which={quote(which)}&saved="
        ids: List[str] = []
        if verb == "remove" and tid in p["talls"] and p["talls"][tid].get("day") is None:
            p["talls"].pop(tid)
            p["sections"] = [s for s in p["sections"] if s["id"] != tid]
            (p.get("schemes") or {}).pop(tid, None)
            store.put(dkey, p)
            raise web.HTTPSeeOther(here + quote("Removed that tall picture."))
        if verb == "add_tall":                  # from a built-in or saved stack, this week's streams / games filled in
            kind, _, name = str(form.get("tall_stack") or "b:Week overview").partition(":")
            src = (tall.BUILTIN.get(name) if kind == "b" else (store.get(TEMPLATES_KEY) or {}).get(name)) \
                or tall.BUILTIN["Week overview"]
            chunks = tall.renumber(src)
            recipes.fill(chunks, p, week)
            ids = recipes.add_to_draft(p, [(name or "Tall picture", chunks)], on=False)
        elif verb == "add_recipe":              # a whole picture (or several) from the week: flavrpromo/recipes.py
            recipe = str(form.get("recipe") or "")
            arg = str(form.get("recipe_day") if recipe == "day" else form.get("recipe_person") or "")
            built, err = recipes.build(recipe, p, week, arg, str(form.get("recipe_seams") or ""), str(form.get("recipe_look") or ""))
            if err:
                raise web.HTTPSeeOther(here + quote(err))
            ids = recipes.add_to_draft(p, built, on=False)
        if not ids:
            raise web.HTTPSeeOther(here + quote("Pick what to make."))
        p["saved_at"] = time.time()
        store.put(dkey, p)
        note = ("Made it. Build it here; it is saved as you go." if len(ids) == 1 else
                f"Made {len(ids)} pictures (it was too much for one). This is the first; the others are on the Tall pictures page.")
        raise _back(dkey, ids[0], note)

    app.router.add_get("/settings/talls", talls_get)
    app.router.add_post("/settings/talls", talls_post)
    app.router.add_get("/settings/tall", get)
    app.router.add_post("/settings/tall", post)
    app.router.add_get("/settings/tall/picture", picture)


__all__ = ["add_routes", "page", "talls_page", "line_options"]
