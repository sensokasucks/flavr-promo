"""
KoboldCpp: extra host lines written by a local AI model, next to the template lines on the review
picker page (owner 2026-11-20, plan doc "FlaVR Bot presenter plan": KoboldCpp runs on its own PC and
isn't always on, so lines always wait for the owner's pick and the templates are always there).

Settings: KOBOLD_URL (e.g. http://192.168.1.50:5001; empty = off) and KOBOLD_KEY (only when
KoboldCpp was started with --password). KoboldCpp's own documented API:
  GET  /api/v1/model      the loaded model's name: the "online" check on the picker page
  POST /api/v1/generate   {"prompt", "max_length", ...} → {"results": [{"text": ...}]}

The prompt is the host's character card (Character Card V2, flavrpromo/host_art/<host>/card.json:
the same cards work in SillyTavern): system prompt, description, personality, scenario and the
example exchanges, then one request per LINE ("Facts: ... Write one opener ..."), made per_slot
times for a slot's alternatives (Sen 2026-11-21: asking for 5 at once got one paragraph split into
5 "lines"). The card asks for a JSON list of strings; whatever comes back is joined into ONE line
(``as_line``), so a paragraph-long answer stays whole. Lines are checked (no @, no links, no
blanks left, at most MAX_CHARS) before they reach the page.

The owner can edit both on the settings page (flavrpromo/card_page.py, /settings/cards): a card's
text fields are saved in kv "host_cards" ({host: {field: text}}) and the slot asks in kv
"kobold_asks" ({slot: text}); ``load_card_overrides`` puts them in force, and ``card`` / ``asks``
return the edited text over the built-in one. An emptied field goes back to the built-in text.

Variety (owner 2026-11-22: "they pretty much say the same replies from kobold each time"): every
request for a slot used to be word for word the same, so only the temperature made a difference.
Now each request differs in four ways, each with a switch on the settings page (kv "kobold"):
  angles     a different take per request ("make it a small joke", "use a 90s reference"): ANGLES
             for both hosts plus HOST_ANGLES for each, editable on the cards page (kv kobold_angles);
  memory     the last lines a host wrote for that kind of slot (kv host_said) are listed as "already
             used, don't repeat", and a line that still comes out nearly the same is asked for again;
  examples   the card's example exchanges are shuffled and only EXAMPLES_MAX of them are sent;
  chattiness short / normal / chatty fills {length} in the asks (LENGTHS).
Banter (kv hosts_banter, flavrpromo/hosts.py ``banter``): ``Kobold.replies`` has the OTHER host answer
the opener (slot "reply" on the picker page and in the article editor), and ``Kobold.chat`` writes a
tall picture's chat chunk as a real back-and-forth, one request per turn with the speaker's own card.

Who calls it: flavrpromo/host_picker.py (``write`` when a review starts waiting and on the page's
"Write more" button, ``status`` for the page), flavrpromo/article_editor.py (new host lines for an
article section), flavrpromo/__main__.py makes one.
"""

from __future__ import annotations

import difflib
import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from . import hosts

log = logging.getLogger("flavrpromo.kobold")

CARDS = Path(__file__).resolve().parent / "host_art"
MAX_CHARS = 500             # longest line kept: a few sentences (the own-line boxes allow the same)
PER_SLOT = 3                # lines asked for in each slot
TIMEOUT = 300               # seconds for one generate call (a big model or a CPU-only PC can be slow)
# where an answer stops: a new example / the producer speaking, or a chat model's end-of-turn marks.
# Not a single newline (Sen 2026-11-21: Gemma writes the JSON list one line per item, and a "\n" stop
# cut every answer down to nothing, so the editor said KoboldCpp "couldn't be reached").
STOPS = ["<START>", "Producer:", "\n\n\n", "<end_of_turn>", "<|im_end|>", "<|eot_id|>", "</s>"]

