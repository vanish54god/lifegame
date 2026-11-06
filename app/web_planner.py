"""REST API: банк заданий, таймер, темп, время дня, привычки, оценки, неделя, сезоны, календарь."""

from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from . import rules


class TaskIn(BaseModel):
    title: str = Field(max_length=200)
    category: str = "study"
    difficulty: int = Field(2, ge=1, le=4)
    est_min: int | None = Field(None, ge=0, le=6000)
    deadline: date | None = None
    parent_id: int | None = None

class TaskPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    category: str | None = None
    difficulty: int | None = Field(None, ge=1, le=4)
    est_min: int | None = Field(None, ge=0, le=6000)
    deadline: date | None = None
    clear_deadline: bool = False

class ScheduleIn(BaseModel):
    day: date
    xp: int = Field(ge=0, le=100_000)

class DoneIn(BaseModel):
    xp: int | None = Field(None, ge=0, le=100_000)

class TimerIn(BaseModel):
    action: str

class PaceIn(BaseModel):
    pace: str | None = None

class HabitIn(BaseModel):
    title: str = Field(max_length=60)
    emoji: str = Field("🔁", max_length=8)
    per_week: int = Field(7, ge=1, le=7)
    xp: int = Field(20, ge=0, le=200)

class HabitToggle(BaseModel):
    day: date | None = None

class RatingIn(BaseModel):
    day: date
    score: int | None = Field(None, ge=1, le=10)


def add_planner_routes(app: FastAPI, game, today, now, require_auth) -> None:
    p, life = game.planner, game.life
    auth = [Depends(require_auth)]

    def ach_diff(before):
        return [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]

    # ---------- банк ----------

    @app.get("/api/bank", dependencies=auth)
    async def bank():
        t = today()
        return {"tasks": p.tasks(t), "done": p.tasks(t, "done")[:20], "schedulable": p.schedulable(t),
                "difficulty": {k: {"name": n, "emoji": e} for k, (n, e, _) in rules.DIFFICULTY.items()},
                "time_presets": rules.TIME_PRESETS, "heat": rules.HEAT, "heat_names": rules.HEAT_NAMES,
                "early_days": rules.EARLY_DAYS, "early_bonus": rules.EARLY_BONUS}

    @app.post("/api/bank", dependencies=auth)
    async def add_task(body: TaskIn):
        before = game._achieved(today())
        t = p.add_task(body.title, body.category, today(), body.difficulty, body.est_min or None,
                       body.deadline, body.parent_id)
        return {**t, "new_achievements": ach_diff(before)}

    @app.patch("/api/bank/{tid}", dependencies=auth)
    async def patch_task(tid: int, body: TaskPatch):
        f = {"title": body.title, "category": body.category, "difficulty": body.difficulty, "est_min": body.est_min}
        if body.deadline is not None or body.clear_deadline:
            f["deadline"] = None if body.clear_deadline else body.deadline
        return p.edit_task(tid, today(), **f)

    @app.delete("/api/bank/{tid}", dependencies=auth)
    async def del_task(tid: int):
        p.delete_task(tid, today())
        return {"ok": True}

    @app.post("/api/bank/{tid}/schedule", dependencies=auth)
    async def schedule(tid: int, body: ScheduleIn):
        res = p.schedule(tid, body.day, body.xp, today())
        return {"quest": res["quest"].to_dict(), "bonus": res["bonus"], "warning": res["warning"],
                "load": p.load(body.day)}

    @app.post("/api/bank/{tid}/done", dependencies=auth)
    async def done_now(tid: int, body: DoneIn):
        t = p.task(tid, today())
        res = p.do_now(tid, body.xp if body.xp is not None else t["suggested_xp"], today())
        return {"quest": res["quest"].to_dict(), "level_before": res["level_before"],
                "level_after": res["level_after"], "new_achievements": res["new_achievements"], "bonus": res["bonus"]}

    @app.delete("/api/quests/{qid}/unschedule", dependencies=auth)
    async def unschedule(qid: int):
        p.unschedule(qid)
        return {"ok": True}

    # ---------- таймер, темп, время дня ----------

    @app.post("/api/quests/{qid}/timer", dependencies=auth)
    async def timer(qid: int, body: TimerIn):
        return p.timer_start(qid) if body.action == "start" else p.timer_pause(qid)

    @app.post("/api/quests/{qid}/pace", dependencies=auth)
    async def pace(qid: int, body: PaceIn):
        before = game._achieved(today())
        q = p.set_pace(qid, body.pace)
        return {"quest": q, "new_achievements": ach_diff(before)}

    @app.get("/api/plan/day/{day}", dependencies=auth)
    async def plan_day(day: date):
        t = today()
        return {"start_by": p.start_by(t, now()) if day == t else None, "load": p.load(day),
                "pace_factor": p.pace_factor()[0]}

    # ---------- привычки ----------

    @app.get("/api/habits", dependencies=auth)
    async def habits():
        return life.habits(today())

    @app.post("/api/habits", dependencies=auth)
    async def add_habit(body: HabitIn):
        return life.add_habit(body.title, today(), body.emoji, body.per_week, body.xp)

    @app.patch("/api/habits/{hid}", dependencies=auth)
    async def patch_habit(hid: int, body: HabitIn):
        return life.edit_habit(hid, today(), title=body.title, emoji=body.emoji, per_week=body.per_week, xp=body.xp)

    @app.delete("/api/habits/{hid}", dependencies=auth)
    async def del_habit(hid: int):
        life.archive_habit(hid, today())
        return {"ok": True}

    @app.post("/api/habits/{hid}/toggle", dependencies=auth)
    async def toggle(hid: int, body: HabitToggle):
        return life.toggle_habit(hid, body.day or today(), today())

    # ---------- оценка, неделя, сезоны, календарь ----------

    @app.put("/api/rating", dependencies=auth)
    async def rate(body: RatingIn):
        before = game._achieved(today())
        r = life.rate(body.day, body.score, today())
        return {**r, "new_achievements": ach_diff(before)}

    @app.get("/api/rating/{day}", dependencies=auth)
    async def get_rating(day: date):
        return {"day": day.isoformat(), "score": life.rating(day)}

    @app.get("/api/review", dependencies=auth)
    async def review():
        return {**life.week_review(today()), "rating": life.rating_stats(today())}

    @app.get("/api/season", dependencies=auth)
    async def season(month: str | None = None):
        t = today()
        m = month or t.strftime("%Y-%m")
        first = game.conn.execute("SELECT MIN(day) FROM quests").fetchone()[0] or t.isoformat()
        months, d = [], date.fromisoformat(first[:7] + "-01")
        while d <= t:
            months.append(d.strftime("%Y-%m"))
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        return {**life.season(m), "months": months[::-1]}

    @app.get("/api/calendar", dependencies=auth)
    async def calendar(month: str | None = None):
        return life.calendar(month or today().strftime("%Y-%m"), today())
