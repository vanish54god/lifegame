"""
Финансы и чек-ины в боте.
- «кофе 250» / «+30000 зарплата» → операция, с кнопками «категория» и «отменить»;
- 💼 смена по кнопкам: компания → дата → тип работы → сумма;
- сводка, зарплата по компаниям, платежи, желания;
- 👋 умный чек-ин.
"""

import time
from datetime import date, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message

from .finance import CATS, IN_CATS, OUT_CATS, FinError, parse_money, parse_shift_pay, rub, to_kop, AMOUNT
from .rules import progress_bar

import re

K_FIN = "💰 Финансы"


class ShiftFlow(StatesGroup):
    company = State()
    date_text = State()
    amount = State()


class WishAmount(StatesGroup):
    amount = State()


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def short(text: str, n: int = 24) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def ddmm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def plural(n: int, one: str, few: str, many: str) -> str:
    a, b = abs(n) % 100, abs(n) % 10
    if 10 < a < 20:
        return many
    return one if b == 1 else few if 1 < b < 5 else many


def days_word(n: int) -> str:
    if n < 0:
        return f"просрочено на {-n} дн"
    return {0: "сегодня", 1: "завтра"}.get(n, f"через {n} дн")


class FinUI:
    def __init__(self, ui):
        self.ui, self.game, self.fin = ui, ui.game, ui.game.fin

    def limit_line(self) -> str:
        t = self.ui.today()
        spent, lim = self.fin.spent_today(t), self.fin.daily_limit
        if not lim:
            return f"Сегодня потрачено: <b>{rub(spent)}</b>"
        line = f"Сегодня: <b>{rub(spent)}</b> / {rub(lim)}  {progress_bar(min(spent, lim), lim, 8)}"
        if spent > lim:
            line += f"\n⚠️ Лимит превышен на {rub(spent - lim)}"
        return line

    def overview(self) -> tuple[str, InlineKeyboardMarkup]:
        o = self.fin.overview(self.ui.today())
        lines = ["💰 <b>Финансы</b>", "",
                 f"Свободно: <b>{rub(o['balance'])}</b>",
                 self.limit_line(),
                 f"Месяц: {rub(o['month_in'], sign=True)} / −{rub(o['month_out'])}"]
        if o["expected_salary"]:
            parts = ", ".join(f"{escape(c['company'])} {rub(c['owed'])}" for c in o["companies_owed"][:3])
            lines.append(f"\n💼 Ждём зарплату: <b>{rub(o['expected_salary'])}</b>\n<i>{parts}</i>")
        soon = [p for p in o["plans_soon"] if p["days_left"] <= 7]
        if soon:
            lines.append("\n📅 <b>Платежи</b>")
            lines += [f"• {escape(p['title'])} — {rub(p['amount'])}, {days_word(p['days_left'])}" for p in soon]
        if o["wishes"]:
            lines.append("\n🎯 <b>Желания</b>")
            lines += [f"• {escape(w['title'])} {progress_bar(w['saved'], w['target'], 6)} {w['progress']}%"
                      for w in o["wishes"][:3]]
        if o["savings_total"]:
            lines.append(f"\n🏦 Накопления: <b>{rub(o['savings_total'])}</b>")
        lines.append("\n<i>Записать трату: просто напиши «кофе 250» или «+5000 монтаж»</i>")
        return "\n".join(lines), kb(
            [Btn(text="💼 Смена", callback_data="fin:shift"), Btn(text="💰 Зарплата", callback_data="fin:salary")],
            [Btn(text="📅 Платежи", callback_data="fin:plans"), Btn(text="🎯 Желания", callback_data="fin:wishes")],
            [Btn(text="🧾 Последние операции", callback_data="fin:recent")],
            [Btn(text="🌐 Подробно в приложении", callback_data="adm:web")],
        )

    def tx_text(self, t: dict) -> tuple[str, InlineKeyboardMarkup]:
        sign = "+" if t["kind"] == "in" else "−"
        icon = "💵" if t["kind"] == "in" else "💸"
        note = f" · {escape(t['note'])}" if t["note"] else ""
        text = f"{icon} <b>{sign}{rub(t['amount'])}</b> · {t['emoji']} {t['cat_title']}{note}"
        if t["kind"] == "out" and t["in_limit"]:
            text += "\n" + self.limit_line()
        if t["kind"] == "in":
            text += f"\nСвободно: {rub(self.fin.balance())}"
        return text, kb([Btn(text="🏷 Категория", callback_data=f"fin:cats:{t['id']}"),
                         Btn(text="🗑 Отменить", callback_data=f"fin:del:{t['id']}")])

    def salary(self) -> tuple[str, InlineKeyboardMarkup]:
        comps = self.fin.companies()
        lines, rows = ["💼 <b>Зарплата по сменам</b>", ""], []
        if not comps:
            lines.append("Смен пока нет. Жми «💼 Смена», чтобы записать первую.")
        for c in comps:
            lines.append(f"<b>{escape(c['company'])}</b>: {c['shifts']} {plural(c['shifts'], 'смена', 'смены', 'смен')}, "
                         f"заработано {rub(c['earned'])}")
            if c["owed"]:
                lines.append(f"   ⏳ должны <b>{rub(c['owed'])}</b> (с {ddmm(c['oldest_unpaid'])})")
                oldest = self.fin.shifts(company=c["company"], unpaid_only=True, limit=1000)[-1]
                rows.append([Btn(text=f"💰 {short(c['company'], 20)} оплатил всё",
                                 callback_data=f"fin:cpay:{oldest['id']}")])
            else:
                lines.append("   ✅ всё выплачено")
        unpaid = self.fin.shifts(unpaid_only=True, limit=8)
        if unpaid:
            lines.append("\n<b>Неоплаченные смены</b> (жми, если оплатили одну):")
            for s in unpaid:
                rows.append([Btn(text=f"💰 {ddmm(s['day'])} {short(s['company'], 12)} · {s['work_type']} · {rub(s['amount'])}",
                                 callback_data=f"fin:spay:{s['id']}")])
        lines.append(f"\nВсего ждём: <b>{rub(self.fin.expected_salary())}</b>")
        rows.append([Btn(text="➕ Смена", callback_data="fin:shift"), Btn(text="⬅️ Финансы", callback_data="fin:home")])
        return "\n".join(lines), kb(*rows)

    def plans(self) -> tuple[str, InlineKeyboardMarkup]:
        ps = self.fin.plans(self.ui.today())
        lines, rows = ["📅 <b>Планируемые траты</b>", ""], []
        if not ps:
            lines.append("Пусто. Добавить платёж можно в приложении: Финансы → Планы.")
        rep = {"none": "", "week": " 🔁 нед", "month": " 🔁 мес"}
        for p in ps:
            warn = "⚠️ " if p["days_left"] < 0 else ""
            lines.append(f"{warn}{p['emoji']} {escape(p['title'])} — <b>{rub(p['amount'])}</b>, "
                         f"{days_word(p['days_left'])} ({ddmm(p['due'])}){rep[p['repeat']]}")
            if p["days_left"] <= 7:
                rows.append([Btn(text=f"✅ Оплатил: {short(p['title'], 20)}", callback_data=f"fin:ppay:{p['id']}")])
        rows.append([Btn(text="⬅️ Финансы", callback_data="fin:home")])
        return "\n".join(lines), kb(*rows)

    def wishes(self) -> tuple[str, InlineKeyboardMarkup]:
        ws = self.fin.wishes(include_done=False)
        lines, rows = ["🎯 <b>Карта желаний</b>", ""], []
        if not ws:
            lines.append("Пусто. Добавить желание можно в приложении: Финансы → Желания.")
        for w in ws:
            lines.append(f"<b>{escape(w['title'])}</b>\n{progress_bar(w['saved'], w['target'], 10)} "
                         f"{rub(w['saved'])} / {rub(w['target'])} ({w['progress']}%)")
            rows.append([Btn(text=f"➕ Отложить: {short(w['title'], 22)}", callback_data=f"fin:wadd:{w['id']}")])
        lines.append(f"\nСвободно: {rub(self.fin.balance())}")
        rows.append([Btn(text="⬅️ Финансы", callback_data="fin:home")])
        return "\n".join(lines), kb(*rows)

    def recent(self) -> tuple[str, InlineKeyboardMarkup]:
        t = self.ui.today()
        txs = [x for x in self.fin.txs(t - timedelta(days=30), t) if x["kind"] != "move"][:12]
        lines = ["🧾 <b>Последние операции</b>", ""]
        if not txs:
            lines.append("Пока пусто.")
        for x in txs:
            sign = "+" if x["kind"] == "in" else "−"
            note = f" {escape(x['note'])}" if x["note"] else ""
            lines.append(f"{ddmm(x['day'])} {x['emoji']} <b>{sign}{rub(x['amount'])}</b>{note}")
        return "\n".join(lines), kb([Btn(text="⬅️ Финансы", callback_data="fin:home")])

    def digest_lines(self) -> tuple[list[str], list[list[Btn]]]:
        """Платежи для утренней сводки."""
        ps = self.fin.digest(self.ui.today())
        if not ps:
            return [], []
        lines = ["\n📅 <b>Платежи</b>"]
        rows = []
        for p in ps:
            lines.append(f"• {escape(p['title'])} — {rub(p['amount'])}, {days_word(p['days_left'])}")
            rows.append([Btn(text=f"✅ Оплатил: {short(p['title'], 22)}", callback_data=f"fin:ppay:{p['id']}")])
        return lines, rows

    def checkin(self) -> tuple[str, InlineKeyboardMarkup]:
        t = self.ui.today()
        qs = self.game.quests(t)
        done = sum(1 for q in qs if q.status == "done")
        prom_today = [p for p in self.game.promises(t) if p["due"] and p["due"] <= t.isoformat()]
        lines = ["👋 <b>Чек-ин</b>", "Давно не заглядывал — всё по плану?", ""]
        lines.append(f"🎮 Квесты: {done}/{len(qs)}" if qs else "🎮 Квестов на сегодня нет")
        lines.append("💸 " + self.limit_line().replace("Сегодня: ", "Траты: ").replace("Сегодня потрачено: ", "Траты: "))
        if prom_today:
            lines.append(f"💌 Обещаний на сегодня: {len(prom_today)}")
        return "\n".join(lines), kb(
            [Btn(text="🎮 Квесты", callback_data="ci:today"), Btn(text="💸 Трата", callback_data="ci:spend")],
            [Btn(text="💼 Смена", callback_data="fin:shift"), Btn(text="👌 Всё ок", callback_data="ci:ok")],
        )


