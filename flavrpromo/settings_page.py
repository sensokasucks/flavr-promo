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
  Pictures    (/settings/pictures) every picture kind for both hosts with a preview, upload to
              replace the main one (the same as /host picture) and "back to built-in" (deletes the
              upload), plus a POOL of extra pictures per kind (add several at once, remove one;
              flavrpromo/hosts.py ``variants``): posts pick from the pool at random.
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


def pictures_page(poster: Any, saved: str = "") -> str:
    """Hosts > Pictures: every picture kind of both hosts as a POOL (flavrpromo/hosts.py): the main
    picture (replace / back to built-in) plus extra pictures to add and remove; the system picks one
    of the pool at random, and the article editor lets you pin one."""
    cells = []
    for key, h in hosts.HOSTS.items():
        have = hosts.pictures(key)
        for kind in hosts.KINDS:
            src = f"/settings/picture/{key}/{kind}" if have[kind] else ""
            img = f'<img src="{src}" loading=lazy alt="">' if src else '<div class=none>none</div>'
            reset = '<button name=action value=reset>Back to built-in</button>' if have[kind] == "yours" else ""
            pool = ""
            if kind in hosts.POOLED:
                extra = hosts.variants(key, kind)[1:] if have[kind] else [
                    v for v in hosts.variants(key, kind) if v[0] != "main"]
                thumbs = "".join(
                    f'<form class=thumb method=post action=/settings/pool><input type=hidden name=host value={key}>'
                    f'<input type=hidden name=kind value={kind}><input type=hidden name=vid value="{_e(v)}">'
                    f'<img src="/settings/picture/{key}/{kind}?v={_e(v)}" loading=lazy alt="">'
                    f'<button name=action value=remove class=alt title="Remove this picture">✕</button></form>'
                    for v, _ in extra)
                pool = (f'<div class=pool><small>Pool: {1 + len(extra) if have[kind] else len(extra)} '
                        f'picture{"" if len(extra) == 0 and have[kind] else "s"}'
                        f'{" (random pick)" if extra else ""}</small>{thumbs}'
                        f'<form method=post action=/settings/pool enctype=multipart/form-data>'
                        f'<input type=hidden name=host value={key}><input type=hidden name=kind value={kind}>'
                        f'<input type=file name=file accept=".png,.jpg,.jpeg,.webp" multiple>'
                        f'<button name=action value=add>Add to pool</button></form></div>')
            cells.append(f'<div class=pic><form method=post action=/settings/picture enctype=multipart/form-data>'
                         f'<input type=hidden name=host value={key}><input type=hidden name=kind value={kind}>'
                         f'{img}<b>{_e(h["name"])}: {_e(kind.replace("_", " "))}</b>'
                         f'<small>main picture: {_e(have[kind] or "missing")}</small>'
                         f'<input type=file name=file accept=".png,.jpg,.jpeg,.webp">'
                         f'<button name=action value=upload>Replace main</button> {reset}</form>{pool}</div>')
    body = (f'<section id=pictures><p class=help>PNG, JPG or WebP up to 8 MB; see-through PNG / WebP is best. '
            f'"Replace main" swaps the main picture of that kind. <b>Add to pool</b> adds more pictures to the '
            f'same kind (up to {hosts.POOL_MAX}): a post or article picks one of them at random, and in the '
            f'article editor you can choose a specific one or re-roll. Head pictures (the go-live avatar) stay '
            f'single.</p><div class=grid>{"".join(cells)}</div></section>')
    return frame("FlaVR Promo pictures", "🖼️ Pictures", body, saved, style=(
        ".pool{margin-top:8px;border-top:1px solid #3d2a3b;padding-top:6px}"
        ".thumb{display:inline-block;position:relative;margin:2px}.thumb img{width:64px!important;height:64px!important}"
        ".thumb button{position:absolute;top:2px;right:2px;padding:0 6px}"))


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
