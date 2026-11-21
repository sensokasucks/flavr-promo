"""
The two hosts, Colette Cappuccino and Clark, who present FlaVR Promo's posts (owner 2026-11-20,
plan doc "FlaVR Bot presenter plan"). Still pictures only: a pose picture and a speech bubble on
review cards, a desk picture for the sign-off, and one line from the host above each go-live card.

This file holds who the hosts are, their pictures, which one presents a post, and their lines:
  * HOSTS: name, job, emoji and colours. Colette (Marketing) is loud, upbeat and caffeinated, with
    FlaVR colours and sticky notes. Clark (Division Clerk) is calm and dry, a filed report on
    cream paper. Card layouts are in flavrpromo/host_cards.py.
  * Pictures: the owner's art is built in (flavrpromo/host_art, transparent WebP); uploads from
    Discord with /host picture go to DATA_DIR/hosts/<host>/<kind>.png (or .jpg / .webp) and win. Kinds: happy, pointing, sleepy
    (poses for the opener), desk (the sign-off card), head (the small face on go-live cards) and
    chibi_happy / chibi_pointing / chibi_sleepy (chibi versions: peeking over the opener card, the
    go-live face when there's no head, and on day posts), chibi_desk (the desk card's other look,
    picked on the picker page) and chibi_head. Built-in defaults of all ten (the owner's art) are in
    flavrpromo/host_art; an upload replaces one. A missing pose falls back to another pose,
    a missing chibi to another chibi; no pictures at all still works (text only).
  * Which host: random per post, but never the same one three times in a row (kv host_last), or
    always one when the owner picks it (/host setup only:). Off until /host setup on (kv hosts_on),
    so other groups running their own copy see no change until they add hosts.
  * Lines: TEMPLATES per host and situation ("slot"), with blanks filled from real numbers
    (``facts``). A template whose blank has no value is skipped, so a line never says "{name}".
    Go-live cards use one at random (they can't wait). Reviews wait for the owner to pick from
    several on the picker page (flavrpromo/host_picker.py); KoboldCpp lines join them in a later
    round.

Who calls it: flavrpromo/bot.py (live cards, /host commands), flavrpromo/host_picker.py (reviews),
flavrpromo/__main__.py (``init`` with the pictures folder).
"""

from __future__ import annotations

import base64
import mimetypes
import random
import string
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import gameinfo
from .store import Store

HOSTS: Dict[str, Dict[str, str]] = {
    "colette": {"name": "Colette Cappuccino", "role": "Marketing", "emoji": "☕", "accent": "#f72ca2"},
    "clark": {"name": "Clark", "role": "Division Clerk", "emoji": "🍎", "accent": "#e0782e"},
}
KINDS = ("happy", "pointing", "sleepy", "desk", "head", "chibi_happy", "chibi_pointing", "chibi_sleepy",
         "chibi_desk", "chibi_head")
POSES = ("happy", "pointing", "sleepy")
CHIBIS = ("chibi_happy", "chibi_pointing", "chibi_sleepy")     # the same three moods, small (Sen 2026-11-21)
EXTS = (".png", ".jpg", ".jpeg", ".webp")
MAX_PICTURE = 8 * 1024 * 1024       # bytes; one uploaded picture
LONG_STREAM = 4 * 3600.0            # a stream this long gets the "long stream" end line (s)
BUSY_STREAMS, BUSY_HOURS = 8, 20    # a review this full is "busy" (happy pose, busy opener)
QUIET_STREAMS = 2                   # this few streams or fewer is "quiet" (sleepy pose)

_folder: Optional[Path] = None      # DATA_DIR/hosts (set by flavrpromo/__main__.py; None in tests = no pictures)
# the built-in pictures (owner's art, 2026-11-21, transparent WebP, flavrpromo/host_art/<host>/<kind>.webp);
# an upload of the same kind in DATA_DIR/hosts wins. Off until init (tests see no pictures).
DEFAULTS = Path(__file__).resolve().parent / "host_art"
_defaults = False


