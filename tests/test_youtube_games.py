"""YouTube game detection (flavrpromo/games.py detect_how, gameinfo.py guess, watcher.py _guess;
owner 2026-11-21): a title fixed by hand, the person's own words, known games, an IGDB guess for a
brand-new game (looked up in the background once per title) and the game of an earlier stream with
nearly the same title."""

import asyncio

from flavrpromo import gameinfo, games
from flavrpromo.store import Store
from tests.test_ai_and_games import FakeResp, FakeTwitch

DAY = 86400.0
YT = lambda title: {"youtube": {"title": title, "url": "u"}}          # noqa: E731


class SearchTwitch(FakeTwitch):
    """IGDB that answers per search text: {part: [results]}."""

    def __init__(self, answers):
        super().__init__([])
        self.answers = answers

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        text = data.split('"')[1]
        return FakeResp(200, self.answers.get(text, []))


def world():
    store = Store(":memory:")
    pid = store.add_person("Lulu", "flavr")
    return store, {"id": pid, "name": "Lulu"}


def test_title_parts_and_names():
    assert games.parts("SCHEDULE I | first time! (day 3) !discord") == ["schedule i"]
    assert games.parts("Valheim w/ friends - day 3") == ["valheim"]
    assert games.parts("chill stream | !socials") == []
    assert games.names_part("Minecraft", "minecraft with chat")          # the rest is filler
    assert not games.names_part("Building", "building a longhouse with chat")
    assert games.names_part("Schedule I", "schedule i") and not games.names_part("It", "it")


def test_detect_order_fix_words_known_similar():
    store, p = world()
    pid = p["id"]
    assert games.detect_how(store, p, {"twitch": {"game": "Valheim", "title": "x"}}, "twitch") == ("Valheim", "platform")
    assert games.detect_how(store, p, YT("cooking with chat"), "youtube") == ("", "")
    games.set_words(store, pid, "Cooking", "Schedule I")
    assert games.detect_how(store, p, YT("Cooking with chat!"), "youtube") == ("Schedule I", "words")
    games.remember_fix(store, pid, "Cooking with chat!", "Schedule I Co-op")
    assert games.detect_how(store, p, YT("cooking with CHAT"), "youtube") == ("Schedule I Co-op", "fix")
    assert games.set_words(store, pid, "cooking", "") == "cooking"           # forgotten
    assert games.set_words(store, pid, "ab", "X") == ""                       # too short
    # an earlier stream with nearly the same title (a series)
    s = store.start_session(pid, 10 * DAY, ended_at=10 * DAY + 3600, last_seen=10 * DAY + 3600,
                            game="Factorio", title="Building the mega base with chat day 4")
    assert s
    got = games.detect_how(store, p, YT("Building the mega base with chat day 5"), "youtube", now=11 * DAY)
    assert got == ("Factorio", "similar")
    assert games.detect_how(store, p, YT("Speedrunning tonight"), "youtube", now=11 * DAY) == ("", "")


async def test_igdb_guess_once_per_title():
    store, p = world()
    tw = SearchTwitch({"schedule i": [{"name": "Schedule I", "genres": [{"name": "Simulator"}], "url": "https://igdb/s"}],
                       "building a longhouse with chat": [{"name": "Building"}]})
    gi = gameinfo.GameInfo(store, tw)
    assert await gi.guess("SCHEDULE I | first time! !discord") == "Schedule I"
    assert gameinfo.cached(store, "Schedule I")["genres"] == ["Simulator"]       # details kept for the card
    assert games.detect_how(store, p, YT("SCHEDULE I | first time! !discord"), "youtube") == ("Schedule I", "igdb")
    n = len(tw.calls)
    await gi.guess("SCHEDULE I | first time! !discord")
    assert len(tw.calls) == n                                                    # asked once per title
    assert await gi.guess("Building a longhouse with chat") == ""                 # not the game "Building"
    assert store.get(games.guess_key("Building a longhouse with chat"))["game"] == ""


async def test_watcher_asks_in_the_background_then_uses_it():
    from flavrpromo.watcher import Watcher
    store, p = world()
    w = Watcher(store, {}, {})
    asked = []

    async def guess(title):
        asked.append(title)
        store.put(games.guess_key(title), {"game": "Peak", "at": 1})
        return "Peak"
    w.guess_game = guess
    w._guess("PEAK with the crew")
    w._guess("PEAK with the crew")                                               # already being asked
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert asked == ["PEAK with the crew"]
    assert games.detect_how(store, p, YT("PEAK with the crew"), "youtube") == ("Peak", "igdb")
