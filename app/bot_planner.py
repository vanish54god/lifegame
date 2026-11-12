"""
Банк заданий, таймер, темп, привычки, оценка дня и сезоны — в боте. Всё на кнопках.
"""

import re
from datetime import date, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message

from . import rules
from .life import LifeError, MONTHS
from .planner import PACE, PlanError

K_BANK = "🗃 Банк"


class BankNew(StatesGroup):
    title = State()
    sub_title = State()
    date_text = State()


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def short(text: str, n: int = 24) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def ddmm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def left_label(days: int | None) -> str:
    if days is None:
        return "без срока"
    if days < 0:
        return f"просрочено на {-days} дн"
    return {0: "сегодня", 1: "завтра"}.get(days, f"через {days} дн")


DEADLINE_ROWS = lambda prefix: [
    [Btn(text="Сегодня", callback_data=f"{prefix}:0"), Btn(text="Завтра", callback_data=f"{prefix}:1"),
     Btn(text="3 дня", callback_data=f"{prefix}:3")],
    [Btn(text="Неделя", callback_data=f"{prefix}:7"), Btn(text="2 недели", callback_data=f"{prefix}:14"),
     Btn(text="Месяц", callback_data=f"{prefix}:30")],
    [Btn(text="Без срока", callback_data=f"{prefix}:none"), Btn(text="📅 Дата", callback_data=f"{prefix}:other")],
]


def time_rows(prefix: str, skip: bool = True) -> list[list[Btn]]:
    p = rules.TIME_PRESETS
    rows = [[Btn(text=rules.fmt_min(m), callback_data=f"{prefix}:{m}") for m in p[:4]],
            [Btn(text=rules.fmt_min(m), callback_data=f"{prefix}:{m}") for m in p[4:]]]
    if skip:
        rows.append([Btn(text="Не знаю / пропустить", callback_data=f"{prefix}:0")])
    return rows


