"""The settings page (/settings, flavrpromo/settings_page.py): KoboldCpp settings over the
environment's, hosts on / off, picture upload and "back to built-in", and edited host lines."""

import random

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from flavrpromo import hosts, settings_page
from flavrpromo.store import Store


class Poster:
    def __init__(self, store):
        self.store, self.kobold, self.http = store, None, object()
        self.kobold_env = {"url": "http://env:5001", "key": "envpw"}


async def _client(poster):
    from aiohttp import web
    app = web.Application(client_max_size=10 * 1024 * 1024)
    settings_page.add_routes(app, poster)
    return TestClient(TestServer(app))


def test_every_template_slot_has_help():
    for key, slots in hosts.TEMPLATES.items():
        assert set(slots) <= set(hosts.SLOT_HELP), key
        for slot, rows in slots.items():
            assert not any(hosts.bad_blanks(r) for r in rows), (key, slot)


async def test_kobold_settings_override_the_environment():
    store = Store(":memory:")
    poster = Poster(store)
    settings_page.apply(poster)
    assert poster.kobold.url == "http://env:5001" and poster.kobold.key == "envpw"
    async with await _client(poster) as c:
        r = await c.post("/settings/kobold", data={"url": "192.168.1.9:5001/", "temperature": "1.2", "per_slot": "9",
                                                   "action": "save"}, allow_redirects=False)
        assert r.status == 303
        k = poster.kobold
        assert (k.url, k.key, k.temperature, k.per_slot) == ("http://192.168.1.9:5001", "envpw", 1.2, 6)
        page = await (await c.get("/settings")).text()
        assert "envpw" not in page and "(set, leave empty to keep)" in page     # the password is never shown
        await c.post("/settings/kobold", data={"url": "", "clear_key": "1"}, allow_redirects=False)
        assert poster.kobold is None                                           # empty address = off
        r = await c.post("/settings/kobold", data={"url": "", "action": "test"}, allow_redirects=False)
        assert "KoboldCpp%20is%20off" in r.headers["Location"]


async def test_hosts_switches_and_pictures(tmp_path):
    store = Store(":memory:")
    poster = Poster(store)
    hosts.init(tmp_path)
    try:
        async with await _client(poster) as c:
            await c.post("/settings/hosts", data={"on": "1", "only": "clark"}, allow_redirects=False)
            assert store.get("hosts_on") and store.get("hosts_only") == "clark"
            await c.post("/settings/hosts", data={"only": "nobody"}, allow_redirects=False)
            assert not store.get("hosts_on") and store.get("hosts_only") == ""
            page = await (await c.get("/settings/pictures")).text()
            assert "/settings/picture/colette/chibi_desk" in page                  # built-in pictures shown
            assert "FlaVR Promo</h2>" in page and 'class=on' in page               # drawn in the panel (flavrpromo/panel.py)
            assert "/settings/lines" in page and "<b>🖼️ Pictures</b>" in page     # its tab row
            # the tidy layout (owner 2026-11-22): a folding card per host, a folding group per kind family, every
            # kind in exactly one group, rows that update in place (quick forms, flavrpromo/panel.py) and take drops
            grouped = [k for _, _, kinds in settings_page.PICTURE_GROUPS for k in kinds]
            assert sorted(grouped) == sorted(hosts.KINDS)
            for key in hosts.HOSTS:
                assert f'<details class=card id="pics-{key}" open>' in page and f'data-swap-id="count-{key}"' in page
                for gid, _, kinds in settings_page.PICTURE_GROUPS:
                    assert f'id="pics-{key}-{gid}"' in page
                    assert all(f'data-swap-id="pool-{key}-{k}"' in page for k in kinds)
            assert "10 pictures · 0 your own" in page and "data-quick" in page
            assert 'data-dropzone=add-colette-happy' in page and 'id="add-colette-happy"' in page
            assert 'data-dropzone=main-clark-head' in page and 'id="add-clark-head"' not in page   # heads stay single
            assert "value=reset" not in page                                       # nothing uploaded yet
            assert (await c.get("/settings/picture/clark/head")).status == 200
            form = aiohttp.FormData()
            form.add_field("host", "clark")
            form.add_field("kind", "head")
            form.add_field("action", "upload")
            form.add_field("file", b"PNG" * 1000, filename="face.png", content_type="image/png")
            r = await c.post("/settings/picture", data=form, allow_redirects=False)
            assert "Saved" in r.headers["Location"] and hosts.pictures("clark")["head"] == "yours"
            page = await (await c.get("/settings/pictures")).text()
            assert "main · yours" in page and "value=reset" in page and "10 pictures · 1 your own" in page
            r = await c.post("/settings/picture", data={"host": "clark", "kind": "head", "action": "reset"},
                             allow_redirects=False)
            assert hosts.pictures("clark")["head"] == "built-in"
            assert (await c.get("/settings/picture/clark/nope")).status == 404
    finally:
        hosts.init(None)


