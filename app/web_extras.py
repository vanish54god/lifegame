"""API: ⭐ розыск, 🌙 «иду спать», 🎲 побочки, 📊 статистика как в GTA."""

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from .planner import wanted


class SideIn(BaseModel):
    title: str = Field(max_length=120)
    xp: int = Field(50, ge=10, le=300)


class AnswerIn(BaseModel):
    take: bool


def add_extra_routes(app: FastAPI, game, today, now, require_auth) -> None:
    auth = [Depends(require_auth)]

    def rewarded(fn):
        lvl = game.stats().level.level
        before = game._achieved(today())
        r = fn()
        new = [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]
        return {**r, "level_before": lvl, "level_after": game.stats().level.level, "new_achievements": new}

    @app.get("/api/wanted", dependencies=auth)
    async def get_wanted():
        return wanted(game.planner, today())

    @app.get("/api/sleep", dependencies=auth)
    async def sleep_stats():
        return game.sleep.stats(today())

    @app.post("/api/sleep", dependencies=auth)
    async def sleep_go():
        return rewarded(lambda: game.sleep.go(today(), now()))

    @app.get("/api/side", dependencies=auth)
    async def side():
        return {"pool": game.side.pool(), "today": game.side.offer_today(today())}

    @app.post("/api/side", dependencies=auth)
    async def side_add(body: SideIn):
        return game.side.add(body.title, body.xp)

    @app.delete("/api/side/{pid}", dependencies=auth)
    async def side_del(pid: int):
        game.side.remove(pid)
        return {"ok": True}

    @app.post("/api/side/offer", dependencies=auth)
    async def side_offer():
        return game.side.offer(today()) or {}

    @app.post("/api/side/offers/{oid}", dependencies=auth)
    async def side_answer(oid: int, body: AnswerIn):
        return game.side.answer(oid, body.take, today())

    @app.get("/api/funstats", dependencies=auth)
    async def funstats():
        return game.funstats.all(today())
