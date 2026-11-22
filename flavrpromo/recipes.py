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

The remarks (KoboldCpp): ``write_choices`` (the ✨ on a chunk: a few to pick from) and ``write_line`` (one) write a chunk's remark from THAT stream's or game's facts
(``stream_facts`` / ``game_facts``: person, game, day and time, length, platforms, title, genre, what
the game is, history tag), and ``start_lines`` writes every empty remark of a picture in the
background, one request each (the pattern of flavrpromo/host_picker.py ``start_ai``). What it is
asked comes from kobold.ASKS "stream" and "game" (editable on the settings page's Asks).
Two things steer a remark (owner 2026-11-22: "a good way to get the host to talk a little about the game"),
both set on the chunk in the builder:
  about   "" = a reaction to the stream / the game being played (the asks above); "game" = the host talks
          about the game itself (asks "stream_game" / "game_talk"; ``ask_kind``), and the facts then carry
          the game's longer IGDB details (gameinfo.talk). The details are fetched first when they aren't
          kept yet (``_details``, through poster.game_info).
  hint    a few words of the owner's the host should work in ("they finally beat the boss"); it joins the
          facts as "The producer adds: ...".
Host moments and the sign-off strip (SUMMARY_TYPES; owner 2026-11-22: "the sign off card has no way to
generate lines with kobold. ideally, it could read the other chunks to make a summary"): their ✨ uses the
asks "tall_host" / "tall_signoff" and the facts are what the picture's OTHER chunks show (``stack_facts``:
the header, each stream, the games, a day's streams, the highlight numbers), so the line sums the picture
up. They take a ``hint`` too.

A tall picture can have its own host style (p["talls"][tid]["host"], the builder's Look card): ``as_tall``
gives the draft as that picture sees it, and everything that reads p["host"] for a tall picture gets that.
``apply_seams`` sets every bottom edge of a stack at once (the recipes' seams menu and the Look card's).

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
SUMMARY_TYPES = ("host", "footer")                        # chunk types whose line ✨ writes from the whole picture
SUMMARY_ITEMS = 12                                        # streams listed in a picture's summary facts (the rest: "and n more")
CHAT_LINE = 220                                           # characters kept of one chat line (tall_page caps the box)
ABOUT = {"": "the stream (a reaction)", "game": "the game (what it is, why it's fun)"}     # a stream chunk's ``about``
ABOUT_GAME = {"": "it being played this week (a reaction)", "game": "the game itself (what it is, why it's fun)"}
HINT_MAX = 200                                            # characters kept of a chunk's ``hint``
DETAILS_WAIT = 8.0                                        # seconds a ✨ waits for a game's IGDB details
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


def _stop(text: str) -> str:
    """``text`` ending in a full stop, unless it already ends a sentence (IGDB's text usually does)."""
    return text if text.rstrip().endswith((".", "!", "?", "…")) else text.rstrip() + "."


def _about(info: Dict[str, Any]) -> str:
    return "; ".join(x for x in (", ".join(info.get("genres") or []), info.get("summary") or "") if x)


def stream_facts(store: Any, week: Any, t: Any, deep: bool = False) -> str:
    """One stream as the facts sentence KoboldCpp gets (who, game, when, how long, where, its title,
    what the game is, whether it's new / part n for them). ``deep``: the game at more length
    (gameinfo.talk), for a remark about the game."""
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
        if deep and gameinfo.talk(info):
            return ", ".join(parts) + ". " + _stop(gameinfo.talk(info))
        if _about(info):
            parts.append(f"{t.game} is {_about(info)}")
    return ", ".join(parts) + "."


def game_facts(row: Dict[str, Any], info: Dict[str, Any], deep: bool = False) -> str:
    """One game of the week as the facts sentence: who played it, how many streams, tags, what it is
    (``deep``: at more length, gameinfo.talk)."""
    text = kobold.games_text([row]).replace("games played: ", "game played this week: ")
    if deep and gameinfo.talk(info):
        return f"{text}. {_stop(gameinfo.talk(info))}"
    return text + (f". {row['game']} is {_about(info)}" if _about(info) else "") + "."


def as_tall(p: Dict[str, Any], tid: str) -> Dict[str, Any]:
    """The draft as tall picture ``tid`` sees it: with the picture's own host style when it has one
    (p["talls"][tid]["host"], set on the builder's Look card) in place of the article's host. A copy of
    the top level only: its chunks, lines and facts are the draft's own objects."""
    own = ((p.get("talls") or {}).get(tid) or {}).get("host")
    return dict(p, host=own) if own in hosts.HOSTS and own != p.get("host") else p


def _stream_short(week: Any, t: Any) -> str:
    """One stream in a few words for a picture's summary: "Lulu streamed Valheim on Monday for 3 hours"
    (a stream with no known game goes by its title)."""
    d = next((i for i, tiles in enumerate(week.days) if any(x is t for x in tiles)), None)
    day = f" on {week.date_of(d).strftime('%A')}" if d is not None else ""
    title = " ".join(w for w in str(t.title or "").split() if not w.startswith("#"))
    what = f" {t.game}" if t.game else (f' "{title}"' if title else "")
    if t.kind == "past":
        return f"{t.name} streamed{what}{day}" + (f" for {hosts.length_words(t.length)}" if t.end else "")
    return f"{t.name} is live now{' with' + what if what else ''}" if t.kind == "live" else f"{t.name} plans{what or ' a stream'}{day}"


def stack_facts(store: Any, p: Dict[str, Any], week: Any, chunks: List[Dict[str, Any]]) -> str:
    """What a tall picture shows, as the facts sentence for a host moment's or sign-off strip's line: its
    header, then what its stream, game, day and number chunks hold, in order (at most SUMMARY_ITEMS
    streams). A stack with none of those falls back to the review's own facts."""
    title, streams, games_, extra = "", [], [], []
    rows = {r["game"].lower(): r for r in game_rows(p.get("facts") or {}, week)}
    for c in chunks:
        t = c.get("type")
        if t == "header" and not title:
            title = " ".join(str(c.get("title") or host_picker.heading_of(p, "Week in Review")).split())
            sub = " ".join(str(c.get("sub") or "").split())
            title += f" ({sub})" if sub else ""
        elif t == "stream":
            _, tile = tall._tile_of(c.get("ref") or "", week)
            if tile is not None:
                streams.append(_stream_short(week, tile))
        elif t == "game" and str(c.get("game") or "").lower() in rows:
            games_.append(rows[str(c["game"]).lower()])
        elif t == "grid" and getattr(week, "days", None):
            d = max(0, min(len(week.days) - 1, int(c.get("day") or 0)))
            who = ", ".join(f"{x.name} ({x.game})" if x.game else x.name for x in week.days[d])
            extra.append(f"{week.date_of(d).strftime('%A')}: {who}" if who else f"{week.date_of(d).strftime('%A')} had no streams")
        elif t == "stats":
            extra.append("the numbers: " + kobold.facts_text(p.get("facts") or {}).rstrip("."))
    more = len(streams) - SUMMARY_ITEMS
    parts = streams[:SUMMARY_ITEMS] + ([f"and {more} more stream{'' if more == 1 else 's'}"] if more > 0 else [])
    if games_:
        parts.append(kobold.games_text(games_))
    parts += extra
    if not parts:
        return kobold.facts_text(p.get("facts") or {})
    return (f'This picture is "{title}". ' if title else "") + "It shows: " + "; ".join(parts) + "."


def ask_kind(c: Dict[str, Any]) -> str:
    """Which kobold.ASKS entry writes this chunk's line: its type, the game-talk ask when the chunk's
    "The remark is about" menu says the game, or the picture asks for a host moment / sign-off strip."""
    if c.get("type") in SUMMARY_TYPES:
        return "tall_signoff" if c.get("type") == "footer" else "tall_host"
    if c.get("about") == "game":
        return "stream_game" if c.get("type") == "stream" else "game_talk"
    return str(c.get("type") or "")


def chunk_game(p: Dict[str, Any], week: Any, c: Dict[str, Any]) -> str:
    """The game a stream / game chunk is about ("" = none: no stream picked, or its game isn't known)."""
    if c.get("type") == "stream":
        _, t = tall._tile_of(c.get("ref") or "", week)
        return str(getattr(t, "game", "") or "")
    return str(c.get("game") or "") if c.get("type") == "game" else ""


def chunk_facts(store: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any], chunks: Any = None) -> str:
    """The facts for a chunk's line ("" = the chunk points at nothing yet), with the owner's ``hint``.
    ``chunks``: the whole stack, for a host moment / sign-off strip (their facts are the other chunks)."""
    deep, facts = c.get("about") == "game", ""
    if c.get("type") in SUMMARY_TYPES:
        facts = stack_facts(store, p, week, [x for x in chunks or [] if x is not c])
    if c.get("type") == "stream":
        _, t = tall._tile_of(c.get("ref") or "", week)
        facts = stream_facts(store, week, t, deep) if t is not None else ""
    if c.get("type") == "game":
        row = next((r for r in game_rows(p.get("facts") or {}, week) if r["game"].lower() == str(c.get("game") or "").lower()), None)
        facts = game_facts(row, gameinfo.cached(store, row["game"]), deep) if row else ""
    hint = " ".join(str(c.get("hint") or "").split())[:HINT_MAX]
    return facts + (f" The producer adds: {_stop(hint)}" if facts and hint else "")


async def _details(poster: Any, game: str) -> None:
    """Make sure ``game``'s IGDB details are kept before a remark is written (one look-up, only when they
    aren't there or are from before the game-talk details; at most DETAILS_WAIT seconds, never an error)."""
    gi = getattr(poster, "game_info", None)
    if gi is None or not game:
        return
    try:
        await asyncio.wait_for(gi.lookup(game), DETAILS_WAIT)
    except Exception as e:                            # the details are a nice-to-have; the remark goes on without
        log.info("game details for %s not fetched: %s", game, e)


async def _ready(poster: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any], chunks: Any = None) -> Tuple[str, str]:
    """(facts, "") for a chunk's line, or ("", why not) for the page: nothing picked yet, or a remark
    about the game on a stream whose game isn't known. ``chunks``: the whole stack (``chunk_facts``)."""
    game = chunk_game(p, week, c)
    if c.get("about") == "game" and c.get("type") == "stream" and not game and tall._tile_of(c.get("ref") or "", week)[1] is not None:
        return "", "This stream has no game yet. Set it under Game on the chunk, then try again."
    await _details(poster, game)
    facts = chunk_facts(poster.store, p, week, c, chunks)
    return facts, "" if facts else "Pick a stream or game for that chunk first."


async def write_line(poster: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any], chunks: Any = None) -> Tuple[str, str]:
    """✨ for one chunk: (new line or "", note for the page). One request; the chunk's own host speaks.
    ``chunks``: the chunk's whole stack (needed for a host moment / sign-off strip)."""
    kob = getattr(poster, "kobold", None)
    if kob is None:
        return "", "KoboldCpp isn't set up (Settings → KoboldCpp)."
    facts, why = await _ready(poster, p, week, c, chunks)
    if not facts:
        return "", why
    host = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
    kind = ask_kind(c)
    new = await kob.line(host, kobold.asks()[kind], host_picker.heading_of(p, "review"), facts, kind=kind)
    if new is None:
        return "", "KoboldCpp couldn't be reached."
    if not new:
        return "", f"KoboldCpp answered, but with no usable line. Try again. Its answer: {kob.last_raw[:200]}"
    return new, "✨ Wrote the remark."