def init(folder: Optional[Path], defaults: bool = True) -> None:
    global _folder, _defaults
    _folder = Path(folder) if folder else None
    _defaults = defaults


# ── switches and choosing ──────────────────────────────────────────────
def enabled(store: Store) -> bool:
    """/host setup on: hosts present live cards and reviews (reviews then wait for the picker)."""
    return bool(store.get("hosts_on"))


def choose(store: Store, rng: Optional[random.Random] = None) -> str:
    """The host for a new post: the one picked with /host setup only:, else random, never three in a row."""
    only = str(store.get("hosts_only") or "")
    if only in HOSTS:
        return only
    last = list(store.get("host_last") or [])[-2:]
    keys = list(HOSTS)
    if len(last) == 2 and last[0] == last[1] and last[0] in keys and len(keys) > 1:
        keys.remove(last[0])                        # twice in a row already: the other one now
    key = (rng or random).choice(keys)
    store.put("host_last", (last + [key])[-2:])
    return key


# ── pictures ───────────────────────────────────────────────────────────
def picture(key: str, kind: str) -> Optional[Path]:
    """The picture file, or None. A missing pose falls back to another pose."""
    if key not in HOSTS:
        return None
    folders = [f for f in (_folder, DEFAULTS if _defaults else None) if f is not None]
    family = POSES if kind in POSES else CHIBIS if kind in CHIBIS else ()
    for k in [kind] + [p for p in family if p != kind]:      # the exact kind first (yours, then built-in)
        for folder in folders:
            for ext in EXTS:
                p = folder / key / f"{k}{ext}"
                if p.is_file():
                    return p
    return None


def face(key: str) -> Optional[Path]:
    """The small face on go-live cards: the head picture, else the chibi head, else a chibi."""
    return picture(key, "head") or picture(key, "chibi_head") or picture(key, "chibi_happy")


def data_url(key: str, kind: str) -> str:
    """A picture as a data: URL for the card pages ("" when there is none)."""
    p = picture(key, kind)
    if not p:
        return ""
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def save_picture(key: str, kind: str, data: bytes, filename: str) -> str:
    """/host picture: save an upload; returns "" when saved, else why not."""
    if _folder is None:
        return "The bot has no data folder for pictures."
    ext = Path(filename or "").suffix.lower()
    if key not in HOSTS or kind not in KINDS:
        return "Unknown host or picture kind."
    if ext not in EXTS:
        return "Send a PNG, JPG or WebP picture."
    if len(data) > MAX_PICTURE:
        return "That picture is over 8 MB."
    folder = _folder / key
    folder.mkdir(parents=True, exist_ok=True)
    for old in EXTS:                                # one file per kind: replace any older one
        (folder / f"{kind}{old}").unlink(missing_ok=True)
    (folder / f"{kind}{'.jpg' if ext == '.jpeg' else ext}").write_bytes(data)
    return ""


def remove_picture(key: str, kind: str) -> bool:
    """The settings page's "back to built-in": delete the uploaded picture of this kind (True if one was there)."""
    if _folder is None or key not in HOSTS or kind not in KINDS:
        return False
    gone = False
    for ext in EXTS:
        f = _folder / key / f"{kind}{ext}"
        if f.is_file():
            f.unlink()
            gone = True
    return gone


def pictures(key: str) -> Dict[str, str]:
    """/host list: for each kind "yours" (uploaded), "built-in" or "" (exact files, no fallback)."""
    out = {}
    for kind in KINDS:
        has = lambda folder: folder is not None and any((folder / key / f"{kind}{e}").is_file() for e in EXTS)  # noqa: E731
        out[kind] = "yours" if has(_folder) else "built-in" if _defaults and has(DEFAULTS) else ""
    return out