# what each picker slot asks the model for (flavrpromo/hosts.py review_candidates)
# One request = ONE line (owner 2026-11-21: a model asked for "5 lines" wrote one paragraph and split
# it into 5 items, "Then we have Cara on deck." / "And finally, Lulu ..."; so each request asks for a
# single complete line, a few sentences are fine, and per_slot requests make the alternatives). {n}
# still works in an edited ask (it is 1).
ASKS = {
    "opener": "Write one opener for the {heading}: a complete line of {length}.",
    "note": "Write one very short comment ({length}) on this highlight: {note}.",
    "desk_highlight": "Write one closing line about the highlight of the {heading} ({length}).",
    "desk_nudge": "Write one 'for next time' nudge for the group ({length}).",
    "desk_signoff": "Write one sign-off line, you are leaving your desk ({length}).",
    # the article editor's day pictures (flavrpromo/article_editor.py ``ask_slot``; the facts are that day's)
    "day": "Write one line for this day's picture about who streams and when ({length}).",
    # the tall pictures' stream and game chunks (flavrpromo/recipes.py ``write_line``; the facts are that stream's / game's)
    # (owner's first try 2026-11-22: the model just read the facts back, "X spent over four hours on YouTube
    # playing ..."; the name, day, length and title are printed next to the remark, so it is told to react instead)
    "stream": "Write one reaction to this stream in your own voice ({length}): a joke, a cheer or "
              "what made it fun. Do not repeat the streamer's name, the day, the length, the platform or the title; "
              "they are already printed next to your line.",
    "game": "Write one reaction to this game being played this week, in your own voice ({length}). "
            "Do not list who played it or how many streams; that is already printed next to your line.",
    # the same two chunks with "The remark is about: the game" (owner 2026-11-22: "a good way to get the host to
    # talk a little about the game"); the facts then carry the game's longer details (gameinfo.talk)
    "stream_game": "Talk a little about the game in this stream, in your own voice ({length}): what kind of game "
                   "it is and what makes it fun to watch, using only what the facts say about the game. If the facts "
                   "do not say what the game is, go by its name and the stream title and do not make up details. "
                   "Do not repeat the streamer's name, the day, the length or the platform; they are already printed "
                   "next to your line.",
    "game_talk": "Talk a little about this game in your own voice ({length}): what kind of game it is and why it is "
                 "fun to watch someone play it, using only what the facts say about it. Do not list who played it or "
                 "how many streams; that is already printed next to your line.",
    # a tall picture's host moment and sign-off strip (owner 2026-11-22: "the sign off card has no way to generate
    # lines with kobold. ideally, it could read the other chunks to make a summary"); the facts are what the
    # picture's other chunks show (flavrpromo/recipes.py ``stack_facts``)
    "tall_host": "Write one line that presents this picture in your own voice ({length}): say what it shows and "
                 "what you make of it. The facts list what is in the picture; do not read them all out.",
    "tall_signoff": "Write one sign-off line that closes this picture ({length}): sum up what it showed in a few "
                    "words of your own, then say goodbye your way. The facts list what is in the picture; do not "
                    "read them all out.",
    # banter (owner 2026-11-22: hosts answering each other). {name} = the host being answered, {line} = what
    # they said. "reply": the other host's answer on the opener card (``Kobold.replies``); "chat" opens a tall
    # picture's chat chunk and "chat_reply" is every turn after it (``Kobold.chat``).
    "reply": "{name} just opened the {heading} with: \"{line}\" Write your one reply to {name} ({length}): react to "
             "what they said or how they said it, in your own voice. Do not repeat their line.",
    "chat": "You are chatting with {name} about the {heading}. Start the chat with one remark to {name} ({length}).",
    "chat_reply": "You are chatting with {name} about the {heading}. {name} just said: \"{line}\" Write your one "
                  "answer to {name} ({length}): react to them, then add something of your own. Do not repeat their line.",
}

