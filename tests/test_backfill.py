"""Filling in weeks the bot wasn't watching (Watcher.backfill, CalendarPoster.ensure_backfill) and
the platform parsers behind it (Twitch past broadcasts, YouTube uploads + real start / end times)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from flavrpromo.calendar import build_week
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.platforms.twitch import Twitch, duration_sec
from flavrpromo.platforms.youtube import DEEP_CHECK, YouTube
from flavrpromo.store import Store
from flavrpromo.watcher import Watcher

TZ = ZoneInfo("America/New_York")
SUN = datetime(2026, 11, 8, tzinfo=TZ)          # Nov 8-14, the empty week in review
A = SUN.timestamp()
NOW = A + 9 * 86400                              # Tuesday of the next week


class Past:
    ready = True

    def __init__(self, rows):
        self.rows = rows                         # platform_id → [{started_at, ended_at, title, url, thumb}]
        self.asked = 0

    async def past_streams(self, pid, since, until):
        self.asked += 1
        return [r for r in self.rows.get(pid, []) if since <= r["started_at"] < until]


def vod(start_h, hours, url, title="Stream"):
    s = A + start_h * 3600
    return {"started_at": s, "ended_at": s + hours * 3600, "title": title, "url": url, "thumb": url + ".jpg"}


def world(yt_rows, tw_rows):
    store = Store(":memory:")
    amanda = store.add_person("Amanda", "flavr")
    store.add_account(amanda, "youtube", "@amanda")
    store.add_account(amanda, "twitch", "amanda")
    for a in store.people()[0]["accounts"]:
        store.set_account_info(a["id"], "UCamanda" if a["platform"] == "youtube" else "111")
    ch = {"youtube": Past({"UCamanda": yt_rows}), "twitch": Past({"111": tw_rows})}
    return store, ch, Watcher(store, ch, {}, clock=lambda: NOW)


async def test_backfill_fills_an_empty_week_and_merges_multistreams():
    store, ch, w = world([vod(20, 3, "yt1"), vod(72, 2, "yt2")], [vod(20.2, 3.1, "tw1")])
    assert await w.backfill(A, A + 7 * 86400, everyone=True) == 2
    week = build_week(store, "flavr", SUN, NOW, TZ, recap=True)
    tiles = week.tiles()
    assert len(tiles) == 2
    first = tiles[0]
    assert first.kind == "past" and sorted(first.platforms) == ["twitch", "youtube"]
    assert first.url == "yt1"                    # main platform YouTube leads
    assert first.end == A + 23.3 * 3600         # the later of the two ends (Twitch 20.2 h + 3.1 h)
    assert not first.late                        # filled-in streams never get LATE NOTICE
    # a second run adds nothing (it overlaps what is now saved)
    assert await w.backfill(A, A + 7 * 86400, everyone=True) == 0


async def test_youtube_is_only_asked_about_active_people_once_per_activity():
    # owner 2026-11-20: free checks flag who did something; YouTube's costly list only for them, once
    store, ch, w = world([vod(20, 3, "yt1")], [vod(50, 2, "tw1")])
    pid = store.people()[0]["id"]
    assert await w.backfill(A, A + 7 * 86400) == 1            # Twitch (free) still asked; YouTube not
    assert ch["youtube"].asked == 0 and ch["twitch"].asked == 1
    store.note_activity(pid, [A + 20 * 3600], now=NOW)        # the RSS feed showed a video those days
    assert await w.backfill(A, A + 7 * 86400) == 1 and ch["youtube"].asked == 1
    await w.backfill(A, A + 7 * 86400)                         # nothing new since: not asked again
    assert ch["youtube"].asked == 1
    store.note_activity(pid, [NOW - 3600], now=NOW)           # outside those days: still not due
    await w.backfill(A, A + 7 * 86400)
    assert ch["youtube"].asked == 1
    await w.backfill(A, A + 7 * 86400, everyone=True)          # /calendar refresh: everyone
    assert ch["youtube"].asked == 2


async def test_backfill_skips_what_the_watcher_saw_and_streams_still_running():
    store, ch, w = world([vod(20, 3, "yt1")], [])
    pid = store.people()[0]["id"]
    store.start_session(pid, A + 20.1 * 3600, ended_at=A + 23 * 3600, title="seen live")
    # ended 5 minutes ago: may still be live, the watcher owns it
    ch["youtube"].rows["UCamanda"].append({"started_at": NOW - 3600, "ended_at": NOW - 300, "title": "now",
                                           "url": "yt9", "thumb": ""})
    assert await w.backfill(A, NOW, everyone=True) == 0
    assert [s["title"] for s in store.sessions_between(A, NOW)] == ["seen live"]


async def test_ensure_backfill_runs_once_per_finished_week():
    store, ch, w = world([vod(20, 3, "yt1")], [])
    poster = CalendarPoster(store, None, None, None, clock=lambda: NOW, backfill=w.backfill)
    store.note_activity(store.people()[0]["id"], [A + 20 * 3600], now=NOW)     # active that week
    assert await poster.ensure_backfill(SUN) == 1
    asked = ch["youtube"].asked
    assert await poster.ensure_backfill(SUN) == 0 and ch["youtube"].asked == asked     # not asked again
    await poster.ensure_backfill(SUN, force=True)                     # before a review: nothing new, no quota
    assert ch["youtube"].asked == asked
    await poster.ensure_backfill(SUN, force=True, everyone=True)      # /calendar refresh
    assert ch["youtube"].asked == asked + 1


def test_twitch_duration():
    assert duration_sec("3h2m1s") == 3 * 3600 + 121
    assert duration_sec("45m") == 2700 and duration_sec("12s") == 12 and duration_sec("") == 0


class FakeHttp:
    """Answers aiohttp-style GETs from a list of (path piece, json) pairs."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        body = next(j for piece, j in self.answers if piece in url)

        class R:
            status = 200

            async def json(self, content_type=None):
                return body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False
        return R()


