"""📊 Статистика как в меню GTA: «Часов на таймере: 83», «Пар отсижено: 214» — всё, что уже накопилось."""

from datetime import date


def _h(minutes: int) -> str:
    return f"{minutes // 60} ч {minutes % 60:02d} мин" if minutes >= 60 else f"{minutes} мин"


class FunStats:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    def q(self, sql: str, *a):
        return self.conn.execute(sql, a).fetchone()[0] or 0

    def all(self, today: date) -> list[dict]:
        q, t = self.q, today.isoformat()
        first = self.conn.execute("SELECT MIN(day) FROM quests").fetchone()[0]
        days_in = (today - date.fromisoformat(first)).days + 1 if first else 0
        s = self.g.full_stats(today)
        best_week = self.conn.execute(
            "SELECT strftime('%Y-%W', day) w, SUM(xp) x FROM quests WHERE status='done' GROUP BY w ORDER BY x DESC LIMIT 1"
        ).fetchone()
        saved = q("SELECT COALESCE(SUM(lim - spent), 0) FROM fin_day_limit WHERE spent IS NOT NULL AND lim > 0 AND spent <= lim")
        pairs = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM((CAST(substr(end,1,2) AS INT)*60 + CAST(substr(end,4,2) AS INT)) - "
            "(CAST(substr(start,1,2) AS INT)*60 + CAST(substr(start,4,2) AS INT))), 0) FROM sched_events "
            "WHERE status='ok' AND allday=0 AND day < ?", (t,)).fetchone()
        kept, prom_all = q("SELECT COUNT(*) FROM promises WHERE status='kept'"), q("SELECT COUNT(*) FROM promises WHERE status != 'open'")
        groups = [
            ("🎮 Игра", [
                ("Дней в игре", days_in, f"с {first[8:10]}.{first[5:7]}.{first[:4]}" if first else ""),
                ("Квестов выполнено", q("SELECT COUNT(*) FROM quests WHERE status='done'"), ""),
                ("Квестов провалено", q("SELECT COUNT(*) FROM quests WHERE status='failed'"), "бывает"),
                ("Всего XP", s["total_xp"], ""),
                ("Лучший день", s["best_day_xp"], "XP"),
                ("Лучшая неделя", best_week["x"] if best_week else 0, "XP"),
                ("Самая длинная серия", s["best_streak"], "дней"),
                ("Достижений открыто", sum(1 for a in s["achievements"] if a["done"]), f"из {len(s['achievements'])}"),
            ]),
            ("⏱ Время", [
                ("На таймере", _h(q("SELECT COALESCE(SUM(timer_sec), 0) FROM quests") // 60), ""),
                ("Пар отсижено", pairs[0], _h(pairs[1]) + " в вузе" if pairs[1] else ""),
                ("Отбоев вовремя", q("SELECT COUNT(*) FROM sleep_log WHERE ontime=1"), ""),
                ("Самый поздний отбой", self._latest(), ""),
            ]),
            ("🗃 Дела", [
                ("Задач из банка", q("SELECT COUNT(*) FROM bank_tasks WHERE status='done'"), ""),
                ("Боссов побеждено", q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND difficulty=4"), "💀"),
                ("Сдано работ на парах", q("SELECT COUNT(*) FROM sched_marks m JOIN quests qq ON qq.id=m.quest_id WHERE qq.status='done'"), ""),
                ("Пятёрок", q("SELECT COUNT(*) FROM sched_marks WHERE grade='5'"), ""),
                ("Сюжетных миссий", q("SELECT COUNT(*) FROM story_missions WHERE status='done'"), f"этапов {q('SELECT COUNT(*) FROM story_steps WHERE done_day IS NOT NULL')}"),
                ("Побочек выполнено", q("SELECT COUNT(*) FROM side_offers o JOIN quests qq ON qq.id=o.quest_id WHERE qq.status='done'"), ""),
                ("Привычек отмечено", q("SELECT COUNT(*) FROM habit_log"), ""),
            ]),
            ("❤️ Люди", [
                ("Обещаний сдержано", kept, f"{round(100 * kept / prom_all)}% от закрытых" if prom_all else ""),
            ]),
            ("💰 Деньги", [
                ("Дней в лимите", q("SELECT COUNT(*) FROM fin_day_limit WHERE spent IS NOT NULL AND lim > 0 AND spent <= lim"), ""),
                ("Сэкономлено в лимите", f"{saved // 100:,} ₽".replace(",", " "), "сколько не потратил из разрешённого"),
                ("Смен отработано", q("SELECT COUNT(*) FROM shifts"), ""),
                ("Монет потрачено в магазине", q("SELECT COALESCE(SUM(cost), 0) FROM purchases"), f"наград {q('SELECT COUNT(*) FROM purchases')}"),
                ("Фондов набрано к сроку", self.g.env.ob.counts(today)["funds_ontime"], ""),
            ]),
        ]
        return [{"title": t, "items": [{"label": l, "value": v, "sub": sub} for l, v, sub in items]} for t, items in groups]

    def _latest(self) -> str:
        from .sleep import fmt, norm
        rows = [r["at"] for r in self.conn.execute("SELECT at FROM sleep_log")]
        return fmt(max(norm(a) for a in rows)) if rows else "—"
