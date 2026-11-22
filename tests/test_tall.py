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


def test_a_host_picture_stands_on_the_seam_where_it_is_not_on_the_straight_line(tmp_path):
    """Owner 2026-11-22: the chibi beside a stream stopped short of the chunk's border. It stood on the line h - d
    (where the text area ends) while a diagonal seam goes down to h on the right, so a picture there floated above it."""
    hosts.init(tmp_path / "pics")
    from types import SimpleNamespace
    try:
        week = SimpleNamespace(days=[[]], day_name=lambda i: "SUN", tz=None)
        ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "H", "range": "R",
               "seed": 1, "pins": {}}
        # how far above the chunk's bottom line the seam is, at the left, middle and right (depth 60 px)
        d, diag = 60, {"cut": "down", "slope": 2}
        assert [round(tall.seam_up(diag, d, x)) for x in (0, tall.WIDTH / 2, tall.WIDTH)] == [60, 30, 0]
        assert [round(tall.seam_up(dict(diag, cut="up"), d, x)) for x in (0, tall.WIDTH)] == [0, 60]
        assert tall.seam_up({"cut": ""}, 0, 800) == 0 and tall.seam_up({"cut": "wave"}, 0, 800) == 0
        assert 0 <= tall.seam_up({"cut": "wave", "slope": 2}, d, 1500) <= d
        # a sign-off strip on the right with a diagonal below it: its feet are on the seam at its centre
        foot = tall.new_chunk("footer", [], size=0, cut="down", slope=2, pic=True)
        tail = tall.new_chunk("quote", [foot], size=0)
        h, d = tall.height(foot), tall.cut_depth([foot, tail], 0)         # the depth the picture really gets (<= 40% of h)
        fig = tall.figure(foot, dict(ctx, theme={}), h - d)
        feet = h - round(tall.seam_up(foot, d, fig["x"] + fig["w"] / 2))
        assert feet > h - d                                           # lower than the old line, on the right side
        doc = tall.document([foot, tail], ctx)
        assert f"top:{feet - fig['h']}px" in doc and f"top:{h - d - fig['h']}px" not in doc
        # the picture is cut by the row's slanted clip-path, not by the text area (which stops at h - d)
        row = doc[:doc.index("</div></div>", doc.index("<img"))]
        assert row.count("clip-path:polygon(") == 1 and row.index("clip-path") < row.index("<img")
        # a straight bottom edge is unchanged: standing on the chunk's bottom
        flat = tall.document([dict(foot, cut=""), tail], ctx)
        assert f"top:{h - tall.figure(dict(foot, cut=''), dict(ctx, theme={}), h)['h']}px" in flat
    finally:
        hosts.init(None)


