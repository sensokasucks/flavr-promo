"""
Talent channels: one Discord channel per person (Sen 2026-11-18, "each talent has their own channel").

What a talent channel gets, once /talent channel picks it:
  go-live cards   flavrpromo/bot.py post_start posts the card in the group's live channel AND here.
                  Either can be switched off per person (/talent options or /me posts): people
                  columns live_group / live_own, both on by default.
  her week        one text card with only her streams (no picture; Sen chose the text card),
                  posted Sunday at CALENDAR_PREVIEW_HOUR, pinned, and edited in place whenever her
                  week changes. Made by ``week_card`` from the group's calendar week (flavrpromo/calendar.py)
                  filtered to her.
  her reviews     with the group's (Friday: Mon-Thu, Monday: Fri-Sun; /setup review-times): her
                  streams, hours, longest stream, VOD links, and her videos / Shorts / premieres.
  commands        /live, /schedule, /calendar view and /calendar share used IN her channel show only
                  her (``person_for_channel``); everywhere else they work as before.

Linking a Discord account (/talent link) lets that person run /me: their own weekly times, main
platform, X handle, calendar hide (vacation), where their go-live cards go, and their own share
text. /me only ever touches the linked person; groups and server settings stay with the owner and
Manage Server (who can do all of it with /talent and /friend).

Saved: people.talent_channel / discord_user / live_group / live_own (flavrpromo/store.py), and in kv
  talent_post.<person id>   {week, channel, message, sig}: the current week card
  talent_recap.<person id>  "<label>:<first day>" of the newest review posted ("week:2026-11-16")

Who calls it: CalendarPoster.tick (flavrpromo/calendar_post.py) calls ``refresh_all`` every minute and
after a poke; flavrpromo/bot.py calls ``register`` for the commands and ``person_for_channel`` /
``live_channels`` for the posts. Every Discord message uses allowed_mentions none (the bot's sends).
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

import discord
from discord import app_commands

from .calendar import Week
from .store import PLATFORMS, Store

log = logging.getLogger("flavrpromo.talent")


# ── who and where ──────────────────────────────────────────────────────
def person_for_channel(store: Store, channel_id: Any) -> Optional[Dict[str, Any]]:
    """The person whose talent channel this is (None for any other channel). Commands use it to
    show only that person when used in their channel."""
    cid = str(channel_id or "")
    if not cid:
        return None
    return next((p for p in store.people() if p.get("talent_channel") == cid), None)


def person_for_user(store: Store, user_id: Any) -> Optional[Dict[str, Any]]:
    """The person linked to this Discord account (/talent link), for /me."""
    uid = str(user_id or "")
    return next((p for p in store.people() if uid and p.get("discord_user") == uid), None)


def live_channels(store: Store, person: Dict[str, Any]) -> List[str]:
    """Where a go-live card goes, first one first (its id is the session's main post): the group's
    live channel unless live_group is off, then the person's own channel unless live_own is off.
    The same channel twice counts once. Called by flavrpromo/bot.py post_start."""
    out: List[str] = []
    group_ch = str(store.get(f"live_channel.{person.get('grp') or 'flavr'}") or "")
    if group_ch and int(person.get("live_group", 1)):
        out.append(group_ch)
    own = str(person.get("talent_channel") or "")
    if own and int(person.get("live_own", 1)) and own not in out:
        out.append(own)
    return out


def only(week: Week, person_id: int) -> Week:
    """The same week with only one person's streams (her week card, /calendar in her channel)."""
    days = [[t for t in d if t.person_id == person_id] for d in week.days]
    uploads = [u for u in week.uploads if u.get("person_id") == person_id]     # a review's videos: hers only
    return dataclasses.replace(week, days=days, quiet=[], uploads=uploads)


# ── her week (text card) ───────────────────────────────────────────────
def week_card(week: Week, name: str) -> Dict[str, Any]:
    """The text card for one person's week, as embed data (flavrpromo/bot.py make_embed): one field
    per day she streams, the same lines as the group post (calendar_post.line, times shown in each
    reader's own time zone). Recap: streams, hours and her longest stream in the footer."""
    from .calendar_post import embed     # late import: calendar_post imports this module
    data = embed(week)
    if week.recap:
        span = "weekend" if week.label == "weekend" else "week"          # calendar.py REVIEWS label
        data["title"] = f"📼 {name} · {span} in review · {week.range_text}"
        past = [t for t in week.tiles() if t.kind == "past"]
        if past:
            top = max(past, key=lambda t: t.length)
            h = week.hours_live
            hours = f"{h:.0f}h" if h >= 10 else f"{h:.1f}".rstrip("0").rstrip(".") + "h"
            data["footer"] = (f"{len(past)} stream{'s' if len(past) != 1 else ''} · {hours} live · "
                              f"longest: {(top.title or top.game or 'stream')[:60]}")
        else:
            data["footer"] = "No streams this week."
    else:
        data["title"] = f"🗓️ {name} · this week · {week.range_text}"
        data["footer"] = "Times are in your own time zone · ✅ done (links go to the VOD) · 🗓️ planned"
    if data.get("empty"):
        data["empty"] = False
        data["fields"] = [("​", "Nothing on the calendar yet." if not week.recap else "No streams this week.")]
    return data


async def refresh_all(poster: Any) -> None:
    """Bring every talent channel's week card (and Friday / Monday reviews) up to date. Called by
    CalendarPoster.tick under its lock; same rhythm as the group posts (flavrpromo/calendar_post.py):
    a new card each Sunday from CALENDAR_PREVIEW_HOUR, edits in place when her week changes, the
    reviews once each, at the group reviews' times."""
    for p in poster.store.people():
        if p.get("talent_channel"):
            try:
                await refresh_one(poster, p)
            except Exception:
                log.exception("talent card for %s failed", p.get("name"))


async def refresh_one(poster: Any, person: Dict[str, Any]) -> None:
    store, d = poster.store, poster.discord
    pid, channel = person["id"], str(person["talent_channel"])
    now = poster.clock()
    local = datetime.fromtimestamp(now, poster.tz)
    wday = (local.weekday() + 1) % 7                    # 0 = Sunday
    this_week = poster.week_of(0, now)
    key = this_week.date().isoformat()
    group = person.get("grp") or "flavr"

    # her own reviews, with the group's (calendar_post.py): Friday Mon-Thu, Monday Fri-Sun
    from .calendar import review_range
    from .calendar_post import REVIEW_WEEKDAY
    for label, at in poster.review_times().items():
        if at is None or local.weekday() != REVIEW_WEEKDAY[label] or local.hour * 60 + local.minute < at:
            continue
        rkey = f"{label}:{review_range(label, now, poster.tz)[0].date().isoformat()}"
        if store.get(f"talent_recap.{pid}") == rkey:
            continue
        week = only(poster.build_review(group, label), pid)
        if await d.cal_send(channel, week_card(week, person["name"]), None, ""):
            store.put(f"talent_recap.{pid}", rkey)

    post = store.get(f"talent_post.{pid}") or {}
    if post.get("channel") and post["channel"] != channel:
        post = {}                                       # her channel changed: start over there
    week = only(poster.build(group, this_week), pid)
    sig = week.signature()
    new_week_due = post.get("week") != key and (wday > 0 or local.hour >= poster.preview_hour)
    if not post.get("message") or new_week_due:
        msg = await d.cal_send(channel, week_card(week, person["name"]), None, "")
        if msg:
            if post.get("message"):
                await _unpin(d, post["channel"], post["message"])
            await _pin(d, channel, msg)
            store.put(f"talent_post.{pid}", {"week": key, "channel": channel, "message": str(msg), "sig": sig})
        return
    if post.get("sig") != sig:
        if await d.cal_edit(channel, post["message"], week_card(week, person["name"]), None, ""):
            store.put(f"talent_post.{pid}", {**post, "sig": sig})
        else:
            store.put(f"talent_post.{pid}", {})          # deleted: the next tick posts a new one


async def _pin(d: Any, channel: str, message: str) -> None:
    pin = getattr(d, "cal_pin", None)
    if pin:
        await pin(channel, message, True)


async def _unpin(d: Any, channel: str, message: str) -> None:
    pin = getattr(d, "cal_pin", None)
    if pin:
        await pin(channel, message, False)


# ── commands ───────────────────────────────────────────────────────────
def register(tree: app_commands.CommandTree, bot: Any,
             managers_only: Callable[[discord.Interaction], Awaitable[bool]],
             day_choices: List[app_commands.Choice[int]], parse_time: Callable[[str], Optional[int]]) -> None:
    """Adds /talent (owner or Manage Server) and /me (the linked person, for their own entry)."""
    store: Store = bot.store
    plat_choices = [app_commands.Choice(name=p.title(), value=p) for p in PLATFORMS]

    def poke() -> None:
        if bot.calendar:
            bot.calendar.poke()

    async def say(inter: discord.Interaction, text: str) -> None:
        await inter.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def find(inter: discord.Interaction, name: str) -> Optional[Dict[str, Any]]:
        p = store.person(name)
        if not p:
            await say(inter, f"No one called {name}. Add them with /friend add first.")
        return p

    talent = app_commands.Group(name="talent", description="Talent channels: one channel per person (owner or Manage Server)")

    @talent.command(name="channel", description="Give someone their own channel (go-live cards, their week, recap)")
    @app_commands.describe(channel="Leave empty to stop using a channel for them")
    async def talent_channel(inter: discord.Interaction, name: str, channel: Optional[discord.TextChannel] = None):
        if not await managers_only(inter):
            return
        p = await find(inter, name)
        if not p:
            return
        store.set_talent(p["id"], talent_channel=str(channel.id) if channel else "")
        store.put(f"talent_post.{p['id']}", {})
        poke()
        await say(inter, f"{channel.mention} is {p['name']}'s channel now: go-live cards, a pinned card with their "
                         "week, and their Friday and Monday reviews. Commands used there show only them." if channel else
                  f"{p['name']} has no channel of their own now.")

    @talent.command(name="link", description="Link someone's Discord account, so they can use /me")
    @app_commands.describe(user="Leave empty to unlink")
    async def talent_link(inter: discord.Interaction, name: str, user: Optional[discord.User] = None):
        if not await managers_only(inter):
            return
        p = await find(inter, name)
        if not p:
            return
        other = person_for_user(store, user.id) if user else None
        if other and other["id"] != p["id"]:
            await say(inter, f"That account is linked to {other['name']}. Unlink it there first.")
            return
        store.set_talent(p["id"], discord_user=str(user.id) if user else "")
        await say(inter, f"{user.mention} can now use /me to manage {p['name']}'s own entry." if user else
                  f"{p['name']} has no linked account now.")

    @talent.command(name="options", description="Where someone's go-live cards go")
    @app_commands.describe(group_channel="Also post in their group's live channel", own_channel="Also post in their own channel")
    async def talent_options(inter: discord.Interaction, name: str, group_channel: Optional[bool] = None,
                             own_channel: Optional[bool] = None):
        if not await managers_only(inter):
            return
        p = await find(inter, name)
        if p:
            await posts(inter, p, group_channel, own_channel)

    @talent.command(name="list", description="Everyone with their own channel or a linked account")
    async def talent_list(inter: discord.Interaction):
        rows = []
        for p in store.people():
            if not (p.get("talent_channel") or p.get("discord_user")):
                continue
            where = [w for w, on in (("group", p.get("live_group", 1)), ("own", p.get("live_own", 1))) if int(on)]
            rows.append(f"**{p['name']}** · " + (f"<#{p['talent_channel']}>" if p.get("talent_channel") else "no channel")
                        + (f" · <@{p['discord_user']}>" if p.get("discord_user") else "")
                        + f" · go-live in: {', '.join(where) or 'nowhere'}")
        await say(inter, "\n".join(rows)[:1900] or "Nobody has a talent channel yet. /talent channel gives one.")

    tree.add_command(talent)

    async def posts(inter: discord.Interaction, p: Dict[str, Any], group_on: Optional[bool], own_on: Optional[bool]) -> None:
        """/talent options and /me posts: switch the two go-live places."""
        change = {}
        if group_on is not None:
            change["live_group"] = int(group_on)
        if own_on is not None:
            change["live_own"] = int(own_on)
        store.set_talent(p["id"], **change)
        p = store.person(p["name"]) or p
        g = "on" if int(p.get("live_group", 1)) else "off"
        o = "on" if int(p.get("live_own", 1)) else "off"
        await say(inter, f"{p['name']}'s go-live cards: group channel {g}, own channel {o}"
                  + ("" if p.get("talent_channel") else " (no own channel set yet: /talent channel)") + ".")

    # /me: the linked person, for their own entry only
    me = app_commands.Group(name="me", description="Your own entry (needs your account linked with /talent link)")

    async def mine(inter: discord.Interaction) -> Optional[Dict[str, Any]]:
        p = person_for_user(store, inter.user.id)
        if not p:
            await say(inter, "Your account isn't linked to anyone yet. Ask a mod to run /talent link.")
        return p

    @me.command(name="schedule", description="Add a regular weekly stream time (for the calendar)")
    @app_commands.choices(day=day_choices)
    @app_commands.describe(time="Like 7 PM or 19:30, in the bot's time zone", title="Optional, e.g. the game")
    async def me_schedule(inter: discord.Interaction, day: app_commands.Choice[int], time: str,
                          title: Optional[str] = None):
        p = await mine(inter)
        if not p:
            return
        minute = parse_time(time)
        if minute is None:
            await say(inter, "Couldn't read that time. Try 7 PM or 19:30.")
            return
        store.add_manual(p["id"], day.value, minute, (title or "").strip()[:100])
        poke()
        await say(inter, f"You're on the calendar every {day.name} at {time.strip()} ({bot.settings.timezone}).")

    @me.command(name="unschedule", description="Remove all your hand-set weekly times")
    async def me_unschedule(inter: discord.Interaction):
        p = await mine(inter)
        if p:
            n = store.clear_manual(p["id"])
            poke()
            await say(inter, f"Removed {n} weekly time(s).")

    @me.command(name="main", description="Which platform your posts link to first")
    @app_commands.choices(platform=plat_choices)
    async def me_main(inter: discord.Interaction, platform: app_commands.Choice[str]):
        p = await mine(inter)
        if p:
            store.set_main(p["id"], platform.value)
            poke()
            await say(inter, f"Your posts link to {platform.name} first.")

    @me.command(name="x", description="Your X / Twitter handle for the copy-ready X text (- removes it)")
    async def me_x(inter: discord.Interaction, handle: str):
        import re
        p = await mine(inter)
        if not p:
            return
        h = "" if handle.strip() in ("-", "none", "") else handle.strip().lstrip("@")
        if h and not re.fullmatch(r"\w{1,15}", h):
            await say(inter, "That isn't an X handle (letters, numbers and _ only, 15 at most).")
            return
        store.set_x(p["id"], h)
        await say(inter, f"You're @{h} in the X text." if h else "You're written by name in the X text.")

    @me.command(name="hide", description="Take yourself off the calendar for now (vacation); hidden: False undoes it")
    async def me_hide(inter: discord.Interaction, hidden: bool = True):
        p = await mine(inter)
        if p:
            store.set_hidden(p["id"], hidden)
            poke()
            await say(inter, "You're off the calendar until you run /me hide hidden: False." if hidden
                      else "You're back on the calendar.")

    @me.command(name="posts", description="Where your go-live cards go")
    @app_commands.describe(group_channel="Also post in your group's live channel", own_channel="Also post in your own channel")
    async def me_posts(inter: discord.Interaction, group_channel: Optional[bool] = None, own_channel: Optional[bool] = None):
        p = await mine(inter)
        if p:
            await posts(inter, p, group_channel, own_channel)

    @me.command(name="share", description="DMs you copy-ready text of your week for X and other Discords")
    @app_commands.choices(week=[app_commands.Choice(name="This week", value=0), app_commands.Choice(name="Next week", value=1),
                                app_commands.Choice(name="Last week (recap)", value=-1)])
    async def me_share(inter: discord.Interaction, week: Optional[app_commands.Choice[int]] = None):
        p = await mine(inter)
        if not p:
            return
        if not bot.calendar:
            await say(inter, "The calendar isn't running.")
            return
        await inter.response.defer(ephemeral=True, thinking=True)
        ok = await bot.calendar.share_person(p, week.value if week else 0, inter.user.id)
        await inter.followup.send("Sent to your DMs." if ok else "Couldn't DM you. Discord → this server → Privacy "
                                  "Settings → allow direct messages.", ephemeral=True)

    tree.add_command(me)


__all__ = ["person_for_channel", "person_for_user", "live_channels", "only", "week_card", "refresh_all", "register"]
