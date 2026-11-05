"""
База данных: обычный SQLite-файл (game.db). Ничего ставить не надо.
Если база осталась от этапа 1 — она сама обновится при запуске (миграция ниже).
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,                -- игровой день, '2026-11-03'
    category   TEXT    NOT NULL,                -- ключ из rules.CATEGORIES
    title      TEXT    NOT NULL,
    xp         INTEGER NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'todo', -- todo / done / failed
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    done_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_quests_day ON quests(day);

-- Шаблоны квестов: то, что повторяется («Вовремя лечь», «Смена»)
CREATE TABLE IF NOT EXISTS templates (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT    NOT NULL,
    title    TEXT    NOT NULL,
    xp       INTEGER NOT NULL
);

-- Товары в магазине
CREATE TABLE IF NOT EXISTS shop_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'wish',  -- wish / trip / fun
    cost       INTEGER NOT NULL,
    repeatable INTEGER NOT NULL DEFAULT 0,       -- 1 = можно покупать много раз
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Покупки
CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    cost       INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Настройки (напоминания и прочее)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Обещания
CREATE TABLE IF NOT EXISTS promises (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT    NOT NULL,
    created_day TEXT    NOT NULL,              -- игровой день, когда пообещал
    due         TEXT,                          -- срок (может не быть)
    status      TEXT    NOT NULL DEFAULT 'open', -- open / kept / cancelled
    postponed   INTEGER NOT NULL DEFAULT 0,    -- сколько раз переносил
    closed_day  TEXT,
    quest_id    INTEGER,                       -- квест, через который начислен XP
    last_nudge  TEXT                           -- когда бот последний раз спрашивал «когда?»
);

-- Открытые достижения (навсегда, даже если потом что-то отменил)
CREATE TABLE IF NOT EXISTS achievements (
    key         TEXT PRIMARY KEY,
    unlocked_at TEXT NOT NULL
);

-- Вход в веб-приложение: одноразовые коды и сессии (храним только хэши)
CREATE TABLE IF NOT EXISTS login_codes (
    code_hash  TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    device     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen  TEXT
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    # Этап 1 → этап 2+: у покупок появилась ссылка на товар
    if "item_id" not in _columns(conn, "purchases"):
        conn.execute("ALTER TABLE purchases ADD COLUMN item_id INTEGER")
    conn.commit()


def connect(path: str | Path) -> sqlite3.Connection:
    # check_same_thread=False: базу читают и бот, и веб-сервер в одном процессе
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row   # строки можно читать как словарь: row["title"]
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
