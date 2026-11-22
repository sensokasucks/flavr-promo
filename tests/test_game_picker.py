"""A stream's game set by hand and the hosts' game talk (owner 2026-11-22): the tall picture builder's game
box (type it, or search IGDB and pick; flavrpromo/tall_page.py, gameinfo.py ``search``, games.py
``set_stream``), a remark about the game itself with a few words of the owner's worked in
(flavrpromo/recipes.py ``ask_kind`` / ``chunk_facts``), and remarks without stray marks in front
(flavrpromo/kobold.py ``tidy``). A fake IGDB and a fake model; no network."""

import time

from flavrpromo import article_editor, gameinfo, games, hosts, kobold, recipes, tall_page
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.render import ImageCache
from flavrpromo.store import Store

from test_hosts import FakeDiscord, ts, world
from test_recipes import FakeKobold
from test_settings_round2 import _client, _poster
from test_youtube_games import SearchTwitch

TITLE = "~ We Steal From Old People Brick by Brick! ~ #flavr #vtuber"
BRICK = {"name": "Brick by Brick", "summary": "Rob a retirement home, one brick at a time. " * 8,
         "genres": [{"name": "Simulator"}, {"name": "Indie"}], "themes": [{"name": "Comedy"}],
         "game_modes": [{"name": "Co-operative"}], "first_release_date": 1735689600,
         "involved_companies": [{"company": {"name": "Big Publisher"}, "developer": False},
                                {"company": {"name": "Tiny Studio"}, "developer": True}],
         "url": "https://igdb/brick"}


def test_remarks_lose_the_stray_marks_in_front():
    # what the owner's model wrote (2026-11-22): a "]" inside the line's quotes, an item of only dots
    assert kobold.as_line('"]BREAKING NEWS: Pure chaos has hit the Discord!"]') == "BREAKING NEWS: Pure chaos has hit the Discord!"
    assert kobold.as_line('". . .", "The way you handled those bricks!!"]') == "The way you handled those bricks!!"
    assert kobold.as_line('". . . Absolutely legendary moves right there!"]') == "Absolutely legendary moves right there!"
    assert kobold.parse('"...", "That level of chaos!", ". . .", "So much magic!"]') == ["That level of chaos!", "So much magic!"]
    assert kobold.as_line("] Wait, did anyone see that coming?!") == "Wait, did anyone see that coming?!"
    # a "]" inside a line no longer cuts the list short; lines that are fine stay as they are
    assert kobold.parse('"She said [sic] and left.", "Second."]') == ["She said [sic] and left.", "Second."]
    assert kobold.as_line('"Monday is busy!",\n"Traube starts at midnight."]') == "Monday is busy! Traube starts at midnight."
    assert kobold.tidy("Fine. As is.") == "Fine. As is." and kobold.tidy("🔥🔥") == "🔥🔥"
    assert kobold.tidy("...") == "" and kobold.as_line('"..."]') == ""


async def test_igdb_details_for_game_talk_and_the_owners_search():
    row = gameinfo.shape(BRICK)
    assert row["year"] == "2025" and row["maker"] == "Tiny Studio" and row["themes"] == ["Comedy"]
    assert row["modes"] == ["Co-operative"] and row["v"] == gameinfo.DETAIL
    assert len(row["summary"]) <= gameinfo.SUMMARY_MAX + 1 < len(row["about"]) <= gameinfo.ABOUT_MAX + 1
    said = gameinfo.talk(row)
    assert said.startswith("About the game Brick by Brick (genres: Simulator, Indie; themes: Comedy; modes: Co-operative; "
                           "released in 2025; made by Tiny Studio): Rob a retirement home")
    assert gameinfo.talk({}) == "" and gameinfo.talk({"name": "X"}) == ""
    assert gameinfo.shape({"name": "Old", "first_release_date": "soon"})["year"] == ""     # odd data never raises

    store = Store(":memory:")
    tw = SearchTwitch({"brick by brick": [BRICK, {"name": "Brick by brick"}, {"name": "Brick Breaker"}]})
    gi = gameinfo.GameInfo(store, tw)
    got = await gi.search("  brick   by brick ")
    assert [g["name"] for g in got] == ["Brick by Brick", "Brick Breaker"]       # the same name twice is listed once
    assert "themes.name" in tw.calls[0][1] and f"limit {gameinfo.SEARCH_MAX}" in tw.calls[0][1]
    assert await gi.search("") == [] and await gi.search("nothing like it") == []
    gi.keep(got[0])
    assert gameinfo.cached(store, "brick by brick")["maker"] == "Tiny Studio"
    calls = len(tw.calls)
    assert (await gi.lookup("Brick by Brick"))["year"] == "2025" and len(tw.calls) == calls    # kept: not asked again
    # a row kept before the game-talk details existed is asked for once more
    store.put("game_info.valheim", {"name": "Valheim", "genres": ["Survival"], "summary": "Vikings.", "at": time.time()})
    tw.answers["Valheim"] = [{"name": "Valheim", "summary": "Vikings.", "themes": [{"name": "Fantasy"}]}]
    assert (await gi.lookup("Valheim"))["themes"] == ["Fantasy"] and len(tw.calls) == calls + 1
    await gi.lookup("Valheim")
    assert len(tw.calls) == calls + 1
    # no Twitch keys: nothing can be searched
    tw.ready = False
    assert await gi.search("brick by brick") is None and not gi.ready


