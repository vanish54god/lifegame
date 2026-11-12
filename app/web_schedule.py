"""API расписания пар: подключение календаря, пары дня, «сейчас / дальше»."""

from datetime import date

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field


class SchedSettingsIn(BaseModel):
    url: str | None = Field(None, max_length=2000)
    commute_min: int | None = Field(None, ge=0, le=600)
    leave: bool | None = None


def add_schedule_routes(app: FastAPI, game, today, now, require_auth) -> None:
    auth = [Depends(require_auth)]
    sch = game.schedule

    def day_info(d: date) -> dict:
        la = sch.leave_at(d)
        return {"day": d.isoformat(), "pairs": sch.day(d), "busy": sch.busy(d), "leave_at": la[0] if la else None}

    @app.get("/api/schedule/settings", dependencies=auth)
    async def sched_settings():
        return sch.settings()

    @app.put("/api/schedule/settings", dependencies=auth)
    async def sched_save(body: SchedSettingsIn):
        st = sch.save_settings(body.url, body.commute_min, body.leave)
        if body.url:
            try:
                r = await sch.sync(today())
                return {**sch.settings(), "synced": r["count"]}
            except Exception:
                return sch.settings()          # ошибка уже записана в last_error — покажем её
        return st

    @app.post("/api/schedule/sync", dependencies=auth)
    async def sched_sync():
        r = await sch.sync(today())
        return {**sch.settings(), "synced": r["count"], "cancelled": len(r["cancelled"]), "moved": len(r["moved"])}

    @app.get("/api/schedule/now", dependencies=auth)
    async def sched_now():
        return {**sch.now_next(now()), **day_info(today()), "connected": bool(sch.url)}

    @app.get("/api/schedule/day/{day}", dependencies=auth)
    async def sched_day(day: date):
        return day_info(day)

    @app.get("/api/schedule/week", dependencies=auth)
    async def sched_week():
        return {"days": [day_info(date.fromisoformat(d["day"])) for d in sch.next_days(today(), 7)]}
