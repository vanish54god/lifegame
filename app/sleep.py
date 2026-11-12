"""🌙 «Иду спать» — точка в конце дня: отбой вовремя → серия и Дисциплина, и время, во сколько реально ложишься."""

from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS sleep_log (
    day    TEXT PRIMARY KEY,          -- игровой день (после полуночи до 5:00 — всё ещё вчера)
    at     TEXT NOT NULL,             -- HH:MM, когда нажал
    ontime INTEGER NOT NULL,
    quest_id INTEGER
);
"""
XP = 20
GRACE_MIN = 10


def norm(hm: str) -> int:
    """Минуты, где ночь идёт после вечера: 23:30 → 1410, 00:20 → 1460."""
    h, m = map(int, hm.split(":"))
    v = h * 60 + m
    return v + 1440 if h < 12 else v


def fmt(n: int) -> str:
    n %= 1440
    return f"{n // 60:02d}:{n % 60:02d}"


class Sleep:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    @property
    def bedtime(self) -> str:
        return self.g.get_setting("bedtime", "00:00")

    def get(self, day: date) -> dict | None:
        r = self.conn.execute("SELECT * FROM sleep_log WHERE day = ?", (day.isoformat(),)).fetchone()
        return dict(r) if r else None

    def go(self, day: date, now: datetime) -> dict:
        """Нажал «Иду спать». Повторное нажатие в ту же ночь просто обновляет время (XP не дублируется)."""
        hm = f"{now.hour:02d}:{now.minute:02d}"
        ontime = norm(hm) <= norm(self.bedtime) + GRACE_MIN
        old = self.get(day)
        qid = old["quest_id"] if old else None
        if ontime and not qid:
            cur = self.conn.execute(
                "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'habit', '🌙 Отбой вовремя', ?, 'done', ?)",
                (day.isoformat(), XP, now.replace(tzinfo=None).isoformat(timespec="seconds")))
            qid = cur.lastrowid
        elif not ontime and qid:
            self.conn.execute("DELETE FROM quests WHERE id = ?", (qid,))
            qid = None
        self.conn.execute("INSERT INTO sleep_log (day, at, ontime, quest_id) VALUES (?, ?, ?, ?) ON CONFLICT(day) DO "
                          "UPDATE SET at=excluded.at, ontime=excluded.ontime, quest_id=excluded.quest_id",
                          (day.isoformat(), hm, int(ontime), qid))
        self.conn.commit()
        return {**self.stats(day), "at": hm, "ontime": ontime, "xp": XP if ontime else 0}

    def streak(self, day: date) -> int:
        n, d = 0, day
        while True:
            r = self.get(d)
            if not r or not r["ontime"]:
                return n
            n += 1
            d -= timedelta(days=1)

    def stats(self, day: date, days: int = 7) -> dict:
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM sleep_log WHERE day BETWEEN ? AND ? ORDER BY day",
            ((day - timedelta(days=days - 1)).isoformat(), day.isoformat()))]
        avg = fmt(round(sum(norm(r["at"]) for r in rows) / len(rows))) if rows else None
        best = self.conn.execute("SELECT COUNT(*) FROM sleep_log WHERE ontime = 1").fetchone()[0]
        return {"bedtime": self.bedtime, "streak": self.streak(day), "week_ontime": sum(r["ontime"] for r in rows),
                "week_logged": len(rows), "avg": avg, "total_ontime": best, "logged_today": self.get(day) is not None}

    def counts(self, today: date) -> dict:
        late = self.conn.execute("SELECT COUNT(*) FROM sleep_log WHERE at >= '03:00' AND at < '05:00'").fetchone()[0]
        best, run, prev = 0, 0, None
        for r in self.conn.execute("SELECT day, ontime FROM sleep_log ORDER BY day"):
            d = date.fromisoformat(r["day"])
            run = run + 1 if r["ontime"] and prev and (d - prev).days == 1 else (1 if r["ontime"] else 0)
            best, prev = max(best, run), d
        return {"sleep_best": best, "owl": late}
