"""
Recipes: whole tall sections for the article editor (owner 2026-11-21: "the article editor should be
able to use these to build whole new parts for the article, like a breakdown of the games someone played
this week, or a tall image giving more detailed commentary on the streams for a day").

A recipe turns the draft's week into one or more tall pictures made of chunks (flavrpromo/tall.py):
  games    "Games this week": a header, one "A game" chunk per game played (who, how many streams,
           history tags, genre, what it is), a sign-off strip
  day      "<Day> in detail": a header, one "One stream" chunk per stream of that day
  person   "<Name>'s week": the same, for one person's streams of the week
Each picture is at most tall.MAX_H px tall (X shows no more); a long list is split over several
pictures of balanced size, each its own section of the article. The result is ordinary chunks: the
owner edits them afterwards in the tall picture builder (flavrpromo/tall_page.py) like any stack.

The remarks (KoboldCpp): ``write_line`` writes one chunk's remark from THAT stream's or game's facts
(``stream_facts`` / ``game_facts``: person, game, day and time, length, platforms, title, genre, what
the game is, history tag), and ``start_lines`` writes every empty remark of a picture in the
background, one request each (the pattern of flavrpromo/host_picker.py ``start_ai``). What it is
asked comes from kobold.ASKS "stream" and "game" (editable on the settings page's Asks).

Who calls it: flavrpromo/article_editor.py ("+ Add a tall section" and the ✨ on a tall section),
flavrpromo/tall_page.py (✨ on a chunk, the drawing context). No network of its own except KoboldCpp.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Tuple

from . import gameinfo, games, host_picker, hosts, kobold, tall
from .render import clock

log = logging.getLogger("flavrpromo.recipes")

RECIPES = {"games": "Games this week", "day": "One day in detail", "person": "One person's week"}
HEAD_H = tall.height({"type": "header", "size": 0})       # px: the header strip of a recipe picture
FOOT_H = tall.height({"type": "footer", "size": 0})       # px: the sign-off strip (the last picture only)
LINE_TYPES = ("stream", "game")                           # chunk types that carry a KoboldCpp remark
_tasks: Dict[str, "asyncio.Task[None]"] = {}              # "<draft key>|<tall id>" → background writer

AI_STATES = {"writing": "writing the remarks… refresh in a minute or two", "done": "the remarks are written",
             "offline": "couldn't be reached", "nolines": "answered, but with nothing usable"}


# ---- the week's games and their facts ----------------------------------------------------------

def game_rows(facts: Dict[str, Any], week: Any) -> List[Dict[str, Any]]:
    """Every game of the week as {game, people, streams, tags}: the review facts' list (hosts.facts, the
    top GAMES_MAX with history tags), then any other game on the week's calendar (no tags)."""
    rows = [dict(r) for r in (facts or {}).get("games") or []]
    seen = {r["game"].lower() for r in rows}
    for t in (week.tiles() if week is not None else []):
        if not t.game or t.game.lower() in seen:
            continue
        seen.add(t.game.lower())
        rows.append({"game": t.game, "people": [], "streams": 0, "tags": []})
    for r in rows:                                    # fill in people / streams for the extra ones
        if not r["people"] and week is not None:
            mine = [t for t in week.tiles() if (t.game or "").lower() == r["game"].lower()]
            r["people"] = sorted({t.name for t in mine})
            r["streams"] = r["streams"] or len(mine)
    return rows


