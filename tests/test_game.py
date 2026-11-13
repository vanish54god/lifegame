"""Тесты: python -m pytest"""

from datetime import date, datetime, timedelta

import pytest

from app import rules
from app.db import connect
from app.game import Game, GameError, game_day


@pytest.fixture
def game():
    return Game(connect(":memory:"))   # база в памяти, файл не создаётся


DAY = date(2026, 11, 3)


def test_levels_follow_plan():
    # 1 - 100, 2 - 150, 3 - 200
    assert rules.level_info(0).level == 0
    assert rules.level_info(99).level == 0
    assert rules.level_info(100).level == 1
    assert rules.level_info(249).level == 1
    assert rules.level_info(250).level == 2
    info = rules.level_info(300)
    assert (info.level, info.into, info.need) == (2, 50, 200)


def test_coins_are_xp_div_10():
    assert rules.coins_earned(355) == 35


def test_categories_by_russian_words():
    assert rules.find_category("Учеба").key == "study"
    assert rules.find_category("гутв").key == "gutv"
    assert rules.find_category("непонятно") is None


def test_xp_bounds_are_soft(game):
    q, warn = game.add_quest(DAY, rules.CATEGORIES["study"], "Курсач", 900)
    assert q.xp == 900 and "ультра хард" in warn
    _, warn = game.add_quest(DAY, rules.CATEGORIES["work"], "Смена", 300)
    assert warn is None


def test_max_three_main_when_planning_but_today_unlimited(game):
    future = game.today() + timedelta(days=1)
    for i in range(3):
        game.add_quest(future, rules.CATEGORIES["study"], f"Задание {i}", 100)
    with pytest.raises(GameError):
        game.add_quest(future, rules.CATEGORIES["work"], "Смена", 200)
    game.add_quest(future, rules.CATEGORIES["bonus"], "Разобрать стол", 30)
    assert len(game.quests(future)) == 4
    today = game.today()                                   # появилось окно — сколько успеешь
    for i in range(5):
        game.add_quest(today, rules.CATEGORIES["study"], f"Сегодня {i}", 100)
    assert sum(q.is_main for q in game.quests(today)) == 5


def test_complete_undo_and_level_up(game):
    q, _ = game.add_quest(DAY, rules.CATEGORIES["work"], "Смена", 260)
    _, before, after = game.set_status(q.id, "done")
    assert (before, after) == (0, 2)
    st = game.stats(DAY)
    assert st.total_xp == 260 and st.coins == 26 and st.xp_on_day == 260
    game.set_status(q.id, "todo")
    assert game.stats().total_xp == 0


def test_cannot_delete_done(game):
    q, _ = game.add_quest(DAY, rules.CATEGORIES["sleep"], "Вовремя лечь", 80)
    game.set_status(q.id, "done")
    with pytest.raises(GameError):
        game.delete_quest(q.id)


def test_game_day_starts_at_5am():
    assert game_day(datetime(2026, 11, 3, 0, 30), 5) == date(2026, 11, 2)
    assert game_day(datetime(2026, 11, 3, 6, 0), 5) == date(2026, 11, 3)
