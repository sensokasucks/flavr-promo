"""The one-time copy of FlaVR Bot's calendar data (flavrpromo/import_old.py), split 2026-11-20."""

import sqlite3

from flavrpromo.import_old import maybe_import
from flavrpromo.store import Store


def old_bot_db(folder):
    """A FlaVR Bot database as it was before the split: calendar data plus Core chat and keys."""
    store = Store(folder / "flavr_bot.db")
    pid = store.add_person("Lulu", "flavr")
    store.add_account(pid, "youtube", "@lulu")
    store.start_session(pid, 1000.0, platforms=["youtube"], title="Xenosaga")
    store.put("calendar_channel.flavr", "123")
    store.put("review_times", {"week": 600})
    store.put("core.heartbeat", {"viewers": 5})
    store.put("recap_channel", "9")
    store.put("held_pings", ["x"])
    # FlaVR Bot's own tables (Stream Core's chat copy, moments, alerts), made the way its store does
    store._db.execute("CREATE TABLE chat (core_id INTEGER PRIMARY KEY, message TEXT, at REAL)")
    store._db.execute("INSERT INTO chat VALUES (1, 'hi', 5)")
    store._db.execute("CREATE TABLE moments (id INTEGER PRIMARY KEY, at REAL)")
    store._db.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY, at REAL, data TEXT)")
    store._db.commit()
    store._db.close()


def test_copies_calendar_data_and_leaves_core_parts(tmp_path):
    (tmp_path / "old").mkdir()
    old_bot_db(tmp_path / "old")
    new = tmp_path / "data" / "flavr_promo.db"
    assert maybe_import(new, tmp_path / "old")
    store = Store(new)
    assert [p["name"] for p in store.people()] == ["Lulu"]
    assert store.people()[0]["accounts"][0]["handle"] == "@lulu"
    assert len(store.sessions_between(0, 2000)) == 1
    assert store.get("calendar_channel.flavr") == "123" and store.get("review_times") == {"week": 600}
    assert store.get("core.heartbeat") is None and store.get("recap_channel") is None and store.get("held_pings") is None
    tables = {r[0] for r in sqlite3.connect(new).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"chat", "moments", "alerts"} & tables
    assert not (tmp_path / "data" / "flavr_promo.db.importing").exists()


def test_only_once_and_only_when_there_is_something(tmp_path):
    new = tmp_path / "flavr_promo.db"
    assert not maybe_import(new, tmp_path / "nothing-here")       # no FlaVR Bot data mounted: fresh start
    (tmp_path / "old").mkdir()
    old_bot_db(tmp_path / "old")
    Store(new).put("mine", 1)
    assert not maybe_import(new, tmp_path / "old")                # FlaVR Promo already has its own database
    assert Store(new).people() == []
