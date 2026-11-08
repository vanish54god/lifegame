"""Тесты ячеек «Обязательного»: подсветка, запас на следующий раз, фонды."""

from datetime import date, timedelta

import pytest

from app.db import connect
from app.envelopes import EnvError
from app.game import Game

T = date(2026, 11, 8)


@pytest.fixture
def game():
    g = Game(connect(":memory:"))
    g.day_start_hour = 5
    g.env.add_expected("Карманные", 1000000, T + timedelta(days=7), "month")
    return g


def item(game, slot, day=T):
    return game.env.ob.item(slot, day)


def income(game, amount, day=T):
    game.fin.add_tx(day, "in", amount, note="доход")
    return game.env.apply(amount, day)


def test_payment_gets_its_own_money_and_turns_green(game):
    f = game.fin
    p = f.add_plan("Проездной", 210000, T + timedelta(days=3), "month")
    assert item(game, f"p{p['id']}")["status"] == "late"            # до следующих денег, а денег нет
    income(game, 1000000)
    it = item(game, f"p{p['id']}")
    assert it["balance"] == 210000 + 100000                          # закрыт + 10% на следующий раз
    assert it["status"] == "ok" and it["covered"] == 1
    ob = game.env.obligations(T)
    assert ob["all_ok"] and ob["gap"] == 0 and ob["green"] == 1


def test_ahead_does_not_take_extra_when_everything_is_covered(game):
    f = game.fin
    p = f.add_plan("VPS", 50000, T + timedelta(days=3), "month")
    income(game, 1000000)
    assert item(game, f"p{p['id']}")["status"] == "double"           # 500 сейчас + 500 на следующий раз
    pl = game.env.plan(1000000, T)
    assert pl["oblig"] == 0 and pl["ahead"] == 0                     # всё с запасом — лишнего не берём


def test_pay_from_slot_and_double_reserve_stays(game):
    f, e = game.fin, game.env
    p = f.add_plan("VPS", 50000, T + timedelta(days=3), "month")
    income(game, 1000000)
    r = f.pay_plan(p["id"], T + timedelta(days=3))
    assert r["took"] == []                                            # хватило своих денег
    it = item(game, f"p{p['id']}", T + timedelta(days=3))
    assert it["balance"] == 50000 and it["status"] == "ok"           # запас стал оплатой на следующий месяц
    assert e.unallocated() == 0


def test_pay_with_shortage_takes_from_buffer_free_then_want(game):
    f, e = game.fin, game.env
    f.add_tx(T, "in", 300000)
    e.apply(300000, T)                                                # платежей нет — всё по конвертам
    want = e.balance("want")
    p = f.add_plan("Штраф", 30000, T + timedelta(days=30))
    r = f.pay_plan(p["id"], T)
    assert [x["src"] for x in r["took"]] == ["want"] and r["took"][0]["amount"] == 30000
    assert e.balance("want") == want - 30000 and e.balance("oblig") == 0


def test_manual_put_and_take(game):
    f, e = game.fin, game.env
    income(game, 1000000)
    p = f.add_plan("Подарок маме", 300000, T + timedelta(days=40))
    me = e.balance("me")
    it = e.ob.put(f"p{p['id']}", 100000, "me", T)
    assert it["balance"] == 100000 and e.balance("me") == me - 100000
    with pytest.raises(EnvError):
        e.ob.put(f"p{p['id']}", 10**9, "me", T)
    it = e.ob.take(f"p{p['id']}", 40000, "free", T)
    assert it["balance"] == 60000 and e.unallocated() == 40000


def test_fund_is_filled_by_schedule(game):
    e = game.env
    fd = e.ob.add_fund("Новый год", 1000000, T + timedelta(days=50), T, repeat="year")
    assert fd["need"] == 140000                                       # 10 000 × 7 дней / 50 дней
    pl = e.plan(1000000, T)
    assert pl["funds"] == 140000
    income(game, 1000000)
    it = item(game, fd["slot"])
    assert it["balance"] >= 140000 and it["status"] == "progress"


def test_fund_spending_matches_by_category_and_date(game):
    f, e = game.fin, game.env
    fd = e.ob.add_fund("ДР Сони", 500000, T + timedelta(days=10), T)
    e.ob.put(fd["slot"], 500000, "free", T) if e.unallocated() >= 500000 else None
    income(game, 1000000)
    e.ob.put(fd["slot"], max(0, 500000 - item(game, fd["slot"])["balance"]), "me", T)
    assert item(game, fd["slot"])["status"] == "ok"
    t = f.add_tx(T + timedelta(days=9), "out", 450000, "gifts", "подарок Соне")
    assert t["envelope"] == "oblig" and t["slot"] == fd["slot"] and t["env_emoji"] == "🎁"
    assert item(game, fd["slot"], T + timedelta(days=9))["balance"] == 50000
    e.set_tx_envelope(t["id"], "rel")                                  # передумал — из «Отношений»
    assert item(game, fd["slot"], T + timedelta(days=9))["balance"] == 500000


