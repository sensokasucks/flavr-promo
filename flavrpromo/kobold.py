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

Who calls it: flavrpromo/host_picker.py (``write`` when a review starts waiting and on the page's
"Write more" button, ``status`` for the page), flavrpromo/article_editor.py (new host lines for an
article section), flavrpromo/__main__.py makes one.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

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
    "opener": "Write one opener for the {heading}: a complete line of one to three sentences.",
    "note": "Write one very short comment (2 to 5 words) on this highlight: {note}.",
    "desk_highlight": "Write one closing line about the highlight of the {heading} (one to three sentences).",
    "desk_nudge": "Write one short 'for next time' nudge for the group.",
    "desk_signoff": "Write one short sign-off line (you are leaving your desk).",
    # the article editor's day pictures (flavrpromo/article_editor.py ``ask_slot``; the facts are that day's)
    "day": "Write one line for this day's picture about who streams and when (one to three sentences).",
}


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


def load_card_overrides(store: Any) -> None:
    """Put the settings page's card and ask edits in force (flavrpromo/settings_page.py ``apply`` at
    start, flavrpromo/card_page.py after a save)."""
    _card_edits.clear()
    _card_edits.update({k: dict(v) for k, v in (store.get("host_cards") or {}).items() if isinstance(v, dict)})
    _ask_edits.clear()
    _ask_edits.update({k: str(v) for k, v in (store.get("kobold_asks") or {}).items() if k in ASKS})


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


def prompt(key: str, ask: str, facts: str) -> str:
    """The whole prompt for one request (KoboldCpp's plain text completion)."""
    c = card(key)
    name = c.get("name") or key.title()
    sub = lambda s: str(s or "").replace("{{char}}", name).replace("{{user}}", "Producer")  # noqa: E731
    head = "\n".join(x for x in (sub(c.get("system_prompt")), f"{name}: {sub(c.get('description'))}",
                                 f"Personality: {sub(c.get('personality'))}", f"Scenario: {sub(c.get('scenario'))}")
                     if x.strip())
    return (f"{head}\n{sub(c.get('mes_example'))}\n<START>\nProducer: Facts: {facts} {ask} "
            f"{sub(c.get('post_history_instructions'))}\n{name}: [")


def fill_ask(ask: str, n: int, heading: str) -> str:
    """One slot's ask with {n} and {heading} filled in. An edited ask with a stray brace is used as
    typed instead of failing (format would raise)."""
    try:
        return ask.format(n=n, heading=heading.lower())
    except (KeyError, IndexError, ValueError):
        return ask.replace("{n}", str(n)).replace("{heading}", heading.lower())


def as_line(text: str) -> str:
    """One answer as ONE line: the items of its list joined ("Monday is busy!" + "Traube starts at
    midnight." = one line), cut to MAX_CHARS at a word; "" when nothing usable."""
    items = parse(text, MAX_CHARS * 4)
    line = " ".join(items)
    if not line:                        # plain prose with no quotes: keep the words themselves
        plain = re.sub(r"(?s)<think>.*?</think>|```(?:json)?", "", text or "")
        line = " ".join(plain.strip().strip("[]").strip().strip('"').split())
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return line


def parse(text: str, longest: int = MAX_CHARS) -> List[str]:
    """The model's answer (continuing after "[") as clean lines; bad ones are dropped. Copes with a
    list written one item per line, a ```json fence or a second "[", thinking (<think>...</think>)
    before it, and a numbered / bulleted list of quoted lines instead of JSON."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = text.lstrip("[").strip()
    body = "[" + text.split("]", 1)[0] + "]"
    try:
        items = json.loads(body)
    except ValueError:
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
    out: List[str] = []
    for x in items if isinstance(items, list) else []:
        s = " ".join(str(x).split())
        if not s or len(s) > longest or "@" in s or "http" in s.lower() or "{" in s or s in out:
            continue
        out.append(s)
    return out


class Kobold:
    """One KoboldCpp server (KOBOLD_URL). Every call fails soft: offline = no AI lines, never an error."""

    def __init__(self, http: aiohttp.ClientSession, url: str, key: str = "", temperature: float = 0.8,
                 per_slot: int = PER_SLOT):
        self.http = http
        self.url = url.rstrip("/")
        self.key = key
        self.temperature = temperature      # 0.1 (plain) .. 1.5 (wild); the settings page sets it
        self.per_slot = per_slot            # lines asked for in each slot (1-6)
        self.last_raw = ""                  # the newest answer as it came (settings page test, picker state)

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
        (0 = enough for one line of a few sentences: 200)."""
        max_length = max_length or 200
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

    async def write(self, key: str, facts: Dict[str, Any], heading: str,
                    notes: List[Dict[str, str]], only: tuple = ()) -> Dict[str, List[str]]:
        """New lines for every slot of a review: {slot: [lines]} (empty slots left out; {} when offline).
        ``only``: slot name starts to ask for (("opener", "note") = the opener card's slots; the
        article editor's host sections), () = all."""
        a = asks()
        todo = [("opener", a["opener"])]
        todo += [(f"note{i}", a["note"].replace("{note}", f"{n['label'].lower()}: {n['value']}"))
                 for i, n in enumerate(notes)]
        todo += [(s, a[s]) for s in ("desk_highlight", "desk_nudge", "desk_signoff")]
        if only:
            todo = [(s, x) for s, x in todo if any(s.startswith(o) for o in only)]
        out: Dict[str, List[str]] = {}
        for slot, ask in todo:
            got = await self.lines(key, ask, heading, facts)
            if got is None:
                break                       # offline or failing: stop asking for this review
            if got:
                out[slot] = got
        return out

    async def line(self, key: str, ask: str, heading: str, facts: Any) -> Optional[str]:
        """ONE new line for a slot (one request; "" = it answered with nothing usable, None =
        unreachable). ``facts``: a facts dict (hosts.facts) or the facts sentence itself."""
        text = facts if isinstance(facts, str) else facts_text(facts)
        got = await self.generate(prompt(key, fill_ask(ask, 1, heading), text))
        return None if got is None else as_line(got)

    async def lines(self, key: str, ask: str, heading: str, facts: Any, n: int = 0) -> Optional[List[str]]:
        """``n`` (default per_slot) different lines for a slot, one request each; None = unreachable."""
        out: List[str] = []
        for _ in range(n or self.per_slot):
            got = await self.line(key, ask, heading, facts)
            if got is None:
                return out or None
            if got and got not in out:
                out.append(got)
        return out
