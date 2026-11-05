"""
Разбор обещания из обычного текста:
  «обещал забрать посылку в пятницу»  →  («Забрать посылку», пятница)
  «обещал сходить в кино»             →  («Сходить в кино», без срока)
Понимает: сегодня, завтра, послезавтра, в <день недели>, на выходных,
на этой неделе, через N дней, (до) 12.11 / 12.11.2026.
"""

import re
from datetime import date, timedelta

WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2, "четверг": 3,
    "пятницу": 4, "пятница": 4, "субботу": 5, "суббота": 5, "воскресенье": 6,
}

PREFIX = re.compile(r"^\s*(я\s+)?(обещал[аи]?|пообещал[аи]?|обещание)\s*[:,—-]?\s*(что\s+)?", re.I)


def _next_weekday(today: date, wd: int) -> date:
    """Ближайший такой день недели после сегодняшнего."""
    days = (wd - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def _parse(text: str, today: date) -> tuple[date | None, tuple[int, int] | None]:
    t = text.lower()
    rules = [
        (r"\bпослезавтра\b", lambda m: today + timedelta(days=2)),
        (r"\bзавтра\b", lambda m: today + timedelta(days=1)),
        (r"\bсегодня\b", lambda m: today),
        (r"\bна\s+выходных\b", lambda m: today if today.weekday() == 5 else _next_weekday(today, 5)),
        (r"\bна\s+(этой\s+)?неделе\b", lambda m: today + timedelta(days=6 - today.weekday())),
        (r"\bчерез\s+(\d{1,2})\s+(день|дня|дней)\b", lambda m: today + timedelta(days=int(m.group(1)))),
        (r"\bчерез\s+неделю\b", lambda m: today + timedelta(days=7)),
        (r"\b(во?\s+)(" + "|".join(WEEKDAYS) + r")\b", lambda m: _next_weekday(today, WEEKDAYS[m.group(2)])),
        (r"\b(до\s+)?(\d{1,2})\.(\d{1,2})(\.(\d{2,4}))?\b", None),
    ]
    for pattern, fn in rules:
        m = re.search(pattern, t)
        if not m:
            continue
        if fn is None:   # дата цифрами
            d, mo = int(m.group(2)), int(m.group(3))
            y = int(m.group(5)) if m.group(5) else today.year
            if y < 100:
                y += 2000
            try:
                due = date(y, mo, d)
            except ValueError:
                continue
            if not m.group(5) and due < today:
                due = date(y + 1, mo, d)
            return due, m.span()
        return fn(m), m.span()
    return None, None


def parse_promise(text: str, today: date) -> tuple[str, date | None]:
    """Возвращает (текст обещания без «обещал» и без даты, срок или None)."""
    body = PREFIX.sub("", text.strip(), count=1)
    due, span = _parse(body, today)
    if span:
        body = (body[:span[0]] + body[span[1]:])
    body = re.sub(r"\s{2,}", " ", body).strip(" ,.—-")
    if body:
        body = body[0].upper() + body[1:]
    return body, due


def due_label(due: date | None, today: date) -> str:
    """Срок по-человечески: «сегодня», «завтра», «в пт 07.11», «просрочено на 2 дн»."""
    if due is None:
        return "без срока"
    delta = (due - today).days
    if delta < 0:
        return f"просрочено на {-delta} дн"
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    wd = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][due.weekday()]
    return f"{wd} {due:%d.%m}"