def test_a_game_set_by_hand_reaches_the_stream_its_history_and_the_calendar(tmp_path):
    store = world()
    lulu = store.person("Lulu")["id"]
    at = ts(2026, 11, 19, 15)
    sid = store.start_session(lulu, at, platforms=["youtube"], title=TITLE)
    store.update_session(sid, ended_at=at + 7200)
    poster = CalendarPoster(store, FakeDiscord(), ImageCache(tmp_path), None, clock=lambda: ts(2026, 11, 20, 10, 5))
    tile = lambda week: next(t for t in week.tiles() if t.title == TITLE and t.kind != "scheduled")     # noqa: E731
    assert tile(poster.build_review("flavr", "week")).game == ""
    # set: the stream's row, and "this title means this game"
    assert games.set_stream(store, lulu, TITLE, "  Brick  by Brick ", sid) == "Brick by Brick"
    assert tile(poster.build_review("flavr", "week")).game == "Brick by Brick"
    assert games.fixed(store, lulu, TITLE) == "Brick by Brick" and "Brick by Brick" in store.known_games(lulu)
    assert games.tag(store, lulu, "Brick by Brick", at + 86400) == "part:2"          # it counts in the game history
    # a planned stream with the same title shows the game too (YouTube gives a waiting room no category)
    store.replace_scheduled(lulu, "youtube", [{"key": "v1", "at": ts(2026, 11, 21, 15), "title": TITLE, "url": "u"}], now=ts(2026, 11, 20, 9))
    planned = [t for t in poster.build("flavr", poster.week_of(0)).tiles() if t.kind == "scheduled"]
    assert [t.game for t in planned] == ["Brick by Brick"]
    # a stream with ONE game segment has it renamed (the tag worked out again); the owner's fix wins over the old guess
    one = store.sessions_between(ts(2026, 11, 18, 20) - 1, ts(2026, 11, 18, 20) + 1)[0]
    assert [s["game"] for s in store.segments(one["id"])] == ["Valheim"]
    games.set_stream(store, one["person_id"], one["title"], "Enshrouded", one["id"])
    seg = store.segments(one["id"])[0]
    assert (seg["game"], seg["tag"]) == ("Enshrouded", "new")
    # cleared: no game on the row, the segment gone, the title forgotten
    games.set_stream(store, lulu, TITLE, "", sid)
    assert tile(poster.build_review("flavr", "week")).game == "" and games.fixed(store, lulu, TITLE) == ""
    games.set_stream(store, one["person_id"], one["title"], "", one["id"])
    assert store.segments(one["id"]) == []


