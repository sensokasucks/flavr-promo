"""
The character card editor: http://<this PC>:3871/settings/cards (owner 2026-11-21: "a host
character card editor as well so we can edit what it's sending to kobold").

What KoboldCpp gets for every host line (flavrpromo/kobold.py ``prompt``): the host's character card
(system prompt, description, personality, scenario, example exchanges, the after-facts rule), then
the review's facts and one slot's ask ("Write one opener for the week in review: ..."), sent once
per line wanted (lines per slot). This page
edits both:
  Cards   one form per host with each field of kobold.CARD_FIELDS as a text box, prefilled with the
          text in force. Saved in kv "host_cards" ({host: {field: text}}), only the fields that
          differ from the built-in card (flavrpromo/host_art/<host>/card.json, which stays as it is,
          so it still loads in SillyTavern). "Back to built-in" drops that host's edits.
  Asks    what each slot asks for (kobold.ASKS), kv "kobold_asks". {n} = lines per slot, {heading}
          = "week in review", {note} = the highlight a note comments on, {length} = the sentence
          count for the settings page's Chattiness, {name} / {line} = who a banter line answers
          and what they said.
  Angles  the takes one of which is added to each request so the lines differ (owner 2026-11-22):
          a box per host for their own habits and one for both, one angle per row, kv
          "kobold_angles" ({"all": [...], "<host>": [...]}); an empty box = the built-in list.
  Preview the whole prompt one opener request sends, with example facts, and with KoboldCpp set
          up a "Try it" button that asks for opener lines with those facts and shows them.

A save calls kobold.load_card_overrides, so the next request uses it. No password, like the rest of
port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/__main__.py (``add_routes`` on the web server).
"""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from aiohttp import web

from . import hosts, kobold
from .settings_page import _e, frame

MAX_FIELD = 6000            # characters kept per card field (a card's example block is the longest)
# example facts for the preview and "Try it" (the shape of flavrpromo/hosts.py ``facts``)
SAMPLE = {"streams": 9, "hours": 31, "top_name": "Lulu Teala", "top_count": 4, "longest_name": "Sen",
          "longest_len": "6 hours", "new_game": "Schedule I", "new_game_name": "Sen", "quiet_day": "Tuesday"}


def _back(note: str, anchor: str = "") -> web.HTTPSeeOther:
    return web.HTTPSeeOther(f"/settings/cards?saved={quote(note)}" + (f"#{anchor}" if anchor else ""))


def page(poster: Any, saved: str = "") -> str:
    edits = poster.store.get("host_cards") or {}
    forms = []
    for key, h in hosts.HOSTS.items():
        c = kobold.card(key)
        rows = []
        for field, help_text in kobold.CARD_FIELDS.items():
            mark = " <i>edited</i>" if (edits.get(key) or {}).get(field) else ""
            rows.append(f'<label><b>{_e(field.replace("_", " "))}</b>{mark}<small>{_e(help_text)}</small>'
                        f'<textarea name="{field}" rows={10 if field == "mes_example" else 4}>{_e(c.get(field))}</textarea></label>')
        # with one angle and one "already used" line, so the owner sees where those go
        preview = kobold.prompt(key, kobold.fill_ask(kobold.asks()["opener"], 1, "week in review"),
                                kobold.facts_text(SAMPLE), (kobold.angles(key) or [""])[0],
                                hosts.templates(key, "open_normal")[:1])
        own = (poster.store.get("kobold_angles") or {}).get(key)
        rows.append(f'<label><b>angles (their own habits)</b>{" <i>edited</i>" if own else ""}<small>One per row. One '
                    f'is added to each request ("For this one: ...") so the lines differ; short lines (nudge, '
                    f'sign-off, reply) only use these. Empty = the built-in list.</small>'
                    f'<textarea name=angles rows=6>{_e(chr(10).join(kobold.angles(key, "reply")))}</textarea></label>')
        try_it = ('<button name=action value=try class=alt>Save and try it (opener lines)</button>'
                  if getattr(poster, "kobold", None) is not None else
                  '<small>Set a KoboldCpp address on <a href="/settings#kobold">Settings</a> to try it here.</small>')
        forms.append(f'<section id="{key}"><h2>{_e(h["emoji"])} {_e(h["name"])}</h2>'
                     f'<form method=post action=/settings/cards><input type=hidden name=host value={key}>'
                     f'{"".join(rows)}<p><button name=action value=save>Save {_e(h["name"])}\'s card</button> '
                     f'<button name=action value=reset class=alt>Back to built-in</button> {try_it}</p></form>'
                     f'<details><summary>The whole prompt for one opener request (example facts)</summary>'
                     f'<pre>{_e(preview)}</pre></details></section>')
    a = kobold.asks()
    shared_angles = (poster.store.get("kobold_angles") or {}).get("all") or kobold.ANGLES
    ask_rows = "".join(
        f'<label><b>{_e(slot.replace("_", " "))}</b>{" <i>edited</i>" if (poster.store.get("kobold_asks") or {}).get(slot) else ""}'
        f'<input name="{slot}" value="{_e(a[slot])}" style="width:100%"></label>' for slot in kobold.ASKS)
    asks_form = (f'<section id=asks><h2>❓ What each slot asks for</h2><p class=help>Sent after the facts. '
                 f'{{n}} = lines per slot, {{heading}} = "week in review" / "weekend in review", {{note}} = the '
                 f'highlight a note comments on, {{length}} = how long (the Chattiness on Settings), {{name}} and {{line}} = '
                 f'who a reply answers and what they said. An empty box uses the built-in ask.</p>'
                 f'<form method=post action=/settings/asks>{ask_rows}'
                 f'<label><b>angles for both hosts</b>{" <i>edited</i>" if (poster.store.get("kobold_angles") or {}).get("all") else ""}'
                 f'<small>One per row; each request for a longer line gets one of these or one of the host\'s own. '
                 f'Empty = the built-in list. Switch angles off on Settings.</small>'
                 f'<textarea name=angles rows=8>{_e(chr(10).join(shared_angles))}</textarea></label>'
                 f'<p><button name=action value=save>Save asks</button> '
                 f'<button name=action value=reset class=alt>Back to built-in</button></p></form></section>')
    intro = ('<p class=help>What KoboldCpp is sent for every host line: the character card below, then the '
             'facts and the slot\'s ask. {{char}} is the host\'s name and {{user}} is "Producer". The built-in '
             'cards (flavrpromo/host_art/&lt;host&gt;/card.json) stay as they are; edits are kept here.</p>')
    return frame("Character cards", "🧾 Character cards", intro + "".join(forms) + asks_form, saved)


