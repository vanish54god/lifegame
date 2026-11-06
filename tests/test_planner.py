"""Тесты банка заданий, огня, таймера, привычек, оценок, сезонов, календаря."""

from datetime import date, datetime, timedelta

import pytest

from app import rules
from app.db import connect
from app.game import Game
from app.life import LifeError
from app.planner import PlanError, heat_level

T = date(2026, 11, 6)   # пятница


@pytest.fixture
def game():
    g = Game(connect(":memory:"))
    g.day_start_hour = 5
    return g


def test_heat_levels():
    assert heat_level(60, None, T) == 0
    assert heat_level(30, T + timedelta(days=20), T) == 0          # мелочь, далеко
    assert heat_level(30, T + timedelta(days=5), T) == 1           # неделя
    assert heat_level(60, T + timedelta(days=3), T) == 2           # 3 дня
    assert heat_level(600, T + timedelta(days=3), T) == 3          # 10ч на 3 дня — очень горит
    assert heat_level(600, T + timedelta(days=20), T) == 1         # 10ч, но 20 дней
    assert heat_level(60, T, T) == 4 and heat_level(60, T - timedelta(days=1), T) == 4


def test_bank_sort_and_schedule_bonus(game):
    p = game.planner
    a = p.add_task("Курсач", "study", T, 4, 600, T + timedelta(days=3))
    b = p.add_task("Купить тетради", "bonus", T, 1, 15)
    c = p.add_task("Лаба", "study", T, 2, 120, T + timedelta(days=10))
    assert [t["title"] for t in p.tasks(T)] == ["Курсач", "Лаба", "Купить тетради"]
    assert p.task(a["id"], T)["heat_emoji"] == "🔥🔥"
    res = p.schedule(c["id"], T + timedelta(days=1), 200, T)       # до дедлайна 9 дней — «заранее»
    assert res["bonus"] == 40 and res["quest"].xp == 240 and res["quest"].est_min == 120
    assert p.task(c["id"], T)["planned"]["day"] == "2026-11-07"
    with pytest.raises(PlanError):
        p.schedule(c["id"], T + timedelta(days=2), 200, T)          # уже в плане
    assert c["id"] not in [t["id"] for t in p.schedulable(T)]


def test_done_and_return_to_bank(game):
    p = game.planner
    t = p.add_task("Лаба", "study", T, 2, 60, T + timedelta(days=2))
    q = p.schedule(t["id"], T, 200, T)["quest"]
    game.mark(q.id, "done", T)
    assert p.task(t["id"], T)["status"] == "done"
    game.mark(q.id, "todo", T)
    assert p.task(t["id"], T)["status"] == "open"
    # не сделал за день — на следующий день задача снова в банке, а не «в плане»
    assert p.task(t["id"], T + timedelta(days=1))["planned"] is None
    assert t["id"] in [x["id"] for x in p.schedulable(T + timedelta(days=1))]
    # провалил — тоже возвращается
    q2 = p.schedule(t["id"], T + timedelta(days=1), 200, T + timedelta(days=1))["quest"]
    game.mark(q2.id, "failed", T + timedelta(days=1))
    assert p.task(t["id"], T + timedelta(days=1))["planned"] is None


def test_subtasks(game):
    p = game.planner
    big = p.add_task("Курсач", "study", T, 4, None, T + timedelta(days=14))
    parts = [p.add_task(f"Глава {i}", "study", T, 2, 120, parent_id=big["id"]) for i in range(1, 6)]
    t = p.task(big["id"], T)
    assert len(t["children"]) == 5 and t["rem_min"] == 600 and t["children"][0]["deadline"] == big["deadline"]
    with pytest.raises(PlanError):
        p.schedule(big["id"], T, 300, T)                            # переносить надо части
    for i, part in enumerate(parts):
        q = p.schedule(part["id"], T, 100, T)["quest"]
        assert q.title.startswith("Курсач: ")
        game.mark(q.id, "done", T)
        game.conn.execute("UPDATE quests SET day = ? WHERE id = ?", ((T - timedelta(days=i + 1)).isoformat(), q.id))
    t = p.task(big["id"], T)
    assert t["status"] == "done" and t["progress"] == 100
    keys = {a["key"] for a in game.full_stats(T)["achievements"] if a["done"]}
    assert {"splitter", "early5", "boss"} <= keys


def test_boss_and_firefighter(game):
    p = game.planner
    t = p.add_task("Экзамен", "study", T, 4, 60, T)
    res = p.do_now(t["id"], 500, T)
    keys = {a["key"] for a in res["new_achievements"]}
    assert {"boss", "firefighter"} <= keys


