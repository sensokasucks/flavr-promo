"""Community calendar (flavrpromo/promo.py): links, "when?", adding, following each stream, the board.
No network: the platform clients are fakes with the same calls as flavrpromo/platforms."""

from datetime import datetime

from flavrpromo import groups, promo
from flavrpromo.calendar import build_week, week_start
from flavrpromo.store import Store

from test_calendar import TZ, ts

NOW = ts(2026, 11, 20, 7)               # Friday 7 AM


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeYouTube:
    ready = True

    def __init__(self):
        self.vids = {}

    async def videos(self, ids):
        return {i: dict(self.vids[i]) for i in ids if i in self.vids}


class FakeTwitch:
    ready = True

    def __init__(self):
        self.live_now = {}              # user id → live info
        self.segments = []
        self.vods = []

    async def resolve(self, handles):
        return {h: ({"platform_id": "id_" + h, "display": h.title(), "avatar": "pic"} if h != "nobody" else None)
                for h in handles}

    async def live(self, accounts):
        return {a["platform_id"]: self.live_now[a["platform_id"]] for a in accounts if a["platform_id"] in self.live_now}

    async def schedule(self, pid, limit=5):
        return list(self.segments)

    async def past_streams(self, pid, since, until):
        return [v for v in self.vods if since <= v["started_at"] < until]

    async def video(self, vid):
        return None


class FakeKick:
    ready = True

    def __init__(self):
        self.live_now = {}

    async def channels(self, slugs):
        return [{"slug": s} for s in slugs if s != "nobody"]

    async def live(self, accounts):
        return {a["platform_id"]: self.live_now[a["platform_id"]] for a in accounts if a["platform_id"] in self.live_now}


def make(limit=7):
    store = Store(":memory:")
    groups.init(store)
    clock = Clock(NOW)
    pokes = []
    checkers = {"youtube": FakeYouTube(), "twitch": FakeTwitch(), "kick": FakeKick()}
    p = promo.Promo(store, checkers, TZ, weekly_limit=limit, wait_hours=6, poke=lambda: pokes.append(1), clock=clock)
    return store, p, checkers, clock, pokes


WHO = {"author_id": "111", "name": "Lulu", "avatar": "https://cdn/av.png", "added_by": "lulu"}


def test_links():
    L = promo.parse_link
    assert L("https://www.youtube.com/watch?v=YapXOrRpuxk").ident == "YapXOrRpuxk"
    assert L("https://m.youtube.com/watch?si=x&v=YapXOrRpuxk").ident == "YapXOrRpuxk"
    assert L("https://youtu.be/YapXOrRpuxk?si=abc").kind == "video"
    assert L("https://youtube.com/live/YapXOrRpuxk").platform == "youtube"
    assert (L("https://www.twitch.tv/videos/123456").platform, L("https://www.twitch.tv/videos/123456").kind) == ("twitch", "video")
    assert L("https://twitch.tv/SensokaFlaVR").ident == "sensokaflavr"
    assert L("https://kick.com/sensoka-FlaVR/").ident == "sensoka-flavr"
    assert L("https://kick.com/categories") is None and L("https://twitch.tv/directory") is None
    assert L("https://example.com/watch?v=YapXOrRpuxk") is None
    assert L("https://www.youtube.com/@someone") is None          # a channel page: post the stream's own link
    text = ("live now!! https://twitch.tv/lulu and https://youtu.be/YapXOrRpuxk also "
            "https://twitch.tv/lulu again, my art https://example.com/x")
    assert [(x.platform, x.ident) for x in promo.find_links(text)] == [("twitch", "lulu"), ("youtube", "YapXOrRpuxk")]


def test_when():
    W = lambda text: promo.parse_when(text, NOW, TZ)             # noqa: E731  (Friday 7 AM)
    assert W("8pm") == ts(2026, 11, 20, 20)
    assert W("6am") == ts(2026, 11, 21, 6)                         # passed today → tomorrow
    assert W("sat 8pm") == ts(2026, 11, 21, 20)
    assert W("Saturday 8:30 PM") == ts(2026, 11, 21, 20, 30)
    assert W("friday 6am") == ts(2026, 11, 27, 6)                  # today's has passed → next week
    assert W("tomorrow 7:30pm") == ts(2026, 11, 21, 19, 30)
    assert W("tonight 9") == ts(2026, 11, 20, 21)
    assert W("mon 19:00") == ts(2026, 11, 23, 19)
    assert W("<t:1763600000:F>") == 1763600000.0
    assert W("whenever") is None and W("25:00") is None


