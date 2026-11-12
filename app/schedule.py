"""
📚 Расписание пар из Apple Календаря (публичная ссылка webcal://…).

Сервер сам скачивает календарь раз в несколько часов, разворачивает повторы (RRULE, исключения, перенесённые пары)
в конкретные пары по дням и хранит их в sched_events. Отсюда:
  • лента «сейчас / дальше» и пары дня — в приложении и боте;
  • учёт сил: часы пар + дорога вычитаются из «часов на дела»;
  • «🚇 пора выходить» и «🎉 пару отменили / перенесли».
"""

import ipaddress
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

SCHEMA = """
CREATE TABLE IF NOT EXISTS sched_events (
    key      TEXT PRIMARY KEY,             -- uid | начало
    uid      TEXT    NOT NULL,
    day      TEXT    NOT NULL,
    start    TEXT    NOT NULL,             -- HH:MM по местному времени
    end      TEXT    NOT NULL,
    allday   INTEGER NOT NULL DEFAULT 0,
    title    TEXT    NOT NULL,
    location TEXT    NOT NULL DEFAULT '',
    note     TEXT    NOT NULL DEFAULT '',
    status   TEXT    NOT NULL DEFAULT 'ok',   -- ok / cancelled
    seen     TEXT                             -- метка последней синхронизации, в которой пара была
);
CREATE INDEX IF NOT EXISTS idx_sched_day ON sched_events(day);
"""

WINDOW_PAST = 1          # дней назад, которые обновляем
WINDOW_AHEAD = 150       # дней вперёд — до конца семестра с запасом
NOTICE_DAYS = 14         # об отменах и переносах сообщаем только на ближайшие две недели
KEEP_DAYS = 200          # сколько хранить прошедшие пары (к ним будут привязаны контрольные)
MAX_BYTES = 5_000_000
SYNC_EVERY_H = 3


class SchedError(Exception):
    pass


def normalize_url(url: str) -> str:
    """webcal:// → https://; только внешние https-адреса (без localhost и IP), чтобы сервер не ходил куда не надо."""
    url = (url or "").strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise SchedError("Нужна ссылка вида webcal://… или https://… на опубликованный календарь")
    host = p.hostname.lower()
    try:
        ipaddress.ip_address(host)
        raise SchedError("Нужна ссылка с именем сайта, а не IP-адресом")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal") or "." not in host:
        raise SchedError("Такой адрес не подходит")
    return url


def mask_url(url: str) -> str:
    if not url:
        return ""
    p = urlparse(url)
    return f"{p.hostname}/…{url[-6:]}"