# ── lines ──────────────────────────────────────────────────────────────
# Blanks: {name} {game} {tag} {length} {signoff} {streams} {hours} {top_name} {top_count}
# {longest_name} {longest_len} {quiet_day} {quiet_name} {new_game} {new_game_name} {other} {streams_text} ("1 stream")
# go-live: {genre} (live_new_genre, IGDB's first genre)
# day posts: {when} ("Today", "This weekend") {when_lower} {count} {first_name} {first_time}
TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "colette": {
        "live_start": ["{name} is LIVE!! Grab a coffee and get in here! ☕", "Drop everything, {name} just went live!!",
                       "{name} is on air! This is not a drill!"],
        "live_game": ["{name} is LIVE with {game}!! Cappuccinos ready? ☕", "{game} time with {name}! Let's GOOO!"],
        "live_new_game": ["NEW GAME ALERT!! {name} is trying {game} for the first time!",
                          "{name} + {game} = a brand new adventure!! Be there for the first one!"],
        "live_new_genre": ["NEW GAME ALERT!! {name} is diving into {game}, a {genre} game! First time ever!",
                           "Brand new {genre} adventure: {name} is starting {game}!! Coffee up! ☕"],
        "live_part": ["{name} is back on {game}! {tag}, don't miss it!", "{game} {tag} with {name}! The saga continues!!"],
        "live_change": ["Plot twist! {name} switched to {game}!!", "{name} just moved over to {game}! Keep up, team!"],
        "live_end": ["{name} wrapped up after {length}! Great show!!", "That's a wrap for {name}! {length} of content, yes!"],
        "live_end_long": ["{length}?! {name}, I need a refill just from watching!", "{name} went {length} strong! Legend!!"],
        "live_end_signoff": ["{signoff} {name} signed off after {length}! ☕", "{length} with {name}! {signoff}"],
        "open_busy": ["OKAY team, gather round!! ☕ {streams} streams and {hours} hours live. {top_name} did {top_count}. I need to lie down.",
                      "What a run!! {streams} streams, {hours} hours! {top_name} carried with {top_count} shows!",
                      "{streams} streams?! {hours} hours?! The coffee machine filed a complaint. Here's the recap!"],
        "open_normal": ["Hi hi hi! {streams} streams and {hours} hours this time. Let's look!",
                        "Recap time!! {streams} streams, {hours} hours, and {longest_name} went longest!",
                        "Coffee in hand, recap ready! {streams} streams to go through!"],
        "open_quiet": ["A cozy one: {streams_text}. Quality over quantity, right?",
                       "Quiet stretch, team! {streams_text}. Recharge mode activated. ☕"],
        "open_empty": ["Nobody streamed?! I'm making a LOT of coffee for next time.",
                       "Zero streams this time. Everyone's resting, and so am I. ☕"],
        "note_longest": ["approved for the highlight reel", "absolute marathon!", "someone get them a snack"],
        "note_most": ["overtime form attached", "employee of the week!", "how?! HOW?!"],
        "note_quiet": ["we were... recharging", "the coffee was brewing", "a well-earned break"],
        "note_new_game": ["first time ever!", "new game energy!!", "a brand new adventure"],
        "desk_highlight": ["{longest_name}'s {longest_len} stream? I was there for ALL of it.",
                           "{top_name} did {top_count} shows. FIVE STARS. Maybe six.",
                           "{new_game_name} trying {new_game}? Best decision of the week."],
        "desk_nudge": ["Haven't seen {quiet_name} in a while. Go say hi!", "Next time: more {quiet_name}, please!",
                       "Next time? Bigger. Louder. More caffeine."],
        "desk_signoff": ["Colette out! ☕", "See you next time, team! Colette out!", "Refilling my mug. Bye bye!! ☕"],
        "day_one": ["{when}: {first_name} at {first_time}! Mark it, team!! ☕", "Just one on the board {when_lower}: {first_name}! Show some love!"],
        "day_many": ["{count} streams {when_lower}!! Starting with {first_name} at {first_time}! ☕",
                     "{when}: {count} streams lined up! Coffee's on, I'll see you there!!",
                     "{count} streams {when_lower}?! First up, {first_name}! Let's GO!"],
    },
    "clark": {
        # Clark (Sen 2026-11-21): still the tidy, calm clerk, but a big VTuber nerd who loves his job
        # because it's VTuber work; 90s nerd habits (VHS, dial-up, burned CDs, trading cards, a
        # Geocities shrine, AIM away messages, Toonami); now and then calls VTubers "Anime Americans".
        # Keep in step with his character card (flavrpromo/host_art/clark/card.json).
        "live_start": ["{name} is live. Filed under: worth watching. Also under: personal favourites.",
                       "{name} has started a stream. I've set the VCR to record, out of habit.",
                       "{name} is on air. Cider's on, chat window's open, away message set: 'watching streams, brb'.",
                       "Live now: {name}. One of our finest Anime Americans. Noted with enthusiasm."],
        "live_game": ["{name} is live with {game}. Filed under: worth watching.",
                      "{game}, with {name}. Now in session. I have snacks.",
                      "{name} is playing {game}. Adding it to the lore spreadsheet as we speak."],
        "live_new_game": ["{name} is starting {game} for the first time. A new folder has been opened. A new binder, honestly.",
                          "First {game} stream for {name}. I've noted the date, like a rookie card.",
                          "Brand-new game for {name}: {game}. Day one. I'll be telling people I was there."],
        "live_new_genre": ["{name} is starting {game}, a {genre} game, for the first time. A new folder has been opened.",
                           "First {game} stream for {name}. Genre on file: {genre}. Cross-referenced, naturally."],
        "live_part": ["{name} returns to {game}. {tag}, for the records.",
                      "{game} with {name}: {tag}. Previously on... I keep the recap tapes.",
                      "{tag} of {game} with {name}. The continuity is, as always, impeccable."],
        "live_change": ["{name} has moved on to {game}. Records updated.", "Now {game}, per {name}. Filed.",
                        "Plot twist: {name} switched to {game}. Updating the wiki page I keep for myself."],
        "live_end": ["{name} streamed for {length}. Filed and closed.", "Stream closed: {name}, {length}. In order.",
                     "{name} wrapped after {length}. Good episode. Rewinding the tape to watch it again."],
        "live_end_long": ["{name} kept going for {length}. Thoroughly documented.",
                          "{length}. {name} has earned a rest. Filed.",
                          "{length} from {name}. That's a marathon. Longer than my old dial-up downloads."],
        "live_end_signoff": ["{signoff} {name}, {length}. Filed with care.",
                             "{name} signed off: \"{signoff}\" {length}, filed.",
                             "\"{signoff}\" — {name}, after {length}. Clipped for the archive."],
        "open_busy": ["Good day. Everything is filed. {streams} streams, {hours} hours. {top_name} covered {top_count} of them, noted with admiration.",
                      "A full report: {streams} streams across {hours} hours. {top_name} led with {top_count}. A legendary pull.",
                      "{streams} streams, {hours} hours. The filing cabinet is full, in a good way. So is my heart.",
                      "{streams} streams, {hours} hours of our Anime Americans at work. Best job in the building."],
        "open_normal": ["Good day. {streams} streams, {hours} hours, all in order.",
                        "The report is ready: {streams} streams. {longest_name} went longest, at {longest_len}.",
                        "{streams} streams filed this period. Details below. I've highlighted my favourites. All of them.",
                        "Welcome back. {streams} streams this time. I watched every one, for work. Mostly for work."],
        "open_quiet": ["A quiet period: {streams_text}. Nothing to worry about. Status: restful.",
                       "{streams_text} on file. Quiet, but in order. A fine time to catch up on VODs.",
                       "{streams_text}. Quiet week. I reorganised my acrylic stands by debut date."],
        "open_empty": ["No streams on file this time. The cider is still warm.",
                       "Nothing filed this period. Everyone is resting. Noted.",
                       "No streams this time. I am rewatching old VODs like reruns on a Saturday morning."],
        "note_longest": ["thoroughly documented", "a long file", "commendable stamina", "a two-tape recording"],
        "note_most": ["noted with admiration", "a full folder", "remarkably consistent", "a rare holo card"],
        "note_quiet": ["none filed", "a day of rest", "no entries", "reruns day"],
        "note_new_game": ["new folder opened", "first entry", "filed under new", "a new binder"],
        "desk_highlight": ["{longest_name}'s {longest_len} stream was, by my count, the highlight of the period.",
                           "{top_name} streamed {top_count} times. I have noted it twice. Underlined it once.",
                           "{new_game_name} opened a new file: {new_game}. Promising. Lore implications pending.",
                           "Highlight: {longest_name}, {longest_len}. Already on my personal highlights reel."],
        "desk_nudge": ["{quiet_name} has been quiet. A friendly hello would not go amiss.",
                       "For next time: a little more {quiet_name}, if possible.", "For next time: more of the same, please.",
                       "For next time: clip your favourite moments. The archive thanks you."],
        "desk_signoff": ["Cider's on. — Clark", "Filed and closed. — Clark", "Until next time. — Clark",
                         "Be kind, rewind. — Clark", "Away message: filing VODs, back soon. — Clark"],
        "day_one": ["{when}: {first_name} at {first_time}. Noted.", "One stream on file {when_lower}: {first_name}, {first_time}.",
                    "{when}: {first_name} at {first_time}. Setting the VCR now."],
        "day_many": ["{when}: {count} streams on file. {first_name} opens at {first_time}.",
                     "{count} streams scheduled {when_lower}. All in order.",
                     "{when}'s schedule: {count} streams. I've put the cider on.",
                     "{count} Anime Americans on the schedule {when_lower}. {first_name} leads off at {first_time}."],
    },
}


