"""Round 2 of the hosts: KoboldCpp lines on the picker page (flavrpromo/kobold.py, host_picker.py
start_ai) and game details from IGDB (flavrpromo/gameinfo.py) on go-live cards and host lines.
No network: KoboldCpp and IGDB are faked."""

import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from flavrpromo import config, gameinfo, host_picker, hosts, kobold
from flavrpromo.store import Store


def test_settings():
    s = config.load({"KOBOLD_URL": "http://pc:5001/", "KOBOLD_KEY": "pw"})
    assert (s.kobold_url, s.kobold_key) == ("http://pc:5001", "pw")
    assert config.load({}).kobold_url == ""


def test_prompt_uses_the_character_card():
    p = kobold.prompt("clark", "Write 3 opener lines for the week in review.", "9 streams, 26 hours.")
    assert "You are Clark" in p and "Personality:" in p and "Ashe Anchaneko" in p        # card + examples
    assert "{{char}}" not in p and "{{user}}" not in p
    assert p.endswith("Clark: [") and "Facts: 9 streams, 26 hours. Write 3 opener lines" in p


def test_parse_keeps_only_clean_lines():
    got = kobold.parse('"Filed and in order.", "Ping @everyone!", "See http://x", "Filed and in order.", '
                       '"Short one."] trailing chatter')
    assert got == ["Filed and in order.", "Short one."]
    assert kobold.parse('not json at all') == []
    assert kobold.parse('"one", "two]') == ["one"]      # a cut-off answer keeps the whole lines


def test_facts_text():
    f = {"streams": 3, "hours": 10, "top_name": "Lulu", "top_count": 2, "longest_name": "Lulu",
         "longest_len": "5 h 0 min", "new_game": "Valheim", "new_game_name": "Sen",
         "new_game_about": "Survival; Vikings"}
    t = kobold.facts_text(f)
    assert t.startswith("3 streams, 10 hours, Lulu did 2 shows") and "Valheim for the first time (Survival; Vikings)" in t


class FakeKobold(kobold.Kobold):
    def __init__(self, answers):
        super().__init__(None, "http://pc:5001")
        self.answers, self.prompts = list(answers), []

    async def generate(self, text, max_length=220):
        self.prompts.append(text)
        return self.answers.pop(0) if self.answers else None


async def test_write_asks_each_slot_and_stops_when_offline():
    k = FakeKobold(['"A line."]', '"note!"]', '"note two"]'])
    got = await k.write("colette", {"streams": 3, "hours": 5}, "Week in Review",
                        [{"label": "LONGEST STREAM", "value": "Lulu · 2 h"}, {"label": "MOST SHOWS", "value": "Lulu · 2"}])
    assert got == {"opener": ["A line."], "note0": ["note!"], "note1": ["note two"]}
    assert "longest stream: Lulu · 2 h" in k.prompts[1]
    assert len(k.prompts) == 4                         # the 4th answered None (offline): no more asks


class Poster:
    def __init__(self, store, kob):
        self.store, self.kobold, self.web_url, self.discord = store, kob, "http://pc:3871", None
        self.pokes = 0

    def poke(self):
        self.pokes += 1

    def clock(self):
        return time.time()


async def test_picker_gets_ai_lines_first_and_marked():
    store = Store(":memory:")
    f = {"streams": 3, "hours": 5, "range": "Nov 16 - 19", "longest_name": "Lulu", "longest_len": "2 h 0 min"}
    p = {"group": "flavr", "label": "week", "start": "2026-11-16", "host": "clark", "facts": f,
         "notes": hosts.notes(f), "candidates": hosts.review_candidates("clark", f), "picks": {}, "ready": False}
    k = host_picker.key_of("week", "flavr")
    store.put(k, p)
    store.put(host_picker.INDEX, [k])
    kob = FakeKobold(['"AI opener."]', '"ai note"]', '"AI highlight."]', '"AI nudge."]', '"AI bye."]'])
    poster = Poster(store, kob)
    assert host_picker.start_ai(poster, k)
    assert store.get(k)["ai_state"] == "writing"
    assert not host_picker.start_ai(poster, k)        # already writing
    await host_picker._tasks[k]
    p = store.get(k)
    assert p["ai_state"] == "done" and p["candidates"]["opener"][0] == "AI opener."
    assert host_picker.chosen(p, "opener") == "AI opener."
    page = host_picker.page(store, ai_on=True)
    assert "✨ AI opener." in page and "Write more" in page
    assert "Write more" not in host_picker.page(store, ai_on=False)

    app = web.Application()
    host_picker.add_routes(app, poster)
    async with TestClient(TestServer(app)) as client:
        r = await client.post("/hosts/pick", data={"key": k, "action": "swap"}, allow_redirects=False)
        assert r.status == 303 and "KoboldCpp" in r.headers["Location"]
        await host_picker._tasks[k]                    # offline now: template lines only
    p = store.get(k)
    assert p["host"] == "colette" and p["ai"] == [] and p["ai_state"] == "offline"


