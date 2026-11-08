"""
Финансы: операции, лимит на день, смены и зарплата, планируемые траты,
карта желаний, накопления и вложения, статистика.

Все суммы в базе — в КОПЕЙКАХ (целые числа), чтобы не было ошибок округления.
Для людей показываем рубли: rub(123450) → «1 234,50 ₽», rub(150000) → «1 500 ₽».
"""

import re
import sqlite3
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta


class FinError(Exception):
    """Ошибка, которую можно показать как есть."""


# ================= Категории =================

@dataclass(frozen=True)
class Cat:
    key: str
    title: str
    emoji: str
    words: tuple[str, ...]   # по началу слов угадываем категорию


OUT_CATS = [
    Cat("food", "Продукты", "🛒", ("продукт", "магаз", "пятёроч", "пятероч", "перекрест", "вкусвилл", "лента",
                                    "ашан", "дикси", "магнит", "самокат", "лавк", "еда")),
    Cat("cafe", "Кафе", "☕", ("кофе", "кафе", "ресторан", "обед", "ужин", "завтрак", "шаурм", "бургер", "kfc",
                              "вкусно", "доставк", "пицц", "суши", "столов", "перекус", "чай")),
    Cat("transport", "Транспорт", "🚇", ("метро", "такси", "автобус", "транспорт", "электричк", "бензин",
                                         "каршер", "тройк", "мцд", "проезд", "самолёт", "поезд")),
    Cat("fun", "Развлечения", "🎮", ("кино", "игр", "steam", "стим", "концерт", "бар", "клуб", "театр",
                                     "боулинг", "квест", "кальян")),
    Cat("shop", "Покупки", "🛍", ("одежд", "озон", "ozon", "вб", "wb", "wildberries", "вайлдберриз",
                                  "кроссов", "техник", "наушник", "куртк")),
    Cat("home", "Дом и связь", "🏠", ("связь", "интернет", "квартир", "аренд", "коммунал", "жкх", "телефон",
                                      "мобильн")),
    Cat("subs", "Подписки", "🔁", ("подписк", "впс", "vps", "vpn", "впн", "spotify", "яндекс", "плюс",
                                   "apple", "icloud", "сервер", "домен")),
    Cat("health", "Здоровье", "💊", ("аптек", "врач", "лекарств", "стомат", "анализ", "таблет")),
    Cat("sport", "Спорт", "🏋️", ("зал", "спорт", "фитнес", "трениров", "бассейн")),
    Cat("gifts", "Подарки", "🎁", ("подар", "цвет", "букет")),
    Cat("study", "Учёба", "📚", ("учеб", "учёб", "книг", "курс", "распечат", "принтер", "тетрад")),
    Cat("other", "Другое", "📦", ()),
]
IN_CATS = [
    Cat("salary", "Зарплата", "💼", ("зарплат", "зп", "аванс", "смен", "оплат")),
    Cat("freelance", "Фриланс", "🎬", ("трансляц", "монтаж", "съёмк", "съемк", "фриланс", "заказ", "vmix")),
    Cat("gift_in", "Подарок", "🎁", ("подар", "мама", "папа", "родител", "бабушк")),
    Cat("other_in", "Другое", "💵", ()),
]
CATS = {c.key: c for c in OUT_CATS + IN_CATS}
OUT_KEYS = {c.key for c in OUT_CATS}
IN_KEYS = {c.key for c in IN_CATS}

DEFAULT_WORK_TYPES = ["Хелпер", "Менеджер", "Трансляция", "Монтаж", "Съёмка"]


def guess_cat(note: str, kind: str) -> str:
    words = re.findall(r"[a-zа-яё0-9]+", note.lower())
    for c in (IN_CATS if kind == "in" else OUT_CATS):
        if any(w.startswith(p) for w in words for p in c.words):
            return c.key
    return "other_in" if kind == "in" else "other"


# ================= Деньги =================

def rub(k: int | None, sign: bool = False) -> str:
    """Копейки → «1 234 ₽» (копейки показываем, только если они есть)."""
    if k is None:
        return "—"
    s = "−" if k < 0 else ("+" if sign and k > 0 else "")
    k = abs(k)
    r, kop = divmod(k, 100)
    body = f"{r:,}".replace(",", " ")
    if kop:
        body += f",{kop:02d}"
    return f"{s}{body} ₽"


