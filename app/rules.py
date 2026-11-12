"""
Правила игры. Всё, что взято из файла «План XP», лежит здесь.
Хочешь поменять баланс — меняй только этот файл.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str          # внутреннее имя (латиницей, хранится в базе)
    title: str        # как показывать игроку
    emoji: str
    xp_min: int       # рекомендованный минимум XP
    xp_max: int       # рекомендованный максимум XP (можно превысить для «ультра хард»)
    is_main: bool     # основное задание или бонусное
    pickable: bool = True   # можно ли выбрать при добавлении квеста


CATEGORIES: dict[str, Category] = {
    "study": Category("study", "Учёба", "📚", 100, 500, True),
    "work":  Category("work",  "Работа", "💼", 100, 500, True),
    "gutv":  Category("gutv",  "ГУТВ", "🎥", 50, 500, True),
    "sleep": Category("sleep", "Сон", "😴", 0, 100, True),
    "code":  Category("code",  "Программирование", "💻", 50, 200, True),
    "bonus": Category("bonus", "Бонус", "⭐", 10, 200, False),
    # квесты этой категории создаются сами, когда сдерживаешь обещание
    "promise": Category("promise", "Обещание", "💌", 30, 150, False, pickable=False),
    # отметка привычки
    "habit": Category("habit", "Привычка", "🔁", 10, 50, False, pickable=False),
    # день, прожитый в лимите трат
    "money": Category("money", "Деньги", "💰", 10, 50, False, pickable=False),
    # этапы и финалы сюжетных миссий
    "story": Category("story", "Сюжет", "🎬", 100, 5000, False, pickable=False),
}

# Слова, которыми можно назвать категорию в команде боту
ALIASES: dict[str, str] = {
    "учеба": "study", "учёба": "study", "study": "study",
    "работа": "work", "смена": "work", "work": "work",
    "гутв": "gutv", "студия": "gutv", "gutv": "gutv",
    "сон": "sleep", "sleep": "sleep",
    "прога": "code", "код": "code", "программирование": "code", "code": "code",
    "бонус": "bonus", "bonus": "bonus",
}

MAX_MAIN_PER_DAY = 3

# Банк заданий
DIFFICULTY = {1: ("Лёгкая", "🟢", 0.6), 2: ("Средняя", "🟡", 1.0), 3: ("Сложная", "🟠", 1.5), 4: ("Босс", "💀", 2.2)}
EARLY_DAYS = 3             # сделал за столько дней до дедлайна —
EARLY_BONUS = 0.2          # …+20% XP
HEAT = ["❄️", "🌤", "🔥", "🔥🔥", "🔥🔥🔥"]
HEAT_NAMES = ["спокойно", "пора задуматься", "горит", "очень горит", "пожар"]
TIME_PRESETS = [15, 30, 60, 90, 120, 180, 300, 480]   # минуты

# Обещания
PROMISE_XP = 50            # за сдержанное обещание
PROMISE_FAST_DAYS = 3      # сдержал за столько дней с момента обещания —
PROMISE_FAST_MULT = 1.5    # …получи XP × 1.5
PROMISE_NUDGE_AFTER = 3    # обещание без срока висит столько дней — бот спрашивает «когда?»      # основных заданий в день: от 1 до 3
COINS_PER_XP = 10         # монеты = XP / 10

# Уровни: на 1-й уровень нужно 100 XP, на каждый следующий на 50 больше
LEVEL_BASE = 100
LEVEL_STEP = 50


def find_category(word: str) -> Category | None:
    """Ищет категорию по слову из команды (регистр не важен)."""
    key = ALIASES.get(word.lower())
    return CATEGORIES.get(key) if key else None


def xp_warning(cat: Category, xp: int) -> str | None:
    """Если XP вне рекомендованных границ — возвращает предупреждение. Это не запрет."""
    if xp < cat.xp_min:
        return f"меньше обычного ({cat.xp_min}–{cat.xp_max})"
    if xp > cat.xp_max:
        return f"больше обычного ({cat.xp_min}–{cat.xp_max}) — ультра хард? 🔥"
    return None


def xp_for_level(level: int) -> int:
    """Сколько XP нужно, чтобы с уровня level-1 перейти на level. 1→100, 2→150, 3→200…"""
    return LEVEL_BASE + LEVEL_STEP * (level - 1)


@dataclass
class LevelInfo:
    level: int        # текущий уровень
    into: int         # сколько XP уже набрано внутри уровня
    need: int         # сколько XP нужно на следующий уровень всего


def level_info(total_xp: int) -> LevelInfo:
    """Переводит общий XP в уровень и прогресс до следующего."""
    level = 0
    left = total_xp
    while left >= xp_for_level(level + 1):
        left -= xp_for_level(level + 1)
        level += 1
    return LevelInfo(level=level, into=left, need=xp_for_level(level + 1))


def coins_earned(total_xp: int) -> int:
    """Сколько монет заработано за всё время (до трат)."""
    return total_xp // COINS_PER_XP


def progress_bar(into: int, need: int, width: int = 10) -> str:
    filled = round(width * into / need) if need else width
    return "▰" * filled + "▱" * (width - filled)


def fmt_min(m: int | None) -> str:
    """90 → «1ч 30м», 45 → «45м»."""
    if not m:
        return "—"
    h, mm = divmod(int(m), 60)
    return f"{h}ч {mm}м" if h and mm else f"{h}ч" if h else f"{mm}м"


def suggest_xp(category: "Category", difficulty: int) -> int:
    """Подсказка цены при переносе из банка: середина диапазона категории × сложность."""
    mid = (category.xp_min + category.xp_max) / 2
    return max(10, int(round(mid * DIFFICULTY.get(difficulty, DIFFICULTY[2])[2] / 10) * 10))


# Что бот показывает в «Сегодня» сразу, а что — только по кнопке (☰ Ещё → ⚙ и вкладка «Ещё» в приложении)
BOT_SHOW = {
    "show_time": ("⏰ Когда начинать", "1"),
    "show_money": ("💰 Сколько можно потратить", "1"),
    "show_sched": ("📚 Пары", "1"),
    "show_habits": ("🔁 Привычки списком", "0"),
    "show_promises": ("💌 Обещания списком", "0"),
    "show_rating": ("⭐ Оценка дня (иначе — после 20:00)", "0"),
}
