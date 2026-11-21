"""
Hosted reviews and the line picker (owner 2026-11-20: "the bot always waits for my picks").

With hosts on (/host setup on), a Friday / Monday review doesn't post at its time. Instead:
  1. ``ready`` (called by flavrpromo/calendar_post.py at review time) picks the host
     (flavrpromo/hosts.py ``choose``), works out the review's facts and the candidate lines for
     every slot, saves them as a pending review (kv host_review.<label>.<group>, listed in kv
     host_reviews) and DMs the owner a link to the picker page. It keeps answering "not yet".
  2. The owner opens http://<this PC>:3871/hosts/pick, picks a line per slot (or types their own),
     can swap the host, previews the two cards, and presses "Post it".
  3. The next calendar tick finds the picks: the opener card, the normal review board, then the
     desk sign-off card go out in that order, and the pending review is cleared.
  With KOBOLD_URL set, KoboldCpp writes more lines for every slot in the background as soon as the
  review starts waiting (``start_ai``, flavrpromo/kobold.py); they appear first in each slot with a ✨,
  and the page's "Write more" button asks again. KoboldCpp offline = template lines only.
  An hour after the first DM, if nothing is picked, one more DM nudges (NUDGE_AFTER). Nothing ever
  posts without the owner's picks; a review that is never picked simply never posts. /calendar
  post review: (by hand) still posts the plain review at once.

The page has no password, like the rest of port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/calendar_post.py (``ready``, ``post_card``, ``done``),
flavrpromo/__main__.py (``add_routes`` on the bot's web server).
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from aiohttp import web

from . import groups, host_cards, hosts

log = logging.getLogger("flavrpromo.host_picker")
NUDGE_AFTER = 3600.0            # seconds after the first DM before the one reminder
INDEX = "host_reviews"          # kv: the pending review keys, for the picker page
HEADINGS = {"week": "Week in Review", "weekend": "Weekend in Review"}
_tasks: Dict[str, "asyncio.Task[None]"] = {}     # KoboldCpp writing for a pending review (key → task)


def key_of(label: str, group: str) -> str:
    return f"host_review.{label}.{group}"


def _index(store: Any) -> List[str]:
    return [k for k in (store.get(INDEX) or []) if store.get(k)]


def waiting(store: Any) -> List[str]:
    """The pending review keys (/host list counts them)."""
    return _index(store)


def make(store: Any, group: str, label: str, week: Any, start_iso: str, host: str = "") -> Dict[str, Any]:
    """A fresh pending review: host, facts, notes and candidate lines (nothing picked)."""
    key = host or hosts.choose(store)
    f = hosts.facts(store, week)
    # regular or chibi picture on each card, picked at random so the two mix (Sen 2026-11-21); the
    # picker page's "opener picture" / "desk picture" switches change them
    return {"group": group, "label": label, "start": start_iso, "host": key, "facts": f,
            "notes": hosts.notes(f), "candidates": hosts.review_candidates(key, f), "picks": {},
            "ready": False, "asked_at": time.time(), "nudged": False,
            "opener_kind": random.choice(("pose", "chibi")), "desk_kind": random.choice(("desk", "chibi_desk"))}


async def ready(poster: Any, group: str, label: str, start_iso: str) -> Optional[Dict[str, Any]]:
    """The picked review when the owner has posted their picks, else None (still waiting; the first
    call makes the pending review and DMs the picker link, a later one may nudge once)."""
    store = poster.store
    k = key_of(label, group)
    p = store.get(k)
    if p and p.get("start") != start_iso:
        p = None                                    # an older review never picked: replaced by this one
    if not p:
        await poster.backfill_review(label)
        p = make(store, group, label, poster.build_review(group, label), start_iso)
        p["asked_at"] = poster.clock()               # the calendar's clock (tests set it)
        store.put(k, p)
        store.put(INDEX, sorted(set(_index(store)) | {k}))
        ai = start_ai(poster, k)
        await _dm(poster, f"🎙️ The {groups.heading(group, True, label)} is ready for {hosts.HOSTS[p['host']]['name']}. "
                          f"Pick the lines and it posts: {link(poster)}"
                          + (" (KoboldCpp is writing more lines; they show up on the page in a few minutes)" if ai else ""))
        return None
    if p.get("ready"):
        return p
    if not p.get("nudged") and poster.clock() - float(p.get("asked_at") or 0) >= NUDGE_AFTER:
        p["nudged"] = True
        store.put(k, p)
        await _dm(poster, f"⏰ The {groups.heading(group, True, label)} is still waiting for your picks: {link(poster)}")
    return None


def start_ai(poster: Any, k: str) -> bool:
    """Ask KoboldCpp (poster.kobold, None = KOBOLD_URL not set) for lines for pending review ``k`` in
    the background; False when it can't (not set up, or already writing for it)."""
    kob = getattr(poster, "kobold", None)
    if kob is None or (k in _tasks and not _tasks[k].done()):
        return False
    p = poster.store.get(k)
    if not p:
        return False
    p["ai_state"] = "writing"
    poster.store.put(k, p)
    _tasks[k] = asyncio.get_running_loop().create_task(_write(poster, k, p["host"]))
    return True


