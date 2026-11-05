"""
Веб-сервер: REST API для приложения + раздача самого приложения (папка web/).
Все запросы к /api (кроме входа) требуют заголовок  Authorization: Bearer <токен>.
"""

import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import rules
from .auth import Auth
from .config import Config
from .game import SHOP_KINDS, Game, GameError, game_day
from .promise_text import parse_promise

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------- Что приходит от приложения ----------

class LoginIn(BaseModel):
    code: str = Field(max_length=32)

class QuestIn(BaseModel):
    day: date
    category: str
    title: str = Field(max_length=200)
    xp: int

class QuestPatch(BaseModel):
    status: str | None = None
    title: str | None = Field(None, max_length=200)
    xp: int | None = None
    day: date | None = None

class TemplateIn(BaseModel):
    category: str
    title: str = Field(max_length=200)
    xp: int

class FromTemplateIn(BaseModel):
    day: date
    template_id: int

class ItemIn(BaseModel):
    title: str = Field(max_length=200)
    cost: int
    kind: str = "wish"
    repeatable: bool = False

class ItemPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    cost: int | None = None
    kind: str | None = None
    repeatable: bool | None = None

class SettingsIn(BaseModel):
    remind_morning: str = ""
    remind_evening: str = ""
    remind_promises: str = "10:00"

class PromiseIn(BaseModel):
    text: str = Field(max_length=300)

class PromisePatch(BaseModel):
    action: str | None = None          # keep / cancel
    due: date | None = None
    clear_due: bool = False