def test_stream_chunks_can_be_colour_strips_like_the_day_pictures(tmp_path):
    """Owner 2026-11-22: "is there a good way to add the article styles ... to the chunk stacks as well?" A stream
    chunk with look "strip" is a tilted colour strip: time pill, framed picture with its platform badges, name and
    length, title, remark; every other strip swings right with its picture on that side; the colours go in turn."""
    hosts.init(tmp_path / "pics")
    from types import SimpleNamespace
    try:
        def tile(n, name, plats):
            return SimpleNamespace(name=name, game="Game" + str(n), title=f"title {n} #FlaVR", at=1700000000 + n * 9000, end=1, kind="past",
                                   thumb="", avatar="", length=3600, platforms=plats, url="", links={})
        week = SimpleNamespace(days=[[tile(0, "Traube", ["twitch"]), tile(1, "Cara", ["youtube"]), tile(2, "Ashe", ["twitch", "youtube"])]],
                               day_name=lambda i: "MON", tz=None)
        ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "H", "range": "R",
               "seed": 1, "pins": {}}
        chunks = [tall.new_chunk("stream", [], ref=f"d0:{i}", look="strip", line=f"remark {i}") for i in range(3)]
        chunks = tall.renumber(chunks)
        doc = tall.document(chunks, ctx)
        pal = tall.schemes.BASE["colette"]["notes"]
        assert all(f"background:{pal[i]}" in doc for i in range(3))                 # the host's note colours in turn
        assert doc.count(f"margin-left:{tall.STRIP_SWING}px") == 1 and "rotate(0.5deg)" in doc and "rotate(-0.6deg)" in doc
        assert "title 0" in doc and "#FlaVR" not in doc and "“remark 1”" in doc and "Traube" in doc and "1h 00m" in doc
        assert ">T</span>" in doc and ">Y</span>" in doc                              # platform badges on the pictures
        # the time pill is the accent colour with white lettering
        assert f'background:{tall.THEMES["colette"]["accent"]};color:#fff' in doc
        # the plain look is unchanged, and the ticks still decide what a strip shows
        plain = tall.document([dict(chunks[0], look="")], ctx)
        assert "rotate(0.5deg)" not in plain and "Traube" in plain
        bare = tall.document([dict(chunks[0], show=["name"])], ctx)
        assert "Traube" in bare and "title 0" not in bare and "remark 0" not in bare and ">T</span>" not in bare
        # Clark's strips are straight; a colour scheme brings its own note colours
        assert "rotate(0.0deg)" in tall.document(chunks, dict(ctx, host="clark"))
        ocean = tall.document(chunks, dict(ctx, scheme="ocean"))
        assert tall.schemes.get("ocean")["notes"][0] in ocean and pal[0] not in ocean
        # a strip makes a stack no taller, and an unknown look is the plain row
        assert tall.total(chunks) == 3 * tall.height(chunks[0])
        assert "rotate(0.5deg)" not in tall.document([dict(chunks[0], look="zzz")], ctx)
        # the built-in stack of strips fits and every stream chunk in it is a strip
        built = tall.BUILTIN["Colour strips"]
        assert tall.total(built) <= tall.MAX_H and [c["look"] for c in built if c["type"] == "stream"] == ["strip"] * 4
    finally:
        hosts.init(None)


