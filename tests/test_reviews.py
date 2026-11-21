"""The Friday / Monday reviews (owner 2026-11-20): which days each covers (calendar.review_range),
the review board with its "Also this week" uploads (calendar.build_week label, store uploads), the
share text / X Article with them, how YouTube videos are sorted into Short / video / premiere
(platforms/youtube.upload_info), and the free feed reads feeding the activity flag (store.note_activity)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from flavrpromo import share
from flavrpromo.calendar import UPLOADS_HEAD, build_week, review_range
from flavrpromo.calendar_post import embed
from flavrpromo.platforms.youtube import upload_info
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_review_ranges():
    # Friday Nov 20 2026: the week review is Mon Nov 16 - Thu Nov 19
    assert review_range("week", ts(2026, 11, 20, 10), TZ) == (datetime(2026, 11, 16, tzinfo=TZ), 4)
    # Monday Nov 23: the weekend review is Fri Nov 20 - Sun Nov 22 (across the Sunday board change)
    assert review_range("weekend", ts(2026, 11, 23, 10), TZ) == (datetime(2026, 11, 20, tzinfo=TZ), 3)
    # asked mid-week (/calendar view review): the newest one that has started
    assert review_range("weekend", ts(2026, 11, 25, 12), TZ)[0] == datetime(2026, 11, 20, tzinfo=TZ)
    assert review_range("week", ts(2026, 11, 18, 12), TZ)[0] == datetime(2026, 11, 16, tzinfo=TZ)


def world():
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    pip = store.add_person("Pippa", "friends")
    store.start_session(lulu, ts(2026, 11, 21, 19), ended_at=ts(2026, 11, 21, 22), platforms=["youtube"],
                        title="Saturday cozy", url="https://youtu.be/s")
    store.add_upload(lulu, "youtube", "sh1", "short", ts(2026, 11, 22, 12), "Funny bit", "https://www.youtube.com/shorts/sh1")
    store.add_upload(lulu, "youtube", "old", "video", ts(2026, 11, 18, 12), "Midweek video", "https://youtu.be/old")
    store.add_upload(pip, "youtube", "p1", "video", ts(2026, 11, 21, 12), "Not FlaVR", "https://youtu.be/p1")
    return store, lulu, pip


def test_weekend_review_board_with_uploads():
    store, lulu, pip = world()
    start, n = review_range("weekend", ts(2026, 11, 23, 10), TZ)
    week = build_week(store, "flavr", start, ts(2026, 11, 23, 10), TZ, recap=True, days=n, label="weekend")
    assert len(week.days) == 3 and week.day_name(0) == "FRI"
    assert [t.title for t in week.tiles()] == ["Saturday cozy"]
    assert [u["video_id"] for u in week.uploads] == ["sh1"]       # only FlaVR's, only Fri-Sun
    e = embed(week)
    assert e["title"].startswith("FlaVR weekend in review · Nov 20")
    assert e["fields"][-1][0] == UPLOADS_HEAD and "Funny bit" in e["fields"][-1][1]
    text = share.discord_text(week)
    assert "weekend in review" in text and UPLOADS_HEAD in text and "shorts/sh1" in text
    art = share.article(week)
    assert UPLOADS_HEAD in art["html"] and "Funny bit" in art["html"] and "Short" in art["text"]


def video(vid, *, w=640, h=360, dur="PT5M", live=None, state="none", published="2026-11-20T15:00:00Z"):
    v = {"id": vid, "snippet": {"title": vid, "publishedAt": published, "liveBroadcastContent": state},
         "contentDetails": {"duration": dur}, "player": {"embedWidth": str(w), "embedHeight": str(h)}}
    if live is not None:
        v["liveStreamingDetails"] = live
    return v


def test_upload_kinds():
    now = ts(2026, 11, 20, 12)
    assert upload_info(video("a"), now)["kind"] == "video"
    short = upload_info(video("b", w=360, h=640, dur="PT45S"), now)
    assert short["kind"] == "short" and short["url"].endswith("/shorts/b")
    assert upload_info(video("c", w=360, h=640, dur="PT10M"), now)["kind"] == "video"   # vertical but long
    prem = upload_info(video("d", dur="PT20M", state="upcoming",
                             live={"scheduledStartTime": "2026-11-21T20:00:00Z"}), now)
    assert prem["kind"] == "premiere"
    # a waiting live stream (no length) and a finished stream are not uploads
    assert upload_info(video("e", dur="P0D", state="upcoming", live={"scheduledStartTime": "2026-11-21T20:00:00Z"}), now) is None
    assert upload_info(video("f", live={"actualStartTime": "2026-11-19T20:00:00Z"}), now) is None
    assert upload_info(video("g", published="2026-10-01T15:00:00Z"), now) is None        # too old


def test_activity_flag():
    store, lulu, pip = world()
    now = ts(2026, 11, 23, 10)
    a, b = ts(2026, 11, 20), ts(2026, 11, 23)
    assert store.last_activity(pip, a, b) == ts(2026, 11, 21, 12)          # her upload
    assert store.last_activity(lulu, ts(2026, 11, 16), ts(2026, 11, 18)) == 0
    store.note_activity(lulu, [ts(2026, 11, 17, 9), ts(2026, 10, 1)], now=now)   # the October one is dropped
    assert store.last_activity(lulu, ts(2026, 11, 16), ts(2026, 11, 18)) == ts(2026, 11, 17, 9)
    assert store.get("activity")[str(lulu)] == [ts(2026, 11, 17, 9)]
