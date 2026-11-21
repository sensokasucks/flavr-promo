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
example exchanges, then one request per slot ("Facts: ... Write 3 opener lines."). The card asks
for a JSON list of strings; anything else in the answer is ignored. Lines are checked (no @, no
links, no blanks left, at most MAX_CHARS) before they reach the page.

Who calls it: flavrpromo/host_picker.py (``write`` when a review starts waiting and on the page's
"Write more" button, ``status`` for the page), flavrpromo/__main__.py makes one.
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
MAX_CHARS = 300             # longest line kept (the picker's own-line box allows the same)
PER_SLOT = 3                # lines asked for in each slot
TIMEOUT = 120               # seconds for one generate call (a CPU-only PC can be slow)

# what each picker slot asks the model for (flavrpromo/hosts.py review_candidates)
ASKS = {
    "opener": "Write {n} opener lines for the {heading}.",
    "note": "Write {n} very short comments (2 to 5 words) on this highlight: {note}.",
    "desk_highlight": "Write {n} closing lines about the highlight of the {heading}.",
    "desk_nudge": "Write {n} short 'for next time' nudges for the group.",
    "desk_signoff": "Write {n} short sign-off lines (you are leaving your desk).",
}


def card(key: str) -> Dict[str, Any]:
    """The host's character card data ({} when missing)."""
    try:
        return json.loads((CARDS / key / "card.json").read_text(encoding="utf-8")).get("data") or {}
    except (OSError, ValueError):
        return {}


def facts_text(f: Dict[str, Any]) -> str:
    """A review's facts (flavrpromo/hosts.py ``facts``) as the plain sentence the card's examples use."""
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


def parse(text: str) -> List[str]:
    """The model's answer (continuing after "[") as clean lines; bad ones are dropped."""
    body = "[" + text.split("]", 1)[0] + "]"
    try:
        items = json.loads(body)
    except ValueError:
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
    out: List[str] = []
    for x in items if isinstance(items, list) else []:
        s = " ".join(str(x).split())
        if not s or len(s) > MAX_CHARS or "@" in s or "http" in s.lower() or "{" in s or s in out:
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

    async def generate(self, text: str, max_length: int = 220) -> Optional[str]:
        try:
            async with self.http.post(f"{self.url}/api/v1/generate", headers=self._headers(),
                                      timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                                      json={"prompt": text, "max_length": max_length, "max_context_length": 4096,
                                            "temperature": self.temperature, "top_p": 0.9, "rep_pen": 1.1,
                                            "stop_sequence": ["\n", "<START>", "Producer:"]}) as r:
                if r.status != 200:
                    log.info("KoboldCpp answered HTTP %s", r.status)
                    return None
                data = await r.json(content_type=None)
                return str(((data.get("results") or [{}])[0]).get("text") or "")
        except Exception as e:
            log.info("KoboldCpp unreachable: %s", e)
            return None

    async def write(self, key: str, facts: Dict[str, Any], heading: str,
                    notes: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """New lines for every slot of a review: {slot: [lines]} (empty slots left out; {} when offline)."""
        text = facts_text(facts)
        asks = [("opener", ASKS["opener"])]
        asks += [(f"note{i}", ASKS["note"].replace("{note}", f"{n['label'].lower()}: {n['value']}"))
                 for i, n in enumerate(notes)]
        asks += [(s, ASKS[s]) for s in ("desk_highlight", "desk_nudge", "desk_signoff")]
        out: Dict[str, List[str]] = {}
        for slot, ask in asks:
            got = await self.generate(prompt(key, ask.format(n=self.per_slot, heading=heading.lower()), text))
            if got is None:
                break                       # offline or failing: stop asking for this review
            lines = parse(got)
            if lines:
                out[slot] = lines[:self.per_slot]
        return out
