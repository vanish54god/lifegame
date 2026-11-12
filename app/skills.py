"""
💪 Навыки персонажа — как в GTA San Andreas. Растут сами из того, что ты уже делаешь.

Каждый навык собирает XP своих категорий. Уровень = √(XP / цена): первые уровни быстро, дальше медленнее.
«Цена» выровнена под то, сколько XP обычно даёт категория: привычка — 10–50 XP, учёба — сотни,
поэтому иначе Интеллект улетал бы в космос, а Выносливость стояла на месте.
"""

import json
import math
import re
from datetime import date, timedelta

SPORT = re.compile(r"спорт|физр|физкульт|физ-ра|зал|трен|бег|пробеж|плав|йог|отжим|присед|футбол|баскет|волейб|велос|растяж|кардио|gym|run|workout",
                   re.I)

#       ключ,      эмодзи, название,          цена уровня
SKILLS = [
    ("mind",   "🧠", "Интеллект",      120),
    ("body",   "🏃", "Выносливость",     8),
    ("craft",  "🎥", "Мастерство",     100),
    ("hack",   "💻", "Хакерство",       60),
    ("hustle", "💼", "Деловая хватка", 120),
    ("charm",  "❤️", "Харизма",         15),
    ("money",  "💰", "Финансы",          8),
    ("will",   "🔥", "Дисциплина",      10),
    ("grit",   "🦁", "Характер",        80),
]
CAT_SKILL = {"study": "mind", "gutv": "craft", "code": "hack", "work": "hustle", "promise": "charm",
             "money": "money", "sleep": "will", "story": "grit"}
SKILL_DESC = {
    "mind": "учёба, контрольные, экзамены", "body": "спортивные привычки", "craft": "ГУТВ, камера, трансляции",
    "hack": "программирование", "hustle": "работа и смены", "charm": "сдержанные обещания",
    "money": "дни в лимите трат", "will": "остальные привычки и сон", "grit": "сюжетные миссии",
}


def skill_of(category: str, title: str) -> str | None:
    if category == "habit":
        return "body" if SPORT.search(title or "") else "will"
    return CAT_SKILL.get(category)


def level_of(xp: int, cost: int) -> tuple[int, int, int]:
    """Уровень, XP с начала уровня, XP до следующего."""
    lvl = int(math.isqrt(max(0, xp) // cost))
    lo, hi = lvl * lvl * cost, (lvl + 1) * (lvl + 1) * cost
    return lvl, xp - lo, hi - lo


class Skills:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    def _xp(self, since: str | None = None) -> dict:
        out = {k: 0 for k, *_ in SKILLS}
        q = "SELECT category, title, SUM(xp) x FROM quests WHERE status='done'"
        args: tuple = ()
        if since:
            q += " AND day >= ?"
            args = (since,)
        for r in self.conn.execute(q + " GROUP BY category, title", args):
            sk = skill_of(r["category"], r["title"])
            if sk:
                out[sk] += r["x"] or 0
        return out

    def all(self, today: date) -> list[dict]:
        xp = self._xp()
        week = self._xp((today - timedelta(days=6)).isoformat())
        out = []
        for k, emoji, title, cost in SKILLS:
            lvl, cur, need = level_of(xp[k], cost)
            out.append({"key": k, "emoji": emoji, "title": title, "desc": SKILL_DESC[k], "xp": xp[k], "level": lvl,
                        "cur": cur, "need": need, "pct": round(100 * cur / need) if need else 0, "week_xp": week[k]})
        return out

    def ups(self, today: date) -> list[dict]:
        """Какие навыки выросли с прошлого раза (для «🧠 Интеллект +1»). Первый вызов — тихий."""
        now = {s["key"]: s["level"] for s in self.all(today)}
        raw = self.g.get_setting("skills_seen", "")
        self.g.set_setting("skills_seen", json.dumps(now))
        if not raw:
            return []
        seen = json.loads(raw)
        return [{**s, "gain": s["level"] - seen.get(s["key"], 0)} for s in self.all(today)
                if s["level"] > seen.get(s["key"], 0)]

    def counts(self, today: date) -> dict:
        sk = self.all(today)
        return {"skill_max": max(s["level"] for s in sk), "skills_5": sum(1 for s in sk if s["level"] >= 5)}
