"""Colour schemes for the article's pictures (flavrpromo/schemes.py): the schemes stay readable, a host
card page is recoloured by role and only inside its styles, a draft's choice resolves the same way
every time, tall pictures take the scheme as their theme, and the article editor saves and draws it."""

from flavrpromo import article_editor, hosts, schemes, tall

from test_settings_round2 import _client, _poster


def test_every_scheme_is_readable():
    # the rules a scheme must keep so every card still reads: light text on the backgrounds, dark ink on
    # light paper, an accent that works as lettering on the background AND under white lettering
    for key, s in list(schemes.SCHEMES.items()) + list(schemes.BASE.items()):
        assert all(len(s[r]) == 7 and s[r].startswith("#") for r in schemes.ROLES), key
        assert len(s["notes"]) == 4 and s["name"], key
        assert schemes.contrast(s["fg"], s["bg1"]) >= 7, key
        assert schemes.contrast(s["fg"], s["bg2"]) >= 4.5, key
        assert schemes.contrast(s["ink"], s["paper"]) >= 10, key
        assert schemes.contrast(s["accent"], s["bg0"]) >= 4, key
        assert schemes.contrast(s["gold"], s["bg1"]) >= 5, key
        assert schemes.contrast("#ffffff", s["accent"]) >= 2.3, key
        assert all(schemes.contrast(s["ink"], n) >= 6 for n in s["notes"]), key       # dark writing on the notes
    # the menu: every built-in scheme, then the OTHER host's own colours
    assert [k for k, _ in schemes.names("colette")] == list(schemes.SCHEMES) + ["clark"]
    assert schemes.get("") is None and schemes.get("nope") is None and schemes.get("clark") is schemes.BASE["clark"]


def test_swap_goes_by_role():
    ocean = schemes.SCHEMES["ocean"]
    # each host's own role colour becomes the scheme's colour of that role
    assert schemes.swap("#f72ca2", "ocean") == ocean["accent"] == schemes.swap("#E0782E", "ocean")
    assert schemes.swap("#1b1018", "ocean") == ocean["bg0"] and schemes.swap("#3a2416", "ocean") == ocean["bg1"]
    assert schemes.swap("#f4ead8", "ocean") == ocean["paper"] and schemes.swap("#2b1d12", "ocean") == ocean["ink"]
    assert schemes.swap("#f8cf33", "ocean") == ocean["gold"]
    # sticky notes map note for note
    assert [schemes.swap(c, "ocean") for c in schemes.BASE["colette"]["notes"]] == list(ocean["notes"])
    assert [schemes.swap(c, "ocean") for c in schemes.BASE["clark"]["notes"]] == list(ocean["notes"])
    # a darker shade of a role stays a darker shade of the scheme's colour
    assert schemes.luminance(schemes.swap("#c21c80", "ocean")) < schemes.luminance(ocean["accent"])
    assert schemes.luminance(schemes.swap("#5a4030", "ocean")) < schemes.luminance(schemes.swap("#8a5a33", "ocean"))
    # Clark's rule lines and small print follow the paper, not "gold"
    assert schemes.swap("#d8c3a3", "ocean") == schemes.mix(ocean["paper"], ocean["ink"], 0.2)
    # left alone: greys, black, white, the platform badges, the live clock, Clark's stamp, anything unknown
    for c in ("#ffffff", "#000000", "#1a1a1a", "#9aa3ad", "#ff0033", "#9146ff", "#53fc18", "#e5312f", "#b8402a"):
        assert schemes.swap(c, "ocean") == c
    assert schemes.swap("#f72ca2", "") == "#f72ca2" == schemes.swap("#f72ca2", "nope")
    # the other host's colours are a scheme too
    assert schemes.swap("#f72ca2", "clark") == schemes.BASE["clark"]["accent"]


def test_recolour_only_touches_styles():
    ocean = schemes.SCHEMES["ocean"]
    page = ('<html><head><style>.a{color:#f72ca2;background:#1b1018}</style></head><body>'
            '<div style="border:5px solid #f72ca2;box-shadow:0 0 4px #0007;background:#f72ca255;color:#fff">'
            'Playing #beef and #f72ca2 tonight &quot;style=#f72ca2&quot;</div>'
            '<img src="data:image/png;base64,AAAA" style="outline:1px solid #F8CF33"></body></html>')
    out = schemes.recolour(page, "ocean")
    assert f".a{{color:{ocean['accent']};background:{ocean['bg0']}}}" in out
    assert f"border:5px solid {ocean['accent']};box-shadow:0 0 4px #00000077;background:{ocean['accent']}55;color:#ffffff" in out
    assert "Playing #beef and #f72ca2 tonight &quot;style=#f72ca2&quot;" in out          # a title is never recoloured
    assert f"outline:1px solid {ocean['gold']}" in out and "base64,AAAA" in out
    assert schemes.recolour(page, "") is page and schemes.recolour(page, "nope") is page


