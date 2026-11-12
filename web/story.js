/* 🎬 Сюжетные миссии: экран в админке, полоска на «Сегодня», хроника в статах, катсцена «миссия пройдена». */

// ---------- полоска активной миссии на «Сегодня» (как задание в GTA) ----------
function storyStripHtml(s) {
  if (!s || !s.active.length) return "";
  return s.active.slice(0, 2).map(m => `<div class="story-strip" data-act="toStory">
      <span class="story-ico">${esc(m.emoji)}</span>
      <div class="story-body"><div class="story-label">Сюжет · ${m.steps_total ? `этап ${Math.min(m.steps_done + 1, m.steps_total)}/${m.steps_total}` : "миссия"}</div>
        <div class="story-title">${esc(m.title)}</div>
        ${m.next_step ? `<div class="small muted">▸ ${esc(m.next_step.title)}</div>` : m.steps_total ? `<div class="small" style="color:var(--good)">Все этапы пройдены — пора финал 🏁</div>` : ""}</div>
      <span class="story-xp">${fmt(m.xp)}</span></div>`).join("");
}
actions.toStory = () => { state.adminTab = "story"; return go("admin"); };

// ---------- экран «🎬 Сюжет» в админке ----------
async function renderStory() {
  const s = await api("GET", "/story");
  const f = state.storyForm || { xp: 1000 };
  let html = adminTabs() + `
    <div class="story-chapter">
      <div><div class="stat-label">Сейчас идёт</div><div class="story-chapter-title">${esc(s.chapter.title)}</div>
        <div class="small muted">с ${ddmm(s.chapter.started)} · 😮‍💨 респект ${s.respect}</div></div>
      <button class="btn btn-sm" data-act="chapterNew">Новая глава</button></div>
    <p class="muted small">Важные события жизни. Этапы дают немного XP сразу, финал — катсцену и большой куш. Провалить нельзя — только отложить.</p>`;
  html += s.active.map(missionCard).join("") || `<div class="empty small">Активных миссий нет. Что сейчас по-настоящему важно?</div>`;
  if (s.paused.length) html += `<div class="h2">⏸ Отложено</div>` + s.paused.map(missionCard).join("");
  html += `<div class="h2">＋ Новая миссия</div>
    <form class="card" data-submit="storyAdd">
      <label class="field"><span>Название</span><input class="input" name="title" maxlength="120" placeholder="Сложить полномочия старосты" required></label>
      <label class="field"><span>Зачем это тебе (будет в хронике)</span><input class="input" name="why" maxlength="300" placeholder="Закрыть семестр без хвостов"></label>
      <label class="field"><span>Этапы — каждый с новой строки, по 100 XP (можно без этапов)</span>
        <textarea class="input" name="steps" rows="3" placeholder="Встреча с куратором&#10;Разговор с группой&#10;Деканат"></textarea></label>
      <div class="field"><span>XP за финал</span><div class="chips">${[500, 1000, 2000, 3000].map(x =>
        `<button type="button" class="chip ${f.xp === x ? "on" : ""}" data-act="storyXp" data-x="${x}">${fmt(x)}</button>`).join("")}</div></div>
      <button class="btn btn-accent wide" type="submit">🎬 Начать миссию</button></form>`;
  view.innerHTML = html;
}
function missionCard(m) {
  const open = state.storyOpen === m.id;
  const fin = state.storyFinish === m.id;
  const pct = m.steps_total ? Math.round(100 * m.steps_done / m.steps_total) : 0;
  return `<div class="card mission ${m.status}">
    <div class="row"><span style="font-size:24px">${esc(m.emoji)}</span>
      <div class="q-body"><div class="q-title">${esc(m.title)}</div>${m.why ? `<div class="small muted">${esc(m.why)}</div>` : ""}</div>
      <span class="story-xp">${fmt(m.xp)}</span>
      <button class="btn btn-sm btn-ghost" data-act="storyDel" data-id="${m.id}" aria-label="Удалить миссию">✕</button></div>
    ${m.steps_total ? `<div class="dayprog-bar" style="margin:10px 0 4px"><div class="dayprog-fill" style="width:${pct}%"></div></div>` : ""}
    ${m.steps.map(s => `<div class="step ${s.done_day ? "done" : ""}">
      <button class="step-check" data-act="stepToggle" data-id="${s.id}" aria-label="${s.done_day ? "Отменить этап" : "Этап пройден"}">${s.done_day ? "✓" : ""}</button>
      <span class="step-title">${esc(s.title)}</span><span class="muted small">${s.xp ? `+${s.xp}` : ""}</span>
      ${open && !s.done_day ? `<button class="btn btn-sm btn-ghost" data-act="stepDel" data-id="${s.id}" aria-label="Удалить этап">✕</button>` : ""}</div>`).join("")}
    ${open ? `<form class="row" data-submit="stepAdd" data-id="${m.id}" style="margin-top:8px">
      <input class="input" name="title" maxlength="120" placeholder="Ещё этап" required style="flex:2">
      <input class="input" name="xp" type="number" min="0" max="5000" value="100" style="flex:0 0 80px">
      <button class="btn" type="submit">＋</button></form>` : ""}
    ${fin ? `<form data-submit="storyComplete" data-id="${m.id}" style="margin-top:10px">
      <label class="field"><span>Фраза-итог — как в конце миссии (можно пусто)</span>
        <input class="input" name="outro" maxlength="200" placeholder="Сложил полномочия. Теперь — сессия без хвостов"></label>
      <button class="btn btn-accent wide" type="submit">🏁 Миссия пройдена</button></form>` : ""}
    <div class="row wrap" style="gap:6px;margin-top:10px">
      ${fin ? "" : `<button class="btn btn-sm btn-accent" data-act="storyFinish" data-id="${m.id}">🏁 Финал</button>`}
      <button class="btn btn-sm" data-act="storyOpen" data-id="${m.id}">${open ? "Готово" : "✏️ Этапы"}</button>
      <button class="btn btn-sm" data-act="storyPause" data-id="${m.id}" data-p="${m.status === "paused" ? 0 : 1}">${m.status === "paused" ? "▶️ Продолжить" : "⏸ Отложить"}</button>
</div></div>`;
}
const reStory = () => renderStory();
actions.storyXp = el => { state.storyForm = { xp: Number(el.dataset.x) }; document.querySelectorAll("[data-act=storyXp]").forEach(b => b.classList.toggle("on", b === el)); };
actions.storyAdd = async form => {
  const steps = form.steps.value.split("\n").map(s => s.trim()).filter(Boolean);
  const m = await api("POST", "/story", { title: form.title.value, why: form.why.value, xp: (state.storyForm || { xp: 1000 }).xp, steps });
  toast(`🎬 Новая миссия: ${esc(m.title)}`);
  state.storyForm = null;
  await reStory();
};
actions.storyOpen = el => { const id = Number(el.dataset.id); state.storyOpen = state.storyOpen === id ? null : id; return reStory(); };
actions.storyFinish = el => { state.storyFinish = Number(el.dataset.id); return reStory(); };
actions.stepToggle = async el => {
  const r = await api("POST", `/story/steps/${el.dataset.id}/toggle`);
  const s = r.steps.find(x => x.id === Number(el.dataset.id));
  if (s && s.done_day) toast(`▸ Этап пройден: ${esc(s.title)}${s.xp ? ` · +${s.xp} XP` : ""}`);
  celebrate(r);
  await reStory();
};
actions.stepAdd = async form => { await api("POST", `/story/${form.dataset.id}/steps`, { title: form.title.value, xp: Number(form.xp.value) || 0 }); await reStory(); };
actions.stepDel = async el => { await api("DELETE", `/story/steps/${el.dataset.id}`); await reStory(); };
actions.storyPause = async el => { await api("POST", `/story/${el.dataset.id}/pause`, { paused: el.dataset.p === "1" }); await reStory(); };
actions.storyDel = async el => {
  if (!confirm("Удалить миссию? XP за уже пройденные этапы останется.")) return;
  await api("DELETE", "/story/" + el.dataset.id); await reStory();
};
actions.storyComplete = async form => {
  const r = await api("POST", `/story/${form.dataset.id}/complete`, { outro: form.outro.value });
  state.storyFinish = null;
  await cutscene(r);
  celebrate({ ...r, level_before: r.level_after });             // новый уровень покажет сама катсцена
  await reStory();
};
actions.chapterNew = async () => {
  const t = prompt("Название новой главы — текущая закроется и уйдёт в хронику:", "Глава 2: ");
  if (!t || !t.trim()) return;
  await api("POST", "/story/chapter", { title: t });
  toast(`📖 ${esc(t)}`);
  await reStory();
};

