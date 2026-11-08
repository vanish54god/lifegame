"""
Telegram-бот. Всё управляется кнопками:
внизу постоянная клавиатура (Сегодня / Профиль / Админ / Магазин),
под сообщениями — инлайн-кнопки. Команды тоже работают, как запасной вариант.
"""

import asyncio
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton as Btn,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

from . import rules
from .auth import Auth
from .config import Config
from .game import SHOP_KINDS, Game, GameError, game_day
from .promise_text import parse_promise
from .bot_finance import K_FIN, K_MONEY, FinUI, register_finance
from .bot_planner import K_BANK, PlanUI, register_planner, time_rows
from .life import month_bounds

# Тексты кнопок постоянной клавиатуры
K_TODAY, K_ME, K_ADMIN, K_SHOP = "🎮 Сегодня", "👤 Профиль", "🛠 Админ", "🛒 Магазин"
K_PROM = "💌 Обещания"
K_MORE = "☰ Ещё"
KB_VERSION = "2"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=K_TODAY), KeyboardButton(text=K_MONEY)],
              [KeyboardButton(text=K_BANK), KeyboardButton(text=K_MORE)]],
    resize_keyboard=True, is_persistent=True,
)

SHOW = rules.BOT_SHOW   # что показывать в «Сегодня» сразу

HELP = """<b>🎮 Как играть</b>

Вечером ты <b>админ</b>: «☰ Ещё» → «🛠 Админ», собирай квесты на завтра.
Утром ты <b>игрок</b>: «🎮 Сегодня» и отмечай ✅ / ❌.
Монеты тратятся в «🛒 Магазине» (☰ Ещё).

<b>💌 Обещания</b> — просто напиши боту:
<code>обещал забрать посылку в пятницу</code>
Срок бот поймёт сам (сегодня, завтра, в пятницу, на выходных, до 12.11).
Без срока тоже можно — через пару дней бот спросит «когда?».

<b>💰 Деньги</b> — тоже просто текстом:
<code>кофе 250</code> · <code>такси 1.5к</code> · <code>+30000 зарплата</code>
Пришли деньги — бот предложит разложить их по конвертам:
📅 Обязательное · 🏦 Копилка · 🧍 Я · ❤️ Отношения · 🎯 Хотелки.
Лимит на день считается сам до следующих денег; день в лимите — +20 XP.

<b>🗃 Банк заданий</b> — все дела, пока не сделаны. 🔥 показывает, что горит.
Вечером бери из банка в завтрашний день. Не успел — задача сама вернётся в банк.
⏱ — таймер на квест. ⭐ — оценка дня.

<b>Команды на всякий случай</b>
/add <i>категория xp название</i> — квест на завтра
/bonus <i>xp название</i> — бонус на завтра
/addnow, /bonusnow — то же на сегодня
/item <i>цена название</i> — товар в магазин
/web — войти в веб-приложение
/logout_all — выйти из приложения на всех устройствах
/rules — категории и границы XP"""


class NewPromise(StatesGroup):
    text = State()


class AddQuest(StatesGroup):
    category = State()
    xp = State()
    xp_custom = State()
    est = State()
    title = State()