# every blank a template may use (the settings page refuses others, so a line never shows "{oops}")
BLANKS = ("name", "game", "tag", "length", "signoff", "genre", "streams", "streams_text", "hours", "top_name",
          "top_count", "longest_name", "longest_len", "quiet_day", "quiet_name", "new_game", "new_game_name",
          "when", "when_lower", "count", "first_name", "first_time")
# what each slot is for, and its useful blanks (the settings page's help text)
SLOT_HELP = {
    "live_start": "go-live, no game known: {name}",
    "live_game": "go-live with a game: {name} {game}",
    "live_new_game": "go-live, first time with this game: {name} {game}",
    "live_new_genre": "the same, when the genre is known: {name} {game} {genre}",
    "live_part": "go-live, a game they've played before: {name} {game} {tag}",
    "live_change": "they switched game mid-stream: {name} {game}",
    "live_end": "stream ended: {name} {length}",
    "live_end_long": "stream ended after 4 h or more: {name} {length}",
    "live_end_signoff": "stream ended, with their sign-off line: {name} {length} {signoff}",
    "open_busy": "review opener, busy (8+ streams or 20+ h): {streams} {hours} {top_name} {top_count}",
    "open_normal": "review opener: {streams} {hours} {longest_name} {longest_len}",
    "open_quiet": "review opener, 1-2 streams: {streams_text}",
    "open_empty": "review opener, no streams",
    "note_longest": "short comment on the longest stream note",
    "note_most": "short comment on the most shows note",
    "note_quiet": "short comment on a quiet day note",
    "note_new_game": "short comment on the new game note",
    "desk_highlight": "desk card highlight: {longest_name} {longest_len} {top_name} {top_count} {new_game} {new_game_name}",
    "desk_nudge": "desk card 'next time': {quiet_name}",
    "desk_signoff": "desk card sign-off",
    "day_one": "day post with one stream: {when} {when_lower} {first_name} {first_time}",
    "day_many": "day post with more: {when} {when_lower} {count} {first_name} {first_time}",
}
# the settings page's edits (kv host_templates {host: {slot: [lines]}}); a slot there replaces TEMPLATES'
_overrides: Dict[str, Dict[str, List[str]]] = {}