# How long a line may be, by kind of slot (the ASKS keys) and the settings page's Chattiness: what {length}
# in an ask becomes. An ask the owner edited without {length} stays exactly as typed.
CHATTY = ("short", "normal", "chatty")
_LONG = ("one sentence", "one to three sentences", "two to four sentences, at most 70 words")
_MID = ("one short sentence", "one or two sentences", "two to four sentences, at most 60 words")
_BRIEF = ("a few words", "one short sentence", "one or two sentences")
_CHAT = ("a few words", "one short sentence, at most 16 words", "one or two short sentences, at most 28 words")
LENGTHS = {"opener": _LONG, "desk_highlight": _LONG, "day": _LONG, "stream": _MID, "game": _MID,
           "stream_game": _LONG, "game_talk": _LONG,      # talking about a game needs a little more room
           "tall_host": _MID, "tall_signoff": _MID,       # a tall picture's host moment / sign-off bubble
           "note": ("1 to 3 words", "2 to 5 words", "4 to 8 words"),
           "desk_nudge": _BRIEF, "desk_signoff": _BRIEF,
           "reply": ("a few words", "one short sentence, at most 20 words", "one or two sentences, at most 30 words"),
           # a chat chunk's bubbles are small (flavrpromo/tall.py "chat"): its lines stay short
           "chat": _CHAT, "chat_reply": _CHAT}
MAX_TOKENS = {"short": 160, "normal": 200, "chatty": 300}     # generate's max_length for one line

# Angles: one is added to each request so the lines differ by more than luck. ANGLES fit either host and
# any longer line; HOST_ANGLES are each host's own habits (also used alone for the short slots, SHORT_KINDS).
# The cards page edits both (kv kobold_angles {"all": [...], "<host>": [...]}, one per row).
ANGLES = [
    "Make it a small joke.",
    "Open with a question to the viewers.",
    "Pick ONE of the facts and talk only about that one.",
    "Sound honestly impressed.",
    "Announce it like breaking news.",
    "Compare it to something from everyday life.",
    "Talk straight to one of the people in the facts, by name.",
    "Understate it on purpose.",
    "Start in the middle of a thought, as if you were interrupted.",
    "Tease the other host a little.",
    "Say what you are looking forward to next.",
    "Start with a sound or a one-word reaction.",
]
HOST_ANGLES = {
    "colette": ["Work in your coffee, or how little you slept.", "Use CAPS on exactly one word.",
                "Mention the office printer you talk to.", "Bring up croissants or your 'French' side.",
                "Cheer for one streamer like their biggest fan.", "Tease Clark for being so calm."],
    "clark": ["Work in ONE 90s reference (a VCR, dial-up, an AIM away message, holo cards, Saturday-morning reruns).",
              "Talk about it as paperwork: filed, noted, cross-referenced.",
              "Call the streamers 'Anime Americans', affectionately.",
              "Mention your warm drink or a good bun.",
              "Let your inner fan slip out for a moment, then be professional again.",
              "Mention Colette's chaos, patiently."],
}
NO_ANGLE = ("note",)                                            # a comment of a few words has no room for one
SHORT_KINDS = ("desk_nudge", "desk_signoff", "reply")           # short lines: the host's own habits only

EXAMPLES_MAX = 3            # example exchanges sent per request when shuffling (a card can hold more)
SAID_KEY = "host_said"      # kv {host: {kind: [line, ...]}}: what KoboldCpp wrote before, newest last
SAID_KEEP = 30              # lines kept per host and kind
MEMORY = 12                 # of those, how many a request lists as "already used" (settings page; 0 = off)
AVOID_CHARS = 140           # an "already used" line is cut to this many characters in the prompt
CLOSE = 0.82                # difflib ratio from which two lines count as the same line again


# the card fields the settings page edits, in the order the prompt uses them, with a short help line
# (flavrpromo/card_page.py shows them; the rest of card.json, like tags, stays as built in)
CARD_FIELDS = {
    "system_prompt": "First line of every prompt: who they are and the rules. {{char}} = their name.",
    "description": "Who they are: look, job, background.",
    "personality": "How they talk.",
    "scenario": "Where they are and what they're doing when they speak.",
    "mes_example": "Example exchanges, each starting with <START>; {{user}} is the producer asking.",
    "post_history_instructions": "Added after the facts in every request (the JSON list rule lives here).",
}
_card_edits: Dict[str, Dict[str, str]] = {}     # kv host_cards, loaded by load_card_overrides
_ask_edits: Dict[str, str] = {}                 # kv kobold_asks
_angle_edits: Dict[str, List[str]] = {}         # kv kobold_angles ("all" + one list per host)


