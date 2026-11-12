"""🎬 Сюжетные миссии в боте: /story, этапы кнопками, финал с текстовой катсценой, новая миссия."""

import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message

from .story import StoryError


class NewMission(StatesGroup):
    title = State()
    steps = State()


class Outro(StatesGroup):
    text = State()


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def short(t: str, n: int = 26) -> str:
    return t if len(t) <= n else t[: n - 1] + "…"


def cutscene_text(m: dict) -> str:
    bar = "▬" * 14
    return (f"<code>{bar}</code>\n"
            + (f"<i>{escape(m.get('chapter', ''))}</i>\n" if m.get("chapter") else "")
            + f"🎬 <b>МИССИЯ ПРОЙДЕНА</b>\n\n<b>{escape(m['emoji'])} {escape(m['title'].upper())}</b>\n"
            + (f"\n<i>«{escape(m['outro'])}»</i>\n" if m.get("outro") else "")
            + f"\n+{m['xp']} XP · 😮‍💨 Респект +1\n<code>{bar}</code>")


def strip_line(game) -> str | None:
    """Строка активной миссии для «Сегодня» — как текущее задание в GTA."""
    act = game.story.missions("active")
    if not act:
        return None
    m = act[0]
    nxt = f" · ▸ {escape(m['next_step']['title'])}" if m["next_step"] else ""
    return f"🎬 <b>Сюжет:</b> {escape(m['title'])}{nxt}"


