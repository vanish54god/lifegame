"""📰 Брифинг недели и 🏁 «Неделя пройдена» — тексты для бота."""

from html import escape

from .finance import rub

MARK = {"double": "🟢", "ok": "🟢", "progress": "🟡", "late": "🔴", "": "•"}
HEAT = ["", "", "🔥", "🔥🔥", "🔥🔥🔥"]


def rr(k: int) -> str:
    return rub(k // 100 * 100).replace(",00", "")


def wd(day: str) -> str:
    from datetime import date
    return ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][date.fromisoformat(day).weekday()]


def brief_text(b: dict) -> str:
    L = [f"📰 <b>НЕДЕЛЯ {b['week']}</b> · {b['span']}", f"<i>{b['mood']}</i>", ""]
    if b["pair_days"]:
        L.append(f"📚 Пар: <b>{b['pairs_total']}</b> · " + " · ".join(f"{d['wd']} {d['first']}" for d in b["pair_days"]))
    for m in b["marks"]:
        L.append(f"{m['emoji']} <b>{escape(m['kind_title'])}</b> — {escape(m['subject'])}, {wd(m['day'])} {m['start']}")
    if b["payments"]:
        L.append("📅 Платежи: " + " · ".join(f"{MARK.get(p.get('status', ''), '•')} {escape(p['title'])} {rr(p['amount'])} ({wd(p['due'])})"
                                         for p in b["payments"]))
    for f in b["funds"]:
        L.append(f"🎁 {escape(f['title'])} через {f['days_left']} дн: {MARK[f['status']]} {rr(f['balance'])} из {rr(f['target'])}")
    if b["bank"]:
        L.append("🗃 Дедлайны: " + " · ".join(f"{HEAT[min(t['heat'], 4)]}{escape(t['title'])} ({wd(t['deadline'])})" for t in b["bank"])
                 + (f" и ещё {b['bank_more']}" if b["bank_more"] else ""))
    if b["promises_open"]:
        L.append(f"💌 Открытых обещаний: {b['promises_open']}")
    for s in b["story"][:2]:
        L.append(f"🎬 {escape(s['title'])}" + (f" ▸ {escape(s['next'])}" if s["next"] else ""))
    if len(L) == 3:
        L.append("Ничего срочного. Отличная неделя, чтобы взять что-нибудь из банка 😉")
    return "\n".join(L)


def recap_text(r: dict) -> str:
    bar = "<code>" + "▬" * 14 + "</code>"
    L = [bar, f"🏁 <b>НЕДЕЛЯ {r['week']} ПРОЙДЕНА</b>", f"<i>{r['span']}</i>", "",
         f"<b>+{r['xp']:,} XP</b>".replace(",", " ") + f" · {r['verdict']}" + (f" ({r['delta']:+d}%)" if r["delta"] is not None else ""),
         f"✅ Квестов: {r['quests_done']} · активных дней {r['active_days']}/7"
         + (f" · идеальных {r['perfect_days']}" if r["perfect_days"] else "")]
    if r["best_day"]:
        L.append(f"🏆 Лучший день: {r['best_day']['wd']} — {r['best_day']['xp']} XP")
    if r["limit_total"]:
        L.append(f"💰 В лимите: {r['limit_days']} из {r['limit_total']} дн")
    extra = []
    if r["marks_done"]:
        extra.append(f"✍️ сдано {r['marks_done']}")
    if r["steps"]:
        extra.append(f"🎬 этапов {r['steps']}")
    if r["promises_kept"]:
        extra.append(f"💌 обещаний {r['promises_kept']}")
    if r["bank_done"]:
        extra.append(f"🗃 из банка {r['bank_done']}")
    if extra:
        L.append(" · ".join(extra))
    for m in r["missions"]:
        L.append(f"{m['emoji']} Миссия пройдена: <b>{escape(m['title'])}</b>")
    if r["skills"]:
        L.append("💪 " + " · ".join(f"{k['emoji']} {k['title']} +{k['week_xp']}" for k in r["skills"]))
    if r["rating_avg"]:
        L.append(f"⭐ Средняя оценка дня: {r['rating_avg']}")
    L.append(bar)
    return "\n".join(L)
