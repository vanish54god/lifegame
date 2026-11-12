"""Тесты сюжетных миссий."""

from datetime import date, timedelta

import pytest

from app.db import connect
from app.game import Game
from app.story import StoryError

T = date(2026, 11, 12)


@pytest.fixture
def game():
    g = Game(connect(":memory:"))
    g.day_start_hour = 5
    return g


def xp(g):
    return g.stats().total_xp


def test_mission_steps_and_final(game):
    st = game.story
    m = st.add("Сложить полномочия старосты", T, 1000, why="Закрыть семестр без хвостов",
               steps=["Встреча с куратором", "Разговор с группой", "Деканат"])
    assert m["steps_total"] == 3 and m["next_step"]["title"] == "Встреча с куратором"
    st.toggle_step(m["steps"][0]["id"], T)
    assert xp(game) == 100
    m = st.toggle_step(m["steps"][0]["id"], T)                     # отметил по ошибке — XP обратно
    assert xp(game) == 0 and m["steps_done"] == 0
    for s in m["steps"]:
        st.toggle_step(s["id"], T)
    r = st.complete(m["id"], T + timedelta(days=1), "Сложил полномочия. Теперь — сессия без хвостов")
    assert r["status"] == "done" and r["chapter"] == "Глава 1" and r["respect"] == 1
    assert xp(game) == 1300
    got = game._achieved(T + timedelta(days=1))
    assert {"story1", "exhale"} <= got
    with pytest.raises(StoryError):
        st.complete(m["id"], T)
    with pytest.raises(StoryError):
        st.delete(m["id"])                                          # пройденная — в хронике навсегда
    with pytest.raises(Exception):
        game.delete_quest(r["quest_id"])


def test_pause_not_fail_and_chronicle_by_chapters(game):
    st = game.story
    a = st.add("Сдать на права", T, 2000, steps=["Теория", "Площадка"])
    st.set_paused(a["id"], True)
    assert st.missions("paused")[0]["id"] == a["id"]
    st.toggle_step(a["steps"][0]["id"], T)                          # продолжил — снова активна
    assert st.get(a["id"])["status"] == "active"
    b = st.add("Первая трансляция на vMix", T)
    st.complete(b["id"], T, "Отработал без единого чёрного кадра")
    st.new_chapter("Глава 2: Второй курс, зима", T + timedelta(days=30))
    st.complete(a["id"], T + timedelta(days=40))
    ch = st.chronicle(T + timedelta(days=40))
    assert [c["title"] for c in ch] == ["Глава 2: Второй курс, зима", "Глава 1"]
    assert ch[0]["current"] and ch[0]["missions"][0]["title"] == "Сдать на права"
    assert ch[1]["missions"][0]["outro"] == "Отработал без единого чёрного кадра"
    assert "chapter1" in game._achieved(T + timedelta(days=40))


def test_delete_keeps_earned_step_xp(game):
    st = game.story
    m = st.add("Ремонт в комнате", T, steps=["Покраска"])
    st.toggle_step(m["steps"][0]["id"], T)
    st.delete(m["id"])
    assert xp(game) == 100 and st.missions() == []


def test_api_story():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    m = c.post("/api/story", json={"title": "Сложить полномочия", "xp": 1000, "steps": ["Куратор", "Группа"]}).json()
    assert c.post("/api/story", json={"title": " "}).status_code == 400
    r = c.post(f"/api/story/steps/{m['steps'][0]['id']}/toggle").json()
    assert r["steps_done"] == 1 and "level_after" in r
    m2 = c.post(f"/api/story/{m['id']}/steps", json={"title": "Деканат", "xp": 150}).json()
    assert m2["steps_total"] == 3
    r = c.post(f"/api/story/{m['id']}/complete", json={"outro": "Выдохнул"}).json()
    assert r["level_after"] > r["level_before"] and any(x["key"] == "story1" for x in r["new_achievements"])
    ch = c.get("/api/story/chronicle").json()
    assert ch["respect"] == 1 and ch["chapters"][0]["missions"][0]["outro"] == "Выдохнул"
    assert c.post("/api/story/chapter", json={"title": "Глава 2"}).json()["title"] == "Глава 2"
    assert c.get("/api/story").json()["chapter"]["title"] == "Глава 2"
