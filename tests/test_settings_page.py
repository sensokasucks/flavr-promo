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
            page = await (await c.get("/settings")).text()
            assert "/settings/picture/colette/chibi_desk" in page                  # built-in pictures shown
            assert (await c.get("/settings/picture/clark/head")).status == 200
            form = aiohttp.FormData()
            form.add_field("host", "clark")
            form.add_field("kind", "head")
            form.add_field("action", "upload")
            form.add_field("file", b"PNG" * 1000, filename="face.png", content_type="image/png")
            r = await c.post("/settings/picture", data=form, allow_redirects=False)
            assert "Saved" in r.headers["Location"] and hosts.pictures("clark")["head"] == "yours"
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
