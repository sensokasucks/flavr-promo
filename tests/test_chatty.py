"""Chattier hosts (owner 2026-11-22: "they pretty much say the same replies from kobold each time"):
the variety in every KoboldCpp request (flavrpromo/kobold.py: angles, memory, shuffled examples,
chattiness) and banter (the other host's reply on the opener card, a chat chunk written as a real
back-and-forth). KoboldCpp is faked: no network."""

import random

from flavrpromo import card_page, host_cards, host_picker, hosts, kobold, recipes, settings_page
from flavrpromo.store import Store
from test_settings_round2 import _client


class FakeKobold(kobold.Kobold):
    """A Kobold whose model answers from a list (the last answer repeats) and keeps every prompt."""

    def __init__(self, answers, **kw):
        super().__init__(None, "http://pc:5001", **kw)
        self.answers, self.prompts, self.tokens = list(answers), [], []
        self.rng = random.Random(7)

    async def generate(self, text, max_length=0):
        self.prompts.append(text)
        self.tokens.append(max_length or kobold.MAX_TOKENS[self.chatty])
        return self.answers.pop(0) if len(self.answers) > 1 else (self.answers[0] if self.answers else None)


def _angle(prompt):
    """The angle a prompt carries ("" = none): the text after "For this one:" up to the next instruction."""
    if "For this one: " not in prompt:
        return ""
    return prompt.rsplit("For this one: ", 1)[1].split(" You already used")[0].split(" Use only the facts")[0]


async def test_each_request_gets_its_own_angle():
    k = FakeKobold(['"One take on it."]', '"A wholly different remark."]', '"Third and unlike the rest."]'])
    got = await k.lines("clark", kobold.asks()["opener"], "Week in Review", "3 streams.", n=3, kind="opener")
    assert len(got) == 3
    used = [_angle(p) for p in k.prompts]
    assert all(used) and len(set(used)) == 3                    # three requests, three different takes
    assert set(used) <= set(kobold.ANGLES + kobold.HOST_ANGLES["clark"])
    # a comment of a few words gets none; a short line only the host's own habits
    assert kobold.angles("clark", "note") == []
    assert kobold.angles("colette", "desk_signoff") == kobold.HOST_ANGLES["colette"]
    await k.line("clark", kobold.asks()["note"], "Week in Review", "3 streams.", kind="note")
    assert _angle(k.prompts[-1]) == ""
    # switched off on the settings page: the request is the plain one
    off = FakeKobold(['"Plain."]'], angles=False)
    await off.line("clark", kobold.asks()["opener"], "Week in Review", "3 streams.", kind="opener")
    assert "For this one" not in off.prompts[0]


async def test_a_host_is_told_what_it_already_said_and_does_not_repeat():
    store = Store(":memory:")
    k = FakeKobold(['"Filed and in order, as ever."]', '"The tapes are labelled."]'], store=store)
    ask = kobold.asks()["opener"]
    assert await k.line("clark", ask, "Week in Review", "3 streams.", kind="opener") == "Filed and in order, as ever."
    assert kobold.said(store, "clark", "opener") == ["Filed and in order, as ever."]
    await k.line("clark", ask, "Week in Review", "4 streams.", kind="opener")
    assert 'You already used these lines' in k.prompts[1] and '"Filed and in order, as ever."' in k.prompts[1]
    # per kind of slot and per host: a sign-off isn't told about openers, Colette isn't told about Clark
    await k.line("clark", kobold.asks()["desk_signoff"], "Week in Review", "4 streams.", kind="desk_signoff")
    await k.line("colette", ask, "Week in Review", "4 streams.", kind="opener")
    assert "already used" not in k.prompts[2] and "already used" not in k.prompts[3]
    # a line that comes out (nearly) the same again is asked for once more, with the repeat named
    again = FakeKobold(['"Filed and in order, as ever!"]', '"Something new entirely, at last."]'], store=store)
    got = await again.line("clark", ask, "Week in Review", "5 streams.", kind="opener")
    assert got == "Something new entirely, at last." and len(again.prompts) == 2
    assert kobold.too_close("Filed, and in order as ever", ["Filed and in order, as ever."])
    assert not kobold.too_close("The tapes are labelled.", ["Filed and in order, as ever."])
    # memory 0 = nothing listed (still remembered, for when it is switched back on); no kind = not remembered
    none = FakeKobold(['"Quiet one."]'], store=store, memory=0)
    await none.line("clark", ask, "Week in Review", "5 streams.", kind="opener")
    assert "already used" not in none.prompts[0] and "Quiet one." in kobold.said(store, "clark", "opener")
    await none.line("clark", ask, "Week in Review", "5 streams.")
    assert len(kobold.said(store, "clark", "opener")) == 4
    # the list is capped
    for i in range(kobold.SAID_KEEP + 5):
        kobold.remember(store, "clark", "day", f"line number {i}")
    assert len(kobold.said(store, "clark", "day")) == kobold.SAID_KEEP and kobold.said(store, "clark", "day", 2)[-1].endswith("34")


