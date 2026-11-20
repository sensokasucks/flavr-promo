"""flavrpromo/server.py: /health and /live.json, the shape flavr-bot's promo_link.py reads."""

import time

from aiohttp.test_utils import TestClient, TestServer

from flavrpromo.server import Server
from flavrpromo.store import Store


async def test_live_json_owner_game_and_streams():
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    sen = store.add_person("Sensoka", "flavr", is_owner=True)
    now = time.time()
    # the owner: one finished stream with its VOD, one live now (with a game); Lulu live too
    old = store.start_session(sen, now - 5 * 3600, platforms=["twitch"], url="https://twitch.tv/sensoka")
    store.update_session(old, ended_at=now - 3 * 3600, vod_url="https://www.twitch.tv/videos/1")
    store.start_session(sen, now - 600, platforms=["twitch"], url="https://twitch.tv/sensoka", game="Schedule I")
    store.start_session(lulu, now - 300, platforms=["youtube"])
    store.start_session(sen, now - 3 * 86400, platforms=["twitch"])        # too old for owner_streams
    server = Server(store)
    server.owner_live = lambda: True
    async with TestClient(TestServer(server.app())) as client:
        assert (await (await client.get("/health")).json()) == {"ok": True}
        live = await (await client.get("/live.json")).json()
    assert live["owner_live"] is True
    me = next(r for r in live["live"] if r["owner"])
    assert me["name"] == "Sensoka" and me["game"] == "Schedule I"
    assert [r["owner"] for r in live["live"] if r["name"] == "Lulu"] == [False]
    # newest first; the live one has no end yet
    streams = live["owner_streams"]
    assert len(streams) == 2 and streams[0]["ended_at"] is None
    assert streams[1]["vod_url"] == "https://www.twitch.tv/videos/1"