AMOUNT = r"(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(к|k|тыс\.?)?\s*(₽|р\.?|руб\.?|рублей|рубля)?"


def to_kop(num: str, thousand: str | None = None) -> int:
    v = float(num.replace(" ", "").replace(" ", "").replace(",", "."))
    if thousand:
        v *= 1000
    return round(v * 100)


def parse_money(text: str) -> tuple[str, int, str] | None:
    """«кофе 250» → ('out', 25000, 'кофе');  «+30000 зарплата» → ('in', 3000000, 'зарплата').
    Сумма должна стоять в начале или в конце сообщения. None — если это не похоже на трату."""
    t = text.strip()
    if not t or len(t) > 100:
        return None
    kind = "out"
    income_word = re.match(r"(?i)^(получил[аи]?|доход|пришл[оа]|перевели)\s+", t)
    if t.startswith("+") or income_word:
        kind = "in"
    if income_word:
        t = t[income_word.end():]
    t = t.lstrip("+-− ").strip()
    m = re.match(r"^" + AMOUNT + r"(?:\s+|$)(.*)$", t, re.I)
    if m:
        amount, note = to_kop(m.group(1), m.group(2)), m.group(4)
    else:
        m = re.match(r"^(.*?)\s+([+])?" + AMOUNT + r"$", t, re.I)
        if not m:
            return None
        note, amount = m.group(1), to_kop(m.group(3), m.group(4))
        if m.group(2):
            kind = "in"
    note = note.strip(" -—:,")
    if amount <= 0:
        return None
    return kind, amount, note


def parse_shift_pay(text: str) -> tuple[float | None, int | None, int]:
    """«8ч по 400» / «8 по 400» / «8×400» → (8, 40000, 320000);  «3200» → (None, None, 320000)."""
    t = text.lower().replace("х", "x").replace("×", "x").replace(",", ".")
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(ч|час[а-я]*)?\s*(по|x|\*)\s*(\d+(?:\.\d+)?)\s*(₽|р|руб.*)?\s*$", t)
    if m:
        hours, rate = float(m.group(1)), to_kop(m.group(4))
        return hours, rate, round(hours * rate)
    m = re.match(r"^\s*" + AMOUNT + r"\s*$", t)
    if m:
        return None, None, to_kop(m.group(1), m.group(2))
    raise FinError("Не понял сумму. Примеры: «3200», «8ч по 400», «8 x 400»")


# ================= Схема =================

SCHEMA = """
CREATE TABLE IF NOT EXISTS fin_tx (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,
    kind       TEXT    NOT NULL,             -- in / out / move (перевод в копилку; минус — обратно)
    amount     INTEGER NOT NULL,             -- копейки
    category   TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    in_limit   INTEGER NOT NULL DEFAULT 1,   -- считается ли в дневной лимит
    source     TEXT    NOT NULL DEFAULT 'manual',  -- manual / shift / plan / wish / saving
    ref_id     INTEGER,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fin_tx_day ON fin_tx(day);

-- Конверты: сколько денег положено в каждый (минус — переложено из него)
CREATE TABLE IF NOT EXISTS env_moves (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,
    env        TEXT    NOT NULL,             -- oblig / me / rel / want
    amount     INTEGER NOT NULL,             -- копейки, со знаком
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Лимит на день (снимок утром) и итог дня
CREATE TABLE IF NOT EXISTS fin_day_limit (
    day     TEXT PRIMARY KEY,
    lim     INTEGER NOT NULL,
    spent   INTEGER,
    settled INTEGER NOT NULL DEFAULT 0
);

-- Ожидаемые поступления (карманные, оплата заказа…)
CREATE TABLE IF NOT EXISTS expected_income (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    title  TEXT    NOT NULL,
    amount INTEGER NOT NULL,
    day    TEXT    NOT NULL,
    repeat TEXT    NOT NULL DEFAULT 'none',  -- none / month
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shifts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    day       TEXT    NOT NULL,
    company   TEXT    NOT NULL,
    work_type TEXT    NOT NULL,
    hours     REAL,
    rate      INTEGER,                       -- копеек в час
    amount    INTEGER NOT NULL,              -- копейки
    note      TEXT    NOT NULL DEFAULT '',
    paid      INTEGER NOT NULL DEFAULT 0,
    paid_day  TEXT,
    tx_id     INTEGER
);

CREATE TABLE IF NOT EXISTS planned (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title    TEXT    NOT NULL,
    amount   INTEGER NOT NULL,
    due      TEXT    NOT NULL,
    repeat   TEXT    NOT NULL DEFAULT 'none',   -- none / week / month
    category TEXT    NOT NULL DEFAULT 'other',
    active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS wishes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    target      INTEGER NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_day TEXT    NOT NULL,
    done_day    TEXT
);

CREATE TABLE IF NOT EXISTS savings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'saving',  -- saving / invest
    value      INTEGER,                            -- текущая стоимость вложения (если обновлял)
    value_day  TEXT,
    archived   INTEGER NOT NULL DEFAULT 0
);
"""


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


