"""
Банк заданий и время.
- Банк: все дела, пока они не сделаны. У задачи есть категория, сложность, примерное время, дедлайн, части.
- 🔥 Огонь: насколько горит задача — по дедлайну И объёму оставшейся работы.
- Перенос в день: задача становится квестом. Не сделал — сама вернулась в банк.
- ⏱ Таймер на квест и темп (быстрее / как думал / дольше).
- ⏰ «Начать не позднее» и нагрузка дня.
"""

from datetime import date, datetime, timedelta

from . import rules


class PlanError(Exception):
    """Ошибка, которую можно показать как есть."""


PACE = {"fast": "⚡ быстрее", "ok": "👌 как думал", "slow": "🐢 дольше"}
PACE_RATIO = {"fast": 0.75, "ok": 1.0, "slow": 1.4}   # если таймера не было — грубая оценка


def heat_level(rem_min: int, deadline: date | None, today: date) -> int:
    """0 ❄️ … 4 🔥🔥🔥.  Учитывает и близость дедлайна, и сколько часов работы на день осталось."""
    if deadline is None:
        return 0
    days = (deadline - today).days
    if days <= 0:
        return 4
    per_day = (rem_min or 30) / 60 / days
    prox = 3 if days == 1 else 2 if days <= 3 else 1 if days <= 7 else 0
    load = 3 if per_day >= 3 else 2 if per_day >= 1.5 else 1 if per_day >= 0.5 else 0
    return max(prox, load)