def test_fund_lifecycle_task_ontime_and_rollover(game):
    e = game.env
    fd = e.ob.add_fund("Новый год", 300000, T + timedelta(days=20), T, repeat="year")
    income(game, 1000000)
    e.ob.put(fd["slot"], 300000 - item(game, fd["slot"])["balance"], "me", T)
    e.ob.sync(T + timedelta(days=6))                                   # за 14 дней — задача в банк
    assert any("Новый год" in t["title"] for t in game.planner.tasks(T))
    assert "fund_ontime" in game._achieved(T + timedelta(days=6))
    game.fin.add_tx(T + timedelta(days=20), "out", 250000, "gifts", "подарки")
    e.ob.sync(T + timedelta(days=28))                                  # прошла дата + неделя
    f = e.ob.fund(fd["id"])
    assert f["active"] == 1 and f["due"] == (T + timedelta(days=20)).replace(year=2027).isoformat()
    assert item(game, fd["slot"], T + timedelta(days=28))["balance"] == 50000   # остаток — на следующий год


def test_one_time_fund_leftover_goes_back(game):
    e = game.env
    income(game, 1000000)
    e.move("me", "oblig", 200000, T)                                   # в общий запас «Обязательного»
    fd = e.ob.add_fund("Поездка", 200000, T + timedelta(days=5), T, remind=False)
    left = item(game, fd["slot"])["balance"]
    assert left == 200000                                              # общий запас сам ушёл в фонд
    free = e.unallocated()
    e.ob.sync(T + timedelta(days=13))
    assert e.ob.fund(fd["id"])["active"] == 0 and e.unallocated() == free + 200000


def test_legacy_oblig_money_is_distributed(game):
    f, e = game.fin, game.env
    f.add_tx(T, "in", 500000)
    e.move("free", "oblig", 300000, T)                                 # как было раньше: просто в «Обязательное»
    p = f.add_plan("Интернет", 70000, T + timedelta(days=4), "month")
    ob = e.obligations(T)
    it = next(i for i in ob["items"] if i["slot"] == f"p{p['id']}")
    assert it["status"] == "double" and ob["buffer"] == 300000 - 140000


def test_moving_out_of_oblig_and_reset(game):
    f, e = game.fin, game.env
    p1 = f.add_plan("Скоро", 100000, T + timedelta(days=2), "month")
    p2 = f.add_plan("Потом", 100000, T + timedelta(days=25), "month")
    income(game, 1000000)
    before1 = item(game, f"p{p1['id']}")["balance"]
    e.move("oblig", "me", item(game, f"p{p2['id']}")["balance"], T)    # забираем — сначала дальнее
    assert item(game, f"p{p1['id']}")["balance"] == before1
    assert item(game, f"p{p2['id']}")["balance"] == 0
    e.reset(T)
    assert all(v == 0 for v in e.ob.balances().values())


def test_all_green_achievement(game):
    f = game.fin
    for i, n in enumerate(("Проездной", "VPS", "Связь")):
        f.add_plan(n, 30000, T + timedelta(days=2 + i), "month")
    income(game, 1000000)
    got = game._achieved(T)
    assert "allgreen" in got and "double" in got


