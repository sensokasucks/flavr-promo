"""Collab streams (owner 2026-11-22, flavrpromo/collabs.py): @mentions in titles become possible
collabs, the owner confirms them (DM buttons, /collab, /settings/collabs), and confirmed ones are
highlighted on every calendar. No network, no Discord."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flavrpromo import collab_page, collabs, groups
from flavrpromo.calendar import build_week, week_start
from flavrpromo.calendar_post import CalendarPoster, embed
from flavrpromo.render import ImageCache, page, tiles_card
from flavrpromo.share import discord_text
from flavrpromo.store import Store
from flavrpromo.web import ics

TZ = ZoneInfo("America/New_York")


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


NOW = ts(2026, 11, 23, 12)          # Monday noon


def world():
    store = Store(":memory:")
    groups.init(store)
    lulu = store.add_person("Lulu", "flavr")
    store.add_account(lulu, "youtube", "@luluteala")
    pip = store.add_person("Pippa", "friends")
    store.add_account(pip, "youtube", "@pipkinpippa")
    cara = store.add_person("Cara Malone", "friends")
    store.add_account(cara, "twitch", "caramalone")
    return store, lulu, pip, cara


def test_find_mentions_people_groups_and_outsiders():
    store, lulu, pip, cara = world()
    index = collabs.Index(store.people(), groups.keys())

    def who(title, pid):
        return [(p["kind"], p["name"]) for p in collabs.find(title, pid, index)]

    # a friend tags the FlaVR group and a FlaVR member's handle
    assert who("Bricks with @FlaVR and @luluteala!", pip) == [("group", "FlaVR"), ("person", "Lulu")]
    # their own group is like a hashtag (not a collab); their own handle neither; #hashtags never count
    assert who("Cozy night @FlaVR @luluteala #flavr #vtuber", lulu) == []
    # "w/" / "ft." + a name the bot follows (several words too); "with friends" / "with chat" never count
    assert who("Lethal Company w/ Cara Malone", lulu) == [("person", "Cara Malone")]
    assert who("Horror ft. Pippa", lulu) == [("person", "Pippa")]
    assert who("Chill with friends and with chat", lulu) == []
    # an outside streamer by @handle; @everyone and e-mail addresses are not mentions
    assert who("Duo night @SomeoneElse @everyone mail me hi@lulu.com", pip) == [("handle", "@SomeoneElse")]


def test_scan_suggests_once_and_dismissed_stays_dismissed():
    store, lulu, pip, cara = world()
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19), "title": "Collab with @FlaVR"}],
                            now=NOW)
    fresh = collabs.scan(store, NOW)
    assert len(fresh) == 1 and fresh[0]["name"] == "Pippa" and collabs.names(fresh[0]["partners"]) == ["FlaVR"]
    assert collabs.scan(store, NOW) == []                                   # once per stream
    # the title gains a name: the waiting suggestion picks it up
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19),
                                              "title": "Collab with @FlaVR and @caramalone"}], now=NOW)
    collabs.scan(store, NOW)
    row = store.collab_get(fresh[0]["id"])
    assert collabs.names(row["partners"]) == ["FlaVR", "Cara Malone"]
    collabs.decide(store, row["id"], False, NOW)
    # the live stream that replaces the scheduled one: same stream, still "not a collab"
    store.start_session(pip, ts(2026, 11, 26, 19, 5), platforms=["youtube"], title="Collab with @FlaVR LIVE")
    assert collabs.scan(store, NOW + 3 * 86400) == []
    assert store.collab_get(row["id"])["state"] == "dismissed"
    # spotting off: nothing new
    store.put("collab_detect", False)
    store.replace_scheduled(lulu, "youtube", [{"key": "v2", "at": ts(2026, 11, 27, 19), "title": "w/ Pippa"}], now=NOW)
    assert collabs.scan(store, NOW) == []


def test_confirmed_collab_is_highlighted_everywhere():
    store, lulu, pip, cara = world()
    # Pippa's scheduled stream @mentions Lulu; Lulu streams at the same time
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19), "title": "Duo with @luluteala",
                                              "url": "https://www.youtube.com/watch?v=v1"}], now=NOW)
    store.replace_scheduled(lulu, "youtube", [{"key": "v9", "at": ts(2026, 11, 26, 19), "title": "Duo!"}], now=NOW)
    (row,) = collabs.scan(store, NOW)
    friends = build_week(store, "friends", week_start(NOW, TZ), NOW, TZ)
    assert all(not t.collab for t in friends.tiles())                       # only CONFIRMED ones show
    sig = friends.signature()
    collabs.decide(store, row["id"], True, NOW)
    friends = build_week(store, "friends", week_start(NOW, TZ), NOW, TZ)
    flavr = build_week(store, "flavr", week_start(NOW, TZ), NOW, TZ)
    (pt,) = [t for t in friends.tiles() if t.name == "Pippa"]
    (lt,) = [t for t in flavr.tiles() if t.name == "Lulu"]
    assert pt.collab == ["Lulu"] and lt.collab == ["Pippa"]                 # both sides
    assert friends.signature() != sig                                       # the board redraws
    img = lambda u: ""
    board = page(friends, img)
    assert 'class="tile scheduled collab"' in board and "COLLAB" in board and "with Lulu" in board
    assert 'class="c collab"' in tiles_card("friends", "THURSDAY", [pt], TZ, img)
    assert "🤝 *with Lulu*" in embed(friends)["fields"][0][1]
    assert "🤝" in discord_text(friends)
    assert "Pippa (collab with Lulu): Duo" in ics([friends], NOW)
    # the live stream keeps the highlight
    store.start_session(pip, ts(2026, 11, 26, 19, 4), platforms=["youtube"], title="Duo with @luluteala")
    live = build_week(store, "friends", week_start(NOW, TZ), ts(2026, 11, 26, 19, 30), TZ)
    assert [t.collab for t in live.tiles() if t.kind == "live"] == [["Lulu"]]


def test_mark_by_hand_and_pick_stream():
    store, lulu, pip, cara = world()
    store.replace_scheduled(lulu, "youtube", [{"key": "a", "at": ts(2026, 11, 24, 20), "title": "Tue"},
                                              {"key": "b", "at": ts(2026, 11, 27, 20), "title": "Fri"}], now=NOW)
    assert collabs.pick_stream(store, lulu, NOW, TZ)["title"] == "Tue"           # the next one
    assert collabs.pick_stream(store, lulu, NOW, TZ, 5)["title"] == "Fri"        # on Friday
    assert collabs.pick_stream(store, lulu, NOW, TZ, 3) is None
    parts = collabs.partners_from_text(store, "flavr, Pippa, @Outsider, Lulu", lulu)
    assert [(p["kind"], p["name"]) for p in parts] == [("group", "FlaVR"), ("person", "Pippa"), ("handle", "@Outsider")]
    cid = collabs.add(store, lulu, ts(2026, 11, 27, 20), parts, "Fri", now=NOW)
    assert store.collab_get(cid)["state"] == "confirmed"
    assert collabs.with_text(collabs.names(parts)) == "with FlaVR, Pippa and @Outsider"


class FakeDiscord:
    def __init__(self):
        self.collab_dms = []

    async def dm_collab(self, text, cid):
        self.collab_dms.append((text, cid))


async def test_collab_tick_dms_each_suggestion_once_and_waits_for_quiet_hours(tmp_path):
    store, lulu, pip, cara = world()
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19), "title": "w/ Lulu"}], now=NOW)
    d = FakeDiscord()
    quiet = {"on": True}
    poster = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: NOW,
                            quiet=lambda: quiet["on"], collab_on=lambda: True)
    await poster.collab_tick()
    assert d.collab_dms == []                       # quiet hours: waits
    quiet["on"] = False
    await poster.collab_tick()
    await poster.collab_tick()
    assert len(d.collab_dms) == 1 and "Possible collab" in d.collab_dms[0][0] and "Lulu" in d.collab_dms[0][0]


async def test_collab_page_confirm_and_mark(tmp_path):
    store, lulu, pip, cara = world()
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19), "title": "w/ Lulu"}], now=NOW)
    store.replace_scheduled(cara, "twitch", [{"key": "t1", "at": ts(2026, 11, 28, 15), "title": "Bricks"}], now=NOW)
    (row,) = collabs.scan(store, NOW)
    poster = CalendarPoster(store, FakeDiscord(), ImageCache(tmp_path), None, clock=lambda: NOW)
    app = web.Application()
    collab_page.add_routes(app, poster)
    async with TestClient(TestServer(app)) as c:
        html = await (await c.get("/settings/collabs")).text()
        assert "Waiting for you" in html and "Pippa" in html and "with Lulu" in html
        r = await c.post("/settings/collabs", data={"action": "confirm", "id": str(row["id"])}, allow_redirects=False)
        assert "Confirmed" in r.headers["Location"] and store.collab_get(row["id"])["state"] == "confirmed"
        at = int(ts(2026, 11, 28, 15))
        r = await c.post("/settings/collabs", data={"action": "add", "stream": f"{cara}:{at}", "partners": "FlaVR"},
                         allow_redirects=False)
        assert "Marked" in r.headers["Location"]
        assert [collabs.names(x["partners"]) for x in store.collabs_between(at - 60, at + 60)] == [["FlaVR"]]
        await c.post("/settings/collabs", data={"action": "detect"}, allow_redirects=False)
        assert store.get("collab_detect") is False


def test_two_way_tag_is_one_question():
    store, lulu, pip, cara = world()
    store.replace_scheduled(pip, "youtube", [{"key": "v1", "at": ts(2026, 11, 26, 19), "title": "w/ @luluteala"}], now=NOW)
    store.replace_scheduled(lulu, "youtube", [{"key": "v2", "at": ts(2026, 11, 26, 19, 10), "title": "w/ @pipkinpippa"}],
                            now=NOW)
    fresh = collabs.scan(store, NOW)
    assert len(fresh) == 1                                      # one DM for the pair
    collabs.decide(store, fresh[0]["id"], True, NOW)
    rows = store.collabs_between(NOW, NOW + 7 * 86400)
    assert [r["state"] for r in rows] == ["confirmed", "confirmed"]
