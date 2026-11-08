"""Тесты конвертов, динамического лимита и наград."""

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
    return g


def test_plan_obligatory_first_then_save_then_shares(game):
    f, e = game.fin, game.env
    f.add_plan("VPS", 50000, T + timedelta(days=5), "month")
    f.add_plan("Подписка", 30000, T + timedelta(days=60))            # далеко — не резервируем
    p = e.plan(1000000, T)                                             # 10 000 ₽
    assert p["oblig"] == 50000
    assert p["save"] == 95000                                          # 10% от 9 500
    assert (p["me"], p["rel"], p["want"]) == (342000, 342000, 171000)  # 40/40/20 от 8 550
    assert p["oblig"] + p["save"] + p["me"] + p["rel"] + p["want"] == 1000000


def test_apply_and_balances(game):
    f, e = game.fin, game.env
    f.add_tx(T, "in", 1000000, note="зарплата")
    assert e.unallocated() == 1000000
    res = e.apply(1000000, T)
    assert {a["key"] for a in res["new_achievements"]} >= {"envelope1"}
    assert e.unallocated() == 0
    assert f.balance() == 900000                                       # 10% ушло в копилку
    assert f.savings()[0]["title"] == "Подушка" and f.savings()[0]["current"] == 100000
    t = f.add_tx(T, "out", 50000, note="кофе")                         # кафе → «Отношения»
    assert t["envelope"] == "rel" and e.balance("rel") == 360000 - 50000
    e.set_tx_envelope(t["id"], "me")
    assert e.balance("rel") == 360000 and e.balance("me") == 310000
    with pytest.raises(EnvError):
        e.apply(1, T)                                                  # больше неразложенного нет


def test_dynamic_limit_and_reward(game):
    f, e = game.fin, game.env
    e.add_expected("Карманные", 500000, T + timedelta(days=10), "month")
    f.add_tx(T - timedelta(days=1), "in", 1000000, note="зарплата")
    e.apply(1000000, T - timedelta(days=1))
    lim_y = e.today_limit(T - timedelta(days=1))                       # (Я+Отношения) / 11 дней
    assert lim_y == (360000 + 360000) // 11 // 100 * 100
    f.add_tx(T - timedelta(days=1), "out", 30000, note="кола")        # потратил меньше лимита
    rewards = e.settle(T)
    assert len(rewards) == 1 and rewards[0]["saved"] == lim_y - 30000
    assert game.stats().total_xp == 20
    assert e.settle(T) == []                                           # повторно не начисляет
    b = e.budget(T)
    assert b["days_left"] == 10 and b["next_income"]["title"] == "Карманные"
    assert b["limit"] == (720000 - 30000) // 10 // 100 * 100           # сэкономил вчера — сегодня больше


def test_overspend_no_reward_and_forecast(game):
    f, e = game.fin, game.env
    f.add_tx(T - timedelta(days=1), "in", 100000, note="+")
    e.apply(100000, T - timedelta(days=1))
    e.today_limit(T - timedelta(days=1))
    f.add_tx(T - timedelta(days=1), "out", 80000, note="кино")
    assert e.settle(T) == []
    b = e.budget(T)
    assert b["forecast"] < b["spendable"] + b["want"]


def test_expected_monthly_rolls(game):
    e = game.env
    e.add_expected("Карманные", 500000, T - timedelta(days=3), "month")
    e.add_expected("Разовое старое", 100, T - timedelta(days=3))
    ex = e.expected(T)
    assert len(ex) == 1 and ex[0]["next"] == "2026-12-05"


def test_move_and_save(game):
    f, e = game.fin, game.env
    f.add_tx(T, "in", 100000, note="+")
    e.apply(100000, T)
    e.move("me", "want", 10000, T)
    assert e.balance("want") == 18000 + 10000
    e.move("want", "save", 5000, T)
    assert f.savings()[0]["current"] == 10000 + 5000
    with pytest.raises(EnvError):
        e.move("me", "rel", 10**9, T)