def builtin_card(key: str) -> Dict[str, Any]:
    """The card as built in (flavrpromo/host_art/<key>/card.json), {} when missing."""
    try:
        return json.loads((CARDS / key / "card.json").read_text(encoding="utf-8")).get("data") or {}
    except (OSError, ValueError):
        return {}


def card(key: str) -> Dict[str, Any]:
    """The host's character card data with the settings page's edits on top ({} when missing)."""
    c = dict(builtin_card(key))
    c.update({f: v for f, v in (_card_edits.get(key) or {}).items() if f in CARD_FIELDS and v.strip()})
    return c


def asks() -> Dict[str, str]:
    """What each slot asks for (ASKS) with the settings page's edits on top."""
    return {s: (_ask_edits.get(s) or "").strip() or a for s, a in ASKS.items()}


def angles(key: str, kind: str = "") -> List[str]:
    """The angles a request of ``kind`` for host ``key`` can get ([] = none for that kind): the shared
    ones plus the host's own, or only the host's own for a short line. The cards page's edits win."""
    if kind in NO_ANGLE:
        return []
    own = _angle_edits.get(key) or HOST_ANGLES.get(key, [])
    return list(own) if kind in SHORT_KINDS else list(_angle_edits.get("all") or ANGLES) + list(own)


def load_card_overrides(store: Any) -> None:
    """Put the settings page's card, ask and angle edits in force (flavrpromo/settings_page.py ``apply``
    at start, flavrpromo/card_page.py after a save)."""
    _card_edits.clear()
    _card_edits.update({k: dict(v) for k, v in (store.get("host_cards") or {}).items() if isinstance(v, dict)})
    _ask_edits.clear()
    _ask_edits.update({k: str(v) for k, v in (store.get("kobold_asks") or {}).items() if k in ASKS})
    _angle_edits.clear()
    _angle_edits.update({k: [str(x) for x in v if str(x).strip()]
                         for k, v in (store.get("kobold_angles") or {}).items() if isinstance(v, list) and v})


def said(store: Any, key: str, kind: str, n: int = SAID_KEEP) -> List[str]:
    """The last ``n`` lines KoboldCpp wrote for host ``key`` in slots of ``kind``, oldest first."""
    if store is None or not kind or n <= 0:
        return []
    return [str(x) for x in ((store.get(SAID_KEY) or {}).get(key) or {}).get(kind) or []][-n:]


def remember(store: Any, key: str, kind: str, line: str) -> None:
    """Add a line KoboldCpp just wrote to the host's memory (kv host_said), so later requests can be
    told not to repeat it. Kept per kind of slot: openers don't push sign-offs out."""
    if store is None or not kind or not line:
        return
    all_said = dict(store.get(SAID_KEY) or {})
    mine = dict(all_said.get(key) or {})
    mine[kind] = ([x for x in mine.get(kind) or [] if x != line] + [line])[-SAID_KEEP:]
    all_said[key] = mine
    store.put(SAID_KEY, all_said)


