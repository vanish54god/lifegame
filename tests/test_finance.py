"""Тесты финансов."""

from datetime import date, timedelta

import pytest

from app.db import connect
from app.finance import FinError, parse_money, parse_shift_pay, rub, guess_cat
from app.game import Game

T = date(2026, 11, 5)


@pytest.mark.parametrize("text, expected", [
    ("кофе 250", ("out", 25000, "кофе")),
    ("250 кофе", ("out", 25000, "кофе")),
    ("такси 1.5к", ("out", 150000, "такси")),
    ("продукты 1 250,50", ("out", 125050, "продукты")),
    ("+30000 зарплата", ("in", 3000000, "зарплата")),
    ("зарплата +30000", ("in", 3000000, "зарплата")),
    ("получил 5000 за монтаж", ("in", 500000, "за монтаж")),
    ("обед 450₽", ("out", 45000, "обед")),
    ("метро 62 руб", ("out", 6200, "метро")),
    ("1200", ("out", 120000, "")),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["привет", "как дела", "встретиться в кино с Соней и пойти гулять долго-долго " * 3])
def test_not_money(text):
    assert parse_money(text) is None


def test_parse_shift_pay():
    assert parse_shift_pay("8ч по 400") == (8.0, 40000, 320000)
    assert parse_shift_pay("8 x 400") == (8.0, 40000, 320000)
    assert parse_shift_pay("10,5 по 300") == (10.5, 30000, 315000)
    assert parse_shift_pay("3200") == (None, None, 320000)
    assert parse_shift_pay("3.5к") == (None, None, 350000)
    with pytest.raises(FinError):
        parse_shift_pay("много")


def test_rub_and_guess():
    assert rub(150000) == "1 500 ₽" and rub(12345) == "123,45 ₽" and rub(-5000) == "−50 ₽"
    assert guess_cat("кофе с булкой", "out") == "cafe"
    assert guess_cat("Пятёрочка", "out") == "food"
    assert guess_cat("монтаж ролика", "in") == "freelance"
    assert guess_cat("непонятное", "out") == "other"


@pytest.fixture
def fin():
    return Game(connect(":memory:")).fin


def test_balance_and_limit(fin):
    fin.save_settings(daily_limit=100000, start_balance=500000)
    fin.add_tx(T, "out", 25000, note="кофе")
    fin.add_tx(T, "in", 300000, note="зарплата")
    assert fin.balance() == 500000 - 25000 + 300000
    assert fin.spent_today(T) == 25000
    t = fin.add_tx(T, "out", 30000, note="что-то")
    assert t["category"] == "other"
    assert fin.set_tx_category(t["id"], "fun")["category"] == "fun"
    with pytest.raises(FinError):
        fin.set_tx_category(t["id"], "salary")      # доходная категория для траты нельзя
    fin.delete_tx(t["id"])
    assert fin.spent_today(T) == 25000


def test_shifts_and_companies(fin):
    a = fin.add_shift(T - timedelta(days=2), "Ивент Про", "Хелпер", 320000, 8, 40000)
    fin.add_shift(T - timedelta(days=1), "Ивент Про", "Менеджер", 500000)
    fin.add_shift(T, "Студия", "Трансляция", 700000)
    assert fin.expected_salary() == 1520000
    fin.pay_shift(a["id"], T)
    comp = {c["company"]: c for c in fin.companies()}
    assert comp["Ивент Про"]["owed"] == 500000 and comp["Ивент Про"]["paid"] == 320000
    assert comp["Ивент Про"]["shifts"] == 2 and comp["Ивент Про"]["hours"] == 8
    assert fin.balance() == 320000                    # оплата упала в доходы
    n, s = fin.pay_company("Ивент Про", T)
    assert (n, s) == (1, 500000) and fin.expected_salary() == 700000
    with pytest.raises(FinError):
        fin.pay_company("Ивент Про", T)
    # отмена оплаты — деньги уходят из доходов
    fin.unpay_shift(a["id"])
    assert fin.balance() == 500000
    assert fin.recent_companies()[0] == "Студия"


def test_plans_repeat_and_limit(fin):
    fin.save_settings(daily_limit=50000)
    p = fin.add_plan("VPS", 50000, date(2026, 1, 31), "month")
    fin.pay_plan(p["id"], T)
    assert fin.plan(p["id"])["due"] == "2026-02-28"   # 31 января + месяц → 28 февраля
    assert fin.spent_today(T) == 0                    # плановая трата не в лимите
    once = fin.add_plan("Подарок", 300000, T + timedelta(days=1))
    assert [x["title"] for x in fin.digest(T)] == ["VPS", "Подарок"]   # VPS просрочен, подарок завтра
    fin.pay_plan(once["id"], T)
    assert not fin.plan(once["id"])["active"]


def test_wishes(fin):
    fin.save_settings(start_balance=1000000)
    w = fin.add_wish("Наушники", 2500000, T)
    w = fin.wish_add_money(w["id"], 1000000, T)
    assert w["saved"] == 1000000 and w["progress"] == 40
    assert fin.balance() == 0                         # отложенное не «свободные» деньги
    with pytest.raises(FinError):
        fin.wish_add_money(w["id"], -2000000, T)
    fin.wish_done(w["id"], T)
    assert fin.balance() == 0 and fin.wish(w["id"])["done"]
    assert fin.counts()["wishes_done"] == 1


def test_savings_and_invest(fin):
    s = fin.add_saving("Подушка")
    fin.saving_move(s["id"], 1000000, T)
    assert fin.saving(s["id"])["current"] == 1000000
    inv = fin.add_saving("Акции", "invest")
    fin.saving_move(inv["id"], 500000, T)
    fin.saving_value(inv["id"], 560000, T)
    x = fin.saving(inv["id"])
    assert x["current"] == 560000 and x["profit"] == 60000
    fin.saving_move(inv["id"], 100000, T)            # докупил — стоимость тоже растёт
    assert fin.saving(inv["id"])["current"] == 660000
    with pytest.raises(FinError):
        fin.saving_value(s["id"], 1, T)
    with pytest.raises(FinError):
        fin.archive_saving(s["id"])


def test_stats_and_limit_streak(fin):
    fin.save_settings(daily_limit=100000)
    for i in range(1, 9):
        fin.add_tx(T - timedelta(days=i), "out", 50000, note="обед")
    fin.add_tx(T - timedelta(days=3), "in", 1000000, note="зарплата")
    fin.add_shift(T - timedelta(days=3), "Ивент Про", "Хелпер", 300000, 6, 50000)
    st = fin.stats(T - timedelta(days=6), T)
    assert st["expense"] == 300000 and st["income"] == 1000000
    assert st["by_category"][0]["key"] == "salary"
    assert len(st["days"]) == 7 and st["shifts_total"] == 300000
    assert fin.limit_streak(T) == 8


def test_finance_achievements():
    g = Game(connect(":memory:"))
    g.fin.add_shift(T, "Ивент Про", "Хелпер", 100000)
    keys = {a["key"] for a in g.full_stats(T)["achievements"] if a["done"]}
    assert "shift1" in keys
    for i in range(5):
        g.fin.add_shift(T, "Студия", "Монтаж", 100000)
    g.fin.pay_company("Студия", T)
    keys = {a["key"] for a in g.full_stats(T)["achievements"] if a["done"]}
    assert "payday" in keys


def test_api_finance():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    assert c.get("/api/fin/overview").status_code == 200
    assert c.post("/api/fin/quick", json={"text": "кофе 250"}).json()["category"] == "cafe"
    assert c.post("/api/fin/quick", json={"text": "привет"}).status_code == 400
    s = c.post("/api/fin/shifts", json={"day": "2026-11-04", "company": "А", "work_type": "Хелпер",
                                        "hours": 8, "rate": 400}).json()
    assert s["amount"] == 320000
    assert c.post("/api/fin/shifts", json={"day": "2026-11-04", "company": "А", "work_type": "Х"}).status_code == 400
    assert c.post("/api/fin/companies/pay", json={"company": "А"}).json()["total"] == 320000
    p = c.post("/api/fin/plans", json={"title": "VPS", "amount": 500, "due": "2026-11-06", "repeat": "month"}).json()
    assert c.post(f"/api/fin/plans/{p['id']}/pay").json()["due"] == "2026-12-06"
    w = c.post("/api/fin/wishes", json={"title": "Наушники", "target": 1000}).json()
    assert c.post(f"/api/fin/wishes/{w['id']}/money", json={"amount": 500}).json()["progress"] == 50
    sv = c.post("/api/fin/savings", json={"title": "Акции", "kind": "invest"}).json()
    c.post(f"/api/fin/savings/{sv['id']}/move", json={"amount": 1000})
    assert c.post(f"/api/fin/savings/{sv['id']}/value", json={"amount": 1100}).json()["profit"] == 10000
    st = c.get("/api/fin/stats", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert st["shifts_total"] == 320000
    assert c.put("/api/fin/settings", json={"daily_limit": 1500, "work_types": ["Хелпер", "vMix"]}).json()["work_types"] == ["Хелпер", "vMix"]
    # без входа — нельзя
    assert TestClient(c.app).get("/api/fin/overview").status_code == 401


def test_checkin_logic():
    import time
    g = Game(connect(":memory:"))
    g.last_activity = time.time() - 4 * 3600
    assert g.checkin_due(15) and not g.checkin_due(8) and not g.checkin_due(23)
    g.checkin_sent()
    assert not g.checkin_due(15)                     # следующий не раньше чем через 3 ч
    g.last_checkin -= 4 * 3600
    assert g.checkin_due(15)
    g.checkin_sent(); g.last_checkin -= 4 * 3600
    assert not g.checkin_due(15)                     # два без ответа подряд — замолкаем
    g.touch()
    assert not g.checkin_due(15)                     # только что был активен
    g.set_setting("checkin_on", "0"); g.last_activity -= 5 * 3600
    assert not g.checkin_due(15)


def test_backdate_spending(fin):
    fin.save_settings(daily_limit=100000)
    t = fin.add_tx(T, "out", 50000, note="кофе")
    t = fin.set_tx_day(t["id"], T - timedelta(days=1), T)
    assert t["day"] == "2026-11-04"
    assert fin.spent_today(T) == 0 and fin.spent_today(T - timedelta(days=1)) == 50000   # лимит пересчитался
    with pytest.raises(FinError):
        fin.set_tx_day(t["id"], T + timedelta(days=1), T)          # в будущее нельзя
    s = fin.add_shift(T, "А", "Хелпер", 100000)
    paid = fin.pay_shift(s["id"], T)
    with pytest.raises(FinError):
        fin.set_tx_day(paid["tx_id"], T - timedelta(days=1), T)    # оплату смены — только через смены


def test_api_backdate():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    today = date.fromisoformat(c.get("/api/meta").json()["today"])
    y = (today - timedelta(days=1)).isoformat()
    t = c.post("/api/fin/quick", json={"text": "кофе 250", "day": y}).json()
    assert t["day"] == y
    t2 = c.patch(f"/api/fin/tx/{t['id']}", json={"day": (today - timedelta(days=3)).isoformat()}).json()
    assert t2["day"] == (today - timedelta(days=3)).isoformat() and t2["category"] == "cafe"
    assert c.patch(f"/api/fin/tx/{t['id']}", json={"day": (today + timedelta(days=1)).isoformat()}).status_code == 400
    assert c.post("/api/fin/tx", json={"kind": "out", "amount": 100, "day": (today + timedelta(days=2)).isoformat()}).status_code == 400