async def _write(poster: Any, k: str, host: str) -> None:
    """The background half of ``start_ai``: new lines go first in each slot (marked in p["ai"])."""
    store = poster.store
    p = store.get(k) or {}
    try:
        got = await poster.kobold.write(host, p.get("facts") or {}, HEADINGS.get(p.get("label"), "review"),
                                        p.get("notes") or [])
    except Exception:
        log.exception("KoboldCpp lines failed")
        got = {}
    p = store.get(k)                                # re-read: the owner may have saved picks meanwhile
    if not p or p.get("host") != host:
        return                                      # posted, replaced or host swapped: these lines don't fit
    ai = list(p.get("ai") or [])
    for slot, lines in got.items():
        if slot in (p.get("candidates") or {}):
            new = [x for x in lines if x not in p["candidates"][slot]]
            p["candidates"][slot] = new + p["candidates"][slot]
            ai += new
    p["ai"] = ai
    p["ai_state"] = "done" if got else "offline"
    store.put(k, p)


def link(poster: Any) -> str:
    return f"{poster.web_url or 'http://<this PC>:3871'}/hosts/pick"


async def _dm(poster: Any, text: str) -> None:
    try:
        await poster.discord.dm_owner(text)
    except Exception as e:                          # a DM failing mustn't stop the calendar
        log.info("picker DM failed: %s", e)


def chosen(p: Dict[str, Any], slot: str) -> str:
    """The picked line for a slot, else its first candidate (previews before picking)."""
    if slot in (p.get("picks") or {}):
        return p["picks"][slot]
    c = (p.get("candidates") or {}).get(slot) or []
    return c[0] if c else ""


def card_html(p: Dict[str, Any], card: str) -> str:
    key, f = p["host"], p.get("facts") or {}
    if card == "opener":
        notes = p.get("notes") or []
        return host_cards.opener(key, HEADINGS.get(p["label"], "In Review"), str(f.get("range") or ""),
                                 chosen(p, "opener"), notes, [chosen(p, f"note{i}") for i in range(len(notes))],
                                 hosts.pose(f), p.get("opener_kind") == "chibi")
    return host_cards.desk(key, chosen(p, "desk_highlight"), chosen(p, "desk_nudge"), chosen(p, "desk_signoff"),
                           p.get("desk_kind") or "desk")


