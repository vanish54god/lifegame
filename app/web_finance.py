"""REST API финансов. Суммы от приложения приходят в рублях, в базе — копейки."""

from datetime import date, timedelta

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from .finance import IN_CATS, OUT_CATS, parse_money

MAX_RUB = 1_000_000_000


def k(rub_amount: float | None) -> int | None:
    return None if rub_amount is None else round(rub_amount * 100)


class TxIn(BaseModel):
    kind: str
    amount: float = Field(gt=0, lt=MAX_RUB)
    category: str | None = None
    note: str = Field("", max_length=200)
    day: date | None = None

class QuickIn(BaseModel):
    text: str = Field(max_length=100)
    day: date | None = None

class TxPatch(BaseModel):
    category: str | None = None
    day: date | None = None
    envelope: str | None = None

class EnvApply(BaseModel):
    amount: float | None = Field(None, gt=0, lt=MAX_RUB)

class EnvMoveIn(BaseModel):
    src: str
    dst: str
    amount: float = Field(gt=0, lt=MAX_RUB)

class EnvSettings(BaseModel):
    shares: dict[str, int] | None = None
    save_pct: int | None = Field(None, ge=0, le=80)
    save_target: int | None = None
    horizon: int | None = Field(None, ge=3, le=45)

class ExpectedIn(BaseModel):
    title: str = Field(max_length=60)
    amount: float = Field(gt=0, lt=MAX_RUB)
    day: date
    repeat: str = "none"

class ShiftIn(BaseModel):
    day: date
    company: str = Field(max_length=60)
    work_type: str = Field(max_length=40)
    amount: float | None = Field(None, gt=0, lt=MAX_RUB)
    hours: float | None = Field(None, gt=0, lt=100)
    rate: float | None = Field(None, gt=0, lt=MAX_RUB)
    note: str = Field("", max_length=200)

class ShiftPatch(BaseModel):
    action: str | None = None   # pay / unpay
    day: date | None = None
    company: str | None = Field(None, max_length=60)
    work_type: str | None = Field(None, max_length=40)
    amount: float | None = Field(None, gt=0, lt=MAX_RUB)
    hours: float | None = None
    rate: float | None = None
    note: str | None = Field(None, max_length=200)

class CompanyPay(BaseModel):
    company: str

class PlanIn(BaseModel):
    title: str = Field(max_length=100)
    amount: float = Field(gt=0, lt=MAX_RUB)
    due: date
    repeat: str = "none"
    category: str = "other"

class WishIn(BaseModel):
    title: str = Field(max_length=100)
    target: float = Field(gt=0, lt=MAX_RUB)

class MoneyIn(BaseModel):
    amount: float = Field(gt=-MAX_RUB, lt=MAX_RUB)

class SavingIn(BaseModel):
    title: str = Field(max_length=60)
    kind: str = "saving"

class FinSettingsIn(BaseModel):
    daily_limit: float | None = Field(None, ge=0, lt=MAX_RUB)
    start_balance: float | None = Field(None, gt=-MAX_RUB, lt=MAX_RUB)
    work_types: list[str] | None = None


