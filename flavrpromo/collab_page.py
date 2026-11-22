"""
The Collabs page: http://<this PC>:3871/settings/collabs (Calendar > Collabs in the panel menu,
flavrpromo/panel.py NAV). The web side of flavrpromo/collabs.py, for when a phone DM isn't handy.

Sections (each its own form; a save redirects back with a note, like the other settings pages):
  Waiting for you   possible collabs (a title @mentions a friend / group): Confirm or Not a collab,
                    the same as the DM buttons (collabs.decide)
  Confirmed         collabs that get the highlight on the calendars; "Not a collab" takes it off
  Mark a collab     pick anyone's stream (this week and next, collabs.streams_of) and type who with
                    ("FlaVR, Lulu, @someone"; collabs.partners_from_text) → collabs.add (confirmed)
  Not collabs       ones you said no to; "Confirm" changes your mind
  Spotting          the kv "collab_detect" switch (also /collab detect)

Every change pokes the calendar (CalendarPoster.poke) so the boards redraw with or without the gold.
No password, like the rest of port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/__main__.py (``add_routes`` on the web server).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import quote

from aiohttp import web

from . import collabs
from .panel import _e, frame

HEADING = "🤝 Collabs"          # the label in panel.NAV
STYLE = (".co{display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:#0e0f14;border-radius:10px;"
         "padding:8px 12px;margin:8px 0;border-left:4px solid #ffc83d}.co b{color:#ffc83d}.co .t{color:#aab;font-size:14px;"
         "flex:1;min-width:200px}.co form{display:flex;gap:6px;margin:0}.co.no{border-left-color:#555;opacity:.8}"
         ".co.no b{color:#ccd}")


def _when(ts: float, tz: Any) -> str:
    """"Thu Nov 26, 7:30 PM" in the bot's time zone (TZ)."""
    d = datetime.fromtimestamp(ts, tz)
    return f"{d:%a %b} {d.day}, {d.hour % 12 or 12}{':%02d' % d.minute if d.minute else ''} {'AM' if d.hour < 12 else 'PM'}"


def _row(r: Dict[str, Any], tz: Any, buttons: str) -> str:
    who = collabs.with_text(collabs.names(r["partners"]), 6)
    src = " · marked by hand" if r.get("source") == "manual" else ""
    return (f'<div class="co{" no" if r["state"] == "dismissed" else ""}"><span><b>{_e(r["name"])}</b> {_e(who)}<br>'
            f'<small>{_e(_when(float(r["at"]), tz))}{src}</small></span><span class=t>{_e(r.get("title") or "")}</span>'
            f'<form method=post action=/settings/collabs><input type=hidden name=id value={int(r["id"])}>{buttons}</form></div>')


