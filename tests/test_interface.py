"""The comfort layer of the settings pages (owner 2026-11-22: live preview, folding cards, drag to reorder, a
colour per chunk, copy a tall section, and the same look on every page): what the server side does for it.
The script itself (flavrpromo/panel.py SCRIPT) only posts the same forms a button would."""

from types import SimpleNamespace

from flavrpromo import article_editor, hosts, panel, tall, tall_page
from test_settings_round2 import _client, _poster


def test_every_page_gets_the_script_and_sections_fold():
    page = panel.frame("T", "⚙️ Settings", "<section id=a><h2>One</h2><p>x</p></section>")
    assert "<script>" in page and "data-live" in panel.SCRIPT and "data-draglist" in panel.SCRIPT
    assert "getAttribute('action')" in panel.SCRIPT          # form.action is shadowed by the buttons named "action"
    # quick forms and drop zones (the Pictures tab): posted in the background, files included
    assert "form[data-quick]" in panel.SCRIPT and "data-dropzone" in panel.SCRIPT and "new FormData(form)" in panel.SCRIPT
    assert ".js .nojs" in panel.STYLE and ".toast" in panel.STYLE
    assert "section.folded" in panel.STYLE and "details.card" in panel.STYLE


def test_a_chunk_takes_its_own_colour():
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "W", "range": "R",
           "seed": 1, "pins": {}}
    q = {"id": "c1", "type": "quote", "size": 0, "text": "Wow"}
    assert tall.band_colour(q) == "" and tall.band_colour(dict(q, band="teal")) == "#0e4a4c"
    assert tall.band_colour(dict(q, band="#ABCDEF")) == "#abcdef" and tall.band_colour(dict(q, band="red; x")) == ""
    assert "background:#0e4a4c;" in tall.document([dict(q, band="teal")], ctx)
    light = tall.document([dict(q, band="paper")], ctx)                 # a light colour gets dark text
    assert "background:#f4ead8;color:#1a1a1a;" in light
    assert "background:#0e4a4c" not in tall.document([q], ctx)


async def test_builder_reorders_colours_and_editor_copies_and_reorders(tmp_path):
    hosts.init(tmp_path / "pics")
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")

            async def edit(action, **extra):
                p = poster.store.get(dkey)
                data = {"d": dkey, "action": action, **{f"on_{s['id']}": "1" for s in p["sections"]}, **extra}
                assert (await c.post("/settings/article", data=data, allow_redirects=False)).status == 303
                return poster.store.get(dkey)

            async def build(action, **extra):
                r = await c.post("/settings/tall", data={"d": dkey, "t": "tall1", "action": action, "c1__title": "T", **extra},
                                 allow_redirects=False)
                assert r.status == 303
                return poster.store.get(dkey)["talls"]["tall1"]["chunks"]

            p = await edit("add_tall")
            builder = await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            assert "data-live" in builder and 'data-swap=rebuild data-swap-id=chunks data-draglist' in builder
            assert '<details class="card chunk" id="c1">' in builder and "c1__band" in builder and "Fold all" in builder
            # the colour menu, the colour box ("custom"), nonsense is dropped
            ch = await build("save", c2__band="navy")
            assert ch[1]["band"] == "navy"
            ch = await build("save", c2__band="custom", c2__bandhex="#112233")
            assert ch[1]["band"] == "#112233"
            ch = await build("save", c2__band="nope")
            assert ch[1]["band"] == ""
            # cards dragged into a new order; a list that isn't the same cards is ignored
            ch = await build("order", order="c3,c1,c4,c2")
            assert [x["id"] for x in ch] == ["c3", "c1", "c4", "c2"]
            ch = await build("order", order="c3,c1")
            assert [x["id"] for x in ch] == ["c3", "c1", "c4", "c2"]

            # the editor: live form, folding cards, the section parts that are swapped in
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert "data-live" in page and '<details class="card sec" id="s-intro" open>' in page
            assert 'data-swap-id="sec-tall1"' in page and 'value="copy:tall1"' in page and "data-draglist" in page
            # a picture's URL stamp: the same after a plain save, new once what it shows changes
            p = poster.store.get(dkey)
            before = article_editor.stamp(p, "tall1"), article_editor.stamp(p, "intro"), article_editor.stamp(p)
            p = await edit("save")
            assert (article_editor.stamp(p, "tall1"), article_editor.stamp(p, "intro"), article_editor.stamp(p)) == before
            p2 = poster.store.get(dkey)
            p2["talls"]["tall1"]["chunks"][0]["title"] = "Changed"
            assert article_editor.stamp(p2, "tall1") != before[0] and article_editor.stamp(p2, "intro") == before[1]
            # copy a tall section: its own chunks, right under the original
            p = await edit("copy:tall1")
            ids = [s["id"] for s in p["sections"]]
            assert ids.index("tall2") == ids.index("tall1") + 1 and p["talls"]["tall2"]["chunks"] == p["talls"]["tall1"]["chunks"]
            assert p["talls"]["tall2"]["chunks"] is not p["talls"]["tall1"]["chunks"]
            assert [s["title"] for s in p["sections"] if s["id"] == "tall2"][0].endswith("(copy)")
            # sections dragged into a new order
            want = ["tall2"] + [i for i in ids if i != "tall2"]
            p = await edit("order", order=",".join(f"s-{i}" for i in want))
            assert [s["id"] for s in p["sections"]] == want
            p = await edit("order", order="s-intro")
            assert [s["id"] for s in p["sections"]] == want
    finally:
        hosts.init(None)