async def post_card(poster: Any, channel: str, p: Dict[str, Any], card: str) -> None:
    """Post the opener or desk card in the review's channel (text only without Chromium)."""
    h = hosts.HOSTS[p["host"]]
    png = None
    if poster.shooter is not None:
        try:
            png = await poster.shooter.png(card_html(p, card))
        except Exception as e:
            log.warning("host card picture failed: %s", e)
    text = chosen(p, "opener") if card == "opener" else \
        "\n".join(x for x in (chosen(p, "desk_highlight"), chosen(p, "desk_nudge"), chosen(p, "desk_signoff")) if x)
    data = {"title": f"{h['emoji']} {h['name']} · {HEADINGS.get(p['label'], '')}".strip(" ·"),
            "colour": int(h["accent"].lstrip("#"), 16), "fields": [], "description": text if not png else "",
            "empty": False}
    await poster.discord.cal_send(channel, data, png, f"{p['host']}-{card}-{p['start']}.png")


def done(store: Any, p: Dict[str, Any]) -> None:
    store.delete(key_of(p["label"], p["group"]))
    store.put(INDEX, [k for k in _index(store)])


# ── the picker page ────────────────────────────────────────────────────
def _e(s: Any) -> str:
    return html.escape(str(s or ""))


AI_STATES = {"writing": "writing lines… (refresh in a minute or two)", "done": "its lines are marked ✨",
             "offline": "couldn't be reached, so only the template lines are here"}


def _switch(p: Dict[str, Any], name: str, legend: str, options: Any) -> str:
    """Radio buttons for one of a pending review's picture switches (opener_kind / desk_kind)."""
    cur = p.get(name) or options[0][0]
    return (f"<fieldset><legend>{_e(legend)}</legend>"
            + "".join(f'<label><input type=radio name={name} value={v}{" checked" if cur == v else ""}> {_e(n)}</label>'
                      for v, n in options) + "</fieldset>")


