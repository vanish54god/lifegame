"""
Ритм жизни: привычки (каждый день или N раз в неделю), оценка дня 1–10,
обзор недели, сезоны (итоги месяца) и календарь.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta

from . import rules


class LifeError(Exception):
    """Ошибка, которую можно показать как есть."""


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, monthrange(y, m)[1])


MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
          "сентябрь", "октябрь", "ноябрь", "декабрь"]


class Life:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ================= Привычки =================

    def add_habit(self, title: str, today: date, emoji: str = "🔁", per_week: int = 7, xp: int = 20) -> dict:
        title = title.strip()
        if not title:
            raise LifeError("Назови привычку")
        if not 1 <= per_week <= 7:
            raise LifeError("Раз в неделю: от 1 до 7")
        if not 0 <= xp <= 200:
            raise LifeError("XP за отметку: 0–200")
        cur = self.conn.execute("INSERT INTO habits (title, emoji, per_week, xp, created_day) VALUES (?, ?, ?, ?, ?)",
                                (title[:60], (emoji or "🔁")[:4], per_week, xp, today.isoformat()))
        self.conn.commit()
        return self.habit(cur.lastrowid, today)

    def edit_habit(self, hid: int, today: date, **f) -> dict:
        self.habit(hid, today)
        upd = {k: v for k, v in f.items() if k in ("title", "emoji", "per_week", "xp") and v is not None}
        if "per_week" in upd and not 1 <= upd["per_week"] <= 7:
            raise LifeError("Раз в неделю: от 1 до 7")
        if upd:
            self.conn.execute(f"UPDATE habits SET {', '.join(f'{k} = ?' for k in upd)} WHERE id = ?", (*upd.values(), hid))
            self.conn.commit()
        return self.habit(hid, today)

    def archive_habit(self, hid: int, today: date) -> None:
        self.habit(hid, today)
        self.conn.execute("UPDATE habits SET archived = 1 WHERE id = ?", (hid,))
        self.conn.commit()

    def _days(self, hid: int) -> set[str]:
        return {r["day"] for r in self.conn.execute("SELECT day FROM habit_log WHERE habit_id = ?", (hid,))}

    def _streak(self, h: dict, days: set[str], today: date) -> tuple[int, int]:
        """(текущая серия, лучшая). Для ежедневных — в днях, для «N раз в неделю» — в неделях."""
        if not days:
            return 0, 0
        first = date.fromisoformat(min(days))
        if h["per_week"] >= 7:
            ok = lambda d: d.isoformat() in days
            cur, d = 0, today if ok(today) else today - timedelta(days=1)
            while ok(d):
                cur, d = cur + 1, d - timedelta(days=1)
            best = run = 0
            d = first
            while d <= today:
                run = run + 1 if ok(d) else 0
                best = max(best, run)
                d += timedelta(days=1)
            return cur, max(best, cur)
        def week_ok(m: date) -> bool:
            return sum(1 for i in range(7) if (m + timedelta(days=i)).isoformat() in days) >= h["per_week"]
        this = monday(today)
        cur, w = 0, this if week_ok(this) else this - timedelta(days=7)
        while week_ok(w):
            cur, w = cur + 1, w - timedelta(days=7)
        best = run = 0
        w = monday(first)
        while w <= this:
            run = run + 1 if week_ok(w) else (run if w == this else 0)
            best = max(best, run)
            w += timedelta(days=7)
        return cur, max(best, cur)

    def habit(self, hid: int, today: date) -> dict:
        row = self.conn.execute("SELECT * FROM habits WHERE id = ?", (hid,)).fetchone()
        if row is None:
            raise LifeError("Такой привычки нет")
        h = dict(row)
        days = self._days(hid)
        h["done_today"] = today.isoformat() in days
        m = monday(today)
        h["week_count"] = sum(1 for i in range(7) if (m + timedelta(days=i)).isoformat() in days)
        h["streak"], h["best"] = self._streak(h, days, today)
        h["unit"] = "дн" if h["per_week"] >= 7 else "нед"
        h["goal_label"] = "каждый день" if h["per_week"] >= 7 else f"{h['per_week']}× в неделю"
        h["week_done"] = h["week_count"] >= h["per_week"] if h["per_week"] < 7 else h["done_today"]
        return h

    def habits(self, today: date) -> list[dict]:
        return [self.habit(r["id"], today) for r in self.conn.execute(
            "SELECT id FROM habits WHERE archived = 0 ORDER BY per_week DESC, id")]

    def toggle_habit(self, hid: int, day: date, today: date) -> dict:
        """Отметить / снять отметку. Отметка даёт XP (через квест категории «Привычка»)."""
        h = self.habit(hid, today)
        if day > today:
            raise LifeError("Нельзя отметить будущий день")
        if (today - day).days > 1:
            raise LifeError("Отмечать можно только сегодня и вчера")
        before = self.g._achieved(today)
        lvl_before = self.g.stats().level.level
        row = self.conn.execute("SELECT quest_id FROM habit_log WHERE habit_id = ? AND day = ?",
                                (hid, day.isoformat())).fetchone()
        if row:
            if row["quest_id"]:
                self.conn.execute("DELETE FROM quests WHERE id = ?", (row["quest_id"],))
            self.conn.execute("DELETE FROM habit_log WHERE habit_id = ? AND day = ?", (hid, day.isoformat()))
            done = False
        else:
            qid = None
            if h["xp"]:
                now = datetime.now(self.g.tz).replace(tzinfo=None).isoformat(timespec="seconds")
                qid = self.conn.execute(
                    "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'habit', ?, ?, 'done', ?)",
                    (day.isoformat(), f"{h['emoji']} {h['title']}", h["xp"], now)).lastrowid
            self.conn.execute("INSERT INTO habit_log (habit_id, day, quest_id) VALUES (?, ?, ?)",
                              (hid, day.isoformat(), qid))
            done = True
        self.conn.commit()
        new = [a for a in self.g.full_stats(today)["achievements"] if a["done"] and a["key"] not in before]
        return {"habit": self.habit(hid, today), "done": done, "level_before": lvl_before,
                "level_after": self.g.stats().level.level, "new_achievements": new}

    def best_habit_streaks(self, today: date) -> tuple[int, int]:
        """(лучшая серия в днях по ежедневным, лучшая в неделях по недельным) — для достижений."""
        d = w = 0
        for r in self.conn.execute("SELECT * FROM habits"):
            h = dict(r)
            _, best = self._streak(h, self._days(h["id"]), today)
            if h["per_week"] >= 7:
                d = max(d, best)
            else:
                w = max(w, best)
        return d, w

    # ================= Оценка дня =================

    def rate(self, day: date, score: int | None, today: date) -> dict:
        if day > today:
            raise LifeError("Нельзя оценить будущий день")
        if score is None:
            self.conn.execute("DELETE FROM day_rating WHERE day = ?", (day.isoformat(),))
        else:
            if not 1 <= score <= 10:
                raise LifeError("Оценка от 1 до 10")
            self.conn.execute("INSERT INTO day_rating (day, score) VALUES (?, ?) "
                              "ON CONFLICT(day) DO UPDATE SET score = excluded.score", (day.isoformat(), score))
        self.conn.commit()
        return {"day": day.isoformat(), "score": score}

    def rating(self, day: date) -> int | None:
        row = self.conn.execute("SELECT score FROM day_rating WHERE day = ?", (day.isoformat(),)).fetchone()
        return row["score"] if row else None

    def rating_stats(self, today: date, days: int = 30) -> dict:
        start = (today - timedelta(days=days - 1)).isoformat()
        rows = self.conn.execute("SELECT day, score FROM day_rating WHERE day >= ?", (start,)).fetchall()
        xp_by_day = {r["day"]: r["s"] for r in self.conn.execute(
            "SELECT day, SUM(xp) s FROM quests WHERE status='done' AND day >= ? GROUP BY day", (start,))}
        good = [xp_by_day.get(r["day"], 0) for r in rows if r["score"] >= 7]
        bad = [xp_by_day.get(r["day"], 0) for r in rows if r["score"] <= 4]
        avg = lambda xs: round(sum(xs) / len(xs)) if xs else None
        return {"count": len(rows), "avg": round(sum(r["score"] for r in rows) / len(rows), 1) if rows else None,
                "xp_good": avg(good), "xp_bad": avg(bad), "n_good": len(good), "n_bad": len(bad),
                "total": self.conn.execute("SELECT COUNT(*) FROM day_rating").fetchone()[0]}

    # ================= Период: неделя, сезон =================

    def period(self, start: date, end: date) -> dict:
        s, e = start.isoformat(), end.isoformat()
        q1 = lambda sql, *a: self.conn.execute(sql, (s, e, *a)).fetchone()[0]
        xp = q1("SELECT COALESCE(SUM(xp),0) FROM quests WHERE status='done' AND day BETWEEN ? AND ?")
        done = q1("SELECT COUNT(*) FROM quests WHERE status='done' AND category NOT IN ('habit','promise') "
                  "AND day BETWEEN ? AND ?")
        total = q1("SELECT COUNT(*) FROM quests WHERE category NOT IN ('habit','promise') AND day BETWEEN ? AND ?")
        active = q1("SELECT COUNT(DISTINCT day) FROM quests WHERE status='done' AND day BETWEEN ? AND ?")
        top = self.conn.execute("""SELECT category, SUM(xp) s FROM quests WHERE status='done' AND day BETWEEN ? AND ?
            GROUP BY category ORDER BY s DESC LIMIT 1""", (s, e)).fetchone()
        fin = self.g.fin.period_totals(start, end)
        shifts = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM shifts WHERE day BETWEEN ? AND ?",
                                   (s, e)).fetchone()
        rating = self.conn.execute("SELECT AVG(score), COUNT(*) FROM day_rating WHERE day BETWEEN ? AND ?",
                                   (s, e)).fetchone()
        summary = self.g._days_summary()
        perfect = sum(1 for d, x in summary.items() if s <= d <= e and x["total"] >= 1 and x["done"] == x["total"]
                      and x["main_total"] > 0)
        run = best = 0
        d = start
        while d <= end:
            run = run + 1 if self.g._complete(summary.get(d.isoformat())) else 0
            best = max(best, run)
            d += timedelta(days=1)
        ach = [dict(r) for r in self.conn.execute(
            "SELECT key, unlocked_at FROM achievements WHERE substr(unlocked_at,1,10) BETWEEN ? AND ?", (s, e))]
        return {
            "start": s, "end": e, "xp": xp, "quests_done": done, "quests_total": total,
            "rate": round(100 * done / total) if total else None, "active_days": active,
            "top_category": dict(key=top["category"], title=rules.CATEGORIES[top["category"]].title,
                                 emoji=rules.CATEGORIES[top["category"]].emoji, xp=top["s"]) if top else None,
            "perfect_days": perfect, "best_streak": best,
            "promises_kept": q1("SELECT COUNT(*) FROM promises WHERE status='kept' AND closed_day BETWEEN ? AND ?"),
            "bank_done": q1("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND done_day BETWEEN ? AND ?"),
            "bosses": q1("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND difficulty=4 AND done_day BETWEEN ? AND ?"),
            "habit_checks": q1("SELECT COUNT(*) FROM habit_log WHERE day BETWEEN ? AND ?"),
            "income": fin["income"], "expense": fin["expense"],
            "shifts": shifts[0], "shifts_sum": shifts[1],
            "rating_avg": round(rating[0], 1) if rating[0] else None, "rated_days": rating[1],
            "achievements": [a["key"] for a in ach],
        }

    def week_review(self, today: date) -> dict:
        m = monday(today)
        return {"this": self.period(m, today), "last": self.period(m - timedelta(days=7), m - timedelta(days=1)),
                "week_start": m.isoformat()}

    def season(self, month: str) -> dict:
        start, end = month_bounds(month)
        p = self.period(start, end)
        names = {k: (e, t) for k, e, t, _, _ in self._ach_list()}
        p["achievements"] = [{"key": k, "emoji": names[k][0], "title": names[k][1]} for k in p["achievements"] if k in names]
        y, mm = map(int, month.split("-"))
        p["month"] = month
        p["title"] = f"Сезон: {MONTHS[mm - 1]} {y}"
        return p

    def _ach_list(self):
        from .game import ACHIEVEMENTS
        return ACHIEVEMENTS

    def seasons_played(self, today: date) -> int:
        """Сколько прошедших месяцев с 20+ активными днями."""
        rows = self.conn.execute("""SELECT substr(day,1,7) m, COUNT(DISTINCT day) n FROM quests
            WHERE status='done' AND substr(day,1,7) < ? GROUP BY m""", (today.isoformat()[:7],)).fetchall()
        return sum(1 for r in rows if r["n"] >= 20)

    # ================= Календарь =================

    def calendar(self, month: str, today: date) -> dict:
        start, end = month_bounds(month)
        s, e = start.isoformat(), end.isoformat()
        days: dict[str, dict] = {}
        get = lambda d: days.setdefault(d, {"quests": 0, "done": 0, "xp": 0, "deadlines": [], "shifts": [],
                                             "plans": [], "promises": [], "rating": None, "habits": 0})
        for r in self.conn.execute("""SELECT day, COUNT(*) n, SUM(status='done') d, SUM(CASE WHEN status='done' THEN xp END) x
                FROM quests WHERE day BETWEEN ? AND ? AND category NOT IN ('habit') GROUP BY day""", (s, e)):
            x = get(r["day"]); x.update(quests=r["n"], done=r["d"] or 0, xp=r["x"] or 0)
        for t in self.g.planner.tasks(today):
            for item in [dict(c, parent_title=t["title"]) for c in t["children"] if c["status"] == "open"] or [t]:
                if item["deadline"] and s <= item["deadline"] <= e:
                    get(item["deadline"])["deadlines"].append({"id": item["id"], "title": item["title"],
                                                               "heat": item["heat"], "parent": item.get("parent_title")})
        for r in self.conn.execute("SELECT day, company, work_type, amount, paid FROM shifts WHERE day BETWEEN ? AND ?", (s, e)):
            get(r["day"])["shifts"].append(dict(r))
        for p in self.g.fin.plans(today):
            if s <= p["due"] <= e:
                get(p["due"])["plans"].append({"title": p["title"], "amount": p["amount"]})
        for r in self.conn.execute("SELECT text, due FROM promises WHERE status='open' AND due BETWEEN ? AND ?", (s, e)):
            get(r["due"])["promises"].append(r["text"])
        for r in self.conn.execute("SELECT day, score FROM day_rating WHERE day BETWEEN ? AND ?", (s, e)):
            get(r["day"])["rating"] = r["score"]
        for r in self.conn.execute("SELECT day, COUNT(*) n FROM habit_log WHERE day BETWEEN ? AND ? GROUP BY day", (s, e)):
            get(r["day"])["habits"] = r["n"]
        return {"month": month, "start": s, "end": e, "today": today.isoformat(), "days": days}
