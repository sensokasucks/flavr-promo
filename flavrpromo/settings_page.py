"""
The settings page: http://<this PC>:3871/settings (owner 2026-11-21: "a local web page to set that
kobold URL and maybe other tweaks that'd be troublesome to do over Discord commands").

All the settings pages are drawn in the panel shell (flavrpromo/panel.py: menu on the left, tabs
across the top): this file holds the Bot > Settings, Hosts > Pictures and Hosts > Host lines tabs;
character cards (card_page.py), the article editor (article_editor.py), the line picker
(host_picker.py) and the command forms (command_forms.py) are the others.

Tabs and sections (each its own form; a save redirects back with a note):
  KoboldCpp   address, password (never shown back), creativity (temperature) and lines per slot,
              a Test button that asks KoboldCpp for its model. Saved in kv "kobold"; it wins over
              KOBOLD_URL / KOBOLD_KEY from the environment (an empty address there = off).
  Hosts       on / off and "take turns" or always one host: the same kv as /host setup
              (hosts_on, hosts_only); "post go-live cards as the host" (kv hosts_webhook, default on,
              flavrpromo/host_webhooks.py; needs the bot's Manage Webhooks in the live channels); how
              long the Sunday board waits for the week-ahead picks (kv host_preview_wait, hours); the
              recap picture on ended go-live cards (kv host_recap_card, default on); boards in the
              host's look (kv host_board, default on).
  Pictures    (/settings/pictures) a folding card per host, in it the picture kinds in groups
              (PICTURE_GROUPS: regular poses, chibi, heads), each kind a row of thumbnails: the main
              picture (replace it, the same as /host picture; "back to built-in" deletes the upload)
              plus its POOL of extra pictures (add several at once, drop files on the row, remove
              one; flavrpromo/hosts.py ``variants``): posts pick from the pool at random. The forms
              are "quick forms" (flavrpromo/panel.py): with the script the row updates in place.
  Lines       (/settings/lines) every template slot for both hosts as a text box, one line per row; a blank that
              isn't in hosts.BLANKS is refused, an emptied box goes back to the built-in lines.
              Saved in kv "host_templates" (flavrpromo/hosts.py ``load_overrides``).

No password, like the rest of port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/__main__.py (``apply`` at start, ``add_routes`` on the web server).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from urllib.parse import quote

from aiohttp import web

from . import host_picker, hosts, kobold
from .panel import _e, frame      # re-exported: card_page, article_editor and command_forms import them from here
from .kobold import PER_SLOT, Kobold

log = logging.getLogger("flavrpromo.settings_page")


def kobold_settings(poster: Any) -> Dict[str, Any]:
    """The KoboldCpp settings in force: the page's (kv "kobold") over the environment's."""
    env = getattr(poster, "kobold_env", {}) or {}
    saved = poster.store.get("kobold") or {}
    out = {"url": env.get("url", ""), "key": env.get("key", ""), "temperature": 0.8, "per_slot": PER_SLOT}
    out.update({k: v for k, v in saved.items() if k in out})
    return out


def apply(poster: Any) -> None:
    """Make poster.kobold match the settings (None = off) and load the edited host lines, character
    cards and slot asks (flavrpromo/card_page.py)."""
    k = kobold_settings(poster)
    http = getattr(poster, "http", None)
    poster.kobold = Kobold(http, k["url"], k["key"], float(k["temperature"]), int(k["per_slot"])) \
        if k["url"] and http is not None else None
    hosts.load_overrides(poster.store)
    kobold.load_card_overrides(poster.store)


# which tab a save goes back to ("pictures" and "lines" moved to their own tabs, others stay on Settings)
_TAB_OF = {"pictures": "/settings/pictures", "lines": "/settings/lines"}


def _back(note: str, anchor: str = "") -> web.HTTPSeeOther:
    if anchor in _TAB_OF:
        return web.HTTPSeeOther(f"{_TAB_OF[anchor]}?saved={quote(note)}")
    return web.HTTPSeeOther(f"/settings?saved={quote(note)}" + (f"#{anchor}" if anchor else ""))


def page(poster: Any, saved: str = "", test: str = "") -> str:
    store = poster.store
    k = kobold_settings(poster)
    only = str(store.get("hosts_only") or "")
    on = bool(store.get("hosts_on"))
    as_host = store.get("hosts_webhook") is not False      # flavrpromo/host_webhooks.py SETTING, default on
    wait = host_picker.preview_wait(store)
    recap_on = store.get("host_recap_card") is not False   # flavrpromo/bot.py _recap_png, default on
    board_on = store.get("host_board") is not False        # flavrpromo/calendar_post.py board_host, default on                  # kv host_preview_wait (hours, 0 = for ever)
    # KoboldCpp
    kob = (f'<section id=kobold><h2>✨ KoboldCpp (AI lines)</h2>'
           f'<p class=help>Lines in each host\'s voice on the review picker page. Empty address = template lines only.</p>'
           f'<form method=post action=/settings/kobold>'
           f'<label>Address <input name=url value="{_e(k["url"])}" placeholder="http://192.168.1.50:5001"></label>'
           f'<label>Password <input name=key type=password placeholder="{"(set, leave empty to keep)" if k["key"] else "only with --password"}">'
           f'</label><label><input type=checkbox name=clear_key value=1> remove the password</label>'
           f'<label>Creativity <input name=temperature type=number min=0.1 max=1.5 step=0.05 value="{_e(k["temperature"])}">'
           f' <small>0.5 plain … 1.2 wild</small></label>'
           f'<label>Lines per slot <input name=per_slot type=number min=1 max=6 value="{_e(k["per_slot"])}"></label>'
           f'<p><button name=action value=save>Save</button> <button name=action value=test>Save and test</button></p>'
           + (f'<p class=test style="white-space:pre-wrap">{_e(test)}</p>' if test else "") + '</form></section>')
    # hosts on / off
    opts = [("", "Take turns (random, never 3 in a row)")] + [(key, f"Always {h['name']}") for key, h in hosts.HOSTS.items()]
    hst = (f'<section id=hosts><h2>🎙️ Hosts</h2><form method=post action=/settings/hosts>'
           f'<label><input type=checkbox name=on value=1{" checked" if on else ""}> Hosts on (go-live lines, day posts, '
           f'reviews wait for your picks)</label>'
           + "".join(f'<label><input type=radio name=only value="{v}"{" checked" if only == v else ""}> {_e(n)}</label>'
                     for v, n in opts)
           + f'<label><input type=checkbox name=webhook value=1{" checked" if as_host else ""}> Post go-live cards as '
           f'the host (their name and face; needs the bot\'s Manage Webhooks permission in the live channels, '
           f'otherwise the bot posts them as before)</label>'
           f'<label><input type=checkbox name=recap value=1{" checked" if recap_on else ""}> Recap picture on ended '
           f'go-live cards (the host\'s "That\'s a wrap" / stream report card in place of the stream picture)</label>'
           f'<label><input type=checkbox name=board value=1{" checked" if board_on else ""}> Draw the weekly board and '
           f'the reviews\' boards in the host\'s look (from the next new week; a review takes its host)</label>'
           f'<label>Sunday board waits <input name=preview_wait type=number min=0 max=48 step=0.5 value="{wait:g}" '
           f'style="width:5em"> hours for the week-ahead picks, then posts without the host <small>(0 = wait for ever)</small></label>'
           + '<p><button>Save</button> <a href="/hosts/pick">Open the line picker</a></p></form></section>')
    return frame("FlaVR Promo settings", "⚙️ Settings", kob + hst, saved)


# The Pictures tab's groups inside each host's card: (id, heading, picture kinds). Every kind of
# hosts.KINDS must be in exactly one group (tests/test_settings_page.py checks it).
PICTURE_GROUPS = (
    ("poses", "Regular poses", ("happy", "pointing", "sleepy", "desk")),
    ("chibi", "Chibi", ("chibi_happy", "chibi_pointing", "chibi_sleepy", "chibi_desk")),
    ("heads", "Heads (one picture each)", ("head", "chibi_head")),
)
_ACCEPT = ".png,.jpg,.jpeg,.webp"

# the Pictures tab's own CSS (the shared look, the toast and the drop mark are in flavrpromo/panel.py STYLE)
_PICTURES_STYLE = (
    "details.sub{background:#231521;margin:8px 0}details.sub>summary{padding:7px 12px}"
    # the kinds of a group sit side by side while there is room (a kind with many pictures takes its own line)
    "details.sub>.inner{display:flex;flex-wrap:wrap;gap:4px 30px}.kind{padding:8px 0;max-width:100%}"
    ".kindhead b{text-transform:capitalize}.kindhead small{display:inline;margin-left:8px}"
    ".strip{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;align-items:flex-start}"
    ".thumb{position:relative;width:104px;margin:0}.thumb img,.thumb .none,.tile{width:104px;height:104px;"
    "object-fit:contain;background:#0e0f14;border-radius:8px;border:2px solid transparent;display:flex;"
    "align-items:center;justify-content:center;color:#778}.thumb.mainpic img,.thumb.mainpic .none{border-color:var(--teal)}"
    ".thumb a{display:block}.thumb .tag{display:block;font-size:12px;color:#aab;text-align:center;margin-top:2px}"
    ".thumb .x{position:absolute;top:4px;right:4px;padding:0 7px;line-height:22px;background:#000a}"
    ".thumb .x:hover{background:var(--pink)}.thumb .row{display:flex;gap:4px;justify-content:center;flex-wrap:wrap}"
    ".thumb .row button,.thumb .row label{font-size:12px;margin:0;padding:1px 4px}"
    ".pick{color:var(--teal);cursor:pointer}.pick:hover{text-decoration:underline}"
    ".tile{flex-direction:column;border:2px dashed #4a3547;color:var(--teal);font-size:28px;margin:0;cursor:pointer}"
    ".tile small{font-size:12px;color:#aab}.tile:hover{border-color:var(--teal)}"
    # with the script a chosen file uploads at once, so the file boxes themselves are hidden behind their labels
    ".js .pick input[type=file]{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}"
    ".pick input[type=file]{width:100px;font-size:11px}")


def _kind_row(key: str, kind: str, state: str) -> str:
    """One picture kind of one host on the Pictures tab: its main picture (replace / back to built-in)
    and, for a pooled kind, the extra pictures (remove) and an "add" tile. ``state`` = hosts.pictures'
    "yours" / "built-in" / "". Everything here is a quick form (flavrpromo/panel.py): it also works as a
    plain form post, and with the script the row is swapped in place (data-swap-id pool-<host>-<kind>)."""
    hidden = f'<input type=hidden name=host value={key}><input type=hidden name=kind value={kind}>'
    url = f"/settings/picture/{key}/{kind}"

    def stamp(path: Any) -> int:           # in the picture's URL, so a replaced picture is fetched again
        try:
            return path.stat().st_mtime_ns // 1_000_000
        except OSError:
            return 0

    every = hosts.variants(key, kind) if kind in hosts.POOLED else []
    extra = [(v, path) for v, path in every if v != "main"]
    main_path = hosts.exact(key, kind)
    main_img = (f'<a href="{url}?t={stamp(main_path)}" target=_blank title="Open the picture">'
                f'<img src="{url}?t={stamp(main_path)}" loading=lazy alt=""></a>'
                if main_path is not None else '<div class=none>none</div>')
    reset = ('<button name=action value=reset class=link title="Delete your upload and use the built-in picture '
             'again">↺ Built-in</button>' if state == "yours" else "")
    main = (f'<form class="thumb mainpic" data-quick data-dropzone="main-{key}-{kind}" method=post action=/settings/picture '
            f'enctype=multipart/form-data>{hidden}{main_img}<span class=tag>main · {_e(state or "missing")}</span>'
            f'<span class=row><label class=pick>Replace<input type=file name=file id="main-{key}-{kind}" '
            f'accept="{_ACCEPT}"></label><button name=action value=upload class=nojs>Upload</button>{reset}</span></form>')
    thumbs = "".join(
        f'<form class=thumb data-quick method=post action=/settings/pool>{hidden}<input type=hidden name=vid value="{_e(v)}">'
        f'<a href="{url}?v={_e(v)}&amp;t={stamp(path)}" target=_blank title="Open the picture">'
        f'<img src="{url}?v={_e(v)}&amp;t={stamp(path)}" loading=lazy alt=""></a>'
        f'<button name=action value=remove class=x title="Remove this picture from the pool">✕</button></form>'
        for v, path in extra)
    # the group's heading already says "chibi" for the chibi poses; the two heads share a group, so they keep it
    name = (kind if kind not in hosts.POOLED else kind.replace("chibi_", "")).replace("_", " ")
    if kind not in hosts.POOLED:       # heads stay single: the go-live avatar must not change at random (hosts.py)
        count, add, zone = "single picture", "", f"main-{key}-{kind}"
    else:
        n = len(extra) + (1 if main_path is not None else 0)
        count = (f'{n} of {hosts.POOL_MAX + 1}' + (" · a post picks one at random" if n > 1 else ""))
        full = len(extra) >= hosts.POOL_MAX
        add = "" if full else (
            f'<form class=thumb data-quick method=post action=/settings/pool enctype=multipart/form-data>{hidden}'
            f'<label class="tile pick" title="Add pictures to this pool (or drop them here)">＋<small>Add pictures</small>'
            f'<input type=file name=file id="add-{key}-{kind}" accept="{_ACCEPT}" multiple></label>'
            f'<button name=action value=add class=nojs>Add to pool</button></form>')
        zone = "" if full else f"add-{key}-{kind}"
        if full:
            count += " · full, remove one to add another"
    return (f'<div class=kind data-swap=rebuild data-swap-id="pool-{key}-{kind}">'
            f'<div{f" data-dropzone={zone}" if zone else ""}><div class=kindhead><b>{_e(name)}</b>'
            f'<small>{_e(count)}</small></div><div class=strip>{main}{thumbs}{add}</div></div></div>')


def pictures_page(poster: Any, saved: str = "") -> str:
    """Hosts > Pictures (owner 2026-11-22: "go ahead and tidy up the pictures pages"): one folding card
    per host, inside it a folding group per PICTURE_GROUPS entry, inside that one row per picture kind
    (``_kind_row``): the kind's POOL (flavrpromo/hosts.py) as thumbnails. The main picture can be
    replaced or put back to the built-in one, extra pictures added and removed; the system picks one of
    a pool at random, and the article editor lets you pin one. With the panel script nothing reloads:
    a chosen or dropped file uploads at once and only that row is redrawn."""
    cards = []
    for key, h in hosts.HOSTS.items():
        have = hosts.pictures(key)
        total = sum(len(hosts.variants(key, k)) if k in hosts.POOLED else (1 if have[k] else 0) for k in hosts.KINDS)
        own = sum(1 for k in hosts.KINDS if have[k] == "yours") + sum(
            len([v for v, _ in hosts.variants(key, k) if v != "main"]) for k in hosts.POOLED)
        groups = "".join(
            f'<details class="card sub" id="pics-{key}-{gid}" open><summary><b>{_e(title)}</b></summary>'
            f'<div class=inner>{"".join(_kind_row(key, k, have[k]) for k in kinds)}</div></details>'
            for gid, title, kinds in PICTURE_GROUPS)
        cards.append(
            f'<details class=card id="pics-{key}" open><summary><b>{_e(h["emoji"])} {_e(h["name"])}</b>'
            f'<span class=what data-swap=rebuild data-swap-id="count-{key}">{total} picture{"" if total == 1 else "s"}'
            f' · {own} your own</span></summary><div class=inner>{groups}</div></details>')
    body = (f'<p class=help>PNG, JPG or WebP up to 8 MB; see-through PNG / WebP is best. The picture with the teal '
            f'frame is a kind\'s <b>main</b> picture: <i>Replace</i> swaps it for your own, <i>↺ Built-in</i> brings the '
            f'built-in one back. <b>＋ Add pictures</b> puts more pictures in the same pool (up to {hosts.POOL_MAX} '
            f'extra): a post or article picks one at random, and the article editor can pin one or re-roll. You can '
            f'also drop picture files onto a row (adds them) or onto a main picture (replaces it). ✕ deletes an '
            f'added picture.</p><p><button type=button class=link data-foldall=close>Fold all</button>'
            f'<button type=button class=link data-foldall=open>Open all</button></p>{"".join(cards)}')
    return frame("FlaVR Promo pictures", "🖼️ Pictures", body, saved, style=_PICTURES_STYLE)


def lines_page(poster: Any, saved: str = "") -> str:
    """Hosts > Host lines: every template slot of both hosts as a text box."""
    store = poster.store
    blocks = []
    for key, h in hosts.HOSTS.items():
        rows = []
        for slot, help_text in hosts.SLOT_HELP.items():
            own = slot in (store.get("host_templates") or {}).get(key, {})
            rows.append(f'<label class=slot><b>{_e(slot.replace("_", " "))}</b>{" <i>edited</i>" if own else ""}'
                        f'<small>{_e(help_text)}</small>'
                        f'<textarea name="{slot}" rows=3>{_e(chr(10).join(hosts.templates(key, slot)))}</textarea></label>')
        blocks.append(f'<form method=post action=/settings/lines><input type=hidden name=host value={key}>'
                      f'<h3>{_e(h["emoji"])} {_e(h["name"])}</h3>{"".join(rows)}'
                      f'<p><button name=action value=save>Save {_e(h["name"])}\'s lines</button> '
                      f'<button name=action value=reset>Back to built-in lines</button></p></form>')
    lines = (f'<section id=lines><h2>💬 Host lines</h2><p class=help>One line per row; the host picks one at random '
             f'(reviews: you pick on the picker page). Blanks in braces are filled in; a line whose blank has no '
             f'value is skipped. Allowed blanks: {_e(" ".join("{" + b + "}" for b in hosts.BLANKS))}. An empty box '
             f'uses the built-in lines.</p>{"".join(blocks)}</section>')
    return frame("FlaVR Promo host lines", "💬 Host lines", lines, saved)


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store

    async def get(request: web.Request) -> web.Response:
        return web.Response(text=page(poster, request.query.get("saved", ""), request.query.get("test", "")),
                            content_type="text/html")

    async def save_kobold(request: web.Request) -> web.Response:
        form = await request.post()
        k = kobold_settings(poster)
        url = str(form.get("url") or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "http://" + url
        new = {"url": url, "key": k["key"]}
        if form.get("clear_key"):
            new["key"] = ""
        elif str(form.get("key") or ""):
            new["key"] = str(form.get("key"))
        try:
            new["temperature"] = max(0.1, min(1.5, float(str(form.get("temperature") or "0.8"))))
            new["per_slot"] = max(1, min(6, int(str(form.get("per_slot") or PER_SLOT))))
        except ValueError:
            raise _back("Creativity and lines per slot must be numbers.", "kobold")
        store.put("kobold", new)
        apply(poster)
        if str(form.get("action")) == "test":
            if poster.kobold is None:
                test = "No address: KoboldCpp is off (template lines only)."
            else:
                model = await poster.kobold.status()
                test = f"✅ KoboldCpp answered: {model}" if model else "❌ No answer from KoboldCpp at that address."
                if model:
                    # a real request too (example facts, Colette's opener): reaching it isn't enough, the
                    # answer must be a line this bot can read (kobold.as_line); shows the raw answer if not
                    from .card_page import SAMPLE
                    k = poster.kobold
                    line = await k.line("colette", kobold.asks()["opener"], "week in review", kobold.facts_text(SAMPLE))
                    test += f"\n✨ Test line: {line}" if line else \
                        ("\n❌ The test request got no answer (timed out?)." if line is None else
                         f"\n❌ It answered, but not with a line the bot can read: {k.last_raw[:300]}")
            raise web.HTTPSeeOther(f"/settings?saved=Saved.&test={quote(test)}#kobold")
        raise _back("KoboldCpp settings saved." if url else "KoboldCpp is off (no address).", "kobold")

    async def save_hosts(request: web.Request) -> web.Response:
        form = await request.post()
        store.put("hosts_on", bool(form.get("on")))
        only = str(form.get("only") or "")
        store.put("hosts_only", only if only in hosts.HOSTS else "")
        store.put("hosts_webhook", bool(form.get("webhook")))   # flavrpromo/host_webhooks.py SETTING
        store.put("host_recap_card", bool(form.get("recap")))   # flavrpromo/bot.py _recap_png
        store.put("host_board", bool(form.get("board")))        # flavrpromo/calendar_post.py board_host
        try:                                                    # flavrpromo/host_picker.py preview_wait
            store.put("host_preview_wait", min(48.0, max(0.0, float(str(form.get("preview_wait") or host_picker.PREVIEW_WAIT)))))
        except ValueError:
            pass
        raise _back("Hosts saved.", "hosts")

    async def save_picture(request: web.Request) -> web.Response:
        form = await request.post()
        key, kind = str(form.get("host") or ""), str(form.get("kind") or "")
        if key not in hosts.HOSTS or kind not in hosts.KINDS:
            raise _back("Unknown picture.", "pictures")
        if str(form.get("action")) == "reset":
            hosts.remove_picture(key, kind)
            raise _back(f"{hosts.HOSTS[key]['name']}'s {kind} picture is back to the built-in one.", "pictures")
        f = form.get("file")
        if not isinstance(f, web.FileField) or not f.filename:
            raise _back("Pick a file first.", "pictures")
        err = hosts.save_picture(key, kind, f.file.read(hosts.MAX_PICTURE + 1), f.filename)
        raise _back(err or f"Saved {hosts.HOSTS[key]['name']}'s {kind} picture.", "pictures")

    async def picture(request: web.Request) -> web.Response:
        key, kind = request.match_info["host"], request.match_info["kind"]
        # only that exact kind (no fallback) on the settings page; ?v= = one extra picture of its pool
        p = hosts.exact(key, kind, request.query.get("v") or "main") if kind in hosts.KINDS else None
        if p is None:
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Cache-Control": "no-store"})

    async def save_pool(request: web.Request) -> web.Response:
        """Add (several files at once) or remove extra pictures of a kind's pool (hosts.add_to_pool)."""
        form = await request.post()
        key, kind = str(form.get("host") or ""), str(form.get("kind") or "")
        if key not in hosts.HOSTS or kind not in hosts.POOLED:
            raise _back("Unknown picture.", "pictures")
        who = f"{hosts.HOSTS[key]['name']}'s {kind.replace('_', ' ')}"
        if str(form.get("action")) == "remove":
            gone = hosts.remove_from_pool(key, kind, str(form.get("vid") or ""))
            raise _back(f"Removed a picture from {who}." if gone else "That picture was already gone.", "pictures")
        files = [f for f in form.getall("file", []) if isinstance(f, web.FileField) and f.filename]
        if not files:
            raise _back("Pick one or more files first.", "pictures")
        done, errs = 0, []
        for f in files:
            err = hosts.add_to_pool(key, kind, f.file.read(hosts.MAX_PICTURE + 1), f.filename)
            if err:
                errs.append(f"{f.filename}: {err}")
            else:
                done += 1
        if not done:                                  # nothing went in: only say why
            raise _back("Nothing added. " + " ".join(errs), "pictures")
        raise _back(f"Added {done} picture{'' if done == 1 else 's'} to {who}." + (" " + " ".join(errs) if errs else ""),
                    "pictures")

    async def save_lines(request: web.Request) -> web.Response:
        form = await request.post()
        key = str(form.get("host") or "")
        if key not in hosts.HOSTS:
            raise _back("Unknown host.", "lines")
        all_edits = dict(store.get("host_templates") or {})
        if str(form.get("action")) == "reset":
            all_edits.pop(key, None)
            store.put("host_templates", all_edits)
            hosts.load_overrides(store)
            raise _back(f"{hosts.HOSTS[key]['name']}'s lines are back to the built-in ones.", "lines")
        mine: Dict[str, List[str]] = {}
        problems: List[str] = []
        for slot in hosts.SLOT_HELP:
            rows = [" ".join(x.split()) for x in str(form.get(slot) or "").splitlines()]
            rows = [x[:300] for x in rows if x]
            for x in rows:
                bad = hosts.bad_blanks(x)
                if bad:
                    problems.append(f"{slot}: {', '.join('{' + b + '}' for b in bad)}")
            if rows and rows != hosts.TEMPLATES.get(key, {}).get(slot, []):
                mine[slot] = rows                     # only slots that differ from the built-in ones
        if problems:
            raise _back("Not saved, unknown blanks: " + "; ".join(problems[:5]), "lines")
        all_edits[key] = mine
        store.put("host_templates", all_edits)
        hosts.load_overrides(store)
        raise _back(f"Saved {hosts.HOSTS[key]['name']}'s lines ({len(mine)} slot{'' if len(mine) == 1 else 's'} edited).", "lines")

    async def get_pictures(request: web.Request) -> web.Response:
        return web.Response(text=pictures_page(poster, request.query.get("saved", "")), content_type="text/html")

    async def get_lines(request: web.Request) -> web.Response:
        return web.Response(text=lines_page(poster, request.query.get("saved", "")), content_type="text/html")

    app.router.add_get("/settings", get)
    app.router.add_get("/settings/pictures", get_pictures)
    app.router.add_get("/settings/lines", get_lines)
    app.router.add_post("/settings/pool", save_pool)
    app.router.add_post("/settings/kobold", save_kobold)
    app.router.add_post("/settings/hosts", save_hosts)
    app.router.add_post("/settings/picture", save_picture)
    app.router.add_get("/settings/picture/{host}/{kind}", picture)
    app.router.add_post("/settings/lines", save_lines)