def kb(*rows: list[Btn]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def short(text: str, n: int = 26) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def xp_presets(cat: rules.Category) -> list[int]:
    """5 удобных значений XP в рекомендованных границах категории."""
    lo, hi = max(cat.xp_min, 10), cat.xp_max
    vals = {int(round((lo + (hi - lo) * i / 4) / 10) * 10) for i in range(5)}
    return sorted(v for v in vals if v > 0)


class UI:
    """Тексты и клавиатуры — общие для команд, кнопок и напоминаний."""

    def __init__(self, cfg: Config, game: Game):
        self.cfg, self.game = cfg, game

    def today(self) -> date:
        return game_day(datetime.now(self.cfg.tz), self.cfg.day_start_hour)

    def day_title(self, day: date) -> str:
        t = self.today()
        return {t: "🎮 <b>Сегодня</b>", t - timedelta(days=1): "⏪ <b>Вчера</b>",
                t + timedelta(days=1): "🛠 <b>План на завтра</b>"}.get(day, f"📅 <b>{day:%d.%m}</b>")

    def show(self, key: str) -> bool:
        return self.game.get_setting(key, SHOW[key][1]) == "1"

    def render_day(self, day: date, header: str | None = None) -> tuple[str, InlineKeyboardMarkup | None]:
        t = self.today()
        pu = PlanUI(self)
        quests = [q for q in self.game.quests(day) if q.category.key not in ("habit", "money")]
        planning = day > t
        lines = [header or self.day_title(day)]
        if day == t:
            if self.show("show_time"):
                sb = pu.start_by_line()
                if sb:
                    lines.append(sb)
            env = self.game.env
            if self.show("show_money") and env.on:
                b = env.budget(t)
                left = b["left_today"]
                lines.append(f"💰 Можно сегодня: <b>{max(0, left) // 100} ₽</b>" if left >= 0
                             else f"💰 Больше лимита на {-left // 100} ₽")
        lines.append("")
        if not quests:
            lines.append("Квестов нет. Админ, твой выход 👇" if day >= t else "В этот день квестов не было.")
        for q in quests:
            est = f" · ~{rules.fmt_min(q.est_min)}" if q.est_min and q.status == "todo" else ""
            lines.append(escape(q.line()) + est + pu.timer_label(q))
        if any(q.category.pickable for q in quests) and not any(q.is_main for q in quests):
            lines.append("\n⚠️ Нет ни одного основного задания (нужно 1–3)")
        if planning:
            lines.append(f"\nВсего можно взять: <b>{sum(q.xp for q in quests)}</b> XP")
            lines.append(pu.load_line(self.game.planner.load(day)))
        elif quests:
            lines.append(f"\nЗа день: <b>{self.game.stats(day).xp_on_day}</b> XP")

        off = (day - t).days
        rows = []
        for q in quests:
            if planning:
                rows.append([Btn(text=f"🗑 {short(q.title)}", callback_data=f"del:{q.id}")])
            elif q.status == "todo":
                row = [Btn(text=f"✅ {short(q.title, 22)}", callback_data=f"done:{q.id}")]
                if day == t:
                    row.append(Btn(text="⏸" if q.timer_start else "⏱",
                                   callback_data=f"tm:{'pause' if q.timer_start else 'start'}:{q.id}"))
                row.append(Btn(text="❌", callback_data=f"failed:{q.id}"))
                rows.append(row)
            else:
                rows.append([Btn(text=f"↩️ {short(q.title)}", callback_data=f"todo:{q.id}")])
        extra = []
        if day == t:
            due = [p for p in self.game.promises(t) if p["due"] and p["due"] <= t.isoformat()]
            if due and self.show("show_promises"):
                lines.append("\n💌 <b>Обещания на сегодня</b>")
                for p in due:
                    mark = "⚠️ " if p["overdue"] else ""
                    lines.append(f"{mark}• {escape(p['text'])} <i>({p['due_label']})</i>")
                    rows.append([Btn(text=f"💌 {short(p['text'], 24)}", callback_data=f"p:keep:{p['id']}:d"),
                                 Btn(text="📅", callback_data=f"p:menu:{p['id']}")])
            elif due:
                extra.append(Btn(text=f"💌 {len(due)}" + (" ⚠️" if any(p["overdue"] for p in due) else ""),
                                 callback_data="p:list"))
            hs = self.game.life.habits(t)
            if hs and self.show("show_habits"):
                hl, hr = pu.habit_block()
                lines += hl
                rows += hr
            elif hs:
                extra.append(Btn(text=f"🔁 {sum(h['done_today'] for h in hs)}/{len(hs)}", callback_data="hb:list"))
        if off in (0, -1) and (self.show("show_rating") or off == -1
                               or datetime.now(self.cfg.tz).hour >= 20 or self.game.life.rating(day)):
            score = self.game.life.rating(day)
            extra.append(Btn(text=f"⭐ {score}" if score else "⭐", callback_data=f"rt:ask:{-off}"))
        if off in (0, 1):
            extra.append(Btn(text="➕", callback_data=f"day:add:{off}"))
        if extra:
            rows.append(extra)
        return "\n".join(lines), kb(*rows)

    def render_me(self) -> str:
        s = self.game.full_stats(self.today())
        lv = rules.LevelInfo(**s["level"])
        got = [a for a in s["achievements"] if a["done"]]
        rate = f"{s['completion_30']}%" if s["completion_30"] is not None else "—"
        return (
            f"👤 <b>Уровень {lv.level}</b>\n"
            f"{rules.progress_bar(lv.into, lv.need)} {lv.into}/{lv.need} XP\n\n"
            f"🔥 Серия: <b>{s['streak']}</b> дн. (рекорд {s['best_streak']})\n"
            f"Сегодня: <b>{s['xp_on_day']}</b> XP · всего <b>{s['total_xp']}</b>\n"
            f"Выполнено за 30 дней: {rate}\n"
            f"💰 Монеты: <b>{s['coins']}</b>\n\n"
            f"🏆 Достижения: {len(got)}/{len(s['achievements'])} "
            + "".join(a["emoji"] for a in got)
        )

    def admin_menu(self) -> tuple[str, InlineKeyboardMarkup]:
        tomorrow = self.today() + timedelta(days=1)
        qs = self.game.quests(tomorrow)
        mains = sum(1 for q in qs if q.is_main)
        pu = PlanUI(self)
        hot = [x for x in self.game.planner.schedulable(self.today()) if x["heat"] >= 2]
        text = (f"🛠 <b>Режим админа</b>\n\nНа завтра: {len(qs)} квест(ов), "
                f"основных {mains}/{rules.MAX_MAIN_PER_DAY}, "
                f"{sum(q.xp for q in qs)} XP\n" + pu.load_line(self.game.planner.load(tomorrow)))
        if hot:
            text += "\n\n🔥 <b>Горит в банке:</b>\n" + "\n".join(
                f"{x['heat_emoji']} {escape(x.get('parent_title', '') + ': ' if x.get('parent_title') else '')}"
                f"{escape(x['title'])} — {x['days_left']} дн" for x in hot[:5])
        return text, kb(
            [Btn(text="➕ Квест на завтра", callback_data="adm:add:1"),
             Btn(text="➕ На сегодня", callback_data="adm:add:0")],
            [Btn(text="🗃 Из банка → завтра", callback_data="bk:pick:1"),
             Btn(text="🗃 Банк", callback_data="bk:list")],
            [Btn(text="📋 Шаблон → завтра", callback_data="adm:tpl:1"),
             Btn(text="📋 → сегодня", callback_data="adm:tpl:0")],
            [Btn(text="🗓 План на завтра", callback_data="adm:plan"),
             Btn(text="⏪ Вчера", callback_data="adm:yday")],
            [Btn(text="🌐 Веб-приложение", callback_data="adm:web")],
        )

    def render_promises(self) -> tuple[str, InlineKeyboardMarkup]:
        t = self.today()
        items = self.game.promises(t)
        st = self.game.promise_stats(t)
        lines = ["💌 <b>Обещания</b>", ""]
        rows = []
        if not items:
            lines.append("Открытых обещаний нет 🧹\n\nЧтобы записать, просто напиши боту:\n"
                         "<code>обещал сходить в кино на выходных</code>")
        for p in items:
            mark = "⚠️ " if p["overdue"] else ""
            extra = f", висит {p['age']} дн" if p["due"] is None and p["age"] >= 2 else ""
            moved = f", переносил {p['postponed']}×" if p["postponed"] else ""
            lines.append(f"{mark}• {escape(p['text'])} <i>({p['due_label']}{extra}{moved})</i>")
            rows.append([Btn(text=f"✅ {short(p['text'], 24)}", callback_data=f"p:keep:{p['id']}:l"),
                         Btn(text="📅 ⋯", callback_data=f"p:menu:{p['id']}")])
        if st["kept"]:
            lines.append(f"\nСдержано: <b>{st['kept']}</b> (в срок {st['on_time']})")
        lines.append(f"\n✅ — сдержал: +{rules.PROMISE_XP} XP, а если за {rules.PROMISE_FAST_DAYS} дня — "
                     f"+{round(rules.PROMISE_XP * rules.PROMISE_FAST_MULT)}")
        rows.append([Btn(text="➕ Новое обещание", callback_data="p:new")])
        return "\n".join(lines), kb(*rows)

    def render_promise_menu(self, pid: int) -> tuple[str, InlineKeyboardMarkup]:
        p = self.game.promise(pid, self.today())
        text = (f"💌 <b>{escape(p['text'])}</b>\n\nСрок: {p['due_label']}"
                f"\nОбещал {p['age']} дн назад" + (f", переносил {p['postponed']}×" if p["postponed"] else "")
                + "\n\nКогда сделаешь?")
        return text, kb(
            [Btn(text="Сегодня", callback_data=f"p:due:{pid}:0"),
             Btn(text="Завтра", callback_data=f"p:due:{pid}:1"),
             Btn(text="На выходных", callback_data=f"p:due:{pid}:we")],
            [Btn(text="Через неделю", callback_data=f"p:due:{pid}:7"),
             Btn(text="Без срока", callback_data=f"p:due:{pid}:none")],
            [Btn(text="✅ Уже сдержал", callback_data=f"p:keep:{pid}:l"),
             Btn(text="✕ Отменили вместе", callback_data=f"p:cancel:{pid}")],
            [Btn(text="⬅️ Все обещания", callback_data="p:list")],
        )

    def promise_nudge(self) -> tuple[str, InlineKeyboardMarkup] | None:
        """Ежедневное напоминание. None — если напоминать нечего."""
        t = self.today()
        n = self.game.promises_to_nudge(t)
        pay_lines, pay_rows = FinUI(self).digest_lines()
        bank_lines, bank_rows = PlanUI(self).digest_lines()
        money_lines = []
        for r in self.game.env.settle(t):
            money_lines.append(f"💰 {r['day'][8:10]}.{r['day'][5:7]} в лимите: {r['spent'] // 100} из {r['limit'] // 100} ₽ "
                               f"· сэкономил {r['saved'] // 100} ₽ · +20 XP")
        if self.game.env.on:
            b = self.game.env.budget(t)
            money_lines.append(f"💸 Сегодня можно ~<b>{max(0, b['left_today']) // 100} ₽</b>")
        if not any(n.values()) and not pay_lines and not bank_lines and not money_lines:
            return None
        lines, rows = ["☀️ <b>Сводка на сегодня</b>"], []
        if any(n.values()):
            lines.append("\n💌 <b>Обещания</b>")
        sections = [("overdue", "⚠️ Просрочено"), ("today", "📌 Сегодня"), ("tomorrow", "⏭ Завтра")]
        for key, title in sections:
            if n[key]:
                lines.append(f"\n<b>{title}</b>")
                for p in n[key]:
                    lines.append(f"• {escape(p['text'])}")
                    if key != "tomorrow":
                        rows.append([Btn(text=f"✅ {short(p['text'], 24)}", callback_data=f"p:keep:{p['id']}:l"),
                                     Btn(text="📅", callback_data=f"p:menu:{p['id']}")])
        if n["hanging"]:
            lines.append("\n<b>🕸 Висят без срока</b> — назначь день, пока не спросили:")
            for p in n["hanging"]:
                lines.append(f"• {escape(p['text'])} <i>(уже {p['age']} дн)</i>")
                rows.append([Btn(text=f"📅 {short(p['text'], 28)}", callback_data=f"p:menu:{p['id']}")])
            self.game.mark_nudged([p["id"] for p in n["hanging"]], t)
        if money_lines:
            lines += [""] + money_lines
        lines += bank_lines + pay_lines
        rows += bank_rows + pay_rows
        return "\n".join(lines), kb(*rows)

    def render_shop(self) -> tuple[str, InlineKeyboardMarkup | None]:
        coins = self.game.stats().coins
        items = self.game.shop_items()
        lines = [f"🛒 <b>Магазин</b>\n\n💰 У тебя: <b>{coins}</b> монет\n"]
        rows = []
        if not items:
            lines.append("Пока пусто. Добавь награды в веб-приложении или командой\n"
                         "<code>/item 300 Сходить в квест-комнату</code>")
        for it in items:
            kind = SHOP_KINDS[it["kind"]].split()[0]
            if not it["repeatable"] and it["bought"]:
                lines.append(f"✔️ <s>{escape(it['title'])}</s> — куплено")
                continue
            mark = "" if coins >= it["cost"] else " 🔒"
            lines.append(f"{kind} {escape(it['title'])} — <b>{it['cost']}</b> 💰{mark}")
            rows.append([Btn(text=f"{kind} {short(it['title'], 22)} · {it['cost']}",
                             callback_data=f"shop:ask:{it['id']}")])
        return "\n".join(lines), kb(*rows)


def build_router(cfg: Config, game: Game, auth: Auth) -> Router:
    router = Router()
    ui = UI(cfg, game)

    # ---------- Пока ID не настроен: бот только подсказывает твой ID ----------
    if cfg.owner_id == 0:
        @router.message()
        async def tell_id(msg: Message):
            await msg.answer(f"Твой Telegram ID: <code>{msg.from_user.id}</code>\n"
                             "Впиши его в .env как OWNER_ID и перезапусти бота.")
        return router

    # Всё остальное — только для владельца. Чужие сообщения просто игнорируются.
    router.message.filter(F.from_user.id == cfg.owner_id)
    router.callback_query.filter(F.from_user.id == cfg.owner_id)

    # Любое твоё действие в боте = активность (умный чек-ин не придёт)
    async def activity(handler, event, data):
        user = getattr(event, "from_user", None)
        if user and user.id == cfg.owner_id:
            game.touch()
        return await handler(event, data)
    router.message.outer_middleware(activity)
    router.callback_query.outer_middleware(activity)

    async def edit(cb: CallbackQuery, text: str, markup=None):
        try:
            await cb.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass  # сообщение не изменилось — ничего страшного

    async def celebrate(target: Message, res: dict):
        if res["level_after"] > res["level_before"]:
            await target.answer(f"🎉 <b>НОВЫЙ УРОВЕНЬ: {res['level_after']}</b>\n\n" + ui.render_me())
        for a in res["new_achievements"]:
            head = "🤫 <b>Секретное достижение!</b>" if a.get("secret") else "🏆 <b>Достижение открыто!</b>"
            await target.answer(f"{head}\n{a['emoji']} <b>{a['title']}</b> — {a['desc']}")

    # ================= Постоянная клавиатура (работает из любого состояния) =================

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def cmd_help(msg: Message, state: FSMContext):
        await state.clear()
        await msg.answer(HELP, reply_markup=MAIN_KB)

    @router.message(F.text == K_TODAY)
    @router.message(Command("today"))
    async def k_today(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = ui.render_day(ui.today())
        await msg.answer(text, reply_markup=markup)

    @router.message(F.text == K_ME)
    @router.message(Command("me"))
    async def k_me(msg: Message, state: FSMContext):
        await state.clear()
        await msg.answer(ui.render_me())

    def more_menu() -> tuple[str, InlineKeyboardMarkup]:
        return "☰ <b>Ещё</b>", kb(
            [Btn(text="🛠 Админ", callback_data="more:admin"), Btn(text="👤 Профиль", callback_data="more:me")],
            [Btn(text="💌 Обещания", callback_data="p:list"), Btn(text="🔁 Привычки", callback_data="hb:list")],
            [Btn(text="🛒 Магазин", callback_data="shop:list"), Btn(text="⭐ Оценить день", callback_data="rt:ask:0")],
            [Btn(text="🌐 Приложение", callback_data="adm:web"), Btn(text="⚙ Что показывать", callback_data="more:show")],
        )

    @router.message(F.text == K_MORE)
    async def k_more(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = more_menu()
        await msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "more:menu")
    async def more_back(cb: CallbackQuery):
        await cb.answer()
        text, markup = more_menu()
        await edit(cb, text, markup)

    @router.callback_query(F.data == "more:admin")
    async def more_admin(cb: CallbackQuery):
        await cb.answer()
        text, markup = ui.admin_menu()
        await edit(cb, text, markup)

    @router.callback_query(F.data == "more:me")
    async def more_me(cb: CallbackQuery):
        await cb.answer()
        await edit(cb, ui.render_me(), kb([Btn(text="⬅️ Ещё", callback_data="more:menu")]))

    def show_menu() -> tuple[str, InlineKeyboardMarkup]:
        rows = [[Btn(text=("✅ " if ui.show(k) else "▫️ ") + title, callback_data=f"more:tog:{k}")]
                for k, (title, _) in SHOW.items()]
        rows.append([Btn(text="⬅️ Ещё", callback_data="more:menu")])
        return ("⚙ <b>Что показывать в «Сегодня» сразу</b>\nВыключенное остаётся доступно по маленьким кнопкам внизу.",
                kb(*rows))

    @router.callback_query(F.data == "more:show")
    async def more_show(cb: CallbackQuery):
        await cb.answer()
        text, markup = show_menu()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("more:tog:"))
    async def more_tog(cb: CallbackQuery):
        key = cb.data.split(":")[2]
        if key not in SHOW:
            return await cb.answer()
        game.set_setting(key, "0" if ui.show(key) else "1")
        await cb.answer("Сохранено")
        text, markup = show_menu()
        await edit(cb, text, markup)

    @router.callback_query(F.data == "hb:list")
    async def habits_list(cb: CallbackQuery):
        await cb.answer()
        pu = PlanUI(ui)
        hl, hr = pu.habit_block()
        if not hl:
            return await cb.message.answer("Привычек пока нет. Добавь в приложении: «Ещё» → «Привычки».")
        await cb.message.answer("\n".join(hl).strip(), reply_markup=kb(*hr))

    @router.callback_query(F.data.startswith("day:add:"))
    async def day_add(cb: CallbackQuery):
        off = cb.data.split(":")[2]
        await cb.answer()
        await cb.message.answer("➕ Что добавить?", reply_markup=kb(
            [Btn(text="➕ Квест", callback_data=f"adm:add:{off}"), Btn(text="🗃 Из банка", callback_data=f"bk:pick:{off}")],
            [Btn(text="📋 Шаблон", callback_data=f"adm:tpl:{off}"), Btn(text="🗃 Новая задача в банк", callback_data="bk:new")]))

    @router.message(F.text == K_ADMIN)
    @router.message(Command("admin"))
    async def k_admin(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = ui.admin_menu()
        await msg.answer(text, reply_markup=markup)

    @router.message(F.text == K_SHOP)
    @router.message(Command("shop"))
    async def k_shop(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = ui.render_shop()
        await msg.answer(text, reply_markup=markup)

    @router.message(Command("plan"))
    async def cmd_plan(msg: Message):
        text, markup = ui.render_day(ui.today() + timedelta(days=1))
        await msg.answer(text, reply_markup=markup)

    @router.message(Command("yesterday"))
    async def cmd_yesterday(msg: Message):
        text, markup = ui.render_day(ui.today() - timedelta(days=1))
        await msg.answer(text, reply_markup=markup)

    @router.message(Command("rules"))
    async def cmd_rules(msg: Message):
        lines = ["<b>📜 Правила</b>", "", f"<b>Основные</b> (1–{rules.MAX_MAIN_PER_DAY} в день):"]
        for c in rules.CATEGORIES.values():
            if c.is_main:
                lines.append(f"{c.emoji} {c.title}: {c.xp_min}–{c.xp_max} XP")
        b = rules.CATEGORIES["bonus"]
        lines += ["", f"💌 <b>Обещания</b>: {rules.PROMISE_XP} XP, если за {rules.PROMISE_FAST_DAYS} дня — "
                  f"×{rules.PROMISE_FAST_MULT}"]
        lines += ["", f"<b>Бонусные</b>: {b.xp_min}–{b.xp_max} XP",
                  "", "Границы примерные — за ультра хард можно больше.",
                  f"Уровни: {rules.LEVEL_BASE} XP на первый, дальше +{rules.LEVEL_STEP}.",
                  f"Монеты: XP / {rules.COINS_PER_XP}.",
                  "Серия: день засчитан, если все основные квесты выполнены."]
        await msg.answer("\n".join(lines))

    # ---------- Вход в веб ----------

    async def send_login(target: Message):
        code = auth.new_code()
        link = f"{cfg.public_url}/#code={code}"
        text = (f"🌐 <b>Вход в приложение</b>\n\nКод: <code>{code}</code>\n"
                f"Действует 10 минут, одноразовый.\n\n{escape(link)}")
        markup = kb([Btn(text="Открыть и войти", url=link)]) if link.startswith("https://") else None
        await target.answer(text, reply_markup=markup)

    @router.message(Command("web"))
    async def cmd_web(msg: Message):
        await send_login(msg)

    @router.message(Command("logout_all"))
    async def cmd_logout_all(msg: Message):
        n = auth.logout_all()
        await msg.answer(f"🔒 Выход выполнен на всех устройствах ({n}).")

    # ---------- Команды-шорткаты для админа ----------

    async def add_cmd(msg: Message, args: str | None, day: date, bonus: bool):
        try:
            parts = (args or "").split(maxsplit=1 if bonus else 2)
            if bonus:
                cat = rules.CATEGORIES["bonus"]
                xp_str, title = parts
            else:
                cat_word, xp_str, title = parts
                cat = rules.find_category(cat_word)
                if cat is None:
                    raise GameError(f"Не знаю категорию «{cat_word}». Есть: учеба, работа, гутв, сон, прога, бонус")
            if not xp_str.isdigit():
                raise GameError("XP должно быть числом")
            q, warn = game.add_quest(day, cat, title, int(xp_str))
        except ValueError:
            usage = "/bonus 50 Разобрать стол" if bonus else "/add учеба 300 Лаба по криптографии"
            await msg.answer(f"Формат: <code>{usage}</code>\nИли просто жми «🛠 Админ».")
            return
        except GameError as e:
            await msg.answer(f"⛔ {escape(str(e))}")
            return
        await msg.answer(added_text(q, warn), reply_markup=after_add_kb(q))

    @router.message(Command("add"))
    async def cmd_add(msg: Message, command: CommandObject):
        await add_cmd(msg, command.args, ui.today() + timedelta(days=1), bonus=False)

    @router.message(Command("addnow"))
    async def cmd_addnow(msg: Message, command: CommandObject):
        await add_cmd(msg, command.args, ui.today(), bonus=False)

    @router.message(Command("bonus"))
    async def cmd_bonus(msg: Message, command: CommandObject):
        await add_cmd(msg, command.args, ui.today() + timedelta(days=1), bonus=True)

    @router.message(Command("bonusnow"))
    async def cmd_bonusnow(msg: Message, command: CommandObject):
        await add_cmd(msg, command.args, ui.today(), bonus=True)

    @router.message(Command("item"))
    async def cmd_item(msg: Message, command: CommandObject):
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await msg.answer("Формат: <code>/item 300 Сходить в квест-комнату</code>")
            return
        try:
            it = game.add_shop_item(parts[1], int(parts[0]))
        except GameError as e:
            await msg.answer(f"⛔ {escape(str(e))}")
            return
        await msg.answer(f"🛒 В магазине: {escape(it['title'])} — {it['cost']} 💰")

    # ================= Кнопочная админка: добавление квеста =================

    def added_text(q, warn) -> str:
        off = (date.fromisoformat(q.day) - ui.today()).days
        day = {0: "на сегодня", 1: "на завтра"}.get(off, f"на {date.fromisoformat(q.day):%d.%m}")
        text = f"➕ <b>Добавлено {day}</b>\n{escape(q.line())}"
        if warn:
            text += f"\n⚠️ XP {warn}"
        return text

    def after_add_kb(q) -> InlineKeyboardMarkup:
        off = (date.fromisoformat(q.day) - ui.today()).days
        return kb(
            [Btn(text="➕ Ещё квест", callback_data=f"adm:add:{off}"),
             Btn(text="💾 В шаблоны", callback_data=f"savetpl:{q.id}")],
            [Btn(text="🗓 Весь день", callback_data=f"adm:day:{off}")],
        )

    CANCEL_ROW = [Btn(text="✖️ Отмена", callback_data="cancel")]

    @router.callback_query(F.data.startswith("adm:add:"))
    async def adm_add(cb: CallbackQuery, state: FSMContext):
        off = int(cb.data.split(":")[2])
        await state.clear()
        await state.set_state(AddQuest.category)
        await state.update_data(off=off)
        day = "сегодня" if off == 0 else "завтра"
        cats = [c for c in rules.CATEGORIES.values() if c.pickable]
        rows = [[Btn(text=f"{c.emoji} {c.title}", callback_data=f"cat:{c.key}") for c in cats[i:i + 2]]
                for i in range(0, len(cats), 2)]
        await cb.answer()
        await edit(cb, f"➕ <b>Новый квест на {day}</b>\n\nШаг 1/4 — категория:", kb(*rows, CANCEL_ROW))

    @router.callback_query(AddQuest.category, F.data.startswith("cat:"))
    async def pick_cat(cb: CallbackQuery, state: FSMContext):
        cat = rules.CATEGORIES.get(cb.data.split(":")[1])
        if cat is None:
            await cb.answer("?")
            return
        await state.update_data(cat=cat.key)
        await state.set_state(AddQuest.xp)
        presets = xp_presets(cat)
        rows = [[Btn(text=str(v), callback_data=f"xp:{v}") for v in presets],
                [Btn(text="✏️ Своё число", callback_data="xp:custom")], CANCEL_ROW]
        await cb.answer()
        await edit(cb, f"{cat.emoji} <b>{cat.title}</b>\n\nШаг 2/4 — сколько XP?\n"
                       f"Обычно {cat.xp_min}–{cat.xp_max}, за ультра хард можно больше.", kb(*rows))

    @router.callback_query(AddQuest.xp, F.data.startswith("xp:"))
    async def pick_xp(cb: CallbackQuery, state: FSMContext):
        val = cb.data.split(":")[1]
        await cb.answer()
        if val == "custom":
            await state.set_state(AddQuest.xp_custom)
            await edit(cb, "✏️ Напиши число XP сообщением:", kb(CANCEL_ROW))
            return
        await state.update_data(xp=int(val))
        await state.set_state(AddQuest.est)
        await edit(cb, f"<b>{val} XP</b>\n\nШаг 3/4 — сколько примерно времени?", kb(*time_rows("qt"), CANCEL_ROW))

    @router.message(AddQuest.xp_custom, F.text)
    async def custom_xp(msg: Message, state: FSMContext):
        if not msg.text.strip().isdigit():
            await msg.answer("Нужно целое число, например <code>650</code>")
            return
        await state.update_data(xp=int(msg.text.strip()))
        await state.set_state(AddQuest.est)
        await msg.answer(f"<b>{int(msg.text)} XP</b>\n\nШаг 3/4 — сколько примерно времени?",
                         reply_markup=kb(*time_rows("qt"), CANCEL_ROW))

    @router.callback_query(AddQuest.est, F.data.startswith("qt:"))
    async def pick_est(cb: CallbackQuery, state: FSMContext):
        m = int(cb.data.split(":")[1])
        await state.update_data(est=m or None)
        await state.set_state(AddQuest.title)
        await cb.answer()
        await edit(cb, (f"⏱ {rules.fmt_min(m)}\n\n" if m else "") + "Шаг 4/4 — напиши название квеста сообщением:",
                   kb(CANCEL_ROW))

    @router.message(AddQuest.title, F.text)
    async def got_title(msg: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        try:
            q, warn = game.add_quest(ui.today() + timedelta(days=data["off"]),
                                     rules.CATEGORIES[data["cat"]], msg.text, data["xp"], data.get("est"))
        except GameError as e:
            await msg.answer(f"⛔ {escape(str(e))}")
            return
        await msg.answer(added_text(q, warn), reply_markup=after_add_kb(q))

    @router.callback_query(F.data == "cancel")
    async def cancel(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer("Отменено")
        text, markup = ui.admin_menu()
        await edit(cb, text, markup)

    # ================= Шаблоны =================

    @router.callback_query(F.data.startswith("adm:tpl:"))
    async def adm_tpl(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        off = int(cb.data.split(":")[2])
        tpls = game.templates()
        rows = [[Btn(text=f"{rules.CATEGORIES[t['category']].emoji} {short(t['title'], 24)} · {t['xp']}",
                     callback_data=f"tpl:{off}:{t['id']}")] for t in tpls]
        await cb.answer()
        day = "сегодня" if off == 0 else "завтра"
        text = f"📋 <b>Шаблоны → {day}</b>\n\nЖми — квест добавится сразу."
        if not tpls:
            text += "\n\nШаблонов пока нет. Добавь квест и нажми «💾 В шаблоны»."
        await edit(cb, text, kb(*rows, [Btn(text="⬅️ Назад", callback_data="cancel")]))

    @router.callback_query(F.data.startswith("tpl:"))
    async def use_tpl(cb: CallbackQuery):
        _, off, tid = cb.data.split(":")
        try:
            q, warn = game.add_from_template(ui.today() + timedelta(days=int(off)), int(tid))
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer(f"Добавлено: {q.title}")
        # остаёмся в списке шаблонов — можно тыкать дальше
        qs = game.quests(date.fromisoformat(q.day))
        await edit(cb, f"📋 <b>Шаблоны</b>\n\nДобавлено: {escape(q.title)}"
                       f"\nВ этом дне уже {len(qs)} квест(ов), {sum(x.xp for x in qs)} XP",
                   cb.message.reply_markup)

    @router.callback_query(F.data.startswith("savetpl:"))
    async def save_tpl(cb: CallbackQuery):
        try:
            q = game.get(int(cb.data.split(":")[1]))
            game.add_template(q.category, q.title, q.xp, q.est_min)
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer("💾 Сохранено в шаблоны")

    # ================= Просмотр дней из админки =================

    @router.callback_query(F.data.in_({"adm:plan", "adm:yday"}) | F.data.startswith("adm:day:"))
    async def adm_day(cb: CallbackQuery):
        if cb.data == "adm:plan":
            off = 1
        elif cb.data == "adm:yday":
            off = -1
        else:
            off = int(cb.data.split(":")[2])
        text, markup = ui.render_day(ui.today() + timedelta(days=off))
        await cb.answer()
        await cb.message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm:web")
    async def adm_web(cb: CallbackQuery):
        await cb.answer()
        await send_login(cb.message)

    # ================= Отметки квестов =================

    @router.callback_query(F.data.regexp(r"^(done|failed|todo|del):\d+$"))
    async def on_quest_button(cb: CallbackQuery):
        action, qid = cb.data.split(":")
        try:
            if action == "del":
                q = game.delete_quest(int(qid))
                await cb.answer("Удалено")
                res = None
            else:
                res = game.mark(int(qid), action, ui.today())
                q = res["quest"]
                await cb.answer({"done": f"ЗАДАНИЕ ВЫПОЛНЕНО  +{q.xp} XP",
                                 "failed": "Провалено. Бывает.", "todo": "Отменено"}[action])
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        text, markup = ui.render_day(date.fromisoformat(q.day))
        await edit(cb, text, markup)
        if res:
            await celebrate(cb.message, res)
            fresh = game.get(q.id) if action == "done" else None
            if fresh and fresh.est_min and fresh.pace is None and fresh.timer_sec < 60:
                await cb.message.answer(
                    f"⏱ «{escape(short(q.title, 40))}» — по времени как вышло? (можно не отвечать)",
                    reply_markup=kb([Btn(text="⚡ Быстрее", callback_data=f"pc:{q.id}:fast"),
                                     Btn(text="👌 Как думал", callback_data=f"pc:{q.id}:ok"),
                                     Btn(text="🐢 Дольше", callback_data=f"pc:{q.id}:slow")]))

    # ================= Магазин =================

    @router.callback_query(F.data.startswith("shop:ask:"))
    async def shop_ask(cb: CallbackQuery):
        try:
            it = game.shop_item(int(cb.data.split(":")[2]))
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer()
        coins = game.stats().coins
        await edit(cb, f"🛒 Купить <b>{escape(it['title'])}</b> за {it['cost']} 💰?\n"
                       f"У тебя {coins}, останется {coins - it['cost']}.",
                   kb([Btn(text="✅ Купить", callback_data=f"shop:buy:{it['id']}"),
                       Btn(text="⬅️ Назад", callback_data="shop:list")]))

    @router.callback_query(F.data.startswith("shop:buy:"))
    async def shop_buy(cb: CallbackQuery):
        before = game._achieved(ui.today())
        try:
            it, left = game.buy(int(cb.data.split(":")[2]))
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer("Куплено!")
        await edit(cb, f"🎁 <b>КУПЛЕНО:</b> {escape(it['title'])}\n\nЗаслужил — наслаждайся. "
                       f"Осталось {left} 💰",
                   kb([Btn(text="⬅️ В магазин", callback_data="shop:list")]))
        new = [a for a in game.full_stats(ui.today())["achievements"]
               if a["done"] and a["key"] not in before]
        await celebrate(cb.message, {"level_before": 0, "level_after": 0, "new_achievements": new})

    @router.callback_query(F.data == "shop:list")
    async def shop_list(cb: CallbackQuery):
        await cb.answer()
        text, markup = ui.render_shop()
        await edit(cb, text, markup)

    # ================= Обещания =================

    @router.message(F.text == K_PROM)
    @router.message(Command("promises"))
    async def k_prom(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = ui.render_promises()
        await msg.answer(text, reply_markup=markup)

    async def save_promise(msg: Message, raw: str):
        t = ui.today()
        body, due = parse_promise(raw, t)
        try:
            p = game.add_promise(body, t, due)
        except GameError as e:
            await msg.answer(f"⛔ {escape(str(e))}")
            return
        hint = "" if due else f"\nСрока нет — через {rules.PROMISE_NUDGE_AFTER} дня спрошу «когда?». Или назначь сейчас:"
        markup = kb([Btn(text="📅 Назначить срок", callback_data=f"p:menu:{p['id']}"),
                     Btn(text="🗑 Ошибся", callback_data=f"p:undo:{p['id']}")],
                    [Btn(text="💌 Все обещания", callback_data="p:list")])
        await msg.answer(f"💌 <b>Записал:</b> {escape(p['text'])}\nСрок: <b>{p['due_label']}</b>{hint}",
                         reply_markup=markup)

    @router.message(StateFilter(None), F.text.regexp(r"(?i)^\s*(я\s+)?(по)?обещ"))
    async def promise_text(msg: Message):
        await save_promise(msg, msg.text)

    @router.callback_query(F.data == "p:new")
    async def p_new(cb: CallbackQuery, state: FSMContext):
        await state.set_state(NewPromise.text)
        await cb.answer()
        await cb.message.answer("💌 Что пообещал? Напиши одним сообщением, срок можно прямо в тексте:\n"
                                "<i>забрать посылку в пятницу</i>", reply_markup=kb(CANCEL_ROW))

    @router.message(NewPromise.text, F.text)
    async def p_new_text(msg: Message, state: FSMContext):
        await state.clear()
        await save_promise(msg, msg.text)

    @router.callback_query(F.data == "p:list")
    async def p_list(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer()
        text, markup = ui.render_promises()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("p:menu:"))
    async def p_menu(cb: CallbackQuery):
        try:
            text, markup = ui.render_promise_menu(int(cb.data.split(":")[2]))
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer()
        await cb.message.answer(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("p:due:"))
    async def p_due(cb: CallbackQuery):
        _, _, pid, code = cb.data.split(":")
        t = ui.today()
        due = {"0": t, "1": t + timedelta(days=1), "7": t + timedelta(days=7), "none": None,
               "we": t if t.weekday() == 5 else t + timedelta(days=(5 - t.weekday()) % 7)}[code]
        try:
            p = game.set_promise_due(int(pid), due, t)
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer(f"Срок: {p['due_label']}")
        text, markup = ui.render_promises()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("p:keep:"))
    async def p_keep(cb: CallbackQuery):
        parts = cb.data.split(":")
        try:
            res = game.keep_promise(int(parts[2]), ui.today())
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer(f"💌 СДЕРЖАЛ  +{res['xp']} XP" + ("  ⚡ быстро!" if res["fast"] else ""))
        if len(parts) > 3 and parts[3] == "d":
            text, markup = ui.render_day(ui.today())
        else:
            text, markup = ui.render_promises()
        await edit(cb, text, markup)
        await celebrate(cb.message, res)

    @router.callback_query(F.data.startswith("p:cancel:"))
    async def p_cancel(cb: CallbackQuery):
        try:
            game.cancel_promise(int(cb.data.split(":")[2]), ui.today())
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer("Отменено — без штрафа")
        text, markup = ui.render_promises()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("p:undo:"))
    async def p_undo(cb: CallbackQuery):
        pid = int(cb.data.split(":")[2])
        try:
            p = game.promise(pid, ui.today())
            if p["status"] != "open":
                raise GameError("Обещание уже закрыто")
        except GameError as e:
            await cb.answer(str(e), show_alert=True)
            return
        game.conn.execute("DELETE FROM promises WHERE id = ?", (pid,))
        game.conn.commit()
        await cb.answer("Удалено")
        await edit(cb, f"🗑 <s>{escape(p['text'])}</s>")

    @router.message(Command("bank"))
    async def cmd_bank(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = PlanUI(ui).bank()
        await msg.answer(text, reply_markup=markup)

    @router.message(Command("finance"))
    async def cmd_finance(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = FinUI(ui).money()
        await msg.answer(text, reply_markup=markup)

    register_finance(router, ui, edit, celebrate, MAIN_KB)
    register_planner(router, ui, edit, celebrate)

    # Любой другой текст вне диалогов — подсказка
    @router.message(StateFilter(None), F.text)
    async def unknown_text(msg: Message):
        await msg.answer("Не понял 🤔 Пользуйся кнопками внизу.\n\n"
                         "💌 Обещание: <code>обещал позвонить в субботу</code>\n"
                         "💸 Трата: <code>кофе 250</code>  ·  💵 доход: <code>+3000 монтаж</code>",
                         reply_markup=MAIN_KB)

    @router.callback_query()
    async def stale(cb: CallbackQuery):
        await cb.answer("Эта кнопка устарела — открой меню заново", show_alert=False)

    return router


async def reminders_loop(bot: Bot, cfg: Config, game: Game) -> None:
    """Раз в 20 секунд проверяет, не пора ли напомнить. Время задаётся в веб-приложении."""
    ui = UI(cfg, game)
    # новое меню: один раз присылаем клавиатуру, чтобы она обновилась на телефоне
    if game.get_setting("kb_version") != KB_VERSION:
        try:
            await bot.send_message(cfg.owner_id, "🆕 <b>Обновление</b>: меню стало короче.\n"
                                   "🎮 Сегодня · 💰 Деньги · 🗃 Банк · ☰ Ещё\n"
                                   "Что показывать в «Сегодня» сразу — ☰ Ещё → ⚙", reply_markup=MAIN_KB)
            game.set_setting("kb_version", KB_VERSION)
        except Exception as e:
            print("Не удалось прислать меню:", e)
    while True:
        try:
            now = datetime.now(cfg.tz)
            hm, today_str = now.strftime("%H:%M"), now.date().isoformat()
            for kind in ("morning", "evening", "promises"):
                default = "10:00" if kind == "promises" else ""
                if game.get_setting(f"remind_{kind}", default) != hm:
                    continue
                if game.get_setting(f"sent_{kind}") == today_str:
                    continue
                game.set_setting(f"sent_{kind}", today_str)
                if kind == "promises":
                    nudge = ui.promise_nudge()
                    if nudge is None:
                        continue
                    text, markup = nudge
                elif kind == "morning":
                    text, markup = ui.render_day(ui.today(), "☀️ <b>Новый день. Игра началась.</b>")
                else:
                    plan, _ = ui.render_day(ui.today() + timedelta(days=1))
                    text, markup = ui.admin_menu()
                    text = "🌙 <b>Время админа.</b> Настрой завтрашний день.\n\n" + plan
                    if game.life.rating(ui.today()) is None:
                        text += "\n\n⭐ И оцени сегодняшний день (1–10):"
                        markup = kb(*markup.inline_keyboard, *PlanUI.rating_rows(0))
                await bot.send_message(cfg.owner_id, text, reply_markup=markup)
            # ⏰ «пора садиться за квесты» — один раз в день
            if game.get_setting("remind_startby", "1") == "1" and game.get_setting("sent_startby") != today_str:
                sb = game.planner.start_by(ui.today(), now)
                if sb and sb["remaining_min"] and sb["late"]:
                    game.set_setting("sent_startby", today_str)
                    text, markup = ui.render_day(ui.today(), "⏰ <b>Пора садиться за квесты</b>")
                    await bot.send_message(cfg.owner_id, text, reply_markup=markup)
            # 🏆 итоги сезона — в первый день месяца после 10:00
            prev = (now.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            if now.day == 1 and now.hour >= 10 and game.get_setting("season_sent") != prev:
                game.set_setting("season_sent", prev)
                if game.life.period(*month_bounds(prev))["active_days"]:
                    await bot.send_message(cfg.owner_id, PlanUI(ui).season_card(prev))
            # умный чек-ин
            if game.checkin_due(now.hour):
                game.checkin_sent()
                text, markup = FinUI(ui).checkin()
                await bot.send_message(cfg.owner_id, text, reply_markup=markup)
        except Exception as e:  # напоминание не должно ронять бота
            print("Ошибка напоминания:", e)
        await asyncio.sleep(20)


def make_bot(cfg: Config, game: Game, auth: Auth) -> tuple[Bot, Dispatcher]:
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(build_router(cfg, game, auth))
    return bot, dp


COMMANDS = [
    BotCommand(command="today", description="Квесты на сегодня"),
    BotCommand(command="admin", description="Режим админа"),
    BotCommand(command="me", description="Уровень, серия, монеты"),
    BotCommand(command="shop", description="Магазин"),
    BotCommand(command="promises", description="Обещания"),
    BotCommand(command="finance", description="Финансы"),
    BotCommand(command="bank", description="Банк заданий"),
    BotCommand(command="web", description="Войти в веб-приложение"),
    BotCommand(command="help", description="Помощь"),
]
