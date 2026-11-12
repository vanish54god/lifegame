"""Тесты: розыск, «иду спать», побочки, статистика, напоминания о дедлайнах."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.bot_extras import deadline_pings, funstats_text, stars_line
from app.db import connect
from app.game import Game
from app.planner import wanted
from app.sidequests import SideError

MSK = ZoneInfo("Europe/Moscow")
T = date(2026, 11, 16)


@pytest.fixture
def game():
    g = Game(connect(":memory:"), MSK)
    g.day_start_hour = 5
    return g


def test_wanted_only_overdue(game):
    p = game.planner
    p.add_task("Свежая", "study", T, deadline=T + timedelta(days=2))
    assert wanted(p, T)["stars"] == 0 and stars_line(wanted(p, T)) is None
    p.add_task("Просрочка 1 день", "study", T - timedelta(days=5), deadline=T - timedelta(days=1))
    p.add_task("Просрочка неделю", "study", T - timedelta(days=20), deadline=T - timedelta(days=8))
    w = wanted(p, T)
    assert w["stars"] == 4 and w["items"][0]["late"] == 8          # 1 + (1+1+1)
    assert "★★★★☆" in stars_line(w)


def test_escape_achievement(game):
    p = game.planner
    ids = [p.add_task(f"Хвост {i}", "study", T - timedelta(days=9), deadline=T - timedelta(days=4))["id"] for i in range(2)]
    assert "escape" not in game._achieved(T)                        # ★★★★ — погоня
    for i in ids:
        game.conn.execute("UPDATE bank_tasks SET status='done', done_day=? WHERE id=?", (T.isoformat(), i))
    game.conn.commit()
    assert "escape" in game._achieved(T)


def test_deadline_pings_7_and_5(game):
    p = game.planner
    p.add_task("Курсовая", "study", T, est_min=600, deadline=T + timedelta(days=7))
    p.add_task("Реферат", "study", T, deadline=T + timedelta(days=5))
    p.add_task("Неважно", "study", T, deadline=T + timedelta(days=6))
    msgs = deadline_pings(game, T)
    assert len(msgs) == 2 and "через неделю" in msgs[0] + msgs[1] and "через 5 дней" in msgs[0] + msgs[1]


def test_sleep(game):
    game.set_setting("bedtime", "00:00")
    r = game.sleep.go(T, datetime(2026, 11, 16, 23, 48, tzinfo=MSK))
    assert r["ontime"] and r["xp"] == 20 and r["streak"] == 1
    assert game.stats().total_xp == 20
    r = game.sleep.go(T, datetime(2026, 11, 17, 0, 40, tzinfo=MSK))  # передумал, лёг позже — XP забирается
    assert not r["ontime"] and game.stats().total_xp == 0
    game.sleep.go(T + timedelta(days=1), datetime(2026, 11, 18, 0, 5, tzinfo=MSK))   # 10 минут форы
    st = game.sleep.stats(T + timedelta(days=1))
    assert st["week_logged"] == 2 and st["week_ontime"] == 1 and st["avg"] == "00:22"
    game.sleep.go(T + timedelta(days=2), datetime(2026, 11, 19, 3, 30, tzinfo=MSK))
    assert "owl" in game._achieved(T + timedelta(days=2))


def test_side_quests(game):
    s = game.side
    assert s.offer(T) is None                                       # пул пуст
    with pytest.raises(SideError):
        s.add(" ")
    a, b = s.add("Позвонить бабушке", 50), s.add("Разобрать фото", 80)
    offered = []
    for i in range(14):                                             # две недели
        d = T + timedelta(days=i)
        o = s.maybe_offer(d, datetime(d.year, d.month, d.day, 23, 0, tzinfo=MSK))
        if o:
            offered.append(d)
    weeks = {d.isocalendar()[1] for d in offered}
    assert len(offered) == 4 and all(sum(1 for d in offered if d.isocalendar()[1] == w) == 2 for w in weeks)
    o = s.offer_today(offered[0])
    r = s.answer(o["id"], True, offered[0])
    q = game.get(r["quest_id"])
    assert q.category.key == "bonus" and q.title.startswith("🎲")
    game.set_status(q.id, "done")
    assert "side1" in game._achieved(offered[0])
    with pytest.raises(SideError):
        s.answer(o["id"], False, offered[0])


def test_funstats(game):
    groups = game.funstats.all(T)
    assert [g["title"] for g in groups][0] == "🎮 Игра"
    assert "Статистика" in funstats_text(game, T)


def test_api_extras(game):
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    a = Auth(game.conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, MSK), game, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    assert c.get("/api/wanted").json()["stars"] == 0
    r = c.post("/api/sleep").json()
    assert "ontime" in r and "level_after" in r
    it = c.post("/api/side", json={"title": "Прогулка без телефона", "xp": 60}).json()
    o = c.post("/api/side/offer").json()
    assert o["item"]["id"] == it["id"]
    assert c.post(f"/api/side/offers/{o['id']}", json={"take": False}).json()["status"] == "skipped"
    assert c.get("/api/side").json()["today"]["status"] == "skipped"
    assert len(c.get("/api/funstats").json()) == 5
