"""Tall pictures from chunks (flavrpromo/tall.py, tall_page.py, the article editor's "+ Add a tall picture"):
the height meter, building a stack with menus, saved chunks and stacks, the mix of regular and chibi
pictures, and the picture drawn at its real height."""

from flavrpromo import article_editor, hosts, tall, tall_page
from test_settings_round2 import _client, _poster


def test_heights_and_builtin_stacks_fit_the_limit():
    assert tall.MAX_H == 2133 and tall.WIDTH == 1600
    for name, chunks in tall.BUILTIN.items():
        assert tall.total(chunks) <= tall.MAX_H, name
    c = tall.new_chunk("host", [{"id": "c4", "type": "quote"}], kind="chibi_sleepy")
    assert c["id"] == "c5" and c["kind"] == "chibi_sleepy" and tall.height(c) == 520
    assert [x["id"] for x in tall.renumber([{"id": "z"}, {"id": "q"}])] == ["c1", "c2"]


async def test_build_a_tall_picture_with_menus(tmp_path):
    hosts.init(tmp_path / "pics")                   # built-in pictures on
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")

            async def edit(action, **extra):
                p = poster.store.get(dkey)
                data = {"d": dkey, "action": action, **{f"on_{s['id']}": "1" for s in p["sections"]}}
                data.update(extra)
                r = await c.post("/settings/article", data=data, allow_redirects=False)
                assert r.status == 303
                return poster.store.get(dkey)

            p = await edit("add_tall")
            assert "tall1" in p["talls"] and [s["id"] for s in p["sections"]][-2] == "tall1"
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert "Edit the chunks" in page and "/settings/tall/picture?d=" in page

            async def build(action, **extra):
                data = {"d": dkey, "t": "tall1", "action": action, **extra}
                r = await c.post("/settings/tall", data=data, allow_redirects=False)
                assert r.status == 303, await r.text()
                return poster.store.get(dkey)["talls"]["tall1"]["chunks"]

            builder = await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            assert "FlaVR Promo</h2>" in builder and "Host moment" in builder and "px</b>" in builder
            chunks = poster.store.get(dkey)["talls"]["tall1"]["chunks"]
            assert [x["type"] for x in chunks] == ["header", "host", "stats", "footer"]
            # menus: the host moment's own line, a chibi pose, the host on the right, and the quote chunk
            chunks = await build("save", **{"c2__kind": "chibi_pointing", "c2__side": "right", "c2__line": "Look at this week!",
                                            "c2__size": "2", "c1__title": "BIG WEEK"})
            assert chunks[1]["kind"] == "chibi_pointing" and chunks[1]["side"] == "right" and chunks[1]["size"] == 2
            assert chunks[1]["line"] == "Look at this week!" and chunks[0]["title"] == "BIG WEEK"
            # a line taken from the article's own lines (menu), a bad host / pose is ignored
            first_line = next(iter(next(iter(poster.store.get(dkey)["candidates"].values()))))
            chunks = await build("save", **{"c2__pick_line": first_line, "c2__kind": "nope", "c2__host": "ghost"})
            assert chunks[1]["line"] == first_line and chunks[1]["kind"] == "chibi_pointing" and chunks[1]["host"] == ""
            chunks = await build("save", **{"c1__cut": "down", "c1__slope": "2", "c2__cut": "sideways"})
            assert chunks[0]["cut"] == "down" and chunks[0]["slope"] == 2 and not chunks[1].get("cut")
            chunks = await build("save", **{"c1__cut": ""})
            chunks = await build("add", newtype="grid")
            assert chunks[-1]["type"] == "grid" and chunks[-1]["id"] == "c5"
            chunks = await build("add", newtype="grid")
            # the meter: Large host + two day grids is over 2133 → a warning, the picture is still drawn
            assert tall.total(chunks) > tall.MAX_H
            assert "crop" in await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            chunks = await build("del:c6")
            chunks = await build("del:c5")
            chunks = await build("down:c1")
            assert [x["id"] for x in chunks][:2] == ["c2", "c1"]
            chunks = await build("dup:c4")
            assert len(chunks) == 5 and chunks[4]["id"] == "c5"
            # hero and chat chunks: their own boxes, the V / peak edges
            chunks = await build("add", newtype="hero")
            hid = chunks[-1]["id"]
            chunks = await build("add", newtype="chat")
            cid = chunks[-1]["id"]
            chunks = await build("save", **{f"{hid}__title": "Colette", f"{hid}__top": "Meet", f"{hid}__tag": "Coffee first",
                                            f"{hid}__cut": "v", f"{cid}__lines": "Hi!\n\n  Hello   there \nBye", f"{cid}__other": "clark",
                                            f"{cid}__cut": "nonsense"})
            hero, chat = chunks[-2], chunks[-1]
            assert hero["title"] == "Colette" and hero["tag"] == "Coffee first" and hero["cut"] == "v"
            assert chat["lines"] == "Hi!\nHello there\nBye" and chat["other"] == "clark" and not chat.get("cut")
            page = await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            assert "V shape" in page and "Lines, one per row" in page and "Tagline" in page
            await build(f"del:{cid}")
            await build(f"del:{hid}")
            # saved chunk + saved stack, used again
            await build("savechunk:c2", **{"c2__savename": "Pointing chibi"})
            assert poster.store.get("tall_chunks")["Pointing chibi"]["kind"] == "chibi_pointing"
            chunks = await build("insert", insert="Pointing chibi")
            assert chunks[-1]["kind"] == "chibi_pointing" and chunks[-1]["id"] == "c6"
            await build("savetpl", tplname="My stack")
            assert [x["id"] for x in poster.store.get("tall_templates")["My stack"]][:2] == ["c1", "c2"]
            chunks = await build("load", stack="b:Day in detail")
            assert [x["type"] for x in chunks] == ["header", "grid", "host", "quote"]
            chunks = await build("load", stack="t:My stack")
            assert len(chunks) == 6
            await build("delsaved", delwhat="c:Pointing chibi")
            assert "Pointing chibi" not in (poster.store.get("tall_chunks") or {})
            # the picture: drawn at its real height with the chunks' contents
            chunks = await build("load", stack="b:Week overview")
            r = await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            assert r.status == 200
            doc = poster.shooter.docs[-1]
            assert f"height:{tall.total(chunks)}px" in doc and "BIG WEEK" not in doc and "<img" in doc
            assert poster.shooter.sizes[-1] == (1600, tall.total(chunks))
            # the section is in the finished article as a Save block, and Remove takes it out again
            view = await (await c.get(f"/settings/article/view?d={dkey}")).text()
            assert "/settings/tall/picture?d=" in view.split('id="body"')[1]
            p = await edit("remove:tall1")
            assert "tall1" not in p["talls"] and "tall1" not in [s["id"] for s in p["sections"]]
    finally:
        hosts.init(None)