class Planner:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ================= Банк =================

    def add_task(self, title: str, category: str, today: date, difficulty: int = 2,
                 est_min: int | None = None, deadline: date | None = None, parent_id: int | None = None) -> dict:
        title = title.strip()
        if not title:
            raise PlanError("Напиши, что за задача")
        if len(title) > 200:
            raise PlanError("Слишком длинное название")
        cat = rules.CATEGORIES.get(category)
        if cat is None or not cat.pickable:
            raise PlanError("Неизвестная категория")
        if difficulty not in rules.DIFFICULTY:
            raise PlanError("Сложность: 1–4")
        if est_min is not None and not (0 < est_min <= 100 * 60):
            raise PlanError("Время — от 1 минуты до 100 часов")
        if parent_id is not None:
            parent = self.task(parent_id, today)
            if parent["parent_id"]:
                raise PlanError("Части можно делать только у основной задачи")
            if parent["status"] == "done":
                # все прежние части были сделаны — новая часть снова открывает задачу
                self.conn.execute("UPDATE bank_tasks SET status='open', done_day=NULL WHERE id=?", (parent_id,))
            if parent["planned"]:
                raise PlanError("Задача уже в плане — сначала убери её из дня")
            category = category or parent["category"]
            deadline = deadline or (date.fromisoformat(parent["deadline"]) if parent["deadline"] else None)
        cur = self.conn.execute(
            "INSERT INTO bank_tasks (title, category, difficulty, est_min, deadline, parent_id, created_day) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, category, difficulty, est_min, deadline.isoformat() if deadline else None, parent_id,
             today.isoformat()))
        self.conn.commit()
        return self.task(cur.lastrowid, today)

    def edit_task(self, tid: int, today: date, **f) -> dict:
        t = self.task(tid, today)
        upd = {}
        if f.get("title") is not None:
            if not f["title"].strip():
                raise PlanError("Пустое название")
            upd["title"] = f["title"].strip()[:200]
        if f.get("category") is not None:
            if f["category"] not in rules.CATEGORIES or not rules.CATEGORIES[f["category"]].pickable:
                raise PlanError("Неизвестная категория")
            upd["category"] = f["category"]
        if f.get("difficulty") is not None:
            if f["difficulty"] not in rules.DIFFICULTY:
                raise PlanError("Сложность: 1–4")
            upd["difficulty"] = f["difficulty"]
        if f.get("est_min") is not None:
            upd["est_min"] = f["est_min"] or None
        if "deadline" in f:
            upd["deadline"] = f["deadline"].isoformat() if f["deadline"] else None
        if upd:
            sets = ", ".join(f"{k} = ?" for k in upd)
            self.conn.execute(f"UPDATE bank_tasks SET {sets} WHERE id = ?", (*upd.values(), tid))
            self.conn.commit()
        return self.task(tid, today)

    def delete_task(self, tid: int, today: date) -> None:
        t = self.task(tid, today)
        if t["planned"]:
            raise PlanError("Задача в плане на день — сначала убери квест")
        ids = [tid] + [c["id"] for c in t["children"]]
        self.conn.execute(f"UPDATE quests SET bank_id = NULL WHERE bank_id IN ({','.join('?' * len(ids))})", ids)
        self.conn.execute(f"DELETE FROM bank_tasks WHERE id IN ({','.join('?' * len(ids))})", ids)
        self.conn.commit()

    def _planned_quest(self, tid: int, today: date) -> dict | None:
        """Задача «в плане», если есть невыполненный квест на сегодня или позже."""
        row = self.conn.execute(
            "SELECT * FROM quests WHERE bank_id = ? AND status = 'todo' AND day >= ? ORDER BY day LIMIT 1",
            (tid, today.isoformat())).fetchone()
        if row is None:
            return None
        from .game import _row_to_quest
        return _row_to_quest(row).to_dict()

    def _enrich(self, row, today: date, with_children: bool = True) -> dict:
        t = dict(row)
        cat = rules.CATEGORIES[t["category"]]
        name, emoji, _ = rules.DIFFICULTY[t["difficulty"]]
        t.update(cat_emoji=cat.emoji, cat_title=cat.title, diff_name=name, diff_emoji=emoji)
        t["planned"] = self._planned_quest(t["id"], today) if t["status"] == "open" else None
        t["children"] = []
        if with_children and not t["parent_id"]:
            t["children"] = [self._enrich(r, today, False) for r in self.conn.execute(
                "SELECT * FROM bank_tasks WHERE parent_id = ? ORDER BY status, id", (t["id"],))]
        kids = t["children"]
        open_kids = [c for c in kids if c["status"] == "open"]
        if kids:
            t["progress"] = round(100 * (len(kids) - len(open_kids)) / len(kids))
            t["rem_min"] = sum(c["est_min"] or 30 for c in open_kids)
        else:
            t["progress"] = 100 if t["status"] == "done" else 0
            t["rem_min"] = 0 if t["status"] == "done" else (t["est_min"] or 0)
        dl = date.fromisoformat(t["deadline"]) if t["deadline"] else None
        t["days_left"] = (dl - today).days if dl else None
        t["heat"] = 0 if t["status"] == "done" else heat_level(t["rem_min"], dl, today)
        t["heat_emoji"] = rules.HEAT[t["heat"]]
        t["heat_name"] = rules.HEAT_NAMES[t["heat"]]
        t["age"] = (today - date.fromisoformat(t["created_day"])).days
        t["suggested_xp"] = rules.suggest_xp(cat, t["difficulty"])
        t["early"] = bool(dl and (dl - today).days >= rules.EARLY_DAYS)
        return t

    def task(self, tid: int, today: date) -> dict:
        row = self.conn.execute("SELECT * FROM bank_tasks WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise PlanError("Такой задачи нет")
        return self._enrich(row, today)

    def tasks(self, today: date, status: str = "open") -> list[dict]:
        """Задачи банка верхнего уровня. Открытые — по огню, потом по дедлайну."""
        rows = self.conn.execute("SELECT * FROM bank_tasks WHERE parent_id IS NULL AND status = ?", (status,))
        items = [self._enrich(r, today) for r in rows]
        if status == "open":
            items.sort(key=lambda t: (-t["heat"], t["deadline"] or "9999", -t["age"]))
        else:
            items.sort(key=lambda t: t["done_day"] or "", reverse=True)
        return items

    def schedulable(self, today: date) -> list[dict]:
        """Что можно положить в день: задачи без частей и открытые части, не запланированные."""
        out = []
        for t in self.tasks(today):
            if t["children"]:
                out += [dict(c, parent_title=t["title"]) for c in t["children"]
                        if c["status"] == "open" and not c["planned"]]
            elif not t["planned"]:
                out.append(t)
        out.sort(key=lambda t: (-t["heat"], t["deadline"] or "9999"))
        return out

    def schedule(self, tid: int, day: date, xp: int, today: date) -> dict:
        """Перенести задачу в день. Если до дедлайна 3+ дня — +20% XP «заранее»."""
        t = self.task(tid, today)
        if t["status"] != "open":
            raise PlanError("Задача уже сделана")
        if t["planned"]:
            raise PlanError(f"Задача уже в плане на {t['planned']['day'][8:10]}.{t['planned']['day'][5:7]}")
        if any(c["status"] == "open" for c in t["children"]):
            raise PlanError("У задачи есть части — переноси в день их")
        if day < today:
            raise PlanError("Нельзя планировать в прошлое")
        bonus = 0
        if t["deadline"] and (date.fromisoformat(t["deadline"]) - day).days >= rules.EARLY_DAYS:
            bonus = round(xp * rules.EARLY_BONUS)
        title = t["title"]
        if t["parent_id"]:
            parent = self.task(t["parent_id"], today)
            title = f"{parent['title']}: {t['title']}"
        q, warn = self.g.add_quest(day, rules.CATEGORIES[t["category"]], title, xp + bonus,
                                   t["est_min"], bank_id=tid)
        return {"quest": q, "bonus": bonus, "warning": warn}

    def unschedule(self, quest_id: int) -> None:
        q = self.g.get(quest_id)
        if q.bank_id is None:
            raise PlanError("Этот квест не из банка")
        self.g.delete_quest(quest_id)

    def after_mark(self, q, today: date) -> None:
        """Хук после отметки квеста: закрыть/открыть задачу банка, посчитать темп."""
        if q.bank_id:
            row = self.conn.execute("SELECT * FROM bank_tasks WHERE id = ?", (q.bank_id,)).fetchone()
            if row:
                if q.status == "done":
                    self.conn.execute("UPDATE bank_tasks SET status='done', done_day=? WHERE id=?", (q.day, q.bank_id))
                    if row["parent_id"]:   # все части сделаны — закрываем и большую задачу
                        left = self.conn.execute("SELECT COUNT(*) FROM bank_tasks WHERE parent_id=? AND status='open'",
                                                 (row["parent_id"],)).fetchone()[0]
                        if left == 0:
                            self.conn.execute("UPDATE bank_tasks SET status='done', done_day=? WHERE id=?",
                                              (q.day, row["parent_id"]))
                else:
                    self.conn.execute("UPDATE bank_tasks SET status='open', done_day=NULL WHERE id=?", (q.bank_id,))
                    if row["parent_id"]:
                        self.conn.execute("UPDATE bank_tasks SET status='open', done_day=NULL WHERE id=?",
                                          (row["parent_id"],))
        # темп: есть оценка и таймер — считаем сами
        if q.status == "done" and q.est_min and q.timer_sec >= 60 and q.pace is None:
            ratio = q.timer_sec / 60 / q.est_min
            pace = "fast" if ratio <= 0.8 else "slow" if ratio >= 1.25 else "ok"
            self.conn.execute("UPDATE quests SET pace = ? WHERE id = ?", (pace, q.id))
        if q.status != "done" and q.pace is not None:
            self.conn.execute("UPDATE quests SET pace = NULL WHERE id = ?", (q.id,))
        self.conn.commit()

    def do_now(self, tid: int, xp: int, today: date) -> dict:
        """Сделал задачу вне плана: сразу квест на сегодня + выполнено."""
        res = self.schedule(tid, today, xp, today)
        out = self.g.mark(res["quest"].id, "done", today)
        out["bonus"] = res["bonus"]
        return out

    def digest(self, today: date) -> list[dict]:
        """Задачи с дедлайном в ближайшие 3 дня (и просроченные) — для утренней сводки."""
        out = []
        for t in self.tasks(today):
            items = [dict(c, parent_title=t["title"]) for c in t["children"] if c["status"] == "open"] or [t]
            for x in items:
                if x["days_left"] is not None and x["days_left"] <= rules.EARLY_DAYS:
                    out.append(x)
        return out

    # ================= Таймер и темп =================

    def timer_start(self, quest_id: int) -> dict:
        q = self.g.get(quest_id)
        if q.status != "todo":
            raise PlanError("Квест уже закрыт")
        now = datetime.now().isoformat(timespec="seconds")
        # одновременно идёт только один таймер
        for r in self.conn.execute("SELECT id FROM quests WHERE timer_start IS NOT NULL AND id != ?", (quest_id,)).fetchall():
            self.timer_pause(r["id"])
        if not q.timer_start:
            self.conn.execute("UPDATE quests SET timer_start = ? WHERE id = ?", (now, quest_id))
            self.conn.commit()
        return self.g.get(quest_id).to_dict()

    def timer_pause(self, quest_id: int) -> dict:
        q = self.g.get(quest_id)
        if q.timer_start:
            self.conn.execute("UPDATE quests SET timer_sec = ?, timer_start = NULL WHERE id = ?", (q.elapsed(), quest_id))
            self.conn.commit()
        return self.g.get(quest_id).to_dict()

    def running_timer(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM quests WHERE timer_start IS NOT NULL LIMIT 1").fetchone()
        if row is None:
            return None
        from .game import _row_to_quest
        return _row_to_quest(row).to_dict()

    def set_pace(self, quest_id: int, pace: str | None) -> dict:
        q = self.g.get(quest_id)
        if pace is not None and pace not in PACE:
            raise PlanError("Темп: fast / ok / slow")
        if q.status != "done":
            raise PlanError("Темп ставится выполненному квесту")
        self.conn.execute("UPDATE quests SET pace = ? WHERE id = ?", (pace, quest_id))
        self.conn.commit()
        return self.g.get(quest_id).to_dict()

    def pace_factor(self) -> tuple[float, int]:
        """Во сколько раз реальное время отличается от твоих оценок (по последним 30 квестам)."""
        rows = self.conn.execute("""SELECT est_min, timer_sec, pace FROM quests
            WHERE status='done' AND est_min > 0 AND (pace IS NOT NULL OR timer_sec >= 60)
            ORDER BY id DESC LIMIT 30""").fetchall()
        ratios = []
        for r in rows:
            if r["timer_sec"] and r["timer_sec"] >= 60:
                ratios.append(r["timer_sec"] / 60 / r["est_min"])
            elif r["pace"]:
                ratios.append(PACE_RATIO[r["pace"]])
        if len(ratios) < 5:
            return 1.0, len(ratios)
        f = sum(ratios) / len(ratios)
        return round(min(1.8, max(0.7, f)), 2), len(ratios)

    def pace_counts(self) -> dict:
        rows = self.conn.execute("SELECT pace, COUNT(*) n FROM quests WHERE status='done' AND pace IS NOT NULL "
                                 "GROUP BY pace").fetchall()
        return {r["pace"]: r["n"] for r in rows}

    # ================= Время дня =================

    def _bedtime(self, today: date) -> datetime:
        h, m = map(int, self.g.get_setting("bedtime", "00:00").split(":"))
        start_hour = getattr(self.g, "day_start_hour", 5)
        d = today + timedelta(days=1) if h < start_hour else today
        return datetime(d.year, d.month, d.day, h, m)

    def start_by(self, today: date, now: datetime) -> dict | None:
        """Сколько осталось дел на сегодня и когда надо начать, чтобы лечь вовремя."""
        qs = [q for q in self.g.quests(today) if q.status == "todo" and q.category.pickable]
        if not qs:
            return None
        factor, samples = self.pace_factor()
        rem = sum(max(0, q.est_min * 60 - q.elapsed()) for q in qs if q.est_min) / 60 * factor
        unknown = sum(1 for q in qs if not q.est_min)
        if rem <= 0:
            return {"remaining_min": 0, "unknown": unknown, "start": None, "late": False,
                    "bedtime": self.g.get_setting("bedtime", "00:00"), "factor": factor}
        bed = self._bedtime(today)
        start = bed - timedelta(minutes=rem)
        now = now.replace(tzinfo=None)
        return {"remaining_min": round(rem), "unknown": unknown, "start": start.strftime("%H:%M"),
                "start_iso": start.isoformat(), "late": now >= start, "too_late": now + timedelta(minutes=rem) > bed,
                "bedtime": self.g.get_setting("bedtime", "00:00"), "factor": factor, "samples": samples}

    def load(self, day: date) -> dict:
        qs = [q for q in self.g.quests(day) if q.category.pickable]
        planned = sum(q.est_min or 0 for q in qs)
        # учёт сил: в день с парами (пары + окна + дорога) сил на дела меньше — своя настройка
        busy = self.g.schedule.busy(day)
        base = int(float(self.g.get_setting("capacity_h", "6")) * 60)
        cap = int(float(self.g.get_setting("capacity_pair_h", "3")) * 60) if busy["pairs"] else base
        factor, _ = self.pace_factor()
        return {"planned_min": planned, "real_min": round(planned * factor), "factor": factor,
                "unknown": sum(1 for q in qs if not q.est_min), "capacity_min": cap, "capacity_base": base,
                "busy": busy, "over": planned * factor > cap}

    # ================= Для достижений =================

    def counts(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {
            "done": q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND id NOT IN "
                      "(SELECT DISTINCT parent_id FROM bank_tasks WHERE parent_id IS NOT NULL)"),
            "open": q("SELECT COUNT(*) FROM bank_tasks WHERE status='open' AND parent_id IS NULL"),
            "early": q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND deadline IS NOT NULL "
                       "AND julianday(deadline) - julianday(done_day) >= 3"),
            "fire": q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND deadline = done_day"),
            "split": q("SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) n FROM bank_tasks "
                       "WHERE parent_id IS NOT NULL GROUP BY parent_id)"),
            "boss": q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' AND difficulty=4"),
            "longhaul": q("SELECT COUNT(*) FROM bank_tasks WHERE status='done' "
                          "AND julianday(done_day) - julianday(created_day) >= 30"),
            "deep": q("SELECT COUNT(*) FROM quests WHERE timer_sec >= 3 * 3600"),
        }
