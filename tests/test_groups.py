"""Custom groups (flavrpromo/groups.py): FlaVR and Friends built in, more added with /group add."""

from datetime import datetime
from zoneinfo import ZoneInfo

from flavrpromo import groups
from flavrpromo.calendar import Week
from flavrpromo.calendar_post import embed
from flavrpromo.render import theme
from flavrpromo.share import discord_text, x_posts
from flavrpromo.store import Store

TZ = ZoneInfo("America/New_York")
SUN = datetime(2026, 11, 15, tzinfo=TZ)


def fresh():
    store = Store(":memory:")
    groups.init(store)
    return store


def test_defaults_and_add():
    fresh()
    assert groups.keys() == ["flavr", "friends", "community"]
    assert groups.find("") == "flavr" and groups.find("FRIENDS") == "friends" and groups.find("nope") is None
    assert groups.add("Art Pals", "#ff8800") == "art-pals"
    assert groups.find("art pals") == "art-pals" and groups.find("Art-Pals") == "art-pals"
    assert groups.add("art pals") == "" and groups.add("flavr") == "" and groups.add("!!!") == ""   # taken / empty
    assert groups.keys() == ["flavr", "friends", "community", "art-pals"]
    assert groups.colour("art-pals") == "#ff8800" and groups.colour_int("art-pals") == 0xff8800
    assert groups.parse_colour("f80") == "#ff8800" and groups.parse_colour("orange") is None


def test_edit_and_remove():
    store = fresh()
    groups.add("Art Pals")
    groups.update("friends", "Pals of FlaVR", "#123456")             # the built-in two can be renamed
    assert groups.name("friends") == "Pals of FlaVR" and groups.colour("friends") == "#123456"
    assert groups.find("pals of flavr") == "friends"
    assert not groups.remove("flavr") and not groups.remove("friends") and not groups.remove("nope")
    a = store.add_person("Lulu", "art-pals")
    store.add_person("Raimi", "art-pals")
    assert groups.remove("art-pals") and store.move_group("art-pals", "friends") == 2
    assert [p["grp"] for p in store.people()] == ["friends", "friends"] and groups.keys() == ["flavr", "friends", "community"]
    store.set_group(a, "flavr")
    assert next(p for p in store.people() if p["id"] == a)["grp"] == "flavr"
    store.put("live_channel.x", "1")
    store.delete("live_channel.x")
    assert store.get("live_channel.x") is None


def test_custom_group_on_the_board_and_in_text():
    fresh()
    groups.add("Art Pals", "#ff8800")
    w = Week(group="art-pals", start=SUN, tz=TZ, now=SUN.timestamp(), recap=False, days=[[] for _ in range(7)], quiet=[])
    assert w.title == "THIS WEEK WITH ART PALS"
    assert embed(w)["title"].startswith("This week with Art Pals") and embed(w)["colour"] == 0xff8800
    assert "#ff8800" in theme("art-pals") and "#b7ef33" in theme("flavr")       # FlaVR keeps its logo colours
    assert discord_text(w).startswith("🗓️ **This week with Art Pals**")
    assert x_posts(w, {}, "one")[0].startswith("🗓️ This week with Art Pals")
    w.recap = True
    assert w.title == "ART PALS: WEEK IN REVIEW" and groups.heading("art-pals", True) == "Art Pals week in review"