async def test_youtube_link_follows_the_stream():
    store, p, ck, clock, pokes = make()
    yt = ck["youtube"]
    yt.vids["YapXOrRpuxk"] = {"state": "upcoming", "at": ts(2026, 11, 21, 20), "end": None, "title": "Cozy games",
                              "channel_id": "UCx", "channel": "Lulu Teala", "url": "https://www.youtube.com/watch?v=YapXOrRpuxk",
                              "thumb": "https://i.ytimg.com/vi/YapXOrRpuxk/hqdefault.jpg"}
    yt.vids["upload00001"] = {**yt.vids["YapXOrRpuxk"], "state": "upload"}
    links = promo.find_links("https://youtu.be/YapXOrRpuxk https://youtu.be/upload00001")
    lines = await p.add(links, None, **WHO, post_channel="5", post_message="99")
    assert lines[0].startswith("Added: Lulu Teala on YouTube, planned <t:") and "Cozy games" in lines[0]
    assert "upload, not a stream" in lines[1] and pokes
    # the same video again (another post) merges
    assert "already on" in (await p.add(links[:1], None, **WHO))[0]
    # it goes live, then ends
    yt.vids["YapXOrRpuxk"].update(state="live", at=ts(2026, 11, 21, 20, 5))
    clock.t = ts(2026, 11, 21, 20, 10)
    assert await p.tick()
    yt.vids["YapXOrRpuxk"].update(state="past", end=ts(2026, 11, 21, 23))
    clock.t = ts(2026, 11, 21, 23, 30)
    assert await p.tick()
    row = store.promo_for_message("99")[0]
    assert (row["state"], row["at"], row["end_at"]) == ("past", ts(2026, 11, 21, 20, 5), ts(2026, 11, 21, 23))
    # the recap shows it, with the poster's Discord id as the person
    week = build_week(store, "community", week_start(NOW, TZ), clock.t, TZ, recap=True)
    (t,) = week.tiles()
    assert (t.kind, t.name, t.length, t.person_id, t.late) == ("past", "Lulu Teala", 2 * 3600 + 55 * 60, -111, False)
    assert groups.title("community", True) == "COMMUNITY: WEEK IN REVIEW"


async def test_twitch_channel_link_waits_then_goes_live_and_gets_its_vod():
    store, p, ck, clock, _ = make()
    tw = ck["twitch"]
    (line,) = await p.add(promo.find_links("https://twitch.tv/lulu"), None, **WHO, post_message="7")
    assert "not live yet" in line and "6 hours" in line
    week = build_week(store, "community", week_start(NOW, TZ), NOW, TZ)
    assert week.tiles() == []                                   # waiting: nothing to show yet
    tw.live_now["id_lulu"] = {"title": "Art stream", "game": "Art", "started_at": NOW + 3600, "thumb": "live.jpg"}
    clock.t = NOW + 3700
    assert await p.tick()
    (t,) = build_week(store, "community", week_start(NOW, TZ), clock.t, TZ).tiles()
    assert (t.kind, t.title, t.name) == ("live", "Art stream", "Lulu")
    # still live a bit later: nothing changes; gone for LIVE_GONE: over, with the VOD
    clock.t = NOW + 2 * 3600
    assert not await p.tick()
    del tw.live_now["id_lulu"]
    tw.vods = [{"started_at": NOW + 3600, "ended_at": NOW + 3 * 3600, "url": "https://twitch.tv/videos/1", "thumb": "vod.jpg",
                "title": "Art stream"}]
    clock.t = NOW + 2 * 3600 + promo.LIVE_GONE + 1
    assert await p.tick()
    row = store.promo_for_message("7")[0]
    assert (row["state"], row["url"], row["thumb"], row["end_at"]) == ("past", "https://twitch.tv/videos/1", "vod.jpg", NOW + 3 * 3600)