def register_story(router: Router, ui, edit, celebrate):
    game = ui.game
    st = game.story

    def screen() -> tuple[str, InlineKeyboardMarkup]:
        t = ui.today()
        ch = st.chapter(t)
        act, paused = st.missions("active"), st.missions("paused")
        lines = [f"🎬 <b>Сюжет</b> · {escape(ch['title'])}", f"😮‍💨 Респект: {st.respect()}", ""]
        rows = []
        if not act and not paused:
            lines.append("Активных миссий нет. Важное событие на горизонте? Жми «＋ Миссия».")
        for m in act + paused:
            mark = "⏸ " if m["status"] == "paused" else ""
            lines.append(f"{mark}{escape(m['emoji'])} <b>{escape(m['title'])}</b> — {m['xp']} XP"
                         + (f" · этапы {m['steps_done']}/{m['steps_total']}" if m["steps_total"] else ""))
            for s in m["steps"]:
                lines.append(f"   {'✅' if s['done_day'] else '▫️'} {escape(s['title'])}" + (f" (+{s['xp']})" if s["xp"] else ""))
            rows.append([Btn(text=f"{escape(m['emoji'])} {short(m['title'], 28)}", callback_data=f"st:m:{m['id']}")])
        rows.append([Btn(text="＋ Миссия", callback_data="st:new"), Btn(text="📖 Хроника", callback_data="st:chr")])
        return "\n".join(lines), kb(*rows)

    def mission(mid: int) -> tuple[str, InlineKeyboardMarkup]:
        m = st.get(mid)
        lines = [f"{escape(m['emoji'])} <b>{escape(m['title'])}</b>", f"Финал: <b>{m['xp']} XP</b>"]
        if m["why"]:
            lines.append(f"<i>{escape(m['why'])}</i>")
        rows = []
        for s in m["steps"]:
            lines.append(f"{'✅' if s['done_day'] else '▫️'} {escape(s['title'])}" + (f" (+{s['xp']})" if s["xp"] else ""))
            rows.append([Btn(text=("↩️ " if s["done_day"] else "✅ ") + short(s["title"], 30), callback_data=f"st:s:{s['id']}")])
        rows.append([Btn(text="🏁 Миссия пройдена", callback_data=f"st:fin:{mid}")])
        rows.append([Btn(text="▶️ Продолжить" if m["status"] == "paused" else "⏸ Отложить", callback_data=f"st:p:{mid}"),
                     Btn(text="⬅️ Сюжет", callback_data="st:home")])
        return "\n".join(lines), kb(*rows)

    @router.message(Command("story"))
    async def cmd_story(msg: Message, state: FSMContext):
        await state.clear()
        text, markup = screen()
        await msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "st:home")
    async def st_home(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer()
        text, markup = screen()
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("st:m:"))
    async def st_mission(cb: CallbackQuery):
        await cb.answer()
        text, markup = mission(int(cb.data.split(":")[2]))
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("st:s:"))
    async def st_step(cb: CallbackQuery):
        before_lvl = game.stats().level.level
        before = game._achieved(ui.today())
        try:
            m = st.toggle_step(int(cb.data.split(":")[2]), ui.today())
        except StoryError as e:
            return await cb.answer(f"⛔ {e}", show_alert=True)
        s = next(x for x in m["steps"] if x["id"] == int(cb.data.split(":")[2]))
        await cb.answer(f"▸ Этап пройден · +{s['xp']} XP" if s["done_day"] else "Отменено")
        text, markup = mission(m["id"])
        await edit(cb, text, markup)
        new = [a for a in game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]
        await celebrate(cb.message, {"level_before": before_lvl, "level_after": game.stats().level.level,
                                     "new_achievements": new})

    @router.callback_query(F.data.startswith("st:p:"))
    async def st_pause(cb: CallbackQuery):
        mid = int(cb.data.split(":")[2])
        m = st.get(mid)
        st.set_paused(mid, m["status"] != "paused")
        await cb.answer("⏸ Отложено — провалить нельзя, вернёшься когда будешь готов" if m["status"] != "paused" else "▶️ Продолжаем")
        text, markup = mission(mid)
        await edit(cb, text, markup)

    @router.callback_query(F.data.startswith("st:fin:"))
    async def st_finish(cb: CallbackQuery, state: FSMContext):
        mid = int(cb.data.split(":")[2])
        await state.set_state(Outro.text)
        await state.update_data(mid=mid)
        await cb.answer()
        await cb.message.answer("🏁 Финал! Напиши фразу-итог — как в конце миссии. Она будет в катсцене и хронике.\n"
                                "Например: <i>Сложил полномочия. Теперь — сессия без хвостов</i>",
                                reply_markup=kb([Btn(text="Без фразы", callback_data="st:fin0")]))

    async def finish(target: Message, state: FSMContext, outro: str):
        data = await state.get_data()
        await state.clear()
        before_lvl = game.stats().level.level
        before = game._achieved(ui.today())
        try:
            m = st.complete(data["mid"], ui.today(), outro)
        except (StoryError, KeyError) as e:
            return await target.answer(f"⛔ {escape(str(e))}")
        await target.answer(cutscene_text(m))
        new = [a for a in game.full_stats(ui.today())["achievements"] if a["done"] and a["key"] not in before]
        await celebrate(target, {"level_before": before_lvl, "level_after": game.stats().level.level,
                                 "new_achievements": new})

    @router.message(Outro.text, F.text)
    async def st_outro(msg: Message, state: FSMContext):
        await finish(msg, state, msg.text.strip())

    @router.callback_query(F.data == "st:fin0")
    async def st_outro_skip(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await finish(cb.message, state, "")

    # ---------- новая миссия ----------

    @router.callback_query(F.data == "st:new")
    async def st_new(cb: CallbackQuery, state: FSMContext):
        await state.set_state(NewMission.title)
        await cb.answer()
        await cb.message.answer("🎬 <b>Новая миссия</b>\nКак называется? Например: <i>Сложить полномочия старосты</i>")

    @router.message(NewMission.title, F.text)
    async def st_new_title(msg: Message, state: FSMContext):
        await state.update_data(title=msg.text.strip()[:120])
        await state.set_state(NewMission.steps)
        await msg.answer("Этапы — каждый с новой строки (по 100 XP). Или «-», если без этапов.\n"
                         "<i>Встреча с куратором\nРазговор с группой\nДеканат</i>")

    @router.message(NewMission.steps, F.text)
    async def st_new_steps(msg: Message, state: FSMContext):
        steps = [] if msg.text.strip() in ("-", "—", "нет") else \
            [re.sub(r"^\s*[-•\d.)]+\s*", "", s).strip() for s in msg.text.split("\n") if s.strip()]
        await state.update_data(steps=steps[:20])
        await state.set_state(None)
        await msg.answer("Сколько XP за финал?", reply_markup=kb(
            [Btn(text=f"{x}", callback_data=f"st:xp:{x}") for x in (500, 1000, 2000, 3000)]))

    @router.callback_query(F.data.startswith("st:xp:"))
    async def st_new_xp(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        if "title" not in data:
            return await cb.answer("Начни заново: /story → ＋ Миссия", show_alert=True)
        m = st.add(data["title"], ui.today(), int(cb.data.split(":")[2]), steps=data.get("steps") or [])
        await cb.answer("🎬 Миссия началась")
        text, markup = mission(m["id"])
        await edit(cb, "🎬 <b>Новая миссия!</b>\n\n" + text, markup)

    # ---------- хроника ----------

    @router.callback_query(F.data == "st:chr")
    async def st_chronicle(cb: CallbackQuery):
        lines = ["📖 <b>Хроника</b>"]
        for ch in st.chronicle(ui.today())[:4]:
            lines.append(f"\n<b>{escape(ch['title'])}</b>")
            if not ch["missions"]:
                lines.append("<i>пока пусто</i>")
            for m in ch["missions"][:10]:
                d = m["done_day"]
                lines.append(f"{d[8:10]}.{d[5:7]} {escape(m['emoji'])} {escape(m['title'])}"
                             + (f"\n   <i>«{escape(m['outro'])}»</i>" if m["outro"] else ""))
        await cb.answer()
        await edit(cb, "\n".join(lines), kb([Btn(text="⬅️ Сюжет", callback_data="st:home")]))
