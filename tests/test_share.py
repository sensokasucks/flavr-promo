"""Copy-ready calendar text (flavrpromo/share.py) and the share DM package (CalendarPoster.share)."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flavrpromo.calendar import Tile, Week
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.share import X_MAX, discord_text, x_len, x_posts
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")
SUN = datetime(2026, 11, 15, tzinfo=TZ)


def week(n_per_day=1, recap=False):
    days = [[] for _ in range(7)]
    for d in range(7):
        for k in range(n_per_day):
            at = SUN.timestamp() + d * 86400 + (19 + k) * 3600
            days[d].append(Tile(kind="past" if recap else "scheduled", name=f"Streamer{d}{k}", at=at,
                                end=at + 7200 if recap else None, title="Game night", url=f"https://youtu.be/v{d}{k}",
                                person_id=d * 10 + k))
    return Week(group="flavr", start=SUN, tz=TZ, now=SUN.timestamp(), recap=recap, days=days, quiet=[])


def test_discord_text_uses_time_stamps_and_quiet_links():
    t = discord_text(week())
    assert t.startswith("🗓️ **This week in FlaVR** · Nov 15 – 21")
    assert "<t:" in t and "](<https://youtu.be/v00>)" in t and len(t) <= 2000
    from flavrpromo.share import discord_parts
    parts = discord_parts(week(n_per_day=12))                   # 84 streams: nothing cut, several messages
    assert len(parts) > 1 and all(len(p) <= 2000 for p in parts)
    assert sum(p.count("✅") + p.count("•") for p in parts) == 84 and "more" not in "".join(parts)
    assert all(not p.startswith("\n") for p in parts)
    assert "hours live" in discord_text(week(recap=True))


def test_x_reply_style_keeps_links_out_of_the_main_post():
    posts = x_posts(week(2), {0: "@lulu"}, "reply", tag_people=True)
    assert len(posts) == 1 + 7                                  # the schedule, then one links post per day
    assert "https://" not in posts[0] and "Nov 15 – 21 · times in EST" in posts[0]
    assert "SUN · NOV 15\n▸ 7 PM · @lulu\n▸ 8 PM · Streamer01\n\nMON · NOV 16" in posts[0]
    assert posts[1] == "🔗 SUN · NOV 15\n\n@lulu · 7 PM\nhttps://youtu.be/v00\n\nStreamer01 · 8 PM\nhttps://youtu.be/v01"


def test_x_one_post_has_everything():
    posts = x_posts(week(3), {}, "one")
    assert len(posts) == 1 and posts[0].count("https://") == 21
    assert "▸ 7 PM · Streamer00\n   https://youtu.be/v00" in posts[0] and "Game night" not in posts[0]
    recap = x_posts(week(1, recap=True), {}, "reply")
    assert recap[0].startswith("📼 FlaVR week in review") and "▸ Streamer00 · 1 stream · 2 h" in recap[0]
    assert recap[1].startswith("🔗 SUN · NOV 15") and "https://youtu.be/v00" in recap[1]     # the VOD itself


def test_x_thread_fits_280():
    posts = x_posts(week(4), {}, "thread")
    assert len(posts) > 1 and all(x_len(p) <= X_MAX for p in posts) and posts[-1].endswith(f"({len(posts)}/{len(posts)})")
    assert x_len("hi https://example.com/very/long/link/indeed") == 3 + 23
    assert x_len("🗓️") >= 2


class FakeDiscord:
    def __init__(self):
        self.sent = []

    async def dm_share(self, messages, png):
        self.sent.append((messages, png))


async def test_share_package_and_default_style():
    store = Store(":memory:")
    pid = store.add_person("Lulu", "flavr")
    store.set_x(pid, "@luluteala")
    d = FakeDiscord()
    poster = CalendarPoster(store, d, None, None, clock=lambda: SUN.timestamp() + 3600)
    w = week()
    w.days[0][0].person_id = pid
    msgs = poster.share_messages(w)
    # the note, 7 Discord days, the X post, 7 links posts
    assert len(msgs) == 16 and msgs[0].startswith("📋") and "one message per day (7" in msgs[0]
    assert msgs[1].startswith("🗓️ **") and msgs[2].startswith("**Mon Nov 16**") and msgs[8].startswith("🗓️ This week")
    assert msgs[9].startswith("🔗 SUN") and "7 links post(s)" in msgs[0]
    assert "@luluteala" not in msgs[8]                                  # nobody tagged by default
    store.put("share_x_tag", True)
    assert "@luluteala" in poster.share_messages(w)[8]
    store.put("share_x_style", "one")
    assert len(poster.share_messages(w)) == 1 + 7 + 1                 # "one": note, 7 Discord days, one X post
    assert len(poster.share_messages(w, "thread")) > 9               # an override beats the default
    # automatic shares wait for quiet hours to end, and only with the switch on
    poster.share_on, poster.quiet = (lambda: True), (lambda: True)
    poster._share_later(w, b"png")
    await poster.flush_shares()
    assert d.sent == []
    poster.quiet = lambda: False
    await poster.flush_shares()
    assert len(d.sent) == 1 and d.sent[0][1] == b"png"


def test_x_bold_days_and_hashtags():
    posts = x_posts(week(1), {}, "reply", bold=True, tags="#FlaVR #vtuber")
    assert "𝗦𝗨𝗡 · 𝗡𝗢𝗩 𝟭𝟱\n▸ 7 PM · Streamer00" in posts[0]
    assert posts[0].endswith("\n\n#FlaVR #vtuber") and "#FlaVR" not in posts[1]
    thread = x_posts(week(4), {}, "thread", tags="#FlaVR")
    assert all(x_len(p) <= X_MAX for p in thread)


def test_x_recap_is_one_line_per_person_with_vods_per_day():
    w = week(2, recap=True)
    for d in w.days:                        # the same two people every day
        for k, t in enumerate(d):
            t.person_id, t.name = k + 1, ["Lulu", "Raimi"][k]
    w.days[0][0].end += 3600                # Lulu streamed one hour longer: listed first
    posts = x_posts(w, {1: "luluteala"}, "reply", channels={1: "https://www.youtube.com/@luluteala"}, tag_people=True)
    assert "▸ @luluteala · 7 streams · 15 h\n▸ Raimi · 7 streams · 14 h" in posts[0]
    # links: each stream's own VOD, one post per day (not the channel page)
    assert len(posts) == 8 and "@luluteala · 7 PM\nhttps://youtu.be/v00" in posts[1]
    assert "youtube.com/@luluteala" not in "".join(posts)
    one = x_posts(w, {}, "one")[0]
    assert one.count("https://") == 14 and one.index("▸ Lulu · 7 streams") < one.index("SUN · NOV 15")


def test_channel_url():
    from flavrpromo.share import channel_url
    assert channel_url({"accounts": [{"platform": "twitch", "handle": "sensoka"}]}) == "https://twitch.tv/sensoka"
    assert channel_url({"main_platform": "", "accounts": [{"platform": "twitch", "handle": "x"},
                        {"platform": "youtube", "handle": "@lulu"}]}) == "https://www.youtube.com/@lulu"
    assert channel_url({"accounts": []}) == ""


def test_pasted_text_tags_nobody():
    w = week(1)
    t = w.days[0][0]
    t.title, t.name = "Red Dragon Inn w/ @zosimustarkas_vt @everyone <@123>", "@weird name"
    texts = [discord_text(w)] + x_posts(w, {t.person_id: "someone"}, "one") + x_posts(w, {}, "reply")
    for text in texts:
        assert re.search(r"@(?!\u200b)", text) is None, text          # every @ is defused
    assert "zosimustarkas_vt" in texts[0]                               # the words stay readable


def test_x_article_has_headings_links_and_no_tags():
    from flavrpromo.share import article
    w = week(2, recap=True)
    w.days[0][0].title = "Game night w/ @everyone <script>"
    a = article(w, {0: "lulu"}, tags="#FlaVR", tag_people=False)
    assert a["title"] == "FlaVR week in review · Nov 15 – 21"
    assert a["html"].count("<h2>") == 1 + 7 and "<h2>Who streamed</h2>" in a["html"]
    assert '<h2>Sunday, November 15</h2>' in a["html"] and '<br><a href="https://youtu.be/v00">' in a["html"] and "Watch the VOD" not in a["html"]
    assert "<script" not in a["html"] and re.search(r"@(?!​)", a["text"]) is None and "#FlaVR" in a["html"]
    assert "@lulu" in article(w, {0: "lulu"}, tag_people=True)["html"]             # only with tag_people on
    assert "<br><a href=" in article(week(1))["html"] and article(week(1))["title"] == "This week in FlaVR · Nov 15 – 21"


def test_article_style_links_the_copy_page():
    store = Store(":memory:")
    poster = CalendarPoster(store, FakeDiscord(), None, None, clock=lambda: SUN.timestamp() + 3600)
    poster.web_url = "http://192.168.0.20:3870"
    msgs = poster.share_messages(week(), "article")
    assert len(msgs) == 1 + 7 + 1 and "X Article" in msgs[0]
    assert "<http://192.168.0.20:3870/calendar/article?group=flavr>" in msgs[-1] and "This week in FlaVR" in msgs[-1]


def test_article_has_one_picture_per_day_above_its_links():
    from flavrpromo.share import article
    from flavrpromo.render import day_card, day_columns
    w = week(3, recap=True)
    w.days[2] = []                                          # a day without streams gets no picture
    a = article(w, save=lambda day: f"/calendar/day.png?day={day}")
    assert [p for p in a["pictures"]] == [(1, "01-sun.png", 0), (2, "02-mon.png", 1), (3, "03-wed.png", 3),
                                          (4, "04-thu.png", 4), (5, "05-fri.png", 5), (6, "06-sat.png", 6)]
    h = a["html"]
    assert h.count("<img") == 6 and h.count('class="nocopy"') == 6
    assert h.index("<h2>Sunday") < h.index("day.png?day=0") < h.index("youtu.be/v00") < h.index("<h2>Monday")
    assert "<img" not in article(w)["html"]                 # no save address: no picture block
    assert [day_columns(n) for n in (1, 2, 4, 5, 9, 10, 16, 17)] == [1, 2, 2, 3, 3, 4, 4, 5]
    doc = day_card(w, 0, lambda u: "")
    assert "SUNDAY · NOV 15" in doc and doc.count('class="c"') == 3


def test_article_cover_is_5_by_2_with_top_streamers_first():
    from flavrpromo.render import COVER_H, COVER_W, cover, cover_people
    assert COVER_W * 2 == COVER_H * 5
    w = week(2, recap=True)
    w.days[3][1].end += 5 * 3600                            # Streamer31 streamed the longest
    people = cover_people(w)
    assert len(people) == 8 and people[0]["tile"].name == "Streamer31"
    assert people[0]["hours"] > people[1]["hours"]
    doc = cover(w, lambda u: "", "")
    assert doc.count("<em>") == 8 and " stream" in doc
    assert "WEEK IN REVIEW" in doc and "Nov 15 – 21" in doc and doc.count('class="p"') == 8


def test_cover_stats_line():
    from flavrpromo.render import cover_stats
    assert cover_stats({"hours": 24.4, "streams": 6}, True) == "24h · 6 streams"
    assert cover_stats({"hours": 2.5, "streams": 1}, True) == "2.5h · 1 stream"
    assert cover_stats({"hours": 0, "streams": 3}, False) == "3 planned"


def test_article_titles_and_lengths_read_clean():
    from flavrpromo.share import _article_title, _hm
    assert _article_title("Weeb Night with @batsharkvt") == "Weeb Night with batsharkvt"
    assert _article_title("This Time Dark Sawrm #vtuber #flavr") == "This Time Dark Sawrm"
    assert _article_title("@here") == "here" and "@" not in _article_title("mail a@b")
    assert _hm(5 * 3600) == "5h" and _hm(6840) == "1h\u00a054m" and _hm(2400) == "40m"


def test_day_picture_tiles_keep_the_thumbnail_shape():
    # render.tile_layout: tiles are always 16:9 (the stream thumbnail's shape, so nothing is cropped),
    # as big as fits in the 1520 x 750 area under the heading, with their name lines under them
    from flavrpromo.render import GRID_GAP_X, GRID_GAP_Y, GRID_H, GRID_W, tile_layout
    for n in range(1, 21):
        cols, rows, w, label = tile_layout(n)
        assert cols * rows >= n and w > 100
        assert cols * w + (cols - 1) * GRID_GAP_X <= GRID_W                                   # fits across
        assert rows * (w * 9 / 16 + 2 * label + 12) + (rows - 1) * GRID_GAP_Y <= GRID_H + 1  # fits down
    assert tile_layout(4)[:2] == (2, 2) and tile_layout(1)[:2] == (1, 1)