def create_app(cfg: Config, game: Game, auth: Auth) -> FastAPI:
    app = FastAPI(title="LifeGame", docs_url=None, redoc_url=None, openapi_url=None)

    def today() -> date:
        return game_day(datetime.now(cfg.tz), cfg.day_start_hour)

    def category(key: str) -> rules.Category:
        c = rules.CATEGORIES.get(key)
        if c is None:
            raise HTTPException(400, "Неизвестная категория")
        return c

    # Ошибки игры отдаём как 400 с понятным текстом
    @app.exception_handler(GameError)
    async def game_error(_: Request, e: GameError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    # Заголовки безопасности для всех ответов
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if request.url.path.startswith("/api"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    async def require_auth(request: Request) -> str:
        # async — чтобы выполнялась в том же потоке, что и всё остальное (SQLite не любит потоки)
        h = request.headers.get("authorization", "")
        token = h[7:] if h.lower().startswith("bearer ") else ""
        if not auth.check(token):
            raise HTTPException(401, "Нужно войти: получи код в боте (кнопка «🌐 Веб-приложение»)")
        return token

    # ================= Вход =================

    last_login_try = [0.0]

    @app.post("/api/login")
    async def login(body: LoginIn, request: Request):
        # не чаще раза в секунду — от перебора
        if time.monotonic() - last_login_try[0] < 1:
            raise HTTPException(429, "Слишком часто, подожди секунду")
        last_login_try[0] = time.monotonic()
        token = auth.exchange(body.code, request.headers.get("user-agent", ""))
        if token is None:
            raise HTTPException(401, "Код неверный или устарел. Запроси новый в боте.")
        return {"token": token}

    @app.post("/api/logout")
    async def logout(token: str = Depends(require_auth)):
        auth.logout(token)
        return {"ok": True}

    # ================= Чтение =================

    @app.get("/api/meta", dependencies=[Depends(require_auth)])
    async def meta():
        return {
            "today": today().isoformat(),
            "categories": [{"key": c.key, "title": c.title, "emoji": c.emoji, "xp_min": c.xp_min,
                            "xp_max": c.xp_max, "is_main": c.is_main, "pickable": c.pickable}
                           for c in rules.CATEGORIES.values()],
            "max_main": rules.MAX_MAIN_PER_DAY,
            "shop_kinds": SHOP_KINDS,
            "level_base": rules.LEVEL_BASE, "level_step": rules.LEVEL_STEP,
            "coins_per_xp": rules.COINS_PER_XP,
        }

    @app.get("/api/day/{day}", dependencies=[Depends(require_auth)])
    async def get_day(day: date):
        return {"day": day.isoformat(), "today": today().isoformat(),
                "quests": [q.to_dict() for q in game.quests(day)],
                "stats": game.stats(day).to_dict()}

    @app.get("/api/stats", dependencies=[Depends(require_auth)])
    async def stats():
        return game.full_stats(today())

    # ================= Квесты =================

    @app.post("/api/quests", dependencies=[Depends(require_auth)])
    async def add_quest(body: QuestIn):
        q, warn = game.add_quest(body.day, category(body.category), body.title, body.xp)
        return {"quest": q.to_dict(), "warning": warn}

    @app.patch("/api/quests/{qid}", dependencies=[Depends(require_auth)])
    async def patch_quest(qid: int, body: QuestPatch):
        if body.title is not None or body.xp is not None or body.day is not None:
            game.edit_quest(qid, body.title, body.xp, body.day)
        if body.status is not None:
            res = game.mark(qid, body.status, today())
            return {"quest": res["quest"].to_dict(), "level_before": res["level_before"],
                    "level_after": res["level_after"], "new_achievements": res["new_achievements"]}
        return {"quest": game.get(qid).to_dict()}

    @app.delete("/api/quests/{qid}", dependencies=[Depends(require_auth)])
    async def delete_quest(qid: int):
        game.delete_quest(qid)
        return {"ok": True}

    # ================= Шаблоны =================

    @app.get("/api/templates", dependencies=[Depends(require_auth)])
    async def templates():
        return game.templates()

    @app.post("/api/templates", dependencies=[Depends(require_auth)])
    async def add_template(body: TemplateIn):
        return game.add_template(category(body.category), body.title, body.xp)

    @app.delete("/api/templates/{tid}", dependencies=[Depends(require_auth)])
    async def delete_template(tid: int):
        game.delete_template(tid)
        return {"ok": True}

    @app.post("/api/quests/from-template", dependencies=[Depends(require_auth)])
    async def from_template(body: FromTemplateIn):
        q, warn = game.add_from_template(body.day, body.template_id)
        return {"quest": q.to_dict(), "warning": warn}

    # ================= Магазин =================

    @app.get("/api/shop", dependencies=[Depends(require_auth)])
    async def shop():
        return {"coins": game.stats().coins, "items": game.shop_items(),
                "purchases": game.purchases()}

    @app.post("/api/shop/items", dependencies=[Depends(require_auth)])
    async def add_item(body: ItemIn):
        return game.add_shop_item(body.title, body.cost, body.kind, body.repeatable)

    @app.patch("/api/shop/items/{iid}", dependencies=[Depends(require_auth)])
    async def patch_item(iid: int, body: ItemPatch):
        return game.edit_shop_item(iid, body.title, body.cost, body.kind, body.repeatable)

    @app.delete("/api/shop/items/{iid}", dependencies=[Depends(require_auth)])
    async def delete_item(iid: int):
        game.archive_shop_item(iid)
        return {"ok": True}

    @app.post("/api/shop/items/{iid}/buy", dependencies=[Depends(require_auth)])
    async def buy(iid: int):
        before = game._achieved(today())
        it, left = game.buy(iid)
        new = [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]
        return {"item": it, "coins": left, "new_achievements": new}

    @app.delete("/api/shop/purchases/{pid}", dependencies=[Depends(require_auth)])
    async def refund(pid: int):
        game.refund(pid)
        return {"ok": True}

    # ================= Обещания =================

    @app.get("/api/promises", dependencies=[Depends(require_auth)])
    async def promises():
        t = today()
        return {"open": game.promises(t), "kept": game.promises(t, "kept")[:20],
                "stats": game.promise_stats(t), "xp": rules.PROMISE_XP,
                "fast_xp": round(rules.PROMISE_XP * rules.PROMISE_FAST_MULT),
                "fast_days": rules.PROMISE_FAST_DAYS}

    @app.post("/api/promises", dependencies=[Depends(require_auth)])
    async def add_promise(body: PromiseIn):
        t = today()
        text, due = parse_promise(body.text, t)
        return game.add_promise(text, t, due)

    @app.patch("/api/promises/{pid}", dependencies=[Depends(require_auth)])
    async def patch_promise(pid: int, body: PromisePatch):
        t = today()
        if body.action == "keep":
            res = game.keep_promise(pid, t)
            return {**res, "promise": res["promise"]}
        if body.action == "cancel":
            return {"promise": game.cancel_promise(pid, t)}
        if body.due is not None or body.clear_due:
            return {"promise": game.set_promise_due(pid, None if body.clear_due else body.due, t)}
        raise HTTPException(400, "Нечего менять")

    # ================= Настройки =================

    @app.get("/api/settings", dependencies=[Depends(require_auth)])
    async def get_settings():
        return {"remind_morning": game.get_setting("remind_morning", ""),
                "remind_evening": game.get_setting("remind_evening", ""),
                "remind_promises": game.get_setting("remind_promises", "10:00"),
                "sessions": auth.sessions_count(),
                "day_start_hour": cfg.day_start_hour}

    @app.put("/api/settings", dependencies=[Depends(require_auth)])
    async def put_settings(body: SettingsIn):
        for key in ("remind_morning", "remind_evening", "remind_promises"):
            val = getattr(body, key).strip()
            if val and not TIME_RE.match(val):
                raise HTTPException(400, "Время в формате ЧЧ:ММ, например 08:30")
            game.set_setting(key, val)
        return await get_settings()

    # ================= Само приложение =================

    @app.get("/sw.js", include_in_schema=False)
    async def sw():
        # service worker должен лежать в корне и не кэшироваться браузером
        return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app
