"""Тесты обещаний: разбор сроков, XP, пинки, достижения, API."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.auth import Auth
from app.config import Config
from app.db import connect
from app.game import Game, GameError
from app.promise_text import parse_promise
from app.web import create_app

T = date(2026, 11, 5)   # четверг


@pytest.mark.parametrize("text, body, due", [
    ("обещал забрать посылку в пятницу", "Забрать посылку", date(2026, 11, 6)),
    ("Обещал: сходить в кино", "Сходить в кино", None),
    ("пообещала позвонить завтра", "Позвонить", date(2026, 11, 6)),
    ("обещал купить цветы сегодня", "Купить цветы", T),
    ("обещал погулять на выходных", "Погулять", date(2026, 11, 7)),
    ("обещал разобрать фото до 12.11", "Разобрать фото", date(2026, 11, 12)),
    ("обещал поездку 03.01", "Поездку", date(2027, 1, 3)),        # прошедшая дата → следующий год
    ("обещал приготовить ужин в четверг", "Приготовить ужин", date(2026, 11, 12)),  # не сегодня, а через неделю
    ("обещал починить полку через 3 дня", "Починить полку", date(2026, 11, 8)),
    ("обещал выбрать подарок во вторник", "Выбрать подарок", date(2026, 11, 10)),
    ("обещал посмотреть сериал вместе", "Посмотреть сериал вместе", None),
])
def test_parse(text, body, due):
    assert parse_promise(text, T) == (body, due)


@pytest.fixture
def game():
    return Game(connect(":memory:"))


def test_keep_gives_xp_and_fast_bonus(game):
    p = game.add_promise("Посылка", T)
    res = game.keep_promise(p["id"], T)
    assert res["xp"] == 75 and res["fast"]
    assert game.stats().total_xp == 75
    old = game.add_promise("Старое", T - timedelta(days=10))
    assert game.keep_promise(old["id"], T)["xp"] == 50
    with pytest.raises(GameError):
        game.keep_promise(p["id"], T)


def test_undo_reopens_promise(game):
    p = game.add_promise("Посылка", T)
    res = game.keep_promise(p["id"], T)
    qid = res["promise"]["quest_id"]
    out = game.mark(qid, "todo", T)
    assert out["quest"].status == "todo"
    assert game.promise(p["id"], T)["status"] == "open"
    assert game.stats().total_xp == 0


def test_promise_quest_not_counted_as_main(game):
    p = game.add_promise("x", T)
    game.keep_promise(p["id"], T)
    from app import rules
    for i in range(3):   # лимит основных не тронут
        game.add_quest(T, rules.CATEGORIES["study"], f"s{i}", 100)


def test_postpone_counter_and_order(game):
    a = game.add_promise("Без срока", T - timedelta(days=5))
    b = game.add_promise("Просрочено", T - timedelta(days=2), T - timedelta(days=1))
    c = game.add_promise("Завтра", T, T + timedelta(days=1))
    order = [p["text"] for p in game.promises(T)]
    assert order == ["Просрочено", "Завтра", "Без срока"]
    assert game.promise(b["id"], T)["overdue"]
    p = game.set_promise_due(c["id"], T + timedelta(days=3), T)
    assert p["postponed"] == 1
    p = game.set_promise_due(a["id"], T, T)        # назначил срок впервые — это не перенос
    assert p["postponed"] == 0


def test_nudge_hanging_once_per_3_days(game):
    game.add_promise("Кино", T - timedelta(days=4))
    game.add_promise("Свежее", T)
    n = game.promises_to_nudge(T)
    assert [p["text"] for p in n["hanging"]] == ["Кино"]
    game.mark_nudged([n["hanging"][0]["id"]], T)
    assert game.promises_to_nudge(T + timedelta(days=1))["hanging"] == []
    assert len(game.promises_to_nudge(T + timedelta(days=3))["hanging"]) == 2   # и «Свежее» уже подвисло


def test_cancel_and_achievements(game):
    for i in range(5):
        p = game.add_promise(f"p{i}", T)
        res = game.keep_promise(p["id"], T)
    keys = {a["key"] for a in game.full_stats(T)["achievements"] if a["done"]}
    assert {"fastword", "cleanslate"} <= keys
    x = game.add_promise("лишнее", T)
    game.cancel_promise(x["id"], T)
    st = game.promise_stats(T)
    assert st["kept"] == 5 and st["cancelled"] == 1 and st["open"] == 0


def test_api_promises():
    conn = connect(":memory:")
    cfg = Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow"))
    game, auth = Game(conn), Auth(conn)
    c = TestClient(create_app(cfg, game, auth))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": auth.new_code()}).json()["token"]
    p = c.post("/api/promises", json={"text": "обещал позвонить завтра"}).json()
    assert p["text"] == "Позвонить" and p["due_label"] == "завтра"
    r = c.patch(f"/api/promises/{p['id']}", json={"clear_due": True}).json()
    assert r["promise"]["due"] is None
    r = c.patch(f"/api/promises/{p['id']}", json={"action": "keep"}).json()
    assert r["xp"] == 75
    data = c.get("/api/promises").json()
    assert data["open"] == [] and data["stats"]["kept"] == 1
    meta = c.get("/api/meta").json()
    assert any(x["key"] == "promise" and not x["pickable"] for x in meta["categories"])
    assert c.get("/api/settings").json()["remind_promises"] == "10:00"
