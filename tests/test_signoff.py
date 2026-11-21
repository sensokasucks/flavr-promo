"""flavrpromo/signoff.py: several sign-off lines per person, one per finished stream, no repeats."""

import random

from flavrpromo import signoff
from flavrpromo.store import Store


def setup():
    store = Store(":memory:")
    lulu = store.add_person("Lulu", "flavr")
    return store, store.person("Lulu"), lulu


def test_add_list_remove_and_limits():
    store, p, pid = setup()
    assert "no sign-off lines" in signoff.listing(store.signoffs(pid), "Lulu")
    assert signoff.add(store, p, "  otsu-\nnuggies ", "🍗").startswith("Added")
    assert "already has that line" in signoff.add(store, p, "OTSU- NUGGIES")       # case and spaces don't count
    assert "empty" in signoff.add(store, p, "   ")
    signoff.add(store, p, "see you next time *chu*")
    rows = store.signoffs(pid)
    assert [r["line"] for r in rows] == ["otsu- nuggies", "see you next time *chu*"]
    # markdown is escaped so the line shows as typed; emoji goes first
    assert signoff.text(rows[1]) == "see you next time \\*chu\\*" and signoff.text(rows[0]) == "🍗 otsu- nuggies"
    assert signoff.listing(rows, "Lulu", own=True).startswith("Your sign-off lines:\n1. 🍗")
    assert "No line 5" in signoff.remove(store, p, 5)
    assert "Removed" in signoff.remove(store, p, 1)
    assert [r["line"] for r in store.signoffs(pid)] == ["see you next time *chu*"]
    for i in range(signoff.MAX_LINES):
        signoff.add(store, p, f"line {i}")
    assert len(store.signoffs(pid)) == signoff.MAX_LINES
    assert "Remove one first" in signoff.add(store, p, "one more")
    assert len(signoff.clean("x" * 500)) == signoff.MAX_LEN
    # removing the person removes their lines
    store.remove_person("Lulu")
    assert store.signoffs(pid) == []


def test_pick_no_repeat_and_same_for_one_stream():
    store, p, pid = setup()
    assert signoff.pick(store, pid, 1) is None                  # no lines: nothing on the card
    signoff.add(store, p, "only one")
    assert signoff.pick(store, pid, 1)["line"] == "only one"
    assert signoff.pick(store, pid, 2)["line"] == "only one"    # one line: it may repeat
    signoff.add(store, p, "otsu-nuggies")
    signoff.add(store, p, "bye bye")
    rng = random.Random(7)
    seen = []
    for sid in range(10, 40):
        seen.append(signoff.pick(store, pid, sid, rng)["id"])
        # the same stream ended again (a quick restart, then the real end) keeps its line
        assert signoff.pick(store, pid, sid, rng)["id"] == seen[-1]
    assert all(a != b for a, b in zip(seen, seen[1:]))          # never twice in a row
    assert len(set(seen)) == 3


async def test_was_live_card_gets_the_line():
    # flavrpromo/bot.py post_end: the ended card shows one sign-off line under the VOD
    import discord

    from flavrpromo import config, groups
    from flavrpromo.bot import PromoBot
    from flavrpromo.pings import Pinger
    from flavrpromo.watcher import Watcher

    store, p, pid = setup()
    groups.init(store)
    signoff.add(store, p, "otsu-nuggies", "🍗")
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None),
                   Watcher(store, {}, {}))
    edits = []

    class Msg:
        embeds = [discord.Embed(title="Lulu is live", description="Art stream")]

        async def edit(self, **kw):
            edits.append(kw)

    async def messages(session):
        return [Msg()]
    bot._messages = messages
    await bot.post_end(p, {"id": 5, "started_at": 0, "ended_at": 7200, "vod_url": "https://www.twitch.tv/videos/1"})
    e = edits[0]["embed"]
    assert e.title == "Lulu was live" and [f.value for f in e.fields][-1] == "*🍗 otsu-nuggies*"
    await bot.close()
