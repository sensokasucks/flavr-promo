"""flavrpromo/games.py: which game, the games of one stream, and the NEW GAME / PART n / STAPLE /
BACK AGAIN tags; plus the watcher wiring (flavrpromo/watcher.py) and the cards (flavrpromo/bot.py)."""

from flavrpromo import games
from flavrpromo.store import Store
from flavrpromo.watcher import RESTART_GRACE

DAY = 86400.0


def past(store, pid, game, at, length=3600.0):
    """A finished stream from before games were tracked (sessions.game only, like FlaVR Bot's data)."""
    return store.start_session(pid, at, ended_at=at + length, last_seen=at + length, game=game)


def test_title_matching():
    known = ["Schedule I", "Valheim", "Factorio", "It"]
    assert games.from_title("Valheim w/ friends - day 3!", known) == "Valheim"
    assert games.from_title("SCHEDULE I: co-op chaos", known) == "Schedule I"
    assert games.from_title("Just hanging out", known) == ""
    assert games.from_title("Is it raining?", known) == ""          # "It" is too short to trust
    assert games.from_title("Valheimish", known) == ""               # whole words only


def test_tags_new_part_staple_back():
    store = Store(":memory:")
    pid = store.add_person("Lulu", "flavr")
    t0 = 100 * DAY
    assert games.tag(store, pid, "Valheim", t0) == "new"
    assert games.tag(store, pid, "Just Chatting", t0) == ""          # not a game: no tag
    for i in range(3):
        past(store, pid, "Valheim", t0 + i * DAY)
    assert games.tag(store, pid, "Valheim", t0 + 5 * DAY) == "part:4"
    assert games.label("part:4") == "📖 PART 4" and games.label("new") == "🆕 NEW GAME"
    assert games.tag(store, pid, "valheim", t0 + 80 * DAY) == "back"  # case doesn't count; 2+ months away
    # a staple: 6+ streams over 60+ days
    for i in range(6):
        past(store, pid, "Factorio", t0 + i * 15 * DAY)
    assert games.tag(store, pid, "Factorio", t0 + 90 * DAY) == "staple"


async def test_watcher_segments_and_cards():
    from flavrpromo import config, groups
    from flavrpromo.bot import PromoBot
    from flavrpromo.pings import Pinger
    from tests.test_watcher import live, setup

    store, ch, clock, w, log = setup()
    lulu = store.person("Lulu")["id"]
    past(store, lulu, "Valheim", 1_000.0)
    # Twitch says Valheim; YouTube (no category) alone wouldn't know
    ch["twitch"].now = {"luluteala": {**live(), "game": "Valheim"}}
    await w.check("twitch")
    sid = store.open_session(lulu)["id"]
    assert [(s["game"], s["tag"]) for s in store.segments(sid)] == [("Valheim", "part:2")]
    # same game on the next check: nothing new, no card edit
    await w.check("twitch")
    assert [x[0] for x in log] == ["start"]
    # switches to a new game mid-stream: a second segment and a card edit
    clock["t"] += 3600
    ch["twitch"].now = {"luluteala": {**live(), "game": "Schedule I"}}
    await w.check("twitch")
    segs = store.segments(sid)
    assert [(s["game"], s["tag"]) for s in segs] == [("Valheim", "part:2"), ("Schedule I", "new")]
    assert segs[0]["ended_at"] == clock["t"] and log[-1][0] == "change"

    # the live card: Playing with its tag, Earlier with the first game
    groups.init(store)
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None), w)
    person = store.person("Lulu")
    e = bot.live_embed(person, store.open_session(lulu), w.live_on(person))
    fields = {f.name: f.value for f in e.fields}
    assert fields["Playing"] == "Schedule I · 🆕 NEW GAME" and fields["Earlier"] == "Valheim 1 h 1 min"   # from the platform's start time

    # the stream ends: the last game closes; the "was live" card lists every game in order
    ch["twitch"].now = {}
    clock["t"] += RESTART_GRACE + 1
    await w.check("twitch")
    ch["youtube"].now = {}
    await w.check("youtube")
    ended = store.last_session(lulu)
    assert ended["ended_at"] is not None and all(s["ended_at"] for s in store.segments(sid))
    edits = []

    class Msg:
        embeds = [e]

        async def edit(self, **kw):
            edits.append(kw)

    async def messages(session):
        return [Msg()]
    bot._messages = messages
    await bot.post_end(person, ended)
    out = {f.name: f.value for f in edits[0]["embed"].fields}
    assert "Playing" not in out and "Earlier" not in out
    assert out["Played"].startswith("Valheim (📖 PART 2) 1 h 1 min → Schedule I (🆕 NEW GAME)")
    await bot.close()


async def test_youtube_title_finds_a_known_game():
    from tests.test_watcher import live, setup
    store, ch, clock, w, log = setup()
    lulu = store.person("Lulu")["id"]
    past(store, lulu, "Valheim", 1_000.0)
    ch["youtube"].now = {"luluteala": live(title="VALHEIM day 3 | building a boat")}
    await w.check("youtube")
    s = store.open_session(lulu)
    assert s["game"] == "Valheim" and store.segments(s["id"])[0]["tag"] == "part:2"
    assert games.history(store, lulu)[0] == {"game": "Valheim", "streams": 2, "last": s["started_at"]}