def test_document_mixes_regular_and_chibi_and_pins_a_pool_picture(tmp_path):
    hosts.init(tmp_path, defaults=False)
    (tmp_path / "colette").mkdir(parents=True, exist_ok=True)
    (tmp_path / "colette" / "happy.png").write_bytes(b"\x89main-happy")
    (tmp_path / "colette" / "chibi_sleepy.png").write_bytes(b"\x89chibi-sleepy")
    assert hosts.add_to_pool("colette", "happy", b"\x89second-happy", "a.png") == ""
    from types import SimpleNamespace
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {"streams": 3, "hours": 9},
           "heading": "This Week", "range": "Nov 15-21", "seed": 1, "pins": {}}
    chunks = [{"id": "c1", "type": "host", "size": 1, "host": "", "kind": "happy", "var": "1", "side": "left", "line": "Hi!"},
              {"id": "c2", "type": "host", "size": 0, "host": "colette", "kind": "chibi_sleepy", "var": "", "side": "right",
               "line": "Sleepy."},
              {"id": "c3", "type": "stats", "size": 0}, {"id": "c4", "type": "quote", "size": 0, "text": "Wow"},
              {"id": "c5", "type": "stream", "size": 0, "ref": "d9:9"}]
    try:
        doc = tall.document(chunks, ctx)
        import base64
        assert base64.b64encode(b"\x89second-happy").decode() in doc          # chunk 1 pinned the pool picture
        assert base64.b64encode(b"\x89chibi-sleepy").decode() in doc          # chunk 2: a chibi in the same picture
        assert "Hi!" in doc and "Sleepy." in doc and "STREAMS" in doc and "Wow" in doc and "Pick a stream" in doc
        assert "Nov 15-21" not in doc                                        # no header chunk in this stack
        assert tall.total(chunks) == 520 + 380 + 150 + 170 + 200
    finally:
        hosts.init(None)