ANGLES_MAX, ANGLE_CHARS = 30, 160       # angles kept per list, characters kept per angle


def _save_angles(store: Any, who: str, raw: Any, built: list) -> None:
    """Keep one angle list (``who``: a host key, or "all" for the shared one) in kv "kobold_angles":
    one angle per row of ``raw``; an empty box, or the built-in list unchanged, drops the edit.
    ``raw`` None = the form had no angles box (an older page): nothing changes."""
    if raw is None:
        return
    rows = [" ".join(x.split())[:ANGLE_CHARS] for x in str(raw).splitlines()]
    rows = [x for x in rows if x][:ANGLES_MAX]
    edits = dict(store.get("kobold_angles") or {})
    if rows and rows != list(built):
        edits[who] = rows
    else:
        edits.pop(who, None)
    store.put("kobold_angles", edits)


def add_routes(app: web.Application, poster: Any) -> None:
    store = poster.store

    async def get(request: web.Request) -> web.Response:
        return web.Response(text=page(poster, request.query.get("saved", "")), content_type="text/html")

    async def save_card(request: web.Request) -> web.Response:
        form = await request.post()
        key = str(form.get("host") or "")
        if key not in hosts.HOSTS:
            raise _back("Unknown host.")
        name = hosts.HOSTS[key]["name"]
        all_edits = dict(store.get("host_cards") or {})
        if str(form.get("action")) == "reset":
            all_edits.pop(key, None)
            store.put("host_cards", all_edits)
            _save_angles(store, key, "", [])            # their own angles go back to the built-in ones too
            kobold.load_card_overrides(store)
            raise _back(f"{name}'s card is back to the built-in one.", key)
        built = kobold.builtin_card(key)
        mine: Dict[str, str] = {}
        for field in kobold.CARD_FIELDS:
            text = str(form.get(field) or "").replace("\r\n", "\n").strip()[:MAX_FIELD]
            if text and text != str(built.get(field) or "").strip():
                mine[field] = text              # only the fields that differ from the built-in card
        all_edits[key] = mine
        store.put("host_cards", all_edits)
        _save_angles(store, key, form.get("angles"), kobold.HOST_ANGLES.get(key, []))
        kobold.load_card_overrides(store)
        note = f"Saved {name}'s card ({len(mine)} field{'' if len(mine) == 1 else 's'} edited)."
        if str(form.get("action")) == "try" and getattr(poster, "kobold", None) is not None:
            # three lines, one request each (kobold.Kobold.lines; a request = one complete line)
            # (no ``kind``: the try-out lines are about example facts and stay out of the hosts' memory)
            lines = await poster.kobold.lines(key, kobold.asks()["opener"], "week in review", kobold.facts_text(SAMPLE), n=3)
            raw = poster.kobold.last_raw
            note += ("\n✨ " + "\n✨ ".join(lines)) if lines else \
                ("\nKoboldCpp couldn't be reached." if lines is None else f"\nNo usable lines. KoboldCpp said: {raw[:400]}")
        raise _back(note, key)

    async def save_asks(request: web.Request) -> web.Response:
        form = await request.post()
        if str(form.get("action")) == "reset":
            store.put("kobold_asks", {})
            _save_angles(store, "all", "", [])
            kobold.load_card_overrides(store)
            raise _back("The asks and the shared angles are back to the built-in ones.", "asks")
        mine = {}
        for slot, built in kobold.ASKS.items():
            text = " ".join(str(form.get(slot) or "").split())[:400]
            if text and text != built:
                mine[slot] = text
        store.put("kobold_asks", mine)
        _save_angles(store, "all", form.get("angles"), kobold.ANGLES)
        kobold.load_card_overrides(store)
        raise _back(f"Saved the asks ({len(mine)} edited).", "asks")

    app.router.add_get("/settings/cards", get)
    app.router.add_post("/settings/cards", save_card)
    app.router.add_post("/settings/asks", save_asks)
