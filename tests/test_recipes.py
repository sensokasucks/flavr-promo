"""Tall recipes (flavrpromo/recipes.py): whole tall sections for the article editor (games this week, one
day in detail, one person's week), the show tick boxes of stream / game chunks, and the ✨ remark per
chunk written by KoboldCpp from that stream's or game's facts (a fake model here, no network)."""

import asyncio
from types import SimpleNamespace

from flavrpromo import article_editor, gameinfo, hosts, recipes, tall, tall_page
from test_settings_round2 import _client, _poster


class FakeKobold:
    """Stands in for kobold.Kobold: remembers what it was asked and answers with a fixed line."""

    def __init__(self, answer="A cosy one."):
        self.asked, self.answer, self.last_raw = [], answer, ""

    async def line(self, key, ask, heading, facts):
        self.asked.append((key, ask, facts))
        return self.answer


def test_long_lists_split_into_pictures_that_fit():
    items = [{"type": "stream", "ref": f"d0:{n}", "line": ""} for n in range(14)]
    out = recipes._pictures("Friday, in detail", ["Nov 20"], items, diagonal=True)
    assert len(out) == 2 and sum(1 for _, ch in out for c in ch if c["type"] == "stream") == 14
    for title, chunks in out:
        assert tall.total(chunks) <= tall.MAX_H and "of 2" in title
        assert [c["id"] for c in chunks] == [f"c{i}" for i in range(1, len(chunks) + 1)]
        assert chunks[0]["type"] == "header" and chunks[0]["sub"].startswith("Nov 20 · part ")
        assert all(c["cut"] in ("down", "up") for c in chunks[:-1]) and not chunks[-1].get("cut")
    assert out[-1][1][-1]["type"] == "footer" and out[0][1][-1]["type"] == "stream"   # sign-off on the last only
    few = recipes._pictures("Games this week", [""], [{"type": "game", "game": "A"}] * 3, diagonal=False)
    assert len(few) == 1 and few[0][0] == "Games this week" and few[0][1][1]["size"] == 1
    eight = recipes._pictures("Games this week", [""], [{"type": "game", "game": "A"}] * 8, diagonal=False)
    assert len(eight) == 1 and eight[0][1][1]["size"] == 0 and tall.total(eight[0][1]) <= tall.MAX_H


def test_game_and_stream_chunks_draw_what_is_ticked():
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "W", "range": "Nov 15-21",
           "seed": 1, "pins": {},
           "games": {"valheim": {"game": "Valheim", "people": ["Lulu", "Sen"], "streams": 3, "tags": ["part:4"]}},
           "info": {"valheim": {"genres": ["Survival"], "summary": "Vikings build and fight."}}}
    game = {"id": "c1", "type": "game", "size": 1, "game": "Valheim", "line": "Skål!"}
    doc = tall.document([game], ctx)
    assert "Valheim" in doc and "Lulu, Sen · 3 streams" in doc and "PART 4" in doc and "Survival" in doc
    assert "Vikings build" in doc and "Skål!" in doc
    lean = dict(game, show=["people"])                      # mix and match: only who played it
    doc = tall.document([lean], ctx)
    assert "Lulu, Sen" in doc and "PART 4" not in doc and "Survival" not in doc and "Skål!" not in doc
    assert "Pick a game" in tall.document([{"id": "c2", "type": "game", "size": 0, "game": ""}], ctx)
    assert tall.shown({"type": "stream"}, "thumb") and not tall.shown({"type": "stream", "show": []}, "thumb")


