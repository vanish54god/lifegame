"""
⚡ Важные пары: контрольные, тесты, лабы, зачёты, экзамены — привязаны к конкретной паре из расписания.

  • отметил пару → в её день квест «✍️ Контрольная: Кратные ряды» с XP по типу;
  • за 5 дней до пары в банк сам падает «📖 Подготовиться: …» с дедлайном на эту пару (и начинает «гореть»);
  • пару перенесли — квест и дедлайн переезжают вместе с ней;
  • через неделю бот спросит оценку: «5» — +50% XP, «4» и «зачёт» — +25%.
"""

import re
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS sched_marks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    key       TEXT    NOT NULL,          -- пара в sched_events
    day       TEXT    NOT NULL,
    start     TEXT    NOT NULL,
    subject   TEXT    NOT NULL,
    kind      TEXT    NOT NULL,          -- test / lab / kr / zachet / exam
    xp        INTEGER NOT NULL,
    prep_min  INTEGER NOT NULL,
    quest_id  INTEGER,
    task_id   INTEGER,
    grade     TEXT,
    bonus_xp  INTEGER NOT NULL DEFAULT 0,
    ask_after TEXT,                      -- когда спросить оценку
    status    TEXT    NOT NULL DEFAULT 'active',   -- active / removed
    created   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_marks_key ON sched_marks(key);