def add_finance_routes(app: FastAPI, game, today, require_auth) -> None:
    fin = game.fin
    auth = [Depends(require_auth)]

    @app.get("/api/fin/meta", dependencies=auth)
    async def meta():
        cats = lambda lst: [{"key": c.key, "title": c.title, "emoji": c.emoji} for c in lst]
        return {"out": cats(OUT_CATS), "in": cats(IN_CATS), "work_types": fin.work_types,
                "daily_limit": fin.daily_limit, "start_balance": fin.start_balance}

    @app.get("/api/fin/overview", dependencies=auth)
    async def overview():
        return {**fin.overview(today()), "limit_streak": fin.limit_streak(today())}

    # ---------- операции ----------

    @app.get("/api/fin/tx", dependencies=auth)
    async def txs(start: date | None = None, end: date | None = None):
        t = today()
        return fin.txs(start or t - timedelta(days=30), end or t)

    @app.post("/api/fin/tx", dependencies=auth)
    async def add_tx(body: TxIn):
        if body.day and body.day > today():
            from .finance import FinError
            raise FinError("Нельзя записать трату в будущее")
        return fin.add_tx(body.day or today(), body.kind, k(body.amount), body.category, body.note)

    @app.post("/api/fin/quick", dependencies=auth)
    async def quick(body: QuickIn):
        parsed = parse_money(body.text)
        if parsed is None:
            from .finance import FinError
            raise FinError("Не понял. Примеры: «кофе 250», «+30000 зарплата»")
        kind, amount, note = parsed
        t = fin.add_tx(today(), kind, amount, note=note)
        if body.day and body.day != today():
            t = fin.set_tx_day(t["id"], body.day, today())
        return t

    @app.patch("/api/fin/tx/{tid}", dependencies=auth)
    async def patch_tx(tid: int, body: TxPatch):
        t = fin.tx(tid)
        if body.day is not None:
            t = fin.set_tx_day(tid, body.day, today())
        if body.category is not None:
            t = fin.set_tx_category(tid, body.category)
        if body.envelope is not None:
            t = game.env.set_tx_envelope(tid, body.envelope)
        return t

    @app.delete("/api/fin/tx/{tid}", dependencies=auth)
    async def del_tx(tid: int):
        fin.delete_tx(tid)
        return {"ok": True}

    # ---------- конверты ----------

    @app.get("/api/fin/envelopes", dependencies=auth)
    async def envelopes():
        env, t = game.env, today()
        rewards = env.settle(t)
        b = env.budget(t)
        from .envelopes import ENVS
        return {**b, "rewards": rewards, "settings": env.settings(), "expected": env.expected(t),
                "learned": env.learned_shares(t), "envs": {k: {"emoji": e, "title": n} for k, (e, n) in ENVS.items()},
                "plan": env.plan(b["unallocated"], t) if b["unallocated"] > 0 else None,
                "savings": [{"id": x["id"], "title": x["title"]} for x in fin.savings()],
                "streak": env.limit_streak(t)}

    @app.post("/api/fin/envelopes/apply", dependencies=auth)
    async def env_apply(body: EnvApply):
        un = game.env.unallocated()
        amount = min(k(body.amount) if body.amount else un, un)
        return game.env.apply(amount, today())

    @app.post("/api/fin/envelopes/move", dependencies=auth)
    async def env_move(body: EnvMoveIn):
        return game.env.move(body.src, body.dst, k(body.amount), today())

    @app.put("/api/fin/envelopes/settings", dependencies=auth)
    async def env_settings(body: EnvSettings):
        st = game.env.save_settings(body.shares, body.save_pct, body.save_target, body.horizon)
        game.env.refresh_today(today())
        return st

    @app.post("/api/fin/expected", dependencies=auth)
    async def add_expected(body: ExpectedIn):
        e = game.env.add_expected(body.title, k(body.amount), body.day, body.repeat)
        game.env.refresh_today(today())
        return e

    @app.delete("/api/fin/expected/{eid}", dependencies=auth)
    async def del_expected(eid: int):
        game.env.delete_expected(eid)
        game.env.refresh_today(today())
        return {"ok": True}

    # ---------- смены ----------

    @app.get("/api/fin/shifts", dependencies=auth)
    async def shifts():
        return {"companies": fin.companies(), "shifts": fin.shifts(limit=150),
                "expected": fin.expected_salary(), "work_types": fin.work_types,
                "recent_companies": fin.recent_companies(10)}

    @app.post("/api/fin/shifts", dependencies=auth)
    async def add_shift(body: ShiftIn):
        amount = k(body.amount)
        if amount is None and body.hours and body.rate:
            amount = round(body.hours * k(body.rate))
        if amount is None:
            from .finance import FinError
            raise FinError("Укажи сумму или часы и ставку")
        return fin.add_shift(body.day, body.company, body.work_type, amount, body.hours, k(body.rate), body.note)

    @app.patch("/api/fin/shifts/{sid}", dependencies=auth)
    async def patch_shift(sid: int, body: ShiftPatch):
        if body.action == "pay":
            return fin.pay_shift(sid, today())
        if body.action == "unpay":
            return fin.unpay_shift(sid)
        return fin.edit_shift(sid, day=body.day, company=body.company, work_type=body.work_type,
                              amount=k(body.amount), hours=body.hours, rate=k(body.rate), note=body.note)

    @app.delete("/api/fin/shifts/{sid}", dependencies=auth)
    async def del_shift(sid: int):
        fin.delete_shift(sid)
        return {"ok": True}

    @app.post("/api/fin/companies/pay", dependencies=auth)
    async def pay_company(body: CompanyPay):
        before = game._achieved(today())
        n, total = fin.pay_company(body.company, today())
        new = [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]
        return {"shifts": n, "total": total, "new_achievements": new}

    # ---------- планы ----------

    @app.get("/api/fin/plans", dependencies=auth)
    async def plans():
        return fin.plans(today())

    @app.post("/api/fin/plans", dependencies=auth)
    async def add_plan(body: PlanIn):
        return fin.add_plan(body.title, k(body.amount), body.due, body.repeat, body.category)

    @app.post("/api/fin/plans/{pid}/pay", dependencies=auth)
    async def pay_plan(pid: int):
        return fin.pay_plan(pid, today())

    @app.delete("/api/fin/plans/{pid}", dependencies=auth)
    async def del_plan(pid: int):
        fin.delete_plan(pid)
        return {"ok": True}

    # ---------- желания ----------

    @app.get("/api/fin/wishes", dependencies=auth)
    async def wishes():
        return {"wishes": fin.wishes(), "balance": fin.balance()}

    @app.post("/api/fin/wishes", dependencies=auth)
    async def add_wish(body: WishIn):
        return fin.add_wish(body.title, k(body.target), today())

    @app.post("/api/fin/wishes/{wid}/money", dependencies=auth)
    async def wish_money(wid: int, body: MoneyIn):
        return fin.wish_add_money(wid, k(body.amount), today())

    @app.post("/api/fin/wishes/{wid}/done", dependencies=auth)
    async def wish_done(wid: int):
        before = game._achieved(today())
        w = fin.wish_done(wid, today())
        new = [a for a in game.full_stats(today())["achievements"] if a["done"] and a["key"] not in before]
        return {"wish": w, "new_achievements": new}

    @app.delete("/api/fin/wishes/{wid}", dependencies=auth)
    async def del_wish(wid: int):
        fin.delete_wish(wid, today())
        return {"ok": True}

    # ---------- накопления ----------

    @app.get("/api/fin/savings", dependencies=auth)
    async def savings():
        return {"savings": fin.savings(), "balance": fin.balance()}

    @app.post("/api/fin/savings", dependencies=auth)
    async def add_saving(body: SavingIn):
        return fin.add_saving(body.title, body.kind)

    @app.post("/api/fin/savings/{sid}/move", dependencies=auth)
    async def saving_move(sid: int, body: MoneyIn):
        return fin.saving_move(sid, k(body.amount), today())

    @app.post("/api/fin/savings/{sid}/value", dependencies=auth)
    async def saving_value(sid: int, body: MoneyIn):
        return fin.saving_value(sid, k(body.amount), today())

    @app.delete("/api/fin/savings/{sid}", dependencies=auth)
    async def del_saving(sid: int):
        fin.archive_saving(sid)
        return {"ok": True}

    # ---------- статистика и настройки ----------

    @app.get("/api/fin/stats", dependencies=auth)
    async def stats(start: date, end: date):
        return fin.stats(start, end)

    @app.put("/api/fin/settings", dependencies=auth)
    async def settings(body: FinSettingsIn):
        fin.save_settings(k(body.daily_limit), k(body.start_balance), body.work_types)
        return await meta()
