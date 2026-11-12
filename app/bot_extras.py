"""Бот: ⭐ розыск, ⏰ дедлайны за 7 и 5 дней, 🌙 «иду спать», 🎲 побочки, 📊 статистика как в GTA."""

from datetime import date, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message

from .planner import wanted
from .sidequests import SideError


class SideAdd(StatesGroup):
    title = State()


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def stars_line(w: dict) -> str | None:
    if not w["stars"]:
        return None
    n = len(w["items"])
    return f"🚨 Розыск: {'★' * w['stars']}{'☆' * (5 - w['stars'])} — {n} {'просрочка' if n == 1 else 'просрочки' if n < 5 else 'просрочек'} в банке"


def sleep_kb() -> InlineKeyboardMarkup:
    return kb([Btn(text="🌙 Иду спать", callback_data="sl:go")])


def side_offer_msg(o: dict) -> tuple[str, InlineKeyboardMarkup]:
    it = o["item"]
    return (f"🎲 <b>Побочка дня</b>\n{escape(it['title'])}\n+{it['xp']} XP, если сегодня. Без штрафа, если нет.",
            kb([Btn(text="✅ Беру", callback_data=f"sd:a:{o['id']}:1"),
                Btn(text="⏭ Не сегодня", callback_data=f"sd:a:{o['id']}:0")]))


def deadline_pings(game, today: date) -> list[str]:
    """Задачи банка, до дедлайна которых ровно неделя или 5 дней."""
    out = []
    for t in game.planner.tasks(today):
        for x in [c for c in t["children"] if c["status"] == "open"] or [t]:
            if x["days_left"] in (7, 5):
                when = "через неделю" if x["days_left"] == 7 else "через 5 дней"
                est = f" · ~{x['est_min'] // 60} ч {x['est_min'] % 60:02d} мин" if x.get("est_min") else ""
                out.append(f"⏰ <b>{escape(x['title'])}</b> — дедлайн {when} ({x['deadline'][8:10]}.{x['deadline'][5:7]}){est}")
    return out


def funstats_text(game, today: date) -> str:
    lines = ["📊 <b>Статистика</b>"]
    for g in game.funstats.all(today):
        lines.append(f"\n<b>{g['title']}</b>")
        for i in g["items"]:
            lines.append(f"{escape(i['label'])}: <b>{i['value']}</b>" + (f" <i>({escape(str(i['sub']))})</i>" if i["sub"] else ""))
    return "\n".join(lines)