def test_card_examples_are_shuffled_and_capped():
    text = kobold.card("clark")["mes_example"]
    blocks = [b for b in text.split("<START>") if b.strip()]
    assert len(blocks) > kobold.EXAMPLES_MAX                    # the built-in card has enough to pick from
    assert kobold.examples(text, None) == text                  # shuffling off: as written
    seen = set()
    for seed in range(12):
        got = kobold.examples(text, random.Random(seed))
        mine = [b.strip() for b in got.split("<START>") if b.strip()]
        assert len(mine) == kobold.EXAMPLES_MAX and all(b in [x.strip() for x in blocks] for b in mine)
        seen.add(tuple(mine))
    assert len(seen) > 3                                        # different requests, different examples
    assert kobold.examples("just one block", random.Random(1)) == "just one block"
    p = kobold.prompt("clark", "Write one.", "3 streams.", rng=random.Random(2))
    assert p.count("<START>") == kobold.EXAMPLES_MAX + 1 and p.endswith("Clark: [")
    for key in hosts.HOSTS:                                     # the reworded rule: the ask decides the length
        assert "max 30 words" not in kobold.card(key)["system_prompt"]


async def test_chattiness_sets_the_length_in_the_ask():
    asks = kobold.asks()
    assert all("{length}" in a for a in asks.values())
    assert set(kobold.LENGTHS) == set(kobold.ASKS)              # every slot kind has its three lengths
    for chatty, words, tokens in (("short", "one sentence.", 160), ("normal", "one to three sentences.", 200),
                                  ("chatty", "two to four sentences, at most 70 words.", 300)):
        k = FakeKobold(['"Fine."]'], chatty=chatty, angles=False)
        await k.line("clark", asks["opener"], "Week in Review", "3 streams.", kind="opener")
        assert f"a complete line of {words}" in k.prompts[0] and k.tokens[0] == tokens
    k = FakeKobold(['"ok"]'], chatty="chatty")
    await k.line("clark", asks["note"].replace("{note}", "longest stream: Lulu"), "Week in Review", "x", kind="note")
    assert "(4 to 8 words) on this highlight: longest stream: Lulu." in k.prompts[0]
    # an ask the owner typed without {length} (or with a stray brace) is used as typed
    assert kobold.fill_ask("Say hi to the {heading}.", 1, "Week In Review", "ten words") == "Say hi to the week in review."
    assert kobold.fill_ask("Odd {brace", 1, "W", "x") == "Odd {brace"
    assert FakeKobold([], chatty="nonsense").chatty == "normal"


