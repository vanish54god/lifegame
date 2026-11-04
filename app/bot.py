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
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton as Btn,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

from . import rules
from .auth import Auth
from .config import Config
from .game import SHOP_KINDS, Game, GameError, game_day

# Тексты кнопок постоянной клавиатуры
K_TODAY, K_ME, K_ADMIN, K_SHOP = "🎮 Сегодня", "👤 Профиль", "🛠 Админ", "🛒 Магазин"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=K_TODAY), KeyboardButton(text=K_ME)],
              [KeyboardButton(text=K_ADMIN), KeyboardButton(text=K_SHOP)]],
    resize_keyboard=True, is_persistent=True,
)

HELP = """<b>🎮 Как играть</b>

Вечером ты <b>админ</b>: жми «🛠 Админ» и собирай квесты на завтра.
Утром ты <b>игрок</b>: «🎮 Сегодня» и отмечай ✅ / ❌.
Монеты тратятся в «🛒 Магазине».

<b>Команды на всякий случай</b>
/add <i>категория xp название</i> — квест на завтра
/bonus <i>xp название</i> — бонус на завтра
/addnow, /bonusnow — то же на сегодня
/item <i>цена название</i> — товар в магазин
/web — войти в веб-приложение
/logout_all — выйти из приложения на всех устройствах
/rules — категории и границы XP"""


class AddQuest(StatesGroup):
    category = State()
    xp = State()
    xp_custom = State()
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

    def render_day(self, day: date, header: str | None = None) -> tuple[str, InlineKeyboardMarkup | None]:
        t = self.today()
        quests = self.game.quests(day)
        planning = day > t
        lines = [header or self.day_title(day), ""]
        if not quests:
            lines.append("Квестов нет. Админ, твой выход 👇" if day >= t else "В этот день квестов не было.")
        lines += [escape(q.line()) for q in quests]
        if quests and not any(q.is_main for q in quests):
            lines.append("\n⚠️ Нет ни одного основного задания (нужно 1–3)")
        if planning:
            lines.append(f"\nВсего можно взять: <b>{sum(q.xp for q in quests)}</b> XP")
        else:
            st = self.game.stats(day)
            lines.append(f"\nЗа день: <b>{st.xp_on_day}</b> / {sum(q.xp for q in quests)} XP")

        off = (day - t).days
        rows = []
        for q in quests:
            if planning:
                rows.append([Btn(text=f"🗑 {short(q.title)}", callback_data=f"del:{q.id}")])
            elif q.status == "todo":
                rows.append([Btn(text=f"✅ {short(q.title)}", callback_data=f"done:{q.id}"),
                             Btn(text="❌", callback_data=f"failed:{q.id}")])
            else:
                rows.append([Btn(text=f"↩️ {short(q.title)}", callback_data=f"todo:{q.id}")])
        if off in (0, 1):
            rows.append([Btn(text="➕ Квест", callback_data=f"adm:add:{off}"),
                         Btn(text="📋 Шаблон", callback_data=f"adm:tpl:{off}")])
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
        text = (f"🛠 <b>Режим админа</b>\n\nНа завтра: {len(qs)} квест(ов), "
                f"основных {mains}/{rules.MAX_MAIN_PER_DAY}, "
                f"{sum(q.xp for q in qs)} XP")
        return text, kb(
            [Btn(text="➕ Квест на завтра", callback_data="adm:add:1"),
             Btn(text="➕ На сегодня", callback_data="adm:add:0")],
            [Btn(text="📋 Шаблон → завтра", callback_data="adm:tpl:1"),
             Btn(text="📋 → сегодня", callback_data="adm:tpl:0")],
            [Btn(text="🗓 План на завтра", callback_data="adm:plan"),
             Btn(text="⏪ Вчера", callback_data="adm:yday")],
            [Btn(text="🌐 Веб-приложение", callback_data="adm:web")],
        )

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
        cats = list(rules.CATEGORIES.values())
        rows = [[Btn(text=f"{c.emoji} {c.title}", callback_data=f"cat:{c.key}") for c in cats[i:i + 2]]
                for i in range(0, len(cats), 2)]
        await cb.answer()
        await edit(cb, f"➕ <b>Новый квест на {day}</b>\n\nШаг 1/3 — категория:", kb(*rows, CANCEL_ROW))

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
        await edit(cb, f"{cat.emoji} <b>{cat.title}</b>\n\nШаг 2/3 — сколько XP?\n"
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
        await state.set_state(AddQuest.title)
        await edit(cb, f"<b>{val} XP</b>\n\nШаг 3/3 — напиши название квеста сообщением:", kb(CANCEL_ROW))

    @router.message(AddQuest.xp_custom, F.text)
    async def custom_xp(msg: Message, state: FSMContext):
        if not msg.text.strip().isdigit():
            await msg.answer("Нужно целое число, например <code>650</code>")
            return
        await state.update_data(xp=int(msg.text.strip()))
        await state.set_state(AddQuest.title)
        await msg.answer(f"<b>{int(msg.text)} XP</b>\n\nШаг 3/3 — напиши название квеста:", reply_markup=kb(CANCEL_ROW))

    @router.message(AddQuest.title, F.text)
    async def got_title(msg: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        try:
            q, warn = game.add_quest(ui.today() + timedelta(days=data["off"]),
                                     rules.CATEGORIES[data["cat"]], msg.text, data["xp"])
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
            game.add_template(q.category, q.title, q.xp)
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

    @router.callback_query()
    async def stale(cb: CallbackQuery):
        await cb.answer("Эта кнопка устарела — открой меню заново", show_alert=False)

    return router


async def reminders_loop(bot: Bot, cfg: Config, game: Game) -> None:
    """Раз в 20 секунд проверяет, не пора ли напомнить. Время задаётся в веб-приложении."""
    ui = UI(cfg, game)
    while True:
        try:
            now = datetime.now(cfg.tz)
            hm, today_str = now.strftime("%H:%M"), now.date().isoformat()
            for kind in ("morning", "evening"):
                if game.get_setting(f"remind_{kind}", "") != hm:
                    continue
                if game.get_setting(f"sent_{kind}") == today_str:
                    continue
                game.set_setting(f"sent_{kind}", today_str)
                if kind == "morning":
                    text, markup = ui.render_day(ui.today(), "☀️ <b>Новый день. Игра началась.</b>")
                else:
                    plan, _ = ui.render_day(ui.today() + timedelta(days=1))
                    text, markup = ui.admin_menu()
                    text = "🌙 <b>Время админа.</b> Настрой завтрашний день.\n\n" + plan
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
    BotCommand(command="web", description="Войти в веб-приложение"),
    BotCommand(command="help", description="Помощь"),
]