class PlanUI:
    def __init__(self, ui):
        self.ui, self.g = ui, ui.game
        self.p, self.life = ui.game.planner, ui.game.life

    def now(self) -> datetime:
        return datetime.now(self.ui.cfg.tz)

    # ---------- строки для экрана «Сегодня» ----------

    def start_by_line(self) -> str | None:
        sb = self.p.start_by(self.ui.today(), self.now())
        if not sb or not sb["remaining_min"]:
            if sb and sb["unknown"]:
                return f"⏱ У {sb['unknown']} квестов нет оценки времени — не могу посчитать, когда начинать"
            return None
        extra = f" (+{sb['unknown']} без оценки)" if sb["unknown"] else ""
        fix = f", с поправкой на твой темп ×{sb['factor']}" if sb["factor"] != 1.0 else ""
        if sb["too_late"]:
            return f"⏰ <b>Уже не успеть до {sb['bedtime']}</b>: осталось ~{rules.fmt_min(sb['remaining_min'])}{extra}. Выбери главное."
        if sb["late"]:
            return f"⏰ <b>Пора садиться!</b> Осталось ~{rules.fmt_min(sb['remaining_min'])}{extra}{fix}"
        return (f"⏰ Осталось ~{rules.fmt_min(sb['remaining_min'])}{extra}{fix}. "
                f"Чтобы лечь в {sb['bedtime']}, начни не позже <b>{sb['start']}</b>")

    def habit_block(self) -> tuple[list[str], list[list[Btn]]]:
        hs = self.life.habits(self.ui.today())
        if not hs:
            return [], []
        lines, row, rows = ["\n🔁 <b>Привычки</b>"], [], []
        for h in hs:
            prog = f"{h['week_count']}/{h['per_week']} на неделе" if h["per_week"] < 7 else ""
            streak = f"🔥{h['streak']} {h['unit']}" if h["streak"] else ""
            mark = "✅" if h["done_today"] else "▫️"
            lines.append(f"{mark} {h['emoji']} {escape(h['title'])} " + " · ".join(x for x in (prog, streak) if x))
            row.append(Btn(text=f"{'✅' if h['done_today'] else '▫️'} {h['emoji']} {short(h['title'], 14)}",
                           callback_data=f"hb:t:{h['id']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return lines, rows

    def timer_label(self, q) -> str:
        if q.timer_start:
            return f" ⏱{rules.fmt_min(max(1, q.elapsed() // 60))}"
        if q.timer_sec:
            return f" ⏸{rules.fmt_min(max(1, q.timer_sec // 60))}"
        return ""

    # ---------- банк ----------

    def bank(self) -> tuple[str, InlineKeyboardMarkup]:
        t = self.ui.today()
        tasks = self.p.tasks(t)
        lines, rows = ["🗃 <b>Банк заданий</b>", ""], []
        if not tasks:
            lines.append("Пусто. Всё, что надо сделать, складывай сюда — и голова свободна.")
        total = 0
        for x in tasks[:15]:
            total += x["rem_min"]
            when = left_label(x["days_left"])
            parts = f" · {x['progress']}% частей" if x["children"] else ""
            plan = " · 📅 в плане" if x["planned"] else ""
            est = f" · {rules.fmt_min(x['rem_min'])}" if x["rem_min"] else ""
            lines.append(f"{x['heat_emoji']} <b>{escape(x['title'])}</b>\n    {x['diff_emoji']} {when}{est}{parts}{plan}")
            rows.append([Btn(text=f"{x['heat_emoji']} {short(x['title'], 26)}", callback_data=f"bk:t:{x['id']}")])
        if len(tasks) > 15:
            lines.append(f"\n…и ещё {len(tasks) - 15} (все — в приложении)")
        if total:
            lines.append(f"\nВсего работы в банке: ~{rules.fmt_min(total)}")
        rows.append([Btn(text="➕ Задача", callback_data="bk:new"),
                     Btn(text="📅 Взять в завтра", callback_data="bk:pick:1")])
        rows.append([Btn(text="📅 Взять в сегодня", callback_data="bk:pick:0")])
        return "\n".join(lines), kb(*rows)

    def card(self, tid: int) -> tuple[str, InlineKeyboardMarkup]:
        t = self.p.task(tid, self.ui.today())
        lines = [f"{t['heat_emoji']} <b>{escape(t['title'])}</b>",
                 f"{t['cat_emoji']} {t['cat_title']} · {t['diff_emoji']} {t['diff_name']}"
                 + (f" · ⏱ {rules.fmt_min(t['est_min'])}" if t["est_min"] else ""),
                 f"Дедлайн: <b>{left_label(t['days_left'])}</b>" + (f" ({ddmm(t['deadline'])})" if t["deadline"] else "")
                 + f" · {t['heat_name']}"]
        if t["status"] == "done":
            lines.append(f"✅ Сделано {ddmm(t['done_day'])}")
        if t["planned"]:
            lines.append(f"📅 В плане на {ddmm(t['planned']['day'])}")
        rows = []
        if t["children"]:
            lines.append(f"\n<b>Части</b> ({t['progress']}%):")
            for c in t["children"]:
                m = "✅" if c["status"] == "done" else "📅" if c["planned"] else "▫️"
                lines.append(f"{m} {escape(c['title'])}" + (f" · {rules.fmt_min(c['est_min'])}" if c["est_min"] else ""))
                if c["status"] == "open":
                    rows.append([Btn(text=f"{m} {short(c['title'], 28)}", callback_data=f"bk:t:{c['id']}")])
        if t["status"] == "open" and not t["planned"] and not any(c["status"] == "open" for c in t["children"]):
            rows.append([Btn(text="📅 В завтра", callback_data=f"bk:s:{tid}:1"),
                         Btn(text="📅 В сегодня", callback_data=f"bk:s:{tid}:0"),
                         Btn(text="✅ Уже сделал", callback_data=f"bk:now:{tid}")])
        if t["status"] == "open" and not t["parent_id"]:
            rows.append([Btn(text="➕ Часть", callback_data=f"bk:sub:{tid}"),
                         Btn(text="⏰ Дедлайн", callback_data=f"bk:dl:{tid}")])
        rows.append([Btn(text="🗑 Удалить", callback_data=f"bk:del:{tid}"),
                     Btn(text="⬅️ Банк" if not t["parent_id"] else "⬅️ Задача",
                         callback_data="bk:list" if not t["parent_id"] else f"bk:t:{t['parent_id']}")])
        return "\n".join(lines), kb(*rows)

    def pick(self, off: int) -> tuple[str, InlineKeyboardMarkup]:
        t = self.ui.today()
        day = t + timedelta(days=off)
        items = self.p.schedulable(t)[:12]
        ld = self.p.load(day)
        lines = [f"📅 <b>Взять в {'сегодня' if off == 0 else 'завтра'}</b>", self.load_line(ld), ""]
        rows = []
        if not items:
            lines.append("В банке нечего брать 🎉")
        for x in items:
            name = f"{x['parent_title']}: {x['title']}" if x.get("parent_title") else x["title"]
            est = f" · {rules.fmt_min(x['est_min'])}" if x["est_min"] else ""
            lines.append(f"{x['heat_emoji']} {escape(name)} — {left_label(x['days_left'])}{est}")
            rows.append([Btn(text=f"{x['heat_emoji']} {short(name, 30)}", callback_data=f"bk:s:{x['id']}:{off}")])
        rows.append([Btn(text="⬅️ Банк", callback_data="bk:list")])
        return "\n".join(lines), kb(*rows)

    @staticmethod
    def load_line(ld: dict) -> str:
        txt = f"Нагрузка: <b>{rules.fmt_min(ld['real_min']) if ld['real_min'] else '0ч'}</b> из {rules.fmt_min(ld['capacity_min'])}"
        if ld["unknown"]:
            txt += f" (+{ld['unknown']} без оценки)"
        b = ld.get("busy") or {}
        if b.get("pairs"):
            txt += (f"\n📚 День с парами: {b['first']}–{b['last']} + дорога {rules.fmt_min(b['commute_min'])} — "
                    f"сил на квесты меньше")
        if ld["over"]:
            txt += "\n⚠️ <b>Перегруз.</b> Такой день не переживёт первую внеплановую задачу — убери что-нибудь."
        return txt

    def xp_choice(self, tid: int, off: int) -> tuple[str, InlineKeyboardMarkup]:
        t = self.p.task(tid, self.ui.today())
        base = t["suggested_xp"]
        opts = sorted({max(10, int(round(base * k / 10) * 10)) for k in (0.6, 1, 1.4, 2)})
        early = (f"\n⏳ До дедлайна далеко — получишь <b>+{int(rules.EARLY_BONUS * 100)}%</b> «заранее»"
                 if t["deadline"] and (date.fromisoformat(t["deadline"]) - (self.ui.today() + timedelta(days=off))).days >= rules.EARLY_DAYS else "")
        text = (f"💰 Сколько XP за «{escape(t['title'])}»?\n"
                f"{t['cat_emoji']} {t['cat_title']} · {t['diff_emoji']} {t['diff_name']} → обычно ~{base}{early}")
        return text, kb([Btn(text=str(v), callback_data=f"bk:x:{tid}:{off}:{v}") for v in opts],
                        [Btn(text="⬅️ Назад", callback_data=f"bk:t:{tid}")])

    def digest_lines(self) -> tuple[list[str], list[list[Btn]]]:
        items = self.p.digest(self.ui.today())
        if not items:
            return [], []
        lines, rows = ["\n🗃 <b>Дедлайны близко</b>"], []
        for x in items:
            name = f"{x['parent_title']}: {x['title']}" if x.get("parent_title") else x["title"]
            plan = "📅 в плане" if x["planned"] else "<b>не в плане</b>"
            lines.append(f"{x['heat_emoji']} {escape(name)} — {left_label(x['days_left'])}, {plan}")
            if not x["planned"]:
                rows.append([Btn(text=f"📅 В сегодня: {short(name, 22)}", callback_data=f"bk:s:{x['id']}:0")])
        return lines, rows

    @staticmethod
    def rating_rows(off: int) -> list[list[Btn]]:
        return [[Btn(text=str(i), callback_data=f"rt:s:{off}:{i}") for i in range(1, 6)],
                [Btn(text=str(i), callback_data=f"rt:s:{off}:{i}") for i in range(6, 11)]]

    def season_card(self, month: str) -> str:
        s = self.life.season(month)
        from .finance import rub
        lines = [f"🏆 <b>{s['title'].upper()}</b>", "",
                 f"⭐ XP за сезон: <b>{s['xp']}</b>",
                 f"✅ Квестов: <b>{s['quests_done']}</b>" + (f" из {s['quests_total']} ({s['rate']}%)" if s["rate"] is not None else ""),
                 f"📆 Активных дней: <b>{s['active_days']}</b> · лучшая серия: {s['best_streak']} · идеальных дней: {s['perfect_days']}"]
        if s["top_category"]:
            lines.append(f"🎯 Главное направление: {s['top_category']['emoji']} {s['top_category']['title']}")
        if s["bank_done"]:
            lines.append(f"🗃 Задач из банка: {s['bank_done']}" + (f" · 💀 боссов: {s['bosses']}" if s["bosses"] else ""))
        if s["promises_kept"]:
            lines.append(f"💌 Сдержано обещаний: {s['promises_kept']}")
        if s["habit_checks"]:
            lines.append(f"🔁 Отметок привычек: {s['habit_checks']}")
        if s["shifts"]:
            lines.append(f"💼 Смен: {s['shifts']} на {rub(s['shifts_sum'])}")
        if s["income"] or s["expense"]:
            lines.append(f"💰 Доходы {rub(s['income'])} · расходы {rub(s['expense'])}")
        if s["rating_avg"]:
            lines.append(f"⭐ Средняя оценка дня: {s['rating_avg']}/10")
        if s["achievements"]:
            lines.append("\n🏆 Достижения сезона: " + " ".join(a["emoji"] for a in s["achievements"]))
        lines.append("\nНовый сезон — с чистого листа. Уровень остаётся с тобой 💪")
        return "\n".join(lines)


def register_planner(router: Router, ui, edit, celebrate) -> PlanUI:
    pu = PlanUI(ui)
    p, life, game = pu.p, pu.life, ui.game

    async def err(cb: CallbackQuery, e: Exception):
        await cb.answer(str(e), show_alert=True)

    def new_ach(before):
        return [a for a in game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]

    # ================= Банк =================

    @router.message(F.text == K_BANK)
    async def k_bank(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = pu.bank()
        await msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "bk:list")
    async def bk_list(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer()
        text, markup = pu.bank()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("bk:t:"))
    async def bk_card(cb: CallbackQuery):
        try:
            text, markup = pu.card(int(cb.data.split(":")[2]))
        except PlanError as e:
            return await err(cb, e)
        await cb.answer()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("bk:pick:"))
    async def bk_pick(cb: CallbackQuery):
        await cb.answer()
        text, markup = pu.pick(int(cb.data.split(":")[2]))
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("bk:s:"))
    async def bk_sched(cb: CallbackQuery):
        _, _, tid, off = cb.data.split(":")
        try:
            text, markup = pu.xp_choice(int(tid), int(off))
        except PlanError as e:
            return await err(cb, e)
        await cb.answer()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("bk:x:"))
    async def bk_sched_xp(cb: CallbackQuery):
        _, _, tid, off, xp = cb.data.split(":")
        t = ui.today()
        day = t + timedelta(days=int(off))
        try:
            res = p.schedule(int(tid), day, int(xp), t)
        except Exception as e:
            return await err(cb, e)
        q = res["quest"]
        bonus = f" (+{res['bonus']} заранее ⏳)" if res["bonus"] else ""
        await cb.answer("📅 В плане!")
        await edit(cb, f"📅 <b>{escape(q.title)}</b> → {'сегодня' if int(off) == 0 else 'завтра'}, {q.xp} XP{bonus}\n"
                       + pu.load_line(p.load(day)),
                   kb([Btn(text="📅 Ещё из банка", callback_data=f"bk:pick:{off}"),
                       Btn(text="🗃 Банк", callback_data="bk:list")]))

    @router.callback_query(F.data.startswith("bk:now:"))
    async def bk_now(cb: CallbackQuery):
        tid = int(cb.data.split(":")[2])
        try:
            t = p.task(tid, ui.today())
            res = p.do_now(tid, t["suggested_xp"], ui.today())
        except Exception as e:
            return await err(cb, e)
        await cb.answer(f"✅ +{res['quest'].xp} XP")
        text, markup = pu.bank()
        await edit(cb, text, markup)
        await celebrate(cb.message, res)

    @router.callback_query(F.data.startswith("bk:del:"))
    async def bk_del(cb: CallbackQuery):
        tid = int(cb.data.split(":")[2])
        if not cb.data.endswith(":y"):
            await cb.answer()
            return await edit(cb, "🗑 Удалить задачу (и все её части)?",
                              kb([Btn(text="Да, удалить", callback_data=f"bk:del:{tid}:y"),
                                  Btn(text="Нет", callback_data=f"bk:t:{tid}")]))
        try:
            p.delete_task(tid, ui.today())
        except PlanError as e:
            return await err(cb, e)
        await cb.answer("Удалено")
        text, markup = pu.bank()
        await edit(cb, text, markup)

    # ---------- новая задача: название → категория → сложность → время → дедлайн ----------

    @router.callback_query(F.data == "bk:new")
    async def bk_new(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await state.set_state(BankNew.title)
        await cb.answer()
        await cb.message.answer("🗃 <b>Новая задача</b>\n\nШаг 1/5 — напиши, что надо сделать:",
                                reply_markup=kb([Btn(text="✖️ Отмена", callback_data="bk:list")]))

    @router.message(BankNew.title, F.text)
    async def bk_new_title(msg: Message, state: FSMContext):
        await state.update_data(title=msg.text.strip()[:200], parent=None)
        await state.set_state(None)
        cats = [c for c in rules.CATEGORIES.values() if c.pickable]
        btns = [Btn(text=f"{c.emoji} {c.title}", callback_data=f"bk:nc:{c.key}") for c in cats]
        await msg.answer(f"<b>{escape(msg.text.strip()[:200])}</b>\n\nШаг 2/5 — категория:",
                         reply_markup=kb(*[btns[i:i + 2] for i in range(0, len(btns), 2)]))

    async def ask_diff(target: Message, step: str):
        await target.answer(f"Шаг {step} — сложность:", reply_markup=kb(
            [Btn(text=f"{e} {n}", callback_data=f"bk:nd:{k}") for k, (n, e, _) in list(rules.DIFFICULTY.items())[:2]],
            [Btn(text=f"{e} {n}", callback_data=f"bk:nd:{k}") for k, (n, e, _) in list(rules.DIFFICULTY.items())[2:]]))

    @router.callback_query(F.data.startswith("bk:nc:"))
    async def bk_new_cat(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "title" not in data:
            return await cb.answer("Начни заново: ➕ Задача", show_alert=True)
        await state.update_data(cat=cb.data.split(":")[2])
        await cb.answer()
        await ask_diff(cb.message, "3/5")

    @router.callback_query(F.data.startswith("bk:nd:"))
    async def bk_new_diff(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "title" not in data:
            return await cb.answer("Начни заново: ➕ Задача", show_alert=True)
        await state.update_data(diff=int(cb.data.split(":")[2]))
        await cb.answer()
        step = "3/3" if data.get("parent") else "4/5"
        await cb.message.answer(f"Шаг {step} — сколько примерно времени займёт?", reply_markup=kb(*time_rows("bk:nt")))

    async def save_task(target: Message, state: FSMContext, deadline: date | None):
        data = await state.get_data()
        await state.clear()
        before = game._achieved(ui.today())
        try:
            t = p.add_task(data["title"], data.get("cat") or "study", ui.today(), data.get("diff", 2),
                           data.get("est") or None, deadline, data.get("parent"))
        except PlanError as e:
            return await target.answer(f"⛔ {escape(str(e))}")
        text, markup = pu.card(t["parent_id"] or t["id"])
        await target.answer(("➕ Часть добавлена\n\n" if t["parent_id"] else "➕ В банке\n\n") + text, reply_markup=markup)
        await celebrate(target, {"level_before": 0, "level_after": 0, "new_achievements": new_ach(before)})

    @router.callback_query(F.data.startswith("bk:nt:"))
    async def bk_new_time(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "title" not in data:
            return await cb.answer("Начни заново: ➕ Задача", show_alert=True)
        await state.update_data(est=int(cb.data.split(":")[2]))
        await cb.answer()
        if data.get("parent"):          # у части дедлайн как у большой задачи
            return await save_task(cb.message, state, None)
        await cb.message.answer("Шаг 5/5 — дедлайн:", reply_markup=kb(*DEADLINE_ROWS("bk:ndl")))

    def deadline_from(code: str) -> date | None:
        return None if code == "none" else ui.today() + timedelta(days=int(code))

    @router.callback_query(F.data.startswith("bk:ndl:"))
    async def bk_new_deadline(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "title" not in data:
            return await cb.answer("Начни заново: ➕ Задача", show_alert=True)
        code = cb.data.split(":")[2]
        await cb.answer()
        if code == "other":
            await state.update_data(dl_for=None)
            await state.set_state(BankNew.date_text)
            return await cb.message.answer("Напиши дату: <code>20.11</code>")
        await save_task(cb.message, state, deadline_from(code))

    def parse_date(text: str) -> date | None:
        m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*$", text)
        if not m:
            return None
        t = ui.today()
        y = int(m.group(3)) if m.group(3) else t.year
        try:
            d = date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and d < t - timedelta(days=1):
            d = d.replace(year=d.year + 1)
        return d

    @router.message(BankNew.date_text, F.text)
    async def bk_date_text(msg: Message, state: FSMContext):
        d = parse_date(msg.text)
        if d is None:
            return await msg.answer("Не понял дату. Пример: <code>20.11</code>")
        data = await state.get_data()
        if data.get("dl_for"):          # меняли дедлайн существующей задачи
            await state.clear()
            p.edit_task(data["dl_for"], ui.today(), deadline=d)
            text, markup = pu.card(data["dl_for"])
            return await msg.answer(text, reply_markup=markup)
        await save_task(msg, state, d)

    # ---------- часть и дедлайн ----------

    @router.callback_query(F.data.startswith("bk:sub:"))
    async def bk_sub(cb: CallbackQuery, state: FSMContext):
        tid = int(cb.data.split(":")[2])
        try:
            t = p.task(tid, ui.today())
        except PlanError as e:
            return await err(cb, e)
        await state.clear()
        await state.set_state(BankNew.sub_title)
        await state.update_data(parent=tid, cat=t["category"])
        await cb.answer()
        await cb.message.answer(f"➕ Часть задачи «{escape(t['title'])}»\n\nШаг 1/3 — название части:",
                                reply_markup=kb([Btn(text="✖️ Отмена", callback_data=f"bk:t:{tid}")]))

    @router.message(BankNew.sub_title, F.text)
    async def bk_sub_title(msg: Message, state: FSMContext):
        await state.update_data(title=msg.text.strip()[:200])
        await state.set_state(None)
        await ask_diff(msg, "2/3")

    @router.callback_query(F.data.startswith("bk:dl:"))
    async def bk_dl(cb: CallbackQuery):
        tid = int(cb.data.split(":")[2])
        await cb.answer()
        await edit(cb, "⏰ Новый дедлайн:", kb(*DEADLINE_ROWS(f"bk:edl:{tid}"), [Btn(text="⬅️", callback_data=f"bk:t:{tid}")]))

    @router.callback_query(F.data.startswith("bk:edl:"))
    async def bk_edl(cb: CallbackQuery, state: FSMContext):
        _, _, tid, code = cb.data.split(":")
        await cb.answer()
        if code == "other":
            await state.clear()
            await state.set_state(BankNew.date_text)
            await state.update_data(dl_for=int(tid))
            return await cb.message.answer("Напиши дату: <code>20.11</code>")
        try:
            p.edit_task(int(tid), ui.today(), deadline=deadline_from(code))
            text, markup = pu.card(int(tid))
        except PlanError as e:
            return await err(cb, e)
        await edit(cb, text, markup)

    # ================= Таймер и темп =================

    @router.callback_query(F.data.startswith("tm:"))
    async def timer(cb: CallbackQuery):
        _, action, qid = cb.data.split(":")
        try:
            q = p.timer_start(int(qid)) if action == "start" else p.timer_pause(int(qid))
        except Exception as e:
            return await err(cb, e)
        await cb.answer("⏱ Таймер пошёл" if action == "start" else f"⏸ Пауза: {rules.fmt_min(max(1, q['timer_sec'] // 60))}")
        text, markup = ui.render_day(date.fromisoformat(q["day"]))
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("pc:"))
    async def pace(cb: CallbackQuery):
        _, qid, val = cb.data.split(":")
        try:
            before = game._achieved(ui.today())
            p.set_pace(int(qid), val)
        except PlanError as e:
            return await err(cb, e)
        await cb.answer(PACE[val])
        await edit(cb, f"⏱ Записал: {PACE[val]}. Спасибо — так «начать не позднее» станет точнее.")
        await celebrate(cb.message, {"level_before": 0, "level_after": 0, "new_achievements": new_ach(before)})

    # ================= Привычки =================

    @router.callback_query(F.data.startswith("hb:t:"))
    async def habit_toggle(cb: CallbackQuery):
        hid = int(cb.data.split(":")[2])
        try:
            res = life.toggle_habit(hid, ui.today(), ui.today())
        except LifeError as e:
            return await err(cb, e)
        h = res["habit"]
        await cb.answer(f"{h['emoji']} +{h['xp']} XP · 🔥{h['streak']} {h['unit']}" if res["done"] else "Отметка снята")
        if cb.message.text and cb.message.text.lstrip().startswith("🔁"):     # отдельный список привычек
            hl, hr = pu.habit_block()
            await edit(cb, "\n".join(hl).strip(), kb(*hr))
        else:
            text, markup = ui.render_day(ui.today())
            await edit(cb, text, markup)
        await celebrate(cb.message, res)

    # ================= Оценка дня =================

    @router.callback_query(F.data.startswith("rt:ask:"))
    async def rate_ask(cb: CallbackQuery):
        off = int(cb.data.split(":")[2])
        await cb.answer()
        cur = life.rating(ui.today() - timedelta(days=off))
        await cb.message.answer(f"⭐ Как прошёл {'сегодняшний' if off == 0 else 'вчерашний'} день? (1–10)"
                                + (f"\nСейчас: {cur}" if cur else ""), reply_markup=kb(*pu.rating_rows(off)))

    @router.callback_query(F.data.startswith("rt:s:"))
    async def rate_set(cb: CallbackQuery):
        _, _, off, score = cb.data.split(":")
        before = game._achieved(ui.today())
        life.rate(ui.today() - timedelta(days=int(off)), int(score), ui.today())
        await cb.answer(f"⭐ {score}/10")
        await edit(cb, f"⭐ День: <b>{score}/10</b> — записал.")
        await celebrate(cb.message, {"level_before": 0, "level_after": 0, "new_achievements": new_ach(before)})

    return pu