def test_zigzag_and_curved_seams():
    """Owner 2026-11-22: zigzag and curved edges between chunks, with the count of teeth / waves."""
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "W", "range": "R",
           "seed": 1, "pins": {}}
    q = lambda i, **kw: dict({"id": f"c{i}", "type": "quote", "size": 1, "text": "x"}, **kw)  # noqa: E731
    zig = tall.edge("zig", 60, 4)
    assert len(zig) == 9 and zig[0] == (0.0, 60.0) and zig[1] == (12.5, 0.0) and zig[-1] == (100.0, 60.0)
    wave = tall.edge("wave", 60, 2)
    assert wave[0] == (0.0, 60.0) and min(u for _, u in wave) == 0 and max(u for _, u in wave) == 60
    arc, hill = tall.edge("arc", 60), tall.edge("hill", 60)
    assert arc[0][1] == 60 and arc[len(arc) // 2][1] == 0 and hill[0][1] == 0 and hill[len(hill) // 2][1] == 60
    assert tall.teeth(q(1, cut="zig")) == 8 and tall.teeth(q(1, cut="zig", teeth="99")) == 24 and tall.teeth(q(1, cut="down")) == 0
    for kind in tall.SHAPED:
        chunks = [q(1, cut=kind, slope=0, teeth=4), q(2)]
        doc = tall.document(chunks, ctx)
        assert "clip-path:polygon(0 0,100% 0,100% calc(100% - " in doc and doc.count("<polyline") == 2, kind
        assert tall.cut_depth(chunks, 0) == 60 and tall.total(chunks) == 440          # the height never changes
    assert "12.5% calc(100% - 0px)" in tall.document([q(1, cut="zig", slope=0, teeth=4), q(2)], ctx)
    assert "clip-path" not in tall.document([q(1), q(2, cut="zig")], ctx)             # never on the last chunk
    # recipes can stack with them
    from flavrpromo import recipes
    out = recipes._pictures("T", [""], [{"type": "game", "game": "A"}] * 3, "zig")
    assert [c.get("cut") for c in out[0][1]] == ["zig", "zig", "zig", "zig", None]
    assert [c.get("cut") for c in recipes._pictures("T", [""], [{"type": "game", "game": "A"}], "nope")[0][1]] == [None] * 3


async def test_a_day_can_be_classic_or_tall(tmp_path):
    """Owner 2026-11-22: "an option so i can choose between tall and classic styles" for the day pictures."""
    hosts.init(tmp_path / "pics")
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")

            async def edit(action, **extra):
                p = poster.store.get(dkey)
                data = {"d": dkey, "action": action, **{f"on_{s['id']}": "1" for s in p["sections"]}, **extra}
                assert (await c.post("/settings/article", data=data, allow_redirects=False)).status == 303
                return poster.store.get(dkey)

            p = poster.store.get(dkey)
            week, _ = await article_editor._article(poster, p)
            day = next(i for i, d in enumerate(week.days) if d)
            sec = next(s for s in p["sections"] if s["id"] == f"day{day}")
            classic = article_editor.section_html(dkey, article_editor.migrate(p), sec)
            assert "/settings/article/day?" in classic and "/settings/tall/picture" not in classic
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert f"daystyle_{day}" in page and "name=day_style" in page and "Tall pictures (each day in detail)" in page
            # one day switched to tall: its picture is built from the day recipe and shown in the day's own section
            p = await edit("save", **{f"daystyle_{day}": "tall", "day_seams": "zig"})
            tids = article_editor.day_talls(p, day)
            assert len(tids) == 1 and p["talls"][tids[0]]["day"] == str(day)
            chunks = p["talls"][tids[0]]["chunks"]
            assert [x["type"] for x in chunks].count("stream") == len(week.days[day]) and chunks[0]["cut"] == "zig"
            assert tids[0] not in [s["id"] for s in p["sections"]]                    # not a section of its own
            tall_html = article_editor.section_html(dkey, p, sec)
            assert f"/settings/tall/picture?d={dkey}&amp;t={tids[0]}" in tall_html and "/settings/article/day?" not in tall_html
            assert "<h2>" in tall_html and "<ul>" in tall_html                        # heading and stream list stay
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert f"/settings/tall?d={dkey}&t={tids[0]}" in page and "Edit the chunks" in page
            builder = await (await c.get(f"/settings/tall?d={dkey}&t={tids[0]}")).text()
            assert f"#s-day{day}" in builder                                           # "back" lands on the day
            # an edit in the builder survives a save; back to classic keeps the tall picture for later
            p["talls"][tids[0]]["chunks"][0]["title"] = "Mine"
            poster.store.put(dkey, p)
            p = await edit("save", **{f"daystyle_{day}": "classic"})
            assert "/settings/article/day?" in article_editor.section_html(dkey, p, sec)
            p = await edit("save", **{f"daystyle_{day}": "tall"})
            assert article_editor.day_talls(p, day) == tids and p["talls"][tids[0]]["chunks"][0]["title"] == "Mine"
            # "Regen from the calendar" on the day builds it anew
            p = await edit(f"regen:day{day}", **{f"daystyle_{day}": "tall"})
            new = article_editor.day_talls(p, day)
            assert len(new) == 1 and p["talls"][new[0]]["chunks"][0]["title"] != "Mine"
            # the whole article in tall style: every day with streams gets one, a day's own "classic" still wins
            other = [i for i, d in enumerate(week.days) if d and i != day]
            p = await edit("save", day_style="tall", **{f"daystyle_{day}": "classic"})
            assert all(article_editor.day_talls(p, i) for i in other) and article_editor.day_style(p, day) == "classic"
            assert article_editor.day_style(p, other[0]) == "tall" if other else True
            # the finished article uses the same pictures
            view = await (await c.get(f"/settings/article/view?d={dkey}")).text()
            assert ("/settings/tall/picture" in view) == bool(other)
    finally:
        hosts.init(None)
