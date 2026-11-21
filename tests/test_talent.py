"""Talent channels (flavrpromo/talent.py): where go-live cards go, the week card and recap. No Discord."""

from flavrpromo import talent
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.render import ImageCache

from test_calendar import FakeDiscord, setup, ts


class PinDiscord(FakeDiscord):
    def __init__(self):
        super().__init__()
        self.pins = []

    async def cal_pin(self, channel, message, on):
        self.pins.append((channel, message, on))


def test_go_live_goes_to_group_and_own_channel_unless_switched_off():
    store, lulu, pip, sen = setup()
    store.put("live_channel.flavr", "10")
    p = store.person("Lulu")
    assert talent.live_channels(store, p) == ["10"]                      # no own channel yet
    store.set_talent(lulu, talent_channel="20")
    p = store.person("Lulu")
    assert talent.live_channels(store, p) == ["10", "20"]                # both by default
    store.set_talent(lulu, live_group=0)
    assert talent.live_channels(store, store.person("Lulu")) == ["20"]   # opted out of the group channel
    store.set_talent(lulu, live_group=1, live_own=0)
    assert talent.live_channels(store, store.person("Lulu")) == ["10"]
    store.set_talent(lulu, live_own=1, talent_channel="10")              # same channel twice counts once
    assert talent.live_channels(store, store.person("Lulu")) == ["10"]


def test_channel_and_account_lookups():
    store, lulu, pip, sen = setup()
    store.set_talent(lulu, talent_channel="20", discord_user="777")
    assert talent.person_for_channel(store, 20)["name"] == "Lulu"
    assert talent.person_for_channel(store, 21) is None and talent.person_for_channel(store, None) is None
    assert talent.person_for_user(store, 777)["name"] == "Lulu" and talent.person_for_user(store, 1) is None


async def test_week_card_posts_pins_edits_and_recaps(tmp_path):
    store, lulu, pip, sen = setup()
    clock = {"t": ts(2026, 11, 17, 12)}                                  # Tuesday noon
    d = PinDiscord()
    p = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: clock["t"])
    store.add_manual(lulu, 4, 19 * 60, "Thu stream")                    # Thursday 7 PM
    store.add_manual(sen, 3, 20 * 60, "Wed stream")
    await p.tick()
    assert d.sent == []                                                  # nobody has a channel yet
    store.set_talent(lulu, talent_channel="20")
    await p.tick()
    assert d.sent == [("20", "🗓️ Lulu · this week · Nov 15 – 21", "")]
    assert d.pins == [("20", "101", True)]
    await p.tick()
    assert len(d.sent) == 1 and d.edits == []                            # nothing changed: no edit
    # she streams on Tuesday: her card is edited in place
    s = store.start_session(lulu, ts(2026, 11, 17, 13), platforms=["youtube"], title="Cozy", url="https://youtu.be/x")
    store.update_session(s, ended_at=ts(2026, 11, 17, 15, 30), vod_url="https://youtu.be/x")
    clock["t"] = ts(2026, 11, 17, 16)
    await p.tick()
    assert d.edits == [("101", "🗓️ Lulu · this week · Nov 15 – 21")]
    # only her streams are on it
    week = talent.only(p.build("flavr", p.week_of(0)), lulu)
    card = talent.week_card(week, "Lulu")
    assert all("Sensoka" not in v for _, v in card["fields"]) and any("Thu stream" in v for _, v in card["fields"])
    # Friday 10 AM: her week review (Mon-Thu), once
    clock["t"] = ts(2026, 11, 20, 10, 5)
    await p.tick()
    await p.tick()
    recaps = [x for x in d.sent if "week in review" in x[1]]
    assert recaps == [("20", "📼 Lulu · week in review · Nov 16 – 19", "")]
    rc = talent.week_card(talent.only(p.build("flavr", p.week_of(0), recap=True), lulu), "Lulu")
    assert rc["footer"] == "1 stream · 2.5h live · longest: Cozy"
    # Sunday 10 AM: a new card for the new week, pinned; last week's unpinned
    clock["t"] = ts(2026, 11, 22, 10, 1)
    await p.tick()
    assert d.sent[-1][1].startswith("🗓️ Lulu · this week · Nov 22")
    assert ("20", "101", False) in d.pins and d.pins[-1][2] is True
