"""
The settings page: http://<this PC>:3871/settings (owner 2026-11-21: "a local web page to set that
kobold URL and maybe other tweaks that'd be troublesome to do over Discord commands").

The other settings pages share its look and top links (``frame``, PAGES): character cards
(flavrpromo/card_page.py), the article editor (article_editor.py) and the command forms
(command_forms.py).

Sections (each its own form; a save redirects back with a note):
  KoboldCpp   address, password (never shown back), creativity (temperature) and lines per slot,
              a Test button that asks KoboldCpp for its model. Saved in kv "kobold"; it wins over
              KOBOLD_URL / KOBOLD_KEY from the environment (an empty address there = off).
  Hosts       on / off and "take turns" or always one host: the same kv as /host setup
              (hosts_on, hosts_only); "post go-live cards as the host" (kv hosts_webhook, default on,
              flavrpromo/host_webhooks.py; needs the bot's Manage Webhooks in the live channels); how
              long the Sunday board waits for the week-ahead picks (kv host_preview_wait, hours); the
              recap picture on ended go-live cards (kv host_recap_card, default on); boards in the
              host's look (kv host_board, default on).
  Pictures    every picture kind for both hosts with a preview, upload to replace one (the same
              as /host picture) and "back to built-in" (deletes the upload).
  Lines       every template slot for both hosts as a text box, one line per row; a blank that
              isn't in hosts.BLANKS is refused, an emptied box goes back to the built-in lines.
              Saved in kv "host_templates" (flavrpromo/hosts.py ``load_overrides``).

No password, like the rest of port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/__main__.py (``apply`` at start, ``add_routes`` on the web server).
"""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, List
from urllib.parse import quote

from aiohttp import web

from . import host_picker, hosts, kobold
from .kobold import PER_SLOT, Kobold

log = logging.getLogger("flavrpromo.settings_page")


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


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


def _back(note: str, anchor: str = "") -> web.HTTPSeeOther:
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
           + (f'<p class=test>{_e(test)}</p>' if test else "") + '</form></section>')
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
    # pictures
    cells = []
    for key, h in hosts.HOSTS.items():
        have = hosts.pictures(key)
        for kind in hosts.KINDS:
            src = f"/settings/picture/{key}/{kind}" if have[kind] else ""
            img = f'<img src="{src}" loading=lazy alt="">' if src else '<div class=none>none</div>'
            reset = '<button name=action value=reset>Back to built-in</button>' if have[kind] == "yours" else ""
            cells.append(f'<form class=pic method=post action=/settings/picture enctype=multipart/form-data>'
                         f'<input type=hidden name=host value={key}><input type=hidden name=kind value={kind}>'
                         f'{img}<b>{_e(h["name"])}: {_e(kind.replace("_", " "))}</b>'
                         f'<small>{_e(have[kind] or "missing")}</small>'
                         f'<input type=file name=file accept=".png,.jpg,.jpeg,.webp">'
                         f'<button name=action value=upload>Upload</button> {reset}</form>')
    pics = (f'<section id=pictures><h2>🖼️ Pictures</h2><p class=help>PNG, JPG or WebP up to 8 MB; see-through '
            f'PNG / WebP is best. An upload replaces the built-in picture of that kind.</p>'
            f'<div class=grid>{"".join(cells)}</div></section>')
    # lines
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
    nav = ('<nav class=in><a href="#kobold">KoboldCpp</a> · <a href="#hosts">Hosts</a> · <a href="#pictures">Pictures</a> · '
           '<a href="#lines">Lines</a></nav>')
    return frame("FlaVR Promo settings", "⚙️ Settings", nav + kob + hst + pics + lines, saved)


# the pages that share this look (the top links; keep in step with each page's add_routes)
PAGES = (("/settings", "⚙️ Settings"), ("/settings/cards", "🧾 Character cards"),
         ("/settings/article", "📰 Article editor"), ("/settings/commands", "⌨️ Commands"),
         ("/hosts/pick", "🎙️ Line picker"))
STYLE = ("body{font-family:sans-serif;background:#1b1018;color:#eee;"
         "max-width:1100px;margin:auto;padding:16px}a{color:#2ae0d4}section{border-bottom:2px solid #444;padding:10px 0 20px}"
         "label{display:block;margin:8px 0}input:not([type=checkbox]):not([type=radio]):not([type=file]),select{width:min(420px,90%)}"
         "input[type=number]{width:90px!important}button{padding:7px 12px;border-radius:8px;border:0;font-weight:bold;"
         "background:#f72ca2;color:#fff;cursor:pointer}button.alt{background:#3a2d3a}.help,small{color:#aab;display:block}"
         ".saved,.test{background:#2ae0d4;color:#000;padding:8px;border-radius:8px;white-space:pre-wrap}"
         ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}"
         ".pic{background:#2a1a28;border-radius:10px;padding:10px}.pic img,.pic .none{width:100%;height:150px;"
         "object-fit:contain;background:#0e0f14;border-radius:8px;display:flex;align-items:center;justify-content:center}"
         ".pic b{display:block;margin-top:6px}.pic input[type=file]{width:100%;margin:6px 0}"
         "textarea{width:100%;font-size:14px;background:#0e0f14;color:#eee;border:1px solid #555;border-radius:6px}"
         "nav.top{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px}nav.top b{color:#f72ca2}"
         "pre{white-space:pre-wrap;background:#0e0f14;padding:10px;border-radius:8px;font-size:13px}")


def frame(title: str, heading: str, body: str, saved: str = "", style: str = "") -> str:
    """A whole page in the settings look with the links to the other pages (PAGES) on top. Used by
    this page, flavrpromo/card_page.py, article_editor.py and command_forms.py. ``style``: extra CSS."""
    links = " ".join(f"<b>{_e(n)}</b>" if n == heading else f'<a href="{u}">{_e(n)}</a>' for u, n in PAGES)
    note = f'<p class=saved>{_e(saved)}</p>' if saved else ""
    return ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{_e(title)}</title><style>{STYLE}{style}</style></head><body>"
            f"<nav class=top>{links}</nav><h1>{_e(heading)}</h1>{note}{body}</body></html>")


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
        p = hosts.picture(key, kind) if kind in hosts.KINDS else None
        if p is None or p.stem != kind:             # only that exact kind (no fallback) on the settings page
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Cache-Control": "no-store"})

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

    app.router.add_get("/settings", get)
    app.router.add_post("/settings/kobold", save_kobold)
    app.router.add_post("/settings/hosts", save_hosts)
    app.router.add_post("/settings/picture", save_picture)
    app.router.add_get("/settings/picture/{host}/{kind}", picture)
    app.router.add_post("/settings/lines", save_lines)