def test_diagonal_cuts_clip_the_edge_and_keep_the_height(tmp_path):
    hosts.init(tmp_path, defaults=False)
    from types import SimpleNamespace
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "clark", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "H", "range": "R",
           "seed": 1, "pins": {}}
    chunks = [{"id": "c1", "type": "quote", "size": 1, "text": "One", "cut": "down", "slope": 2},
              {"id": "c2", "type": "quote", "size": 1, "text": "Two", "cut": "up", "slope": 0},
              {"id": "c3", "type": "quote", "size": 1, "text": "Three", "cut": "down", "slope": 1},   # last: no cut
              ]
    try:
        assert [tall.cut_depth(chunks, i) for i in range(3)] == [88, 60, 0]     # steep clamps to 40% of the height
        doc = tall.document(chunks, ctx)
        assert "polygon(0 0,100% 0,100% 100%,0 calc(100% - 88px))" in doc         # down: left edge higher
        assert "polygon(0 0,100% 0,100% calc(100% - 60px),0 100%)" in doc          # up: right edge higher
        assert doc.count("<polyline") == 4 and "<svg" in doc                           # a stripe (2 lines) per cut
        assert f"height:{tall.total(chunks)}px" in doc and "#563520" in doc        # Clark's band colours
        straight = tall.document([dict(c, cut="") for c in chunks], ctx)
        assert "clip-path" not in straight and "<svg" not in straight
        assert tall.cut_depth([dict(chunks[0], cut="")] + chunks, 0) == 0
        assert "Slants down" in tall.CUTS["down"] and tall.total(tall.BUILTIN["Week overview (diagonal)"]) <= tall.MAX_H
    finally:
        hosts.init(None)


def test_v_cuts_hero_and_chat_chunks(tmp_path):
    # the "Luna" style pieces: V / peak seams, a hero opening on an angled panel, two hosts chatting
    import base64
    from types import SimpleNamespace
    hosts.init(tmp_path, defaults=False)
    for key, data in (("colette", b"\x89col-head"), ("clark", b"\x89clark-head"), ("colette", None)):
        (tmp_path / key).mkdir(parents=True, exist_ok=True)
        if data:
            (tmp_path / key / "head.png").write_bytes(data)
    (tmp_path / "colette" / "happy.png").write_bytes(b"\x89col-happy")
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "H",
           "range": "Nov 15-21", "seed": 1, "pins": {}}
    chunks = [{"id": "c1", "type": "hero", "size": 1, "cut": "v", "top": "Meet", "title": "", "sub": "", "tag": "",
               "host": "", "kind": "happy", "var": ""},
              {"id": "c2", "type": "chat", "size": 1, "cut": "peak", "lines": "Hi there!\nHello!\nBig week.", "host": "", "other": ""},
              {"id": "c3", "type": "quote", "size": 0, "text": "End"}]
    try:
        doc = tall.document(chunks, ctx)
        assert "MEET" not in doc and ">Meet<" in doc and ">COLETTE<" not in doc and "Colette" in doc     # first name, upper-cased by CSS
        assert "Marketing" in doc and "Nov 15-21" in doc                                  # job and the date range as defaults
        assert base64.b64encode(b"\x89col-happy").decode() in doc                          # the big hero picture
        assert "clip-path:polygon(24% 0" in doc                                            # the angled colour panel
        assert doc.count("<polyline") == 4                                                 # a stripe (2 lines) per cut
        assert f"100% calc(100% - {tall.cut_depth(chunks, 0)}px),{tall.V_AT}% 100%" in doc    # V seam
        assert f"{tall.V_AT}% calc(100% - {tall.cut_depth(chunks, 1)}px)" in doc               # peak seam
        # the chat: three rows taking turns between the two hosts, each with that host's head as the avatar
        assert doc.count("Hi there!") == doc.count("Hello!") == doc.count("Big week.") == 1
        assert base64.b64encode(b"\x89col-head").decode() in doc and base64.b64encode(b"\x89clark-head").decode() in doc
        assert "flex-direction:row-reverse" in doc
        assert tall.total(tall.BUILTIN["Hero and chat (diagonal)"]) <= tall.MAX_H
    finally:
        hosts.init(None)