async def write_choices(poster: Any, p: Dict[str, Any], week: Any, c: Dict[str, Any], chunks: Any = None
                        ) -> Tuple[List[str], str]:
    """✨ on one chunk (owner 2026-11-22: several to pick from, as the host lines work): (lines, note for the
    page). As many requests as the settings page's "lines per slot" (kobold.Kobold.per_slot); the builder
    lists them under the remark and picks the first. ``chunks``: the chunk's whole stack."""
    kob = getattr(poster, "kobold", None)
    if kob is None:
        return [], "KoboldCpp isn't set up (Settings → KoboldCpp)."
    facts, why = await _ready(poster, p, week, c, chunks)
    if not facts:
        return [], why
    host = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
    kind = ask_kind(c)
    new = await kob.lines(host, kobold.asks()[kind], host_picker.heading_of(p, "review"), facts, kind=kind)
    if new is None:
        return [], "KoboldCpp couldn't be reached."
    if not new:
        return [], f"KoboldCpp answered, but with no usable line. Try again. Its answer: {kob.last_raw[:200]}"
    return new, f"✨ {len(new)} remark{'' if len(new) == 1 else 's'} to pick from (the first is in)."


CHAT_TURNS = 4              # lines KoboldCpp writes for a chat chunk (the chunk draws up to 5)