async def test_twitch_past_streams_parses_archive():
    http = FakeHttp([("/videos", {"data": [
        {"created_at": "2026-11-09T01:00:00Z", "duration": "2h30m0s", "title": "Hi", "url": "https://twitch.tv/videos/1",
         "thumbnail_url": "https://x/%{width}x%{height}.jpg"},
        {"created_at": "2026-10-01T01:00:00Z", "duration": "1h", "title": "old", "url": "o", "thumbnail_url": ""}]})])
    t = Twitch(http, "id", "secret")
    t._token, t._token_until = "tok", 1e12
    rows = await t.past_streams("111", A, A + 7 * 86400)
    assert len(rows) == 1 and rows[0]["ended_at"] - rows[0]["started_at"] == 9000
    assert rows[0]["thumb"] == "https://x/640x360.jpg"


async def test_youtube_past_streams_uses_real_start_and_end():
    http = FakeHttp([("/playlistItems", {"items": [{"contentDetails": {"videoId": "a", "videoPublishedAt": "2026-11-09T01:00:00Z"}},
                                                   {"contentDetails": {"videoId": "b", "videoPublishedAt": "2026-11-10T01:00:00Z"}}]}),
                     ("/videos", {"items": [
                         {"id": "a", "snippet": {"title": "Stream"}, "liveStreamingDetails": {
                             "actualStartTime": "2026-11-09T01:00:00Z", "actualEndTime": "2026-11-09T04:00:00Z"}},
                         {"id": "b", "snippet": {"title": "Upload"}}]})])
    y = YouTube(http, "key")
    rows = await y.past_streams("UC" + "x" * 22, A, A + 7 * 86400)
    assert [r["url"] for r in rows] == ["https://www.youtube.com/watch?v=a"]
    assert rows[0]["ended_at"] - rows[0]["started_at"] == 3 * 3600
    assert http.calls[0][1]["playlistId"] == "UU" + "x" * 22


async def test_youtube_finds_waiting_rooms_gone_from_the_feed():
    # Amanda's case (2026-11-20): a waiting room made a month ahead fell out of the 15-video RSS feed.
    # The deep check (here: daily) finds it; after that it's asked about directly until it starts.
    cid = "UC" + "a" * 22
    upcoming = {"items": [{"id": "w", "snippet": {"title": "Folk Blues", "liveBroadcastContent": "upcoming"},
                           "liveStreamingDetails": {"scheduledStartTime": "2026-11-22T12:00:00Z"}}]}
    http = FakeHttp([("/search", {"items": [{"id": {"videoId": "w"}}]}), ("/videos", upcoming),
                     ("/playlistItems", {"items": []})])     # 50+ newer videos: not in the uploads list either
    y = YouTube(http, "key")
    y.search_every = DEEP_CHECK["daily"]

    async def empty_feed(channel_id):
        return []                                   # the waiting room isn't among the 15 newest

    y.feed = empty_feed
    await y.live([{"platform_id": cid}])
    assert [u["title"] for u in y.upcoming[cid]] == ["Folk Blues"]
    await y.live([{"platform_id": cid}])            # no second search within a day, still found
    assert sum(1 for url, _ in http.calls if "/search" in url) == 1
    assert [u["video_id"] for u in y.upcoming[cid]] == ["w"]
    # it starts: live, and no longer kept as a waiting room
    http.answers[1] = ("/videos", {"items": [{"id": "w", "snippet": {"title": "Folk Blues", "liveBroadcastContent": "live"},
                                              "liveStreamingDetails": {"actualStartTime": "2026-11-22T12:01:00Z"}}]})
    out = await y.live([{"platform_id": cid}])
    assert out[cid]["video_id"] == "w" and y._upcoming_ids == {}


async def test_youtube_uploads_list_finds_old_waiting_rooms_and_deep_check_is_off_by_default():
    # The cheap safety net: the 50 newest uploads every UPLOADS_EVERY (1 quota unit). No search.list
    # (100 units) unless the owner turns the deep check on (/setup youtube-check).
    cid = "UC" + "b" * 22
    upcoming = {"items": [{"id": "w2", "snippet": {"title": "Premiere night", "liveBroadcastContent": "upcoming"},
                           "liveStreamingDetails": {"scheduledStartTime": "2026-11-22T12:00:00Z"}},
                          {"id": "up", "snippet": {"title": "A short", "liveBroadcastContent": "none"}}]}
    http = FakeHttp([("/playlistItems", {"items": [{"contentDetails": {"videoId": "w2"}},
                                                   {"contentDetails": {"videoId": "up"}}]}),
                     ("/videos", upcoming), ("/search", {"items": []})])
    y = YouTube(http, "key")
    assert y.search_every == 0

    async def empty_feed(channel_id):
        return []

    y.feed = empty_feed
    await y.live([{"platform_id": cid}])
    assert [u["video_id"] for u in y.upcoming[cid]] == ["w2"] and "up" in y._done
    await y.live([{"platform_id": cid}])            # the uploads list again only after UPLOADS_EVERY
    assert sum(1 for url, _ in http.calls if "/playlistItems" in url) == 1
    assert not any("/search" in url for url, _ in http.calls)
