"""The host's end-of-stream recap picture (flavrpromo/host_cards.py ``recap``, bot.py ``post_end``) and
the weekly / review boards in the host's look (host_cards.py ``board``, calendar_post.py ``png`` with
a host; owner 2026-11-21). Kv switches: host_recap_card, host_board (both default on with hosts on)."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flavrpromo import config, groups, host_cards, hosts, signoff
from flavrpromo.bot import PromoBot
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.pings import Pinger
from flavrpromo.render import ImageCache
from flavrpromo.store import Store
from flavrpromo.watcher import Watcher

TZ = ZoneInfo("America/New_York")
ME = SimpleNamespace(id=999)


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


class Shooter:
    def __init__(self):
        self.docs = []

    async def png(self, doc, size=None):
        self.docs.append(doc)
        return b"\x89PNG"


class FakeMsg:
    def __init__(self, mid, kw):
        self.id, self.author, self.kw, self.edits = mid, ME, kw, []
        self.embeds, self.attachments = [kw["embed"]], [SimpleNamespace(filename="host.webp")]

    async def edit(self, **kw):
        self.edits.append(kw)


class FakeChannel:
    def __init__(self):
        self.id, self.msgs = 55, {}

    async def send(self, **kw):
        m = FakeMsg(len(self.msgs) + 1, kw)
        self.msgs[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.msgs[mid]


async def stream(monkeypatch, tmp_path, recap_on=True):
    store = Store(":memory:")
    groups.init(store)
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None), Watcher(store, {}, {}))
    monkeypatch.setattr(type(bot), "user", property(lambda self: ME))
    ch = FakeChannel()
    monkeypatch.setattr(bot, "get_channel", lambda cid: ch if cid == 55 else None)
    shooter = Shooter()
    bot.calendar = SimpleNamespace(shooter=shooter, tz=TZ, images=ImageCache(tmp_path))
    store.put("live_channel.flavr", "55")
    store.put("hosts_on", True)
    store.put("hosts_only", "clark")
    if not recap_on:
        store.put("host_recap_card", False)
    lulu = store.add_person("Lulu", "flavr")
    person = {"id": lulu, "name": "Lulu", "grp": "flavr"}
    signoff.add(store, person, "otsu-nuggies", "🍗")
    t0 = ts(2026, 11, 20, 19)
    sid = store.start_session(lulu, t0, platforms=["twitch"], title="hi")
    store.segment_add(sid, lulu, "Valheim", t0, "new")
    session = {"id": sid, "started_at": t0, "title": "hi"}
    channel, message = await bot.post_start(person, session, {"twitch": {"url": "https://twitch.tv/lulu", "game": "Valheim"}})
    store.segment_close(sid, t0 + 3600)
    row = {**session, "host": "clark", "host_game": "Valheim", "post_channel": channel, "post_message": message,
           "ended_at": t0 + 3600, "platforms": '["twitch"]', "vod_url": "https://twitch.tv/videos/1"}
    await bot.post_end(person, row)
    await bot.close()
    return ch.msgs[int(message)].edits[-1], shooter


async def test_recap_picture_on_the_ended_card(monkeypatch, tmp_path):
    end, shooter = await stream(monkeypatch, tmp_path)
    assert end["embed"].image.url == "attachment://recap.png"
    names = [getattr(a, "filename", "") for a in end["attachments"]]
    assert names == ["host.webp", "recap.png"]                     # the host's face is kept
    doc = shooter.docs[-1]
    assert "Stream Report" in doc and "Lulu" in doc and "Valheim" in doc and "1 h 0 min" in doc
    assert "on file, link below" in doc                            # the VOD is on the card


async def test_recap_switched_off(monkeypatch, tmp_path):
    end, shooter = await stream(monkeypatch, tmp_path, recap_on=False)
    assert "attachments" not in end and not shooter.docs


def test_recap_card_both_hosts():
    hosts.init(None)
    r = {"name": "Lulu <3", "title": "t", "when": "Fri Nov 20 · 7 PM – 8 PM", "length": "5 h 0 min", "length_s": 5 * 3600,
         "played": [{"game": "Valheim", "tag": "", "length": "5 h 0 min"}], "platforms": ["youtube"], "viewers": 12,
         "signoff": "bye", "vod": False, "thumb": "", "avatar": "", "line": "A long one."}
    assert host_cards.recap_pose(r) == "sleepy"
    c = host_cards.recap("colette", r)
    assert "THAT'S A WRAP" in c and "Lulu &lt;3" in c and "coming soon" in c and "YouTube" in c
    k = host_cards.recap("clark", r)
    assert "Stream Report" in k and "pending" in k and "12 peak" in k
    assert host_cards.recap_pose({**r, "length_s": 60, "played": [{"game": "X", "tag": "🆕 NEW GAME", "length": ""}]}) == "pointing"


class FakeDiscord:
    def __init__(self):
        self.sent = []

    async def cal_send(self, channel, data, png, name):
        self.sent.append(name)
        return str(100 + len(self.sent))

    async def cal_edit(self, channel, message, data, png, name):
        return True

    async def dm_owner(self, text, png=None):
        pass


async def test_board_in_the_hosts_look(tmp_path):
    store = Store(":memory:")
    store.add_person("Lulu", "flavr")
    store.put("calendar_channel.flavr", "55")
    store.put("hosts_on", True)
    store.put("hosts_only", "clark")
    shooter = Shooter()
    p = CalendarPoster(store, FakeDiscord(), ImageCache(tmp_path), shooter, clock=lambda: ts(2026, 11, 19, 12))
    await p.tick()                                                 # first post: drawn by this week's host
    assert store.get("calendar_post.flavr")["host"] == "clark"
    assert "FILED BY CLARK" in shooter.docs[-1] and "Eastern" in shooter.docs[-1]
    week = p.build("flavr", p.week_of(0))
    await p.png(week, "colette")
    assert "pinned up by Colette" in shooter.docs[-1]
    store.put("host_board", False)                                 # settings page box unticked: the plain board
    await p.png(week, "clark")
    assert "FILED BY CLARK" not in shooter.docs[-1] and "Eastern" in shooter.docs[-1]
    store.put("host_board", True)
    store.put("hosts_on", False)                                   # hosts off: plain too
    await p.png(week, "clark")
    assert "FILED BY CLARK" not in shooter.docs[-1]
