"""The tall picture builder, round "stack editor" (owner 2026-11-22; flavrpromo/tall_page.py, recipes.py,
kobold.py): ✨ on the sign-off strip and host moments from a summary of the stack, the Look card (colour
scheme, host style, every bottom edge), stream links, a hand-edited line that stays, lines cleaned of a list
written inside one line, and the Tall pictures page that opens a stack editor without the article editor."""

from flavrpromo import article_editor, hosts, kobold, panel, recipes, tall, tall_page

from test_hosts import world
from test_recipes import FakeKobold
from test_settings_round2 import _client, _poster


def test_a_list_written_inside_one_line_is_put_back_together():
    # the owner's picture (2026-11-22): the model put its three items inside one pair of quotes
    shown = ('ASHE IS TAKING FLIGHT!! SPECTACULAR!!\\\\", \\\\"Aces High III looks stunning!!\\\\", '
             '\\\\"SKY HIGH MAYHEM!!\\\\"')
    assert kobold.tidy(shown) == "ASHE IS TAKING FLIGHT!! SPECTACULAR!! Aces High III looks stunning!! SKY HIGH MAYHEM!!"
    assert kobold.as_line('"A one!!\\", \\"B two!!\\", \\"C three!!\\""]') == "A one!! B two!! C three!!"
    assert kobold.as_line('"A one!!\\\\", \\\\"B two!!\\\\""]') == "A one!! B two!!"
    assert kobold.as_line('"He said \\"hi\\" and left."]') == 'He said "hi" and left.'      # ordinary quotes stay
    # lines written before the fix are cleaned when the builder opens them; the owner's own words never
    chunks = [{"id": "c1", "type": "stream", "line": "]Croissant time!", "choices": ["]Croissant time!", ". . . Wow!"]},
              {"id": "c2", "type": "stream", "line": "] my own bracket", "choices": ["]Other"]}]
    tall_page._tidy_old(chunks)
    assert chunks[0]["line"] == "Croissant time!" and chunks[0]["choices"] == ["Croissant time!", "Wow!"]
    assert chunks[1]["line"] == "] my own bracket" and chunks[1]["choices"] == ["Other"]


def test_seams_for_a_whole_stack_and_the_stack_summary(tmp_path):
    chunks = [{"id": f"c{i}", "type": "quote", "cut": "v"} for i in range(4)]
    recipes.apply_seams(chunks, "diagonal")
    assert [c["cut"] for c in chunks] == ["down", "up", "down", "v"]            # never the last chunk
    recipes.apply_seams(chunks, "")
    assert [c["cut"] for c in chunks[:3]] == ["", "", ""]
    recipes.apply_seams(chunks, "nonsense")                                     # an unknown kind changes nothing
    assert [c["cut"] for c in chunks[:3]] == ["", "", ""]
    assert recipes.ask_kind({"type": "footer"}) == "tall_signoff" and recipes.ask_kind({"type": "host"}) == "tall_host"
    assert {"tall_signoff", "tall_host"} <= set(kobold.ASKS) and "tall_signoff" in kobold.LENGTHS
    # the draft as one tall picture sees it: its own host style, the same chunks
    p = {"host": "colette", "talls": {"tall1": {"host": "clark", "chunks": []}, "tall2": {"chunks": []}}}
    assert recipes.as_tall(p, "tall1")["host"] == "clark" and recipes.as_tall(p, "tall2") is p
    assert recipes.as_tall(p, "tall1")["talls"] is p["talls"]


