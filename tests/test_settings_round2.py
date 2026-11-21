"""Settings pages, round 2 (owner 2026-11-21): the character card editor (/settings/cards,
flavrpromo/card_page.py), the article editor (/settings/article, article_editor.py) and a form
for every slash command (/settings/commands, command_forms.py)."""

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from flavrpromo import (article_editor, card_page, command_forms, config, groups, host_cards, host_picker, hosts,
                        kobold, share)
from flavrpromo.bot import PromoBot
from flavrpromo.calendar_post import CalendarPoster
from flavrpromo.pings import Pinger
from flavrpromo.render import ImageCache
from flavrpromo.store import Store
from flavrpromo.watcher import Watcher

from test_hosts import FakeDiscord, ts, world


def _client(poster, *adders):
    app = web.Application(client_max_size=10 * 1024 * 1024)
    for add in adders:
        add(app, poster)
    return TestClient(TestServer(app))


# ── character cards ────────────────────────────────────────────────────────
class CardPoster:
    def __init__(self, store):
        self.store, self.kobold = store, None


async def test_card_edits_reach_the_prompt_and_reset():
    store = Store(":memory:")
    poster = CardPoster(store)
    kobold.load_card_overrides(store)
    built = kobold.builtin_card("clark")["personality"]
    try:
        async with _client(poster, card_page.add_routes) as c:
            page = await (await c.get("/settings/cards")).text()
            assert "post history instructions" in page and "Clark" in page
            form = {f: kobold.builtin_card("clark").get(f) or "" for f in kobold.CARD_FIELDS}
            form.update(host="clark", action="save", personality="Grumpy but fair.")
            r = await c.post("/settings/cards", data=form, allow_redirects=False)
            assert "1%20field%20edited" in r.headers["Location"]
            assert store.get("host_cards") == {"clark": {"personality": "Grumpy but fair."}}   # only what changed
            assert "Personality: Grumpy but fair." in kobold.prompt("clark", "Write 1 line.", "3 streams.")
            assert kobold.card("colette")["personality"] == kobold.builtin_card("colette")["personality"]
            # the asks: {n} still filled; a stray brace doesn't break the request
            await c.post("/settings/asks", data={"opener": "Give {n} openers {oops}", "action": "save"},
                         allow_redirects=False)
            assert kobold.fill_ask(kobold.asks()["opener"], 2, "Week in Review") == "Give 2 openers {oops}"
            assert kobold.asks()["desk_nudge"] == kobold.ASKS["desk_nudge"]
            await c.post("/settings/cards", data={"host": "clark", "action": "reset"}, allow_redirects=False)
            await c.post("/settings/asks", data={"action": "reset"}, allow_redirects=False)
            assert kobold.card("clark")["personality"] == built and kobold.asks() == kobold.ASKS
    finally:
        store.put("host_cards", {})
        kobold.load_card_overrides(store)


# ── the article editor ────────────────────────────────────────────────────
class Shooter:
    def __init__(self):
        self.docs = []

    async def png(self, doc, size=None):
        self.docs.append(doc)
        return b"\x89PNG fake"


def _poster(tmp_path, store=None):
    store = store or world()
    groups.init(store)
    p = CalendarPoster(store, FakeDiscord(), ImageCache(tmp_path), None, clock=lambda: ts(2026, 11, 20, 10, 5))
    p.shooter, p.kobold = Shooter(), None
    return p


def test_article_sections_join_to_the_html(tmp_path):
    p = _poster(tmp_path)
    a = share.article(p.build_review("flavr", "week"), tags="#FlaVR")
    assert "\n".join(s["html"] for s in a["sections"]) == a["html"]
    ids = [s["id"] for s in a["sections"]]
    assert ids[0] == "summary" and "who" in ids and ids[-1] == "tags" and any(i.startswith("day") for i in ids)