def load_overrides(store: Store) -> None:
    """Read the edited lines (flavrpromo/__main__.py at start, flavrpromo/settings_page.py after a save)."""
    global _overrides
    raw = store.get("host_templates") or {}
    _overrides = {k: {s: [str(x) for x in v] for s, v in (raw.get(k) or {}).items() if isinstance(v, list)}
                  for k in HOSTS}


def templates(key: str, slot: str) -> List[str]:
    """A slot's template lines: the settings page's edit when there is one, else the built-in ones."""
    own = (_overrides.get(key) or {}).get(slot)
    return own if own else TEMPLATES.get(key, {}).get(slot, [])


def bad_blanks(line: str) -> List[str]:
    """Blanks in ``line`` that aren't in BLANKS ("" for a broken brace), for the settings page."""
    try:
        names = [f for _, f, _, _ in string.Formatter().parse(line) if f is not None]
    except ValueError:
        return ["{"]
    return [n for n in names if n not in BLANKS]


class _Blanks(dict):
    def __missing__(self, key):
        raise KeyError(key)


def fill(template: str, facts: Dict[str, Any]) -> Optional[str]:
    """The template with its blanks filled, or None when a blank has no value."""
    names = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    if any(facts.get(n) in (None, "") for n in names):
        return None
    try:
        return template.format_map(_Blanks({k: v for k, v in facts.items() if v not in (None, "")}))
    except (KeyError, ValueError, IndexError):
        return None


