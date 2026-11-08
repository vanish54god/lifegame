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

-- Банк заданий: все дела, пока они не сделаны
CREATE TABLE IF NOT EXISTS bank_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    difficulty  INTEGER NOT NULL DEFAULT 2,   -- 1 лёгкая, 2 средняя, 3 сложная, 4 босс
    est_min     INTEGER,                      -- примерное время, минуты
    deadline    TEXT,
    parent_id   INTEGER,                      -- часть большой задачи
    status      TEXT    NOT NULL DEFAULT 'open',   -- open / done
    created_day TEXT    NOT NULL,
    done_day    TEXT
);

-- Привычки (каждый день или N раз в неделю)
CREATE TABLE IF NOT EXISTS habits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    emoji       TEXT    NOT NULL DEFAULT '🔁',
    per_week    INTEGER NOT NULL DEFAULT 7,   -- 7 = каждый день
    xp          INTEGER NOT NULL DEFAULT 20,
    archived    INTEGER NOT NULL DEFAULT 0,
    created_day TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_log (
    habit_id INTEGER NOT NULL,
    day      TEXT    NOT NULL,
    quest_id INTEGER,
    PRIMARY KEY (habit_id, day)
);

-- Оценка дня 1–10
CREATE TABLE IF NOT EXISTS day_rating (
    day   TEXT PRIMARY KEY,
    score INTEGER NOT NULL
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
    # Банк заданий и таймер: у квестов появились время, связь с банком и таймер
    qcols = _columns(conn, "quests")
    for col, typ in [("est_min", "INTEGER"), ("bank_id", "INTEGER"), ("timer_start", "TEXT"),
                     ("timer_sec", "INTEGER NOT NULL DEFAULT 0"), ("pace", "TEXT")]:
        if col not in qcols:
            conn.execute(f"ALTER TABLE quests ADD COLUMN {col} {typ}")
    tcols = _columns(conn, "fin_tx")
    if "envelope" not in tcols:
        conn.execute("ALTER TABLE fin_tx ADD COLUMN envelope TEXT")
    if "slot" not in tcols:
        conn.execute("ALTER TABLE fin_tx ADD COLUMN slot TEXT")
    if "start_day" not in _columns(conn, "planned"):
        conn.execute("ALTER TABLE planned ADD COLUMN start_day TEXT")
    if "slot" not in _columns(conn, "env_moves"):
        conn.execute("ALTER TABLE env_moves ADD COLUMN slot TEXT")
    if "est_min" not in _columns(conn, "templates"):
        conn.execute("ALTER TABLE templates ADD COLUMN est_min INTEGER")
    conn.commit()


def connect(path: str | Path) -> sqlite3.Connection:
    # check_same_thread=False: базу читают и бот, и веб-сервер в одном процессе
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row   # строки можно читать как словарь: row["title"]
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    from .finance import SCHEMA as FIN_SCHEMA   # таблицы финансов
    conn.executescript(FIN_SCHEMA)
    _migrate(conn)
    return conn
