"""Тесты второй партии достижений (и секретных)."""

from datetime import date, timedelta

import pytest

from app import rules
from app.db import connect
from app.game import Game

C = rules.CATEGORIES
T = date(2026, 11, 10)


@pytest.fixture
def game():
    return Game(connect(":memory:"))


def ach(game, today=T):
    return {a["key"]: a for a in game.full_stats(today)["achievements"]}


def done(game, day, cat="study", xp=100, at=None):
    q, _ = game.add_quest(day, C[cat], "x", xp)
    game.set_status(q.id, "done")
    if at:
        game.conn.execute("UPDATE quests SET done_at = ? WHERE id = ?", (at, q.id))
        game.conn.commit()
    return q


def test_secret_hidden_until_unlocked(game):
    a = ach(game)["jackpot"]
    assert a["secret"] and not a["done"] and a["title"] == "???" and a["emoji"] == "🔒"
    done(game, T, "study", 777)
    a = ach(game)["jackpot"]
    assert a["done"] and a["title"] == "Джекпот"


def test_sticky_after_undo(game):
    q = done(game, T, "study", 777)
    assert ach(game)["jackpot"]["done"]
    game.set_status(q.id, "todo")
    assert ach(game)["jackpot"]["done"]       # не закрывается обратно


def test_time_based(game):
    done(game, T, "study", 100, at=f"{T + timedelta(days=1)}T03:10:00")
    done(game, T, "bonus", 20, at=f"{T}T06:30:00")
    a = ach(game)
    assert a["night"]["done"] and a["early"]["done"] and not a["lastmin"]["done"]
    done(game, T, "work", 100, at=f"{T}T23:45:00")
    assert ach(game)["lastmin"]["done"]


def test_lastmin_needs_main_and_same_day(game):
    done(game, T, "bonus", 20, at=f"{T}T23:50:00")
    assert not ach(game)["lastmin"]["done"]


def test_oops_and_undo(game):
    for _ in range(3):
        q, _ = game.add_quest(T, C["bonus"], "x", 10)
        game.set_status(q.id, "failed")
    assert ach(game)["oops"]["done"]
    q, _ = game.add_quest(T, C["bonus"], "y", 10)
    for _ in range(10):
        game.set_status(q.id, "done")
        game.set_status(q.id, "todo")
    assert ach(game)["undo"]["done"]


def test_dates(game):
    done(game, date(2026, 11, 13))            # пятница
    done(game, date(2027, 1, 1), "bonus", 10)
    a = ach(game, date(2027, 1, 2))
    assert a["fri13"]["done"] and a["newyear"]["done"]


def test_phoenix(game):
    done(game, T - timedelta(days=20))
    assert not ach(game)["phoenix"]["done"]
    done(game, T)                              # основной квест — день засчитан
    assert ach(game)["phoenix"]["done"]


def test_zero_and_spender(game):
    done(game, T, "study", 500)               # 50 монет
    it = game.add_shop_item("Кофе", 50, "fun")
    game.buy(it["id"])
    assert ach(game)["zero"]["done"]
    assert not ach(game)["spender"]["done"]


def test_counts_blitz_strike(game):
    for i in range(10):
        done(game, T - timedelta(days=i // 5), "bonus", 10)
    a = ach(game)
    assert a["blitz"]["done"] and a["strike"]["done"]


def test_strike_broken_by_fail(game):
    for i in range(9):
        done(game, T, "bonus", 10)
    q, _ = game.add_quest(T, C["bonus"], "fail", 10)
    game.set_status(q.id, "failed")
    done(game, T, "bonus", 10)
    assert not ach(game)["strike"]["done"]


def test_perfect7(game):
    for i in range(7):
        d = T - timedelta(days=i)
        done(game, d, "sleep", 80)
        done(game, d, "bonus", 20)
    assert ach(game)["perfect7"]["done"]


def test_architect(game):
    for i in range(5):                         # 5 стартовых + 5 своих
        game.add_template(C["bonus"], f"t{i}", 10)
    assert ach(game)["architect"]["done"]


def test_mark_reports_secret(game):
    q, _ = game.add_quest(T, C["study"], "x", 777)
    res = game.mark(q.id, "done", T)
    sec = [a for a in res["new_achievements"] if a["secret"]]
    assert any(a["title"] == "Джекпот" for a in sec)        # ночью тут же может открыться и «Ночная смена»


def test_done_at_uses_tz():
    from zoneinfo import ZoneInfo
    g = Game(connect(":memory:"), ZoneInfo("Pacific/Kiritimati"))   # UTC+14
    q = done(g, T)
    from datetime import datetime, timezone
    utc_hour = datetime.now(timezone.utc).hour
    stored = int(g.get(q.id) and g.conn.execute("SELECT done_at FROM quests").fetchone()[0][11:13])
    assert stored == (utc_hour + 14) % 24 or stored == (utc_hour + 15) % 24