async def test_article_editor_builds_section_by_section(tmp_path):
    hosts.init(tmp_path / "pics")              # built-in pictures on
    poster = _poster(tmp_path)
    poster.store.put("hosts_only", "colette")
    try:
        async with _client(poster, article_editor.add_routes) as c:
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            dkey = article_editor.draft_key("flavr", "week")
            p = poster.store.get(dkey)
            ids = [s["id"] for s in p["sections"]]
            assert ids[0] == "intro" and ids[-1] == "outro" and "summary" in ids
            assert p["host"] == "colette" and "Host intro" in page and "Regen from the calendar" in page
            opener = host_picker.chosen(p, "opener")
            assert opener

            async def act(action, **extra):
                data = {"d": dkey, "action": action, **{f"on_{s['id']}": "1" for s in p["sections"]}}
                data.update(extra)
                r = await c.post("/settings/article", data=data, allow_redirects=False)
                assert r.status == 303
                return poster.store.get(dkey)

            # own line for the opener, the summary left out, the outro moved up one, a text section added
            p = await act("save", opener="__custom", opener__text="Big week, people!", on_summary="")
            assert host_picker.chosen(p, "opener") == "Big week, people!"
            assert not next(s for s in p["sections"] if s["id"] == "summary")["on"]
            p = await act("up:outro", on_summary="")
            assert [s["id"] for s in p["sections"]][-2] == "outro"
            p = await act("add_text", on_summary="")
            tid = next(iter(p["texts"]))
            p = await act("save", on_summary="", **{f"text_{tid}": "Thanks for watching!\n\nSee you Monday."})
            # chibi big on the opener card (Sen: swap the chibi and the adult)
            p = await act("save", on_summary="", opener_kind="chibi", pic_intro="opener")
            r = await c.get(f"/settings/article/picture?d={dkey}&sec=intro")
            assert r.status == 200 and await r.read() == b"\x89PNG fake"
            assert p["opener_kind"] == "chibi"
            # a plain picture instead of a card for the outro
            p = await act("save", on_summary="", pic_outro="pic:sleepy")
            r = await c.get(f"/settings/article/picture?d={dkey}&sec=outro")
            assert r.status == 200 and len(await r.read()) > 1000
            # Regen: a calendar section from the calendar, a host section gets new (shuffled) lines
            p = await act("regen:summary", on_summary="")
            p = await act("regen:outro", on_summary="")
            assert "desk_signoff" not in p["picks"]
            view = await (await c.get(f"/settings/article/view?d={dkey}")).text()
            assert "Big week, people!" in view and "See you Monday." in view and "Colette Cappuccino" in view
            assert "hours live" not in view.split('id="body"')[1]           # the summary line is out
            assert "back to the article editor" in view and "outro-colette-sleepy.png" in view
            # day pictures in the host's look (owner 2026-11-21), with an editable line per day
            day = next(s["id"] for s in p["sections"] if s["id"].startswith("day"))
            assert p["day_look"] == "host" and p["candidates"][day]          # the day's line is a slot like the others
            p = await act("save", on_summary="", **{day: "__custom", f"{day}__text": "Mark it, team!"})
            assert host_picker.chosen(p, day) == "Mark it, team!"
            r = await c.get(f"/settings/article/day?d={dkey}&day={day[3:]}")
            assert r.status == 200 and "Mark it, team!" in poster.shooter.docs[-1]
            assert "pinned up by Colette" in poster.shooter.docs[-1]
            view = await (await c.get(f"/settings/article/view?d={dkey}")).text()
            assert "/settings/article/day?d=" in view and "/calendar/day.png" not in view.split('id="body"')[1]
            # the other layouts: for the whole article, or one day on its own
            for lay, mark in (("timeline", "pinned up by Colette"), ("spotlight", "TOP PICK"), ("columns", "#fbe48a"),
                              ("zigzag", "margin-left:0px"), ("cards", "border-radius:14px")):
                p = await act("save", on_summary="", day_layout=lay)
                await c.get(f"/settings/article/day?d={dkey}&day={day[3:]}")
                assert mark in poster.shooter.docs[-1] and p["day_layout"] == lay
            p = await act("save", on_summary="", day_layout="wall", **{f"daylayout_{day[3:]}": "spotlight"})
            await c.get(f"/settings/article/day?d={dkey}&day={day[3:]}")
            assert "TOP PICK" in poster.shooter.docs[-1]
            p = await act("save", on_summary="", day_look="board")
            view = await (await c.get(f"/settings/article/view?d={dkey}")).text()
            assert "/calendar/day.png" in view.split('id="body"')[1]
            # per-line buttons (Sen: no scrolling up, no changing every line): ↻ one slot, ✨ one slot
            p = await act("reroll:desk_signoff", on_summary="")
            assert p["picks"]["desk_signoff"] and host_picker.chosen(p, "opener") == "Big week, people!"

            class Kob:
                per_slot = 2

                async def generate(self, text):
                    self.prompt = text
                    return '"Fresh line one!", "Fresh line two!"]'
            poster.kobold = Kob()
            p = await act("ask:desk_nudge", on_summary="")
            assert host_picker.chosen(p, "desk_nudge") == "Fresh line one!" and "Fresh line two!" in p["ai"]
            assert host_picker.chosen(p, "opener") == "Big week, people!"           # the others keep their picks
            p = await act(f"ask:{day}", on_summary="", day_look="host")
            assert host_picker.chosen(p, day) == "Fresh line one!" and "this day's picture" in poster.kobold.prompt
            page = await (await c.get("/settings/article?group=flavr&which=week")).text()
            assert f'value="ask:{day}"' in page and 'value="reroll:opener"' in page
            poster.kobold = None
            p = await act("save", on_summary="", **{day: "__none"})
            assert host_picker.chosen(p, day) == ""                                  # no bubble
            # the cover in the host's look (Sen: "the article cover is still in the old style")
            r = await c.get(f"/settings/article/cover?d={dkey}")
            assert r.status == 200 and "WEEK IN REVIEW" in poster.shooter.docs[-1]
            assert "/settings/article/cover?d=" in await (await c.get(f"/settings/article/view?d={dkey}")).text()
            # the other host, then start over
            p = await act("host", on_summary="", host="clark")
            assert p["host"] == "clark" and not p["picks"]
            await act("reset")
            assert poster.store.get(dkey) is None
    finally:
        hosts.init(None)


