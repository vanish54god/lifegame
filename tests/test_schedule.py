"""Тесты расписания пар из календаря (формат как у публичного календаря iCloud)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db import connect
from app.game import Game
from app.schedule import SchedError, mask_url, normalize_url

MSK = ZoneInfo("Europe/Moscow")
T = date(2026, 11, 16)          # понедельник

VTZ = """BEGIN:VTIMEZONE
TZID:Europe/Moscow
BEGIN:STANDARD
DTSTART:20110327T020000
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
TZNAME:MSK
END:STANDARD
END:VTIMEZONE"""


def ics(*events: str) -> str:
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Apple Inc.//iCloud//RU", "X-WR-CALNAME:Пары",
                        VTZ, *events, "END:VCALENDAR"]) + "\r\n"


def ev(uid, summary, start, end, rrule=None, exdate=None, rid=None, location="", allday=False):
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{summary}", "DTSTAMP:20261101T000000Z"]
    if allday:
        lines += [f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}"]
    else:
        lines += [f"DTSTART;TZID=Europe/Moscow:{start}", f"DTEND;TZID=Europe/Moscow:{end}"]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if exdate:
        lines.append(f"EXDATE;TZID=Europe/Moscow:{exdate}")
    if rid:
        lines.append(f"RECURRENCE-ID;TZID=Europe/Moscow:{rid}")
    if location:
        lines.append(f"LOCATION:{location}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


MATAN = ev("matan@x", "Математический анализ (лекция)", "20260901T090000", "20260901T103000",
           rrule="FREQ=WEEKLY;BYDAY=MO", location="ауд. 1234")
PHYS = ev("phys@x", "Физика (практика)", "20260901T104500", "20260901T121500",
          rrule="FREQ=WEEKLY;BYDAY=MO", exdate="20261123T104500", location="ауд. 512")
# перенесённая на 13:00 пара 30.11
PHYS_MOVED = ev("phys@x", "Физика (практика)", "20261130T130000", "20261130T143000", rid="20261130T104500",
                location="ауд. 512")
WEEK = ev("week@x", "Зачётная неделя", "20261221", "20261228", allday=True)


@pytest.fixture
def game():
    g = Game(connect(":memory:"), MSK)
    g.day_start_hour = 5
    return g


def test_url_rules():
    assert normalize_url("webcal://p138-caldav.icloud.com/published/2/abc").startswith("https://p138-caldav")
    for bad in ("http://x.com/a", "https://127.0.0.1/a", "https://localhost/a", "ftp://a.b", "https://intranet/a"):
        with pytest.raises(SchedError):
            normalize_url(bad)
    assert mask_url("https://p138-caldav.icloud.com/published/2/abcdef123456") == "p138-caldav.icloud.com/…123456"


def test_parse_weekly_with_exception_moved_and_allday(game):
    s = game.schedule
    r = s.apply(ics(MATAN, PHYS, PHYS_MOVED, WEEK), T)
    assert r["count"] > 20
    mon = s.pairs(T)
    assert [(p["start"], p["end"], p["title"]) for p in mon] == [
        ("09:00", "10:30", "Математический анализ (лекция)"), ("10:45", "12:15", "Физика (практика)")]
    assert mon[0]["location"] == "ауд. 1234"
    assert [p["title"] for p in s.pairs(T + timedelta(days=7))] == ["Математический анализ (лекция)"]  # EXDATE
    assert [p["start"] for p in s.pairs(T + timedelta(days=14))] == ["09:00", "13:00"]                  # перенос
    assert s.day(date(2026, 12, 22))[0]["allday"] == 1
    assert s.pairs(T + timedelta(days=1)) == []


def test_busy_leave_and_capacity(game):
    s = game.schedule
    s.apply(ics(MATAN, PHYS), T)
    b = s.busy(T)
    assert b["span_min"] == 195 and b["commute_min"] == 180 and b["total_min"] == 375
    assert s.leave_at(T) == ("07:30", s.pairs(T)[0])                  # 9:00 − полтора часа дороги
    game.set_setting("capacity_pair_h", "2.5")
    assert game.planner.load(T)["capacity_min"] == 150                # день с парами
    assert game.planner.load(T + timedelta(days=1))["capacity_min"] == 360   # свободный день


def test_now_next(game):
    s = game.schedule
    s.apply(ics(MATAN, PHYS), T)
    nn = s.now_next(datetime(2026, 11, 16, 9, 40, tzinfo=MSK))
    assert nn["now"]["start"] == "09:00" and nn["now_left_min"] == 50 and nn["next"]["start"] == "10:45"
    nn = s.now_next(datetime(2026, 11, 16, 19, 0, tzinfo=MSK))
    assert nn["now"] is None and nn["next"]["day"] == "2026-11-23"      # сегодня всё — следующая неделя


def test_cancel_and_move_detected_on_resync(game):
    s = game.schedule
    first = s.apply(ics(MATAN, PHYS), T)
    assert first["cancelled"] == [] and first["added"] == []            # первая загрузка — без уведомлений
    # в календаре пару 23.11 убрали, а 30.11 перенесли
    r = s.apply(ics(MATAN, PHYS.replace("EXDATE;TZID=Europe/Moscow:20261123T104500", "EXDATE;TZID=Europe/Moscow:20261123T104500")
                    .replace("RRULE:FREQ=WEEKLY;BYDAY=MO", "RRULE:FREQ=WEEKLY;BYDAY=MO") , PHYS_MOVED), T)
    assert [m["new"]["start"] for m in r["moved"]] == ["13:00"]
    s.apply(ics(MATAN, PHYS, PHYS_MOVED), T)
    r = s.apply(ics(MATAN, PHYS_MOVED), T)                               # физику убрали совсем
    assert {c["day"] for c in r["cancelled"]} >= {"2026-11-16"}
    assert all(p["title"] != "Физика (практика)" for p in s.pairs(T))
    assert any(p["status"] == "cancelled" for p in s.day(T))            # видно, что отменили


def test_empty_calendar_does_not_wipe(game):
    s = game.schedule
    s.apply(ics(MATAN), T)
    with pytest.raises(SchedError):
        s.apply(ics(), T)
    assert s.pairs(T)
    with pytest.raises(SchedError):
        s.apply("это не календарь", T)


def test_api_schedule(game):
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    a = Auth(game.conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, MSK), game, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    assert c.get("/api/schedule/settings").json()["connected"] is False
    assert c.put("/api/schedule/settings", json={"url": "http://bad"}).status_code == 400
    game.schedule.apply(ics(MATAN, PHYS), T)
    assert c.put("/api/schedule/settings", json={"commute_min": 150}).json()["commute_min"] == 150
    d = c.get("/api/schedule/day/2026-11-16").json()
    assert len(d["pairs"]) == 2 and d["leave_at"] == "07:45" and d["busy"]["total_min"] == 195 + 150
    assert len(c.get("/api/schedule/week").json()["days"]) == 7
    assert "now" in c.get("/api/schedule/now").json()
    st = c.get("/api/settings").json()
    assert st["capacity_pair_h"] == 3


# ---------- ⚡ важные пары ----------

REAL = ev("kr@x", "711 Кратные ряды (лекция)", "20260901T083000", "20260901T100000", rrule="FREQ=WEEKLY;BYDAY=MO")
LAB = ev("lab@x", "2254 Современные процессоры (лр)", "20260901T120000", "20260901T133000", rrule="FREQ=WEEKLY;BYDAY=MO")


def test_title_parsing(game):
    from app.study import parse_title
    assert parse_title("711 Кратные ряды (лекция)") == {"subject": "Кратные ряды", "room": "711", "ptype": "лекция"}
    assert parse_title("2254 Современные процессоры (лр)")["ptype"] == "лаба"
    assert parse_title("Физкультура") == {"subject": "Физкультура", "room": "", "ptype": ""}
    game.schedule.apply(ics(REAL, LAB), T)
    p = game.schedule.pairs(T)
    assert p[0]["location"] == "ауд. 711" and p[0]["subject"] == "Кратные ряды"
    assert p[1]["suggest"] == "lab" and p[0]["suggest"] == "kr"


def test_mark_creates_quest_and_prep_5_days_before(game):
    st, s = game.study, game.schedule
    s.apply(ics(REAL, LAB), T)
    far = s.pairs(T + timedelta(days=14))[0]                      # КР через 2 недели
    m = st.mark(far["key"], "kr", T)
    assert m["xp"] == 300 and m["task_id"] is None                 # подготовка ещё не в банке
    q = game.get(m["quest_id"])
    assert q.day == "2026-11-30" and q.xp == 300 and "Кратные ряды" in q.title
    assert st.tick(T + timedelta(days=8)) == []                    # за 6 дней — ещё рано
    made = st.tick(T + timedelta(days=9))                          # за 5 дней — в банк
    assert len(made) == 1
    t = game.planner.task(made[0]["task"]["id"], T + timedelta(days=9))
    assert t["deadline"] == "2026-11-30" and t["est_min"] == 180
    assert s.day(T + timedelta(days=14))[0]["mark"]["kind"] == "kr"
    st.mark(far["key"], "test", T)                                 # передумал — тест вместо КР
    assert len([x for x in st.upcoming(T) if x["key"] == far["key"]]) == 1
    assert game.conn.execute("SELECT COUNT(*) FROM bank_tasks").fetchone()[0] == 0   # старая подготовка убрана


def test_mark_follows_moved_pair(game):
    st, s = game.study, game.schedule
    s.apply(ics(REAL), T)
    p = s.pairs(T + timedelta(days=7))[0]
    m = st.mark(p["key"], "kr", T)
    st.tick(T + timedelta(days=2))
    moved = ev("kr@x", "711 Кратные ряды (лекция)", "20261124T140000", "20261124T153000", rid="20261123T083000")
    r = s.apply(ics(REAL, moved), T + timedelta(days=2))
    assert r["moved"] and r["moved"][0]["mark"] == "kr"
    m2 = st.get(m["id"])
    assert m2["day"] == "2026-11-24" and m2["start"] == "14:00"
    assert game.get(m["quest_id"]).day == "2026-11-24"
    assert game.planner.task(m2["task_id"], T)["deadline"] == "2026-11-24"
    assert all(e["status"] == "ok" for e in s.day(T + timedelta(days=7)))   # на старом месте не «отменили»


def test_grade_bonus_after_week(game):
    st, s = game.study, game.schedule
    s.apply(ics(REAL), T)
    m = st.mark(s.pairs(T)[0]["key"], "kr", T)
    game.set_status(m["quest_id"], "done") if hasattr(game, "set_status") else None
    game.mark(m["quest_id"], "done") if game.get(m["quest_id"]).status != "done" else None
    assert st.grades_pending(T + timedelta(days=6)) == []
    assert [x["id"] for x in st.grades_pending(T + timedelta(days=7))] == [m["id"]]
    st.set_grade(m["id"], "later", T + timedelta(days=7))
    assert st.grades_pending(T + timedelta(days=8)) == []
    r = st.set_grade(m["id"], "5", T + timedelta(days=10))
    assert r["bonus_xp"] == 150
    assert "study1" in game._achieved(T + timedelta(days=10))
    with pytest.raises(Exception):
        st.set_grade(m["id"], "4", T + timedelta(days=10))


def test_api_marks(game):
    from fastapi.testclient import TestClient
    from app.auth import Auth
    from app.config import Config
    from app.web import create_app
    a = Auth(game.conn)
    c = TestClient(create_app(Config("1:x", 42, ":memory:", 5, MSK), game, a))
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"code": a.new_code()}).json()["token"]
    game.schedule.apply(ics(REAL, LAB), date.today())
    nxt = next(p for i in range(8) for p in game.schedule.pairs(date.today() + timedelta(days=i + 1)))
    m = c.post("/api/schedule/mark", json={"key": nxt["key"], "kind": "lab"}).json()
    assert m["xp"] == 200
    assert c.post("/api/schedule/mark", json={"key": "nope", "kind": "lab"}).status_code == 400
    j = c.get("/api/schedule/marks").json()
    assert j["upcoming"][0]["id"] == m["id"] and j["kinds"]["exam"]["xp"] == 800
    d = c.get(f"/api/schedule/day/{nxt['day']}").json()
    assert any(p["mark"] for p in d["pairs"])
    assert c.delete(f"/api/schedule/mark/{m['id']}").json()["ok"]