async def test_recipes_build_sections_and_kobold_writes_remarks_from_the_facts(tmp_path):
    hosts.init(tmp_path / "pics")
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    kob = FakeKobold()
    poster.kobold = kob
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")
            p = poster.store.get(dkey)
            week, _ = await article_editor._article(poster, p)
            games = recipes.game_rows(p["facts"], week)
            assert games, "the test calendar has games"
            for r in games:                                   # IGDB info the cache would hold
                poster.store.put(gameinfo._key(r["game"]), {"name": r["game"], "genres": ["Puzzle"], "summary": "Solve things."})

            async def edit(action, **extra):
                p = poster.store.get(dkey)
                data = {"d": dkey, "action": action, **{f"on_{s['id']}": "1" for s in p["sections"]}, **extra}
                r = await c.post("/settings/article", data=data, allow_redirects=False)
                assert r.status == 303
                return poster.store.get(dkey), r.headers["Location"]

            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert "Add a tall section" in page and "Build it" in page and "One day in detail" in page
            # games this week → a tall section of game chunks, before the outro
            p, _ = await edit("add_recipe", recipe="games", recipe_seams="diagonal")
            ids = [s["id"] for s in p["sections"]]
            assert ids[-2] == "tall1" and p["talls"]["tall1"]["chunks"][0]["title"] == "Games this week"
            kinds = [x["type"] for x in p["talls"]["tall1"]["chunks"]]
            assert kinds[0] == "header" and kinds.count("game") == len(games) and kinds[-1] == "footer"
            assert p["talls"]["tall1"]["chunks"][0]["cut"] == "down"
            # one day in detail: the first day that has streams
            day = next(i for i, d in enumerate(week.days) if d)
            p, _ = await edit("add_recipe", recipe="day", recipe_day=str(day))
            chunks = p["talls"]["tall2"]["chunks"]
            assert [x["type"] for x in chunks].count("stream") == len(week.days[day])
            assert chunks[1]["ref"] == f"d{day}:0" and "in detail" in chunks[0]["title"]
            # one person's week, and a recipe with nothing to build says so
            who = week.days[day][0].name
            p, _ = await edit("add_recipe", recipe="person", recipe_person=who)
            assert p["talls"]["tall3"]["chunks"][0]["title"] == f"{who}'s week"
            _, loc = await edit("add_recipe", recipe="person", recipe_person="Nobody")
            assert "No%20streams" in loc and "tall4" not in poster.store.get(dkey)["talls"]

            # the builder shows tick boxes; a partial post keeps them, a full one changes them
            builder = await (await c.get(f"/settings/tall?d={dkey}&t=tall2")).text()
            assert "c2__show_thumb" in builder and "Write the remark" in builder and "Write all empty remarks" in builder

            async def build(tid, action, **extra):
                r = await c.post("/settings/tall", data={"d": dkey, "t": tid, "action": action, **extra}, allow_redirects=False)
                assert r.status == 303, await r.text()
                return poster.store.get(dkey)["talls"][tid]["chunks"]

            ch = await build("tall2", "save", c2__line="Mine.")
            assert "show" not in ch[1] and ch[1]["line"] == "Mine."
            ch = await build("tall2", "save", c2__showed="1", c2__show_name="1", c2__show_host="1")
            assert ch[1]["show"] == ["name", "host"]
            ch = await build("tall2", "save", c2__showed="1", c2__show_name="1", c2__show_thumb="1", c2__show_line="1", c2__line="")
            assert ch[1]["show"] == ["thumb", "name", "line"]
            # a game chunk takes only a game of the week
            ch = await build("tall1", "save", c2__game="Not a game")
            assert ch[1]["game"] == ""
            ch = await build("tall1", "save", c2__game=games[0]["game"])
            assert ch[1]["game"] == games[0]["game"]

            # ✨ one game chunk: asked with THAT game's facts, in the chunk's host's voice
            ch = await build("tall1", "ai:c2")
            assert ch[1]["line"] == "A cosy one."
            key, ask, facts = kob.asked[-1]
            assert key == "colette" and ask == recipes.kobold.asks()["game"]
            assert games[0]["game"] in facts and "Puzzle" in facts and "Solve things." in facts
            # ✨ one stream chunk: that stream's person, game and day
            ch = await build("tall2", "save", c2__line="")
            ch = await build("tall2", "ai:c2")
            assert ch[1]["line"] == "A cosy one."
            facts = kob.asked[-1][2]
            t = week.days[day][0]
            assert t.name in facts and "streamed" in facts and week.date_of(day).strftime("%A") in facts
            # ✨ write all: only the empty remarks, in the background
            await build("tall1", "save", c3__line="Keep me.")
            before = poster.store.get(dkey)["talls"]["tall1"]["chunks"]
            empties = sum(1 for x in before if x["type"] == "game" and not x["line"])
            asked = len(kob.asked)
            await build("tall1", "aiall")
            for _ in range(50):
                if (poster.store.get(dkey)["talls"]["tall1"].get("ai_state") or "") in ("done", "offline", "nolines"):
                    break
                await asyncio.sleep(0.02)
            ch = poster.store.get(dkey)["talls"]["tall1"]
            assert ch["ai_state"] == "done" and ch["chunks"][2]["line"] == "Keep me."
            assert len(kob.asked) - asked == empties                    # one request per empty remark, none for c3
            assert all(x["line"] for x in ch["chunks"] if x["type"] == "game")
            # KoboldCpp offline: a clear note, nothing written
            poster.kobold = None
            ch = await build("tall1", "ai:c2")
            # no model: the page still renders and the picture is drawn with the game chunks
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            assert "A cosy one." in poster.shooter.docs[-1] and "Puzzle" in poster.shooter.docs[-1]
            assert poster.shooter.sizes[-1][1] == tall.total(ch)
    finally:
        hosts.init(None)
