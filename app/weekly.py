"""
📰 Брифинг недели (понедельник) и 🏁 «Неделя пройдена» (воскресенье вечером) — как экран загрузки и финал миссии.
Собирает в одну картину всё: пары, контрольные, платежи, фонды, дедлайны банка, обещания, сюжет, навыки.
"""

from datetime import date, timedelta

from .life import monday

WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]


def span_title(m: date) -> str:
    s = m + timedelta(days=6)
    if m.month == s.month:
        return f"{m.day}–{s.day} {MONTHS_GEN[s.month - 1]}"
    return f"{m.day} {MONTHS_GEN[m.month - 1]} – {s.day} {MONTHS_GEN[s.month - 1]}"


class Weekly:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ---------- 📰 брифинг ----------

    def brief(self, today: date) -> dict:
        g = self.g
        m = monday(today)
        sun = m + timedelta(days=6)
        days = [m + timedelta(days=i) for i in range(7)]
        pairs = [(d, g.schedule.pairs(d)) for d in days if d >= today]
        pair_days = [(d, ps) for d, ps in pairs if ps]
        marks = [x for x in g.study.upcoming(today, 7) if x["day"] <= sun.isoformat()]
        pays, funds = [], []
        if g.env.on:
            for i in g.env.obligations(today)["items"]:
                if i["kind"] == "plan" and i["due"] <= sun.isoformat():
                    pays.append(i)
                elif i["kind"] == "fund" and 0 <= i["days_left"] <= 21:
                    funds.append(i)
        else:
            pays = [dict(p, status="") for p in g.fin.plans(today) if p["due"] <= sun.isoformat()]
        bank = []
        for t in g.planner.tasks(today):
            for x in [c for c in t["children"] if c["status"] == "open"] or [t]:
                if x["deadline"] and x["deadline"] <= sun.isoformat():
                    bank.append({"title": x["title"], "deadline": x["deadline"], "heat": x["heat"]})
        bank.sort(key=lambda x: x["deadline"])
        promises = self.conn.execute("SELECT COUNT(*) FROM promises WHERE status='open'").fetchone()[0]
        story = [{"title": s["title"], "emoji": s["emoji"], "next": s["next_step"]["title"] if s["next_step"] else None}
                 for s in g.story.missions("active")]
        load = len(marks) * 2 + len(bank) + sum(1 for p in pays if p.get("status") == "late")
        mood = ("🔥 Горячая неделя" if load >= 5 else "⚡ Рабочая неделя" if load >= 2 else "🌤 Спокойная неделя")
        return {
            "week": m.isocalendar()[1], "start": m.isoformat(), "end": sun.isoformat(), "span": span_title(m),
            "mood": mood, "pairs_total": sum(len(ps) for _, ps in pair_days),
            "pair_days": [{"day": d.isoformat(), "wd": WD[d.weekday()], "n": len(ps), "first": ps[0]["start"],
                           "last": ps[-1]["end"]} for d, ps in pair_days],
            "marks": marks, "payments": pays, "funds": funds, "bank": bank[:6], "bank_more": max(0, len(bank) - 6),
            "promises_open": promises, "story": story,
        }

    # ---------- 🏁 итоги ----------

    def recap(self, today: date, last: bool = False) -> dict:
        """Итоги текущей недели (или прошлой — last=True)."""
        g = self.g
        m = monday(today) - (timedelta(days=7) if last else timedelta(0))
        end = min(today, m + timedelta(days=6)) if not last else m + timedelta(days=6)
        cur = g.life.period(m, end)
        prev = g.life.period(m - timedelta(days=7), m - timedelta(days=1))
        s, e = m.isoformat(), end.isoformat()
        q = lambda sql: self.conn.execute(sql, (s, e)).fetchone()[0]
        lim_days = q("SELECT COUNT(*) FROM fin_day_limit WHERE day BETWEEN ? AND ? AND spent IS NOT NULL "
                     "AND lim > 0 AND spent <= lim")
        lim_total = q("SELECT COUNT(*) FROM fin_day_limit WHERE day BETWEEN ? AND ? AND spent IS NOT NULL AND lim > 0")
        steps = q("SELECT COUNT(*) FROM story_steps WHERE done_day BETWEEN ? AND ?")
        missions = [dict(r) for r in self.conn.execute(
            "SELECT title, emoji, outro FROM story_missions WHERE status='done' AND done_day BETWEEN ? AND ?", (s, e))]
        marks = q("SELECT COUNT(*) FROM sched_marks mk JOIN quests qq ON qq.id = mk.quest_id "
                  "WHERE mk.status='active' AND qq.status='done' AND mk.day BETWEEN ? AND ?")
        best = self.conn.execute("SELECT day, SUM(xp) x FROM quests WHERE status='done' AND day BETWEEN ? AND ? "
                                 "GROUP BY day ORDER BY x DESC LIMIT 1", (s, e)).fetchone()
        skills = sorted((k for k in g.skills.all(today) if k["week_xp"]), key=lambda k: -k["week_xp"])[:3]
        delta = round(100 * (cur["xp"] - prev["xp"]) / prev["xp"]) if prev["xp"] else None
        verdict = ("Лучше прошлой" if delta is not None and delta > 5 else
                   "Хуже прошлой — бывает" if delta is not None and delta < -5 else "Ровно, как прошлая")
        if not prev["xp"]:
            verdict = "Первая неделя в игре" if cur["xp"] else "Тихая неделя"
        return {
            "week": m.isocalendar()[1], "start": s, "end": e, "span": span_title(m), "xp": cur["xp"],
            "xp_prev": prev["xp"], "delta": delta, "verdict": verdict, "quests_done": cur["quests_done"],
            "active_days": cur["active_days"], "perfect_days": cur["perfect_days"],
            "best_day": {"day": best["day"], "wd": WD[date.fromisoformat(best["day"]).weekday()], "xp": best["x"]} if best else None,
            "promises_kept": cur["promises_kept"], "bank_done": cur["bank_done"], "habit_checks": cur["habit_checks"],
            "limit_days": lim_days, "limit_total": lim_total, "steps": steps, "missions": missions, "marks_done": marks,
            "skills": [{"emoji": k["emoji"], "title": k["title"], "week_xp": k["week_xp"], "level": k["level"]} for k in skills],
            "rating_avg": cur["rating_avg"], "achievements": len(cur["achievements"]),
        }