def _plain(line: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", line.lower()))


def too_close(line: str, others: Any) -> bool:
    """True when ``line`` is (nearly) one of ``others`` again: the same words give or take a few."""
    mine = _plain(line)
    return bool(mine) and any(difflib.SequenceMatcher(None, mine, _plain(o)).ratio() >= CLOSE for o in others if o)


def examples(text: str, rng: Optional[random.Random] = None) -> str:
    """A card's example exchanges (blocks that start with <START>) in a random order, at most
    EXAMPLES_MAX of them, so the model doesn't lean on the same example every time. ``rng`` None =
    as written (shuffling off)."""
    if rng is None:
        return text
    blocks = [b.strip() for b in str(text or "").split("<START>") if b.strip()]
    if len(blocks) < 2:
        return text
    return "\n".join("<START>\n" + b for b in rng.sample(blocks, min(len(blocks), EXAMPLES_MAX)))


def games_text(rows: List[Dict[str, Any]], planned: bool = False) -> str:
    """hosts.facts / preview_facts "games" as one clause: "games played: Valheim (Lulu, Sen; 3 streams;
    part 4), Schedule I (Sen; new game)". Tags read as words (flavrpromo/games.py)."""
    words = {"new": "new game", "staple": "a channel staple", "back": "back after a while"}
    out = []
    for r in rows or []:
        tags = [words.get(t, t.replace("part:", "part ")) for t in r.get("tags") or []]
        bits = [", ".join(r.get("people") or [])]
        if int(r.get("streams") or 0) > 1:
            bits.append(f"{r['streams']} streams")
        bits += tags
        out.append(f"{r['game']} ({'; '.join(b for b in bits if b)})")
    return ("games planned: " if planned else "games played: ") + ", ".join(out) if out else ""


def facts_text(f: Dict[str, Any]) -> str:
    """A review's facts (flavrpromo/hosts.py ``facts``) as the plain sentence the card's examples use.
    The Sunday preview's facts (hosts.preview_facts, ``preview`` True) read as the week ahead."""
    if f.get("preview"):
        parts = [f"the week ahead has {f.get('planned_text') or '0 streams'} planned by {f.get('people', 0)} people"]
        if f.get("first_name"):
            parts.append(f"first up {f['first_name']} on {f['first_day']} at {f['first_time']}")
        if f.get("busy_day"):
            parts.append(f"busiest day {f['busy_day']} with {f['busy_count']} streams")
        if f.get("most_name"):
            parts.append(f"{f['most_name']} has {f['most_count']} streams planned")
        if f.get("games"):
            parts.append(games_text(f["games"], planned=True))
        return ", ".join(parts) + "."
    parts = [f"{f.get('streams', 0)} streams", f"{f.get('hours', 0)} hours"]
    if f.get("top_name") and int(f.get("top_count") or 0) > 1:
        parts.append(f"{f['top_name']} did {f['top_count']} shows")
    if f.get("longest_name"):
        parts.append(f"longest stream {f['longest_name']}, {f['longest_len']}")
    if f.get("new_game"):
        parts.append(f"{f['new_game_name']} played {f['new_game']} for the first time"
                     + (f" ({f['new_game_about']})" if f.get("new_game_about") else ""))
    if f.get("quiet_day"):
        parts.append(f"{f['quiet_day']} had no streams")
    if f.get("quiet_name"):
        parts.append(f"{f['quiet_name']} didn't stream")
    if f.get("games"):
        parts.append(games_text(f["games"]))
    return ", ".join(parts) + "."


def prompt(key: str, ask: str, facts: str, angle: str = "", avoid: Any = (),
           rng: Optional[random.Random] = None) -> str:
    """The whole prompt for one request (KoboldCpp's plain text completion). ``angle``: this request's
    take (``angles``); ``avoid``: lines already used, listed as "do not repeat"; ``rng``: shuffles the
    card's examples (``examples``; None = as written)."""
    c = card(key)
    name = c.get("name") or key.title()
    sub = lambda s: str(s or "").replace("{{char}}", name).replace("{{user}}", "Producer")  # noqa: E731
    head = "\n".join(x for x in (sub(c.get("system_prompt")), f"{name}: {sub(c.get('description'))}",
                                 f"Personality: {sub(c.get('personality'))}", f"Scenario: {sub(c.get('scenario'))}")
                     if x.strip())
    extra = f" For this one: {angle}" if angle else ""
    used = [" ".join(str(x).split())[:AVOID_CHARS] for x in avoid if x]
    if used:
        extra += (" You already used these lines; do not reuse their wording, their first words or their joke: "
                  + " | ".join(f'"{x}"' for x in used) + ".")
    return (f"{head}\n{sub(examples(c.get('mes_example'), rng))}\n<START>\nProducer: Facts: {facts} {ask}{extra} "
            f"{sub(c.get('post_history_instructions'))}\n{name}: [")


def length_of(kind: str, chatty: str = "normal") -> str:
    """What {length} in an ask becomes for a slot of ``kind`` at the settings page's Chattiness."""
    return LENGTHS.get(kind, _LONG)[CHATTY.index(chatty) if chatty in CHATTY else 1]


def fill_ask(ask: str, n: int, heading: str, length: str = "", name: str = "", line: str = "") -> str:
    """One slot's ask with its blanks filled in: {n}, {heading}, {length} (``length_of``; the normal
    opener length when not given) and, for banter, {name} and {line} (who is answered and what they
    said). An edited ask with a stray brace is used as typed instead of failing (format would raise)."""
    length = length or length_of("opener")
    try:
        return ask.format(n=n, heading=heading.lower(), length=length, name=name, line=line, note="{note}")
    except (KeyError, IndexError, ValueError):
        for blank, value in (("{n}", str(n)), ("{heading}", heading.lower()), ("{length}", length),
                             ("{name}", name), ("{line}", line)):
            ask = ask.replace(blank, value)
        return ask


def tidy(line: str) -> str:
    """A line without the marks some models leave in it (owner 2026-11-22: remarks came out as
    "]BREAKING NEWS: ...", ". . . The way you handled ..." and, when the model put its whole list inside
    one pair of quotes, 'SPECTACULAR!!\\", \\"Aces High III looks stunning ...\\"'):
      * the seams of a list written inside one line (quote, comma, quote, with or without backslashes)
        become a space, a backslash in front of a quote goes, and a quote left without its partner at
        either end is dropped;
      * brackets, loose commas and leading dots are dropped from the start;
      * a line of nothing but punctuation is "" (not a line)."""
    line = " ".join(str(line or "").split())
    line = re.sub(r'\\*"\s*,\s*\\*"', " ", line)        # ...!!\", \"Aces... = two items of a list in one line
    line = re.sub(r'\\+(?=["\']|\s|$)', "", line)          # \" → ", and a backslash left at the end of an item
    line = re.sub(r"^[\[\]\s,;:.…]+", "", line)
    if line.count('"') % 2:                              # one quote too many: the end of the model's own list
        line = line[:-1].rstrip() if line.endswith('"') else line[1:].lstrip() if line.startswith('"') else line
    return line if re.sub(r"[\s!-/:-@\[-`{-~…]", "", line) else ""      # only punctuation left = nothing said


def as_line(text: str) -> str:
    """One answer as ONE line: the items of its list joined ("Monday is busy!" + "Traube starts at
    midnight." = one line), cut to MAX_CHARS at a word; "" when nothing usable."""
    items = parse(text, MAX_CHARS * 4)
    line = " ".join(items)
    if not line:                        # plain prose with no quotes: keep the words themselves
        plain = re.sub(r"(?s)<think>.*?</think>|```(?:json)?", "", text or "")
        line = tidy(tidy(plain.strip().strip("[]").strip()).strip('"'))
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return line


def parse(text: str, longest: int = MAX_CHARS) -> List[str]:
    """The model's answer (continuing after "[") as clean lines (``tidy``); bad ones are dropped. Copes with a
    list written one item per line, a ```json fence or a second "[", thinking (<think>...</think>)
    before it, and a numbered / bulleted list of quoted lines instead of JSON."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = text.lstrip("[").strip()
    try:                                # the list as written; a "]" inside a line must not end it early
        items, _ = json.JSONDecoder().raw_decode("[" + text)
    except ValueError:
        body = "[" + text.split("]", 1)[0] + "]"
        try:
            items = json.loads(body)
        except ValueError:
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
    out: List[str] = []
    for x in items if isinstance(items, list) else []:
        s = tidy(str(x))                # no stray "]" or ". . ." in front; an item of only dots is dropped
        if not s or len(s) > longest or "@" in s or "http" in s.lower() or "{" in s or s in out:
            continue
        out.append(s)
    return out


class Kobold:
    """One KoboldCpp server (KOBOLD_URL). Every call fails soft: offline = no AI lines, never an error."""

    def __init__(self, http: aiohttp.ClientSession, url: str, key: str = "", temperature: float = 0.8,
                 per_slot: int = PER_SLOT, store: Any = None, angles: bool = True, shuffle: bool = True,
                 memory: int = MEMORY, chatty: str = "normal"):
        self.http = http
        self.url = url.rstrip("/")
        self.key = key
        self.temperature = temperature      # 0.1 (plain) .. 1.5 (wild); the settings page sets it
        self.per_slot = per_slot            # lines asked for in each slot (1-6)
        self.last_raw = ""                  # the newest answer as it came (settings page test, picker state)
        # variety (see the module docstring; flavrpromo/settings_page.py ``apply`` passes the settings)
        self.store = store                  # the bot's kv store for the hosts' memory (None = no memory)
        self.angles = angles                # a different take per request
        self.shuffle = shuffle              # shuffle the card's examples
        self.memory = max(0, int(memory))   # "already used" lines listed per request (0 = off)
        self.chatty = chatty if chatty in CHATTY else "normal"
        self.rng = random.Random()          # tests seed it

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    async def status(self) -> str:
        """The loaded model's name, or "" when KoboldCpp can't be reached."""
        try:
            async with self.http.get(f"{self.url}/api/v1/model", headers=self._headers(),
                                     timeout=aiohttp.ClientTimeout(total=4)) as r:
                if r.status != 200:
                    return ""
                return str((await r.json(content_type=None)).get("result") or "model loaded")
        except Exception:
            return ""

    async def generate(self, text: str, max_length: int = 0) -> Optional[str]:
        """KoboldCpp's answer to ``text`` (None = unreachable / an error). ``max_length`` in tokens
        (0 = enough for one line at the Chattiness setting: MAX_TOKENS)."""
        max_length = max_length or MAX_TOKENS[self.chatty]
        try:
            async with self.http.post(f"{self.url}/api/v1/generate", headers=self._headers(),
                                      timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                                      json={"prompt": text, "max_length": max_length, "max_context_length": 4096,
                                            "temperature": self.temperature, "top_p": 0.9, "rep_pen": 1.1,
                                            "stop_sequence": STOPS}) as r:
                if r.status != 200:
                    log.info("KoboldCpp answered HTTP %s", r.status)
                    return None
                data = await r.json(content_type=None)
                self.last_raw = str(((data.get("results") or [{}])[0]).get("text") or "")
                if not parse(self.last_raw):
                    log.info("KoboldCpp gave no usable lines: %r", self.last_raw[:300])
                return self.last_raw
        except Exception as e:
            log.info("KoboldCpp unreachable: %s", e)
            return None

    def _angles(self, key: str, kind: str, n: int) -> List[str]:
        """``n`` angles for ``n`` requests, all different while the list lasts ("" = no angle)."""
        pool = angles(key, kind) if self.angles else []
        if not pool:
            return [""] * n
        picked = self.rng.sample(pool, min(n, len(pool)))
        return picked + [self.rng.choice(pool) for _ in range(n - len(picked))]

    async def line(self, key: str, ask: str, heading: str, facts: Any, kind: str = "", avoid: Any = (),
                   angle: Optional[str] = None, retry: bool = True, name: str = "", said_line: str = "") -> Optional[str]:
        """ONE new line for a slot (one request; "" = it answered with nothing usable, None =
        unreachable). ``facts``: a facts dict (hosts.facts) or the facts sentence itself.
        ``kind``: the kind of slot (an ASKS key: sets {length}, the angles and which memory is used;
        "" = an opener's length, no memory). ``avoid``: more lines not to repeat (the batch so far).
        ``angle``: this request's take (None = pick one). ``retry``: a line that comes out nearly the
        same as a remembered one is asked for once more with another angle. ``name`` / ``said_line``:
        the banter blanks (who is answered, what they said)."""
        text = facts if isinstance(facts, str) else facts_text(facts)
        full = fill_ask(ask, 1, heading, length_of(kind or "opener", self.chatty), name, said_line)
        used = list(avoid) + [x for x in said(self.store, key, kind, self.memory) if x not in avoid]
        if angle is None:
            angle = self._angles(key, kind, 1)[0]
        rng = self.rng if self.shuffle else None
        got = await self.generate(prompt(key, full, text, angle, used, rng))
        if got is None:
            return None
        new = as_line(got)
        if new and retry and too_close(new, used):
            other = next((a for a in self._angles(key, kind, 3) if a != angle), angle)
            again = await self.generate(prompt(key, full, text, other, used + [new], rng))
            if again is not None and as_line(again):
                new = as_line(again)
        remember(self.store, key, kind, new)
        return new

    async def lines(self, key: str, ask: str, heading: str, facts: Any, n: int = 0, kind: str = "",
                    name: str = "", said_line: str = "") -> Optional[List[str]]:
        """``n`` (default per_slot) different lines for a slot, one request each, each with its own
        angle and told what the earlier ones said; one that still repeats is dropped. None = unreachable."""
        n = n or self.per_slot
        out: List[str] = []
        for angle in self._angles(key, kind, n):
            got = await self.line(key, ask, heading, facts, kind, list(out), angle, False, name, said_line)
            if got is None:
                return out or None
            if got and not too_close(got, out):
                out.append(got)
        return out

    async def write(self, key: str, facts: Dict[str, Any], heading: str,
                    notes: List[Dict[str, str]], only: tuple = (), reply_to: str = "") -> Dict[str, List[str]]:
        """New lines for every slot of a review: {slot: [lines]} (empty slots left out; {} when offline).
        ``only``: slot name starts to ask for (("opener", "note") = the opener card's slots; the
        article editor's host sections), () = all. With banter on (flavrpromo/hosts.py ``banter``) the
        other host's answers to the opener come too (slot "reply"): to the first new opener, else to
        ``reply_to`` (the opener picked on the page)."""
        a = asks()
        todo = [("opener", a["opener"])]
        todo += [(f"note{i}", a["note"].replace("{note}", f"{n['label'].lower()}: {n['value']}"))
                 for i, n in enumerate(notes)]
        if hosts.banter() and hosts.other(key) != key:
            todo.append(("reply", a["reply"]))
        todo += [(s, a[s]) for s in ("desk_highlight", "desk_nudge", "desk_signoff")]
        if only:
            todo = [(s, x) for s, x in todo if any(s.startswith(o) for o in only)]
        out: Dict[str, List[str]] = {}
        for slot, ask in todo:
            if slot == "reply":
                base = (out.get("opener") or [reply_to])[0]
                got = await self.replies(hosts.other(key), key, base, heading, facts) if base else []
            else:
                got = await self.lines(key, ask, heading, facts, kind="note" if slot.startswith("note") else slot)
            if got is None:
                break                       # offline or failing: stop asking for this review
            if got:
                out[slot] = got
        return out

    async def replies(self, key: str, to: str, said_line: str, heading: str, facts: Any, n: int = 0) -> Optional[List[str]]:
        """Banter: host ``key``'s short answers to what host ``to`` just said (``said_line``), ``n``
        (default per_slot) to pick from, written with ``key``'s own card. None = unreachable."""
        return await self.lines(key, asks()["reply"], heading, facts, n, "reply",
                                hosts.HOSTS.get(to, {}).get("name", to.title()), said_line)

    async def chat(self, first: str, second: str, heading: str, facts: Any, turns: int = 4) -> Optional[List[str]]:
        """Banter for a tall picture's chat chunk: ``turns`` lines, ``first`` and ``second`` taking turns
        (one request per turn, each with the speaker's own card and the line it answers). The lines so
        far when KoboldCpp stops answering midway; None when it never answered."""
        name = lambda k: hosts.HOSTS.get(k, {}).get("name", k.title())  # noqa: E731
        out: List[str] = []
        for i in range(turns):
            me, them = (first, second) if i % 2 == 0 else (second, first)
            kind = "chat_reply" if out else "chat"
            got = await self.line(me, asks()[kind], heading, facts, kind, list(out), None, True,
                                  name(them), out[-1] if out else "")
            if got is None:
                return out or None
            if not got:
                break
            out.append(got)
        return out
