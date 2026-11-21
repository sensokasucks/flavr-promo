"""
One-time move of the calendar data from FlaVR Bot (the owner split the bots on 2026-11-20).

Before the split, FlaVR Bot kept everything in one database (flavr_bot.db). FlaVR Promo starts
from a copy of it, so nothing is lost: the people and their channels, every past stream, the
schedules, uploads, groups, talent channels, community calendar posts, and the settings set in
Discord (live / calendar channels, review times, share style, day posts, pings switches).

What is NOT carried over (it belongs to FlaVR Bot): Stream Core's chat copy (chat + chat_fts),
chat moments, alerts, and the Core / recap keys in kv. The server care keys are left in place;
nothing here reads them.

When: flavrpromo/__main__.py calls ``maybe_import`` before opening the database, and only when this
bot has no database yet (DATA_DIR/flavr_promo.db missing) and IMPORT_DIR/flavr_bot.db exists. The
stack mounts FlaVR Bot's data folder read-only at IMPORT_DIR (docker-compose.yml, docs/PORTAINER.md).
The copy uses SQLite's backup API on a read-only connection, so FlaVR Bot can keep running.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("flavrpromo.import")

OLD_NAME = "flavr_bot.db"           # FlaVR Bot's database file name (flavrbot/__main__.py)
DROP_TABLES = ("chat_fts", "chat", "moments", "alerts")
# kv keys that only FlaVR Bot used (Stream Core link, after-stream recap, held Core pings)
DROP_KEYS = ("core.%", "recap_%", "held_pings")


def maybe_import(new_db: Path, import_dir: Path) -> bool:
    """Copy ``import_dir``/flavr_bot.db to ``new_db`` and strip FlaVR Bot's own parts. True when it
    copied. Does nothing (False) when ``new_db`` already exists or there is nothing to import."""
    old = Path(import_dir) / OLD_NAME
    if Path(new_db).exists() or not old.is_file():
        return False
    Path(new_db).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(new_db) + ".importing")
    tmp.unlink(missing_ok=True)
    try:
        src = sqlite3.connect(f"file:{old}?mode=ro", uri=True)
    except sqlite3.Error:
        # a read-only mount can refuse even mode=ro on some setups; immutable skips SQLite's locks
        src = sqlite3.connect(f"file:{old}?immutable=1", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        src.backup(dst)
        for t in DROP_TABLES:
            try:
                dst.execute(f"DROP TABLE IF EXISTS {t}")
            except sqlite3.OperationalError:
                pass                    # chat_fts needs FTS5; without it there was no such table
        for pattern in DROP_KEYS:
            dst.execute("DELETE FROM kv WHERE key LIKE ?", (pattern,))
        dst.commit()
        dst.execute("VACUUM")
        people = dst.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        streams = dst.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        dst.close()
    finally:
        src.close()
    tmp.rename(new_db)              # only a finished copy gets the real name
    log.info("Copied FlaVR Bot's calendar data: %d people, %d streams", people, streams)
    return True