async def test_the_other_host_answers_the_opener():
    k = FakeKobold(['"OKAY team, eight streams!!"]', '"Second opener, quite unlike it."]', '"Volume noted, Colette."]',
                    '"I have filed your shouting."]', '"Highlight line."]'], angles=False)
    k.per_slot = 2
    got = await k.write("colette", {"streams": 8, "hours": 20}, "Week in Review", [], only=("opener", "reply"))
    assert got["opener"][0] == "OKAY team, eight streams!!" and got["reply"] == ["Volume noted, Colette.", "I have filed your shouting."]
    reply_prompt = k.prompts[2]
    assert "You are Clark" in reply_prompt and reply_prompt.endswith("Clark: [")       # the OTHER host's card
    assert 'Colette Cappuccino just opened the week in review with: "OKAY team, eight streams!!"' in reply_prompt
    assert "Write your one reply to Colette Cappuccino (one short sentence, at most 20 words)" in reply_prompt
    # no new opener asked for: the answers go to the opener picked on the page
    k2 = FakeKobold(['"Noted."]'], angles=False)
    got = await k2.write("clark", {"streams": 1}, "Week in Review", [], only=("reply",), reply_to="All filed.")
    assert got == {"reply": ["Noted."]} and 'Clark just opened the week in review with: "All filed."' in k2.prompts[0]
    assert "You are Colette" in k2.prompts[0]
    # banter off (settings page, Hosts): no reply is asked for at all
    hosts._banter = False
    k3 = FakeKobold(['"Only an opener here."]'], angles=False)
    assert set(await k3.write("clark", {"streams": 1}, "Week in Review", [], only=("opener", "reply"))) == {"opener"}


async def test_a_chat_is_written_turn_by_turn_with_each_speakers_card():
    k = FakeKobold(['"So, eight streams this week."]', '"EIGHT!! I counted twice to be sure!"]',
                    '"I counted once. Correctly."]', '"Show-off. Have a croissant."]'])
    got = await k.chat("clark", "colette", "Week in Review", "8 streams, 20 hours.", 4)
    assert got == ["So, eight streams this week.", "EIGHT!! I counted twice to be sure!",
                   "I counted once. Correctly.", "Show-off. Have a croissant."]
    assert [p.rsplit("\n", 1)[1] for p in k.prompts] == ["Clark: [", "Colette Cappuccino: [", "Clark: [", "Colette Cappuccino: ["]
    assert "Start the chat with one remark to Colette Cappuccino" in k.prompts[0]
    assert 'Clark just said: "So, eight streams this week."' in k.prompts[1]
    assert 'Colette Cappuccino just said: "EIGHT!! I counted twice to be sure!"' in k.prompts[2]
    assert await FakeKobold([]).chat("clark", "colette", "Week in Review", "x") is None       # offline

    class Poster:
        store, kobold = Store(":memory:"), k
    k.answers = ['"First."]', '"Second, a reply."]', '"Third thing said."]', '"And the fourth."]']
    text, note = await recipes.write_chat(Poster, {"host": "colette", "facts": {"streams": 3, "hours": 5}},
                                          {"type": "chat", "host": "", "other": ""})
    assert text.splitlines() == ["First.", "Second, a reply.", "Third thing said.", "And the fourth."] and "4 lines" in note
    assert k.prompts[-4].endswith("Colette Cappuccino: [")         # the article's host speaks first
    Poster.kobold = None
    assert (await recipes.write_chat(Poster, {"host": "colette"}, {"type": "chat"}))[0] == ""


def test_the_reply_is_drawn_on_the_opener_card_and_long_lines_shrink():
    notes = [{"label": "LONGEST STREAM", "value": "Lulu · 5 h"}]
    for key in hosts.HOSTS:
        other = hosts.other(key)
        plain = host_cards.opener(key, "Week in Review", "Nov 16 - 19", "Short line.", notes, ["wow"], "happy")
        doc = host_cards.opener(key, "Week in Review", "Nov 16 - 19", "Short line.", notes, ["wow"], "happy",
                                reply="Is that so?", reply_key=other)
        assert "Is that so?" in doc and "Is that so?" not in plain
        assert ("MEMO FROM CLARK" if other == "clark" else "COLETTE SAYS") in doc and "SAYS" not in plain and "MEMO" not in plain
        assert "follows" in doc or "next picture" in doc            # the footer is still there
        long = host_cards.opener(key, "Week in Review", "Nov 16 - 19", "word " * 90, notes, ["wow"], "happy")
        assert "font-size:23px" in long and "font-size:30px" in plain
    assert host_cards._fit("x" * 300, 30) == 26
    # a pending review: the picked reply is on the card and in the text-only post; "no reply" takes it off
    f = {"streams": 3, "hours": 5, "range": "Nov 16 - 19"}
    p = {"group": "flavr", "label": "week", "start": "2026-11-16", "host": "colette", "facts": f, "notes": [],
         "candidates": hosts.review_candidates("colette", f), "picks": {}}
    assert hosts.TEMPLATES["clark"]["reply"][0] in host_picker.card_html(p, "opener")
    p["picks"]["reply"] = ""
    assert "MEMO FROM" not in host_picker.card_html(p, "opener")


