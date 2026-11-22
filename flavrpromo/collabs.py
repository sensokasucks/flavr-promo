"""
Collab streams (owner 2026-11-22: "detect an @mention of other friend/group (like FlaVR) and mark
that as a possible collab for me to confirm it, then we can give that a special highlight on the
calendars").

How it works
  1. Spotting (``scan``, every calendar tick in flavrpromo/calendar_post.py): each stream title of
     this week and next (live / past streams in the sessions table, upcoming ones in the scheduled
     table) is read for
       * an @mention: "@FlaVR", "@luluteala", "@Pippa" (``find``). It is matched to a group (its key or
         name) or a person the bot follows (name, a channel handle or display name, X handle). An @
         nobody here knows still counts ("@someone" = kind "handle"): collabs with outside streamers;
       * "w/", "with", "ft.", "feat.", "featuring" followed by the name of a person the bot follows
         ("cozy night w/ Lulu"). Only known people here, so "with friends" or "with chat" never count.
     Left out: the person themself (their own name or channels), their OWN group ("@FlaVR" in a FlaVR
     member's title is like the #flavr hashtag on every stream, not a collab), @everyone / @here.
     Hashtags (#flavr) are never read: they're on nearly every title.
  2. A stream with a mention gets a "suggested" row (store table collabs). The owner gets one DM per
     suggestion with Confirm / Not a collab buttons (flavrpromo/bot.py ``dm_collab``; the /pings kind
     "collab"; held during quiet hours), and it is listed on the web page /settings/collabs and by
     /collab list. Dismissed rows are never suggested again for that stream; a suggested row picks up
     new names when the title changes. When both streamers tag each other it's one question: the
     second row follows the first one's answer (``twins``).
  3. Confirmed rows (``mark``, from calendar.build_week) set ``Tile.collab`` to the partners' names; the
     partner's own tile at the same time (a person the bot follows) gets the first person's name too.
     Everything that draws the calendar shows it: the board picture and day / focus pictures
     (flavrpromo/render.py, a gold COLLAB ribbon and "with ..." line), the post's list
     (calendar_post.line), the copy-ready text (share.py) and the .ics feed (web.py).
  The owner can also mark a stream by hand (``add``: the web page's "Mark a collab" form, /collab add).

Settings (kv): "collab_detect" false = no spotting (confirmed ones still show). Matching window: a
collab row belongs to the person's stream that starts within calendar.MATCH_WINDOW of its ``at``, so a
confirmed scheduled stream stays confirmed when it goes live.

Who calls it: calendar.py ``build_week`` (``mark``), calendar_post.py ``CalendarPoster.collab_tick``
(``scan`` + the DMs), bot.py (/collab, the DM buttons), collab_page.py (the web page).
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional

from . import groups
from .store import Store

SCAN_BACK = 86400.0            # scan from yesterday (a stream that's on now may have started then) ...
SCAN_AHEAD = 14 * 86400.0      # ... to two weeks ahead (this week's board and next week's)
SKIP_HANDLES = {"everyone", "here", "channel", "youtube", "twitch", "kick", "x", "twitter"}

# "@name": letters, digits, _ . - (YouTube handles allow . and -); not inside an e-mail address
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][\w.\-]{0,38}[A-Za-z0-9_]|[A-Za-z0-9])")
# "w/ Lulu", "with Lulu", "ft. Lulu", "feat Lulu", "featuring Lulu": the words that follow are tried
# against known people only (``_after_with``)
WITH = re.compile(r"(?i)(?:(?<![\w])w/|\bwith\b|\bft\b\.?|\bfeat\b\.?|\bfeaturing\b)\s*@?")
WITH_WORDS = 4                 # names up to this many words ("Mumkey Dee", "Cara Malone")


def norm(text: str) -> str:
    """Lower case letters and digits only, for matching: "Cara Malone" = "caramalone" = "@CaraMalone"."""
    return re.sub(r"[^0-9a-z]", "", (text or "").lower())


class Index:
    """Everyone a title could mention, by normalised name. Built once per scan from store.people()
    and the groups (flavrpromo/groups.py)."""

    def __init__(self, people: Iterable[Dict[str, Any]], group_keys: Iterable[str]):
        self.people: Dict[str, Dict[str, Any]] = {}       # normalised name / handle → partner dict
        self.groups: Dict[str, Dict[str, Any]] = {}
        self.own: Dict[int, set] = {}                      # person id → their own normalised names
        self.group_of: Dict[int, str] = {}
        for g in group_keys:
            if g == "community":                           # the self-promo board (promo.py), not a team
                continue
            part = {"kind": "group", "key": g, "name": groups.name(g)}
            for n in (g, groups.name(g)):
                if norm(n):
                    self.groups[norm(n)] = part
        for p in people:
            names = {p.get("name") or "", p.get("x_handle") or ""}
            for a in p.get("accounts") or []:
                names |= {a.get("handle") or "", a.get("display") or ""}
            keys = {norm(n.lstrip("@")) for n in names} - {""}
            self.own[int(p["id"])] = keys
            self.group_of[int(p["id"])] = p.get("grp") or ""
            part = {"kind": "person", "key": int(p["id"]), "name": p["name"]}
            for k in keys:
                self.people.setdefault(k, part)

    def mention(self, handle: str) -> Dict[str, Any]:
        """What "@handle" points at: a person, a group, or an unknown handle."""
        k = norm(handle)
        return self.people.get(k) or self.groups.get(k) or {"kind": "handle", "key": handle.lower(), "name": "@" + handle}


def _after_with(text: str, index: Index) -> Optional[Dict[str, Any]]:
    """The known person named right after "w/" / "with" / "ft.": the longest run of up to WITH_WORDS
    words that matches a person's name or handle. None when it's no one the bot follows."""
    words = re.findall(r"[\w.\-']+", text[:80])
    for n in range(min(WITH_WORDS, len(words)), 0, -1):
        part = index.people.get(norm("".join(words[:n])))
        if part:
            return part
    return None


def find(title: str, person_id: int, index: Index) -> List[Dict[str, Any]]:
    """The collab partners a stream title names (see the module notes), in title order, no repeats.
    ``person_id``: whose stream it is (they and their own group are left out)."""
    title = title or ""
    out: List[Dict[str, Any]] = []
    own = index.own.get(person_id, set())
    own_group = index.group_of.get(person_id, "")

    def keep(part: Optional[Dict[str, Any]]) -> None:
        if not part:
            return
        if part["kind"] == "person" and int(part["key"]) == person_id:
            return
        if part["kind"] == "group" and part["key"] == own_group:
            return
        if part["kind"] == "handle" and (norm(part["key"]) in own or part["key"] in SKIP_HANDLES):
            return
        if not any(p["kind"] == part["kind"] and p["key"] == part["key"] for p in out):
            out.append(dict(part))

    hits = [(m.start(), "@", m.group(1)) for m in MENTION.finditer(title)]
    hits += [(m.end(), "w", title[m.end():]) for m in WITH.finditer(title)]
    for _, how, text in sorted(hits, key=lambda h: h[0]):
        keep(index.mention(text) if how == "@" else _after_with(text, index))
    return out


def names(partners: List[Dict[str, Any]]) -> List[str]:
    return [p.get("name") or "" for p in partners if p.get("name")]


def enabled(store: Store) -> bool:
    """Spotting on (kv "collab_detect", default on; the web page's switch)."""
    return store.get("collab_detect") is not False


def scan(store: Store, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Read the titles from SCAN_BACK ago to SCAN_AHEAD ahead and save what they mention (module notes,
    step 2). Returns the rows that are NEW suggestions (the caller DMs those). Quick: a few hundred
    rows at most. Called by calendar_post.CalendarPoster.collab_tick about once a minute."""
    from .calendar import MATCH_WINDOW         # late import: calendar.py imports this module
    if not enabled(store):
        return []
    now = time.time() if now is None else now
    a, b = now - SCAN_BACK, now + SCAN_AHEAD
    people = [p for p in store.people() if not p.get("hidden")]
    ids = {p["id"] for p in people}
    index = Index(people, groups.keys())
    items = [(s["person_id"], float(s["started_at"]), s.get("title") or "") for s in store.sessions_between(a, b)]
    items += [(s["person_id"], float(s["at"]), s.get("title") or "") for s in store.scheduled_between(a, b)]
    fresh: List[Dict[str, Any]] = []
    for pid, at, title in sorted(items, key=lambda i: i[1]):
        if pid not in ids or not title:
            continue
        found = find(title, pid, index)
        if not found:
            continue
        row = store.collab_near(pid, at, MATCH_WINDOW)
        if row is None:
            # both streamers tagged each other: the other side's row decides this one too (one DM)
            twin = next(iter(twins(store, pid, at, found)), None)
            if twin and twin["state"] != "suggested":
                store.collab_add(pid, at, found, title, state=twin["state"], now=now)
                continue
            cid = store.collab_add(pid, at, found, title, now=now)
            if twin:
                store.collab_update(cid, dm_sent=1)
                continue
            fresh.append(store.collab_get(cid) or {})
            continue
        if row["state"] == "suggested":
            # the title changed (or the live title names someone the schedule didn't): add the new names
            have = {(p["kind"], p["key"]) for p in row["partners"]}
            more = [p for p in found if (p["kind"], p["key"]) not in have]
            if more:
                store.collab_update(row["id"], partners=row["partners"] + more, title=title)
    return [r for r in fresh if r]


def add(store: Store, person_id: int, at: float, partners: List[Dict[str, Any]], title: str = "",
        now: Optional[float] = None) -> int:
    """Mark a stream as a confirmed collab by hand (web page / /collab add). An existing row for that
    stream is confirmed and gets the names added. Returns the row id."""
    from .calendar import MATCH_WINDOW
    now = time.time() if now is None else now
    row = store.collab_near(person_id, at, MATCH_WINDOW)
    if row:
        have = {(p["kind"], p["key"]) for p in row["partners"]}
        merged = row["partners"] + [p for p in partners if (p["kind"], p["key"]) not in have]
        store.collab_update(row["id"], partners=merged, state="confirmed", decided_at=now)
        return int(row["id"])
    return store.collab_add(person_id, at, partners, title, state="confirmed", source="manual", now=now)


def twins(store: Store, person_id: int, at: float, partners: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The other side of a two-way tag: rows of the people in ``partners`` within MATCH_WINDOW of ``at``
    that name ``person_id`` back (Pippa's "w/ @luluteala" and Lulu's "w/ @pipkinpippa" are one collab)."""
    from .calendar import MATCH_WINDOW
    out = []
    for p in partners:
        if p.get("kind") != "person":
            continue
        r = store.collab_near(int(p["key"]), at, MATCH_WINDOW)
        if r and any(q.get("kind") == "person" and int(q["key"]) == person_id for q in r["partners"]):
            out.append(r)
    return out


def decide(store: Store, cid: int, yes: bool, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Confirm (``yes``) or dismiss one row (DM buttons, web page, /collab confirm | dismiss). The other
    side of a two-way tag (``twins``) still waiting gets the same answer. Returns the row after the
    change, None when it's gone."""
    row = store.collab_get(cid)
    if not row:
        return None
    state, when = ("confirmed" if yes else "dismissed"), (time.time() if now is None else now)
    store.collab_update(cid, state=state, decided_at=when)
    for t in twins(store, row["person_id"], float(row["at"]), row["partners"]):
        if t["state"] == "suggested":
            store.collab_update(t["id"], state=state, decided_at=when)
    return store.collab_get(cid)


def partners_from_text(store: Store, text: str, person_id: int = 0) -> List[Dict[str, Any]]:
    """Partners typed by the owner ("FlaVR, Lulu, @someone"): each comma-separated part is a group, a
    person the bot follows, or else kept as typed (an outside streamer)."""
    index = Index(store.people(), groups.keys())
    out: List[Dict[str, Any]] = []
    for raw in (text or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        part = index.people.get(norm(raw.lstrip("@"))) or index.groups.get(norm(raw.lstrip("@")))
        if not part:
            part = {"kind": "handle", "key": raw.lower(), "name": raw}
        if part["kind"] == "person" and int(part["key"]) == person_id:
            continue
        if not any(p["kind"] == part["kind"] and p["key"] == part["key"] for p in out):
            out.append(dict(part))
    return out


def mark(store: Store, tiles: List[Any]) -> None:
    """Set ``collab`` (partner names) on each tile that is a confirmed collab; called by
    calendar.build_week for every board, review, focus and talent picture. A partner the bot follows
    who streams at the same time gets the first person's name on their own tile too."""
    from .calendar import MATCH_WINDOW
    mine = [t for t in tiles if getattr(t, "person_id", 0)]
    if not mine:
        return
    a = min(t.at for t in mine) - MATCH_WINDOW
    b = max(t.at for t in mine) + MATCH_WINDOW
    rows = store.collabs_between(a, b, "confirmed")
    for t in mine:
        for r in rows:
            if abs(float(r["at"]) - t.at) >= MATCH_WINDOW:
                continue
            if r["person_id"] == t.person_id:
                add_names = names(r["partners"])
            elif any(p["kind"] == "person" and int(p["key"]) == t.person_id for p in r["partners"]):
                add_names = [r["name"]]          # the partner's own stream: "with <who mentioned them>"
            else:
                continue
            for n in add_names:
                if n and n not in t.collab:
                    t.collab.append(n)


def with_text(partners: List[str], limit: int = 3) -> str:
    """"with FlaVR, Lulu and Pippa" (more than ``limit`` names: "with FlaVR, Lulu +2")."""
    if not partners:
        return ""
    if len(partners) > limit:
        return "with " + ", ".join(partners[:limit - 1]) + f" +{len(partners) - limit + 1}"
    if len(partners) == 1:
        return "with " + partners[0]
    return "with " + ", ".join(partners[:-1]) + " and " + partners[-1]


def dm_text(row: Dict[str, Any]) -> str:
    """The owner's DM for one suggestion (bot.py ``dm_collab`` adds the buttons). <t:…:F> shows the
    stream's time in the reader's own time zone."""
    title = (row.get("title") or "").replace("`", "'")[:150]
    who = ", ".join(names(row["partners"]))
    return (f"🤝 **Possible collab:** **{row['name']}** <t:{int(row['at'])}:F> mentions **{who}**\n> {title}\n"
            "Confirm it and it gets the collab highlight on the calendars.")


def streams_of(store: Store, person_id: int, now: float) -> List[Dict[str, Any]]:
    """This person's streams the collab marks can point at, from SCAN_BACK ago to SCAN_AHEAD ahead:
    [{at, title, kind}] oldest first (kind "stream" = the watcher saw it, "scheduled" = upcoming). A
    scheduled item within MATCH_WINDOW of a real stream is left out (it's the same stream).
    Used by ``pick_stream`` (/collab add) and the web page's "Mark a collab" menu."""
    from .calendar import MATCH_WINDOW
    a, b = now - SCAN_BACK, now + SCAN_AHEAD
    out = [{"at": float(s["started_at"]), "title": s.get("title") or "", "kind": "stream"}
           for s in store.sessions_between(a, b) if s["person_id"] == person_id]
    for s in store.scheduled_between(a, b):
        if s["person_id"] == person_id and not any(abs(o["at"] - float(s["at"])) < MATCH_WINDOW for o in out):
            out.append({"at": float(s["at"]), "title": s.get("title") or "", "kind": "scheduled"})
    return sorted(out, key=lambda o: o["at"])


def pick_stream(store: Store, person_id: int, now: float, tz: Any, weekday: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The stream /collab add means: on ``weekday`` (0 = Sunday ... 6 = Saturday, local time) the first one
    from today on; without a day the one on now (started in the last 12 h) or else the next one."""
    from datetime import datetime
    items = streams_of(store, person_id, now)
    if weekday is not None:
        items = [i for i in items if (datetime.fromtimestamp(i["at"], tz).weekday() + 1) % 7 == weekday
                 and i["at"] >= now - 12 * 3600]
        return items[0] if items else None
    recent = [i for i in items if now - 12 * 3600 <= i["at"] <= now]
    if recent:
        return recent[-1]
    ahead = [i for i in items if i["at"] > now]
    return ahead[0] if ahead else None
