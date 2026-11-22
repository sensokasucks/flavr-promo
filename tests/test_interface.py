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
