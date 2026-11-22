"""Owner DMs (flavrpromo/pings.py): switches, quiet hours, friends batching. The Stream Core pings
(raids, tips, stream started, Core lost) stayed in FlaVR Bot when the bots were split (2026-11-20)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from flavrpromo.pings import KINDS, Pinger
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")


def at(hour):
    return datetime(2026, 11, 17, hour, 30, tzinfo=TZ).timestamp()


def make(hour=14, live=False):
    sent = []
    clock = {"t": at(hour)}

    async def send(text):
        sent.append(text)

    p = Pinger(Store(":memory:"), send, quiet=(3, 11), live=lambda: live, clock=lambda: clock["t"])
    return p, sent, clock


def test_only_the_calendar_kinds():
    assert sorted(KINDS) == ["calendar", "collab", "friends", "share"]


async def test_switches_and_quiet_hours_hold():
    p, sent, clock = make(hour=4)
    assert p.quiet_now()
    await p.ping("calendar", "New week posted")
    assert sent == []                          # held until quiet hours end
    clock["t"] = at(11)
    await p.flush()
    assert sent[0].startswith("While you were away") and "New week posted" in sent[0]
    p.set("calendar", False)
    await p.ping("calendar", "another")
    assert len(sent) == 1


async def test_quiet_hours_off_while_live():
    p, sent, _ = make(hour=4, live=True)
    assert not p.quiet_now()


async def test_friends_batched():
    p, sent, clock = make()
    p.friend_live("Lulu", "YouTube")          # off by default
    assert p._friends == []
    p.set("friends", True)
    p.friend_live("Lulu", "YouTube")
    p.friend_live("Raimi", "Twitch")
    await p.flush()
    assert sent == ["🟣 Live now: Lulu (YouTube), Raimi (Twitch)"]
    p.friend_live("Choco", "Kick")
    await p.flush()                           # within 10 minutes: waits
    assert len(sent) == 1
    clock["t"] += 601
    await p.flush()
    assert sent[-1] == "🟣 Live now: Choco (Kick)"


def test_quiet_hours_wrap_and_saved():
    p, _, clock = make(hour=23)
    p.set_quiet(22, 6)
    assert p.quiet_now()
    clock["t"] = at(7)
    assert not p.quiet_now()
    p2 = Pinger(p.store, None)
    p2.load_quiet()
    assert p2.quiet == (22, 6)