// ---------- 🎬 катсцена ----------
function cutscene(r) {
  return new Promise(resolve => {
    const el = $("#cutscene");
    $("#cut-passed").textContent = r.label || "Миссия пройдена";
    $("#cut-title").textContent = r.title;
    $("#cut-outro").textContent = r.outroRaw || (r.outro ? `«${r.outro}»` : "");
    $("#cut-outro").classList.toggle("list", !!r.outroRaw);
    $("#cut-reward").textContent = r.reward || `+${fmt(r.xp)} XP  ·  😮‍💨 Респект +1${r.level_after > r.level_before ? `  ·  Уровень ${r.level_after}` : ""}`;
    $("#cut-chapter").textContent = r.chapter || "";
    el.hidden = false;
    el.classList.remove("play"); void el.offsetWidth; el.classList.add("play");
    if (navigator.vibrate) navigator.vibrate([30, 80, 30, 80, 120]);
    let ready = false;
    setTimeout(() => { ready = true; }, 1800);
    const close = () => { if (!ready) return; el.hidden = true; el.removeEventListener("click", close); resolve(); };
    el.addEventListener("click", close);
    setTimeout(() => { ready = true; close(); }, 9000);
  });
}

// ---------- 📖 хроника в статах ----------
STATS.story = async () => {
  const c = await api("GET", "/story/chronicle");
  let html = `<div class="h1">Статистика</div>` + statsTabs() + `
    <div class="tiles" style="margin:10px 0">
      <div class="tile"><div class="stat-label">Респект</div><div class="stat-value">😮‍💨 ${c.respect}</div><div class="stat-sub">пройдено миссий</div></div>
      <div class="tile"><div class="stat-label">Глав</div><div class="stat-value">${c.chapters.length}</div><div class="stat-sub">в твоей истории</div></div></div>`;
  for (const ch of c.chapters) {
    html += `<div class="chronicle-chapter"><div class="chronicle-head"><b>${esc(ch.title)}</b>
        <span class="muted small">${ddmm(ch.started)}${ch.ended ? ` — ${ddmm(ch.ended)}` : " — сейчас"} · ${ch.missions.length} ${plural(ch.missions.length, "миссия", "миссии", "миссий")}</span></div>`;
    html += ch.missions.length ? ch.missions.map(m => `<div class="chronicle-item">
        <div class="chronicle-date">${ddmm(m.done_day)}</div>
        <div><div><b>${esc(m.emoji)} ${esc(m.title)}</b></div>
          ${m.outro ? `<div class="chronicle-outro">«${esc(m.outro)}»</div>` : ""}
          ${m.why ? `<div class="small muted">${esc(m.why)}</div>` : ""}
          <div class="small muted">+${fmt(m.xp + m.xp_steps)} XP${m.steps_total ? ` · ${m.steps_total} ${plural(m.steps_total, "этап", "этапа", "этапов")}` : ""}</div></div></div>`).join("")
      : `<div class="small muted" style="padding:8px 0">${ch.current ? "Пока ни одной пройденной миссии — всё впереди." : "Пусто"}</div>`;
    html += `</div>`;
  }
  view.innerHTML = html;
};

