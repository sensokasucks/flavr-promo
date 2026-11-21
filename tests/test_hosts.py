"""Colette and Clark (flavrpromo/hosts.py, host_cards.py, host_picker.py): who presents a post (never
three in a row), lines with blanks (a line missing a value is skipped), the review facts and
candidate lines, the cards' HTML, saving pictures, and the review that waits for the owner's picks
(owner 2026-11-20): DM with the picker link, one nudge after an hour, then opener → board → desk."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flavrpromo import host_cards, host_picker, hosts
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.render import ImageCache
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


class FakeDiscord:
    def __init__(self):
        self.sent, self.dms = [], []

    async def cal_send(self, channel, data, png, name):
        self.sent.append((channel, data["title"], name, data.get("description", "")))
        return str(100 + len(self.sent))

    async def cal_edit(self, channel, message, data, png, name):
        return True

    async def dm_owner(self, text, png=None):
        self.dms.append(text)


def test_choose_never_three_in_a_row():
    store = Store(":memory:")
    rng = random.Random(4)
    picks = [hosts.choose(store, rng) for _ in range(300)]
    assert set(picks) == {"colette", "clark"}
    assert not any(picks[i] == picks[i + 1] == picks[i + 2] for i in range(len(picks) - 2))
    store.put("hosts_only", "clark")                    # /host setup only: Clark
    assert {hosts.choose(store, rng) for _ in range(20)} == {"clark"}


def test_lines_skip_missing_blanks():
    assert hosts.fill("{name} plays {game}", {"name": "Lulu", "game": ""}) is None
    assert hosts.fill("{name} is live", {"name": "Lulu"}) == "Lulu is live"
    rng = random.Random(1)
    start = hosts.live_line("colette", "start", "Lulu", rng=rng)
    assert "Lulu" in start and "{" not in start
    assert "Valheim" in hosts.live_line("clark", "start", "Lulu", "Valheim", "new", rng=rng)
    assert "PART 3" in hosts.live_line("colette", "start", "Lulu", "Valheim", "part:3", rng=rng)
    assert "Valheim" in hosts.live_line("clark", "change", "Lulu", "Valheim", rng=rng)
    end = hosts.live_line("clark", "end", "Lulu", length=5 * 3600, signoff="🍗 otsu", rng=rng)
    assert "otsu" in end and "5 h 0 min" in end
    assert hosts.speaker("colette") == "☕ **Colette Cappuccino:**"


def world():
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    sen = store.add_person("Sensoka", "flavr", is_owner=True)
    for who, day, h, hours in ((lulu, 16, 19, 3), (lulu, 17, 18, 5), (sen, 18, 20, 2)):
        sid = store.start_session(who, ts(2026, 11, day, h), platforms=["youtube"], title="t")
        store.update_session(sid, ended_at=ts(2026, 11, day, h) + hours * 3600)
        store.segment_add(sid, who, "Valheim" if day == 18 else "Schedule I", ts(2026, 11, day, h),
                          "new" if day == 18 else "")
    return store


def test_review_facts_notes_and_candidates(tmp_path):
    store = world()
    p = CalendarPoster(store, FakeDiscord(), ImageCache(tmp_path), None, clock=lambda: ts(2026, 11, 20, 10, 5))
    f = hosts.facts(store, p.build_review("flavr", "week"))
    assert f["streams"] == 3 and f["hours"] == 10
    assert (f["top_name"], f["top_count"]) == ("Lulu", 2)
    assert f["longest_name"] == "Lulu" and f["longest_len"] == "5 h 0 min"
    assert f["new_game"] == "Valheim" and f["new_game_name"] == "Sensoka"
    assert f["quiet_day"] == "Thursday"
    assert hosts.pose(f) == "pointing"
    labels = [n["label"] for n in hosts.notes(f)]
    assert labels == ["LONGEST STREAM", "MOST SHOWS", "NEW GAME"]
    c = hosts.review_candidates("clark", f)
    assert set(c) == {"opener", "note0", "note1", "note2", "desk_highlight", "desk_nudge", "desk_signoff"}
    assert all(c[k] for k in c) and not any("{" in x for v in c.values() for x in v)


def test_cards_escape_text():
    notes = [{"label": "MOST SHOWS", "value": "<b>Lulu</b> · 2", "slot": "note_most"}]
    for key in hosts.HOSTS:
        page = host_cards.opener(key, "Week in Review", "Nov 16 - 19", "<script>x</script>", notes, ["ok"], "happy")
        assert "<script>x" not in page and "&lt;b&gt;Lulu" in page and "1600px" in page
        desk = host_cards.desk(key, "high <i>", "nudge", "bye")
        assert "high &lt;i&gt;" in desk


def test_save_picture(tmp_path):
    hosts.init(tmp_path)
    try:
        assert hosts.save_picture("colette", "head", b"PNG", "face.txt") == "Send a PNG, JPG or WebP picture."
        assert hosts.save_picture("nobody", "head", b"PNG", "a.png") == "Unknown host or picture kind."
        assert hosts.save_picture("colette", "happy", b"PNG1", "a.png") == ""
        assert hosts.save_picture("colette", "happy", b"JPG", "a.jpeg") == ""     # replaces the PNG
        assert sorted(x.name for x in (tmp_path / "colette").iterdir()) == ["happy.jpg"]
        assert hosts.pictures("colette")["happy"] and not hosts.pictures("colette")["sleepy"]
        assert hosts.picture("colette", "sleepy").name == "happy.jpg"             # a pose falls back
        assert hosts.picture("colette", "desk") is None
        assert hosts.data_url("colette", "happy").startswith("data:image/jpeg;base64,")
    finally:
        hosts.init(None)


async def test_review_waits_for_picks_then_posts_in_order(tmp_path):
    store = world()
    clock = {"t": ts(2026, 11, 20, 10, 5)}              # Friday 10:05 AM: the week review is due
    d = FakeDiscord()
    p = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: clock["t"])
    p.web_url = "http://pc:3871"
    store.put("calendar_channel.flavr", "55")
    store.put("hosts_on", True)
    store.put("hosts_only", "clark")
    await p.tick()
    titles = [s[1] for s in d.sent]
    assert not any("review" in t.lower() for t in titles)          # nothing posts before the picks
    assert len(d.dms) == 1 and "http://pc:3871/hosts/pick" in d.dms[0] and "Clark" in d.dms[0]
    clock["t"] += 30 * 60
    await p.tick()
    assert len(d.dms) == 1                                         # no nudge before an hour
    clock["t"] += 31 * 60
    await p.tick()
    await p.tick()
    assert len(d.dms) == 2 and "still waiting" in d.dms[1]         # one nudge, only once

    app = web.Application()
    host_picker.add_routes(app, p)
    key = host_picker.key_of("week", "flavr")
    async with TestClient(TestServer(app)) as client:
        page = await (await client.get("/hosts/pick")).text()
        assert "Clark" in page and "Post it" in page
        r = await client.post("/hosts/pick", data={"key": key, "action": "swap"}, allow_redirects=False)
        assert r.status == 303 and store.get(key)["host"] == "colette"
        first = store.get(key)["candidates"]["opener"][0]
        r = await client.post("/hosts/pick", data={"key": key, "action": "post", "opener": "__custom",
                                                   "opener__text": "  My   own line  ", "desk_nudge": first},
                              allow_redirects=False)
        assert r.status == 303
    pend = store.get(key)
    assert pend["ready"] and pend["picks"]["opener"] == "My own line"

    before = len(d.sent)
    await p.tick()
    out = d.sent[before:]
    assert [s[2].split("-")[1] if s[2].startswith("colette") else "board" for s in out] == ["opener", "board", "desk"]
    assert out[0][3] == "My own line"                              # text-only card without Chromium
    assert "review" in out[1][2]
    assert store.get(key) is None and host_picker.waiting(store) == []
    await p.tick()
    assert len(d.sent) == before + 3                               # posted once


async def test_hosts_off_posts_review_at_once(tmp_path):
    store = world()
    d = FakeDiscord()
    p = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: ts(2026, 11, 20, 10, 5))
    store.put("calendar_channel.flavr", "55")
    await p.tick()
    assert any("review" in s[2] for s in d.sent) and d.dms == []


class FakeMsg:
    def __init__(self, mid, author, kw):
        self.id, self.author, self.kw, self.edits = mid, author, kw, []
        self.embeds = [kw["embed"]]

    async def edit(self, **kw):
        self.edits.append(kw)
        if "embed" in kw:
            self.embeds = [kw["embed"]]


class FakeChannel:
    def __init__(self, cid, me):
        self.id, self.me, self.msgs = cid, me, {}

    async def send(self, **kw):
        m = FakeMsg(len(self.msgs) + 1, self.me, kw)
        self.msgs[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.msgs[mid]


async def test_live_card_host_lines(monkeypatch):
    # the go-live card's host line: chosen once at the start, a new line when the game changes, and
    # a closing line that reads out the sign-off (so the card doesn't repeat it)
    from types import SimpleNamespace
    from flavrpromo import config, groups, signoff
    from flavrpromo.bot import PromoBot
    from flavrpromo.pings import Pinger
    from flavrpromo.watcher import Watcher
    store = Store(":memory:")
    groups.init(store)
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None), Watcher(store, {}, {}))
    me = SimpleNamespace(id=999)
    monkeypatch.setattr(type(bot), "user", property(lambda self: me))
    ch = FakeChannel(55, me)
    monkeypatch.setattr(bot, "get_channel", lambda cid: ch if cid == 55 else None)
    store.put("live_channel.flavr", "55")
    store.put("hosts_on", True)
    store.put("hosts_only", "colette")
    lulu = store.add_person("Lulu", "flavr")
    person = {"id": lulu, "name": "Lulu", "grp": "flavr"}
    signoff.add(store, person, "otsu-nuggies", "🍗")
    t0 = ts(2026, 11, 20, 19)
    sid = store.start_session(lulu, t0, platforms=["twitch"], title="hi")
    store.segment_add(sid, lulu, "Valheim", t0, "new")
    live = {"twitch": {"url": "https://twitch.tv/lulu", "game": "Valheim"}}
    session = {"id": sid, "started_at": t0, "title": "hi"}
    channel, message = await bot.post_start(person, session, live)
    msg = ch.msgs[int(message)]
    assert msg.kw["content"].startswith("☕ **Colette Cappuccino:**") and "Valheim" in msg.kw["content"]
    assert msg.kw["embed"].author.name == "Colette Cappuccino · Marketing"
    row = {**session, "host": "colette", "host_game": "Valheim", "post_channel": channel, "post_message": message}
    await bot.post_change(person, row, live)                       # same game: the line stays
    assert "content" not in msg.edits[-1]
    store.segment_close(sid, t0 + 3600)
    store.segment_add(sid, lulu, "Schedule I", t0 + 3600, "")
    await bot.post_change(person, row, live)
    assert "Schedule I" in msg.edits[-1]["content"]
    await bot.post_end(person, {**row, "host_game": "Schedule I", "ended_at": t0 + 2 * 3600})
    end = msg.edits[-1]
    assert end["content"].startswith("☕ **Colette Cappuccino:**") and "2 h 0 min" in end["content"]
    assert "otsu" in end["content"]
    assert not any("otsu" in str(f.value) for f in end["embed"].fields)      # not said twice
    await bot.close()


def test_chibis_fall_back_and_make_the_face(tmp_path):
    hosts.init(tmp_path)
    try:
        assert hosts.face("clark") is None
        assert hosts.save_picture("clark", "chibi_sleepy", b"PNG", "c.png") == ""
        assert hosts.picture("clark", "chibi_happy").name == "chibi_sleepy.png"     # another chibi
        assert hosts.picture("clark", "happy") is None                              # never a chibi for a pose
        assert hosts.face("clark").name == "chibi_sleepy.png"                       # no head: the chibi
        assert hosts.save_picture("clark", "head", b"PNG", "h.png") == ""
        assert hosts.face("clark").name == "head.png"
        page = host_cards.opener("clark", "Week in Review", "Nov 16 - 19", "hi", [], [], "sleepy")
        assert page.count("data:image/png;base64,") == 1                            # the chibi peeking
    finally:
        hosts.init(None)


def test_day_lines():
    rng = random.Random(2)
    one = hosts.day_line("clark", "Today", 1, "Lulu", "8 PM", rng)
    assert "Lulu" in one and "{" not in one
    many = hosts.day_line("colette", "This weekend", 4, "Lulu", "Fri 8 PM", rng)
    assert "{" not in many and ("4" in many or "Lulu" in many)


def test_day_picture_host_corner_or_badge():
    from flavrpromo.calendar import Tile
    from flavrpromo.render import tiles_card
    host = {"chibi": "", "line": "Two <b>streams</b> today!", "accent": "#e0782e"}
    tile = Tile(kind="scheduled", name="Lulu", at=ts(2026, 11, 20, 20))
    few = tiles_card("flavr", "TODAY", [tile], TZ, lambda u: "", host=host)
    assert 'class="hb"' in few and "Two &lt;b&gt;streams" in few                    # big bubble in the free space
    many = tiles_card("flavr", "TODAY", [tile] * 12, TZ, lambda u: "", host=host)
    assert 'class="hb"' not in many and 'class="hs"' in many                       # header badge when full
    assert "<span>1 stream</span>" in tiles_card("flavr", "TODAY", [tile], TZ, lambda u: "")   # no host: the count


async def test_day_post_has_the_host(tmp_path):
    from flavrpromo import focus
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    store.add_account(lulu, "youtube", "@lulu")
    clock = {"t": ts(2026, 11, 20, 10, 5)}
    d = FakeDiscord()
    p = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: clock["t"])
    store.replace_scheduled(lulu, "youtube", [{"key": "v", "at": ts(2026, 11, 20, 20)}], now=clock["t"])
    store.put("day_posts.flavr", {"channel": "77", "today": 600, "tomorrow": None, "weekend": None, "weekend_day": 5})
    store.put("hosts_on", True)
    store.put("hosts_only", "clark")
    await focus.tick(p)
    sent = [s for s in d.sent if s[0] == "77"]
    assert len(sent) == 1 and sent[0][3].startswith("🍎 **Clark:**") and "Lulu" in sent[0][3]
    assert store.get("day_post.flavr.today")["host"]["key"] == "clark"