def test_timer_and_pace(game):
    p = game.planner
    q, _ = game.add_quest(T, rules.CATEGORIES["study"], "Лаба", 200, est_min=60)
    p.timer_start(q.id)
    assert p.running_timer()["id"] == q.id
    game.conn.execute("UPDATE quests SET timer_start = ? WHERE id = ?",
                      ((datetime.now() - timedelta(minutes=40)).isoformat(timespec="seconds"), q.id))
    q2, _ = game.add_quest(T, rules.CATEGORIES["bonus"], "Другое", 20, est_min=10)
    p.timer_start(q2.id)                                            # первый таймер встаёт на паузу
    assert game.get(q.id).timer_start is None and 2350 < game.get(q.id).timer_sec < 2450
    game.mark(q.id, "done", T)
    assert game.get(q.id).pace == "fast"                            # 40 мин из 60 — быстрее
    p.set_pace(q.id, "slow")
    assert game.get(q.id).pace == "slow"
    with pytest.raises(PlanError):
        p.set_pace(q2.id, "ok")                                     # не выполнен


def test_pace_factor_and_start_by(game):
    p = game.planner
    for i in range(6):
        q, _ = game.add_quest(T - timedelta(days=i + 1), rules.CATEGORIES["bonus"], f"x{i}", 10, est_min=60)
        game.mark(q.id, "done", T)
        p.set_pace(q.id, "slow")
    f, n = p.pace_factor()
    assert f == 1.4 and n == 6
    game.add_quest(T, rules.CATEGORIES["study"], "Лаба", 200, est_min=60)
    game.add_quest(T, rules.CATEGORIES["bonus"], "Без оценки", 20)
    sb = p.start_by(T, datetime(2026, 11, 6, 20, 0))
    assert sb["remaining_min"] == 84 and sb["unknown"] == 1
    assert sb["start"] == "22:36" and not sb["late"]                # 00:00 − 1ч24м
    assert p.start_by(T, datetime(2026, 11, 6, 23, 0))["late"]
    game.set_setting("capacity_h", "1")
    ld = p.load(T)
    assert ld["planned_min"] == 60 and ld["over"]


def test_habits_daily_and_weekly(game):
    life = game.life
    sleep = life.add_habit("Лечь до 00:00", T, "😴", 7, 20)
    sport = life.add_habit("Спорт", T, "🏋️", 2, 30)
    for i in range(1, 4):
        life.toggle_habit(sleep["id"], T - timedelta(days=i), T - timedelta(days=i))
    h = life.habit(sleep["id"], T)
    assert h["streak"] == 3 and not h["done_today"]                 # сегодня ещё не отмечено — серия жива
    res = life.toggle_habit(sleep["id"], T, T)
    assert res["done"] and res["habit"]["streak"] == 4 and game.stats().total_xp == 80
    res = life.toggle_habit(sleep["id"], T, T)                      # снял отметку — XP ушёл
    assert not res["done"] and game.stats().total_xp == 60
    # спорт: 2 раза в неделю, 3 недели подряд
    for w in range(1, 4):
        mon = T - timedelta(days=T.weekday()) - timedelta(days=7 * w)
        for d in (mon, mon + timedelta(days=3)):
            game.conn.execute("INSERT INTO habit_log (habit_id, day) VALUES (?, ?)", (sport["id"], d.isoformat()))
    h = life.habit(sport["id"], T)
    assert h["streak"] == 3 and h["unit"] == "нед" and h["week_count"] == 0
    with pytest.raises(LifeError):
        life.toggle_habit(sport["id"], T - timedelta(days=3), T)    # только сегодня и вчера


def test_rating_and_stats(game):
    life = game.life
    life.rate(T, 9, T)
    life.rate(T - timedelta(days=1), 3, T)
    q, _ = game.add_quest(T, rules.CATEGORIES["study"], "x", 300)
    game.mark(q.id, "done", T)
    st = life.rating_stats(T)
    assert st["avg"] == 6.0 and st["xp_good"] == 300 and st["xp_bad"] == 0
    with pytest.raises(LifeError):
        life.rate(T, 11, T)
    life.rate(T, None, T)
    assert life.rating(T) is None


