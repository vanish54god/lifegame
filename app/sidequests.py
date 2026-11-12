"""
🎲 Побочки — как уличные события в GTA. Ты сам наполняешь пул маленьких приятных дел,
а бот пару раз в неделю, в случайный день и час, предлагает одно: «возьмёшь сегодня?».
Взял — бонусный квест на сегодня. Пропустил — ничего страшного.
"""

import hashlib
import random
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS side_pool (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title   TEXT    NOT NULL,
    xp      INTEGER NOT NULL DEFAULT 50,
    active  INTEGER NOT NULL DEFAULT 1,
    created TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS side_offers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    day      TEXT    NOT NULL,
    pool_id  INTEGER NOT NULL,
    status   TEXT    NOT NULL DEFAULT 'offered',   -- offered / taken / skipped
    quest_id INTEGER
);
"""
PER_WEEK = 2
HOURS = (12, 19)          # в какое время дня может прилететь


class SideError(Exception):
    pass


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class SideQuests:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ---------- пул ----------

    def add(self, title: str, xp: int = 50) -> dict:
        title = title.strip()
        if not title:
            raise SideError("Что за побочка?")
        if not 10 <= xp <= 300:
            raise SideError("XP за побочку — от 10 до 300")
        cur = self.conn.execute("INSERT INTO side_pool (title, xp) VALUES (?, ?)", (title[:120], xp))
        self.conn.commit()
        return self.item(cur.lastrowid)

    def item(self, pid: int) -> dict:
        r = self.conn.execute("SELECT * FROM side_pool WHERE id = ?", (pid,)).fetchone()
        if r is None:
            raise SideError("Такой побочки нет")
        d = dict(r)
        d["done"] = self.conn.execute("SELECT COUNT(*) FROM side_offers o JOIN quests q ON q.id=o.quest_id "
                                      "WHERE o.pool_id=? AND q.status='done'", (pid,)).fetchone()[0]
        return d

    def pool(self) -> list[dict]:
        return [self.item(r["id"]) for r in self.conn.execute("SELECT id FROM side_pool WHERE active=1 ORDER BY id")]

    def remove(self, pid: int) -> None:
        self.item(pid)
        self.conn.execute("UPDATE side_pool SET active = 0 WHERE id = ?", (pid,))
        self.conn.commit()

    # ---------- предложения ----------

    def offer_today(self, day: date) -> dict | None:
        r = self.conn.execute("SELECT * FROM side_offers WHERE day = ? ORDER BY id DESC LIMIT 1",
                              (day.isoformat(),)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["item"] = self.item(d["pool_id"])
        return d

    def _week_offers(self, day: date) -> int:
        m = day - timedelta(days=day.weekday())
        return self.conn.execute("SELECT COUNT(*) FROM side_offers WHERE day BETWEEN ? AND ?",
                                 (m.isoformat(), day.isoformat())).fetchone()[0]

    def slot(self, day: date) -> tuple[bool, str]:
        """Будет ли сегодня побочка и во сколько — заранее, но непредсказуемо (зерно — дата)."""
        rnd = random.Random(_seed("side", day.isoformat(), self.g.get_setting("side_salt", "lg")))
        hm = f"{rnd.randint(HOURS[0], HOURS[1] - 1):02d}:{rnd.randint(0, 59):02d}"
        left_days = 7 - day.weekday()
        need = PER_WEEK - self._week_offers(day)
        return need > 0 and rnd.random() < need / left_days, hm

    def pick(self, day: date) -> dict | None:
        items = self.pool()
        if not items:
            return None
        last = {r["pool_id"]: r["d"] for r in self.conn.execute(
            "SELECT pool_id, MAX(day) d FROM side_offers GROUP BY pool_id")}
        items.sort(key=lambda i: (last.get(i["id"], ""), _seed(day.isoformat(), i["id"])))
        fresh = items[:max(1, len(items) // 2)]       # из давно не предлагавшихся — случайно
        return random.Random(_seed("pick", day.isoformat())).choice(fresh)

    def maybe_offer(self, day: date, now: datetime) -> dict | None:
        """Вызывается раз в минуту из напоминаний: если сегодня день побочки и время пришло — предложить."""
        if self.offer_today(day) is not None:
            return None
        ok, hm = self.slot(day)
        if not ok or now.strftime("%H:%M") < hm:
            return None
        return self.offer(day)

    def offer(self, day: date) -> dict | None:
        """Предложить побочку прямо сейчас (и по кнопке «🎲 Дай побочку»)."""
        cur = self.offer_today(day)
        if cur and cur["status"] == "offered":
            return cur
        it = self.pick(day)
        if it is None:
            return None
        self.conn.execute("INSERT INTO side_offers (day, pool_id) VALUES (?, ?)", (day.isoformat(), it["id"]))
        self.conn.commit()
        return self.offer_today(day)

    def answer(self, oid: int, take: bool, day: date) -> dict:
        r = self.conn.execute("SELECT * FROM side_offers WHERE id = ?", (oid,)).fetchone()
        if r is None:
            raise SideError("Предложение не найдено")
        if r["status"] != "offered":
            raise SideError("Уже ответил")
        it = self.item(r["pool_id"])
        qid = None
        if take:
            cur = self.conn.execute("INSERT INTO quests (day, category, title, xp) VALUES (?, 'bonus', ?, ?)",
                                    (day.isoformat(), f"🎲 {it['title']}"[:200], it["xp"]))
            qid = cur.lastrowid
        self.conn.execute("UPDATE side_offers SET status = ?, quest_id = ? WHERE id = ?",
                          ("taken" if take else "skipped", qid, oid))
        self.conn.commit()
        return {**self.offer_today(date.fromisoformat(r["day"])), "quest_id": qid}

    def counts(self) -> dict:
        return {"side_done": self.conn.execute(
            "SELECT COUNT(*) FROM side_offers o JOIN quests q ON q.id=o.quest_id WHERE q.status='done'").fetchone()[0]}