async def write_chat(poster: Any, p: Dict[str, Any], c: Dict[str, Any]) -> Tuple[str, str]:
    """✨ on a chat chunk (owner 2026-11-22: hosts answering each other): (the chat's rows, one per line, or
    ""; note for the page). The chunk's two hosts take turns about the review's facts, one request per
    turn (kobold.Kobold.chat), the first speaker being the chunk's own (else the article's host)."""
    kob = getattr(poster, "kobold", None)
    if kob is None:
        return "", "KoboldCpp isn't set up (Settings → KoboldCpp)."
    first = c.get("host") if c.get("host") in hosts.HOSTS else p["host"]
    second = c.get("other") if c.get("other") in hosts.HOSTS and c.get("other") != first else hosts.other(first)
    got = await kob.chat(first, second, host_picker.heading_of(p, "review"), kobold.facts_text(p.get("facts") or {}),
                         CHAT_TURNS)
    if got is None:
        return "", "KoboldCpp couldn't be reached."
    if not got:
        return "", f"KoboldCpp answered, but with no usable line. Try again. Its answer: {kob.last_raw[:200]}"
    return "\n".join(x[:CHAT_LINE] for x in got), f"✨ Wrote a chat of {len(got)} lines."


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
    # empty remarks, and chat chunks with nothing typed yet (their text field is "lines")
    field = lambda c: "lines" if c.get("type") == "chat" else "line"     # noqa: E731
    # (host moments and the sign-off strip come last: their line sums up the picture)
    todo = [c["id"] for c in ((store.get(dkey) or {}).get("talls", {}).get(tid, {}).get("chunks") or [])
            if (c.get("type") in LINE_TYPES + SUMMARY_TYPES or c.get("type") == "chat") and not c.get(field(c))]
    state = "done"
    for cid in todo:
        p = store.get(dkey)
        c = next((x for x in (p or {}).get("talls", {}).get(tid, {}).get("chunks", []) if x["id"] == cid), None)
        if c is None or c.get(field(c)):
            continue
        try:
            q = as_tall(p, tid)                       # the picture's own host style speaks
            line, _ = (await write_chat(poster, q, c) if c["type"] == "chat" else
                       await write_line(poster, q, week, c, p["talls"][tid]["chunks"]))
        except Exception:
            log.exception("KoboldCpp remark failed")
            line = ""
        p = store.get(dkey)                           # re-read: saved edits must not be overwritten
        c = next((x for x in (p or {}).get("talls", {}).get(tid, {}).get("chunks", []) if x["id"] == cid), None)
        if not line:
            state = "offline" if not str(getattr(poster.kobold, "last_raw", "") or "").strip() else "nolines"
            break
        if c is not None and not c.get(field(c)):
            c[field(c)] = line
            p["saved_at"] = time.time()
            store.put(dkey, p)
    p = store.get(dkey)
    if p and tid in (p.get("talls") or {}):
        p["talls"][tid]["ai_state"] = state
        store.put(dkey, p)


