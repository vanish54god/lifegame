"""
Игровая логика. Бот и веб-приложение зовут только эти функции,
поэтому правила работают одинаково везде.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from . import rules


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


# Достижения: (ключ, эмодзи, название, описание)
ACHIEVEMENTS = [
    ("first", "🩸", "Первая кровь", "Выполни первый квест"),
    ("lvl5", "⭐", "Уже не новичок", "Дойди до 5 уровня"),
    ("lvl10", "🌟", "Свой человек", "Дойди до 10 уровня"),
    ("lvl25", "👑", "Хозяин района", "Дойди до 25 уровня"),
    ("streak3", "🔥", "Разогрев", "Серия 3 дня"),
    ("streak7", "🔥", "Неделя без промахов", "Серия 7 дней"),
    ("streak30", "☄️", "Машина", "Серия 30 дней"),
    ("day1000", "💥", "Тысячник", "1000 XP за один день"),
    ("ultra", "🧨", "Ультра хард", "Выполни квест с XP выше обычного"),
    ("perfect", "💯", "Идеальный день", "Выполни все квесты дня (минимум 4)"),
    ("sleep7", "😴", "Режим", "7 раз вовремя лечь"),
    ("allcats", "🎯", "Многостаночник", "Выполни квесты во всех основных категориях"),
    ("shopper", "🛍", "Заслужил", "Первая покупка в магазине"),
]


class Game:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
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
        self.get(quest_id)  # проверка, что квест существует
        before = self.stats().level.level
        done_at = datetime.now().isoformat(timespec="seconds") if status == "done" else None
        self.conn.execute("UPDATE quests SET status = ?, done_at = ? WHERE id = ?",
                          (status, done_at, quest_id))
        self.conn.commit()
        after = self.stats().level.level
        return self.get(quest_id), before, after

    def mark(self, quest_id: int, status: str, today: date) -> dict:
        """То же, что set_status, но ещё сообщает про новые достижения."""
        before = self._achieved(today)
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
        done_rows = self.conn.execute(
            "SELECT category, xp FROM quests WHERE status='done'").fetchall()
        cats_done = {r["category"] for r in done_rows}
        sleep_done = sum(1 for r in done_rows if r["category"] == "sleep")
        ultra = any(r["xp"] > rules.CATEGORIES[r["category"]].xp_max for r in done_rows)
        perfect = any(x["total"] >= 4 and x["done"] == x["total"] for x in s.values())
        bought = self.conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] > 0
        main_cats = {k for k, c in rules.CATEGORIES.items() if c.is_main}
        lvl = st.level.level
        got = {
            "first": bool(done_rows), "lvl5": lvl >= 5, "lvl10": lvl >= 10, "lvl25": lvl >= 25,
            "streak3": best_streak >= 3, "streak7": best_streak >= 7, "streak30": best_streak >= 30,
            "day1000": any(x["xp"] >= 1000 for x in s.values()), "ultra": ultra,
            "perfect": perfect, "sleep7": sleep_done >= 7,
            "allcats": main_cats <= cats_done, "shopper": bought,
        }
        return [{"key": k, "emoji": e, "title": t, "desc": d, "done": got[k]}
                for k, e, t, d in ACHIEVEMENTS]

    # ================= Настройки =================

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()
