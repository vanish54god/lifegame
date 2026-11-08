"""
📅 Обязательное по ячейкам: у каждого платежа и каждого 🎁 фонда — свои деньги.

Как это работает:
  • пришли деньги → бот сначала закрывает платежи, которые наступят до следующих денег (ровно сколько нужно,
    лишнего не берёт), и кладёт в фонды их долю по графику;
  • плюс каждый раз 10% нового дохода уходит «на следующий раз»: в платежи, до которых ещё далеко,
    и на второй платёж вперёд (двойной запас). Когда всё с запасом — 10% не берутся;
  • деньги в «Обязательном» без ячейки — общий запас; бот сам разносит его по ячейкам;
  • ячейку можно пополнить руками из любого конверта.

Статус ячейки (подсветка):
  double — 🟢🟢 оплачено и следующий тоже;  ok — 🟢 на платёж хватает;
  progress — 🟡 копится, время есть;        late — 🔴 не хватает к сроку.
"""

from collections import defaultdict
from datetime import date, timedelta

from .envelopes import ENVS, EnvError
from .finance import CATS, OUT_KEYS, _add_months, guess_cat, rub

FUND_GRACE = 7          # столько дней после даты фонда из него ещё можно тратить
TASK_DAYS = 14          # за сколько дней закинуть в банк «выбрать подарок»
TAKE_ORDER = ("want", "me", "rel")
FLEX_SHARE = 50         # фонды по графику + запас забирают не больше половины того, что осталось после срочного   # если на платёж не хватает — откуда добираем после запаса и неразложенных


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:          # 29 февраля
        return d.replace(year=d.year + 1, day=28)