// ---------- 📰 брифинг недели и 🏁 «неделя пройдена» ----------
const MARKC = { double: "🟢", ok: "🟢", progress: "🟡", late: "🔴" };
const WDN = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const wdOf = iso => WDN[parseDay(iso).getDay()];
const seen = k => { try { return localStorage.getItem(k) === "1"; } catch (e) { return false; } };
const markSeen = k => { try { localStorage.setItem(k, "1"); } catch (e) { /* ничего */ } };

function briefHtml(b, full) {
  const L = [];
  if (b.pair_days.length) L.push(`📚 Пар: <b>${b.pairs_total}</b> · ${b.pair_days.map(d => `${d.wd} ${d.first}`).join(" · ")}`);
  b.marks.forEach(m => L.push(`${m.emoji} <b>${esc(m.kind_title)}</b> — ${esc(m.subject)}, ${wdOf(m.day)} ${m.start}`));
  if (b.payments.length) L.push("📅 " + b.payments.map(p => `${MARKC[p.status] || "•"} ${esc(p.title)} ${rubR(p.amount)} (${wdOf(p.due)})`).join(" · "));
  b.funds.forEach(f => L.push(`🎁 ${esc(f.title)} через ${f.days_left} дн: ${MARKC[f.status]} ${rubR(f.balance)} из ${rubR(f.target)}`));
  if (b.bank.length) L.push("🗃 " + b.bank.map(t => `${"🔥".repeat(Math.max(0, t.heat - 1))}${esc(t.title)} (${wdOf(t.deadline)})`).join(" · ") + (b.bank_more ? ` и ещё ${b.bank_more}` : ""));
  if (b.promises_open) L.push(`💌 Открытых обещаний: ${b.promises_open}`);
  b.story.slice(0, 2).forEach(s => L.push(`🎬 ${esc(s.title)}${s.next ? ` ▸ ${esc(s.next)}` : ""}`));
  if (!L.length) L.push("Ничего срочного — отличная неделя, чтобы взять что-нибудь из банка 😉");
  return `<div class="card brief">
    <div class="row"><div><div class="story-label">Брифинг · неделя ${b.week}</div><div class="story-title">${b.span}</div></div>
      <span class="spacer"></span>${full ? "" : `<button class="btn btn-sm btn-ghost" data-act="briefHide" data-k="${b.week}" aria-label="Скрыть">✕</button>`}</div>
    <div class="small" style="margin:4px 0 8px;color:var(--accent);font-weight:700">${b.mood}</div>
    ${L.map(x => `<div class="brief-line small">${x}</div>`).join("")}</div>`;
}
function recapCardHtml(r) {
  return `<div class="card brief recap" data-act="recapShow">
    <div class="row"><span style="font-size:24px">🏁</span><div class="q-body"><div class="story-label">Неделя ${r.week}</div>
      <div class="story-title">Неделя пройдена</div><div class="small muted">${fmt(r.xp)} XP · ${esc(r.verdict)} — смотреть итоги</div></div>
      <button class="btn btn-sm btn-ghost" data-act="recapHide" data-k="${r.week}" aria-label="Скрыть">✕</button></div></div>`;
}
async function weekCardsHtml(day) {
  const d = parseDay(day), wd = d.getDay(), h = new Date().getHours();
  let html = "";
  if ((wd === 0 && h >= 18) || wd === 1) {                                   // воскресенье вечером / понедельник
    const r = await api("GET", "/week/recap" + (wd === 1 ? "?last=true" : "")).catch(() => null);
    if (r && r.xp && !seen("recap-" + r.week)) { state.recap = r; html += recapCardHtml(r); }
  }
  if (wd === 1 || wd === 2) {
    const b = await api("GET", "/week/brief").catch(() => null);
    if (b && !seen("brief-" + b.week)) html += briefHtml(b);
  }
  return html;
}
actions.briefHide = (el, e) => { e && e.stopPropagation(); markSeen("brief-" + el.dataset.k); return refresh(); };
actions.recapHide = (el, e) => { e && e.stopPropagation(); markSeen("recap-" + el.dataset.k); return refresh(); };
actions.recapShow = async el => {
  const r = state.recap || await api("GET", "/week/recap");
  await weekCutscene(r);
  markSeen("recap-" + r.week);
  await refresh();
};
actions.briefOpen = async () => { const b = await api("GET", "/week/brief"); toastHtmlCard(briefHtml(b, true)); };
actions.recapOpen = async () => { await weekCutscene(await api("GET", "/week/recap")); };
function toastHtmlCard(html) {
  const box = document.createElement("div");
  box.className = "brief-pop";
  box.innerHTML = html + `<button class="btn wide" style="margin-top:8px">Понял</button>`;
  box.addEventListener("click", e => { if (e.target.closest("button")) box.remove(); });
  view.prepend(box);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function weekCutscene(r) {
  const parts = [`✅ ${r.quests_done} квестов · ${r.active_days}/7 активных дней`];
  if (r.best_day) parts.push(`🏆 лучший день — ${r.best_day.wd}, ${fmt(r.best_day.xp)} XP`);
  if (r.limit_total) parts.push(`💰 в лимите ${r.limit_days} из ${r.limit_total} дн`);
  if (r.skills.length) parts.push("💪 " + r.skills.map(k => `${k.emoji} ${k.title} +${fmt(k.week_xp)}`).join(" · "));
  r.missions.forEach(m => parts.push(`${m.emoji} ${m.title}`));
  if (r.sleep && r.sleep.week_logged) parts.push(`🌙 отбой вовремя ${r.sleep.week_ontime}/${r.sleep.week_logged}, в среднем в ${r.sleep.avg}`);
  if (r.side_done) parts.push(`🎲 побочек: ${r.side_done}`);
  return cutscene({
    label: "Неделя пройдена", chapter: `Неделя ${r.week} · ${r.span}`, title: r.verdict + (r.delta != null ? ` (${r.delta > 0 ? "+" : ""}${r.delta}%)` : ""),
    outroRaw: parts.join("\n"), reward: `+${fmt(r.xp)} XP за неделю${r.rating_avg ? `  ·  ⭐ ${r.rating_avg}` : ""}`,
  });
}

// ---------- ⭐ розыск в банке ----------
function wantedHtml() {
  const w = state.stats && state.stats.wanted;
  if (!w || !w.stars) return "";
  return `<div class="banner bad"><b>🚨 Розыск ${"★".repeat(w.stars)}</b> — просроченные дедлайны. Закроешь — звёзды погаснут.
    ${w.items.slice(0, 5).map(i => `<div class="small">• ${esc(i.title)} — просрочено на ${i.late} ${plural(i.late, "день", "дня", "дней")}</div>`).join("")}</div>`;
}

// ---------- 🌙 иду спать ----------
async function sleepHtml(isToday) {
  if (!isToday) return "";
  const h = new Date().getHours();
  if (h >= 5 && h < 20) return "";
  const s = await api("GET", "/sleep").catch(() => null);
  if (!s) return "";
  if (s.logged_today) return `<div class="card sleep-card done small">🌙 Отбой записан · серия ${s.streak} · за неделю вовремя ${s.week_ontime}/${s.week_logged}${s.avg ? `, в среднем в ${s.avg}` : ""}</div>`;
  return `<button class="card sleep-card" data-act="sleepGo"><span style="font-size:26px">🌙</span>
    <span class="q-body"><b>Иду спать</b><span class="small muted" style="display:block">отбой в ${s.bedtime}${s.streak ? ` · серия ${s.streak}` : ""} — точка в конце дня</span></span></button>`;
}
actions.sleepGo = async () => {
  const r = await api("POST", "/sleep");
  toast(r.ontime ? `🌙 Отбой в ${r.at} — вовремя! +${r.xp} XP · серия ${r.streak}` : `🌙 Записал: ${r.at}. Отбой был в ${r.bedtime} — завтра получится`);
  celebrate(r);
  await refresh();
  const rate = document.querySelector("[data-act=rate]");
  if (rate) rate.scrollIntoView({ behavior: "smooth", block: "center" });
};

// ---------- 🎲 побочки ----------
function sideOfferHtml(sd) {
  const o = sd && sd.today;
  if (!o || o.status !== "offered") return "";
  return `<div class="card side-card"><div class="story-label">🎲 Побочка дня</div>
    <div class="story-title" style="margin:2px 0 4px">${esc(o.item.title)}</div>
    <div class="small muted">+${o.item.xp} XP, если сегодня. Без штрафа, если нет.</div>
    <div class="row" style="gap:8px;margin-top:10px"><button class="btn btn-accent" style="flex:1" data-act="sideAns" data-id="${o.id}" data-t="1">✅ Беру</button>
      <button class="btn" data-act="sideAns" data-id="${o.id}" data-t="0">⏭ Не сегодня</button></div></div>`;
}
actions.sideAns = async el => {
  await api("POST", `/side/offers/${el.dataset.id}`, { take: el.dataset.t === "1" });
  toast(el.dataset.t === "1" ? "🎲 В бонусных квестах на сегодня" : "Ок, в другой раз");
  await refresh();
};
async function renderSide() {
  const sd = await api("GET", "/side");
  let html = adminTabs() + `<p class="muted small" style="margin:4px 0 10px">Маленькие приятные дела, которые всё время откладываешь. Пару раз в неделю, в случайный момент между 12 и 19, бот предложит одно — взять или пропустить.</p>`;
  html += sideOfferHtml(sd);
  html += sd.pool.length ? `<div class="card">${sd.pool.map(it => `<div class="step"><span class="step-title">🎲 ${esc(it.title)}</span>
      <span class="muted small">${it.xp} XP${it.done ? ` · ×${it.done}` : ""}</span>
      <button class="btn btn-sm btn-ghost" data-act="sideDel" data-id="${it.id}" aria-label="Убрать">✕</button></div>`).join("")}</div>`
    : `<div class="empty small">Пул пуст. Позвонить бабушке, разобрать фото, прогулка без телефона…</div>`;
  html += `<form class="card row" data-submit="sideAdd" style="margin-top:10px;gap:8px">
      <input class="input" name="title" maxlength="120" placeholder="Новая побочка" required style="flex:2">
      <input class="input" name="xp" type="number" min="10" max="300" value="50" style="flex:0 0 80px">
      <button class="btn" type="submit">＋</button></form>
    ${sd.pool.length && !(sd.today) ? `<button class="btn wide" data-act="sideNow" style="margin-top:8px">🎲 Дай побочку сейчас</button>` : ""}`;
  view.innerHTML = html;
}
actions.sideAdd = async form => { await api("POST", "/side", { title: form.title.value, xp: Number(form.xp.value) || 50 }); await renderSide(); };
actions.sideDel = async el => { await api("DELETE", "/side/" + el.dataset.id); await renderSide(); };
actions.sideNow = async () => { await api("POST", "/side/offer"); await renderSide(); };

// ---------- 📊 статистика как в GTA ----------
STATS.fun = async () => {
  const groups = await api("GET", "/funstats");
  let shots = 0;
  try { shots = Number(localStorage.getItem("lg-shoot") || 0); } catch (e) { /* ничего */ }
  groups[1].items.push({ label: "Падающих звёзд пролетело при тебе", value: shots, sub: "на этом устройстве" });
  view.innerHTML = `<div class="h1">Статистика</div>` + statsTabs() + groups.map(g => `<div class="h2">${g.title}</div>
    <div class="card fun">${g.items.map(i => `<div class="fun-row"><span>${esc(i.label)}</span><span class="fun-dots"></span>
      <b>${typeof i.value === "number" ? fmt(i.value) : esc(String(i.value))}</b></div>${i.sub ? `<div class="fun-sub">${esc(String(i.sub))}</div>` : ""}`).join("")}</div>`).join("");
};