async def test_channel_link_with_a_time_its_schedule_and_the_wait_running_out():
    store, p, ck, clock, _ = make()
    ck["twitch"].segments = [{"key": "s1", "at": NOW + 86400, "title": "Speedruns", "game": "Celeste", "thumb": "box.jpg"}]
    assert "planned" in (await p.add(promo.find_links("https://twitch.tv/pip"), None, **WHO))[0]   # from Twitch's schedule
    assert "planned" in (await p.add(promo.find_links("https://kick.com/choco"), ts(2026, 11, 21, 18), **WHO))[0]
    (tw_row,) = [r for r in store.promo_active() if r["platform"] == "twitch"]
    assert (tw_row["state"], tw_row["title"], tw_row["thumb"]) == ("scheduled", "Speedruns", "box.jpg")
    # this week's board (Sunday to Saturday) shows both as planned; the recap leaves planned ones out
    tiles = build_week(store, "community", week_start(NOW, TZ), NOW, TZ).tiles()
    assert sorted(t.kind for t in tiles) == ["scheduled", "scheduled"]
    assert build_week(store, "community", week_start(NOW, TZ), NOW, TZ, recap=True).tiles() == []
    # a Kick channel added offline with no time: dropped after PROMO_WAIT_HOURS
    await p.add(promo.find_links("https://kick.com/raimi"), None, **WHO)
    clock.t = NOW + 6 * 3600 + 1
    assert await p.tick()
    assert not any(r["channel"] == "raimi" for r in store.promo_active())
    # the planned Kick stream happens: live, then over, linked to the channel's videos page
    ck["kick"].live_now["choco"] = {"title": "Sunday chill", "started_at": ts(2026, 11, 21, 18, 3), "thumb": "k.jpg"}
    clock.t = ts(2026, 11, 21, 18, 10)
    assert await p.tick()
    ck["kick"].live_now.clear()
    clock.t = ts(2026, 11, 21, 21)
    assert await p.tick()
    row = next(r for r in store.promo_between(0, 2e9) if r["channel"] == "choco")
    assert (row["state"], row["url"], row["title"]) == ("past", "https://kick.com/choco/videos", "Sunday chill")
    # the Twitch one (Saturday 7 AM) never happened: off the board STALE_AFTER after its time
    assert not any(r["platform"] == "twitch" for r in store.promo_between(0, 2e9))


async def test_who_may_add_limits_and_removing():
    store, p, ck, clock, pokes = make(limit=2)
    assert "Nobody has been allowed" in p.may_add([5], False, True)
    p.set_role(5, True)
    assert p.may_add([5, 6], False, True) == ""
    assert "allowed roles" in p.may_add([6], False, True)
    assert "only add your own" in p.may_add([5], False, False)
    assert p.may_add([], True, False) == ""                     # moderators: anyone's post
    for i, h in enumerate(("a1", "b2", "c3")):
        await p.add(promo.find_links(f"https://kick.com/{h}xx"), NOW + 86400 * (i + 1), **WHO, post_message=str(i))
    assert len(store.promo_active()) == 2                       # the third hit the weekly limit
    lines = await p.add(promo.find_links("https://kick.com/d4xx"), NOW + 3600, **WHO)
    assert "the most allowed" in lines[0]
    assert "Added" in (await p.add(promo.find_links("https://kick.com/d4xx"), NOW + 3600, **WHO, is_mod=True))[0]
    assert "no channel called nobody" in (await p.add(promo.find_links("https://kick.com/nobody"), None, **WHO, is_mod=True))[0]
    # remove: only the poster or a moderator
    assert p.remove_post("0", "222", False) == (0, 1)
    assert p.remove_post("0", "111", False) == (1, 0)
    rid = store.promo_for_message("1")[0]["id"]
    assert "someone else" in p.remove(rid, "222", False)
    assert p.remove(rid, "222", True) == ""
    # a deleted post takes its stream with it
    await p.add(promo.find_links("https://kick.com/e5xx"), NOW + 7200, **WHO, post_message="77", is_mod=True)
    assert p.post_deleted("77") == 1 and store.promo_for_message("77") == []
    lines = p.listing(0, 2e9)
    assert lines and "(post by <@111>)" in lines[0]


async def test_multistream_is_one_tile():
    store, p, ck, clock, _ = make()
    ck["twitch"].live_now["id_lulu"] = {"title": "Both", "started_at": NOW - 600, "thumb": "t.jpg"}
    ck["kick"].live_now["lulu"] = {"title": "Both", "started_at": NOW - 300, "thumb": "k.jpg"}
    lines = await p.add(promo.find_links("https://twitch.tv/lulu https://kick.com/lulu"), None, **WHO)
    assert all("live now" in x for x in lines)
    (t,) = build_week(store, "community", week_start(NOW, TZ), NOW, TZ).tiles()
    assert t.kind == "live" and t.platforms == ["twitch", "kick"]
    # adding the same live channel again (another post) is a duplicate, not a second tile
    assert "already on" in (await p.add(promo.find_links("https://twitch.tv/lulu"), None, **WHO))[0]


def test_community_is_a_built_in_board():
    store = Store(":memory:")
    groups.init(store)
    assert "community" in groups.keys() and not groups.remove("community")
    assert groups.heading("community", False) == "Community streams this week"
    assert groups.title("community", False) == "COMMUNITY STREAMS THIS WEEK"
    assert datetime.fromtimestamp(NOW, TZ).weekday() == 4      # the tests' "now" is a Friday