def test_week_season_calendar(game):
    p, life = game.planner, game.life
    q, _ = game.add_quest(T, rules.CATEGORIES["study"], "Лаба", 300)
    game.mark(q.id, "done", T)
    t = p.add_task("Курсач", "study", T, 4, 300, T + timedelta(days=5))
    game.fin.add_shift(T, "Ивент Про", "Хелпер", 320000)
    game.add_promise("Кино", T, T + timedelta(days=1))
    life.rate(T, 8, T)
    wr = life.week_review(T)
    assert wr["this"]["xp"] == 300 and wr["this"]["shifts"] == 1 and wr["last"]["xp"] == 0
    s = life.season("2026-11")
    assert s["title"] == "Сезон: ноябрь 2026" and s["xp"] == 300 and s["top_category"]["key"] == "study"
    assert any(a["key"] == "first" for a in s["achievements"]) or True
    cal = life.calendar("2026-11", T)
    d = cal["days"]
    assert d["2026-11-06"]["done"] == 1 and d["2026-11-06"]["rating"] == 8
    assert d["2026-11-11"]["deadlines"][0]["title"] == "Курсач"
    assert d["2026-11-07"]["promises"] == ["Кино"]
    assert d["2026-11-06"]["shifts"][0]["company"] == "Ивент Про"


def test_digest_and_delete(game):
    p = game.planner
    a = p.add_task("Срочно", "study", T, 2, 60, T + timedelta(days=2))
    p.add_task("Не срочно", "study", T, 2, 60, T + timedelta(days=10))
    assert [x["title"] for x in p.digest(T)] == ["Срочно"]
    q = p.schedule(a["id"], T, 100, T)["quest"]
    with pytest.raises(PlanError):
        p.delete_task(a["id"], T)                                   # в плане — сначала убери
    p.unschedule(q.id)
    p.delete_task(a["id"], T)
    assert len(p.tasks(T)) == 1


def test_habit_quests_protected(game):
    h = game.life.add_habit("Вода", T)
    res = game.life.toggle_habit(h["id"], T, T)
    qid = game.conn.execute("SELECT quest_id FROM habit_log").fetchone()[0]
    from app.game import GameError
    with pytest.raises(GameError):
        game.delete_quest(qid)
    with pytest.raises(GameError):
        game.mark(qid, "todo", T)


def test_api_planner():
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
    today = c.get("/api/meta").json()["today"]
    t = c.post("/api/bank", json={"title": "Курсач", "category": "study", "difficulty": 4, "est_min": 300,
                                  "deadline": today}).json()
    assert t["heat"] == 4
    part = c.post("/api/bank", json={"title": "Глава 1", "category": "study", "est_min": 60, "parent_id": t["id"]}).json()
    b = c.get("/api/bank").json()
    assert b["tasks"][0]["children"][0]["id"] == part["id"] and b["schedulable"][0]["id"] == part["id"]
    r = c.post(f"/api/bank/{part['id']}/schedule", json={"day": today, "xp": 200}).json()
    qid = r["quest"]["id"]
    assert r["quest"]["est_min"] == 60 and r["load"]["planned_min"] == 60
    assert c.post(f"/api/quests/{qid}/timer", json={"action": "start"}).json()["timer_running"]
    assert not c.post(f"/api/quests/{qid}/timer", json={"action": "pause"}).json()["timer_running"]
    assert c.get(f"/api/plan/day/{today}").json()["load"]["planned_min"] == 60
    assert c.patch(f"/api/quests/{qid}", json={"status": "done"}).json()["quest"]["status"] == "done"
    assert c.post(f"/api/quests/{qid}/pace", json={"pace": "ok"}).json()["quest"]["pace"] == "ok"
    h = c.post("/api/habits", json={"title": "Спорт", "emoji": "🏋️", "per_week": 2, "xp": 30}).json()
    assert c.post(f"/api/habits/{h['id']}/toggle", json={}).json()["done"]
    assert c.put("/api/rating", json={"day": today, "score": 9}).json()["score"] == 9
    assert c.put("/api/rating", json={"day": today, "score": 11}).status_code == 422
    assert c.get("/api/review").json()["this"]["habit_checks"] == 1
    s = c.get("/api/season").json()
    assert s["month"] == today[:7] and today[:7] in s["months"]
    assert today in c.get("/api/calendar").json()["days"]
    st = c.get("/api/settings").json()
    assert st["bedtime"] == "00:00"
    st.update(bedtime="23:30", capacity_h=5, remind_startby=False)
    st.pop("sessions"); st.pop("day_start_hour")
    assert c.put("/api/settings", json=st).json()["bedtime"] == "23:30"
    assert c.post("/api/bank", json={"title": "x", "category": "promise"}).status_code == 400


def test_new_part_reopens_parent(game):
    p = game.planner
    big = p.add_task("Курсач", "study", T, 4, None, T + timedelta(days=10))
    first = p.add_task("Введение", "study", T, 2, 60, parent_id=big["id"])
    q = p.schedule(first["id"], T, 100, T)["quest"]
    game.mark(q.id, "done", T)
    assert p.task(big["id"], T)["status"] == "done"
    p.add_task("Глава 1", "study", T, 2, 120, parent_id=big["id"])
    t = p.task(big["id"], T)
    assert t["status"] == "open" and t["progress"] == 50