# ---- the recipes ---------------------------------------------------------------------------------

SEAMS = {"": "straight seams", "diagonal": "diagonal seams", "zig": "zigzag seams", "wave": "wavy seams"}


def apply_seams(chunks: List[Dict[str, Any]], seams: str) -> None:
    """Give every chunk of a stack but the last the same kind of bottom edge (a SEAMS key: "" straight,
    "diagonal" slanting down and up in turn, "zig", "wave"), gently sloped. An unknown key changes nothing.
    Used by the recipes and by the builder's Look card (flavrpromo/tall_page.py "seams")."""
    if seams not in SEAMS:
        return
    for i, c in enumerate(chunks[:-1]):
        c["cut"] = ("down", "up")[i % 2] if seams == "diagonal" else seams
        if seams:
            c["slope"] = 0


def apply_look(chunks: List[Dict[str, Any]], look: str) -> None:
    """Give every stream chunk of a stack the same ``look`` (a tall.LOOKS key: "" the plain row, "strip" the
    colour strip of the day pictures). Other chunk types and an unknown key are left alone. Used by the
    recipes and by the builder's Look card (flavrpromo/tall_page.py "looks")."""
    if look not in tall.LOOKS:
        return
    for c in chunks:
        if c.get("type") == "stream":
            c["look"] = look