def _hm(t: time | datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _mins(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def clean_title(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:120] or "Пара"


def parse_ics(text: str | bytes, start: date, end: date, tz) -> list[dict]:
    """Развернуть календарь в пары по дням в окне [start, end]."""
    import icalendar
    import recurring_ical_events
    try:
        cal = icalendar.Calendar.from_ical(text)
    except Exception as e:
        raise SchedError(f"Это не похоже на календарь ({type(e).__name__})")
    try:
        events = recurring_ical_events.of(cal).between(start, end + timedelta(days=1))
    except Exception as e:
        raise SchedError(f"Не получилось разобрать повторы в календаре ({type(e).__name__})")
    out = []
    for ev in events:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s = ev.get("DTSTART")
        if s is None:
            continue
        s = s.dt
        e = ev.get("DTEND")
        if e is not None:
            e = e.dt
        elif ev.get("DURATION") is not None:
            e = s + ev.get("DURATION").dt
        else:
            e = s
        uid = str(ev.get("UID", "")) or clean_title(str(ev.get("SUMMARY", "")))
        base = {"uid": uid, "title": clean_title(str(ev.get("SUMMARY", ""))),
                "location": re.sub(r"\s+", " ", str(ev.get("LOCATION", "") or "")).strip()[:120],
                "note": str(ev.get("DESCRIPTION", "") or "").strip()[:300]}
        if isinstance(s, datetime):
            s = s.astimezone(tz) if s.tzinfo else s.replace(tzinfo=tz)
            e = e.astimezone(tz) if isinstance(e, datetime) and e.tzinfo else \
                (e.replace(tzinfo=tz) if isinstance(e, datetime) else s)
            if not start <= s.date() <= end:
                continue
            if e.date() != s.date():                     # через полночь — обрезаем днём начала
                e = s.replace(hour=23, minute=59)
            out.append({**base, "key": f"{uid}|{s.strftime('%Y-%m-%dT%H:%M')}", "day": s.date().isoformat(),
                        "start": _hm(s), "end": _hm(max(e, s)), "allday": 0})
        else:                                             # на весь день (зачётная неделя и т. п.) — на каждый день
            last = (e if isinstance(e, date) and e > s else s + timedelta(days=1)) - timedelta(days=1)
            d = s
            while d <= min(last, s + timedelta(days=31)):
                if start <= d <= end:
                    out.append({**base, "key": f"{uid}|{d.isoformat()}", "day": d.isoformat(), "start": "00:00",
                                "end": "23:59", "allday": 1})
                d += timedelta(days=1)
    return out


class Schedule:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    # ---------- настройки ----------

    @property
    def url(self) -> str:
        return self.g.get_setting("sched_url", "")

    @property
    def commute_min(self) -> int:
        """Дорога туда-обратно в дни с парами, минут."""
        return int(self.g.get_setting("sched_commute", "180"))

    def settings(self) -> dict:
        return {"connected": bool(self.url), "url_masked": mask_url(self.url), "commute_min": self.commute_min,
                "leave": self.g.get_setting("sched_leave", "1") == "1",
                "last_sync": self.g.get_setting("sched_last_sync", ""),
                "last_error": self.g.get_setting("sched_last_error", ""),
                "count": self.conn.execute("SELECT COUNT(*) FROM sched_events WHERE status='ok' AND day >= ?",
                                           (date.today().isoformat(),)).fetchone()[0]}

    def save_settings(self, url: str | None = None, commute_min: int | None = None, leave: bool | None = None) -> dict:
        if url is not None:
            if url.strip() == "":
                self.g.set_setting("sched_url", "")
                self.conn.execute("DELETE FROM sched_events")
                self.conn.commit()
            else:
                self.g.set_setting("sched_url", normalize_url(url))
                self.g.set_setting("sched_last_sync", "")
        if commute_min is not None:
            if not 0 <= commute_min <= 600:
                raise SchedError("Дорога — от 0 до 600 минут")
            self.g.set_setting("sched_commute", str(commute_min))
        if leave is not None:
            self.g.set_setting("sched_leave", "1" if leave else "0")
        return self.settings()

    # ---------- синхронизация ----------

    async def fetch(self) -> bytes:
        import aiohttp
        if not self.url:
            raise SchedError("Расписание не подключено")
        timeout = aiohttp.ClientTimeout(total=25)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(self.url, headers={"User-Agent": "LifeGame-calendar/1.0"},
                                 allow_redirects=True, max_redirects=3) as r:
                    if r.status != 200:
                        raise SchedError(f"Календарь ответил {r.status} — проверь, что он всё ещё общий")
                    data = await r.content.read(MAX_BYTES + 1)
        except SchedError:
            raise
        except Exception as e:
            raise SchedError(f"Не достучался до календаря ({type(e).__name__})")
        if len(data) > MAX_BYTES:
            raise SchedError("Календарь слишком большой")
        return data

    def apply(self, text: str | bytes, today: date) -> dict:
        """Обновить пары из текста календаря. Возвращает, что отменили / перенесли / добавили на ближайшие дни."""
        start, end = today - timedelta(days=WINDOW_PAST), today + timedelta(days=WINDOW_AHEAD)
        events = parse_ics(text, start, end, self.g.tz)
        had = self.conn.execute("SELECT COUNT(*) FROM sched_events WHERE status='ok' AND day >= ?",
                                (today.isoformat(),)).fetchone()[0]
        if not events and had:
            raise SchedError("Календарь пришёл пустым — оставил старое расписание")
        first = self.g.get_setting("sched_last_sync", "") == ""
        stamp = datetime.now().isoformat(timespec="seconds")
        old = {r["key"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM sched_events WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}
        added = []
        for e in events:
            if e["key"] not in old and not first:
                added.append(e)
            self.conn.execute(
                "INSERT INTO sched_events (key, uid, day, start, end, allday, title, location, note, status, seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?) ON CONFLICT(key) DO UPDATE SET day=excluded.day, "
                "start=excluded.start, end=excluded.end, allday=excluded.allday, title=excluded.title, "
                "location=excluded.location, note=excluded.note, status='ok', seen=excluded.seen",
                (e["key"], e["uid"], e["day"], e["start"], e["end"], e["allday"], e["title"], e["location"],
                 e["note"], stamp))
        soon = (today + timedelta(days=NOTICE_DAYS)).isoformat()
        gone = []
        new_keys = {e["key"] for e in events}
        marked = {r["key"] for r in self.conn.execute("SELECT key FROM sched_marks WHERE status='active'")}
        for k, r in old.items():
            if r["status"] != "ok" or k in new_keys:
                continue
            if (today.isoformat() <= r["day"] <= soon or k in marked) and not r["allday"]:
                self.conn.execute("UPDATE sched_events SET status='cancelled' WHERE key=?", (k,))
                gone.append(r)
            elif r["day"] >= today.isoformat():
                self.conn.execute("DELETE FROM sched_events WHERE key=?", (k,))
        self.conn.execute("DELETE FROM sched_events WHERE day < ?",
                          ((today - timedelta(days=KEEP_DAYS)).isoformat(),))
        # перенос: та же пара (uid) пропала и появилась в другое время в ближайшие дни
        moved, cancelled = [], []
        new_soon = [e for e in added if today.isoformat() <= e["day"] and not e["allday"]]
        for r in gone:
            twin = next((e for e in new_soon if e["uid"] == r["uid"] or
                         (e["title"] == r["title"] and abs((date.fromisoformat(e["day"]) -
                                                            date.fromisoformat(r["day"])).days) <= 7)), None)
            mark = self.conn.execute("SELECT kind FROM sched_marks WHERE key=? AND status='active'",
                                     (r["key"],)).fetchone()
            if twin:
                new_soon.remove(twin)
                self.g.study.moved(r["key"], twin)
                self.conn.execute("DELETE FROM sched_events WHERE key=?", (r["key"],))
                moved.append({"old": r, "new": twin, "mark": mark["kind"] if mark else None})
            else:
                cancelled.append({**r, "mark": mark["kind"] if mark else None})
        self.g.set_setting("sched_last_sync", stamp)
        self.g.set_setting("sched_last_error", "")
        self.conn.commit()
        new_soon = [e for e in new_soon if e["day"] <= soon]
        return {"count": len(events), "cancelled": cancelled, "moved": moved, "added": new_soon}

    async def sync(self, today: date) -> dict:
        try:
            data = await self.fetch()
            return self.apply(data, today)
        except SchedError as e:
            self.g.set_setting("sched_last_error", str(e))
            raise

    def due(self, now: datetime) -> bool:
        if not self.url:
            return False
        last = self.g.get_setting("sched_last_sync", "")
        if not last:
            return True
        try:
            return now.replace(tzinfo=None) - datetime.fromisoformat(last) >= timedelta(hours=SYNC_EVERY_H)
        except ValueError:
            return True

    # ---------- чтение ----------

    def day(self, d: date, with_cancelled: bool = True) -> list[dict]:
        from .study import parse_title, suggest_kind
        q = "SELECT * FROM sched_events WHERE day = ?" + ("" if with_cancelled else " AND status='ok'")
        rows = [dict(r) for r in self.conn.execute(q + " ORDER BY allday DESC, start", (d.isoformat(),))]
        marks = {r["key"]: r["id"] for r in self.conn.execute(
            "SELECT id, key FROM sched_marks WHERE status='active' AND day = ?", (d.isoformat(),))}
        for r in rows:
            r["minutes"] = 0 if r["allday"] else max(0, _mins(r["end"]) - _mins(r["start"]))
            r.update(parse_title(r["title"]))
            if not r["location"] and r["room"]:
                r["location"] = f"ауд. {r['room']}"
            r["suggest"] = suggest_kind(r["ptype"])
            r["mark"] = self.g.study.get(marks[r["key"]]) if r["key"] in marks else None
        return rows

    def pairs(self, d: date) -> list[dict]:
        return [r for r in self.day(d, with_cancelled=False) if not r["allday"]]

    def busy(self, d: date) -> dict:
        """Сколько сил съедают пары: от начала первой до конца последней (окна между парами — тоже вуз) + дорога."""
        ps = self.pairs(d)
        if not ps:
            return {"pairs": 0, "span_min": 0, "class_min": 0, "commute_min": 0, "total_min": 0,
                    "first": None, "last": None}
        span = _mins(ps[-1]["end"]) - _mins(ps[0]["start"])
        cls = sum(p["minutes"] for p in ps)
        com = self.commute_min
        return {"pairs": len(ps), "span_min": span, "class_min": cls, "commute_min": com, "total_min": span + com,
                "first": ps[0]["start"], "last": ps[-1]["end"]}

    def now_next(self, now: datetime) -> dict:
        d = now.date()
        hm = _hm(now)
        ps = self.pairs(d)
        cur = next((p for p in ps if p["start"] <= hm < p["end"]), None)
        nxt = next((p for p in ps if p["start"] > hm), None)
        if nxt is None:                                   # сегодня всё — ближайшие пары на неделе
            for i in range(1, 8):
                later = self.pairs(d + timedelta(days=i))
                if later:
                    nxt = later[0]
                    break
        left = _mins(cur["end"]) - _mins(hm) if cur else None
        until = (_mins(nxt["start"]) - _mins(hm)) if nxt and nxt["day"] == d.isoformat() else None
        return {"now": cur, "next": nxt, "now_left_min": left, "next_in_min": until}

    def leave_at(self, d: date) -> tuple[str, dict] | None:
        """Когда выходить: начало первой пары минус дорога в одну сторону."""
        ps = self.pairs(d)
        if not ps or not self.commute_min:
            return None
        m = _mins(ps[0]["start"]) - self.commute_min // 2
        if m < 0:
            return None
        return f"{m // 60:02d}:{m % 60:02d}", ps[0]

    def next_days(self, today: date, n: int = 7) -> list[dict]:
        return [{"day": (today + timedelta(days=i)).isoformat(), "pairs": self.day(today + timedelta(days=i))}
                for i in range(n)]