async def test_the_tall_pictures_page_opens_a_stack_editor_directly(tmp_path):
    hosts.init(tmp_path / "pics")
    store = world()
    for s in store.sessions_between(0, 9e9):
        store.update_session(s["id"], vod_url=f"https://vods.example/{s['id']}", links={"youtube": "https://yt.example/live"})
    poster = _poster(tmp_path, store)
    store.put("hosts_only", "colette")
    kob = FakeKobold("That was the week. Bye!")
    poster.kobold = kob
    dkey = article_editor.draft_key("flavr", "week")
    assert any(n == tall_page.LIST_TAB for _, pages in panel.NAV for _, n in pages)       # it is in the panel's menu
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            # looking at the page makes no draft; the recipes and stacks are offered
            page = await (await c.get("/settings/talls?group=flavr&which=week")).text()
            assert store.get(dkey) is None and "No tall pictures for this week yet" in page
            assert "Build it" in page and "Week overview (built-in)" in page and "<b>🧱 Tall pictures</b>" in page

            async def make(**data):
                r = await c.post("/settings/talls", data={"group": "flavr", "which": "week", **data}, allow_redirects=False)
                assert r.status == 303
                return r.headers["Location"]

            # a recipe with nothing to build says so and makes nothing
            assert "No%20streams" in await make(action="add_recipe", recipe="person", recipe_person="Nobody")
            assert not (store.get(dkey) or {}).get("talls")
            # one day in detail: the draft is made quietly, the picture is NOT in the article, the builder opens
            p0 = store.get(dkey) or await article_editor.new_draft(poster, "flavr", "week")
            week, _ = await article_editor._article(poster, p0)
            day = next(i for i, d in enumerate(week.days) if d)
            loc = await make(action="add_recipe", recipe="day", recipe_day=str(day))
            assert loc.startswith("/settings/tall?d=") and "t=tall1" in loc
            p = store.get(dkey)
            assert [s["on"] for s in p["sections"] if s["id"] == "tall1"] == [False]
            assert [x["type"] for x in p["talls"]["tall1"]["chunks"]][0] == "header"
            # from a stack: this week's streams filled in
            loc = await make(action="add_tall", tall_stack="b:Week overview")
            assert "t=tall2" in loc and store.get(dkey)["talls"]["tall2"]["chunks"]
            page = await (await c.get("/settings/talls?group=flavr&which=week")).text()
            assert page.count("Edit the chunks") == 2 and "not in the article" in page and 'value="remove:tall2"' in page
            assert "Removed" in await make(action="remove:tall2")
            assert "tall2" not in store.get(dkey)["talls"] and not any(s["id"] == "tall2" for s in store.get(dkey)["sections"])

            async def build(action, **extra):
                r = await c.post("/settings/tall", data={"d": dkey, "t": "tall1", "action": action, **extra}, allow_redirects=False)
                assert r.status == 303, await r.text()
                return store.get(dkey)["talls"]["tall1"]["chunks"], r.headers["Location"]

            async def builder():
                return await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()

            page = await builder()
            assert "all tall pictures</a>" in page and "Look of the whole stack" in page and "data-redraw" in page
            assert 'name="scheme_tall1"' in page and "name=stack_host" in page and "name=stack_seams" in page
            # the stream's own links, to check it
            sid = store.sessions_between(week.days[day][0].at - 1, week.days[day][0].at + 1)[0]["id"]
            assert f'<a href="https://vods.example/{sid}" target=_blank rel=noopener>VOD ↗</a>' in page
            assert '<a href="https://yt.example/live" target=_blank rel=noopener>youtube ↗</a>' in page

            # ✨ on the sign-off strip: asked with what the picture shows, plus the owner's words
            ch, _ = await build("save")
            foot = ch[-1]["id"]
            assert ch[-1]["type"] == "footer" and "Write the sign-off" in page and f'name="{foot}__hint"' in page
            ch, loc = await build(f"ai:{foot}", **{f"{foot}__hint": "thank the mods"})
            host, ask, facts = kob.asked[-1]
            assert ch[-1]["line"] == "That was the week. Bye!" and ch[-1]["choices"][1] == "Second take."
            assert ask == kobold.asks()["tall_signoff"] and kob.kinds[-1] == "tall_signoff" and host == "colette"
            assert "It shows: " in facts and week.days[day][0].name in facts and facts.endswith("The producer adds: thank the mods.")
            assert "in detail" in facts                                   # the header's title names the picture
            # a host moment gets one too
            ch, _ = await build("add", newtype="host")
            hid = ch[-1]["id"]
            ch, _ = await build(f"ai:{hid}")
            assert kob.kinds[-1] == "tall_host" and ch[-1]["line"] == "That was the week. Bye!"
            _, loc = await build("add", newtype="quote")
            _, loc = await build(f"ai:{store.get(dkey)['talls']['tall1']['chunks'][-1]['id']}")
            assert "no%20%E2%9C%A8" in loc                                # a chunk type without ✨ says so

            # a hand-edited line stays: the browser still has the old choice ticked on every later save
            page = await builder()
            assert f'name="{foot}__chosen" value="0"' in page
            sent = {f"{foot}__choice": "0", f"{foot}__chosen": "0"}
            ch, _ = await build("save", **sent, **{f"{foot}__line": "My own goodbye."})
            ch, _ = await build("save", **sent, **{f"{foot}__line": "My own goodbye."})      # the next save, nothing changed
            assert next(x for x in ch if x["id"] == foot)["line"] == "My own goodbye."
            assert f'name="{foot}__chosen" value=""' in await builder()                      # none of the choices is in the box
            # ... and picking another choice still puts it in
            ch, _ = await build("save", **{f"{foot}__choice": "2", f"{foot}__chosen": "", f"{foot}__line": "My own goodbye."})
            assert next(x for x in ch if x["id"] == foot)["line"] == "Third take."

            # the Look card: this picture's colours, its host style, every bottom edge
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            plain = poster.shooter.docs[-1]
            before = article_editor.stamp(store.get(dkey), "tall1")
            await build("save", scheme_tall1="ocean", stack_host="clark")
            p = store.get(dkey)
            assert p["schemes"] == {"tall1": "ocean"} and p["talls"]["tall1"]["host"] == "clark" and p["host"] == "colette"
            assert article_editor.stamp(p, "tall1") != before             # the pictures are drawn again
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            doc = poster.shooter.docs[-1]
            assert doc != plain and tall.THEMES["clark"]["font"] in doc and tall.THEMES["colette"]["font"] not in doc
            page = await builder()
            assert "The stack&#x27;s host (Clark)" in page or "The stack's host (Clark)" in page
            ch, _ = await build(f"ai:{foot}")
            assert kob.asked[-1][0] == "clark"                            # the stack's own host speaks
            await build("save", scheme_tall1="", stack_host="colette")    # the article's own host = no style of its own
            p = store.get(dkey)
            assert p["schemes"] == {} and p["talls"]["tall1"]["host"] == ""
            ch, loc = await build("seams", stack_seams="wave")
            assert [x.get("cut") for x in ch[:-1]] == ["wave"] * (len(ch) - 1) and "every%20bottom%20edge" in loc
            # the stream look: the Look card sets every stream chunk, each stream has its own menu, a recipe can start with it
            page = await builder()
            assert "name=stack_look" in page and 'value=looks' in page
            ch, loc = await build("looks", stack_look="strip")
            streams = [x for x in ch if x["type"] == "stream"]
            assert streams and all(x["look"] == "strip" for x in streams) and "stream" in loc
            sid1 = streams[0]["id"]
            assert f'name="{sid1}__look"' in await builder()
            ch, _ = await build("save", **{f"{sid1}__look": "nonsense"})              # only a known look is taken
            assert next(x for x in ch if x["id"] == sid1)["look"] == ""
            ch, _ = await build("save", **{f"{sid1}__look": "strip"})
            assert next(x for x in ch if x["id"] == sid1)["look"] == "strip"
            ch, _ = await build("looks", stack_look="")
            assert all(x.get("look") == "" for x in ch if x["type"] == "stream")
            loc = await make(action="add_recipe", recipe="day", recipe_day=str(day), recipe_look="strip")
            made = store.get(dkey)["talls"][loc.split("t=")[1].split("&")[0].split("#")[0]]["chunks"]
            assert [x["look"] for x in made if x["type"] == "stream"] == ["strip"] * len([x for x in made if x["type"] == "stream"]) and made
            # the other article styles: layouts on a day's pictures chunk, sticky notes on highlights, people cards
            ch, _ = await build("add", newtype="grid")
            gid = ch[-1]["id"]
            ch, _ = await build("save", **{f"{gid}__layout": "spotlight"})
            assert next(x for x in ch if x["id"] == gid)["layout"] == "spotlight"
            ch, _ = await build("save", **{f"{gid}__layout": "nonsense"})
            assert next(x for x in ch if x["id"] == gid)["layout"] == ""
            ch, _ = await build("add", newtype="stats")
            nid = ch[-1]["id"]
            ch, _ = await build("save", **{f"{nid}__look": "notes"})
            assert next(x for x in ch if x["id"] == nid)["look"] == "notes"
            ch, _ = await build("add", newtype="people")
            page = await builder()
            assert f'name="{gid}__layout"' in page and f'name="{nid}__look"' in page and "tilted colour cards" in page
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")                   # all of them draw
            assert "TOP PICK" not in poster.shooter.docs[-1] and "📌" in poster.shooter.docs[-1]
            # the article editor's recipe row and Look card offer it too
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert "name=recipe_look" in page and "name=day_stream_look" in page
            # the article editor still lists the picture, unticked
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert 'id="s-tall1"' in page
    finally:
        hosts.init(None)