def test_every_day_layout_draws_for_both_hosts(tmp_path):
    poster = _poster(tmp_path)
    week = poster.build_review("flavr", "week")
    day = next(i for i, d in enumerate(week.days) if d)
    for key in hosts.HOSTS:
        for lay in host_cards.DAY_LAYOUTS:
            doc = host_cards.day(key, week, day, lambda u: "", "A line <b>", layout=lay)
            assert "A line &lt;b&gt;" in doc and "Lulu" in doc, (key, lay)      # escaped, stream shown
        empty = next(i for i, d in enumerate(week.days) if not d)
        assert "Nothing" in host_cards.day(key, week, empty, lambda u: "", layout="cards")


def test_clark_is_a_vtuber_nerd():
    """Sen 2026-11-21: Clark loves the job because it's VTuber work, sometimes says "Anime Americans"."""
    all_lines = " ".join(x for rows in hosts.TEMPLATES["clark"].values() for x in rows)
    assert "Anime Americans" in all_lines and "VCR" in all_lines
    assert "Anime Americans" in kobold.builtin_card("clark")["personality"]


def test_card_html_takes_the_article_heading_and_pose():
    p = {"host": "clark", "label": "", "heading": "This Week", "pose": "sleepy", "facts": {"range": "Nov 15 - 21"},
         "notes": [], "candidates": {"opener": ["Filed."]}, "picks": {}}
    doc = host_picker.card_html(p, "opener")
    assert "This Week" in doc and "Filed." in doc


# ── the command forms ─────────────────────────────────────────────────────
def _bot():
    s = config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "42"})
    store = Store(":memory:")
    groups.init(store)
    return PromoBot(s, store, Pinger(store, None), Watcher(store, {}, {}))


class CmdPoster:
    def __init__(self, bot):
        self.discord, self.store = bot, bot.store


async def test_every_command_gets_a_form_and_runs_as_the_owner():
    bot = _bot()
    try:
        async with _client(CmdPoster(bot), command_forms.add_routes) as c:
            page = await (await c.get("/settings/commands")).text()
            for name in ("pings set", "friend add", "calendar view", "host picture", "setup live-channel"):
                assert f"/{name}" in page, name
            assert 'type=file name="file"' in page and "Discord isn't connected" in page
            # a choice + yes / no: the command gets the Choice and the bool, and its answer shows
            r = await c.post("/settings/commands", data={"__cmd": "pings set", "kind": "calendar", "on": "0"},
                             allow_redirects=False)
            assert r.status == 303 and "#c-pings-set" in r.headers["Location"]
            shown = await (await c.get(r.headers["Location"].split("#")[0])).text()
            assert "<code>calendar</code> pings off." in shown
            assert bot.pinger.switches()["calendar"] is False
            # missing a needed option: not run
            out = await command_forms.run(bot, "pings quiet", {"start": "3"})
            assert out["error"].startswith("Not run") and "end: needed" in out["error"]
            out = await command_forms.run(bot, "pings quiet", {"start": "3", "end": "99"})
            assert "between 0 and 23" in out["error"]
            # the owner check passes (owner-only commands answer)
            out = await command_forms.run(bot, "pings view", {})
            assert "Quiet hours" in out["messages"][0]["text"]
            # a file option (/host picture) gets the uploaded file
            form = FormData()
            for k, v in (("__cmd", "host picture"), ("host", "clark"), ("kind", "head")):
                form.add_field(k, v)
            form.add_field("file", b"x" * 10, filename="face.txt", content_type="text/plain")
            r = await c.post("/settings/commands", data=form, allow_redirects=False)
            assert r.status == 303
    finally:
        await bot.close()


def test_discord_markdown_on_the_page():
    out = command_forms.md("**Lulu** is *live*: [watch](https://x.y/z) `code` <script>")
    assert "<b>Lulu</b>" in out and "<i>live</i>" in out and '<a href="https://x.y/z"' in out
    assert "<code>code</code>" in out and "&lt;script&gt;" in out
