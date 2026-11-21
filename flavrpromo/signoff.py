"""
Sign-off lines: the line a streamer ends their stream with ("otsu-nuggies", "otsu-cara"), shown on
their "was live" card when the stream ends (owner 2026-11-20: several per person, each with an
optional emoji; no raid detection). Later the two hosts (plan doc "FlaVR Bot presenter plan") will
use them too, so they live per person in the database (store table ``signoffs``), not in a setting.

Which line: ``pick`` chooses one at random for each finished stream, never the same one twice in a
row when the person has more than one. The choice is remembered per stream (kv
``signoff_last.<person id>`` = {"session": id, "line": id}), so a card that gets ended again (a
quick restart, then the real end) keeps the same line.

Commands (``register_friend`` from flavrpromo/bot.py, ``register_me`` from flavrpromo/talent.py):
  /friend signoff add name line [emoji] | remove name number | list name     owner or Manage Server
  /me signoff add line [emoji] | remove number | list                         the linked person's own

Nothing in a line can ping anyone: every message has allowed_mentions none, and markdown is escaped
so a line shows exactly as typed.
"""

from __future__ import annotations

import random
from typing import Any, Awaitable, Callable, Dict, List, Optional

import discord
from discord import app_commands

from .store import Store

MAX_LINES = 20          # sign-off lines one person can have
MAX_LEN = 100           # characters in one line
MAX_EMOJI = 64          # characters in the emoji box (a custom emoji like <:nugget:1234...> is long)


def clean(line: str) -> str:
    """One tidy line: no line breaks, single spaces, at most MAX_LEN characters."""
    return " ".join((line or "").split())[:MAX_LEN]


def text(row: Dict[str, Any]) -> str:
    """A line as the card shows it: emoji first, markdown escaped ("🍗 otsu-nuggies")."""
    line = discord.utils.escape_markdown(row.get("line") or "")
    emoji = (row.get("emoji") or "").strip()
    return f"{emoji} {line}".strip()


def pick(store: Store, person_id: int, session_id: Optional[int] = None,
         rng: Optional[random.Random] = None) -> Optional[Dict[str, Any]]:
    """The sign-off line for this person's finished stream (None when they have none). The same
    stream always gets the same line; a new stream never repeats the previous one (when there are
    two or more). Called by flavrpromo/bot.py post_end."""
    rows = store.signoffs(person_id)
    if not rows:
        return None
    last = store.get(f"signoff_last.{person_id}") or {}
    if session_id is not None and last.get("session") == session_id:
        same = next((r for r in rows if r["id"] == last.get("line")), None)
        if same:
            return same
    choices = [r for r in rows if r["id"] != last.get("line")] or rows
    row = (rng or random).choice(choices)
    store.put(f"signoff_last.{person_id}", {"session": session_id, "line": row["id"]})
    return row


def listing(rows: List[Dict[str, Any]], who: str, own: bool = False) -> str:
    """The numbered list (the numbers /signoff remove takes). ``own``: worded for /me ("You have")."""
    if not rows:
        return "You have no sign-off lines yet." if own else f"{who} has no sign-off lines yet."
    head = "Your sign-off lines:" if own else f"{who}'s sign-off lines:"
    return head + "\n" + "\n".join(f"{i}. {text(r)}" for i, r in enumerate(rows, 1))


def add(store: Store, person: Dict[str, Any], line: str, emoji: str = "", own: bool = False) -> str:
    """Add a line; the answer to show (shared by /friend signoff add and /me signoff add)."""
    line = clean(line)
    if not line:
        return "That line is empty."
    if len(store.signoffs(person["id"])) >= MAX_LINES:
        return f"{person['name']} already has {MAX_LINES} lines. Remove one first."
    if not store.signoff_add(person["id"], line, " ".join((emoji or "").split())[:MAX_EMOJI]):
        return f"{person['name']} already has that line."
    return f"Added. {listing(store.signoffs(person['id']), person['name'], own)}"


def remove(store: Store, person: Dict[str, Any], number: int, own: bool = False) -> str:
    row = store.signoff_remove(person["id"], number)
    if row is None:
        return f"No line {number}. {listing(store.signoffs(person['id']), person['name'], own)}"
    return f"Removed “{text(row)}”."


async def _say(inter: discord.Interaction, msg: str) -> None:
    await inter.response.send_message(msg[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def register_friend(friend: app_commands.Group, bot: Any,
                    managers_only: Callable[[discord.Interaction], Awaitable[bool]], person_auto: Any = None) -> None:
    """Adds /friend signoff (anyone's lines; owner or Manage Server). Called by flavrpromo/bot.py
    before it adds the /friend group to the command tree; ``person_auto`` suggests names."""
    store: Store = bot.store

    async def find(inter: discord.Interaction, name: str) -> Optional[Dict[str, Any]]:
        if not await managers_only(inter):
            return None
        p = store.person(name)
        if not p:
            await _say(inter, f"No one called {name}. Add them with /friend add first.")
        return p

    group = app_commands.Group(name="signoff", description="Lines people end their stream with, for the was-live card",
                               parent=friend)

    @group.command(name="add", description="Add a sign-off line (several each; one is picked per stream)")
    @app_commands.describe(line="Like otsu-nuggies", emoji="Optional, shown before the line")
    async def friend_add(inter: discord.Interaction, name: str, line: str, emoji: Optional[str] = None):
        p = await find(inter, name)
        if p:
            await _say(inter, add(store, p, line, emoji or ""))

    @group.command(name="remove", description="Remove one of someone's sign-off lines (number from list)")
    async def friend_remove(inter: discord.Interaction, name: str, number: app_commands.Range[int, 1, MAX_LINES]):
        p = await find(inter, name)
        if p:
            await _say(inter, remove(store, p, number))

    @group.command(name="list", description="Someone's sign-off lines, numbered")
    async def friend_list(inter: discord.Interaction, name: str):
        p = await find(inter, name)
        if p:
            await _say(inter, listing(store.signoffs(p["id"]), p["name"]))

    if person_auto is not None:
        for cmd in (friend_add, friend_remove, friend_list):
            cmd.autocomplete("name")(person_auto)


def register_me(me: app_commands.Group, store: Store,
                mine: Callable[[discord.Interaction], Awaitable[Optional[Dict[str, Any]]]]) -> None:
    """Adds /me signoff (the linked person's own lines). Called by flavrpromo/talent.py with its
    ``me`` group and ``mine`` (the person linked to whoever typed the command, or None)."""
    own = app_commands.Group(name="signoff", description="Your sign-off lines, for your was-live card", parent=me)

    @own.command(name="add", description="Add a sign-off line (one is picked for each stream)")
    @app_commands.describe(line="Like otsu-nuggies", emoji="Optional, shown before the line")
    async def me_add(inter: discord.Interaction, line: str, emoji: Optional[str] = None):
        p = await mine(inter)
        if p:
            await _say(inter, add(store, p, line, emoji or "", own=True))

    @own.command(name="remove", description="Remove one of your sign-off lines (number from list)")
    async def me_remove(inter: discord.Interaction, number: app_commands.Range[int, 1, MAX_LINES]):
        p = await mine(inter)
        if p:
            await _say(inter, remove(store, p, number, own=True))

    @own.command(name="list", description="Your sign-off lines, numbered")
    async def me_list(inter: discord.Interaction):
        p = await mine(inter)
        if p:
            await _say(inter, listing(store.signoffs(p["id"]), p["name"], own=True))