async def test_edited_lines():
    store = Store(":memory:")
    poster = Poster(store)
    settings_page.apply(poster)
    async with await _client(poster) as c:
        r = await c.post("/settings/lines", data={"host": "clark", "live_start": "Oops {nme} is live"},
                         allow_redirects=False)
        assert "unknown%20blanks" in r.headers["Location"] and not store.get("host_templates")
        await c.post("/settings/lines", data={"host": "clark", "live_start": "  {name}   is on.  \n\nHello {name}!"},
                     allow_redirects=False)
        assert store.get("host_templates")["clark"] == {"live_start": ["{name} is on.", "Hello {name}!"]}
        assert hosts.live_line("clark", "start", "Lulu", rng=random.Random(3)) in ("Lulu is on.", "Hello Lulu!")
        assert hosts.templates("clark", "live_end") == hosts.TEMPLATES["clark"]["live_end"]   # untouched slot
        await c.post("/settings/lines", data={"host": "clark", "action": "reset"}, allow_redirects=False)
        assert hosts.templates("clark", "live_start") == hosts.TEMPLATES["clark"]["live_start"]


async def test_picture_pool_upload_remove_and_pick(tmp_path):
    # extra pictures per kind: add several at once, thumbnails serve, remove one; the pick follows pins / seed
    store = Store(":memory:")
    poster = Poster(store)
    hosts.init(tmp_path, defaults=False)
    (tmp_path / "colette").mkdir(parents=True, exist_ok=True)
    (tmp_path / "colette" / "happy.png").write_bytes(b"main")
    try:
        async with await _client(poster) as c:
            form = aiohttp.FormData()
            form.add_field("host", "colette")
            form.add_field("kind", "happy")
            form.add_field("action", "add")
            form.add_field("file", b"one", filename="a.png", content_type="image/png")
            form.add_field("file", b"two", filename="b.webp", content_type="image/webp")
            form.add_field("file", b"bad", filename="c.gif", content_type="image/gif")
            r = await c.post("/settings/pool", data=form, allow_redirects=False)
            assert "Added%202%20pictures" in r.headers["Location"] and "c.gif" in r.headers["Location"]
            assert [v for v, _ in hosts.variants("colette", "happy")] == ["main", "1", "2"]
            assert await (await c.get("/settings/picture/colette/happy?v=2")).read() == b"two"
            assert (await c.get("/settings/picture/colette/happy?v=9")).status == 404
            page = await (await c.get("/settings/pictures")).text()
            assert "/settings/picture/colette/happy?v=1" in page and "3 of 13 · a post picks one at random" in page
            form = aiohttp.FormData()                  # only files that can't be used: the note says why, nothing more
            for name, value in (("host", "colette"), ("kind", "happy"), ("action", "add")):
                form.add_field(name, value)
            form.add_field("file", b"bad", filename="c.gif", content_type="image/gif")
            r = await c.post("/settings/pool", data=form, allow_redirects=False)
            assert "Nothing%20added" in r.headers["Location"] and "Added" not in r.headers["Location"]
            # a pin wins; the same seed always gives the same picture; no context = random from the pool
            with hosts.look(1, {"happy": "2"}):
                assert hosts.picture("colette", "happy").read_bytes() == b"two"
            with hosts.look(7):
                first = hosts.picture("colette", "happy")
                assert all(hosts.picture("colette", "happy") == first for _ in range(5))
            assert {hosts.picture("colette", "happy").read_bytes() for _ in range(60)} == {b"main", b"one", b"two"}
            assert hosts.picture("colette", "head") is None and hosts.add_to_pool("colette", "head", b"x", "h.png")
            await c.post("/settings/pool", data={"host": "colette", "kind": "happy", "vid": "1", "action": "remove"})
            assert [v for v, _ in hosts.variants("colette", "happy")] == ["main", "2"]
            # numbers are never reused: the next upload is 3
            assert hosts.add_to_pool("colette", "happy", b"three", "d.png") == ""
            assert [v for v, _ in hosts.variants("colette", "happy")] == ["main", "2", "3"]
            # a full pool has no "add" tile and takes no drops
            for i in range(hosts.POOL_MAX - 2):
                assert hosts.add_to_pool("colette", "happy", b"x%d" % i, "e.png") == ""
            page = await (await c.get("/settings/pictures")).text()
            assert 'id="add-colette-happy"' not in page and "full, remove one to add another" in page
    finally:
        hosts.init(None)