def page(poster: Any, saved: str = "") -> str:
    store, tz = poster.store, poster.tz
    now = poster.clock()
    rows = store.collabs_between(now - collabs.SCAN_BACK, now + collabs.SCAN_AHEAD)
    yes = '<button name=action value=confirm>🤝 Confirm</button>'
    no = '<button class=alt name=action value=dismiss>Not a collab</button>'
    waiting = "".join(_row(r, tz, yes + no) for r in rows if r["state"] == "suggested") or \
        "<p class=help>Nothing waiting. Stream titles of this week and next are read for @mentions every minute.</p>"
    confirmed = "".join(_row(r, tz, no) for r in rows if r["state"] == "confirmed") or \
        "<p class=help>No confirmed collabs this week or next.</p>"
    dismissed = "".join(_row(r, tz, yes) for r in rows if r["state"] == "dismissed")
    # "Mark a collab": everyone's streams this week and next (not hidden people)
    opts: List[str] = []
    for p in store.people():
        if p.get("hidden"):
            continue
        for s in collabs.streams_of(store, p["id"], now):
            if s["at"] < now - 12 * 3600 and s["kind"] == "scheduled":
                continue                    # a scheduled time long gone that never happened
            label = f'{p["name"]} · {_when(s["at"], tz)}' + (f' · {s["title"][:60]}' if s["title"] else "")
            opts.append((s["at"], f'<option value="{p["id"]}:{int(s["at"])}">{_e(label)}</option>'))
    menu = "".join(o for _, o in sorted(opts, key=lambda o: o[0]))
    mark = (f'<form method=post action=/settings/collabs><input type=hidden name=action value=add>'
            f'<label>Stream <select name=stream>{menu}</select></label>'
            '<label>With <input name=partners placeholder="FlaVR, Lulu, @someone"></label>'
            '<small>Groups and people the bot follows by name; anyone else as typed. Commas between.</small>'
            '<p><button>Mark as collab</button></p></form>') if menu else \
        "<p class=help>Nobody has a stream on the calendar this week or next yet.</p>"
    on = collabs.enabled(store)
    spot = (f'<form method=post action=/settings/collabs><input type=hidden name=action value=detect>'
            f'<label><input type=checkbox name=on value=1{" checked" if on else ""}> Read stream titles for @mentions '
            '(and "w/", "with", "ft." + a name the bot follows)</label>'
            '<small>A title that @mentions another group or a friend (not the streamer\'s own group or channel) '
            'becomes a possible collab: you get a DM with Confirm / Not a collab (/pings set collab), and it is '
            'listed here. Hashtags like #flavr are never read.</small><p><button>Save</button></p></form>')
    body = (f'<section><h2>Waiting for you</h2>{waiting}</section>'
            f'<section><h2>Confirmed (gold on the calendars)</h2>{confirmed}</section>'
            f'<section><h2>Mark a collab</h2>{mark}</section>'
            + (f'<section><h2>Not collabs</h2>{dismissed}</section>' if dismissed else "")
            + f'<section><h2>Spotting</h2>{spot}</section>')
    return frame("Collabs · FlaVR Promo", HEADING, body, saved, STYLE)


def _back(note: str) -> web.HTTPSeeOther:
    return web.HTTPSeeOther(f"/settings/collabs?saved={quote(note)}")


def add_routes(app: web.Application, poster: Any) -> None:
    """GET /settings/collabs (the page) and POST /settings/collabs (action = confirm | dismiss | add | detect)."""
    store = poster.store

    async def get(request: web.Request) -> web.Response:
        return web.Response(text=page(poster, request.query.get("saved", "")), content_type="text/html")

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        action = str(form.get("action") or "")
        if action in ("confirm", "dismiss"):
            try:
                cid = int(str(form.get("id") or "0"))
            except ValueError:
                cid = 0
            row = collabs.decide(store, cid, action == "confirm", poster.clock())
            poster.poke()
            if row is None:
                raise _back("That collab is gone.")
            raise _back(f"{'Confirmed' if action == 'confirm' else 'Not a collab'}: {row['name']} "
                        f"{collabs.with_text(collabs.names(row['partners']))}.")
        if action == "add":
            try:
                pid, at = (int(x) for x in str(form.get("stream") or "").split(":"))
            except ValueError:
                raise _back("Pick a stream first.")
            parts = collabs.partners_from_text(store, str(form.get("partners") or ""), pid)
            if not parts:
                raise _back("Type who it's with, e.g. FlaVR, Lulu.")
            title = next((s["title"] for s in collabs.streams_of(store, pid, poster.clock()) if int(s["at"]) == at), "")
            cid = collabs.add(store, pid, float(at), parts, title, now=poster.clock())
            poster.poke()
            row = store.collab_get(cid) or {"name": "", "partners": parts}
            raise _back(f"Marked: {row['name']} {collabs.with_text(collabs.names(row['partners']))}.")
        if action == "detect":
            store.put("collab_detect", bool(form.get("on")))
            raise _back("Spotting on." if form.get("on") else "Spotting off (confirmed collabs keep their highlight).")
        raise _back("Nothing changed.")

    app.router.add_get("/settings/collabs", get)
    app.router.add_post("/settings/collabs", post)