def lines(key: str, slot: str, facts: Dict[str, Any]) -> List[str]:
    """Every usable line for a slot, in template order, no duplicates."""
    out: List[str] = []
    for t in templates(key, slot):
        s = fill(t, facts)
        if s and s not in out:
            out.append(s)
    return out


def one(key: str, slot: str, facts: Dict[str, Any], fallback: str = "", rng: Optional[random.Random] = None) -> str:
    """One line at random (live cards), falling back to ``fallback`` slot, then ""."""
    got = lines(key, slot, facts) or (lines(key, fallback, facts) if fallback else [])
    return (rng or random).choice(got) if got else ""


# ── live cards ─────────────────────────────────────────────────────────
def length_words(sec: float) -> str:
    m = int(max(0, sec)) // 60
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def live_line(key: str, event: str, name: str, game: str = "", tag: str = "", length: float = 0,
              signoff: str = "", rng: Optional[random.Random] = None, genre: str = "") -> str:
    """The host's line for a go-live card. ``event``: "start", "change" or "end"; ``tag`` the game's
    history tag as stored ("new", "part:8", ...; flavrpromo/games.py); ``genre`` its first genre in
    lower case when IGDB knew it (flavrpromo/gameinfo.py; a new game's line can say it)."""
    from .games import label
    facts = {"name": name, "game": game, "tag": label(tag), "length": length_words(length), "signoff": signoff,
             "genre": genre}
    if event == "start":
        slot = "live_new_game" if tag == "new" else "live_part" if tag.startswith("part:") else \
            "live_game" if game else "live_start"
        if slot == "live_new_game" and genre:
            slot = "live_new_genre"                 # "a survival game!": only with a genre
        return one(key, slot, facts, "live_new_game" if slot == "live_new_genre" else "live_start", rng)
    if event == "change":
        return one(key, "live_change", facts, "", rng)
    slot = "live_end_signoff" if signoff else "live_end_long" if length >= LONG_STREAM else "live_end"
    return one(key, slot, facts, "live_end", rng)


def day_line(key: str, when: str, count: int, first_name: str = "", first_time: str = "",
             rng: Optional[random.Random] = None) -> str:
    """The host's line on a day post (flavrpromo/focus.py): ``when`` its label ("Today", "This weekend"),
    ``count`` streams on it, the first one's name and time ("8 PM")."""
    facts = {"when": when, "when_lower": when.lower(), "count": count, "first_name": first_name,
             "first_time": first_time}
    return one(key, "day_one" if count == 1 else "day_many", facts, "day_many", rng)


def speaker(key: str) -> str:
    """The prefix of a host's line on a card: "☕ **Colette Cappuccino:**"."""
    h = HOSTS[key]
    return f"{h['emoji']} **{h['name']}:**"


