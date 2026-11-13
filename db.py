import os
import sqlite3
import time

DB_PATH = os.getenv("DB_PATH", "leadbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pos INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    delay_sec INTEGER NOT NULL DEFAULT 0,
    btn_text TEXT NOT NULL DEFAULT '',
    btn_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    first_seen INTEGER,
    last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    text TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    step_id INTEGER NOT NULL,
    send_at INTEGER NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    kind TEXT NOT NULL,
    ref TEXT DEFAULT '',
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO settings VALUES ('bot_enabled', '1')")


def now() -> int:
    return int(time.time())


def touch_user(c, user):
    c.execute(
        """INSERT INTO users (user_id, username, name, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             username = excluded.username,
             name = excluded.name,
             last_seen = excluded.last_seen""",
        (user.id, user.username, user.full_name, now(), now()),
    )


def log_event(c, user_id, kind, ref=""):
    c.execute(
        "INSERT INTO events (user_id, kind, ref, created_at) VALUES (?, ?, ?, ?)",
        (user_id, kind, str(ref), now()),
    )


def log_msg(c, user_id, direction, text):
    c.execute(
        "INSERT INTO messages (user_id, direction, text, created_at) VALUES (?, ?, ?, ?)",
        (user_id, direction, text, now()),
    )