def register_finance(router: Router, ui, edit, celebrate, main_kb) -> FinUI:
    fu = FinUI(ui)
    fin = ui.game.fin

    async def fin_err(cb: CallbackQuery, e: Exception):
        await cb.answer(str(e), show_alert=True)

    # ---------- сводка ----------

    @router.message(F.text == K_FIN)
    async def k_fin(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = fu.overview()
        await msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data.in_({"fin:home", "fin:salary", "fin:plans", "fin:wishes", "fin:recent"}))
    async def fin_screens(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer()
        screen = {"fin:home": fu.overview, "fin:salary": fu.salary, "fin:plans": fu.plans,
                  "fin:wishes": fu.wishes, "fin:recent": fu.recent}[cb.data]
        text, markup = screen()
        await edit(cb, text, markup)

    # ---------- операции ----------

    @router.callback_query(F.data.startswith("fin:cats:"))
    async def tx_cats(cb: CallbackQuery):
        tid = int(cb.data.split(":")[2])
        try:
            t = fin.tx(tid)
        except FinError as e:
            return await fin_err(cb, e)
        cats = IN_CATS if t["kind"] == "in" else OUT_CATS
        btns = [Btn(text=f"{c.emoji} {c.title}", callback_data=f"fin:setcat:{tid}:{c.key}") for c in cats]
        await cb.answer()
        await edit(cb, "Выбери категорию:", kb(*[btns[i:i + 3] for i in range(0, len(btns), 3)]))

    @router.callback_query(F.data.startswith("fin:setcat:"))
    async def tx_setcat(cb: CallbackQuery):
        _, _, tid, key = cb.data.split(":")
        try:
            t = fin.set_tx_category(int(tid), key)
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer(f"{CATS[key].emoji} {CATS[key].title}")
        text, markup = fu.tx_text(t)
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("fin:del:"))
    async def tx_del(cb: CallbackQuery):
        try:
            t = fin.delete_tx(int(cb.data.split(":")[2]))
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer("Отменено")
        await edit(cb, f"🗑 <s>{rub(t['amount'])} · {escape(t['note'] or t['cat_title'])}</s>")

    # ---------- смена по кнопкам ----------

    @router.callback_query(F.data == "fin:shift")
    async def shift_start(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        comps = fin.recent_companies()
        await state.set_state(ShiftFlow.company)
        await state.update_data(comps=comps)
        rows = [[Btn(text=f"🏢 {short(c, 30)}", callback_data=f"fin:sc:{i}")] for i, c in enumerate(comps)]
        rows.append([Btn(text="✏️ Новая компания", callback_data="fin:scnew")])
        rows.append([Btn(text="✖️ Отмена", callback_data="fin:home")])
        await cb.answer()
        text = "💼 <b>Новая смена</b>\n\nШаг 1/4 — компания:"
        if not comps:
            text += "\n\nНапиши название компании сообщением."
        await cb.message.answer(text, reply_markup=kb(*rows))

    async def ask_date(target: Message, state: FSMContext):
        data = await state.get_data()
        await state.set_state(None)
        await state.update_data(**data)
        t = ui.today()
        await target.answer(
            f"🏢 <b>{escape(data['company'])}</b>\n\nШаг 2/4 — когда была смена?",
            reply_markup=kb([Btn(text="Сегодня", callback_data="fin:sd:0"),
                             Btn(text="Вчера", callback_data="fin:sd:1"),
                             Btn(text=f"Позавчера ({(t - timedelta(days=2)):%d.%m})", callback_data="fin:sd:2")],
                            [Btn(text="📅 Другая дата", callback_data="fin:sdother")],
                            [Btn(text="✖️ Отмена", callback_data="fin:home")]))

    @router.callback_query(F.data.startswith("fin:sc:"))
    async def shift_company(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        comps = data.get("comps") or []
        i = int(cb.data.split(":")[2])
        if i >= len(comps):
            return await cb.answer("Начни заново", show_alert=True)
        await state.update_data(company=comps[i])
        await cb.answer()
        await ask_date(cb.message, state)

    @router.callback_query(F.data == "fin:scnew")
    async def shift_company_new(cb: CallbackQuery, state: FSMContext):
        await state.set_state(ShiftFlow.company)
        await cb.answer()
        await cb.message.answer("Напиши название компании:")

    @router.message(ShiftFlow.company, F.text)
    async def shift_company_text(msg: Message, state: FSMContext):
        await state.update_data(company=msg.text.strip()[:60])
        await ask_date(msg, state)

    async def ask_type(target: Message, state: FSMContext):
        types = fin.work_types
        await state.update_data(types=types)
        btns = [Btn(text=t, callback_data=f"fin:st:{i}") for i, t in enumerate(types)]
        data = await state.get_data()
        await target.answer(f"🏢 {escape(data['company'])} · {ddmm(data['day'])}\n\nШаг 3/4 — тип работы:",
                            reply_markup=kb(*[btns[i:i + 3] for i in range(0, len(btns), 3)],
                                            [Btn(text="✖️ Отмена", callback_data="fin:home")]))

    @router.callback_query(F.data.startswith("fin:sd:"))
    async def shift_date(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if "company" not in data:
            return await cb.answer("Начни заново: 💼 Смена", show_alert=True)
        await state.update_data(day=(ui.today() - timedelta(days=int(cb.data.split(":")[2]))).isoformat())
        await cb.answer()
        await ask_type(cb.message, state)

    @router.callback_query(F.data == "fin:sdother")
    async def shift_date_other(cb: CallbackQuery, state: FSMContext):
        await state.set_state(ShiftFlow.date_text)
        await cb.answer()
        await cb.message.answer("Напиши дату: <code>03.11</code>")

    @router.message(ShiftFlow.date_text, F.text)
    async def shift_date_text(msg: Message, state: FSMContext):
        m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*$", msg.text)
        t = ui.today()
        try:
            y = int(m.group(3)) if m and m.group(3) else t.year
            d = date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
            if d > t + timedelta(days=1) and not (m and m.group(3)):
                d = d.replace(year=d.year - 1)   # «28.12» в январе — это прошлый год
        except (AttributeError, ValueError):
            return await msg.answer("Не понял дату. Пример: <code>03.11</code>")
        await state.set_state(None)
        await state.update_data(day=d.isoformat())
        await ask_type(msg, state)

    @router.callback_query(F.data.startswith("fin:st:"))
    async def shift_type(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        types = data.get("types") or []
        i = int(cb.data.split(":")[2])
        if "day" not in data or i >= len(types):
            return await cb.answer("Начни заново: 💼 Смена", show_alert=True)
        await state.update_data(work_type=types[i])
        await state.set_state(ShiftFlow.amount)
        await cb.answer()
        await cb.message.answer(f"🏢 {escape(data['company'])} · {ddmm(data['day'])} · {types[i]}\n\n"
                                "Шаг 4/4 — сколько? Напиши <code>3200</code> или <code>8ч по 400</code>")

    @router.message(ShiftFlow.amount, F.text)
    async def shift_amount(msg: Message, state: FSMContext):
        data = await state.get_data()
        before = ui.game._achieved(ui.today())
        try:
            hours, rate, amount = parse_shift_pay(msg.text)
            s = fin.add_shift(date.fromisoformat(data["day"]), data["company"], data["work_type"], amount, hours, rate)
        except FinError as e:
            return await msg.answer(f"⛔ {escape(str(e))}")
        await state.clear()
        calc = f"{s['hours']:g}ч × {rub(s['rate'])} = " if s["hours"] else ""
        owed = next((c["owed"] for c in fin.companies() if c["company"] == s["company"]), 0)
        await msg.answer(
            f"💼 <b>Смена записана</b>\n{escape(s['company'])} · {s['work_type']} · {ddmm(s['day'])}\n"
            f"{calc}<b>{rub(s['amount'])}</b> — ждём оплату\n\n"
            f"Всего ждём от {escape(s['company'])}: <b>{rub(owed)}</b>",
            reply_markup=kb([Btn(text="💰 Уже оплачено", callback_data=f"fin:spay:{s['id']}"),
                             Btn(text="🗑 Удалить", callback_data=f"fin:sdel:{s['id']}")],
                            [Btn(text="➕ Ещё смена", callback_data="fin:shift"),
                             Btn(text="💼 Зарплата", callback_data="fin:salary")]))
        new = [a for a in ui.game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]
        await celebrate(msg, {"level_before": 0, "level_after": 0, "new_achievements": new})

    @router.callback_query(F.data.startswith("fin:spay:"))
    async def shift_pay(cb: CallbackQuery):
        try:
            s = fin.pay_shift(int(cb.data.split(":")[2]), ui.today())
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer(f"💰 +{rub(s['amount'])} в доходы")
        text, markup = fu.salary()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("fin:cpay:"))
    async def company_pay(cb: CallbackQuery):
        before = ui.game._achieved(ui.today())
        try:
            company = fin.shift(int(cb.data.split(":")[2]))["company"]
            n, total = fin.pay_company(company, ui.today())
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer(f"💰 {n} {plural(n, 'смена', 'смены', 'смен')}, +{rub(total)}", show_alert=True)
        text, markup = fu.salary()
        await edit(cb, text, markup)
        new = [a for a in ui.game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]
        await celebrate(cb.message, {"level_before": 0, "level_after": 0, "new_achievements": new})

    @router.callback_query(F.data.startswith("fin:sdel:"))
    async def shift_del(cb: CallbackQuery):
        try:
            fin.delete_shift(int(cb.data.split(":")[2]))
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer("Удалено")
        await edit(cb, "🗑 Смена удалена")

    # ---------- платежи и желания ----------

    @router.callback_query(F.data.startswith("fin:ppay:"))
    async def plan_pay(cb: CallbackQuery):
        try:
            p = fin.plan(int(cb.data.split(":")[2]))
            fin.pay_plan(p["id"], ui.today())
        except FinError as e:
            return await fin_err(cb, e)
        await cb.answer(f"✅ {p['title']}: −{rub(p['amount'])}")
        text, markup = fu.plans()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("fin:wadd:"))
    async def wish_add(cb: CallbackQuery, state: FSMContext):
        wid = int(cb.data.split(":")[2])
        try:
            w = fin.wish(wid)
        except FinError as e:
            return await fin_err(cb, e)
        await state.set_state(WishAmount.amount)
        await state.update_data(wid=wid)
        await cb.answer()
        await cb.message.answer(f"🎯 Сколько отложить на «{escape(w['title'])}»? Напиши сумму, например <code>2000</code>.\n"
                                f"Свободно: {rub(fin.balance())}")

    @router.message(WishAmount.amount, F.text)
    async def wish_amount(msg: Message, state: FSMContext):
        m = re.match(r"^\s*([+-])?\s*" + AMOUNT + r"\s*$", msg.text, re.I)
        if not m:
            return await msg.answer("Нужна сумма, например <code>2000</code> (или <code>-500</code>, чтобы забрать)")
        amount = to_kop(m.group(2), m.group(3)) * (-1 if m.group(1) == "-" else 1)
        data = await state.get_data()
        await state.clear()
        try:
            w = fin.wish_add_money(data["wid"], amount, ui.today())
        except FinError as e:
            return await msg.answer(f"⛔ {escape(str(e))}")
        text = (f"🎯 <b>{escape(w['title'])}</b>\n{progress_bar(w['saved'], w['target'], 10)} "
                f"{rub(w['saved'])} / {rub(w['target'])} ({w['progress']}%)")
        if w["saved"] >= w["target"]:
            text += "\n\n🎉 Накопил! Отметь исполнение в приложении — и вперёд за покупкой."
        await msg.answer(text, reply_markup=kb([Btn(text="🎯 Все желания", callback_data="fin:wishes")]))

    # ---------- чек-ин ----------

    @router.callback_query(F.data == "ci:ok")
    async def ci_ok(cb: CallbackQuery):
        every = ui.game.get_setting("checkin_every", "3")
        await cb.answer("👌")
        await edit(cb, f"👌 Принято. Следующий чек-ин — не раньше чем через {every} ч.")

    @router.callback_query(F.data == "ci:spend")
    async def ci_spend(cb: CallbackQuery):
        await cb.answer()
        await cb.message.answer("💸 Напиши трату одним сообщением: <code>кофе 250</code>\n"
                                "Доход — с плюсом: <code>+3000 монтаж</code>")

    @router.callback_query(F.data == "ci:today")
    async def ci_today(cb: CallbackQuery):
        await cb.answer()
        text, markup = ui.render_day(ui.today())
        await cb.message.answer(text, reply_markup=markup)

    # ---------- трата или доход текстом (должно идти последним перед «не понял») ----------

    @router.message(StateFilter(None), F.text.func(lambda t: parse_money(t) is not None))
    async def money_text(msg: Message):
        kind, amount, note = parse_money(msg.text)
        try:
            t = fin.add_tx(ui.today(), kind, amount, note=note)
        except FinError as e:
            return await msg.answer(f"⛔ {escape(str(e))}")
        text, markup = fu.tx_text(t)
        await msg.answer(text, reply_markup=markup)

    return fu