# ── reviews ────────────────────────────────────────────────────────────
def facts(store: Store, week: Any) -> Dict[str, Any]:
    """The numbers a review's lines and cards use, from a review ``Week`` (flavrpromo/calendar.py)."""
    done = [t for t in week.tiles() if t.kind == "past"]
    counts = Counter(t.name for t in done)
    out: Dict[str, Any] = {"streams": len(done), "hours": int(round(week.hours_live)), "range": week.range_text,
                           "streams_text": f"{len(done)} stream{'' if len(done) == 1 else 's'}"}
    if counts:
        out["top_name"], out["top_count"] = counts.most_common(1)[0]
    if done:
        longest = max(done, key=lambda t: t.length)
        out["longest_name"], out["longest_len"] = longest.name, length_words(longest.length)
    today = datetime.fromtimestamp(week.now, week.tz).date()
    past_days = [i for i in range(len(week.days)) if week.date_of(i) < today]
    empty = [i for i in past_days if not any(t.kind == "past" for t in week.days[i])]
    if empty and done:
        out["quiet_day"] = week.date_of(empty[0]).strftime("%A")
    if week.quiet:
        out["quiet_name"] = week.quiet[0]
    # a game someone streamed for the first time in these days (flavrpromo/games.py tags)
    a, b = week.start.timestamp(), week.end.timestamp()
    for t in done:
        sid = _session_id(store, t)
        for seg in store.segments(sid) if sid else []:
            if seg["tag"] == "new" and a <= float(seg["started_at"]) < b:
                out.setdefault("new_game", seg["game"])
                out.setdefault("new_game_name", t.name)
    if out.get("new_game"):                         # what it is, for KoboldCpp's lines (flavrpromo/gameinfo.py)
        info = gameinfo.cached(store, out["new_game"])
        about = "; ".join(x for x in (", ".join(info.get("genres") or []), info.get("summary") or "") if x)
        if about:
            out["new_game_about"] = about
    return out


def _session_id(store: Store, tile: Any) -> Optional[int]:
    row = next((s for s in store.sessions_between(tile.at - 1, tile.at + 1) if s["person_id"] == tile.person_id), None)
    return row["id"] if row else None


def mood(f: Dict[str, Any]) -> str:
    """"busy" / "normal" / "quiet" / "empty" from a review's facts."""
    if not f.get("streams"):
        return "empty"
    if f["streams"] >= BUSY_STREAMS or f.get("hours", 0) >= BUSY_HOURS:
        return "busy"
    if f["streams"] <= QUIET_STREAMS:
        return "quiet"
    return "normal"


def pose(f: Dict[str, Any]) -> str:
    """Which opener pose fits: happy when busy or normal, pointing for a new game, sleepy when quiet."""
    m = mood(f)
    if m in ("quiet", "empty"):
        return "sleepy"
    return "pointing" if f.get("new_game") else "happy"


def notes(f: Dict[str, Any]) -> List[Dict[str, str]]:
    """Up to 3 sticky notes / table rows for the opener: {label, value, slot (its comment lines)}."""
    out = []
    if f.get("longest_name"):
        out.append({"label": "LONGEST STREAM", "value": f"{f['longest_name']} · {f['longest_len']}", "slot": "note_longest"})
    if f.get("top_name") and int(f.get("top_count") or 0) > 1:
        out.append({"label": "MOST SHOWS", "value": f"{f['top_name']} · {f['top_count']}", "slot": "note_most"})
    if f.get("new_game"):
        out.append({"label": "NEW GAME", "value": f"{f['new_game_name']} · {f['new_game']}", "slot": "note_new_game"})
    if f.get("quiet_day") and len(out) < 3:
        out.append({"label": "QUIET DAY", "value": f["quiet_day"], "slot": "note_quiet"})
    return out[:3]


def review_candidates(key: str, f: Dict[str, Any]) -> Dict[str, List[str]]:
    """Every slot of a review and its candidate lines (the picker page shows them)."""
    out = {"opener": lines(key, f"open_{mood(f)}", f) or lines(key, "open_normal", f)}
    for i, n in enumerate(notes(f)):
        out[f"note{i}"] = lines(key, n["slot"], f)
    out["desk_highlight"] = lines(key, "desk_highlight", f)
    out["desk_nudge"] = lines(key, "desk_nudge", f)
    out["desk_signoff"] = lines(key, "desk_signoff", f)
    return out