def test_the_other_article_styles_are_native_chunks(tmp_path):
    """Owner 2026-11-22: "did it bring in all the styles the articles can use?" then "rebuild as native chunks": the day
    pictures' layouts on the grid chunk, the opener's sticky notes on the stats chunk and the cover's people cards."""
    hosts.init(tmp_path / "pics")
    from types import SimpleNamespace
    try:
        def tile(n, name, length, plats=("youtube",)):
            return SimpleNamespace(name=name, game="G", title=f"title {n}", at=1700000000 + n * 9000, end=1, kind="past", thumb="", avatar="",
                                   length=length, platforms=list(plats), person_id=n, url="", links={})

        class Week(SimpleNamespace):
            def tiles(self):
                return [t for d in self.days for t in d]

        day = [tile(i, f"Person{i}", 3600 * (i + 1)) for i in range(7)]
        week = Week(days=[day], day_name=lambda i: "MONDAY", tz=None, recap=True, stream_count=7, hours_live=28.4)
        notes = [{"label": "LONGEST STREAM", "value": "Person6 · 7 h"}, {"label": "MOST SHOWS", "value": "Person1 · 5"}]
        ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": notes, "facts": {}, "heading": "H", "range": "R", "seed": 1,
               "pins": {}, "comments": ["approved for the highlight reel", ""]}

        def draw(c, **more):
            return tall.document([c], dict(ctx, **more))
        # the grid layouts: each is its own picture, from the same streams, and none is taller than its chunk
        docs = {k: draw(tall.new_chunk("grid", [], size=2, day=0, layout=k)) for k in tall.GRID_LAYOUTS}
        assert len(set(docs.values())) == len(docs)
        assert "TOP PICK!" in docs["spotlight"] and "Person6" in docs["spotlight"] and "TOP PICK!" not in docs[""]
        assert docs["spotlight"].count(">Y</span>") == 1 + tall.SPOT_MAX               # the big one and at most SPOT_MAX beside it
        assert docs["timeline"].count("Person") == 5 and docs["columns"].count("Person") == 7 and docs["cards"].count("Person") == 6
        assert "grid-template-columns:repeat(2," in docs["columns"] and "repeat(3," in docs["cards"]
        assert draw(tall.new_chunk("grid", [], day=0, layout="zzz")) == draw(tall.new_chunk("grid", [], day=0))      # unknown = the wall
        assert "Nothing on this day." in draw(tall.new_chunk("grid", [], day=0, layout="cards"), week=Week(days=[[]], day_name=lambda i: "SUN", tz=None))
        # the sticky notes: tilted colour notes with the host's comment (only where one was picked); cards are unchanged
        sticky = draw(tall.new_chunk("stats", [], size=1, look="notes"))
        assert "📌 LONGEST STREAM" in sticky and "“approved for the highlight reel”" in sticky and "MOST SHOWS" in sticky
        assert sticky.count("“") == 1 and "rotate(-2.2deg)" in sticky and tall.schemes.BASE["colette"]["notes"][0] in sticky
        assert "📌" not in draw(tall.new_chunk("stats", [], size=1)) and "📌" not in draw(tall.new_chunk("stats", [], size=1, look="notes"), host="clark")
        # the people cards: the cover's people with their numbers; small shows four, the others eight
        small, big = draw(tall.new_chunk("people", [], size=0)), draw(tall.new_chunk("people", [], size=1))
        assert small.count("Person") == 4 and big.count("Person") == 7 < tall.COVER_PICS and "1 stream" in big      # all seven fit in eight
        assert "No people on the calendar yet." in draw(tall.new_chunk("people", [], size=1), week=SimpleNamespace(days=[[]], day_name=lambda i: "", tz=None))
        # a colour scheme reaches them, and the built-in stacks using them fit
        assert tall.schemes.get("ocean")["notes"][1] in draw(tall.new_chunk("people", [], size=1), scheme="ocean")
        for name in ("Week in cards", "Day spotlight", "Opener and desk"):
            assert tall.total(tall.BUILTIN[name]) <= tall.MAX_H, name
        # the reply note: the other host's answer in their own look (the opener's), the chunk's words over the article's
        ctx2 = dict(ctx, reply="the kettle is on", desk={"line": "great week", "nudge": "post Sunday", "signoff": "see you Monday"})
        memo = tall.document([tall.new_chunk("memo", [], size=1)], ctx2)
        assert "COLETTE SAYS" not in memo and "MEMO FROM CLARK" in memo and "the kettle is on" in memo     # Colette's picture: Clark answers
        assert "COLETTE SAYS" in tall.document([tall.new_chunk("memo", [])], dict(ctx2, host="clark"))
        assert "my own" in tall.document([tall.new_chunk("memo", [], line="my own", host="colette")], ctx2) and "COLETTE SAYS" in tall.document([tall.new_chunk("memo", [], host="colette")], ctx2)
        assert "Write the reply" in tall.document([tall.new_chunk("memo", [])], ctx)                          # nothing to say yet
        # the desk card: bubble + sticky note + sign-off for Colette, closing notes paper for Clark
        desk = tall.document([tall.new_chunk("desk", [], size=1)], ctx2)
        assert "FROM COLETTE" in desk and "great week" in desk and "To do for next time" in desk and "see you Monday" in desk
        clark = tall.document([tall.new_chunk("desk", [], size=1, nudge="my nudge")], dict(ctx2, host="clark"))
        assert "Closing notes" in clark and "great week" in clark and "my nudge" in clark and "post Sunday" not in clark
        assert "Write the desk lines" in tall.document([tall.new_chunk("desk", [], size=1)], ctx)
        # strips for game chunks (same colours and swing as the stream strips) and the cover's title block on a header
        games = {"g": {"game": "G", "streams": 3, "people": ["Person1"], "tags": ["new"]}}
        gs = tall.document([tall.new_chunk("game", [], size=1, game="G", look="strip", line="nice")] * 2, dict(ctx, games=games))
        assert gs.count("NEW GAME") == 2 and "“nice”" in gs and "Person1 · 3 streams" in gs and "margin-left:180px" in gs
        assert "margin-left:180px" not in tall.document([tall.new_chunk("game", [], size=1, game="G", look="strip")], dict(ctx, games=games))
        cover = tall.document([tall.new_chunk("header", [], size=1, look="cover")], ctx)
        assert "7 streams · 28 hours live" in cover and "<img" in cover
        assert "1 stream this week" in tall.document([tall.new_chunk("header", [], size=1, look="cover")], dict(ctx, week=Week(days=[[day[0]]], day_name=lambda i: "", tz=None)))
        assert "FILED BY CLARK" in tall.document([tall.new_chunk("header", [], size=1, look="cover")], dict(ctx, host="clark"))
        assert "FILED BY CLARK" not in tall.document([tall.new_chunk("header", [], size=1)], dict(ctx, host="clark"))
    finally:
        hosts.init(None)