def test_which_scheme_a_picture_gets():
    p = {"host": "colette", "seed": 7, "scheme": "", "schemes": {}}
    assert schemes.of(p, "intro") == ""                                  # the host's own colours
    p["scheme"] = "forest"
    assert schemes.of(p) == schemes.of(p, "day2") == "forest"
    p["scheme"] = "colette"                                              # her own colours are not a scheme for her
    assert schemes.of(p) == ""
    p["scheme"] = "clark"
    assert schemes.of(p) == "clark"
    # one picture's own choice wins; "host" keeps the host's colours whatever the article says
    p["scheme"], p["schemes"] = "forest", {"intro": "ocean", "outro": "host", "day1": "nope"}
    assert (schemes.of(p, "intro"), schemes.of(p, "outro"), schemes.of(p, "day1")) == ("ocean", "", "forest")
    # surprise: one scheme for the whole article, the same until the seed changes
    p["scheme"], p["schemes"] = schemes.RANDOM, {}
    one = schemes.of(p)
    assert one and schemes.get(one) and all(schemes.of(p, part) == one for part in ("intro", "day0", "tall3"))
    assert len({schemes.of(dict(p, seed=n)) for n in range(60)}) > 5
    # mix: per picture, steady for that picture, and not all the same
    p["scheme"] = schemes.MIX
    parts = ["", "intro", "outro"] + [f"day{i}" for i in range(7)] + [f"tall{i}" for i in range(6)]
    got = [schemes.of(p, part) for part in parts]
    assert got == [schemes.of(p, part) for part in parts] and len(set(got)) > 4 and all(schemes.get(k) for k in got)


def test_tall_picture_in_a_scheme(tmp_path):
    week = _poster(tmp_path).build_review("flavr", "week")
    chunks = [{"id": "c0", "type": "header", "size": 0, "title": "Week", "sub": "Nov 16 - 19", "cut": "down"},
              {"id": "c1", "type": "host", "size": 1, "host": "", "kind": "happy", "var": "", "side": "left", "line": "Hello"},
              {"id": "c2", "type": "chat", "size": 1, "host": "", "other": "", "lines": "One\nTwo"}]
    ctx = {"host": "colette", "week": week, "img": lambda u: "", "notes": [], "facts": {}, "heading": "Week",
           "range": "", "seed": 1, "pins": {}, "games": {}, "info": {}}
    own = tall.document(chunks, ctx)
    assert "#f72ca2" in own and "#e0782e" in own                 # her pink, and Clark's orange for his chat avatar
    assert tall.document(chunks, dict(ctx, scheme="")) == own == tall.document(chunks, dict(ctx, scheme="nope"))
    ocean, doc = schemes.SCHEMES["ocean"], tall.document(chunks, dict(ctx, scheme="ocean"))
    assert "#f72ca2" not in doc and "#e0782e" not in doc and "#3d1233" not in doc
    assert ocean["accent"] in doc and ocean["gold"] in doc and ocean["bg1"] in doc and ocean["paper"] in doc
    assert schemes.bands("ocean")[1] in doc                       # the chunk under the cut takes the scheme's band
    assert "'DejaVu Sans'" in doc                                 # the lettering stays the host's
    assert schemes.theme("", "x") is None and schemes.bands("") is None


async def test_article_editor_colour_schemes(tmp_path):
    hosts.init(tmp_path / "pics")
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes) as c:
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            dkey = article_editor.draft_key("flavr", "week")
            p = poster.store.get(dkey)
            # the menus: one for the article on the Look card, one on each picture's card, with colour dots
            assert "<select name=scheme>" in page and "Surprise me" in page and "Mix (a different scheme" in page
            assert 'name="scheme_intro"' in page and "Clark&#x27;s cocoa and cream" in page and "<span class=sw>" in page
            day = next(s["id"] for s in p["sections"] if s["id"].startswith("day"))
            assert f'name="scheme_{day}"' in page

            async def act(**extra):
                data = {"d": dkey, "action": "save", **{f"on_{s['id']}": "1" for s in p["sections"]}}
                data.update(extra)
                assert (await c.post("/settings/article", data=data, allow_redirects=False)).status == 303
                return poster.store.get(dkey)

            def pink(doc):
                return "#f72ca2" in doc.lower()

            before = article_editor.stamp(p, "intro")
            await c.get(f"/settings/article/picture?d={dkey}&sec=intro")
            assert pink(poster.shooter.docs[-1])                              # her own colours to start with
            p = await act(scheme="ocean", pic_intro="opener")
            assert p["scheme"] == "ocean" and article_editor.stamp(p, "intro") != before   # the picture is drawn again
            await c.get(f"/settings/article/picture?d={dkey}&sec=intro")
            assert not pink(poster.shooter.docs[-1]) and schemes.SCHEMES["ocean"]["accent"] in poster.shooter.docs[-1]
            await c.get(f"/settings/article/day?d={dkey}&day={day[3:]}")
            assert not pink(poster.shooter.docs[-1])
            await c.get(f"/settings/article/cover?d={dkey}")
            assert not pink(poster.shooter.docs[-1]) and schemes.SCHEMES["ocean"]["bg0"] in poster.shooter.docs[-1]
            # one picture keeps the host's colours, another takes its own scheme; nonsense is ignored
            p = await act(scheme="ocean", scheme_intro="host", **{f"scheme_{day}": "forest"}, scheme_outro="nope")
            assert p["schemes"] == {"intro": "host", day: "forest"}
            await c.get(f"/settings/article/picture?d={dkey}&sec=intro")
            assert pink(poster.shooter.docs[-1])
            await c.get(f"/settings/article/day?d={dkey}&day={day[3:]}")
            assert schemes.SCHEMES["forest"]["accent"] in poster.shooter.docs[-1]
            p = await act(scheme="nope")                                       # an unknown scheme changes nothing
            assert p["scheme"] == "ocean"
            p = await act(scheme="", scheme_intro="", **{f"scheme_{day}": ""})
            assert p["scheme"] == "" and p["schemes"] == {}
            # a tall picture made for a day goes by that day's choice
            p["day_talls"], p["schemes"] = {day[3:]: ["tall9"]}, {day: "royal"}
            assert article_editor.scheme_for(p, "tall9") == "royal" and article_editor.scheme_for(p, "tall1") == ""
    finally:
        hosts.init(None)
