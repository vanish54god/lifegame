"""
💌 Конверты под нерегулярный доход.

Пришли деньги → раскладываем:
  1. 📅 Обязательное — по ячейкам (obligations.py): платежи до следующих денег, 🎁 фонды по графику
     и 10% «на следующий раз»;
  2. 🏦 Копилка — процент сразу в накопления (откладываешь первым, а не «что останется»);
  3. остаток по долям: 🧍 Я / ❤️ Отношения / 🎯 Хотелки.

Лимит на день считается сам: (Я + Отношения) ÷ дней до следующих денег.
Снимок лимита фиксируется на день; день в лимите → +20 XP.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta


class EnvError(Exception):
    """Ошибка, которую можно показать как есть."""


ENVS = {
    "oblig": ("📅", "Обязательное"),
    "me": ("🧍", "Я"),
    "rel": ("❤️", "Отношения"),
    "want": ("🎯", "Хотелки"),
}
SPEND_ENVS = ("me", "rel", "want")
DAILY_ENVS = ("me", "rel")          # из них считается лимит на день; хотелки — отдельный котёл

# В какой конверт по умолчанию попадает трата (поправить можно кнопкой)
CAT_TO_ENV = {
    "food": "me", "transport": "me", "study": "me", "health": "me", "sport": "me", "home": "me",
    "subs": "me", "other": "me",
    "cafe": "rel", "fun": "rel", "gifts": "rel",
    "shop": "want",
}
DAY_XP = 20


def default_envelope(category: str | None) -> str:
    return CAT_TO_ENV.get(category or "", "me")


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


class Envelopes:
    def __init__(self, game):
        self.g = game
        self.fin = game.fin
        self.conn = game.conn
        from .obligations import Obligations
        self.ob = Obligations(self)

    # ---------- настройки ----------

    def _s(self, key: str, default: str) -> str:
        return self.g.get_setting(key, default)

    @property
    def on(self) -> bool:
        return self._s("env_on", "0") == "1"

    def settings(self) -> dict:
        return {
            "shares": {k: int(self._s(f"env_share_{k}", d)) for k, d in (("me", "40"), ("rel", "40"), ("want", "20"))},
            "save_pct": int(self._s("env_save_pct", "10")),
            "save_target": int(self._s("env_save_target", "0") or 0),
            "horizon": int(self._s("env_horizon", "14")),
            "reserve": self._s("env_reserve", "next"),     # next — до следующих денег, month — на месяц вперёд
            "ahead_pct": int(self._s("env_ahead_pct", "10")),   # с каждого дохода — на следующие платежи
        }

    def save_settings(self, shares: dict | None = None, save_pct: int | None = None,
                      save_target: int | None = None, horizon: int | None = None, reserve: str | None = None,
                      ahead_pct: int | None = None) -> dict:
        if ahead_pct is not None:
            if not 0 <= ahead_pct <= 50:
                raise EnvError("На следующие платежи — от 0 до 50%")
            self.g.set_setting("env_ahead_pct", str(ahead_pct))
        if reserve is not None:
            if reserve not in ("next", "month"):
                raise EnvError("Резерв: next / month")
            self.g.set_setting("env_reserve", reserve)
        if shares is not None:
            vals = {k: int(shares.get(k, 0)) for k in SPEND_ENVS}
            if any(v < 0 for v in vals.values()) or sum(vals.values()) != 100:
                raise EnvError("Доли конвертов должны в сумме давать 100%")
            for k, v in vals.items():
                self.g.set_setting(f"env_share_{k}", str(v))
        if save_pct is not None:
            if not 0 <= save_pct <= 80:
                raise EnvError("В копилку — от 0 до 80%")
            self.g.set_setting("env_save_pct", str(save_pct))
        if save_target is not None:
            if save_target:
                self.fin.saving(save_target)        # проверка, что такая копилка есть
            self.g.set_setting("env_save_target", str(save_target))
        if horizon is not None:
            if not 3 <= horizon <= 45:
                raise EnvError("Горизонт — от 3 до 45 дней")
            self.g.set_setting("env_horizon", str(horizon))
        return self.settings()

    # ---------- балансы ----------

    def balance(self, env: str) -> int:
        put = self.conn.execute("SELECT COALESCE(SUM(amount), 0) FROM env_moves WHERE env = ?", (env,)).fetchone()[0]
        spent = self.conn.execute("SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='out' AND envelope = ?",
                                  (env,)).fetchone()[0]
        return put - spent

    def balances(self) -> dict:
        return {k: self.balance(k) for k in ENVS}

    def unallocated(self) -> int:
        """Деньги, которые ещё не разложены по конвертам."""
        return self.fin.balance() - sum(self.balances().values())

    # ---------- ожидаемые поступления ----------

    def add_expected(self, title: str, amount: int, day: date, repeat: str = "none") -> dict:
        if not title.strip():
            raise EnvError("Назови поступление")
        if amount <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if repeat not in ("none", "month"):
            raise EnvError("Повтор: none / month")
        cur = self.conn.execute("INSERT INTO expected_income (title, amount, day, repeat) VALUES (?, ?, ?, ?)",
                                (title.strip()[:60], amount, day.isoformat(), repeat))
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM expected_income WHERE id = ?", (cur.lastrowid,)).fetchone())

    def delete_expected(self, eid: int) -> None:
        self.conn.execute("UPDATE expected_income SET active = 0 WHERE id = ?", (eid,))
        self.conn.commit()

    def expected(self, today: date) -> list[dict]:
        """Ближайшие поступления. Ежемесячные сами переезжают на следующий месяц, разовые — исчезают."""
        out = []
        for r in self.conn.execute("SELECT * FROM expected_income WHERE active = 1"):
            e = dict(r)
            d = date.fromisoformat(e["day"])
            if e["repeat"] == "month":
                while d < today:
                    d = _add_months(d, 1)
            elif d < today:
                continue
            e["next"] = d.isoformat()
            e["days_left"] = (d - today).days
            out.append(e)
        out.sort(key=lambda e: e["next"])
        return out

    def next_income(self, today: date) -> dict | None:
        ex = self.expected(today)
        return ex[0] if ex else None

    # ---------- раскладка ----------

    def plan(self, amount: int, today: date) -> dict:
        """Как разложить сумму. Деньги не трогает (только разносит общий запас «Обязательного» по ячейкам)."""
        if amount <= 0:
            raise EnvError("Нечего раскладывать")
        st = self.settings()
        self.ob.sync(today)
        until, _ = self.ob.horizon(today)
        al = self.ob.allocate(amount, today, ahead_cap=round(amount * st["ahead_pct"] / 100))
        oblig = sum(al["slots"].values())
        rest = amount - oblig
        save = round(rest * st["save_pct"] / 100)
        rest -= save
        parts = {k: rest * st["shares"][k] // 100 for k in SPEND_ENVS}
        parts["me"] += rest - sum(parts.values())          # копейки-остаток — в «Я»
        return {"amount": amount, "oblig": oblig, "oblig_now": al["now"], "funds": al["funds"], "sched": al["sched"], "ahead": al["ahead"],
                "slots": al["slots"], "funds_short": al["short"], "save": save, **parts, "save_pct": st["save_pct"], "ahead_pct": st["ahead_pct"],
                "shares": st["shares"], "until": until.isoformat()}

    def apply(self, amount: int, today: date, plan: dict | None = None) -> dict:
        """Разложить. Копилка — настоящий перевод в накопления, обязательное — по ячейкам, остальное — в конверты."""
        if amount > self.unallocated():
            raise EnvError("Столько неразложенных денег нет")
        p = plan or self.plan(amount, today)
        if sum(p[k] for k in ("oblig", "save", *SPEND_ENVS)) != amount or sum(p["slots"].values()) != p["oblig"]:
            raise EnvError("Части не сходятся с суммой")
        before = self.g._achieved(today)
        for slot, x in p["slots"].items():
            self.ob._ins("oblig", slot, x, today, "раскладка")
        for env in SPEND_ENVS:
            if p[env]:
                self.conn.execute("INSERT INTO env_moves (day, env, amount, note) VALUES (?, ?, ?, 'раскладка')",
                                  (today.isoformat(), env, p[env]))
        if p["save"]:
            self.fin.saving_move(self._save_target(), p["save"], today)
        self.g.set_setting("env_on", "1")
        self.conn.commit()
        self.ob.tick(today)
        self.refresh_today(today)
        new = [a for a in self.g.full_stats(today)["achievements"] if a["done"] and a["key"] not in before]
        return {**p, "balances": self.balances(), "new_achievements": new}

    def _save_target(self) -> int:
        sid = self.settings()["save_target"]
        alive = {s["id"] for s in self.fin.savings()}
        if sid in alive:
            return sid
        sid = next(iter(alive), None) or self.fin.add_saving("Подушка")["id"]
        self.g.set_setting("env_save_target", str(sid))
        return sid

    def obligations(self, today: date) -> dict:
        """Обязательное целиком: каждый платёж и фонд со своими деньгами и подсветкой."""
        return self.ob.summary(today)

    def release(self, amount: int, today: date, note: str) -> None:
        """Забрать деньги из «Обязательного»: сначала общий запас, потом то, до чего дальше всего."""
        bal = self.ob.balances()
        left = amount
        x = min(left, max(0, bal.get(None, 0)))
        if x:
            self.ob._ins("oblig", None, -x, today, note)
            left -= x
        items = self.ob.items(today, bal)
        later = sorted((i for i in items if not i["now"]), key=lambda i: i["due"], reverse=True)
        soon = sorted((i for i in items if i["now"]), key=lambda i: i["due"], reverse=True)
        for i in later + soon:
            if left <= 0:
                break
            x = min(left, max(0, i["balance"]))
            if x:
                self.ob._ins("oblig", i["slot"], -x, today, note)
                left -= x
        if left > 0:
            self.ob._ins("oblig", None, -left, today, note)

    def reset(self, today: date) -> dict:
        """Обнулить конверты (деньги вернутся в «неразложенные») — если всё разъехалось, разложить заново."""
        for env, bal in self.balances().items():
            if bal and env != "oblig":
                self.conn.execute("INSERT INTO env_moves (day, env, amount, note) VALUES (?, ?, ?, 'сброс')",
                                  (today.isoformat(), env, -bal))
        for slot, bal in self.ob.balances().items():
            if bal:
                self.ob._ins("oblig", slot, -bal, today, "сброс")
        self.conn.commit()
        self.refresh_today(today)
        return self.balances()

    def redistribute(self, today: date, do: bool = False) -> dict:
        """🔄 Разложить заново ВСЕ деньги из конвертов и ячеек — как будто они только что пришли.
        Копилки не трогаем и в копилку не откладываем (это уже сделано). do=False — только показать «было → станет»."""
        st = self.settings()
        self.ob.tick(today)
        bal = self.balances()
        free = self.unallocated()
        total = free + sum(bal.values())
        if total <= 0:
            raise EnvError("Нечего перераспределять — в конвертах пусто")
        slots_before = self.ob.balances()
        items = self.ob.items(today, bal={})                 # как будто во всех ячейках пусто
        al = self.ob.allocate(total, today, ahead_cap=round(total * st["ahead_pct"] / 100), items=items)
        oblig = sum(al["slots"].values())
        rest = total - oblig
        parts = {k: rest * st["shares"][k] // 100 for k in SPEND_ENVS}
        parts["me"] += rest - sum(parts.values())
        after = {"oblig": oblig, **parts, "free": 0}
        before = {**bal, "free": free}
        lines = [{"slot": i["slot"], "title": i["title"], "emoji": i["emoji"], "before": slots_before.get(i["slot"], 0),
                  "after": al["slots"].get(i["slot"], 0)} for i in items]
        res = {"total": total, "before": before, "after": after, "items": lines, "buffer_before": slots_before.get(None, 0),
               "funds_short": al["short"], "now": al["now"], "funds": al["funds"], "sched": al["sched"],
               "ahead": al["ahead"]}
        if not do:
            return res
        self.reset(today)
        for slot, x in al["slots"].items():
            self.ob._ins("oblig", slot, x, today, "перераспределение")
        for env in SPEND_ENVS:
            if parts[env]:
                self.conn.execute("INSERT INTO env_moves (day, env, amount, note) VALUES (?, ?, ?, 'перераспределение')",
                                  (today.isoformat(), env, parts[env]))
        self.g.set_setting("env_on", "1")
        self.conn.commit()
        self.refresh_today(today)
        return {**res, "balances": self.balances(), "obligations": self.obligations(today)}

    def move(self, src: str, dst: str, amount: int, today: date) -> dict:
        """Переложить между конвертами; dst='save' — отправить в копилку."""
        if amount <= 0:
            raise EnvError("Сумма должна быть больше нуля")
        if src not in ENVS and src != "free":
            raise EnvError("Неизвестный конверт")
        if dst not in ENVS and dst != "save":
            raise EnvError("Неизвестный конверт")
        avail = self.unallocated() if src == "free" else self.balance(src)
        if amount > avail:
            raise EnvError("В конверте столько нет")
        if src == "oblig":
            self.release(amount, today, "перекладка")
        elif src != "free":
            self.conn.execute("INSERT INTO env_moves (day, env, amount, note) VALUES (?, ?, ?, 'перекладка')",
                              (today.isoformat(), src, -amount))
        if dst == "save":
            self.conn.commit()
            self.fin.saving_move(self._save_target(), amount, today)
        else:
            self.conn.execute("INSERT INTO env_moves (day, env, amount, note) VALUES (?, ?, ?, 'перекладка')",
                              (today.isoformat(), dst, amount))
        self.g.set_setting("env_on", "1")
        self.conn.commit()
        if dst == "oblig":
            self.ob.distribute(today)
        self.refresh_today(today)
        return self.balances()

    def set_tx_envelope(self, tx_id: int, env: str) -> dict:
        t = self.fin.tx(tx_id)
        if t["kind"] != "out" or t["source"] != "manual":
            raise EnvError("Конверт меняется только у обычных трат")
        if env.startswith("f") and env[1:].isdigit():          # 🎁 из фонда
            f = self.ob.fund(int(env[1:]))
            if not f["active"]:
                raise EnvError("Фонд уже закрыт")
            if t.get("slot") != env:
                took = self.ob.ensure(env, t["amount"], date.fromisoformat(t["day"]), f"трата: {t['note'] or f['title']}")
                if any(x["src"] == "none" for x in took):
                    self.conn.rollback()
                    raise EnvError(f"В фонде «{f['title']}» и в конвертах не хватает денег")
                self.conn.execute("UPDATE fin_tx SET envelope = 'oblig', slot = ? WHERE id = ?", (env, tx_id))
        elif env in SPEND_ENVS:
            self.conn.execute("UPDATE fin_tx SET envelope = ?, slot = NULL WHERE id = ?", (env, tx_id))
        else:
            raise EnvError("Конверт: Я / Отношения / Хотелки или фонд")
        self.conn.commit()
        self.refresh_today(date.fromisoformat(t["day"]))
        return self.fin.tx(tx_id)

    # ---------- лимит, прогноз, награды ----------

    def _spent(self, day: date, envs=DAILY_ENVS) -> int:
        q = f"SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='out' AND day = ? AND envelope IN ({','.join('?' * len(envs))})"
        return self.conn.execute(q, (day.isoformat(), *envs)).fetchone()[0]

    def days_left(self, today: date) -> tuple[int, dict | None]:
        nxt = self.next_income(today)
        if nxt:
            return max(1, nxt["days_left"]), nxt
        return self.settings()["horizon"], None

    def _calc_limit(self, today: date) -> int:
        days, _ = self.days_left(today)
        pool = sum(self.balance(k) for k in DAILY_ENVS) + self._spent(today)
        return max(0, pool // days // 100 * 100)        # целые рубли — без копеечного шума

    def refresh_today(self, today: date) -> None:
        """Пересчитать лимит на сегодня (после раскладки денег он может вырасти)."""
        if not self.on:
            return
        self.conn.execute("INSERT INTO fin_day_limit (day, lim) VALUES (?, ?) "
                          "ON CONFLICT(day) DO UPDATE SET lim = excluded.lim", (today.isoformat(), self._calc_limit(today)))
        self.conn.commit()

    def today_limit(self, today: date) -> int:
        row = self.conn.execute("SELECT lim FROM fin_day_limit WHERE day = ?", (today.isoformat(),)).fetchone()
        if row is None:
            lim = self._calc_limit(today)
            self.conn.execute("INSERT OR IGNORE INTO fin_day_limit (day, lim) VALUES (?, ?)", (today.isoformat(), lim))
            self.conn.commit()
            return lim
        return row["lim"]

    def avg_daily(self, today: date, days: int = 14) -> int:
        start = (today - timedelta(days=days)).isoformat()
        total = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='out' AND day >= ? AND day < ? "
            "AND envelope IN ('me','rel','want')", (start, today.isoformat())).fetchone()[0]
        return total // days

    def budget(self, today: date) -> dict:
        """Всё для экрана «Деньги»: сколько можно сегодня, до следующих денег, прогноз."""
        ob = self.obligations(today)
        bal = self.balances()
        days, nxt = self.days_left(today)
        lim = self.today_limit(today) if self.on else 0
        spent = self._spent(today)
        spendable = bal["me"] + bal["rel"]
        avg = self.avg_daily(today)
        forecast = spendable + bal["want"] - avg * days
        return {
            "on": self.on, "limit": lim, "spent_today": spent, "left_today": lim - spent,
            "days_left": days, "next_income": nxt, "spendable": spendable,
            "per_day_now": max(0, spendable // days // 100 * 100),
            "want": bal["want"], "oblig": bal["oblig"], "balances": bal,
            "unallocated": self.unallocated(), "avg_daily": avg, "forecast": forecast,
            "oblig_need": ob["need_now"], "oblig_month": ob["month_total"], "oblig_gap": ob["gap"],
            "oblig_green": ob["green"], "oblig_total": ob["total"], "oblig_late": ob["late"],
            "oblig_all_ok": ob["all_ok"],
            "saved_month": self.saved_month(today),
        }

    def settle(self, today: date) -> list[dict]:
        """Подвести итоги прошедших дней: в лимите — +20 XP. Можно звать сколько угодно раз."""
        out = []
        rows = self.conn.execute("SELECT * FROM fin_day_limit WHERE settled = 0 AND day < ?",
                                 (today.isoformat(),)).fetchall()
        for r in rows:
            d = date.fromisoformat(r["day"])
            spent = self._spent(d)
            ok = r["lim"] > 0 and spent <= r["lim"]
            if ok:
                saved = r["lim"] - spent
                now = datetime.now(self.g.tz).replace(tzinfo=None).isoformat(timespec="seconds")
                self.conn.execute(
                    "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'money', ?, ?, 'done', ?)",
                    (r["day"], f"💰 День в лимите · сэкономил {saved // 100} ₽", DAY_XP, now))
                out.append({"day": r["day"], "limit": r["lim"], "spent": spent, "saved": saved})
            self.conn.execute("UPDATE fin_day_limit SET settled = 1, spent = ? WHERE day = ?", (spent, r["day"]))
        if rows:
            self.conn.commit()
        return out

    def saved_month(self, today: date) -> int:
        """Сколько за месяц ушло в копилки (с учётом снятий)."""
        start = today.replace(day=1).isoformat()
        return self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fin_tx WHERE kind='move' AND source='saving' AND day >= ?",
            (start,)).fetchone()[0]

    def limit_streak(self, today: date) -> int:
        n, d = 0, today - timedelta(days=1)
        while True:
            r = self.conn.execute("SELECT lim, spent FROM fin_day_limit WHERE day = ?", (d.isoformat(),)).fetchone()
            if not r or r["spent"] is None or r["lim"] <= 0 or r["spent"] > r["lim"]:
                return n
            n += 1
            d -= timedelta(days=1)

    def learned_shares(self, today: date, days: int = 28) -> dict | None:
        """Доли по факту трат — подсказка, как поставить конверты под реальную жизнь."""
        start = (today - timedelta(days=days)).isoformat()
        rows = self.conn.execute("""SELECT envelope, SUM(amount) s, COUNT(*) n, MIN(day) first FROM fin_tx
            WHERE kind='out' AND source='manual' AND day >= ? AND envelope IN ('me','rel','want')
            GROUP BY envelope""", (start,)).fetchall()
        total = sum(r["s"] for r in rows)
        count = sum(r["n"] for r in rows)
        first = min((r["first"] for r in rows), default=None)
        if not total or count < 10 or not first or (today - date.fromisoformat(first)).days < 10:
            return None
        shares = {k: 0 for k in SPEND_ENVS}
        for r in rows:
            shares[r["envelope"]] = round(100 * r["s"] / total)
        shares["me"] += 100 - sum(shares.values())
        return {"shares": shares, "count": count, "since": first}

    def counts(self, today: date | None = None) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        out = {"allocations": q("SELECT COUNT(DISTINCT day || created_at) FROM env_moves WHERE note='раскладка'"),
               "saved_total": sum(s["current"] for s in self.fin.savings()), **self.ob.counts(today or date.today())}
        return out
