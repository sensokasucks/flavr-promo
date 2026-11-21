"""Go-live watcher (flavrpromo/watcher.py): per-person merge, multistream, restarts, ends; parsers."""

import json

from flavrpromo.bot import parse_import
from flavrpromo.platforms.youtube import parse_feed
from flavrpromo.store import Store
from flavrpromo.watcher import RESTART_GRACE, Watcher, main_platform


class FakeChecker:
    ready = True

    def __init__(self, platform):
        self.platform = platform
        self.now = {}

    async def resolve(self, handles):
        return {h: {"platform_id": h.lower().lstrip("@"), "display": h, "avatar": ""} for h in handles}

    async def live(self, accounts):
        return {k: v for k, v in self.now.items() if k in {a["platform_id"] for a in accounts}}


def setup():
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    store.add_account(lulu, "youtube", "@luluteala")
    store.add_account(lulu, "twitch", "luluteala")
    sen = store.add_person("Sensoka", "flavr", is_owner=True)
    store.add_account(sen, "twitch", "sensoka")
    checkers = {"youtube": FakeChecker("youtube"), "twitch": FakeChecker("twitch")}
    clock = {"t": 10_000.0}
    w = Watcher(store, checkers, {}, clock=lambda: clock["t"])
    log = []

    async def on_start(person, session, live_on):
        log.append(("start", person["name"], tuple(sorted(live_on))))
        return "1", "99"

    async def on_change(person, session, live_on):
        log.append(("change", person["name"], tuple(sorted(live_on)), session.get("restarts")))

    async def on_end(person, session):
        log.append(("end", person["name"], session["ended_at"]))

    w.on_start, w.on_change, w.on_end = on_start, on_change, on_end
    return store, checkers, clock, w, log


def live(title="Hi", started=9_900.0, url="u"):
    return {"title": title, "url": url, "thumb": "t", "viewers": 5, "started_at": started}


async def test_multistream_is_one_session_and_main_platform_is_youtube():
    store, ch, clock, w, log = setup()
    ch["twitch"].now = {"luluteala": live()}
    await w.check("twitch")
    ch["youtube"].now = {"luluteala": live(url="yt")}
    await w.check("youtube")
    assert log == [("start", "Lulu", ("twitch",)), ("change", "Lulu", ("twitch", "youtube"), 0)]
    rows = store.live_now()
    assert len(rows) == 1 and rows[0]["url"] == "yt"            # YouTube leads by default
    assert json.loads(rows[0]["platforms"]) == ["youtube", "twitch"]
    assert rows[0]["post_message"] == "99"
    assert rows[0]["started_at"] == 9_900.0                     # the platform's own start time


async def test_restart_inside_grace_and_end_after():
    store, ch, clock, w, log = setup()
    ch["twitch"].now = {"sensoka": live()}
    await w.check("twitch")
    ch["twitch"].now = {}
    clock["t"] += 300
    await w.check("twitch")
    assert [e[0] for e in log] == ["start"]                     # not over yet
    clock["t"] += 300
    ch["twitch"].now = {"sensoka": live()}
    await w.check("twitch")                                     # back within 15 min: a restart
    assert log[-1][0] == "change" and log[-1][3] == 1
    ch["twitch"].now = {}
    clock["t"] += 120
    await w.check("twitch")
    clock["t"] += RESTART_GRACE
    await w.check("twitch")
    assert log[-1] == ("end", "Sensoka", 10_600.0)              # ended at the last sighting
    clock["t"] += 60
    ch["twitch"].now = {"sensoka": live(started=clock["t"])}   # a new stream has its own, later start time
    await w.check("twitch")                                     # later: a new stream
    assert log[-1][0] == "start"
    assert len(store.live_now()) == 1


async def test_a_failed_platform_keeps_its_last_answer():
    store, ch, clock, w, log = setup()
    ch["twitch"].now = {"sensoka": live()}
    await w.check("twitch")

    async def broken(accounts):
        raise RuntimeError("HTTP 500")

    ch["twitch"].live = broken
    clock["t"] += RESTART_GRACE * 2
    await w.check("twitch")
    assert w.errors["twitch"] == "HTTP 500"
    assert [e[0] for e in log] == ["start"]


def test_main_platform_pick():
    assert main_platform({"main_platform": "twitch"}, {"youtube": {}, "twitch": {}}) == "twitch"
    assert main_platform({"main_platform": "kick"}, {"youtube": {}, "twitch": {}}) == "youtube"
    assert main_platform({}, {"kick": {}, "twitch": {}}) == "twitch"


def test_parse_import():
    rows = parse_import("# name, platform, handle, group\nLulu, youtube, @luluteala, flavr\n"
                        "Pippa\tyoutube\t@pipkinpippa\tfriends\nbad line\nX, myspace, y")
    assert rows == [("Lulu", "youtube", "@luluteala", "flavr"), ("Pippa", "youtube", "@pipkinpippa", "friends")]


def test_youtube_feed_parse():
    xml = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
           'xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">'
           '<entry><yt:videoId>abc12345678</yt:videoId><title>Stream!</title>'
           '<published>2026-11-17T19:00:00+00:00</published>'
           '<media:group><media:thumbnail url="https://i.ytimg.com/vi/abc12345678/hqdefault.jpg"/></media:group>'
           '</entry></feed>')
    rows = parse_feed(xml)
    assert rows[0]["video_id"] == "abc12345678" and rows[0]["title"] == "Stream!"
    assert rows[0]["published"] > 1.7e9
    assert parse_feed("not xml") == []


async def test_bot_restart_mid_stream_doesnt_count_twice():
    """A redeploy longer than RESTART_GRACE: Twitch answers first, YouTube later (the Amanda case)."""
    store, ch, clock, w, log = setup()
    ch["youtube"].now = {"luluteala": live(started=9_900.0, url="yt")}
    await w.check("youtube")
    # the bot is down for 20 minutes, then a NEW watcher (memory lost) checks Twitch first
    w2 = Watcher(store, ch, {}, clock=lambda: clock["t"])
    w2.on_start, w2.on_change, w2.on_end = w.on_start, w.on_change, w.on_end
    clock["t"] += 20 * 60
    await w2.check("twitch")
    assert [e[0] for e in log] == ["start"]                     # not ended: YouTube not asked yet
    await w2.check("youtube")
    assert [e[0] for e in log] == ["start", "change"]           # same session, still one
    assert len(store.live_now()) == 1


async def test_reopen_and_merge_overlapping_sessions():
    store, ch, clock, w, log = setup()
    lulu = store.person("Lulu")["id"]
    # an older version ended the stream at 10,600, then made a new one starting at 9,900 (real start)
    a = store.start_session(lulu, 9_900.0, platforms=["youtube"])
    store.update_session(a, ended_at=10_600.0, restarts=1)
    store.start_session(lulu, 9_900.0, platforms=["youtube"], post_message="new")
    assert store.merge_overlaps() == 1
    rows = store.live_now()
    assert len(rows) == 1 and rows[0]["post_message"] == "new" and rows[0]["restarts"] == 1
    assert store.merge_overlaps() == 0
    # and the watcher reopens an ended session instead of starting a second one
    store.update_session(rows[0]["id"], ended_at=10_600.0)
    ch["youtube"].now = {"luluteala": live(started=9_900.0, url="yt")}
    await w.check("youtube")
    assert len(store.live_now()) == 1 and log[-1][0] == "change"