async def test_settings_page_keeps_the_variety_switches_and_forgets():
    store = Store(":memory:")

    class Poster:
        kobold, http, kobold_env = None, object(), {"url": "http://env:5001", "key": ""}
    Poster.store = store
    settings_page.apply(Poster)
    k = Poster.kobold
    assert (k.angles, k.shuffle, k.memory, k.chatty, k.store) == (True, True, kobold.MEMORY, "normal", store)
    async with _client(Poster, settings_page.add_routes) as c:
        page = await (await c.get("/settings")).text()
        assert "name=chatty" in page and "name=angles value=1 checked" in page and "name=banter value=1 checked" in page
        await c.post("/settings/kobold", data={"url": "pc:5001", "temperature": "1", "per_slot": "2", "variety": "1",
                                               "chatty": "chatty", "shuffle": "1", "memory": "5", "action": "save"},
                     allow_redirects=False)
        k = Poster.kobold
        assert (k.angles, k.shuffle, k.memory, k.chatty) == (False, True, 5, "chatty")
        # a post without the variety fields (an older page, the tests) leaves them as saved
        await c.post("/settings/kobold", data={"url": "pc:5001", "temperature": "1", "per_slot": "2", "action": "save"},
                     allow_redirects=False)
        assert (Poster.kobold.angles, Poster.kobold.memory, Poster.kobold.chatty) == (False, 5, "chatty")
        kobold.remember(store, "clark", "opener", "Filed.")
        assert "1 remembered now" in await (await c.get("/settings")).text()
        r = await c.post("/settings/kobold", data={"url": "pc:5001", "temperature": "1", "per_slot": "2", "action": "forget"},
                         allow_redirects=False)
        assert "forgot" in r.headers["Location"] and kobold.said(store, "clark", "opener") == []
        # Hosts: the banter switch
        await c.post("/settings/hosts", data={"on": "1"}, allow_redirects=False)
        assert store.get(hosts.BANTER_SETTING) is False and not hosts.banter()
        await c.post("/settings/hosts", data={"on": "1", "banter": "1"}, allow_redirects=False)
        assert hosts.banter()


async def test_cards_page_edits_the_angles():
    store = Store(":memory:")

    class Poster:
        kobold = None
    Poster.store = store
    async with _client(Poster, card_page.add_routes) as c:
        page = await (await c.get("/settings/cards")).text()
        assert "angles (their own habits)" in page and "angles for both hosts" in page and "For this one:" in page
        assert "{length}" in page
        await c.post("/settings/cards", data={"host": "clark", "angles": "Mention the binder.\n\n  Quote a   VHS box.  ",
                                              "action": "save"}, allow_redirects=False)
        assert kobold.angles("clark", "reply") == ["Mention the binder.", "Quote a VHS box."]
        assert kobold.angles("colette", "reply") == kobold.HOST_ANGLES["colette"]
        await c.post("/settings/asks", data={"angles": "Whisper it.", "action": "save"}, allow_redirects=False)
        assert kobold.angles("clark", "opener") == ["Whisper it.", "Mention the binder.", "Quote a VHS box."]
        assert store.get("kobold_angles") == {"clark": ["Mention the binder.", "Quote a VHS box."], "all": ["Whisper it."]}
        # an empty box, or the built-in list unchanged, is not an edit; reset drops them
        await c.post("/settings/cards", data={"host": "clark", "angles": "", "action": "save"}, allow_redirects=False)
        await c.post("/settings/asks", data={"action": "reset"}, allow_redirects=False)
        assert store.get("kobold_angles") == {} and kobold.angles("clark", "opener") == kobold.ANGLES + kobold.HOST_ANGLES["clark"]
