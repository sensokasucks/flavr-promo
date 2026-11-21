"""
Go-live watcher: who of the people you follow (your FlaVR group, your other friends, yourself) is
live right now, on which platforms, and posts about it.

Each platform is checked on its own timer (TWITCH_EVERY_SEC 120, YOUTUBE_EVERY_SEC 600,
KICK_EVERY_SEC 180) through flavrpromo/platforms/. After every check ``reconcile()`` merges the
answers per PERSON, not per channel:

  * live on several platforms at once (multistreaming) = one session with several platforms;
  * offline on every platform for less than RESTART_GRACE (15 min) and back = the same session
    ("1 restart"), so a crashed OBS doesn't post twice;
  * the session ends RESTART_GRACE after the last time any platform said live, and its end time
    is that last sighting (not when the watcher noticed). It only ends once every platform the
    person streams on (and that has keys) has been checked AFTER that last sighting: right after
    the bot starts, Twitch may answer minutes before YouTube, and "not on Twitch" must not end a
    YouTube stream that simply hasn't been looked at yet (a long redeploy did exactly that);
  * a "new" stream whose platform start time is before the person's last stream ended is that
    same stream: the old session is reopened instead of a second one being made
    (``merge_overlaps`` in flavrpromo/store.py also folds such pairs together once at start-up).

The main platform (the link and picture a post shows) is the person's own pick, else the first
live one of YouTube, Twitch, Kick.

Each finished stream gets its VOD looked up (``find_vod``: the Twitch archive, or the YouTube
stream page itself, which becomes the VOD) before ``on_end`` runs, so the post and the weekly
calendar can link it.

Upcoming streams for the calendar: ``refresh_schedules`` asks Twitch's schedule API for every
Twitch account every SCHEDULE_EVERY (6 h), and each YouTube check saves the waiting rooms it
found. Both land in the ``scheduled`` table; ``on_scheduled(person, item)`` is called for each
item the bot hadn't seen before (flavrpromo/calendar_post.py turns those into calendar pings).

Weeks the bot wasn't watching (it only knows what it saw live): ``backfill(start, end)`` asks
each platform for the streams that FINISHED in that time (Twitch past broadcasts, YouTube's uploads
list with real start / end times; Kick's API has no list of past streams) and saves the ones the
watcher didn't already have as normal sessions marked source "vod". flavrpromo/calendar_post.py
calls it (``ensure_backfill``) for last week, at start-up, and before each review. Twitch's list
is free (rate limit only), so it is asked for everyone. YouTube's costs quota, so it is asked
only for ACTIVE people (owner 2026-11-20): someone the free checks saw stream or post a video in
those days (store.last_activity), and only once per new activity: kv "yt_backfill.<start>"
remembers {person id: when checked}. ``everyone=True`` (/calendar refresh by hand) asks everyone.

What happens on a change is the bot's business (flavrpromo/bot.py ``LivePoster``): ``on_start``
posts in the person's group channel and returns where, ``on_change`` edits it when the
platforms or title change, ``on_end`` edits it to "was live" with the length and VOD. Sessions
are kept in the database (flavrpromo/store.py), which later rounds use for the weekly calendar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .store import PLATFORMS, Store

log = logging.getLogger("flavrpromo.watcher")
RESTART_GRACE = 15 * 60.0
BACKFILL_MERGE = 30 * 60.0     # backfill: one person's streams on two platforms this close = one multistream
SCHEDULE_EVERY = 6 * 3600.0     # Twitch schedule look-ups: one call per Twitch account this often

# on_start(person, session, infos) -> (channel id, message id) or ("", "")
OnStart = Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Dict[str, Any]]], Awaitable[Tuple[str, str]]]
OnChange = Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Dict[str, Any]]], Awaitable[None]]
OnEnd = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[None]]
# on_scheduled(person, item): a newly seen upcoming stream {key, at, title, game, url, thumb, platform}
OnScheduled = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[None]]


def youtube_id(url: str) -> str:
    """"https://www.youtube.com/watch?v=abc12345678" → "abc12345678" ("" when it isn't one)."""
    if "watch?v=" not in (url or ""):
        return ""
    return url.split("watch?v=", 1)[1].split("&", 1)[0]


def main_platform(person: Dict[str, Any], live_on: Dict[str, Any]) -> str:
    """The person's chosen main platform if it is live, else YouTube, Twitch, Kick in that order."""
    pick = person.get("main_platform") or ""
    if pick in live_on:
        return pick
    return next((p for p in PLATFORMS if p in live_on), "")


class Watcher:
    def __init__(self, store: Store, checkers: Dict[str, Any], every: Dict[str, int],
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.checkers = {k: c for k, c in checkers.items() if c is not None}
        self.every = every
        self.clock = clock
        # platform → {platform_id: Live}: the newest answer of each platform
        self.seen: Dict[str, Dict[str, Dict[str, Any]]] = {p: {} for p in PLATFORMS}
        self.last_check: Dict[str, float] = {}
        self.errors: Dict[str, str] = {}
        self.on_start: Optional[OnStart] = None
        self.on_change: Optional[OnChange] = None
        self.on_end: Optional[OnEnd] = None
        self.on_scheduled: Optional[OnScheduled] = None
        self._lock = asyncio.Lock()
        # people whose open session saw no platform live at the last merge (a possible restart)
        self._gone: set[int] = set()

    # ── checking ───────────────────────────────────────────────────────
    async def resolve_missing(self, platform: str) -> None:
        """Look up platform ids for accounts added without one (a new /friend add, or a failed look-up)."""
        checker = self.checkers.get(platform)
        todo = [a for a in self.store.accounts(platform) if not a["platform_id"]]
        if not checker or not todo:
            return
        found = await checker.resolve([a["handle"] for a in todo])
        for a in todo:
            info = found.get(a["handle"])
            if info and info.get("platform_id"):
                self.store.set_account_info(a["id"], info["platform_id"], info.get("display", ""), info.get("avatar", ""))

    async def check(self, platform: str) -> None:
        """Ask one platform who is live, then merge (reconcile)."""
        checker = self.checkers.get(platform)
        if not checker or not getattr(checker, "ready", True):
            return
        try:
            await self.resolve_missing(platform)
            accounts = [a for a in self.store.accounts(platform) if a["platform_id"]]
            self.seen[platform] = await checker.live(accounts) if accounts else {}
            self.last_check[platform] = self.clock()
            self.errors.pop(platform, None)
        except Exception as e:      # keep the last answer; a platform hiccup is not "everyone went offline"
            self.errors[platform] = str(e) or type(e).__name__
            log.warning("%s check failed: %s", platform.title(), self.errors[platform])
            return
        if platform == "youtube":
            # the same check found the waiting rooms (scheduled streams); save them for the calendar
            upcoming = getattr(checker, "upcoming", {}) or {}
            self.record_uploads("youtube", accounts, getattr(checker, "new_uploads", {}) or {})
            # the free feed reads: when each person last posted anything (the reviews' activity flag)
            posted = getattr(checker, "posted", {}) or {}
            for a in accounts:
                if posted.get(a["platform_id"]):
                    self.store.note_activity(a["person_id"], posted[a["platform_id"]], now=self.clock())
            for a in accounts:
                items = [dict(i, key=i.get("video_id") or i.get("url")) for i in upcoming.get(a["platform_id"], [])
                         if i.get("at")]
                await self._save_scheduled(a["person_id"], "youtube", items)
        await self.reconcile()

    async def _save_scheduled(self, person_id: int, platform: str, items: List[Dict[str, Any]]) -> None:
        new = self.store.replace_scheduled(person_id, platform, items, now=self.clock())
        if not new or not self.on_scheduled:
            return
        person = next((p for p in self.store.people() if p["id"] == person_id), None)
        for item in new:
            if person and float(item["at"]) > self.clock():
                try:
                    await self.on_scheduled(person, {**item, "platform": platform})
                except Exception:
                    log.exception("on_scheduled failed")

    def record_uploads(self, platform: str, accounts: List[Dict[str, Any]], found: Dict[str, List[Dict[str, Any]]]) -> int:
        """Save non-stream videos (``found``: {platform_id: [entry]}) for the reviews' "Also this week"
        (store table "uploads"). Returns how many were new."""
        new = 0
        for a in accounts:
            for u in found.get(a["platform_id"], []):
                new += self.store.add_upload(a["person_id"], platform, u["video_id"], u["kind"], u["at"], u.get("title") or "",
                                             u.get("url") or "", u.get("thumb") or "", float(u.get("length") or 0))
        return new

    async def refresh_schedules(self) -> None:
        """Twitch schedules of everyone followed (YouTube's come with each YouTube check), and their
        Twitch uploads and highlights for the reviews."""
        tw = self.checkers.get("twitch")
        if not tw or not getattr(tw, "ready", True) or not hasattr(tw, "schedule"):
            return
        for a in [a for a in self.store.accounts("twitch") if a["platform_id"]]:
            if hasattr(tw, "recent_uploads"):
                try:
                    found = await tw.recent_uploads(a["platform_id"], self.clock() - 8 * 86400)
                    self.record_uploads("twitch", [a], {a["platform_id"]: found})
                except Exception as e:
                    log.info("Twitch uploads for %s failed: %s", a["handle"], e)
            try:
                segs = await tw.schedule(a["platform_id"], limit=10)
            except Exception as e:
                log.info("Twitch schedule for %s failed: %s", a["handle"], e)
                continue
            items = [dict(s, key=s.get("key") or f"{a['platform_id']}:{int(s['at'])}",
                          url=s.get("url") or f"https://twitch.tv/{a['handle'].lstrip('@')}")
                     for s in segs if s.get("at")]
            await self._save_scheduled(a["person_id"], "twitch", items)

    async def run_schedules(self) -> None:
        """Background task (flavrpromo/__main__.py): refresh_schedules every SCHEDULE_EVERY."""
        while True:
            try:
                await self.refresh_schedules()
            except Exception:
                log.exception("schedule refresh failed")
            await asyncio.sleep(SCHEDULE_EVERY)

    async def find_vod(self, person: Dict[str, Any], session: Dict[str, Any]) -> Tuple[str, str]:
        """(VOD link, VOD picture) of a finished stream, trying the person's main platform first.

        YouTube: the stream's own page is its VOD (picture: hqdefault.jpg). Twitch: the newest
        archive video (Helix videos). Kick has no VOD API: its channel's videos page, no picture."""
        try:
            links = json.loads(session.get("links") or "{}") if isinstance(session.get("links"), str) \
                else dict(session.get("links") or {})
        except ValueError:
            links = {}
        order = sorted(links, key=lambda p: (p != (person.get("main_platform") or "youtube"), PLATFORMS.index(p)
                                             if p in PLATFORMS else 9))
        for p in order:
            if p == "youtube":
                vid = youtube_id(links[p])
                if vid:
                    return links[p], f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            elif p == "twitch" and "twitch" in self.checkers and hasattr(self.checkers["twitch"], "last_vod"):
                acc = next((a for a in person.get("accounts") or [] if a["platform"] == "twitch" and a["platform_id"]), None)
                if acc:
                    try:
                        vod = await self.checkers["twitch"].last_vod(acc["platform_id"])
                    except Exception as e:
                        log.info("Twitch VOD look-up failed: %s", e)
                        vod = None
                    # only a VOD made at about this stream's start (not an older one)
                    if vod and vod.get("url") and abs(float(vod.get("created_at") or session["started_at"])
                                                      - float(session["started_at"])) < 3 * 3600:
                        return vod["url"], vod.get("thumb") or ""
            elif p == "kick" and links[p]:
                return links[p].rstrip("/") + "/videos", ""
        return "", ""

    def _youtube_due(self, person_id: int, start: float, end: float, done: Dict[str, float]) -> bool:
        """backfill: ask YouTube (quota) about this person? Only when something of theirs happened in
        [start, end) after their last YouTube look-up for these days (``done``: {person id: unix s})."""
        last = self.store.last_activity(person_id, start, end)
        return last > 0 and last > float(done.get(str(person_id), 0))

    async def backfill(self, start: float, end: float, everyone: bool = False) -> int:
        """Fill [start, end) (unix s) with finished streams from the platforms' own lists; returns how
        many sessions were added. The same person on two platforms within BACKFILL_MERGE (or
        overlapping) = one multistream session. Anything that overlaps a session the bot already has
        is skipped, and so is anything that ended in the last RESTART_GRACE (it may still be live:
        the watcher owns that one)."""
        now = self.clock()
        known = {}
        for s in self.store.sessions_between(start - 86400, end):
            known.setdefault(s["person_id"], []).append((float(s["started_at"]), float(s["ended_at"] or now)))
        added = 0
        done_key = f"yt_backfill.{int(start)}"      # YouTube look-ups already made for these days
        done = self.store.get(done_key, {}) or {}
        for person in self.store.people():
            found: List[Dict[str, Any]] = []
            for a in person.get("accounts") or []:
                c = self.checkers.get(a["platform"])
                if not a.get("platform_id") or c is None or not getattr(c, "ready", True) \
                        or not hasattr(c, "past_streams"):
                    continue
                if a["platform"] == "youtube":
                    if not everyone and not self._youtube_due(person["id"], start, end, done):
                        continue            # quiet in these days, or already looked up since: no quota spent
                    done[str(person["id"])] = now
                try:
                    for v in await c.past_streams(a["platform_id"], start, end):
                        found.append({**v, "platform": a["platform"]})
                except Exception as e:      # one platform failing mustn't stop the rest
                    log.info("%s past streams for %s failed: %s", a["platform"].title(), person["name"], e)
            merged: List[Dict[str, Any]] = []
            for v in sorted(found, key=lambda v: v["started_at"]):
                if v["ended_at"] > now - RESTART_GRACE:
                    continue
                twin = next((m for m in merged if abs(m["started_at"] - v["started_at"]) < BACKFILL_MERGE
                             or (v["started_at"] < m["ended_at"] and m["started_at"] < v["ended_at"])), None)
                if twin:
                    twin["ended_at"] = max(twin["ended_at"], v["ended_at"])
                    twin["links"].setdefault(v["platform"], v["url"])
                    twin["thumbs"].setdefault(v["platform"], v.get("thumb") or "")
                    if v["platform"] not in twin["platforms"]:
                        twin["platforms"].append(v["platform"])
                    continue
                merged.append({**v, "platforms": [v["platform"]], "links": {v["platform"]: v["url"]},
                               "thumbs": {v["platform"]: v.get("thumb") or ""}})
            mine = known.get(person["id"], [])
            for m in merged:
                if any(m["started_at"] < b and a < m["ended_at"] for a, b in mine):
                    continue                # the watcher saw this one (or an earlier backfill did)
                # the VOD link / picture of the person's main platform first (default YouTube)
                main = next((p for p in [person.get("main_platform") or "youtube", *PLATFORMS] if p in m["links"]))
                vod = m["links"][main]
                thumb = m["thumbs"][main] or next((t for t in m["thumbs"].values() if t), "")
                self.store.start_session(person["id"], m["started_at"], ended_at=m["ended_at"],
                                         last_seen=m["ended_at"], platforms=m["platforms"], links=m["links"],
                                         title=m["title"], url=vod, thumb=thumb, vod_url=vod, vod_thumb=thumb,
                                         source="vod")
                mine.append((m["started_at"], m["ended_at"]))
                added += 1
        self.store.put(done_key, done)
        if added:
            log.info("Filled in %d past stream(s) from the platforms", added)
        return added

    async def run_platform(self, platform: str) -> None:
        while True:
            await self.check(platform)
            await asyncio.sleep(self.every.get(platform, 300))

    # ── merging ────────────────────────────────────────────────────────
    def live_on(self, person: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        out = {}
        for a in person.get("accounts") or []:
            info = self.seen.get(a["platform"], {}).get(a["platform_id"]) if a["platform_id"] else None
            if info:
                out[a["platform"]] = {**info, "display": a.get("display") or a["handle"], "avatar": a.get("avatar") or ""}
        return out

    async def reconcile(self) -> None:
        async with self._lock:
            now = self.clock()
            for person in self.store.people():
                try:
                    await self._one(person, now)
                except Exception:
                    log.exception("watcher update for %s failed", person.get("name"))

    async def _one(self, person: Dict[str, Any], now: float) -> None:
        live_on = self.live_on(person)
        open_s = self.store.open_session(person["id"])
        if live_on:
            main = main_platform(person, live_on)
            info = live_on[main]
            fields = {"last_seen": now, "platforms": sorted(live_on, key=PLATFORMS.index), "title": info.get("title", ""),
                      "links": {p: i.get("url", "") for p, i in live_on.items()},
                      "url": info.get("url", ""), "thumb": info.get("thumb", ""), "game": info.get("game", ""),
                      "viewers": sum(int(i.get("viewers") or 0) for i in live_on.values())}
            if open_s:
                changed = (json.loads(open_s["platforms"]) != fields["platforms"] or open_s["title"] != fields["title"])
                if person["id"] in self._gone:
                    # it was offline everywhere and came back inside RESTART_GRACE: same stream, one restart
                    self._gone.discard(person["id"])
                    fields["restarts"] = int(open_s["restarts"]) + 1
                    changed = True
                self.store.update_session(open_s["id"], **fields)
                if changed and self.on_change:
                    await self.on_change(person, {**open_s, **fields}, live_on)
                return
            started = min([float(i["started_at"]) for i in live_on.values() if i.get("started_at")] or [now])
            last = self.store.last_session(person["id"])
            if last and last.get("ended_at") is not None and started < float(last["ended_at"]):
                # the platform says this stream began before the last one "ended": it never did end
                # (missed while the bot was down / a platform hadn't been checked yet). Reopen it.
                fields.update(ended_at=None, vod_url="", vod_thumb="")
                self.store.update_session(last["id"], **fields)
                if self.on_change:
                    await self.on_change(person, {**last, **fields}, live_on)
                return
            sid = self.store.start_session(person["id"], started, **{k: v for k, v in fields.items() if k != "last_seen"})
            self.store.update_session(sid, last_seen=now)
            session = {**fields, "id": sid, "started_at": started, "restarts": 0}
            if self.on_start:
                channel, message = await self.on_start(person, session, live_on)
                if message:
                    self.store.update_session(sid, post_channel=str(channel), post_message=str(message))
        elif open_s and (now - float(open_s["last_seen"]) < RESTART_GRACE
                         or not self._all_checked_since(person, float(open_s["last_seen"]))):
            self._gone.add(person["id"])        # offline for now; a comeback counts as a restart
        elif open_s:
            self._gone.discard(person["id"])
            ended = {"ended_at": float(open_s["last_seen"])}
            ended["vod_url"], ended["vod_thumb"] = await self.find_vod(person, open_s)
            self.store.update_session(open_s["id"], **ended)
            if self.on_end:
                await self.on_end(person, {**open_s, **ended})

    def _all_checked_since(self, person: Dict[str, Any], since: float) -> bool:
        """Has every platform this person streams on (with a working checker) answered after ``since``?"""
        for a in person.get("accounts") or []:
            c = self.checkers.get(a["platform"])
            if c is not None and getattr(c, "ready", True) and self.last_check.get(a["platform"], 0) <= since:
                return False
        return True

    # ── reading (/live, /schedule, /status) ────────────────────────────
    def owner_live(self) -> Optional[bool]:
        """Is the streamer (people marked owner) live anywhere, as this watcher sees it? True / False,
        or None when it can't say (no owner followed, or no checker has answered for them in the last
        10 minutes). FlaVR Bot asks it through /live.json (flavrpromo/server.py) so Stream Core going quiet after a
        stream isn't an alarm; flavrpromo/pings.py skips quiet hours while it is True."""
        owners = [p for p in self.store.people() if p.get("is_owner") and p.get("accounts")]
        if not owners:
            return None
        if any(self.live_on(p) for p in owners):
            return True
        if not all(self._all_checked_since(p, self.clock() - 600) for p in owners):
            return None
        return False


    def status(self) -> Dict[str, Any]:
        return {"platforms": {p: {"ready": bool(getattr(c, "ready", True)), "last_check": self.last_check.get(p),
                                  "error": self.errors.get(p, "")} for p, c in self.checkers.items()},
                "people": len(self.store.people())}

    async def schedule(self, person: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Upcoming streams of one person: Twitch's schedule + YouTube's scheduled streams."""
        out: List[Dict[str, Any]] = []
        for a in person.get("accounts") or []:
            if not a["platform_id"]:
                continue
            if a["platform"] == "twitch" and "twitch" in self.checkers:
                try:
                    out += await self.checkers["twitch"].schedule(a["platform_id"])
                except Exception as e:
                    log.info("Twitch schedule failed: %s", e)
            if a["platform"] == "youtube" and "youtube" in self.checkers:
                out += list(getattr(self.checkers["youtube"], "upcoming", {}).get(a["platform_id"], []))
        now = self.clock()
        return sorted((s for s in out if s.get("at") and s["at"] > now - 3600), key=lambda s: s["at"])