"""

#        название, эмодзи, XP, подготовка (мин), сложность в банке
KINDS = {
    "test":   ("Тест", "📝", 160, 60, 1),
    "lab":    ("Лабораторная", "🧪", 200, 120, 2),
    "kr":     ("Контрольная", "✍️", 300, 180, 3),
    "zachet": ("Зачёт", "🎓", 500, 360, 3),
    "exam":   ("Экзамен", "💀", 800, 600, 4),
}
GRADES = {"5": ("Отлично", 0.5), "4": ("Хорошо", 0.25), "pass": ("Зачёт", 0.25), "3": ("Удовл.", 0.0),
          "fail": ("Не сдал", 0.0)}
PREP_DAYS = 5
ASK_AFTER_DAYS = 7

# «711 Кратные ряды (лекция)» → аудитория 711, предмет, тип пары
TITLE_RE = re.compile(r"^\s*(?P<room>\d{2,4}[а-яa-z]?)\s+(?P<subj>.+?)\s*(?:\((?P<type>[^()]+)\))?\s*$", re.I)
TYPE_ALIASES = {"лр": "лаба", "лаб": "лаба", "лабораторная": "лаба", "лабораторная работа": "лаба",
                "пр": "практика", "практ": "практика", "сем": "семинар", "лек": "лекция"}


class StudyError(Exception):
    pass


def parse_title(title: str) -> dict:
    """Разобрать название пары на аудиторию, предмет и тип."""
    m = TITLE_RE.match(title or "")
    if m:
        subj, room, typ = m.group("subj"), m.group("room"), (m.group("type") or "").strip()
    else:
        m2 = re.match(r"^(?P<subj>.+?)\s*\((?P<type>[^()]+)\)\s*$", title or "")
        subj, room, typ = (m2.group("subj"), "", m2.group("type").strip()) if m2 else (title, "", "")
    typ_l = typ.lower()
    return {"subject": subj.strip() or title, "room": room, "ptype": TYPE_ALIASES.get(typ_l, typ_l)}


def suggest_kind(ptype: str) -> str:
    return "lab" if ptype == "лаба" else "kr"


class Study:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ---------- отметки ----------

    def mark(self, key: str, kind: str, today: date) -> dict:
        if kind not in KINDS:
            raise StudyError("Тип: тест / лаба / контрольная / зачёт / экзамен")
        ev = self.conn.execute("SELECT * FROM sched_events WHERE key = ? AND status = 'ok'", (key,)).fetchone()
        if ev is None:
            raise StudyError("Такой пары нет в расписании")
        day = date.fromisoformat(ev["day"])
        if day < today:
            raise StudyError("Эта пара уже прошла")
        old = self.conn.execute("SELECT id FROM sched_marks WHERE key = ? AND status = 'active'", (key,)).fetchone()
        if old:
            self.unmark(old["id"], today)
        name, emoji, xp, prep, _ = KINDS[kind]
        subj = parse_title(ev["title"])["subject"]
        minutes = self._pair_min(ev)
        cur = self.conn.execute(
            "INSERT INTO quests (day, category, title, xp, est_min) VALUES (?, 'study', ?, ?, ?)",
            (ev["day"], f"{emoji} {name}: {subj}"[:200], xp, minutes or None))
        qid = cur.lastrowid
        cur = self.conn.execute(
            "INSERT INTO sched_marks (key, day, start, subject, kind, xp, prep_min, quest_id, ask_after) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, ev["day"], ev["start"], subj[:120], kind, xp, prep, qid,
             (day + timedelta(days=ASK_AFTER_DAYS)).isoformat()))
        self.conn.commit()
        self.tick(today)
        return self.get(cur.lastrowid)

    @staticmethod
    def _pair_min(ev) -> int:
        h1, m1 = map(int, ev["start"].split(":"))
        h2, m2 = map(int, ev["end"].split(":"))
        return max(0, h2 * 60 + m2 - h1 * 60 - m1)

    def get(self, mid: int) -> dict:
        r = self.conn.execute("SELECT * FROM sched_marks WHERE id = ?", (mid,)).fetchone()
        if r is None:
            raise StudyError("Такой отметки нет")
        d = dict(r)
        name, emoji, *_ = KINDS[d["kind"]]
        d["kind_title"], d["emoji"] = name, emoji
        q = self.conn.execute("SELECT status FROM quests WHERE id = ?", (d["quest_id"],)).fetchone() \
            if d["quest_id"] else None
        d["quest_status"] = q["status"] if q else None
        return d

    def unmark(self, mid: int, today: date) -> None:
        m = self.get(mid)
        if m["quest_id"]:
            self.conn.execute("DELETE FROM quests WHERE id = ? AND status = 'todo'", (m["quest_id"],))
        if m["task_id"]:
            t = self.conn.execute("SELECT status FROM bank_tasks WHERE id = ?", (m["task_id"],)).fetchone()
            planned = self.conn.execute("SELECT 1 FROM quests WHERE bank_id = ? AND status = 'todo'",
                                        (m["task_id"],)).fetchone()
            if t and t["status"] == "open" and not planned:
                self.conn.execute("DELETE FROM bank_tasks WHERE id = ?", (m["task_id"],))
        self.conn.execute("UPDATE sched_marks SET status = 'removed' WHERE id = ?", (mid,))
        self.conn.commit()

    def by_key(self) -> dict:
        return {r["key"]: self.get(r["id"]) for r in
                self.conn.execute("SELECT id, key FROM sched_marks WHERE status = 'active'")}

    def upcoming(self, today: date, days: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id FROM sched_marks WHERE status='active' AND day BETWEEN ? AND ? ORDER BY day, start",
            (today.isoformat(), (today + timedelta(days=days)).isoformat()))
        out = []
        for r in rows:
            m = self.get(r["id"])
            m["days_left"] = (date.fromisoformat(m["day"]) - today).days
            out.append(m)
        return out

    # ---------- подготовка в банке, переносы ----------

    def tick(self, today: date) -> list[dict]:
        """За 5 дней до пары — задача «подготовиться» в банк."""
        made = []
        rows = self.conn.execute(
            "SELECT id FROM sched_marks WHERE status='active' AND task_id IS NULL AND day >= ? AND day <= ?",
            (today.isoformat(), (today + timedelta(days=PREP_DAYS)).isoformat())).fetchall()
        for r in rows:
            m = self.get(r["id"])
            name, _, _, prep, diff = KINDS[m["kind"]]
            t = self.g.planner.add_task(f"📖 Подготовиться: {name.lower()} — {m['subject']}"[:200], "study", today,
                                        difficulty=diff, est_min=prep, deadline=date.fromisoformat(m["day"]))
            self.conn.execute("UPDATE sched_marks SET task_id = ? WHERE id = ?", (t["id"], m["id"]))
            made.append({**m, "task": t})
        if rows:
            self.conn.commit()
        return made

    def moved(self, old_key: str, new: dict) -> dict | None:
        """Пару перенесли — квест и дедлайн подготовки едут следом."""
        r = self.conn.execute("SELECT id FROM sched_marks WHERE key = ? AND status='active'", (old_key,)).fetchone()
        if r is None:
            return None
        m = self.get(r["id"])
        self.conn.execute("UPDATE sched_marks SET key=?, day=?, start=?, ask_after=? WHERE id=?",
                          (new["key"], new["day"], new["start"],
                           (date.fromisoformat(new["day"]) + timedelta(days=ASK_AFTER_DAYS)).isoformat(), m["id"]))
        if m["quest_id"]:
            self.conn.execute("UPDATE quests SET day = ? WHERE id = ? AND status = 'todo'", (new["day"], m["quest_id"]))
        if m["task_id"]:
            self.conn.execute("UPDATE bank_tasks SET deadline = ? WHERE id = ? AND status = 'open'",
                              (new["day"], m["task_id"]))
        return self.get(m["id"])

    # ---------- оценки ----------

    def grades_pending(self, today: date) -> list[dict]:
        """Написал, прошла неделя, оценки ещё нет."""
        out = []
        for r in self.conn.execute(
                "SELECT m.id FROM sched_marks m JOIN quests q ON q.id = m.quest_id WHERE m.status='active' "
                "AND m.grade IS NULL AND q.status='done' AND m.ask_after <= ? ORDER BY m.day", (today.isoformat(),)):
            out.append(self.get(r["id"]))
        return out

    def set_grade(self, mid: int, grade: str, today: date) -> dict:
        m = self.get(mid)
        if grade == "later":
            self.conn.execute("UPDATE sched_marks SET ask_after = ? WHERE id = ?",
                              ((today + timedelta(days=3)).isoformat(), mid))
            self.conn.commit()
            return self.get(mid)
        if grade not in GRADES:
            raise StudyError("Оценка: 5 / 4 / 3 / зачёт / не сдал")
        if m["grade"]:
            raise StudyError("Оценка уже стоит")
        title, pct = GRADES[grade]
        bonus = int(round(m["xp"] * pct / 10) * 10)
        if bonus:
            now = datetime.now(self.g.tz).replace(tzinfo=None).isoformat(timespec="seconds")
            self.conn.execute(
                "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'bonus', ?, ?, 'done', ?)",
                (today.isoformat(), f"🏅 {title}: {m['kind_title'].lower()} — {m['subject']}"[:200], bonus, now))
        self.conn.execute("UPDATE sched_marks SET grade = ?, bonus_xp = ? WHERE id = ?", (grade, bonus, mid))
        self.conn.commit()
        return self.get(mid)

    def counts(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {"marks_done": q("SELECT COUNT(*) FROM sched_marks m JOIN quests q ON q.id=m.quest_id "
                                "WHERE m.status='active' AND q.status='done'"),
                "grades5": q("SELECT COUNT(*) FROM sched_marks WHERE grade='5'"),
                "exams_done": q("SELECT COUNT(*) FROM sched_marks m JOIN quests q ON q.id=m.quest_id "
                                "WHERE m.kind='exam' AND q.status='done'")}
