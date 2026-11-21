"""The Sunday preview with a host (flavrpromo/host_picker.py label "preview", calendar_post.py
``_preview_host``; owner 2026-11-21): the new week's board waits for the owner's picks, then the host's
week-ahead opener card goes out before it; after the wait limit (kv host_preview_wait) the board posts
on its own. Also the week-ahead facts, lines, notes and KoboldCpp's facts sentence."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from flavrpromo import host_cards, host_picker, hosts, kobold
from flavrpromo.calendar import build_week
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.render import ImageCache
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


class FakeDiscord:
    def __init__(self):
        self.sent, self.dms, self.edits = [], [], []

    async def cal_send(self, channel, data, png, name):
        self.sent.append((channel, data["title"], name, data.get("description", "")))
        return str(100 + len(self.sent))

    async def cal_edit(self, channel, message, data, png, name):
        self.edits.append(name)
        return True

    async def dm_owner(self, text, png=None):
        self.dms.append(text)


def world(tmp_path, clock):
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    sen = store.add_person("Sensoka", "flavr", is_owner=True)
    store.add_manual(lulu, 1, 20 * 60)              # Monday 8 PM, every week
    store.add_manual(lulu, 5, 19 * 60)              # Friday 7 PM
    store.add_manual(sen, 5, 21 * 60)               # Friday 9 PM
    store.put("calendar_channel.flavr", "55")
    store.put("calendar_post.flavr", {"week": "2026-11-15", "channel": "55", "message": "9", "sig": "x", "drawn_at": 0})
    store.put("hosts_on", True)
    store.put("hosts_only", "colette")
    d = FakeDiscord()
    p = CalendarPoster(store, d, ImageCache(tmp_path), None, clock=lambda: clock["t"])
    p.web_url = "http://pc:3871"
    return store, d, p


def boards(d):
    return [s for s in d.sent if s[2].startswith("calendar-2026-11-22")]


async def test_sunday_board_waits_for_the_host_then_opener_first(tmp_path):
    clock = {"t": ts(2026, 11, 22, 10, 5)}          # Sunday 10:05 AM: the new week is due
    store, d, p = world(tmp_path, clock)
    await p.tick()
    assert not boards(d) and d.edits                # waiting; last week's post still edited
    assert len(d.dms) == 1 and "FlaVR week ahead" in d.dms[0] and "/hosts/pick" in d.dms[0]
    key = host_picker.key_of("preview", "flavr")
    pend = store.get(key)
    f = pend["facts"]
    assert (f["planned"], f["people"], f["busy_day"], f["first_name"], f["first_day"], f["first_time"]) == \
        (3, 2, "Friday", "Lulu", "Monday", "8 PM")
    assert [n["label"] for n in pend["notes"]] == ["FIRST UP", "BUSIEST DAY", "MOST PLANNED"]
    assert set(pend["candidates"]) == {"opener", "note0", "note1", "note2"}    # no desk card
    assert all("{" not in x for c in pend["candidates"].values() for x in c)

    app = web.Application()
    host_picker.add_routes(app, p)
    async with TestClient(TestServer(app)) as client:
        page = await (await client.get("/hosts/pick")).text()
        assert "FlaVR week ahead" in page and "desk picture" not in page and "card=desk" not in page
        r = await client.post("/hosts/pick", data={"key": key, "action": "swap"}, allow_redirects=False)
        assert r.status == 303 and store.get(key)["host"] == "clark"
        assert set(store.get(key)["candidates"]) == {"opener", "note0", "note1", "note2"}
        r = await client.post("/hosts/pick", data={"key": key, "action": "post", "opener": "__custom",
                                                   "opener__text": "A fine week ahead."}, allow_redirects=False)
        assert "opener,%20then%20the%20board" in r.headers["Location"]
    before = len(d.sent)
    await p.tick()
    out = d.sent[before:]
    assert [s[2] for s in out] == ["clark-opener-2026-11-22.png", "calendar-2026-11-22.png"]
    assert out[0][3] == "A fine week ahead." and "Week Ahead" in out[0][1]
    assert store.get(key) is None and host_picker.waiting(store) == []
    await p.tick()
    assert len(d.sent) == before + 2                # once


async def test_board_posts_without_host_after_the_wait(tmp_path):
    clock = {"t": ts(2026, 11, 22, 10, 5)}
    store, d, p = world(tmp_path, clock)
    store.put("host_preview_wait", 1.5)
    await p.tick()
    clock["t"] += 80 * 60
    await p.tick()
    assert not boards(d) and "still waiting" in d.dms[-1]
    clock["t"] += 11 * 60                           # 91 minutes: past 1.5 h
    await p.tick()
    assert [s[2] for s in d.sent] == ["calendar-2026-11-22.png"]
    assert "without the host" in d.dms[-1]
    assert store.get(host_picker.key_of("preview", "flavr")) is None
    store.put("host_preview_wait", 0)
    assert host_picker.preview_wait(store) == 0     # 0 = wait for ever


def test_preview_lines_card_and_kobold_facts():
    store = Store(":memory:")
    empty = build_week(store, "flavr", datetime(2026, 11, 22, tzinfo=TZ), ts(2026, 11, 22, 10), TZ)
    f = hosts.preview_facts(empty)
    assert f["planned"] == 0 and hosts.preview_mood(f) == "empty" and hosts.preview_notes(f) == []
    c = hosts.preview_candidates("clark", f)
    assert c["opener"] and set(c) == {"opener"}
    assert "0 streams planned" in kobold.facts_text(f)
    full = {"preview": True, "planned": 7, "planned_text": "7 streams", "people": 3, "busy_day": "Friday",
            "busy_count": 3, "first_name": "Lulu", "first_day": "Monday", "first_time": "8 PM"}
    assert hosts.preview_mood(full) == "busy"
    text = kobold.facts_text(full)
    assert "first up Lulu on Monday at 8 PM" in text and "busiest day Friday" in text
    html = host_cards.opener("clark", "Week Ahead", "Nov 22 - 28", "Line.", [], [], "pointing", preview=True)
    assert "SCHEDULE" in html and "board follows" in html
    assert "This week" in host_cards.opener("colette", "Week Ahead", "r", "Line.", [], [], "pointing", preview=True)