async def test_the_builders_game_box_and_a_remark_about_the_game(tmp_path):
    hosts.init(tmp_path / "pics")
    store = world()
    lulu = store.person("Lulu")["id"]
    at = ts(2026, 11, 19, 15)                         # a Thursday stream whose title names no known game
    sid = store.start_session(lulu, at, platforms=["youtube"], title=TITLE)
    store.update_session(sid, ended_at=at + 7200)
    poster = _poster(tmp_path, store)
    store.put("hosts_only", "colette")
    kob = FakeKobold()
    poster.kobold = kob
    tw = SearchTwitch({"we steal from old people brick by brick": [], "brick by brick": [BRICK, {"name": "Brick Breaker"}]})
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")
            p = poster.store.get(dkey)
            week, _ = await article_editor._article(poster, p)
            day = next(i for i, d in enumerate(week.days) if any(t.title == TITLE for t in d))
            data = {"d": dkey, "action": "add_recipe", "recipe": "day", "recipe_day": str(day),
                    **{f"on_{s['id']}": "1" for s in p["sections"]}}
            await c.post("/settings/article", data=data, allow_redirects=False)

            async def build(action, **extra):
                r = await c.post("/settings/tall", data={"d": dkey, "t": "tall1", "action": action, **extra}, allow_redirects=False)
                assert r.status == 303, await r.text()
                return poster.store.get(dkey)["talls"]["tall1"]["chunks"], r.headers["Location"]

            async def builder():
                return await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()

            page = await builder()
            assert "none found" in page and 'name="c2__gamename"' in page and "Set game" in page
            assert "Search IGDB" not in page and "needs the Twitch keys" in page       # no IGDB yet: type it by hand
            assert '<datalist id=known-games>' in page and '<option value="Valheim">' in page
            assert "The remark is about" in page and 'name="c2__hint"' in page
            # a remark about the game needs a game first
            ch, loc = await build("save", c2__about="game", c2__hint="  they got   caught twice ")
            assert ch[1]["about"] == "game" and ch[1]["hint"] == "they got caught twice"
            ch, loc = await build("ai:c2")
            assert "no%20game%20yet" in loc and not kob.asked and not ch[1].get("line")
            _, loc = await build("findgame:c2")
            assert "Twitch%20keys" in loc

            # IGDB on: an empty box searches the title's parts; the results are buttons
            poster.game_info = gameinfo.GameInfo(store, tw)
            _, loc = await build("findgame:c2")
            assert "found%20no%20game" in loc and [x[1].split('"')[1] for x in tw.calls] == ["we steal from old people brick by brick", "flavr"]
            ch, loc = await build("findgame:c2", c2__gamename="brick by brick")
            assert [g["name"] for g in ch[1]["found"]] == ["Brick by Brick", "Brick Breaker"] and "found%202" in loc
            page = await builder()
            assert "Search IGDB" in page and 'value="pickgame:c2:0"' in page and "2025 · Simulator, Indie" in page
            assert 'value="brick by brick"' in page          # the box keeps the searched words while the results show
            # an ordinary save (the page saving itself) never sets a game, whatever is in the box
            await build("save", c2__gamename="Brick Breaker")
            assert store.sessions_between(at - 1, at + 1)[0]["game"] == ""
            # picked: the stream's game, its details kept, the title remembered, the results cleared
            ch, loc = await build("pickgame:c2:0")
            assert "found" not in ch[1] and "Brick%20by%20Brick%20now" in loc
            assert store.sessions_between(at - 1, at + 1)[0]["game"] == "Brick by Brick"
            assert games.fixed(store, lulu, TITLE) == "Brick by Brick" and gameinfo.cached(store, "Brick by Brick")["year"] == "2025"
            page = await builder()
            assert "<b>Brick by Brick</b> <small>Simulator, Indie · 2025</small>" in page and "none found" not in page
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            assert "Brick by Brick" in poster.shooter.docs[-1]

            # ✨ about the game: the game-talk ask, the longer details and the owner's words in the facts
            ch, _ = await build("ai:c2")
            key, ask, facts = kob.asked[-1]
            assert ask == kobold.asks()["stream_game"] and kob.kinds[-1] == "stream_game" and ch[1]["line"] == "A cosy one."
            assert "About the game Brick by Brick (genres: Simulator, Indie; themes: Comedy" in facts
            assert "made by Tiny Studio" in facts and facts.endswith("The producer adds: they got caught twice.")
            # back to a plain reaction: the short facts, the stream ask
            ch, _ = await build("ai:c2", c2__about="", c2__hint="")
            key, ask, facts = kob.asked[-1]
            assert ask == kobold.asks()["stream"] and "About the game" not in facts and "producer adds" not in facts
            assert "Brick by Brick is Simulator, Indie" in facts

            # typed by hand: Set game looks its details up once; an empty box clears the game
            tw.answers["Enshrouded"] = [{"name": "Enshrouded", "genres": [{"name": "Adventure"}]}]
            _, loc = await build("setgame:c2", c2__gamename=" Enshrouded ")
            assert store.sessions_between(at - 1, at + 1)[0]["game"] == "Enshrouded" and "Enshrouded%20now" in loc
            assert gameinfo.cached(store, "Enshrouded")["genres"] == ["Adventure"]
            _, loc = await build("setgame:c2", c2__gamename="")
            assert store.sessions_between(at - 1, at + 1)[0]["game"] == "" and "no%20game%20now" in loc
            assert "none found" in await builder()
            # a game chunk has the same two steering fields (its own ask)
            await build("add", newtype="game")
            ch = poster.store.get(dkey)["talls"]["tall1"]["chunks"]
            gid = ch[-1]["id"]
            ch, _ = await build("save", **{f"{gid}__game": "Valheim", f"{gid}__about": "game"})
            assert recipes.ask_kind(ch[-1]) == "game_talk" and recipes.ask_kind({"type": "game"}) == "game"
            # a stack saved as a template keeps "about" (a layout choice) but not this week's hint or search
            from flavrpromo import tall
            kept = tall.strip([{"id": "c1", "type": "stream", "about": "game", "hint": "x", "found": [1], "found_q": "q", "ref": "d0:0"}])[0]
            assert kept["about"] == "game" and kept["hint"] == "" and "found" not in kept and "found_q" not in kept
    finally:
        hosts.init(None)