def register_extras(router: Router, ui, edit, celebrate):
    game = ui.game

    # ---------- 🌙 иду спать ----------

    async def go_sleep(target: Message):
        lvl = game.stats().level.level
        before = game._achieved(ui.today())
        r = game.sleep.go(ui.today(), datetime.now(ui.cfg.tz))
        if r["ontime"]:
            text = (f"🌙 Отбой в {r['at']} — <b>вовремя!</b> +{r['xp']} XP\n"
                    f"Серия: {r['streak']} {'ночь' if r['streak'] == 1 else 'ночи' if r['streak'] < 5 else 'ночей'}")
        else:
            text = f"🌙 Записал: {r['at']}. Отбой был в {r['bedtime']} — завтра получится 😴"
        if r["avg"]:
            text += f"\nЗа неделю: вовремя {r['week_ontime']}/{r['week_logged']}, в среднем в {r['avg']}"
        if game.life.rating(ui.today()) is None:
            from .bot_planner import PlanUI
            text += "\n\n⭐ И точка в конце дня — как он прошёл (1–10)?"
            await target.answer(text, reply_markup=kb(*PlanUI.rating_rows(0)))
        else:
            await target.answer(text + "\n\nСпокойной ночи ✨")
        new = [a for a in game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]
        await celebrate(target, {"level_before": lvl, "level_after": game.stats().level.level, "new_achievements": new})

    @router.message(Command("sleep"))
    async def cmd_sleep(msg: Message):
        await go_sleep(msg)

    @router.callback_query(F.data == "sl:go")
    async def cb_sleep(cb: CallbackQuery):
        await cb.answer("🌙")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await go_sleep(cb.message)

    # ---------- 🎲 побочки ----------

    def side_screen() -> tuple[str, InlineKeyboardMarkup]:
        pool = game.side.pool()
        lines = ["🎲 <b>Побочки</b>", "<i>Маленькие приятные дела. Пару раз в неделю, в случайный момент, бот предложит одно.</i>", ""]
        rows = []
        if not pool:
            lines.append("Пул пуст. Добавь, например: «позвонить бабушке», «разобрать фото», «прогулка без телефона».")
        for it in pool:
            lines.append(f"• {escape(it['title'])} · {it['xp']} XP" + (f" · сделано {it['done']}" if it["done"] else ""))
            rows.append([Btn(text=f"✖️ {it['title'][:28]}", callback_data=f"sd:rm:{it['id']}")])
        rows.append([Btn(text="＋ Добавить", callback_data="sd:add"), Btn(text="🎲 Дай побочку", callback_data="sd:now")])
        return "\n".join(lines), kb(*rows)

    @router.message(Command("side"))
    async def cmd_side(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = side_screen()
        await msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "sd:home")
    async def sd_home(cb: CallbackQuery):
        await cb.answer()
        text, markup = side_screen()
        await edit(cb, text, markup)

    @router.callback_query(F.data == "sd:add")
    async def sd_add(cb: CallbackQuery, state: FSMContext):
        await state.set_state(SideAdd.title)
        await cb.answer()
        await cb.message.answer("Что за побочка? Можно несколько — каждую с новой строки. XP по умолчанию 50, "
                                "или допиши в конце: <code>Разобрать фото 80</code>")

    @router.message(SideAdd.title, F.text)
    async def sd_add_title(msg: Message, state: FSMContext):
        await state.clear()
        added = 0
        for line in msg.text.split("\n"):
            line = line.strip(" -•")
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            xp = 50
            if len(parts) == 2 and parts[1].isdigit():
                line, xp = parts[0], int(parts[1])
            try:
                game.side.add(line, xp)
                added += 1
            except SideError as e:
                await msg.answer(f"⛔ {escape(line)}: {escape(str(e))}")
        text, markup = side_screen()
        await msg.answer(f"🎲 Добавлено: {added}\n\n" + text, reply_markup=markup)

    @router.callback_query(F.data.startswith("sd:rm:"))
    async def sd_rm(cb: CallbackQuery):
        game.side.remove(int(cb.data.split(":")[2]))
        await cb.answer("Убрано")
        text, markup = side_screen()
        await edit(cb, text, markup)

    @router.callback_query(F.data == "sd:now")
    async def sd_now(cb: CallbackQuery):
        o = game.side.offer(ui.today())
        if not o:
            return await cb.answer("Пул пуст — добавь пару побочек", show_alert=True)
        if o["status"] != "offered":
            return await cb.answer("Сегодня побочка уже была 🙂", show_alert=True)
        await cb.answer()
        await cb.message.answer(*side_offer_msg(o))

    @router.callback_query(F.data.startswith("sd:a:"))
    async def sd_answer(cb: CallbackQuery):
        _, _, oid, take = cb.data.split(":")
        try:
            o = game.side.answer(int(oid), take == "1", ui.today())
        except SideError as e:
            return await cb.answer(str(e), show_alert=True)
        it = o["item"]
        await cb.answer("🎲 В квестах на сегодня" if take == "1" else "Ок, в другой раз")
        await edit(cb, (f"🎲 <b>Взял:</b> {escape(it['title'])} · +{it['xp']} XP — в бонусных квестах на сегодня"
                        if take == "1" else f"⏭ Пропустил: {escape(it['title'])}"))

    # ---------- 📊 статистика ----------

    @router.message(Command("stats"))
    async def cmd_stats(msg: Message):
        await msg.answer(funstats_text(game, ui.today()))

    @router.callback_query(F.data == "fs:show")
    async def fs_show(cb: CallbackQuery):
        await cb.answer()
        await edit(cb, funstats_text(game, ui.today()), kb([Btn(text="⬅️ Ещё", callback_data="more:menu")]))