def test_settings_and_learning(game):
    f, e = game.fin, game.env
    with pytest.raises(EnvError):
        e.save_settings(shares={"me": 50, "rel": 30, "want": 30})
    e.save_settings(shares={"me": 30, "rel": 50, "want": 20}, save_pct=15)
    assert e.settings()["shares"]["rel"] == 50
    for i in range(12):
        d = T - timedelta(days=i + 1)
        f.add_tx(d, "out", 10000, note="кола")           # Я
        f.add_tx(d, "out", 30000, note="кафе")           # Отношения
    ls = e.learned_shares(T)
    assert ls["shares"] == {"me": 25, "rel": 75, "want": 0}


def test_plan_payment_uses_oblig(game):
    f, e = game.fin, game.env
    p = f.add_plan("VPS", 50000, T + timedelta(days=2))
    f.add_tx(T, "in", 200000, note="+")
    e.apply(200000, T)
    assert e.balance("oblig") == 50000
    f.pay_plan(p["id"], T)
    assert e.balance("oblig") == 0 and e.unallocated() == 0


def test_money_quest_protected(game):
    f, e = game.fin, game.env
    f.add_tx(T - timedelta(days=1), "in", 100000, note="+")
    e.apply(100000, T - timedelta(days=1))
    e.today_limit(T - timedelta(days=1))
    e.settle(T)
    qid = game.conn.execute("SELECT id FROM quests WHERE category='money'").fetchone()[0]
    from app.game import GameError
    with pytest.raises(GameError):
        game.mark(qid, "todo", T)


def test_api_envelopes():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    g.day_start_hour = 5
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    today = date.fromisoformat(c.get("/api/meta").json()["today"])
    c.post("/api/fin/quick", json={"text": "+10000 зарплата"})
    e = c.get("/api/fin/envelopes").json()
    assert not e["on"] and e["unallocated"] == 1000000 and e["plan"]["save"] == 100000
    r = c.post("/api/fin/envelopes/apply", json={}).json()
    assert r["amount"] == 1000000
    c.post("/api/fin/expected", json={"title": "Карманные", "amount": 5000,
                                      "day": (today + timedelta(days=5)).isoformat(), "repeat": "month"})
    e = c.get("/api/fin/envelopes").json()
    assert e["on"] and e["days_left"] == 5 and e["limit"] == (360000 + 360000) // 5 // 100 * 100
    t = c.post("/api/fin/quick", json={"text": "кофе 300"}).json()
    assert t["envelope"] == "rel"
    assert c.patch(f"/api/fin/tx/{t['id']}", json={"envelope": "want"}).json()["envelope"] == "want"
    assert c.post("/api/fin/envelopes/move", json={"src": "me", "dst": "save", "amount": 100}).status_code == 200
    assert c.put("/api/fin/envelopes/settings", json={"shares": {"me": 50, "rel": 50, "want": 10}}).status_code == 400
    assert c.put("/api/fin/envelopes/settings", json={"shares": {"me": 30, "rel": 50, "want": 20}}).json()["shares"]["rel"] == 50
    assert c.put("/api/settings/show", json={"show_habits": True}).json()["show"]["show_habits"] is True


def test_backup_encrypted(tmp_path):
    import pyzipper
    from datetime import datetime
    from app.backup import make_backup
    db = tmp_path / "game.db"
    g = Game(connect(db))
    g.fin.add_tx(T, "in", 100000, note="+")
    path = make_backup(g.conn, str(db), "секрет123", datetime(2026, 11, 8, 4, 30))
    assert path.exists() and path.name == "lifegame-2026-11-08_0430.zip"
    with pyzipper.AESZipFile(path) as z:
        with pytest.raises(RuntimeError):
            z.read("game.db")                                  # без пароля не открыть
        z.setpassword("секрет123".encode())
        data = z.read("game.db")
    restored = tmp_path / "restored.db"
    restored.write_bytes(data)
    assert Game(connect(restored)).fin.balance() == 100000
    with pytest.raises(ValueError):
        make_backup(g.conn, str(db), "", datetime(2026, 11, 8))


def test_static_no_cache():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), Game(conn), Auth(conn)))
    assert c.get("/app.js").headers["cache-control"] == "no-cache"
    assert c.get("/finance.js").headers["cache-control"] == "no-cache"