def test_host_pictures_scale_turn_flip_and_sit_on_any_chunk(tmp_path):
    """Owner 2026-11-22: scale / rotate / flip the character, and a host picture on every chunk type."""
    hosts.init(tmp_path / "pics")                   # built-in pictures on
    from types import SimpleNamespace
    week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {"streams": 3, "hours": 9},
           "heading": "This Week", "range": "Nov 15-21", "seed": 1, "pins": {}}
    try:
        plain = {"id": "c1", "type": "quote", "size": 0, "text": "Wow"}
        assert not tall.has_figure(plain) and "<img" not in tall.document([plain], ctx)
        withpic = dict(plain, pic=True, side="left", kind="chibi_happy", pscale=250, prot=-12, pflip=True, px=30, py=-40)
        assert tall.has_figure(withpic)
        doc = tall.document([withpic], ctx)
        assert "translate(30px,-40px) rotate(-12deg) scale(2.50) scaleX(-1)" in doc and "left:40px" in doc
        assert "transform-origin:50% 100%" in doc
        for t in ("header", "stats", "grid", "host", "footer", "hero"):     # every type can carry one
            c = tall.new_chunk(t, [], pic=True)
            assert tall.has_figure(c) and "transform:translate(0px,0px) rotate(0deg) scale(1.00)" in tall.document([c], ctx), t
        # numbers out of range are pulled in; nonsense falls back to the default
        assert tall._num({"pscale": 9999}, "pscale") == 400 and tall._num({"prot": "x"}, "prot") == 0
        # inside the chunk it is cut off at the chunk's edges; "stick out" moves it to the layer over everything
        foot = tall.new_chunk("footer", [plain], pscale=200, size=0)
        small, big = tall.figure(dict(foot, pscale=100), dict(ctx, theme={}), 260), tall.figure(foot, dict(ctx, theme={}), 260)
        assert big["room"] == 2 * small["room"] and big["w"] == small["w"]      # a bigger host pushes the bubble aside
        doc = tall.document([plain, foot], ctx)
        assert doc.index("<img") < doc.index("z-index:100")
        doc = tall.document([plain, dict(foot, ppop=True)], ctx)
        layer = doc[doc.index("z-index:100"):]
        assert "<img" in layer and f"top:{170 + 260 - (260 - 30)}px" in layer        # standing on its chunk's bottom edge
        assert tall.total([plain, foot]) == 170 + 260                               # the picture never changes the height
        # hashtags at the end of a stream title are dropped unless ticked
        t = SimpleNamespace(name="Ashe", game="", title="tanks and vibes #FlaVR #vtuber", at=0, end=None, kind="scheduled",
                            thumb="", avatar="", length=0)
        w2 = SimpleNamespace(days=[[t]], day_name=lambda i: "MON", tz=None)
        import flavrpromo.tall as tl
        clock, tl.clock = tl.clock, lambda at, tz: "7 PM"
        try:
            s = {"id": "c1", "type": "stream", "size": 1, "ref": "d0:0"}
            assert "#FlaVR" not in tall.document([s], dict(ctx, week=w2)) and "tanks and vibes" in tall.document([s], dict(ctx, week=w2))
            assert "#FlaVR" in tall.document([dict(s, show=["title", "hashtags"])], dict(ctx, week=w2))
        finally:
            tl.clock = clock
    finally:
        hosts.init(None)


async def test_builder_saves_the_picture_controls(tmp_path):
    hosts.init(tmp_path / "pics")
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes, tall_page.add_routes) as c:
            await c.get("/settings/article?group=flavr&which=week")
            dkey = article_editor.draft_key("flavr", "week")
            p = poster.store.get(dkey)
            data = {"d": dkey, "action": "add_tall", **{f"on_{s['id']}": "1" for s in p["sections"]}}
            await c.post("/settings/article", data=data, allow_redirects=False)

            async def build(**extra):
                r = await c.post("/settings/tall", data={"d": dkey, "t": "tall1", "action": "save", **extra}, allow_redirects=False)
                assert r.status == 303
                return poster.store.get(dkey)["talls"]["tall1"]["chunks"]

            page = await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            assert "c2__pscale" in page and "Mirror" in page and "c1__pic" in page and "c1__pscale" not in page
            # the host moment's picture: bigger, turned, mirrored, sticking out; silly numbers are pulled in
            ch = await build(c2__figed="1", c2__pscale="180", c2__prot="-15", c2__pflip="1", c2__ppop="1", c2__px="5000",
                             c1__title="T")
            assert (ch[1]["pscale"], ch[1]["prot"], ch[1]["pflip"], ch[1]["ppop"], ch[1]["px"]) == (180, -15, True, True, 1600)
            # a partial post (no tick boxes on the page) keeps the mirror; a full one without it clears it
            ch = await build(c2__pscale="150", c1__title="T")
            assert ch[1]["pflip"] is True and ch[1]["pscale"] == 150
            ch = await build(c2__figed="1", c2__pscale="150", c1__title="T")
            assert ch[1]["pflip"] is False and ch[1]["ppop"] is False
            # the header (optional picture): tick it, then its menus and numbers show and save
            ch = await build(c1__figed="1", c1__pic="1", c1__title="T")
            assert ch[0]["pic"] is True
            page = await (await c.get(f"/settings/tall?d={dkey}&t=tall1")).text()
            assert "c1__pscale" in page and "c1__kind" in page
            ch = await build(c1__figed="1", c1__pic="1", c1__kind="chibi_pointing", c1__side="left", c1__pscale="60", c1__title="T")
            assert ch[0]["kind"] == "chibi_pointing" and ch[0]["side"] == "left" and ch[0]["pscale"] == 60
            await c.get(f"/settings/tall/picture?d={dkey}&t=tall1")
            assert "scale(0.60)" in poster.shooter.docs[-1] and "scale(1.50)" in poster.shooter.docs[-1]
    finally:
        hosts.init(None)