def drawing_context(store: Any, p: Dict[str, Any], week: Any, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The extra ctx tall.document needs for game chunks: ``games`` {lower name: row} and ``info``
    {lower name: IGDB info from the cache} for the games the chunks use."""
    rows = {r["game"].lower(): r for r in game_rows(p.get("facts") or {}, week)}
    used = {str(c.get("game") or "").lower() for c in chunks if c.get("type") == "game"}
    return {"games": rows, "info": {g: gameinfo.cached(store, rows[g]["game"]) for g in used if g in rows}}


def _about(info: Dict[str, Any]) -> str:
    return "; ".join(x for x in (", ".join(info.get("genres") or []), info.get("summary") or "") if x)


def stream_facts(store: Any, week: Any, t: Any) -> str:
    """One stream as the facts sentence KoboldCpp gets (who, game, when, how long, where, its title,
    what the game is, whether it's new / part n for them)."""
    d = next((i for i, tiles in enumerate(week.days) if any(x is t for x in tiles)), None)
    day = week.date_of(d).strftime("%A") if d is not None else ""
    when = f"{day} at {clock(t.at, week.tz)}".strip()
    if t.kind == "past":
        head = f"{t.name} streamed {t.game or 'a stream'} on {when}" + (f" for {hosts.length_words(t.length)}" if t.end else "")
    elif t.kind == "live":
        head = f"{t.name} is live now with {t.game or 'a stream'}"
    else:
        head = f"{t.name} is planning to stream {t.game or 'a stream'} on {when}"
    parts = [head]
    if t.platforms:
        parts.append("on " + " and ".join(t.platforms))
    if t.title:
        parts.append(f'stream title "{t.title}"')
    if t.game:
        info = gameinfo.cached(store, t.game)
        try:
            sid = hosts._session_id(store, t)
            tag = games.tag(store, t.person_id, t.game, t.at, sid) if t.person_id else ""
        except Exception:                             # the history is a nice-to-have; never block a remark
            tag = ""
        parts.append(kobold.games_text([{"game": t.game, "people": [t.name], "streams": 1, "tags": [tag] if tag else []}])
                     .replace("games played: ", "game: "))
        if _about(info):
            parts.append(f"{t.game} is {_about(info)}")
    return ", ".join(parts) + "."


def game_facts(row: Dict[str, Any], info: Dict[str, Any]) -> str:
    """One game of the week as the facts sentence: who played it, how many streams, tags, what it is."""
    text = kobold.games_text([row]).replace("games played: ", "game played this week: ")
    return text + (f". {row['game']} is {_about(info)}" if _about(info) else "") + "."


def chunk_facts(store: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any]) -> str:
    """The facts for a chunk's remark ("" = the chunk points at nothing yet)."""
    if c.get("type") == "stream":
        _, t = tall._tile_of(c.get("ref") or "", week)
        return stream_facts(store, week, t) if t is not None else ""
    if c.get("type") == "game":
        row = next((r for r in game_rows(p.get("facts") or {}, week) if r["game"].lower() == str(c.get("game") or "").lower()), None)
        return game_facts(row, gameinfo.cached(store, row["game"])) if row else ""
    return ""


async def write_line(poster: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any]) -> Tuple[str, str]:
    """✨ for one chunk: (new line or "", note for the page). One request; the chunk's own host speaks."""
    kob = getattr(poster, "kobold", None)
    if kob is None:
        return "", "KoboldCpp isn't set up (Settings → KoboldCpp)."
    facts = chunk_facts(poster.store, p, week, c)
    if not facts:
        return "", "Pick a stream or game for that chunk first."
    host = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
    new = await kob.line(host, kobold.asks()[c["type"]], host_picker.heading_of(p, "review"), facts)
    if new is None:
        return "", "KoboldCpp couldn't be reached."
    if not new:
        return "", f"KoboldCpp answered, but with no usable line. Try again. Its answer: {kob.last_raw[:200]}"
    return new, "✨ Wrote the remark."


def start_lines(poster: Any, dkey: str, tid: str, week: Any) -> bool:
    """Write every empty remark of tall picture ``tid`` in the background; False when KoboldCpp isn't
    set up or is already writing for this picture."""
    k = f"{dkey}|{tid}"
    if getattr(poster, "kobold", None) is None or (k in _tasks and not _tasks[k].done()):
        return False
    p = poster.store.get(dkey)
    if not p or tid not in (p.get("talls") or {}):
        return False
    p["talls"][tid]["ai_state"] = "writing"
    poster.store.put(dkey, p)
    _tasks[k] = asyncio.get_running_loop().create_task(_write_all(poster, dkey, tid, week))
    return True


async def _write_all(poster: Any, dkey: str, tid: str, week: Any) -> None:
    """The background half of ``start_lines``: one request per empty remark; each is saved as it comes
    (the draft is re-read first, the owner may have edited meanwhile)."""
    store = poster.store
    todo = [c["id"] for c in ((store.get(dkey) or {}).get("talls", {}).get(tid, {}).get("chunks") or [])
            if c.get("type") in LINE_TYPES and not c.get("line")]
    state = "done"
    for cid in todo:
        p = store.get(dkey)
        c = next((x for x in (p or {}).get("talls", {}).get(tid, {}).get("chunks", []) if x["id"] == cid), None)
        if c is None or c.get("line"):
            continue
        try:
            line, _ = await write_line(poster, p, week, c)
        except Exception:
            log.exception("KoboldCpp remark failed")
            line = ""
        p = store.get(dkey)                           # re-read: saved edits must not be overwritten
        c = next((x for x in (p or {}).get("talls", {}).get(tid, {}).get("chunks", []) if x["id"] == cid), None)
        if not line:
            state = "offline" if not str(getattr(poster.kobold, "last_raw", "") or "").strip() else "nolines"
            break
        if c is not None and not c.get("line"):
            c["line"] = line
            p["saved_at"] = time.time()
            store.put(dkey, p)
    p = store.get(dkey)
    if p and tid in (p.get("talls") or {}):
        p["talls"][tid]["ai_state"] = state
        store.put(dkey, p)


# ---- the recipes ---------------------------------------------------------------------------------