def test_api_obligations_and_funds():
    from datetime import date as _d
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    today = _d.fromisoformat(c.get("/api/meta").json()["today"])
    c.post("/api/fin/quick", json={"text": "+20000 карманные"})
    p = c.post("/api/fin/plans", json={"title": "Связь", "amount": 600, "due": str(today + timedelta(days=3)),
                                       "repeat": "month"}).json()
    f = c.post("/api/fin/funds", json={"title": "ДР Сони", "target": 5000, "due": str(today + timedelta(days=40)),
                                       "repeat": "year"}).json()
    assert f["slot"] == f"f{f['id']}" and f["status"] == "progress"
    assert any(x["slot"] == f["slot"] for x in c.get("/api/fin/meta").json()["funds"])
    e = c.get("/api/fin/envelopes").json()
    assert e["plan"]["oblig_now"] == 60000 and e["plan"]["funds"] > 0
    c.post("/api/fin/envelopes/apply", json={})
    e = c.get("/api/fin/envelopes").json()
    assert e["oblig_green"] >= 1 and e["oblig_gap"] == 0
    r = c.post(f"/api/fin/oblig/{f['slot']}/put", json={"amount": 1000, "src": "me"}).json()
    assert r["balance"] >= 100000 and "new_achievements" in r
    assert c.post(f"/api/fin/oblig/{f['slot']}/put", json={"amount": 10**8, "src": "me"}).status_code == 400
    assert c.post(f"/api/fin/oblig/{f['slot']}/take", json={"amount": 500, "src": "free"}).status_code == 200
    t = c.post("/api/fin/tx", json={"kind": "out", "amount": 300, "category": "gifts", "envelope": f["slot"]}).json()
    assert t["env_emoji"] == "🎁" and t["slot"] == f["slot"]
    pay = c.post(f"/api/fin/plans/{p['id']}/pay").json()
    assert pay["took"] == [] and "new_achievements" in pay
    assert c.put("/api/fin/envelopes/settings", json={"ahead_pct": 20}).json()["ahead_pct"] == 20
    assert c.patch(f"/api/fin/funds/{f['id']}", json={"target": 6000}).json()["target"] == 600000
    assert c.delete(f"/api/fin/funds/{f['id']}").json()["ok"]
    assert c.post("/api/fin/oblig/zzz/put", json={"amount": 1, "src": "me"}).status_code == 400


def test_funds_and_ahead_leave_money_for_life(game):
    f, e = game.fin, game.env
    f.add_plan("Проездной", 210000, T + timedelta(days=3), "month")
    e.ob.add_fund("Новый год", 3000000, T + timedelta(days=20), T)      # огромный фонд — график съел бы всё
    p = e.plan(900000, T)
    assert p["oblig_now"] == 210000                                     # срочный платёж — целиком
    assert p["funds"] + p["ahead"] <= (900000 - 210000) // 2            # остальным — не больше половины
    assert p["funds_short"] > 0 and p["me"] > 0


def test_quarterly_payment_saves_by_schedule_and_flags_behind(game):
    f, e = game.fin, game.env
    # проездной раз в 3 месяца, платить через 38 дней, а отложено 0 — уже отстаём от графика
    p = f.add_plan("Проездной", 900000, T + timedelta(days=38), "month3", "transport", today=T - timedelta(days=52))
    it = item(game, f"p{p['id']}")
    assert it["status"] == "late" and not it["now"] and it["behind"] > 0
    assert it["need"] == 900000 * 7 // 38 // 100 * 100 + 100            # догоняем: 7 дней из 38
    ob = e.obligations(T)
    assert ob["gap"] == 0 and ob["behind"] == it["behind"]               # не срочно, но красное
    income(game, 1000000)
    assert item(game, f"p{p['id']}")["balance"] >= it["need"]
    # оплатил — следующий через 3 месяца, копим с нуля и это не «отстаём»
    f.add_tx(T, "in", 1000000)
    e.ob.put(f"p{p['id']}", 900000 - item(game, f"p{p['id']}")["balance"], "free", T)
    f.pay_plan(p["id"], T + timedelta(days=38))
    nxt = f.plan(p["id"])
    assert nxt["due"] == "2027-03-16"
    assert item(game, f"p{p['id']}", T + timedelta(days=38))["status"] == "progress"


def test_half_year_goal_is_single_payment(game):
    f, e = game.fin, game.env
    p = f.add_plan("VPN", 300000, T + timedelta(days=100), "month6", "subs", today=T)
    it = item(game, f"p{p['id']}")
    assert it["goal"] == 300000 and it["status"] == "progress"
    assert e.obligations(T)["month_total"] == 50000                      # 3000 / 6 мес


def test_redistribute_everything_after_new_payments(game):
    f, e = game.fin, game.env
    income(game, 1000000)                                              # платежей нет — всё по конвертам
    assert e.balance("oblig") == 0
    p = f.add_plan("Проездной", 210000, T + timedelta(days=3), "month")
    fd = e.ob.add_fund("ДР Сони", 300000, T + timedelta(days=30), T)
    saved = sum(s["current"] for s in f.savings())
    before = e.balances()
    pr = e.redistribute(T)                                             # только показать
    assert e.balances() == before
    assert pr["total"] == sum(before.values()) + e.unallocated()
    assert next(i for i in pr["items"] if i["slot"] == f"p{p['id']}")["after"] >= 210000
    r = e.redistribute(T, do=True)
    assert item(game, f"p{p['id']}")["status"] in ("ok", "double")
    assert item(game, fd["slot"])["balance"] > 0
    assert sum(e.balances().values()) == pr["total"] and e.unallocated() == 0   # ни копейки не потерялось
    assert sum(s["current"] for s in f.savings()) == saved                      # копилки не тронуты
    assert r["obligations"]["gap"] == 0
