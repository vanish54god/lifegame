"""API сюжетных миссий: миссии, этапы, финал с катсценой, главы и хроника."""

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field


class MissionIn(BaseModel):
    title: str = Field(max_length=120)
    xp: int = Field(1000, gt=0, le=20000)
    why: str = Field("", max_length=300)
    emoji: str = Field("🎬", max_length=4)
    steps: list[str] = Field(default_factory=list, max_length=20)


class MissionPatch(BaseModel):
    title: str | None = Field(None, max_length=120)
    xp: int | None = Field(None, gt=0, le=20000)
    why: str | None = Field(None, max_length=300)
    emoji: str | None = Field(None, max_length=4)


class StepIn(BaseModel):
    title: str = Field(max_length=120)
    xp: int = Field(100, ge=0, le=5000)


class OutroIn(BaseModel):
    outro: str = Field("", max_length=200)


class PauseIn(BaseModel):
    paused: bool


class ChapterIn(BaseModel):
    title: str = Field(max_length=80)


def add_story_routes(app: FastAPI, game, today, require_auth) -> None:
    auth = [Depends(require_auth)]
    st = game.story

    def rewarded(fn):
        before_lvl = game.stats().level.level
        before = game._achieved(today())
        r = fn()
        new = [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]
        return {**r, "level_before": before_lvl, "level_after": game.stats().level.level, "new_achievements": new}

    # ---------- 📰 неделя ----------

    @app.get("/api/week/brief", dependencies=auth)
    async def week_brief():
        return game.weekly.brief(today())

    @app.get("/api/week/recap", dependencies=auth)
    async def week_recap(last: bool = False):
        return game.weekly.recap(today(), last)

    # ---------- 💪 навыки ----------

    @app.get("/api/skills", dependencies=auth)
    async def skills():
        return game.skills.all(today())

    @app.get("/api/skills/ups", dependencies=auth)
    async def skill_ups():
        return game.skills.ups(today())

    @app.get("/api/story", dependencies=auth)
    async def story():
        return {"active": st.missions("active"), "paused": st.missions("paused"), "chapter": st.chapter(today()),
                "respect": st.respect()}

    @app.post("/api/story", dependencies=auth)
    async def add(body: MissionIn):
        return st.add(body.title, today(), body.xp, body.why, body.emoji, body.steps)

    @app.patch("/api/story/{mid}", dependencies=auth)
    async def edit(mid: int, body: MissionPatch):
        return st.edit(mid, body.title, body.xp, body.why, body.emoji)

    @app.delete("/api/story/{mid}", dependencies=auth)
    async def delete(mid: int):
        st.delete(mid)
        return {"ok": True}

    @app.post("/api/story/{mid}/pause", dependencies=auth)
    async def pause(mid: int, body: PauseIn):
        return st.set_paused(mid, body.paused)

    @app.post("/api/story/{mid}/steps", dependencies=auth)
    async def add_step(mid: int, body: StepIn):
        return st.add_step(mid, body.title, body.xp)

    @app.post("/api/story/steps/{sid}/toggle", dependencies=auth)
    async def toggle(sid: int):
        return rewarded(lambda: st.toggle_step(sid, today()))

    @app.delete("/api/story/steps/{sid}", dependencies=auth)
    async def del_step(sid: int):
        return st.delete_step(sid)

    @app.post("/api/story/{mid}/complete", dependencies=auth)
    async def complete(mid: int, body: OutroIn):
        return rewarded(lambda: st.complete(mid, today(), body.outro))

    @app.get("/api/story/chronicle", dependencies=auth)
    async def chronicle():
        return {"chapters": st.chronicle(today()), "respect": st.respect()}

    @app.post("/api/story/chapter", dependencies=auth)
    async def new_chapter(body: ChapterIn):
        return st.new_chapter(body.title, today())

    @app.put("/api/story/chapter", dependencies=auth)
    async def rename_chapter(body: ChapterIn):
        return st.rename_chapter(body.title, today())