def _ceil100(k: int) -> int:
    """Округлить вверх до рубля."""
    return -(-k // 100) * 100


class Obligations:
    def __init__(self, env):
        self.env = env
        self.g = env.g
        self.fin = env.fin
        self.conn = env.conn

    # ---------- настройки ----------

    @property
    def ahead_pct(self) -> int:
        return int(self.g.get_setting("env_ahead_pct", "10"))

    def horizon(self, today: date) -> tuple[date, int]:
        """До какого дня закрываем платежи сейчас: до следующих денег (или на месяц вперёд)."""
        st = self.env.settings()
        days, nxt = self.env.days_left(today)
        h = 30 if st["reserve"] == "month" else (max(days, 7) if nxt else 30)
        return today + timedelta(days=h), h

    # ---------- деньги по ячейкам ----------

    def balances(self) -> dict:
        """{slot: деньги}; ключ None — общий запас «Обязательного»."""
        out: dict = defaultdict(int)
        for r in self.conn.execute("SELECT slot, SUM(amount) s FROM env_moves WHERE env='oblig' GROUP BY slot"):
            out[r["slot"]] += r["s"]
        for r in self.conn.execute(
                "SELECT slot, SUM(amount) s FROM fin_tx WHERE kind='out' AND envelope='oblig' GROUP BY slot"):
            out[r["slot"]] -= r["s"]
        return out

    def slot_balance(self, slot: str | None) -> int:
        return self.balances().get(slot, 0)

    def _ins(self, env: str, slot: str | None, amount: int, day: date, note: str) -> None:
        self.conn.execute("INSERT INTO env_moves (day, env, amount, note, slot) VALUES (?, ?, ?, ?, ?)",
                          (day.isoformat(), env, amount, note, slot))

    def _transfer(self, src: str, slot: str | None, amount: int, day: date, note: str) -> None:
        """src: free (неразложенные) / buffer (общий запас) / me / rel / want / p<id> / f<id>."""
        if amount <= 0:
            return
        if src == "buffer":
            self._ins("oblig", None, -amount, day, note)
        elif src in ("me", "rel", "want"):
            self._ins(src, None, -amount, day, note)
        elif src != "free":
            self._ins("oblig", src, -amount, day, note)
        self._ins("oblig", slot, amount, day, note)

    def _available(self, src: str) -> int:
        if src == "free":
            return self.env.unallocated()
        if src == "buffer":
            return self.slot_balance(None)
        if src in ("me", "rel", "want"):
            return self.env.balance(src)
        return self.slot_balance(src)

    def _check_slot(self, slot: str) -> dict:
        if slot.startswith("p") and slot[1:].isdigit():
            p = self.fin.plan(int(slot[1:]))
            return {"title": p["title"], "active": p["active"]}
        if slot.startswith("f") and slot[1:].isdigit():
            f = self.fund(int(slot[1:]))
            return {"title": f["title"], "active": f["active"]}
        raise EnvError("Неизвестный платёж")

    def src_title(self, src: str) -> str:
        if src == "free":
            return "📥 неразложенные"
        if src == "buffer":
            return "📅 общий запас"
        if src in ENVS:
            return f"{ENVS[src][0]} {ENVS[src][1]}"
        return self._check_slot(src)["title"]

    def put(self, slot: str, amount: int, src: str, day: date) -> dict:
        """Докинуть руками на конкретный платёж или фонд."""
        info = self._check_slot(slot)
        if not info["active"]:
            raise EnvError("Этот платёж уже закрыт")
        if amount <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if src == slot:
            raise EnvError("Откуда и куда — одно и то же")
        if src not in ("free", "buffer", "me", "rel", "want"):
            self._check_slot(src)
        if amount > self._available(src):
            raise EnvError(f"В «{self.src_title(src)}» только {rub(max(0, self._available(src)))}")
        self._transfer(src, slot, amount, day, f"→ {info['title']}")
        self.g.set_setting("env_on", "1")
        self.conn.commit()
        self.env.refresh_today(day)
        return self.item(slot, day)

    def take(self, slot: str, amount: int, dst: str, day: date) -> dict:
        """Забрать деньги с платежа: в неразложенные, в общий запас или в конверт."""
        info = self._check_slot(slot)
        if amount <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if amount > self.slot_balance(slot):
            raise EnvError(f"На «{info['title']}» отложено только {rub(max(0, self.slot_balance(slot)))}")
        if dst not in ("free", "buffer", "me", "rel", "want"):
            raise EnvError("Куда: неразложенные / запас / конверт")
        self._ins("oblig", slot, -amount, day, f"← {info['title']}")
        if dst == "buffer":
            self._ins("oblig", None, amount, day, f"← {info['title']}")
        elif dst != "free":
            self._ins(dst, None, amount, day, f"← {info['title']}")
        self.conn.commit()
        self.env.refresh_today(day)
        return self.item(slot, day)

    def ensure(self, slot: str, need: int, day: date, note: str) -> list[dict]:
        """Сделать так, чтобы в ячейке было не меньше need: запас → неразложенные → Хотелки → Я → Отношения."""
        took = []
        short = need - self.slot_balance(slot)
        for src in ("buffer", "free", *TAKE_ORDER):
            if short <= 0:
                break
            x = min(short, max(0, self._available(src)))
            if x:
                self._transfer(src, slot, x, day, note)
                took.append({"src": src, "title": self.src_title(src), "amount": x})
                short -= x
        if short > 0:
            took.append({"src": "none", "title": "не хватило", "amount": short})
        return took

    # ---------- 🎁 фонды ----------

    def add_fund(self, title: str, target: int, due: date, today: date, repeat: str = "none",
                 category: str | None = None, remind: bool = True) -> dict:
        title = title.strip()
        if not title:
            raise EnvError("Назови фонд: «Новый год», «ДР Сони»…")
        if target <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if due < today:
            raise EnvError("Дата уже прошла")
        if repeat not in ("none", "year"):
            raise EnvError("Повтор: none / year")
        if category not in OUT_KEYS:
            category = guess_cat(title, "out")
            if category == "other":
                category = "gifts"
        cur = self.conn.execute(
            "INSERT INTO funds (title, target, due, repeat, category, remind, created_day) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title[:60], target, due.isoformat(), repeat, category, int(remind), today.isoformat()))
        self.conn.commit()
        self.sync(today)
        return self.item(f"f{cur.lastrowid}", today)

    def fund(self, fid: int) -> dict:
        row = self.conn.execute("SELECT * FROM funds WHERE id = ?", (fid,)).fetchone()
        if row is None:
            raise EnvError("Такого фонда нет")
        return dict(row)

    def funds(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM funds WHERE active = 1 ORDER BY due")]

    def edit_fund(self, fid: int, today: date, title: str | None = None, target: int | None = None,
                  due: date | None = None, repeat: str | None = None, remind: bool | None = None) -> dict:
        f = self.fund(fid)
        if target is not None and target <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if repeat is not None and repeat not in ("none", "year"):
            raise EnvError("Повтор: none / year")
        self.conn.execute("UPDATE funds SET title=?, target=?, due=?, repeat=?, remind=? WHERE id=?",
                          ((title or f["title"]).strip()[:60], target or f["target"],
                           due.isoformat() if due else f["due"], repeat or f["repeat"],
                           f["remind"] if remind is None else int(remind), fid))
        self.conn.commit()
        return self.item(f"f{fid}", today)

    def delete_fund(self, fid: int, today: date) -> None:
        """Удалить фонд: отложенное вернётся в неразложенные."""
        self.fund(fid)
        left = self.slot_balance(f"f{fid}")
        if left > 0:
            self._ins("oblig", f"f{fid}", -left, today, "фонд удалён")
        self.conn.execute("UPDATE funds SET active = 0 WHERE id = ?", (fid,))
        self.conn.commit()
        self.env.refresh_today(today)

    def fund_spent(self, f: dict) -> int:
        """Сколько уже потрачено из фонда в этом цикле (с начала копления)."""
        return self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='out' AND envelope='oblig' AND slot=? AND day >= ?",
            (f"f{f['id']}", f["created_day"])).fetchone()[0]

    def match_fund(self, category: str, day: date) -> int | None:
        """Трата по категории фонда около его даты — сразу из фонда (подарок на ДР → 🎁 «ДР Сони»)."""
        bal = self.balances()
        best = None
        for f in self.funds():
            left = (date.fromisoformat(f["due"]) - day).days
            if f["category"] == category and -FUND_GRACE <= left <= 21 and bal.get(f"f{f['id']}", 0) > 0:
                if best is None or left < best[0]:
                    best = (left, f["id"])
        return best[1] if best else None

    # ---------- картина целиком ----------

    @staticmethod
    def _dates(p: dict, n: int = 6) -> list[date]:
        due = date.fromisoformat(p["due"])
        if p["repeat"] == "month":
            return [_add_months(due, i) for i in range(n)]
        if p["repeat"] == "week":
            return [due + timedelta(days=7 * i) for i in range(n)]
        return [due]

    def items(self, today: date, bal: dict | None = None) -> list[dict]:
        until, hdays = self.horizon(today)
        bal = self.balances() if bal is None else bal
        out = []
        for p in self.fin.plans(today):
            slot, a = f"p{p['id']}", p["amount"]
            b = bal.get(slot, 0)
            rep = p["repeat"] != "none"
            dates = self._dates(p)
            n_now = sum(1 for d in dates if d <= until)
            need_total = a * n_now
            ok_line = max(a, need_total)
            goal = a * (max(n_now, 1) + 1) if rep else a
            if rep and b >= ok_line + a:
                status = "double"
            elif b >= ok_line:
                status = "ok"
            elif b < need_total:
                status = "late"
            else:
                status = "progress"
            out.append({
                "kind": "plan", "id": p["id"], "slot": slot, "title": p["title"], "emoji": p["emoji"],
                "category": p["category"], "amount": a, "due": p["due"], "days_left": p["days_left"],
                "repeat": p["repeat"], "balance": b, "need_total": need_total, "need": max(0, need_total - b),
                "goal": goal, "goal_left": max(0, goal - b), "status": status, "now": n_now > 0,
                "covered": max(0, b) // a if a else 0, "progress": max(0, min(100, round(100 * b / ok_line))),
                "dates": [d.isoformat() for d in dates],
            })
        for f in self.funds():
            slot, t = f"f{f['id']}", f["target"]
            b = bal.get(slot, 0)
            spent = self.fund_spent(f)
            have = b + spent                    # потраченное по назначению тоже считается набранным
            due = date.fromisoformat(f["due"])
            days_to = (due - today).days
            remaining = max(0, t - have)
            if due <= until or days_to <= 0:
                need = remaining
            else:
                need = min(remaining, _ceil100(remaining * hdays // days_to))
            start = date.fromisoformat(f["created_day"])
            span = max(1, (due - start).days)
            expected = t * min(1.0, max(0, (today - start).days) / span)
            if have >= t:
                status = "ok"
            elif days_to <= 3 or have < expected * 0.8:
                status = "late"
            else:
                status = "progress"
            out.append({
                "kind": "fund", "id": f["id"], "slot": slot, "title": f["title"], "emoji": "🎁",
                "category": f["category"], "amount": t, "target": t, "due": f["due"], "days_left": days_to,
                "repeat": f["repeat"], "remind": bool(f["remind"]), "balance": b, "spent": spent, "need_total": need,
                "need": need, "goal": t, "goal_left": remaining, "status": status, "now": due <= until,
                "progress": max(0, min(100, round(100 * have / t))) if t else 0,
                "per_week": _ceil100(remaining * 7 // days_to) if days_to > 0 else remaining,
                "spend": days_to <= 21, "ontime": f["ontime"],
            })
        return out

    def item(self, slot: str, today: date) -> dict:
        for i in self.items(today):
            if i["slot"] == slot:
                return i
        info = self._check_slot(slot)
        return {"slot": slot, "title": info["title"], "balance": self.slot_balance(slot), "status": "ok"}

    # ---------- раскладка ----------

    def allocate(self, amount: int, today: date, ahead_cap: int, items: list[dict] | None = None,
                 flex_share: int = FLEX_SHARE) -> dict:
        """Сколько из суммы отдать на каждый платёж и фонд. Ничего не меняет."""
        items = self.items(today) if items is None else items
        slots: dict = defaultdict(int)
        left = amount
        part = {"plan": 0, "fund": 0}
        # 1) срочное: платежи и фонды, у которых срок до следующих денег, — по дате, сколько бы ни было
        for i in sorted((i for i in items if i["need"] > 0 and i["now"]), key=lambda i: i["due"]):
            x = min(left, i["need"])
            if x:
                slots[i["slot"]] += x
                left -= x
                part[i["kind"]] += x
        # 2) фонды по графику и запас — не больше половины оставшегося: на жизнь должно остаться
        flex = left * flex_share // 100
        short = 0
        for i in sorted((i for i in items if i["need"] > 0 and not i["now"]), key=lambda i: i["due"]):
            x = min(flex, i["need"])
            short += i["need"] - x
            if x:
                slots[i["slot"]] += x
                left -= x
                flex -= x
                part[i["kind"]] += x
        # 3) «на следующий раз»: по кусочку на каждый будущий платёж, ближайшие первыми
        ahead, cap = 0, min(flex, max(0, ahead_cap))
        if cap > 0:
            chunks = []
            for i in items:
                have = i["balance"] + slots[i["slot"]]
                if i["kind"] == "fund":
                    room = i["goal_left"] - slots[i["slot"]]
                    if room > 0:
                        chunks.append((i["due"], i["slot"], room))
                    continue
                a = i["amount"]
                for k, d in enumerate(i["dates"]):
                    lo, hi = a * k, min(a * (k + 1), i["goal"])
                    if hi <= lo:
                        break
                    room = hi - max(lo, have)
                    if room > 0:
                        chunks.append((d, i["slot"], room))
            for _, slot, room in sorted(chunks):
                if cap <= 0:
                    break
                x = min(cap, room)
                slots[slot] += x
                cap -= x
                ahead += x
        return {"slots": {k: v for k, v in slots.items() if v}, "now": part["plan"], "funds": part["fund"],
                "ahead": ahead, "short": short}

    def distribute(self, today: date) -> int:
        """Общий запас «Обязательного» — сам по ячейкам: сначала то, что горит, потом на следующий раз."""
        buf = self.slot_balance(None)
        if buf <= 0:
            return 0
        al = self.allocate(buf, today, ahead_cap=buf, flex_share=100)
        moved = 0
        for slot, x in al["slots"].items():
            self._transfer("buffer", slot, x, today, "из запаса")
            moved += x
        if moved:
            self.conn.commit()
        return moved

    # ---------- жизнь фондов ----------

    def tick(self, today: date) -> list[dict]:
        """Фонд набрался — отметить; за 2 недели — задача в банк; прошла дата — закрыть или на следующий год."""
        events = []
        bal = self.balances()
        for f in self.funds():
            slot = f"f{f['id']}"
            due = date.fromisoformat(f["due"])
            b = bal.get(slot, 0)
            have = b + self.fund_spent(f)
            if f["full_day"] is None and have >= f["target"]:
                self.conn.execute("UPDATE funds SET full_day = ? WHERE id = ?", (today.isoformat(), f["id"]))
                events.append({"kind": "full", "fund": f})
            if f["remind"] and f["task_day"] != f["due"] and 0 <= (due - today).days <= TASK_DAYS:
                try:
                    self.g.planner.add_task(f"🎁 Выбрать и купить: {f['title']}", "bonus", today, difficulty=1,
                                            est_min=60, deadline=max(today, due - timedelta(days=2)))
                    events.append({"kind": "task", "fund": f})
                except Exception:       # банк недоступен — не мешаем финансам
                    pass
                self.conn.execute("UPDATE funds SET task_day = ? WHERE id = ?", (f["due"], f["id"]))
            if today > due + timedelta(days=FUND_GRACE):
                full_day = f["full_day"] or (today.isoformat() if have >= f["target"] else None)
                ontime = f["ontime"] + (1 if full_day and full_day <= f["due"] else 0)
                if f["repeat"] == "year":
                    # остаток остаётся в фонде — в следующем году нужно будет меньше
                    self.conn.execute("UPDATE funds SET due=?, created_day=?, full_day=NULL, ontime=? WHERE id=?",
                                      (_add_year(due).isoformat(), today.isoformat(), ontime, f["id"]))
                else:
                    if b > 0:
                        self._ins("oblig", slot, -b, today, "остаток фонда")
                    self.conn.execute("UPDATE funds SET active=0, ontime=? WHERE id=?", (ontime, f["id"]))
                events.append({"kind": "closed", "fund": f, "left": b})
        self.conn.commit()
        return events

    def sync(self, today: date) -> None:
        self.tick(today)
        self.distribute(today)

    # ---------- сводка ----------

    def summary(self, today: date) -> dict:
        self.sync(today)
        bal = self.balances()
        items = self.items(today, bal)
        until, _ = self.horizon(today)
        month = 0
        until30 = (today + timedelta(days=30)).isoformat()
        for i in items:
            if i["kind"] == "plan":
                month += i["amount"] if i["repeat"] == "month" else round(i["amount"] * 30 / 7) \
                    if i["repeat"] == "week" else (i["amount"] if i["due"] <= until30 else 0)
            else:
                months = max(1, round(max(1, i["days_left"]) / 30))
                month += i["goal_left"] // months
        need_now = sum(i["need_total"] if i["kind"] == "plan" else i["balance"] + i["need"]
                       for i in items if i["now"])
        gap = sum(i["need"] for i in items if i["now"])
        counts = defaultdict(int)
        for i in items:
            counts[i["status"]] += 1
        green = counts["ok"] + counts["double"]
        return {
            "items": items, "until": until.isoformat(), "month_total": month, "need_now": need_now,
            "reserved": sum(bal.values()), "buffer": bal.get(None, 0), "gap": gap,
            "green": green, "total": len(items), "late": counts["late"], "double": counts["double"],
            "all_ok": bool(items) and counts["late"] == 0 and gap == 0, "ahead_pct": self.ahead_pct,
            "month_gap": max(0, month - sum(bal.values())),
        }

    def counts(self, today: date) -> dict:
        ontime = self.conn.execute(
            "SELECT COALESCE(SUM(ontime), 0) + COALESCE(SUM(CASE WHEN active = 1 AND full_day IS NOT NULL "
            "AND full_day <= due THEN 1 ELSE 0 END), 0) FROM funds").fetchone()[0]
        out = {"funds_ontime": ontime, "allgreen": False, "double": False}
        if self.env.on:
            sm = self.summary(today)
            plans = [i for i in sm["items"] if i["kind"] == "plan" and i["repeat"] != "none"]
            out["allgreen"] = sm["all_ok"] and sm["total"] >= 3
            out["double"] = len(plans) >= 2 and all(i["status"] == "double" for i in plans)
        return out


def slot_label(conn, slot: str | None) -> tuple[str, str]:
    """Эмодзи и название ячейки — для подписи траты."""
    if slot and slot.startswith("f") and slot[1:].isdigit():
        r = conn.execute("SELECT title FROM funds WHERE id = ?", (int(slot[1:]),)).fetchone()
        return "🎁", r["title"] if r else "Фонд"
    if slot and slot.startswith("p") and slot[1:].isdigit():
        r = conn.execute("SELECT title, category FROM planned WHERE id = ?", (int(slot[1:]),)).fetchone()
        return (CATS[r["category"]].emoji if r and r["category"] in CATS else "📅"), r["title"] if r else "Платёж"
    return ENVS["oblig"]