def page(store: Any, saved: str = "", ai_on: bool = False) -> str:
    """The picker page. ``ai_on``: KOBOLD_URL is set (shows KoboldCpp's state and the Write more button)."""
    blocks = []
    for k in _index(store):
        p = store.get(k)
        h = hosts.HOSTS[p["host"]]
        slots = []
        for slot, cands in (p.get("candidates") or {}).items():
            title = slot.replace("_", " ")
            if slot.startswith("note"):
                i = int(slot[4:])
                n = (p.get("notes") or [{}] * (i + 1))[i]
                title = f"note: {n.get('label', '').lower()} ({n.get('value', '')})"
            cur = chosen(p, slot)
            ai = set(p.get("ai") or [])
            opts = "".join(
                f'<label><input type=radio name="{slot}" value="{_e(c)}"{" checked" if c == cur else ""}> '
                f'{"✨ " if c in ai else ""}{_e(c)}</label>'
                for c in cands)
            custom = cur if cur and cur not in cands else ""
            opts += (f'<label><input type=radio name="{slot}" value="__custom"{" checked" if custom else ""}> your own: '
                     f'<input name="{slot}__text" value="{_e(custom)}" maxlength=300></label>')
            slots.append(f"<fieldset><legend>{_e(title)}</legend>{opts}</fieldset>")
        q = f"key={quote(k)}&t={int(time.time())}"
        blocks.append(
            f'<section><h2>{_e(groups.heading(p["group"], True, p["label"]))} · {_e(p["facts"].get("range"))}</h2>'
            f'<form method=post><input type=hidden name=key value="{_e(k)}">'
            f'<p>Host: <b>{_e(h["emoji"])} {_e(h["name"])}</b> <button name=action value=swap>Swap host</button></p>'
            + (f'<p class=ai>✨ KoboldCpp: {_e(AI_STATES.get(p.get("ai_state") or "", "ready"))} '
               f'<button name=action value=ai>Write more</button></p>' if ai_on else "")
            + "".join(slots)
            # each card's picture: regular or chibi (hosts.py kinds; the other one peeks on the opener)
            + _switch(p, "opener_kind", "opener picture", (("pose", "regular"), ("chibi", "chibi")))
            + _switch(p, "desk_kind", "desk picture", (("desk", "regular"), ("chibi_desk", "chibi")))
            + f'<p><button name=action value=save>Save and preview</button> '
            f'<button name=action value=post class=go>Post it</button></p></form>'
            f'<div class=prev><img src="/hosts/preview.png?{q}&card=opener" alt="opener preview">'
            f'<img src="/hosts/preview.png?{q}&card=desk" alt="desk preview"></div></section>')
    body = "".join(blocks) or "<p>Nothing is waiting for picks right now.</p>"
    note = f'<p class=saved>{_e(saved)}</p>' if saved else ""
    return ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>Host line picker</title><style>body{font-family:sans-serif;background:#1b1018;color:#eee;"
            "max-width:1100px;margin:auto;padding:16px}fieldset{border:1px solid #555;margin:10px 0;border-radius:8px}"
            "label{display:block;margin:6px 0}input[type=text],input:not([type]){width:60%}"
            "button{padding:8px 14px;border-radius:8px;border:0;font-weight:bold}.go{background:#f72ca2;color:#fff}"
            ".ai{color:#b7ef33}.prev img{width:100%;margin-top:10px;border-radius:8px}.saved{background:#2ae0d4;color:#000;padding:8px;"
            "border-radius:8px}section{border-bottom:2px solid #444;padding-bottom:20px}</style></head><body>"
            f"<h1>🎙️ Host line picker</h1><p><a style=color:#2ae0d4 href=/settings>Settings</a> (KoboldCpp, "
            f"hosts, pictures, lines)</p>{note}{body}</body></html>")


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store

    async def get(request: web.Request) -> web.Response:
        return web.Response(text=page(store, request.query.get("saved", ""), getattr(poster, "kobold", None) is not None),
                            content_type="text/html")

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        k = str(form.get("key") or "")
        p = store.get(k) if k in _index(store) else None
        if not p:
            raise web.HTTPSeeOther("/hosts/pick?saved=That+review+isn%27t+waiting+any+more.")
        action = str(form.get("action") or "save")
        if action == "ai":
            msg = ""                                # keeps the page as it is; start_ai below
        elif action == "swap":
            others = [h for h in hosts.HOSTS if h != p["host"]] or [p["host"]]
            p["host"] = others[0]
            p["candidates"] = hosts.review_candidates(p["host"], p["facts"])
            p["picks"], p["ai"] = {}, []
            msg = f"Swapped to {hosts.HOSTS[p['host']]['name']}."
        else:
            picks = {}
            for slot in p.get("candidates") or {}:
                v = str(form.get(slot) or "")
                if v == "__custom":
                    v = " ".join(str(form.get(f"{slot}__text") or "").split())[:300]
                if v:
                    picks[slot] = v
            p["picks"] = picks
            if str(form.get("desk_kind") or "") in ("desk", "chibi_desk"):
                p["desk_kind"] = str(form.get("desk_kind"))
            if str(form.get("opener_kind") or "") in ("pose", "chibi"):
                p["opener_kind"] = str(form.get("opener_kind"))
            msg = "Saved."
            if action == "post":
                p["ready"] = True
                msg = "Posting now: opener, board, then the desk card."
        store.put(k, p)
        if action == "swap" or action == "ai":          # new lines from KoboldCpp for this host
            if start_ai(poster, k):
                msg += " KoboldCpp is writing more lines." if action == "swap" else "KoboldCpp is writing more lines."
            elif action == "ai":
                msg = "KoboldCpp isn't set up (KOBOLD_URL)." if getattr(poster, "kobold", None) is None else \
                    "KoboldCpp is still writing; refresh in a minute."
        poster.poke()
        raise web.HTTPSeeOther(f"/hosts/pick?saved={quote(msg.strip())}")

    async def preview(request: web.Request) -> web.Response:
        k = request.query.get("key", "")
        p = store.get(k) if k in _index(store) else None
        if not p:
            raise web.HTTPNotFound()
        if poster.shooter is None:
            raise web.HTTPServiceUnavailable(text="No Chromium for pictures.")
        png = await poster.shooter.png(card_html(p, "desk" if request.query.get("card") == "desk" else "opener"))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    app.router.add_get("/hosts/pick", get)
    app.router.add_post("/hosts/pick", post)
    app.router.add_get("/hosts/preview.png", preview)
