"""
Игровая логика. Бот и веб-приложение зовут только эти функции,
поэтому правила работают одинаково везде.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from . import rules
from .promise_text import due_label


class GameError(Exception):
    """Ошибка, которую можно показать игроку как есть."""


@dataclass
class Quest:
    id: int
    day: str
    category: rules.Category
    title: str
    xp: int
    status: str

    @property
    def is_main(self) -> bool:
        return self.category.is_main

    def line(self) -> str:
        mark = {"todo": "▫️", "done": "✅", "failed": "❌"}[self.status]
        return f"{mark} {self.category.emoji} {self.title} — {self.xp} XP"

    def to_dict(self) -> dict:
        return {"id": self.id, "day": self.day, "category": self.category.key,
                "title": self.title, "xp": self.xp, "status": self.status,
                "is_main": self.is_main}


@dataclass
class Stats:
    total_xp: int
    xp_on_day: int
    level: rules.LevelInfo
    coins: int

    def to_dict(self) -> dict:
        return {"total_xp": self.total_xp, "xp_on_day": self.xp_on_day,
                "level": asdict(self.level), "coins": self.coins}


def game_day(now: datetime, day_start_hour: int) -> date:
    """Игровой день начинается не в полночь, а в day_start_hour (например, в 5 утра).
    Так «вовремя лечь» в 00:30 ещё засчитается во вчерашний день."""
    return (now - timedelta(hours=day_start_hour)).date()


def _row_to_quest(row: sqlite3.Row) -> Quest:
    return Quest(
        id=row["id"], day=row["day"], category=rules.CATEGORIES[row["category"]],
        title=row["title"], xp=row["xp"], status=row["status"],
    )


# Шаблоны, которые появятся при первом запуске (из твоих примеров квестов)
STARTER_TEMPLATES = [
    ("study", "Задание по учёбе", 200),
    ("work", "Смена на работе", 300),
    ("gutv", "Смонтировать видео для студии", 250),
    ("sleep", "Вовремя лечь", 80),
    ("code", "Написать алгоритм", 100),
]

SHOP_KINDS = {"wish": "🎁 Вишлист", "trip": "🗺 Поход", "fun": "🎲 Интерактив"}


# Достижения: (ключ, эмодзи, название, описание, секретное?)
# 🙈 Ваня, секретные условия ниже — не подглядывай!
ACHIEVEMENTS = [
    ("first", "🩸", "Первая кровь", "Выполни первый квест", False),
    ("lvl5", "⭐", "Уже не новичок", "Дойди до 5 уровня", False),
    ("lvl10", "🌟", "Свой человек", "Дойди до 10 уровня", False),
    ("lvl25", "👑", "Хозяин района", "Дойди до 25 уровня", False),
    ("streak3", "🔥", "Разогрев", "Серия 3 дня", False),
    ("streak7", "🔥", "Неделя без промахов", "Серия 7 дней", False),
    ("streak30", "☄️", "Машина", "Серия 30 дней", False),
    ("day1000", "💥", "Тысячник", "1000 XP за один день", False),
    ("ultra", "🧨", "Ультра хард", "Выполни квест с XP выше обычного", False),
    ("perfect", "💯", "Идеальный день", "Выполни все квесты дня (минимум 4)", False),
    ("sleep7", "😴", "Режим", "7 раз вовремя лечь", False),
    ("allcats", "🎯", "Многостаночник", "Выполни квесты во всех основных категориях", False),
    ("shopper", "🛍", "Заслужил", "Первая покупка в магазине", False),
    # --- вторая партия ---
    ("gutv20", "🎬", "Режиссёр", "20 квестов по ГУТВ", False),
    ("work10", "🦺", "Железный хелпер", "10 рабочих смен", False),
    ("study50", "🎓", "Ботаник", "50 квестов по учёбе", False),
    ("code30", "🧠", "Алгоритмист", "30 квестов по программированию", False),
    ("sleep30", "🛌", "Сова в завязке", "30 раз вовремя лечь", False),
    ("blitz", "⚡", "Блиц", "5 квестов за один день", False),
    ("strike", "🎳", "Страйк", "10 квестов подряд без единого провала", False),
    ("perfect7", "💎", "Перфекционист", "7 идеальных дней подряд (всё, включая бонусы)", False),
    ("piggy", "🐷", "Копилка", "Накопи 2000 монет", False),
    ("spender", "💸", "Транжира", "Потрать в магазине 1000 монет", False),
    ("architect", "🏗", "Архитектор", "Создай 10 шаблонов", False),
    ("xp10k", "📈", "Пятизначный", "10 000 XP за всё время", False),
    # --- обещания ---
    ("word10", "🤝", "Человек слова", "Сдержи 10 обещаний", False),
    ("fastword", "⚡", "Быстрее, чем спросят", "5 раз сдержи обещание в течение суток", False),
    ("cleanslate", "🧹", "Чистый лист", "Закрой все обещания (и хотя бы 5 сдержанных)", False),
    # --- секретные ---
    ("night", "🌃", "Ночная смена", "Выполнил квест между 2 и 5 часами ночи", True),
    ("early", "🐓", "Ранняя пташка", "Выполнил квест до 7 утра", True),
    ("lastmin", "⏰", "В последний момент", "Закрыл основной квест после 23:30 в его же день", True),
    ("jackpot", "🎰", "Джекпот", "Ровно 777 XP за день", True),
    ("phoenix", "🐦‍🔥", "Феникс", "Вернулся после недели без квестов и закрыл день", True),
    ("oops", "🤡", "Ой", "Провалил 3 квеста за один день", True),
    ("undo", "🔁", "Передумал", "Отменил выполнение 10 раз", True),
    ("zero", "🪙", "До копейки", "Потратил монеты ровно в ноль", True),
    ("fri13", "🐈‍⬛", "Пятница, 13", "Выполнил квест в пятницу 13-го", True),
    ("newyear", "🎄", "С Новым годом!", "Выполнил квест 1 января", True),
    ("knight", "🌹", "Рыцарь", "Сдержал 50 обещаний", True),
]


class Game:
    def __init__(self, conn: sqlite3.Connection, tz=None):
        self.conn = conn
        self.tz = tz   # время выполнения квестов пишется по этому поясу (Москва)
        if self.get_setting("seeded") is None:
            for cat, title, xp in STARTER_TEMPLATES:
                self.conn.execute("INSERT INTO templates (category, title, xp) VALUES (?, ?, ?)",
                                  (cat, title, xp))
            self.set_setting("seeded", "1")

    # ================= Квесты =================

    def _check_main_limit(self, day: date, category: rules.Category, ignore_id: int | None = None):
        if not category.is_main:
            return
        mains = sum(1 for q in self.quests(day) if q.is_main and q.id != ignore_id)
        if mains >= rules.MAX_MAIN_PER_DAY:
            raise GameError(f"На этот день уже {rules.MAX_MAIN_PER_DAY} основных задания. "
                            "Удали одно или сделай квест бонусным.")

    @staticmethod
    def _check_fields(title: str, xp: int):
        if xp < 0:
            raise GameError("XP не может быть отрицательным")
        if xp > 100_000:
            raise GameError("Это уже читерство 😄")
        if not title.strip():
            raise GameError("У квеста должно быть название")
        if len(title) > 200:
            raise GameError("Слишком длинное название")

    def add_quest(self, day: date, category: rules.Category, title: str, xp: int) -> tuple[Quest, str | None]:
        """Добавляет квест. Возвращает (квест, предупреждение про XP или None)."""
        self._check_fields(title, xp)
        self._check_main_limit(day, category)
        cur = self.conn.execute(
            "INSERT INTO quests (day, category, title, xp) VALUES (?, ?, ?, ?)",
            (day.isoformat(), category.key, title.strip(), xp),
        )
        self.conn.commit()
        return self.get(cur.lastrowid), rules.xp_warning(category, xp)

    def edit_quest(self, quest_id: int, title: str | None = None, xp: int | None = None,
                   day: date | None = None) -> Quest:
        """Меняет название, XP или переносит квест на другой день."""
        q = self.get(quest_id)
        new_title = q.title if title is None else title
        new_xp = q.xp if xp is None else xp
        self._check_fields(new_title, new_xp)
        new_day = q.day
        if day is not None and day.isoformat() != q.day:
            if q.status == "done":
                raise GameError("Выполненный квест нельзя перенести")
            self._check_main_limit(day, q.category)
            new_day = day.isoformat()
        self.conn.execute("UPDATE quests SET title = ?, xp = ?, day = ?, status = ? WHERE id = ?",
                          (new_title.strip(), new_xp, new_day,
                           "todo" if new_day != q.day else q.status, quest_id))
        self.conn.commit()
        return self.get(quest_id)

    def delete_quest(self, quest_id: int) -> Quest:
        q = self.get(quest_id)
        if q.status == "done":
            raise GameError("Выполненный квест удалить нельзя — сначала отмени выполнение")
        self.conn.execute("DELETE FROM quests WHERE id = ?", (quest_id,))
        self.conn.commit()
        return q

    def set_status(self, quest_id: int, status: str) -> tuple[Quest, int, int]:
        """Меняет статус квеста. Возвращает (квест, уровень до, уровень после)."""
        if status not in ("todo", "done", "failed"):
            raise GameError("Неизвестный статус")
        old = self.get(quest_id)  # заодно проверка, что квест существует
        before = self.stats().level.level
        now = datetime.now(self.tz).replace(tzinfo=None).isoformat(timespec="seconds")
        done_at = now if status in ("done", "failed") else None
        if old.status == "done" and status == "todo":
            self.set_setting("undo_count", str(int(self.get_setting("undo_count", "0")) + 1))
        self.conn.execute("UPDATE quests SET status = ?, done_at = ? WHERE id = ?",
                          (status, done_at, quest_id))
        self.conn.commit()
        after = self.stats().level.level
        return self.get(quest_id), before, after

    def mark(self, quest_id: int, status: str, today: date) -> dict:
        """То же, что set_status, но ещё сообщает про новые достижения."""
        before = self._achieved(today)
        q0 = self.get(quest_id)
        if q0.category.key == "promise" and status != "done":
            # отменил «сдержал»: XP убирается, обещание снова открыто
            lvl_before = self.stats().level.level
            self.conn.execute("UPDATE promises SET status='open', closed_day=NULL, quest_id=NULL WHERE quest_id=?",
                              (quest_id,))
            self.conn.execute("DELETE FROM quests WHERE id = ?", (quest_id,))
            self.conn.commit()
            q0.status = "todo"
            return {"quest": q0, "level_before": lvl_before, "level_after": self.stats().level.level,
                    "new_achievements": []}
        q, lvl_before, lvl_after = self.set_status(quest_id, status)
        new = [a for a in self.full_stats(today)["achievements"]
               if a["done"] and a["key"] not in before]
        return {"quest": q, "level_before": lvl_before, "level_after": lvl_after,
                "new_achievements": new}

    def _achieved(self, today: date) -> set[str]:
        return {a["key"] for a in self.full_stats(today)["achievements"] if a["done"]}

    def get(self, quest_id: int) -> Quest:
        row = self.conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        if row is None:
            raise GameError(f"Квеста #{quest_id} нет")
        return _row_to_quest(row)

    def quests(self, day: date) -> list[Quest]:
        rows = self.conn.execute(
            "SELECT * FROM quests WHERE day = ? ORDER BY id", (day.isoformat(),)
        ).fetchall()
        # основные сверху, бонусные снизу
        return sorted((_row_to_quest(r) for r in rows), key=lambda q: not q.is_main)

    # ================= Шаблоны =================

    def templates(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM templates ORDER BY category, title").fetchall()
        return [dict(r) for r in rows]

    def add_template(self, category: rules.Category, title: str, xp: int) -> dict:
        self._check_fields(title, xp)
        cur = self.conn.execute("INSERT INTO templates (category, title, xp) VALUES (?, ?, ?)",
                                (category.key, title.strip(), xp))
        self.conn.commit()
        return self.template(cur.lastrowid)

    def template(self, template_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            raise GameError("Такого шаблона нет")
        return dict(row)

    def delete_template(self, template_id: int) -> None:
        self.template(template_id)
        self.conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        self.conn.commit()

    def add_from_template(self, day: date, template_id: int) -> tuple[Quest, str | None]:
        t = self.template(template_id)
        return self.add_quest(day, rules.CATEGORIES[t["category"]], t["title"], t["xp"])

    # ================= Магазин =================

    def shop_items(self, include_archived: bool = False) -> list[dict]:
        rows = self.conn.execute(
            """SELECT i.*, (SELECT COUNT(*) FROM purchases p WHERE p.item_id = i.id) AS bought
               FROM shop_items i WHERE i.archived = 0 OR ? ORDER BY i.cost""",
            (1 if include_archived else 0,),
        ).fetchall()
        return [dict(r) for r in rows]

    def shop_item(self, item_id: int) -> dict:
        row = self.conn.execute(
            """SELECT i.*, (SELECT COUNT(*) FROM purchases p WHERE p.item_id = i.id) AS bought
               FROM shop_items i WHERE i.id = ?""", (item_id,)).fetchone()
        if row is None:
            raise GameError("Такого товара нет")
        return dict(row)

    def add_shop_item(self, title: str, cost: int, kind: str = "wish", repeatable: bool = False) -> dict:
        if not title.strip():
            raise GameError("У товара должно быть название")
        if cost <= 0:
            raise GameError("Цена должна быть больше нуля")
        if kind not in SHOP_KINDS:
            raise GameError("Неизвестный тип товара")
        cur = self.conn.execute(
            "INSERT INTO shop_items (title, kind, cost, repeatable) VALUES (?, ?, ?, ?)",
            (title.strip(), kind, cost, 1 if repeatable else 0))
        self.conn.commit()
        return self.shop_item(cur.lastrowid)

    def edit_shop_item(self, item_id: int, title: str | None = None, cost: int | None = None,
                       kind: str | None = None, repeatable: bool | None = None) -> dict:
        it = self.shop_item(item_id)
        title = it["title"] if title is None else title
        cost = it["cost"] if cost is None else cost
        kind = it["kind"] if kind is None else kind
        rep = it["repeatable"] if repeatable is None else (1 if repeatable else 0)
        if not title.strip() or cost <= 0 or kind not in SHOP_KINDS:
            raise GameError("Проверь название, цену и тип")
        self.conn.execute("UPDATE shop_items SET title=?, cost=?, kind=?, repeatable=? WHERE id=?",
                          (title.strip(), cost, kind, rep, item_id))
        self.conn.commit()
        return self.shop_item(item_id)

    def archive_shop_item(self, item_id: int) -> None:
        self.shop_item(item_id)
        self.conn.execute("UPDATE shop_items SET archived = 1 WHERE id = ?", (item_id,))
        self.conn.commit()

    def buy(self, item_id: int) -> tuple[dict, int]:
        """Покупка. Возвращает (товар, остаток монет)."""
        it = self.shop_item(item_id)
        if it["archived"]:
            raise GameError("Этот товар убран из магазина")
        if not it["repeatable"] and it["bought"] > 0:
            raise GameError("Уже куплено")
        coins = self.stats().coins
        if coins < it["cost"]:
            raise GameError(f"Не хватает {it['cost'] - coins} монет")
        self.conn.execute("INSERT INTO purchases (title, cost, item_id) VALUES (?, ?, ?)",
                          (it["title"], it["cost"], item_id))
        self.conn.commit()
        return self.shop_item(item_id), self.stats().coins

    def purchases(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def refund(self, purchase_id: int) -> None:
        """Отмена покупки (если нажал случайно) — монеты возвращаются."""
        row = self.conn.execute("SELECT id FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        if row is None:
            raise GameError("Такой покупки нет")
        self.conn.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
        self.conn.commit()

    # ================= Обещания =================

    def _promise(self, row: sqlite3.Row, today: date) -> dict:
        p = dict(row)
        due = date.fromisoformat(p["due"]) if p["due"] else None
        p["age"] = (today - date.fromisoformat(p["created_day"])).days
        p["overdue"] = p["status"] == "open" and due is not None and due < today
        p["due_label"] = due_label(due, today)
        p["xp_now"] = self.promise_xp(p, today)
        return p

    @staticmethod
    def promise_xp(p: dict, today: date) -> int:
        fast = (today - date.fromisoformat(p["created_day"])).days <= rules.PROMISE_FAST_DAYS
        return round(rules.PROMISE_XP * (rules.PROMISE_FAST_MULT if fast else 1))

    def promise(self, pid: int, today: date) -> dict:
        row = self.conn.execute("SELECT * FROM promises WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise GameError("Такого обещания нет")
        return self._promise(row, today)

    def add_promise(self, text: str, today: date, due: date | None = None) -> dict:
        text = text.strip()
        if not text:
            raise GameError("Напиши, что обещал")
        if len(text) > 300:
            raise GameError("Слишком длинно — сократи")
        cur = self.conn.execute("INSERT INTO promises (text, created_day, due) VALUES (?, ?, ?)",
                                (text, today.isoformat(), due.isoformat() if due else None))
        self.conn.commit()
        return self.promise(cur.lastrowid, today)

    def promises(self, today: date, status: str = "open") -> list[dict]:
        rows = self.conn.execute("SELECT * FROM promises WHERE status = ?", (status,)).fetchall()
        items = [self._promise(r, today) for r in rows]
        if status == "open":
            # сначала просроченные и с ближайшим сроком, потом без срока — самые старые сверху
            items.sort(key=lambda p: (p["due"] is None, p["due"] or "", -p["age"]))
        else:
            items.sort(key=lambda p: p["closed_day"] or "", reverse=True)
        return items

    def set_promise_due(self, pid: int, due: date | None, today: date) -> dict:
        p = self.promise(pid, today)
        if p["status"] != "open":
            raise GameError("Обещание уже закрыто")
        moved = 1 if p["due"] and (due is None or due.isoformat() > p["due"]) else 0
        self.conn.execute("UPDATE promises SET due = ?, postponed = postponed + ? WHERE id = ?",
                          (due.isoformat() if due else None, moved, pid))
        self.conn.commit()
        return self.promise(pid, today)

    def keep_promise(self, pid: int, today: date) -> dict:
        """Сдержал: создаётся выполненный квест «💌 …» с XP, считаются уровни и достижения."""
        p = self.promise(pid, today)
        if p["status"] != "open":
            raise GameError("Обещание уже закрыто")
        before = self._achieved(today)
        lvl_before = self.stats().level.level
        now = datetime.now(self.tz).replace(tzinfo=None).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'promise', ?, ?, 'done', ?)",
            (today.isoformat(), p["text"], p["xp_now"], now))
        self.conn.execute("UPDATE promises SET status = 'kept', closed_day = ?, quest_id = ? WHERE id = ?",
                          (today.isoformat(), cur.lastrowid, pid))
        self.conn.commit()
        new = [a for a in self.full_stats(today)["achievements"] if a["done"] and a["key"] not in before]
        return {"promise": self.promise(pid, today), "xp": p["xp_now"],
                "fast": p["xp_now"] > rules.PROMISE_XP,
                "level_before": lvl_before, "level_after": self.stats().level.level,
                "new_achievements": new}

    def cancel_promise(self, pid: int, today: date) -> dict:
        """Отменили вместе (договорились, что не нужно) — без XP и без штрафа."""
        p = self.promise(pid, today)
        if p["status"] != "open":
            raise GameError("Обещание уже закрыто")
        self.conn.execute("UPDATE promises SET status = 'cancelled', closed_day = ? WHERE id = ?",
                          (today.isoformat(), pid))
        self.conn.commit()
        return self.promise(pid, today)

    def promise_stats(self, today: date) -> dict:
        rows = self.conn.execute("SELECT * FROM promises").fetchall()
        kept = [r for r in rows if r["status"] == "kept"]
        on_time = [r for r in kept if not r["due"] or r["closed_day"] <= r["due"]]
        fast = [r for r in kept if (date.fromisoformat(r["closed_day"]) - date.fromisoformat(r["created_day"])).days <= 1]
        return {
            "open": sum(1 for r in rows if r["status"] == "open"),
            "overdue": sum(1 for r in rows if r["status"] == "open" and r["due"] and r["due"] < today.isoformat()),
            "kept": len(kept), "on_time": len(on_time), "fast": len(fast),
            "cancelled": sum(1 for r in rows if r["status"] == "cancelled"),
        }

    def promises_to_nudge(self, today: date) -> dict:
        """Что напомнить сегодня: просроченные, на сегодня, на завтра и «зависшие» без срока."""
        items = self.promises(today)
        t, tm = today.isoformat(), (today + timedelta(days=1)).isoformat()
        hanging = [p for p in items if p["due"] is None and p["age"] >= rules.PROMISE_NUDGE_AFTER
                   and (p["last_nudge"] is None or
                        (today - date.fromisoformat(p["last_nudge"])).days >= rules.PROMISE_NUDGE_AFTER)]
        return {
            "overdue": [p for p in items if p["overdue"]],
            "today": [p for p in items if p["due"] == t],
            "tomorrow": [p for p in items if p["due"] == tm],
            "hanging": hanging,
        }

    def mark_nudged(self, ids: list[int], today: date) -> None:
        self.conn.executemany("UPDATE promises SET last_nudge = ? WHERE id = ?",
                              [(today.isoformat(), i) for i in ids])
        self.conn.commit()

    # ================= Статистика =================

    def stats(self, day: date | None = None) -> Stats:
        total = self.conn.execute(
            "SELECT COALESCE(SUM(xp), 0) FROM quests WHERE status = 'done'"
        ).fetchone()[0]
        on_day = 0
        if day is not None:
            on_day = self.conn.execute(
                "SELECT COALESCE(SUM(xp), 0) FROM quests WHERE status = 'done' AND day = ?",
                (day.isoformat(),),
            ).fetchone()[0]
        spent = self.conn.execute("SELECT COALESCE(SUM(cost), 0) FROM purchases").fetchone()[0]
        return Stats(
            total_xp=total,
            xp_on_day=on_day,
            level=rules.level_info(total),
            coins=rules.coins_earned(total) - spent,
        )

    def _days_summary(self) -> dict[str, dict]:
        """Сводка по каждому дню, где были квесты."""
        out: dict[str, dict] = {}
        for r in self.conn.execute("SELECT day, category, xp, status FROM quests"):
            d = out.setdefault(r["day"], {"xp": 0, "planned": 0, "main_total": 0, "main_done": 0,
                                          "total": 0, "done": 0, "failed": 0})
            is_main = rules.CATEGORIES[r["category"]].is_main
            d["planned"] += r["xp"]
            d["total"] += 1
            if is_main:
                d["main_total"] += 1
            if r["status"] == "done":
                d["xp"] += r["xp"]
                d["done"] += 1
                if is_main:
                    d["main_done"] += 1
            elif r["status"] == "failed":
                d["failed"] += 1
        return out

    @staticmethod
    def _complete(d: dict | None) -> bool:
        """День засчитан в серию, если было хоть одно основное и все основные выполнены."""
        return bool(d) and d["main_total"] > 0 and d["main_done"] == d["main_total"]

    def streaks(self, today: date, summary: dict | None = None) -> tuple[int, int]:
        """(текущая серия, лучшая серия). Сегодняшний день ещё идёт и серию не рвёт."""
        s = summary if summary is not None else self._days_summary()
        cur = 0
        d = today if self._complete(s.get(today.isoformat())) else today - timedelta(days=1)
        while self._complete(s.get(d.isoformat())):
            cur += 1
            d -= timedelta(days=1)
        best = run = 0
        if s:
            d = date.fromisoformat(min(s))
            while d <= today:
                run = run + 1 if self._complete(s.get(d.isoformat())) else 0
                best = max(best, run)
                d += timedelta(days=1)
        return cur, max(best, cur)

    def full_stats(self, today: date, days: int = 84) -> dict:
        s = self._days_summary()
        st = self.stats(today)
        cur, best = self.streaks(today, s)

        history = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            x = s.get(d, {})
            history.append({"day": d, "xp": x.get("xp", 0), "planned": x.get("planned", 0),
                            "main_total": x.get("main_total", 0), "main_done": x.get("main_done", 0),
                            "complete": self._complete(x or None)})

        since = (today - timedelta(days=29)).isoformat()
        by_cat = {k: {"xp": 0, "xp30": 0, "done": 0} for k in rules.CATEGORIES}
        for r in self.conn.execute("SELECT day, category, xp FROM quests WHERE status='done'"):
            c = by_cat[r["category"]]
            c["xp"] += r["xp"]
            c["done"] += 1
            if r["day"] >= since:
                c["xp30"] += r["xp"]

        # Процент выполнения за 30 дней (сегодня не считаем — он ещё идёт)
        done = closed = 0
        for d, x in s.items():
            if since <= d < today.isoformat():
                done += x["done"]
                closed += x["total"]
        rate = round(100 * done / closed) if closed else None

        best_day = max((x["xp"] for x in s.values()), default=0)
        return {
            **st.to_dict(),
            "streak": cur, "best_streak": best,
            "best_day_xp": best_day,
            "completion_30": rate,
            "quests_done": sum(c["done"] for c in by_cat.values()),
            "history": history,
            "by_category": by_cat,
            "achievements": self.achievements(today, s, st, best),
        }

    def achievements(self, today: date, s: dict, st: Stats, best_streak: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT day, category, xp, status, done_at, created_at FROM quests "
            "WHERE status IN ('done', 'failed') ORDER BY day, COALESCE(done_at, created_at), id").fetchall()
        done_rows = [r for r in rows if r["status"] == "done"]
        cnt = {k: 0 for k in rules.CATEGORIES}
        for r in done_rows:
            cnt[r["category"]] += 1
        cats_done = {k for k, v in cnt.items() if v}
        main_cats = {k for k, c in rules.CATEGORIES.items() if c.is_main}
        lvl = st.level.level
        spent = self.conn.execute("SELECT COALESCE(SUM(cost), 0) FROM purchases").fetchone()[0]
        bought = self.conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] > 0
        n_templates = self.conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
        ps = self.promise_stats(today)

        # 10 подряд без провала
        run = best_run = 0
        for r in rows:
            run = run + 1 if r["status"] == "done" else 0
            best_run = max(best_run, run)

        # 7 идеальных дней подряд
        def perfect_day(x):
            return x and x["main_total"] > 0 and x["done"] == x["total"]
        p_run = p_best = 0
        if s:
            d = date.fromisoformat(min(s))
            while d <= today:
                p_run = p_run + 1 if perfect_day(s.get(d.isoformat())) else 0
                p_best = max(p_best, p_run)
                d += timedelta(days=1)

        # Время выполнения (часы:минуты по Москве)
        def hm(r):
            t = r["done_at"] or ""
            return t[11:16] if len(t) >= 16 else ""

        # Феникс: засчитанный день после 7+ дней без единого выполненного квеста
        active = sorted(d for d, x in s.items() if x["done"] > 0)
        phoenix = any(
            self._complete(s[b]) and (date.fromisoformat(b) - date.fromisoformat(a)).days >= 8
            for a, b in zip(active, active[1:]))

        fails_by_day: dict[str, int] = {}
        for r in rows:
            if r["status"] == "failed":
                fails_by_day[r["day"]] = fails_by_day.get(r["day"], 0) + 1

        got = {
            "first": bool(done_rows), "lvl5": lvl >= 5, "lvl10": lvl >= 10, "lvl25": lvl >= 25,
            "streak3": best_streak >= 3, "streak7": best_streak >= 7, "streak30": best_streak >= 30,
            "day1000": any(x["xp"] >= 1000 for x in s.values()),
            "ultra": any(r["xp"] > rules.CATEGORIES[r["category"]].xp_max for r in done_rows),
            "perfect": any(x["total"] >= 4 and x["done"] == x["total"] for x in s.values()),
            "sleep7": cnt["sleep"] >= 7,
            "allcats": main_cats <= cats_done, "shopper": bought,
            "gutv20": cnt["gutv"] >= 20, "work10": cnt["work"] >= 10, "study50": cnt["study"] >= 50,
            "code30": cnt["code"] >= 30, "sleep30": cnt["sleep"] >= 30,
            "blitz": any(x["done"] >= 5 for x in s.values()),
            "strike": best_run >= 10, "perfect7": p_best >= 7,
            "piggy": st.coins >= 2000, "spender": spent >= 1000,
            "architect": n_templates >= 10, "xp10k": st.total_xp >= 10_000,
            "night": any("02:00" <= hm(r) < "05:00" for r in done_rows),
            "early": any("05:00" <= hm(r) < "07:00" for r in done_rows),
            "lastmin": any(rules.CATEGORIES[r["category"]].is_main and hm(r) >= "23:30"
                           and (r["done_at"] or "")[:10] == r["day"] for r in done_rows),
            "jackpot": any(x["xp"] == 777 for x in s.values()),
            "phoenix": phoenix,
            "oops": any(v >= 3 for v in fails_by_day.values()),
            "undo": int(self.get_setting("undo_count", "0")) >= 10,
            "zero": bought and st.coins == 0,
            "fri13": any(date.fromisoformat(r["day"]).day == 13 and date.fromisoformat(r["day"]).weekday() == 4
                         for r in done_rows),
            "newyear": any(r["day"][5:] == "01-01" for r in done_rows),
            "word10": ps["kept"] >= 10, "fastword": ps["fast"] >= 5,
            "cleanslate": ps["kept"] >= 5 and ps["open"] == 0,
            "knight": ps["kept"] >= 50,
        }

        # Открытое достижение остаётся открытым навсегда
        unlocked = {r["key"]: r["unlocked_at"] for r in self.conn.execute("SELECT * FROM achievements")}
        now = datetime.now(self.tz).replace(tzinfo=None).isoformat(timespec="seconds")
        fresh = [k for k, ok in got.items() if ok and k not in unlocked]
        for k in fresh:
            self.conn.execute("INSERT OR IGNORE INTO achievements (key, unlocked_at) VALUES (?, ?)", (k, now))
            unlocked[k] = now
        if fresh:
            self.conn.commit()

        out = []
        for k, e, t, d, secret in ACHIEVEMENTS:
            done = k in unlocked
            if secret and not done:
                e, t, d = "🔒", "???", "Секретное достижение"
            out.append({"key": k, "emoji": e, "title": t, "desc": d, "done": done,
                        "secret": secret, "unlocked_at": unlocked.get(k)})
        return out

    # ================= Настройки =================

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()
