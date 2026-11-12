"""Тесты навыков и брифинга / итогов недели."""

from datetime import date, timedelta

import pytest

from app import rules
from app.bot_weekly import brief_text, recap_text
from app.db import connect
from app.game import Game
from app.skills import level_of, skill_of

T = date(2026, 11, 16)    # понедельник


@pytest.fixture
def game():
    g = Game(connect(":memory:"))
    g.day_start_hour = 5
    return g


def done(g, day, cat, title, xp):
    q, _ = g.add_quest(day, rules.CATEGORIES[cat], title, xp)
    g.set_status(q.id, "done")
    g.conn.execute("UPDATE quests SET day=? WHERE id=?", (day.isoformat(), q.id))
    g.conn.commit()


def test_skill_mapping_and_levels():
    assert skill_of("habit", "🔁 Спорт") == "body" and skill_of("habit", "Вода 2 л") == "will"
    assert skill_of("study", "x") == "mind" and skill_of("bonus", "x") is None
    assert level_of(0, 120) == (0, 0, 120)
    assert level_of(480, 120)[0] == 2 and level_of(479, 120)[0] == 1


def test_skills_grow_and_ups_announced_once(game):
    assert game.skills.ups(T) == []                            # первый раз тихо
    done(game, T, "study", "Курсовая", 500)
    ups = game.skills.ups(T)
    assert [u["key"] for u in ups] == ["mind"] and ups[0]["level"] == 2 and ups[0]["gain"] == 2
    assert game.skills.ups(T) == []                            # второй раз — уже показано
    mind = next(s for s in game.skills.all(T) if s["key"] == "mind")
    assert mind["week_xp"] == 500 and 0 <= mind["pct"] <= 100


def test_brief_collects_week(game):
    from tests.test_schedule import ev, ics
    game.schedule.apply(ics(ev("kr@x", "711 Кратные ряды (лекция)", "20260901T083000", "20260901T100000",
                               rrule="FREQ=WEEKLY;BYDAY=MO,WE")), T)
    p = game.schedule.pairs(T + timedelta(days=2))[0]
    game.study.mark(p["key"], "kr", T)
    game.planner.add_task("Отчёт по лабе", "study", T, deadline=T + timedelta(days=3))
    game.story.add("Сложить полномочия", T, steps=["Куратор"])
    game.fin.add_plan("Связь", 60000, T + timedelta(days=1), "month")
    b = game.weekly.brief(T)
    assert b["week"] == 47 and b["span"] == "16–22 ноября" and b["pairs_total"] == 2
    assert b["marks"][0]["kind"] == "kr" and {"Отчёт по лабе", "📖 Подготовиться: контрольная — Кратные ряды"} <= {x["title"] for x in b["bank"]}
    assert b["payments"][0]["title"] == "Связь" and b["story"][0]["next"] == "Куратор"
    t = brief_text(b)
    assert "НЕДЕЛЯ 47" in t and "Контрольная" in t and "Связь" in t


def test_recap(game):
    done(game, T - timedelta(days=5), "study", "Прошлая", 200)
    done(game, T + timedelta(days=1), "study", "Курсовая", 300)
    done(game, T + timedelta(days=2), "code", "Бот", 100)
    m = game.story.add("Миссия", T)
    game.story.complete(m["id"], T + timedelta(days=2), "Выдохнул")
    r = game.weekly.recap(T + timedelta(days=6))
    assert r["xp"] == 1400 and r["xp_prev"] == 200 and r["delta"] == 600 and r["verdict"] == "Лучше прошлой"
    assert r["best_day"]["wd"] == "ср" and r["missions"][0]["title"] == "Миссия"
    assert "ПРОЙДЕНА" in recap_text(r)
    last = game.weekly.recap(T + timedelta(days=7), last=True)
    assert last["xp"] == 1400 and last["end"] == "2026-11-22"


def test_api_week_and_skills():
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    conn = connect(":memory:")
    g, a = Game(conn), Auth(conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, ZoneInfo("Europe/Moscow")), g, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    assert len(c.get("/api/skills").json()) == 9
    assert c.get("/api/skills/ups").json() == []
    assert "mood" in c.get("/api/week/brief").json()
    assert "verdict" in c.get("/api/week/recap?last=true").json()
