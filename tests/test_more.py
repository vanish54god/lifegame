"""Тесты этапов 2–5: шаблоны, магазин, серии, достижения, вход, API."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.auth import Auth
from app.config import Config
from app.db import connect
from app.game import Game, GameError, game_day
from app.web import create_app

C = rules.CATEGORIES
T = date(2026, 11, 10)


@pytest.fixture
def game():
    return Game(connect(":memory:"))


def finish_day(game, day, cats=("study",), xp=200):
    for c in cats:
        q, _ = game.add_quest(day, C[c], "x", xp)
        game.set_status(q.id, "done")


def test_starter_templates_once(game):
    n = len(game.templates())
    assert n == 5
    Game(game.conn)   # повторный запуск не дублирует
    assert len(game.templates()) == 5


def test_template_flow(game):
    tid = game.templates()[0]["id"]
    q, _ = game.add_from_template(T, tid)
    assert q.day == T.isoformat()
    game.delete_template(tid)
    with pytest.raises(GameError):
        game.add_from_template(T, tid)


def test_move_and_edit(game):
    q, _ = game.add_quest(T, C["work"], "Смена", 300)
    game.set_status(q.id, "failed")
    q2 = game.edit_quest(q.id, xp=350, day=T + timedelta(days=1))
    assert q2.status == "todo" and q2.xp == 350 and q2.day == (T + timedelta(days=1)).isoformat()


def test_streaks(game):
    for i in range(3, 0, -1):          # 3 дня подряд до вчера
        finish_day(game, T - timedelta(days=i))
    q, _ = game.add_quest(T, C["study"], "сегодня в процессе", 100)
    assert game.streaks(T) == (3, 3)   # сегодня ещё не сделано — серия не рвётся
    game.set_status(q.id, "done")
    assert game.streaks(T) == (4, 4)
    # дырка в серии
    finish_day(game, T - timedelta(days=10))
    assert game.streaks(T)[1] == 4


def test_failed_main_breaks_streak(game):
    finish_day(game, T - timedelta(days=2))
    q, _ = game.add_quest(T - timedelta(days=1), C["study"], "x", 100)
    game.set_status(q.id, "failed")
    assert game.streaks(T)[0] == 0


def test_shop(game):
    finish_day(game, T, xp=500)                       # 50 монет
    it = game.add_shop_item("Кино", 30, "fun", repeatable=False)
    _, left = game.buy(it["id"])
    assert left == 20
    with pytest.raises(GameError, match="Уже куплено"):
        game.buy(it["id"])
    big = game.add_shop_item("Наушники", 1000)
    with pytest.raises(GameError, match="Не хватает"):
        game.buy(big["id"])
    pid = game.purchases()[0]["id"]
    game.refund(pid)
    assert game.stats().coins == 50
    assert game.stats().level.level == 3              # уровень от покупок не меняется


def test_achievements_via_mark(game):
    q, _ = game.add_quest(T, C["gutv"], "Монтаж", 900)  # ультра хард
    res = game.mark(q.id, "done", T)
    keys = {a["key"] for a in res["new_achievements"]}
    assert {"first", "ultra"} <= keys
    res = game.mark(q.id, "todo", T)
    assert res["new_achievements"] == []


def test_full_stats_shape(game):
    finish_day(game, T, cats=("study", "work"))
    s = game.full_stats(T)
    assert len(s["history"]) == 84 and s["history"][-1]["xp"] == 400
    assert s["by_category"]["work"]["xp30"] == 200
    assert s["streak"] == 1


def test_auth_codes():
    conn = connect(":memory:")
    a = Auth(conn)
    code = a.new_code()
    assert a.exchange("wrong") is None
    tok = a.exchange(code.lower())        # регистр не важен
    assert tok and a.check(tok)
    assert a.exchange(code) is None       # одноразовый
    stored = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert tok not in stored              # в базе только хэш
    a.logout(tok)
    assert not a.check(tok)


def test_bruteforce_burns_codes():
    a = Auth(connect(":memory:"))
    code = a.new_code()
    for _ in range(5):
        a.exchange("AAAAAAAA")
    assert a.exchange(code) is None


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    conn = connect(":memory:")
    cfg = Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow"))
    game, auth = Game(conn), Auth(conn)
    app = create_app(cfg, game, auth)
    c = TestClient(app)
    token = c.post("/api/login", json={"code": auth.new_code()}).json()["token"]
    c.headers["Authorization"] = "Bearer " + token
    c.today = game_day(__import__("datetime").datetime.now(cfg.tz), 5)
    return c


def test_api_requires_auth():
    conn = connect(":memory:")
    cfg = Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow"))
    c = TestClient(create_app(cfg, Game(conn), Auth(conn)))
    assert c.get("/api/stats").status_code == 401
    assert c.get("/api/stats", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = c.get("/")
    assert r.status_code == 200 and "LifeGame" in r.text
    assert "Content-Security-Policy" in r.headers


def test_api_game_flow(client):
    d = client.today.isoformat()
    r = client.post("/api/quests", json={"day": d, "category": "study", "title": "Лаба", "xp": 300})
    assert r.status_code == 200, r.text
    qid = r.json()["quest"]["id"]
    r = client.patch(f"/api/quests/{qid}", json={"status": "done"})
    assert r.json()["level_after"] == 2
    assert client.get(f"/api/day/{d}").json()["stats"]["xp_on_day"] == 300
    # лимит основных
    for i in range(2):
        client.post("/api/quests", json={"day": d, "category": "work", "title": f"w{i}", "xp": 100})
    r = client.post("/api/quests", json={"day": d, "category": "sleep", "title": "s", "xp": 50})
    assert r.status_code == 400 and "основных" in r.json()["detail"]
    # магазин
    it = client.post("/api/shop/items", json={"title": "Кофе", "cost": 20, "kind": "fun", "repeatable": True}).json()
    r = client.post(f"/api/shop/items/{it['id']}/buy")
    assert r.json()["coins"] == 10
    assert client.get("/api/shop").json()["items"][0]["bought"] == 1
    # настройки
    assert client.put("/api/settings", json={"remind_morning": "25:00"}).status_code == 400
    assert client.put("/api/settings", json={"remind_morning": "08:30"}).json()["remind_morning"] == "08:30"
    s = client.get("/api/stats").json()
    assert s["total_xp"] == 300 and any(a["key"] == "shopper" and a["done"] for a in s["achievements"])