class Finance:
    def __init__(self, conn: sqlite3.Connection, game=None):
        self.conn = conn
        self.game = game          # нужен для настроек (лимит, начальный баланс, типы работ)
        conn.executescript(SCHEMA)

    # ---------- настройки ----------

    def _setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def _set(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()

    @property
    def daily_limit(self) -> int:
        return int(self._setting("fin_daily_limit", "0") or 0)

    @property
    def start_balance(self) -> int:
        return int(self._setting("fin_start_balance", "0") or 0)

    @property
    def work_types(self) -> list[str]:
        raw = self._setting("fin_work_types", "")
        return [w for w in raw.split("|") if w] or DEFAULT_WORK_TYPES

    def save_settings(self, daily_limit: int | None = None, start_balance: int | None = None,
                      work_types: list[str] | None = None) -> None:
        if daily_limit is not None:
            if daily_limit < 0:
                raise FinError("Лимит не может быть отрицательным")
            self._set("fin_daily_limit", str(daily_limit))
        if start_balance is not None:
            self._set("fin_start_balance", str(start_balance))
        if work_types is not None:
            clean = [w.strip()[:30] for w in work_types if w.strip()][:15]
            self._set("fin_work_types", "|".join(clean))

    # ---------- операции ----------

    def add_tx(self, day: date, kind: str, amount: int, category: str | None = None, note: str = "",
               in_limit: bool | None = None, source: str = "manual", ref_id: int | None = None,
               envelope: str | None = None) -> dict:
        if kind not in ("in", "out", "move"):
            raise FinError("Неизвестный тип операции")
        if kind != "move" and amount <= 0:
            raise FinError("Сумма должна быть больше нуля")
        if abs(amount) > 10**11:
            raise FinError("Слишком большая сумма")
        if kind == "in":
            category = category if category in IN_KEYS else guess_cat(note, "in")
        elif kind == "out":
            category = category if category in OUT_KEYS else guess_cat(note, "out")
        if in_limit is None:
            in_limit = kind == "out" and source == "manual"
        if envelope is None and kind == "out" and source == "manual":
            from .envelopes import default_envelope
            envelope = default_envelope(category)
        cur = self.conn.execute(
            "INSERT INTO fin_tx (day, kind, amount, category, note, in_limit, source, ref_id, envelope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (day.isoformat(), kind, amount, category or "move", note.strip()[:200], int(in_limit), source, ref_id,
             envelope))
        self.conn.commit()
        return self.tx(cur.lastrowid)

    def tx(self, tx_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM fin_tx WHERE id = ?", (tx_id,)).fetchone()
        if row is None:
            raise FinError("Такой операции нет")
        return self._tx(row)

    @staticmethod
    def _tx(row) -> dict:
        from .envelopes import ENVS
        d = dict(row)
        c = CATS.get(d["category"])
        d["cat_title"] = c.title if c else "Перевод"
        d["emoji"] = c.emoji if c else "🔄"
        env = ENVS.get(d.get("envelope") or "")
        d["env_emoji"], d["env_title"] = (env[0], env[1]) if env else ("", "")
        return d

    def set_tx_category(self, tx_id: int, category: str) -> dict:
        t = self.tx(tx_id)
        allowed = IN_KEYS if t["kind"] == "in" else OUT_KEYS
        if category not in allowed:
            raise FinError("Такой категории нет")
        self.conn.execute("UPDATE fin_tx SET category = ? WHERE id = ?", (category, tx_id))
        self.conn.commit()
        return self.tx(tx_id)

    def set_tx_day(self, tx_id: int, day: date, today: date) -> dict:
        """Перенести операцию на другой день (например, трату, которую записал задним числом)."""
        t = self.tx(tx_id)
        if t["source"] != "manual" or t["kind"] not in ("in", "out"):
            raise FinError("Дату этой операции меняют в её разделе (смены, платежи, копилки)")
        if day > today:
            raise FinError("Нельзя записать трату в будущее")
        if (today - day).days > 366:
            raise FinError("Слишком давно — больше года назад")
        self.conn.execute("UPDATE fin_tx SET day = ? WHERE id = ?", (day.isoformat(), tx_id))
        self.conn.commit()
        return self.tx(tx_id)

    def delete_tx(self, tx_id: int) -> dict:
        t = self.tx(tx_id)
        if t["source"] == "shift":
            # удаляем оплату смены — смена снова «ждёт оплату»
            self.conn.execute("UPDATE shifts SET paid = 0, paid_day = NULL, tx_id = NULL WHERE tx_id = ?", (tx_id,))
        self.conn.execute("DELETE FROM fin_tx WHERE id = ?", (tx_id,))
        self.conn.commit()
        return t

    def txs(self, start: date, end: date, kind: str | None = None) -> list[dict]:
        q = "SELECT * FROM fin_tx WHERE day BETWEEN ? AND ?"
        args: list = [start.isoformat(), end.isoformat()]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY day DESC, id DESC"
        return [self._tx(r) for r in self.conn.execute(q, args)]

    def balance(self) -> int:
        """Свободные деньги: начальный баланс + доходы − траты − переводы в копилки."""
        r = self.conn.execute("""SELECT
            COALESCE(SUM(CASE WHEN kind='in' THEN amount END), 0) -
            COALESCE(SUM(CASE WHEN kind='out' THEN amount END), 0) -
            COALESCE(SUM(CASE WHEN kind='move' THEN amount END), 0) FROM fin_tx""").fetchone()[0]
        return self.start_balance + r

    def spent_today(self, day: date) -> int:
        return self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='out' AND in_limit=1 AND day=?",
            (day.isoformat(),)).fetchone()[0]

    # ---------- смены ----------

    def add_shift(self, day: date, company: str, work_type: str, amount: int,
                  hours: float | None = None, rate: int | None = None, note: str = "") -> dict:
        company, work_type = company.strip()[:60], work_type.strip()[:40]
        if not company:
            raise FinError("Укажи компанию")
        if not work_type:
            raise FinError("Укажи тип работы")
        if amount <= 0:
            raise FinError("Сумма должна быть больше нуля")
        cur = self.conn.execute(
            "INSERT INTO shifts (day, company, work_type, hours, rate, amount, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (day.isoformat(), company, work_type, hours, rate, amount, note.strip()[:200]))
        self.conn.commit()
        return self.shift(cur.lastrowid)

    def shift(self, sid: int) -> dict:
        row = self.conn.execute("SELECT * FROM shifts WHERE id = ?", (sid,)).fetchone()
        if row is None:
            raise FinError("Такой смены нет")
        return dict(row)

    def shifts(self, company: str | None = None, unpaid_only: bool = False, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM shifts WHERE 1=1", []
        if company:
            q += " AND company = ?"
            args.append(company)
        if unpaid_only:
            q += " AND paid = 0"
        q += " ORDER BY day DESC, id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(q, args)]

    def edit_shift(self, sid: int, **fields) -> dict:
        s = self.shift(sid)
        allowed = {"day", "company", "work_type", "hours", "rate", "amount", "note"}
        upd = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "day" in upd and isinstance(upd["day"], date):
            upd["day"] = upd["day"].isoformat()
        if upd.get("amount", 1) <= 0:
            raise FinError("Сумма должна быть больше нуля")
        if not upd:
            return s
        sets = ", ".join(f"{k} = ?" for k in upd)
        self.conn.execute(f"UPDATE shifts SET {sets} WHERE id = ?", (*upd.values(), sid))
        if s["paid"] and s["tx_id"] and "amount" in upd:
            self.conn.execute("UPDATE fin_tx SET amount = ? WHERE id = ?", (upd["amount"], s["tx_id"]))
        self.conn.commit()
        return self.shift(sid)

    def delete_shift(self, sid: int) -> None:
        s = self.shift(sid)
        if s["tx_id"]:
            self.conn.execute("DELETE FROM fin_tx WHERE id = ?", (s["tx_id"],))
        self.conn.execute("DELETE FROM shifts WHERE id = ?", (sid,))
        self.conn.commit()

    def pay_shift(self, sid: int, day: date) -> dict:
        """Смену оплатили: деньги падают в доходы (категория «Зарплата»)."""
        s = self.shift(sid)
        if s["paid"]:
            raise FinError("Эта смена уже оплачена")
        t = self.add_tx(day, "in", s["amount"], "salary", f"{s['company']} · {s['work_type']} · {s['day'][8:10]}.{s['day'][5:7]}",
                        source="shift", ref_id=sid)
        self.conn.execute("UPDATE shifts SET paid = 1, paid_day = ?, tx_id = ? WHERE id = ?",
                          (day.isoformat(), t["id"], sid))
        self.conn.commit()
        return self.shift(sid)

    def unpay_shift(self, sid: int) -> dict:
        s = self.shift(sid)
        if s["tx_id"]:
            self.conn.execute("DELETE FROM fin_tx WHERE id = ?", (s["tx_id"],))
        self.conn.execute("UPDATE shifts SET paid = 0, paid_day = NULL, tx_id = NULL WHERE id = ?", (sid,))
        self.conn.commit()
        return self.shift(sid)

    def pay_company(self, company: str, day: date) -> tuple[int, int]:
        """Компания оплатила все долги. Возвращает (сколько смен, сумма)."""
        unpaid = self.shifts(company=company, unpaid_only=True, limit=10_000)
        if not unpaid:
            raise FinError("У этой компании нет неоплаченных смен")
        for s in unpaid:
            self.pay_shift(s["id"], day)
        return len(unpaid), sum(s["amount"] for s in unpaid)

    def companies(self) -> list[dict]:
        rows = self.conn.execute("""SELECT company,
                COUNT(*) AS shifts,
                COALESCE(SUM(amount), 0) AS earned,
                COALESCE(SUM(CASE WHEN paid=1 THEN amount END), 0) AS paid,
                COALESCE(SUM(CASE WHEN paid=0 THEN amount END), 0) AS owed,
                COALESCE(SUM(hours), 0) AS hours,
                MAX(day) AS last_day,
                MIN(CASE WHEN paid=0 THEN day END) AS oldest_unpaid
            FROM shifts GROUP BY company ORDER BY owed DESC, last_day DESC""").fetchall()
        return [dict(r) for r in rows]

    def expected_salary(self) -> int:
        return self.conn.execute("SELECT COALESCE(SUM(amount), 0) FROM shifts WHERE paid = 0").fetchone()[0]

    def recent_companies(self, n: int = 6) -> list[str]:
        rows = self.conn.execute("SELECT company, MAX(id) m FROM shifts GROUP BY company ORDER BY m DESC LIMIT ?",
                                 (n,)).fetchall()
        return [r["company"] for r in rows]

    # ---------- планируемые траты ----------

    def add_plan(self, title: str, amount: int, due: date, repeat: str = "none", category: str = "other") -> dict:
        if not title.strip():
            raise FinError("Назови платёж")
        if amount <= 0:
            raise FinError("Сумма должна быть больше нуля")
        if repeat not in ("none", "week", "month"):
            raise FinError("Повтор: none / week / month")
        if category not in OUT_KEYS:
            category = guess_cat(title, "out")
        cur = self.conn.execute("INSERT INTO planned (title, amount, due, repeat, category) VALUES (?, ?, ?, ?, ?)",
                                (title.strip()[:100], amount, due.isoformat(), repeat, category))
        self.conn.commit()
        return self.plan(cur.lastrowid)

    def plan(self, pid: int) -> dict:
        row = self.conn.execute("SELECT * FROM planned WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise FinError("Такого платежа нет")
        return dict(row)

    def plans(self, today: date, days_ahead: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM planned WHERE active = 1", []
        if days_ahead is not None:
            q += " AND due <= ?"
            args.append((today + timedelta(days=days_ahead)).isoformat())
        out = []
        for r in self.conn.execute(q + " ORDER BY due", args):
            p = dict(r)
            p["days_left"] = (date.fromisoformat(p["due"]) - today).days
            c = CATS[p["category"]]
            p["emoji"], p["cat_title"] = c.emoji, c.title
            out.append(p)
        return out

    def pay_plan(self, pid: int, day: date) -> dict:
        """Оплатил: появляется трата (не в дневной лимит). Повторяющийся платёж переезжает на следующий срок."""
        p = self.plan(pid)
        if not p["active"]:
            raise FinError("Платёж уже закрыт")
        self.add_tx(day, "out", p["amount"], p["category"], p["title"], in_limit=False, source="plan", ref_id=pid,
                    envelope="oblig")
        due = date.fromisoformat(p["due"])
        if p["repeat"] == "month":
            self.conn.execute("UPDATE planned SET due = ? WHERE id = ?", (_add_months(due, 1).isoformat(), pid))
        elif p["repeat"] == "week":
            self.conn.execute("UPDATE planned SET due = ? WHERE id = ?", ((due + timedelta(days=7)).isoformat(), pid))
        else:
            self.conn.execute("UPDATE planned SET active = 0 WHERE id = ?", (pid,))
        self.conn.commit()
        return self.plan(pid)

    def edit_plan(self, pid: int, title=None, amount=None, due: date | None = None, repeat=None) -> dict:
        p = self.plan(pid)
        self.conn.execute("UPDATE planned SET title=?, amount=?, due=?, repeat=? WHERE id=?",
                          ((title or p["title"]).strip(), amount or p["amount"],
                           due.isoformat() if due else p["due"], repeat or p["repeat"], pid))
        self.conn.commit()
        return self.plan(pid)

    def delete_plan(self, pid: int) -> None:
        self.plan(pid)
        self.conn.execute("UPDATE planned SET active = 0 WHERE id = ?", (pid,))
        self.conn.commit()

    # ---------- карта желаний ----------

    def _wish_saved(self, wid: int) -> int:
        return self.conn.execute("SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='move' AND source='wish' "
                                 "AND ref_id = ?", (wid,)).fetchone()[0]

    def add_wish(self, title: str, target: int, today: date) -> dict:
        if not title.strip():
            raise FinError("Назови желание")
        if target <= 0:
            raise FinError("Цель должна быть больше нуля")
        cur = self.conn.execute("INSERT INTO wishes (title, target, created_day) VALUES (?, ?, ?)",
                                (title.strip()[:100], target, today.isoformat()))
        self.conn.commit()
        return self.wish(cur.lastrowid)

    def wish(self, wid: int) -> dict:
        row = self.conn.execute("SELECT * FROM wishes WHERE id = ?", (wid,)).fetchone()
        if row is None:
            raise FinError("Такого желания нет")
        w = dict(row)
        w["saved"] = self._wish_saved(wid)
        w["progress"] = min(100, round(100 * w["saved"] / w["target"])) if w["target"] else 0
        return w

    def wishes(self, include_done: bool = True) -> list[dict]:
        q = "SELECT id FROM wishes" + ("" if include_done else " WHERE done = 0") + " ORDER BY done, id"
        return [self.wish(r["id"]) for r in self.conn.execute(q)]

    def wish_add_money(self, wid: int, amount: int, day: date) -> dict:
        """Отложить на желание (минус — забрать обратно)."""
        w = self.wish(wid)
        if w["done"]:
            raise FinError("Желание уже исполнено")
        if amount == 0:
            raise FinError("Сумма не может быть нулём")
        if amount < 0 and -amount > w["saved"]:
            raise FinError(f"Отложено только {rub(w['saved'])}")
        self.add_tx(day, "move", amount, None, w["title"], in_limit=False, source="wish", ref_id=wid)
        return self.wish(wid)

    def wish_done(self, wid: int, day: date, spend: bool = True) -> dict:
        """Исполнил желание: отложенное превращается в покупку (трату вне лимита)."""
        w = self.wish(wid)
        if w["done"]:
            raise FinError("Уже исполнено")
        if spend and w["saved"] > 0:
            # возвращаем отложенное из копилки и сразу тратим
            self.add_tx(day, "move", -w["saved"], None, w["title"], in_limit=False, source="wish", ref_id=wid)
            self.add_tx(day, "out", w["saved"], "shop", f"🎯 {w['title']}", in_limit=False, source="wish", ref_id=wid)
        self.conn.execute("UPDATE wishes SET done = 1, done_day = ? WHERE id = ?", (day.isoformat(), wid))
        self.conn.commit()
        return self.wish(wid)

    def delete_wish(self, wid: int, day: date) -> None:
        w = self.wish(wid)
        if w["saved"] > 0 and not w["done"]:
            self.add_tx(day, "move", -w["saved"], None, w["title"], in_limit=False, source="wish", ref_id=wid)
        self.conn.execute("DELETE FROM wishes WHERE id = ?", (wid,))
        self.conn.commit()

    # ---------- накопления и вложения ----------

    def add_saving(self, title: str, kind: str = "saving") -> dict:
        if not title.strip():
            raise FinError("Назови копилку")
        if kind not in ("saving", "invest"):
            raise FinError("Тип: saving / invest")
        cur = self.conn.execute("INSERT INTO savings (title, kind) VALUES (?, ?)", (title.strip()[:60], kind))
        self.conn.commit()
        return self.saving(cur.lastrowid)

    def saving(self, sid: int) -> dict:
        row = self.conn.execute("SELECT * FROM savings WHERE id = ?", (sid,)).fetchone()
        if row is None:
            raise FinError("Такой копилки нет")
        s = dict(row)
        s["invested"] = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='move' AND source='saving' AND ref_id=?",
            (sid,)).fetchone()[0]
        # для вклада/копилки стоимость = сколько положил; для вложений — последняя оценка (если была)
        s["current"] = s["value"] if (s["kind"] == "invest" and s["value"] is not None) else s["invested"]
        s["profit"] = s["current"] - s["invested"]
        return s

    def savings(self) -> list[dict]:
        return [self.saving(r["id"]) for r in self.conn.execute(
            "SELECT id FROM savings WHERE archived = 0 ORDER BY kind, id")]

    def saving_move(self, sid: int, amount: int, day: date) -> dict:
        """Пополнить (плюс) или снять (минус)."""
        s = self.saving(sid)
        if amount == 0:
            raise FinError("Сумма не может быть нулём")
        if amount < 0 and -amount > s["current"]:
            raise FinError(f"Там только {rub(s['current'])}")
        self.add_tx(day, "move", amount, None, s["title"], in_limit=False, source="saving", ref_id=sid)
        if s["kind"] == "invest" and s["value"] is not None:
            self.conn.execute("UPDATE savings SET value = value + ? WHERE id = ?", (amount, sid))
            self.conn.commit()
        return self.saving(sid)

    def saving_value(self, sid: int, value: int, day: date) -> dict:
        """Обновить текущую стоимость вложения (например, портфель вырос)."""
        s = self.saving(sid)
        if s["kind"] != "invest":
            raise FinError("Стоимость обновляется только у вложений")
        if value < 0:
            raise FinError("Стоимость не может быть отрицательной")
        self.conn.execute("UPDATE savings SET value = ?, value_day = ? WHERE id = ?", (value, day.isoformat(), sid))
        self.conn.commit()
        return self.saving(sid)

    def archive_saving(self, sid: int) -> None:
        s = self.saving(sid)
        if s["current"] > 0:
            raise FinError("Сначала сними деньги")
        self.conn.execute("UPDATE savings SET archived = 1 WHERE id = ?", (sid,))
        self.conn.commit()

    # ---------- сводка и статистика ----------

    def overview(self, today: date) -> dict:
        month_start = today.replace(day=1)
        month = self.period_totals(month_start, today)
        sv = self.savings()
        ws = self.wishes(include_done=False)
        return {
            "today": today.isoformat(),
            "balance": self.balance(),
            "spent_today": self.spent_today(today),
            "daily_limit": self.daily_limit,
            "month_in": month["income"], "month_out": month["expense"],
            "expected_salary": self.expected_salary(),
            "companies_owed": [c for c in self.companies() if c["owed"] > 0],
            "plans_soon": self.plans(today, 14),
            "wishes": ws,
            "savings_total": sum(s["current"] for s in sv),
            "wishes_saved": sum(w["saved"] for w in ws),
            "recent": self.txs(today - timedelta(days=60), today)[:15],
        }

    def period_totals(self, start: date, end: date) -> dict:
        r = self.conn.execute("""SELECT
                COALESCE(SUM(CASE WHEN kind='in' THEN amount END), 0),
                COALESCE(SUM(CASE WHEN kind='out' THEN amount END), 0)
            FROM fin_tx WHERE day BETWEEN ? AND ?""", (start.isoformat(), end.isoformat())).fetchone()
        return {"income": r[0], "expense": r[1]}

    def stats(self, start: date, end: date) -> dict:
        if end < start:
            start, end = end, start
        if (end - start).days > 800:
            raise FinError("Слишком длинный период")
        tot = self.period_totals(start, end)
        by_cat = []
        for r in self.conn.execute("""SELECT kind, category, SUM(amount) s, COUNT(*) n FROM fin_tx
                WHERE kind IN ('in','out') AND day BETWEEN ? AND ? GROUP BY kind, category ORDER BY s DESC""",
                                   (start.isoformat(), end.isoformat())):
            c = CATS[r["category"]]
            by_cat.append({"kind": r["kind"], "key": c.key, "title": c.title, "emoji": c.emoji,
                           "sum": r["s"], "count": r["n"]})
        daily = {}
        for r in self.conn.execute("""SELECT day, kind, SUM(amount) s FROM fin_tx WHERE kind IN ('in','out')
                AND day BETWEEN ? AND ? GROUP BY day, kind""", (start.isoformat(), end.isoformat())):
            daily.setdefault(r["day"], {"in": 0, "out": 0})[r["kind"]] = r["s"]
        days, d = [], start
        while d <= end:
            x = daily.get(d.isoformat(), {"in": 0, "out": 0})
            days.append({"day": d.isoformat(), "in": x["in"], "out": x["out"]})
            d += timedelta(days=1)
        sh = self.conn.execute("""SELECT company, COUNT(*) n, SUM(amount) s, COALESCE(SUM(hours),0) h FROM shifts
                WHERE day BETWEEN ? AND ? GROUP BY company ORDER BY s DESC""",
                               (start.isoformat(), end.isoformat())).fetchall()
        n_days = (end - start).days + 1
        limit_days = sum(1 for x in days if x["out"] > 0)
        return {
            "start": start.isoformat(), "end": end.isoformat(), **tot,
            "net": tot["income"] - tot["expense"],
            "avg_day_out": round(tot["expense"] / n_days),
            "by_category": by_cat, "days": days,
            "shifts": [dict(r) for r in sh],
            "shifts_total": sum(r["s"] for r in sh),
            "days_with_spending": limit_days,
        }

    def limit_streak(self, today: date) -> int:
        """Сколько дней подряд (до вчера) траты не превышали лимит."""
        lim = self.daily_limit
        if not lim:
            return 0
        n, d = 0, today - timedelta(days=1)
        first = self.conn.execute("SELECT MIN(day) FROM fin_tx").fetchone()[0]
        if not first:
            return 0
        while d.isoformat() >= first and self.spent_today(d) <= lim:
            n += 1
            d -= timedelta(days=1)
        return n

    def counts(self) -> dict:
        """Для достижений."""
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {
            "tx_out": q("SELECT COUNT(*) FROM fin_tx WHERE kind='out' AND source='manual'"),
            "shifts": q("SELECT COUNT(*) FROM shifts"),
            "wishes_done": q("SELECT COUNT(*) FROM wishes WHERE done=1"),
            "max_payout_shifts": q("SELECT COALESCE(MAX(n),0) FROM (SELECT COUNT(*) n FROM shifts WHERE paid=1 "
                                   "GROUP BY company, paid_day)"),
        }

    def digest(self, today: date) -> list[dict]:
        """Платежи, о которых стоит напомнить: просроченные, сегодня, завтра."""
        return [p for p in self.plans(today, 1)]


def now_day(tz, start_hour: int) -> date:
    return (datetime.now(tz) - timedelta(hours=start_hour)).date()