def test_igdb_result_shapes():
    results = [{"name": "Valheim: Hearth", "url": "https://www.igdb.com/games/x"},
               {"name": "Valheim", "summary": "A brutal exploration and survival game " * 10,
                "genres": [{"name": "Role-playing (RPG)"}, {"name": "Adventure"}],
                "url": "https://www.igdb.com/games/valheim",
                "websites": [{"url": "https://valheimgame.com"}, {"url": "https://store.steampowered.com/app/892970"}]}]
    info = gameinfo.shape(gameinfo.best(results, "valheim"))
    assert info["name"] == "Valheim" and info["link"] == "https://store.steampowered.com/app/892970"
    assert info["genres"] == ["Role-playing (RPG)", "Adventure"] and len(info["summary"]) <= gameinfo.SUMMARY_MAX + 1
    assert gameinfo.genre_word(info) == "role-playing"
    assert gameinfo.shape(results[0])["link"] == "https://www.igdb.com/games/x"


class FakeResp:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self.data


class FakeTwitch:
    ready, client_id = True, "cid"

    def __init__(self, data, status=200):
        self.calls, self.data, self.status = [], data, status
        self.http = self

    async def _app_token(self):
        return "tok"

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        return FakeResp(self.status, self.data)


async def test_lookup_caches_and_skips_non_games():
    store = Store(":memory:")
    tw = FakeTwitch([{"name": "Valheim", "genres": [{"name": "Survival"}], "url": "https://igdb/v"}])
    gi = gameinfo.GameInfo(store, tw)
    assert (await gi.lookup("Valheim"))["genres"] == ["Survival"]
    assert 'search "Valheim"' in tw.calls[0][1] and tw.calls[0][2]["Client-ID"] == "cid"
    await gi.lookup("valheim")
    assert len(tw.calls) == 1                          # remembered
    assert await gi.lookup("Just Chatting") == {} and len(tw.calls) == 1
    miss = gameinfo.GameInfo(store, FakeTwitch([]))
    assert await miss.lookup("Nothing Known") == {}
    assert store.get("game_info.nothing known")["at"]   # the miss is remembered too
    assert gameinfo.cached(store, "VALHEIM")["name"] == "Valheim"


def test_new_game_line_says_the_genre():
    import random
    line = hosts.live_line("colette", "start", "Lulu", "Valheim", "new", rng=random.Random(1), genre="survival")
    assert "survival" in line and "Valheim" in line
    assert "{genre}" not in hosts.live_line("clark", "start", "Lulu", "Valheim", "new", rng=random.Random(1))


async def test_live_card_links_the_game_and_shows_genres():
    from flavrpromo import groups
    from flavrpromo.bot import PromoBot
    from flavrpromo.pings import Pinger
    from flavrpromo.watcher import Watcher
    store = Store(":memory:")
    groups.init(store)
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None), Watcher(store, {}, {}))
    lulu = store.add_person("Lulu", "flavr")
    sid = store.start_session(lulu, time.time(), platforms=["twitch"], title="hi")
    store.segment_add(sid, lulu, "Valheim", time.time(), "new")
    store.put("game_info.valheim", {"name": "Valheim", "genres": ["Survival", "Adventure"],
                                    "link": "https://store.steampowered.com/app/892970", "at": time.time()})
    e = bot.live_embed({"id": lulu, "name": "Lulu", "grp": "flavr"}, {"id": sid, "title": "hi"}, {"twitch": {"url": "u"}})
    playing = next(f.value for f in e.fields if f.name == "Playing")
    assert playing.startswith("[Valheim](https://store.steampowered.com/app/892970) · 🆕 NEW GAME")
    assert playing.endswith("*Survival · Adventure*")
    await bot.close()


def test_parse_copes_with_chat_models():
    # Sen 2026-11-21 (Gemma via KoboldCpp): the list one item per line, fences, thinking, a 2nd "["
    assert kobold.parse('\n  "One line.",\n  "Two line."\n]\n') == ["One line.", "Two line."]
    assert kobold.parse('```json\n["A.", "B."]\n```') == ["A.", "B."]
    assert kobold.parse('<think>hmm</think>"Fine."]') == ["Fine."]
    assert "\n" not in kobold.STOPS                     # a newline mustn't end the answer


async def test_generate_sends_stops_and_keeps_the_raw_answer():
    class Http:
        def __init__(self):
            self.json = None

        def post(self, url, headers=None, timeout=None, json=None):
            self.json = json
            return FakeResp(200, {"results": [{"text": 'Sorry, here you go: none'}]})
    h = Http()
    k = kobold.Kobold(h, "http://k:5001", per_slot=5)
    got = await k.generate("prompt")
    assert got == "Sorry, here you go: none" and k.last_raw == got
    assert h.json["stop_sequence"] == kobold.STOPS and h.json["max_length"] == 70 * 5 + 60