def _pictures(title: str, subs: List[str], items: List[Dict[str, Any]], seams: Any) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Split ``items`` (stream / game chunks, no ids yet) over as few pictures as fit tall.MAX_H, in
    balanced groups, each with a header and, on the last one, a sign-off strip. Medium size first; small
    when that avoids a split. ``seams``: a SEAMS key (True = "diagonal"). ``subs``: the header line under the title (one per picture, or one for all)."""
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
        if seams:
            apply_seams(chunks, "diagonal" if seams is True else seams)                # True: the old yes / no
        out.append((title if count == 1 else f"{title} ({n + 1} of {count})", tall.renumber(chunks)))
    return out


def build(recipe: str, p: Dict[str, Any], week: Any, arg: str = "", diagonal: Any = False, look: str = ""
          ) -> Tuple[List[Tuple[str, List[Dict[str, Any]]]], str]:
    """([(section title, chunks)], error text). ``arg``: the day number for "day", the person's name
    for "person". ``look``: a tall.LOOKS key for the stream chunks ("strip" = colour strips like the day
    pictures; the games recipe has none). Empty list + a message when the week has nothing for that recipe."""
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
    apply_look(items, look)
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


def add_to_draft(p: Dict[str, Any], built: List[Tuple[str, List[Dict[str, Any]]]], on: bool = True) -> List[str]:
    """Put built pictures into the draft as tall sections just before the outro; their ids. ``on``: are
    they part of the article (False for a picture made on the Tall pictures page for a post of its own)."""
    ids = []
    for title, chunks in built:
        sid = next_tall_id(p)
        p.setdefault("talls", {})[sid] = {"chunks": chunks}
        at = next((i for i, s in enumerate(p["sections"]) if s["id"] == "outro"), len(p["sections"]))
        p["sections"].insert(at, {"id": sid, "title": title, "on": on})
        ids.append(sid)
    return ids


__all__ = ["as_tall", "apply_seams", "apply_look", "stack_facts", "SUMMARY_TYPES", "RECIPES", "SEAMS", "build", "fill", "people", "add_to_draft", "write_line", "write_choices", "start_lines", "game_rows", "drawing_context",
           "chunk_facts", "stream_facts", "game_facts", "AI_STATES", "LINE_TYPES", "next_tall_id"]