def _pictures(title: str, subs: List[str], items: List[Dict[str, Any]], diagonal: bool) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Split ``items`` (stream / game chunks, no ids yet) over as few pictures as fit tall.MAX_H, in
    balanced groups, each with a header and, on the last one, a sign-off strip. Medium size first; small
    when that avoids a split. ``subs``: the header line under the title (one per picture, or one for all)."""
    room = lambda size: (tall.MAX_H - HEAD_H - FOOT_H) // tall.height({"type": items[0]["type"], "size": size})  # noqa: E731
    size = 1 if len(items) <= room(1) else 0
    count = max(1, math.ceil(len(items) / max(1, room(size))))
    each = math.ceil(len(items) / count)
    out = []
    for n in range(count):
        part = [dict(x, size=size) for x in items[n * each:(n + 1) * each]]
        sub = subs[n] if len(subs) > 1 else (subs[0] if subs else "")
        if count > 1:
            sub = (sub + " · " if sub else "") + f"part {n + 1} of {count}"
        chunks = [{"type": "header", "size": 0, "title": title, "sub": sub}] + part
        if n == count - 1:
            chunks.append({"type": "footer", "size": 0, "host": "", "kind": "chibi_happy", "var": "", "line": ""})
        if diagonal:                                  # alternating slants, gentle, never on the last chunk
            for i, c in enumerate(chunks[:-1]):
                c["cut"], c["slope"] = ("down", "up")[i % 2], 0
        out.append((title if count == 1 else f"{title} ({n + 1} of {count})", tall.renumber(chunks)))
    return out


def build(recipe: str, p: Dict[str, Any], week: Any, arg: str = "", diagonal: bool = False
          ) -> Tuple[List[Tuple[str, List[Dict[str, Any]]]], str]:
    """([(section title, chunks)], error text). ``arg``: the day number for "day", the person's name
    for "person". Empty list + a message when the week has nothing for that recipe."""
    if recipe == "games":
        rows = game_rows(p.get("facts") or {}, week)
        if not rows:
            return [], "No games on this week's calendar yet."
        items = [{"type": "game", "game": r["game"], "line": "", "host": "", "kind": "happy", "var": ""} for r in rows]
        return _pictures("Games this week", [""], items, diagonal), ""
    refs: List[Tuple[str, str]] = []                  # (ref, person)
    if recipe == "day":
        try:
            d = max(0, min(len(week.days) - 1, int(arg)))
        except ValueError:
            return [], "Pick a day."
        refs = [(f"d{d}:{n}", t.name) for n, t in enumerate(week.days[d])]
        title = f"{week.date_of(d).strftime('%A')}, in detail"
        sub = f"{week.date_of(d).strftime('%B')} {week.date_of(d).day}"
    elif recipe == "person":
        refs = [(f"d{d}:{n}", t.name) for d, tiles in enumerate(week.days) for n, t in enumerate(tiles) if t.name == arg]
        title, sub = f"{arg}'s week", (p.get("facts") or {}).get("range") or ""
    else:
        return [], "Pick what to build."
    if not refs:
        return [], "No streams for that choice."
    items = [{"type": "stream", "ref": r, "line": "", "host": "", "kind": "happy", "var": ""} for r, _ in refs]
    if recipe == "person":                            # their name is the header: not again on every stream
        for x in items:
            x["show"] = [k for k in tall.DEFAULT_SHOW["stream"] if k != "name"]
    return _pictures(title, [sub], items, diagonal), ""


def fill(chunks: List[Dict[str, Any]], p: Dict[str, Any], week: Any) -> None:
    """Put this week into a template's empty chunks (a saved or built-in stack just added): each stream
    chunk without a stream takes the next stream of the calendar not used yet in the stack, each game
    chunk without a game the next game. Chunks already pointing at something are left alone."""
    refs = [x["ref"] for x in tall.tile_choices(week)]
    names = [r["game"] for r in game_rows(p.get("facts") or {}, week)]
    used_r = {c.get("ref") for c in chunks if c.get("type") == "stream" and c.get("ref")}
    used_g = {c.get("game") for c in chunks if c.get("type") == "game" and c.get("game")}
    for c in chunks:
        if c.get("type") == "stream" and not c.get("ref"):
            c["ref"] = next((r for r in refs if r not in used_r), "")
            used_r.add(c["ref"])
        elif c.get("type") == "game" and not c.get("game"):
            c["game"] = next((g for g in names if g not in used_g), "")
            used_g.add(c["game"])


def people(week: Any) -> List[str]:
    """Everyone with a stream this week, in calendar order (the "one person's week" menu)."""
    seen: List[str] = []
    for t in (week.tiles() if week is not None else []):
        if t.name not in seen:
            seen.append(t.name)
    return seen


def next_tall_id(p: Dict[str, Any]) -> str:
    return "tall" + str(1 + max([int(k[4:]) for k in (p.get("talls") or {}) if k[4:].isdigit()] or [0]))


def add_to_draft(p: Dict[str, Any], built: List[Tuple[str, List[Dict[str, Any]]]]) -> List[str]:
    """Put built pictures into the draft as tall sections just before the outro; their ids."""
    ids = []
    for title, chunks in built:
        sid = next_tall_id(p)
        p.setdefault("talls", {})[sid] = {"chunks": chunks}
        at = next((i for i, s in enumerate(p["sections"]) if s["id"] == "outro"), len(p["sections"]))
        p["sections"].insert(at, {"id": sid, "title": title, "on": True})
        ids.append(sid)
    return ids


__all__ = ["RECIPES", "build", "fill", "people", "add_to_draft", "write_line", "start_lines", "game_rows", "drawing_context",
           "chunk_facts", "stream_facts", "game_facts", "AI_STATES", "LINE_TYPES", "next_tall_id"]
