/* LifeGame — банк заданий, таймер, привычки, оценка дня, неделя, календарь, сезоны. */
"use strict";

function fmtMin(m) {
  if (!m) return "0м";
  const h = Math.floor(m / 60), mm = Math.round(m % 60);
  return h && mm ? `${h}ч ${mm}м` : h ? `${h}ч` : `${mm}м`;
}
const leftLabel = d => d == null ? "без срока" : d < 0 ? `просрочено на ${-d} дн` : d === 0 ? "сегодня" : d === 1 ? "завтра" : `через ${d} дн`;
const TIME_PRESETS = [15, 30, 60, 90, 120, 180, 300, 480];
const DIFF = { 1: ["Лёгкая", "🟢"], 2: ["Средняя", "🟡"], 3: ["Сложная", "🟠"], 4: ["Босс", "💀"] };

// ---------- Таймер: тикает на экране без запросов к серверу ----------
setInterval(() => {
  document.querySelectorAll(".tmr[data-run='1']").forEach(el => {
    const sec = Number(el.dataset.base) + (Date.now() - Number(el.dataset.t0)) / 1000;
    el.textContent = "⏱ " + fmtMin(Math.max(1, Math.floor(sec / 60)));
  });
}, 10000);

function timerHtml(q) {
  if (!q.timer_running && !q.timer_sec) return "";
  return `<span class="tag tmr" data-run="${q.timer_running ? 1 : 0}" data-base="${q.timer_sec}" data-t0="${Date.now()}">${q.timer_running ? "⏱" : "⏸"} ${fmtMin(Math.max(1, Math.floor(q.timer_sec / 60)))}</span>`;
}
actions.timer = async el => {
  const q = await api("POST", `/quests/${el.dataset.id}/timer`, { action: el.dataset.a });
  toast(el.dataset.a === "start" ? "⏱ Таймер пошёл" : `⏸ Пауза · ${fmtMin(Math.max(1, Math.floor(q.timer_sec / 60)))}`);
  await refresh();
};
actions.pace = async el => {
  const r = await api("POST", `/quests/${el.dataset.id}/pace`, { pace: el.dataset.p });
  toast({ fast: "⚡ быстрее", ok: "👌 как думал", slow: "🐢 дольше" }[el.dataset.p] + " — записал");
  celebrate(r);
  await refresh();
};

// ---------- «Начать не позднее» ----------
function startByHtml(sb) {
  if (!sb) return "";
  if (!sb.remaining_min) {
    return sb.unknown ? `<div class="banner muted small">⏱ У ${sb.unknown} квестов нет оценки времени — не могу посчитать, когда начинать</div>` : "";
  }
  const extra = sb.unknown ? ` <span class="muted">(+${sb.unknown} без оценки)</span>` : "";
  const fix = sb.factor !== 1 ? `<div class="muted small">с поправкой на твой темп ×${sb.factor}</div>` : "";
  if (sb.too_late) return `<div class="banner bad">⏰ <b>До ${sb.bedtime} уже не успеть</b> — осталось ~${fmtMin(sb.remaining_min)}${extra}. Выбери главное.${fix}</div>`;
  if (sb.late) return `<div class="banner hot">⏰ <b>Пора садиться!</b> Осталось ~${fmtMin(sb.remaining_min)}${extra}${fix}</div>`;
  return `<div class="banner">⏰ Осталось ~${fmtMin(sb.remaining_min)}${extra}. Чтобы лечь в ${sb.bedtime}, начни не позже <b>${sb.start}</b>${fix}</div>`;
}
function loadHtml(ld) {
  const real = ld.real_min, cap = ld.capacity_min;
  return `<div class="load ${ld.over ? "over" : ""}">
    <div class="row small"><span>Нагрузка: <b>${fmtMin(real)}</b> из ${fmtMin(cap)}${ld.unknown ? ` <span class="muted">(+${ld.unknown} без оценки)</span>` : ""}</span>
      ${ld.factor !== 1 ? `<span class="spacer"></span><span class="muted">темп ×${ld.factor}</span>` : ""}</div>
    <div class="dayprog-bar"><div class="dayprog-fill" style="width:${Math.min(100, (100 * real) / cap)}%;background:${ld.over ? "var(--bad)" : "var(--ink-2)"}"></div></div>
    ${ld.busy && ld.busy.pairs ? `<div class="small muted" style="margin-top:4px">📚 День с парами ${ld.busy.first}–${ld.busy.last} + дорога ${fmtMin(ld.busy.commute_min)} — на квесты ${fmtMin(cap)}</div>` : ""}
    ${ld.over ? `<div class="small" style="color:var(--bad);margin-top:4px">⚠️ Перегруз — такой день не переживёт первую внеплановую задачу. Убери что-нибудь.</div>` : ""}</div>`;
}

// ---------- Привычки на экране «Сегодня» ----------
function habitsHtml(hs) {
  if (!hs || !hs.length) return "";
  return `<div class="h2">🔁 Привычки</div><div class="habits">` + hs.map(h => `
    <button class="habit ${h.done_today ? "on" : ""}" data-act="habit" data-id="${h.id}">
      <span class="habit-emoji">${h.emoji}</span>
      <span class="habit-body"><b>${esc(h.title)}</b>
        <span class="muted small">${h.per_week < 7 ? `${h.week_count}/${h.per_week} на неделе` : "каждый день"}${h.streak ? ` · 🔥${h.streak} ${h.unit}` : ""}</span></span>
      <span class="habit-check">${h.done_today ? "✓" : ""}</span>
    </button>`).join("") + `</div>`;
}
actions.habit = async el => {
  el.disabled = true;
  const r = await api("POST", `/habits/${el.dataset.id}/toggle`, {});
  if (r.done) toast(`${r.habit.emoji} +${r.habit.xp} XP${r.habit.streak ? ` · 🔥${r.habit.streak} ${r.habit.unit}` : ""}`);
  celebrate(r);
  await refresh();
};

// ---------- Оценка дня ----------
function ratingHtml(day, score) {
  return `<div class="h2">⭐ Как прошёл день?</div><div class="rating">` +
    Array.from({ length: 10 }, (_, i) => i + 1).map(n =>
      `<button class="rate ${score === n ? "on" : ""}" data-act="rate" data-day="${day}" data-n="${n}" aria-label="${n} из 10">${n}</button>`).join("") + `</div>`;
}
actions.rate = async el => {
  const r = await api("PUT", "/rating", { day: el.dataset.day, score: Number(el.dataset.n) });
  toast(`⭐ ${r.score}/10`);
  celebrate(r);
  await refresh();
};

// ================= Банк заданий (вкладка в «Админе») =================

state.bankForm = { cat: "study", diff: 2, est: 60, dl: 7, title: "" };
state.bankOpen = null;      // открытая карточка задачи
state.bankSched = null;     // задача, которую сейчас кладём в день

async function renderBank() {
  const t = state.meta.today;
  const day = state.adminDay || addDays(t, 1);
  const [b, pl] = await Promise.all([api("GET", "/bank"), api("GET", "/plan/day/" + day)]);
  const f = state.bankForm;
  const total = b.tasks.reduce((s, x) => s + x.rem_min, 0);
  let html = adminTabs() + `<p class="muted small" style="margin:4px 0 10px">Все дела, пока они не сделаны. 🔥 — насколько горит: учитывает и дедлайн, и сколько работы осталось.</p>
    <div class="row small" style="margin-bottom:6px"><span>Кладём в: <b>${esc(dayName(day))}, ${ddmm(day)}</b></span><span class="spacer"></span>
      <span class="muted">в банке ~${fmtMin(total)}</span></div>${loadHtml(pl.load)}`;

  html += b.tasks.length ? b.tasks.map(x => bankCard(x, day)).join("") : `<div class="empty" style="margin-top:10px">Банк пуст 📦</div>`;

  html += `<form class="card" data-submit="bankAdd" style="margin-top:16px"><div class="h3">＋ Новая задача</div>
    <input class="input" name="title" maxlength="200" placeholder="Что надо сделать" value="${esc(f.title)}" data-input="bTitle" required>
    <div class="chips" style="margin:10px 0">${state.meta.categories.filter(c => c.pickable).map(c =>
      `<button type="button" class="chip ${f.cat === c.key ? "on" : ""}" data-act="bSet" data-k="cat" data-v="${c.key}">${c.emoji} ${esc(c.title)}</button>`).join("")}</div>
    <div class="h3">Сложность</div><div class="chips">${Object.entries(DIFF).map(([k, [n, e]]) =>
      `<button type="button" class="chip ${f.diff == k ? "on" : ""}" data-act="bSet" data-k="diff" data-v="${k}">${e} ${n}</button>`).join("")}</div>
    <div class="h3" style="margin-top:10px">Примерно времени</div><div class="chips">${TIME_PRESETS.map(m =>
      `<button type="button" class="chip ${f.est == m ? "on" : ""}" data-act="bSet" data-k="est" data-v="${m}">${fmtMin(m)}</button>`).join("")}
      <button type="button" class="chip ${f.est == 0 ? "on" : ""}" data-act="bSet" data-k="est" data-v="0">не знаю</button></div>
    <div class="h3" style="margin-top:10px">Дедлайн</div><div class="chips">${[[0, "Сегодня"], [1, "Завтра"], [3, "3 дня"], [7, "Неделя"], [14, "2 недели"], [30, "Месяц"], ["none", "Без срока"]].map(([v, l]) =>
      `<button type="button" class="chip ${String(f.dl) === String(v) ? "on" : ""}" data-act="bSet" data-k="dl" data-v="${v}">${l}</button>`).join("")}
      <input type="date" class="chip" data-input="bDate" min="${t}" value="${/^\d{4}/.test(String(f.dl)) ? f.dl : ""}" aria-label="Дата"></div>
    <button class="btn btn-accent wide" type="submit" style="margin-top:14px">В банк</button></form>`;

  if (b.done.length) {
    html += `<details class="card" style="margin-top:12px"><summary>✅ Сделано недавно (${b.done.length})</summary><ul class="list-plain">` +
      b.done.map(x => `<li><span>${x.diff_emoji}</span><div class="q-body">${esc(x.title)}<div class="muted small">${ddmm(x.done_day)}${x.deadline ? ` · дедлайн ${ddmm(x.deadline)}` : ""}</div></div></li>`).join("") + `</ul></details>`;
  }
  view.innerHTML = html;
}

function bankCard(x, day) {
  const open = state.bankOpen === x.id;
  const parts = x.children.length ? ` · части ${x.progress}%` : "";
  const est = x.rem_min ? ` · ~${fmtMin(x.rem_min)}` : "";
  let html = `<div class="quest bank heat${x.heat}" data-act="bOpen" data-id="${x.id}">
    <div class="heat-badge" title="${esc(x.heat_name)}">${x.heat_emoji}</div>
    <div class="q-body"><div class="q-title">${esc(x.title)}</div>
      <div class="q-meta"><span class="tag">${x.cat_emoji} ${x.diff_emoji} ${esc(leftLabel(x.days_left))}${est}${parts}</span>
      ${x.planned ? `<span class="tag" style="color:var(--accent)">📅 ${ddmm(x.planned.day)}</span>` : ""}</div></div>
    <div class="q-actions">${!x.planned && !x.children.some(c => c.status === "open")
      ? `<button class="btn btn-sm btn-accent" data-act="bSched" data-id="${x.id}">В ${esc(dayName(day).toLowerCase())}</button>` : ""}</div></div>`;
  if (state.bankSched === x.id) html += schedForm(x, day);
  if (open) {
    html += `<div class="card bank-open">
      <div class="small muted">${x.cat_emoji} ${esc(x.cat_title)} · ${x.diff_emoji} ${x.diff_name}${x.est_min ? ` · оценка ${fmtMin(x.est_min)}` : ""} · ${esc(x.heat_name)} · в банке ${x.age} дн</div>`;
    if (x.children.length) {
      html += `<div class="h3" style="margin-top:10px">Части · ${x.progress}%</div>
        <div class="dayprog-bar" style="margin-bottom:8px"><div class="dayprog-fill" style="width:${x.progress}%;background:var(--good)"></div></div>` +
        x.children.map(c => `<div class="row small sub ${c.status}">
          <span>${c.status === "done" ? "✅" : c.planned ? "📅" : "▫️"}</span><span class="q-body">${esc(c.title)} <span class="muted">${c.diff_emoji}${c.est_min ? " · " + fmtMin(c.est_min) : ""}</span></span>
          ${c.status === "open" && !c.planned ? `<button class="btn btn-sm" data-act="bSched" data-id="${c.id}">В ${esc(dayName(day).toLowerCase())}</button>` : ""}
          ${c.status === "open" ? `<button class="btn btn-sm btn-ghost" data-act="bDel" data-id="${c.id}" aria-label="Удалить часть">✕</button>` : ""}</div>
          ${state.bankSched === c.id ? schedForm(c, day) : ""}`).join("");
    }
    html += `<form class="row wrap" data-submit="bankSub" data-id="${x.id}" style="margin-top:10px">
        <input class="input" name="title" maxlength="200" placeholder="＋ Часть задачи" required style="flex:2;min-width:150px">
        <select class="input" name="est" style="flex:1;min-width:90px">${TIME_PRESETS.map(m => `<option value="${m}" ${m === 60 ? "selected" : ""}>${fmtMin(m)}</option>`).join("")}</select>
        <button class="btn" type="submit">＋</button></form>
      <div class="row wrap" style="margin-top:10px">
        <label class="small muted">Дедлайн <input type="date" class="input" style="width:auto;display:inline-block" data-input="bDeadline" data-id="${x.id}" value="${x.deadline || ""}"></label>
        <span class="spacer"></span>
        ${!x.children.some(c => c.status === "open") && !x.planned ? `<button class="btn btn-sm btn-good" data-act="bDone" data-id="${x.id}">✓ Уже сделал</button>` : ""}
        <button class="btn btn-sm btn-bad" data-act="bDel" data-id="${x.id}">Удалить</button></div></div>`;
  }
  return html;
}

function schedForm(x, day) {
  const base = x.suggested_xp;
  const opts = [...new Set([0.6, 1, 1.4, 2].map(k => Math.max(10, Math.round((base * k) / 10) * 10)))];
  const early = x.deadline && (parseDay(x.deadline) - parseDay(day)) / 86400000 >= 3;
  return `<div class="card sched"><div class="small">💰 Сколько XP? Обычно ~${base} (${x.cat_emoji} ${x.diff_emoji})${early ? ` · <b style="color:var(--good)">+20% заранее ⏳</b>` : ""}</div>
    <div class="chips" style="margin-top:8px">${opts.map(v => `<button class="chip" data-act="bSchedGo" data-id="${x.id}" data-xp="${v}">${v} XP</button>`).join("")}
      <button class="chip" data-act="bSched" data-id="${x.id}">Отмена</button></div></div>`;
}

function adminTabs() {
  const tab = state.adminTab || "plan";
  return `<div class="h1">Режим админа</div><div class="chips" style="margin:10px 0 6px">
    <button class="chip ${tab === "plan" ? "on" : ""}" data-act="adminTab" data-t="plan">📋 План дня</button>
    <button class="chip ${tab === "bank" ? "on" : ""}" data-act="adminTab" data-t="bank">🗃 Банк заданий</button></div>`;
}
actions.adminTab = el => { state.adminTab = el.dataset.t; return renderAdmin(); };
actions.bOpen = el => { const id = Number(el.dataset.id); state.bankOpen = state.bankOpen === id ? null : id; return renderBank(); };
actions.bSched = el => { const id = Number(el.dataset.id); state.bankSched = state.bankSched === id ? null : id; return renderBank(); };
actions.bSchedGo = async el => {
  const day = state.adminDay || addDays(state.meta.today, 1);
  const r = await api("POST", `/bank/${el.dataset.id}/schedule`, { day, xp: Number(el.dataset.xp) });
  state.bankSched = null;
  toast(`📅 ${esc(r.quest.title)} → ${ddmm(day)} · ${r.quest.xp} XP${r.bonus ? " (заранее ⏳)" : ""}${r.load.over ? " · ⚠️ перегруз" : ""}`);
  await renderBank();
};
actions.bDone = async el => {
  if (!confirm("Задача уже сделана? Запишу на сегодня.")) return;
  const r = await api("POST", `/bank/${el.dataset.id}/done`, {});
  splash("Задание выполнено", `+${r.quest.xp} XP`);
  celebrate(r);
  state.bankOpen = null;
  await renderBank();
};
actions.bDel = async el => {
  if (!confirm("Удалить задачу?")) return;
  await api("DELETE", "/bank/" + el.dataset.id);
  await renderBank();
};
actions.bSet = el => {
  const f = state.bankForm, k = el.dataset.k, v = el.dataset.v;
  f[k] = k === "dl" ? v : Number(v) || (k === "cat" ? v : 0);
  if (k === "cat") f.cat = v;
  return renderBank();
};
actions.bTitle = el => { state.bankForm.title = el.value; };
actions.bDate = el => { if (el.value) { state.bankForm.dl = el.value; renderBank().catch(toastErr); } };
actions.bDeadline = async el => {
  await api("PATCH", "/bank/" + el.dataset.id, el.value ? { deadline: el.value } : { clear_deadline: true });
  await renderBank();
};
actions.bankAdd = async () => {
  const f = state.bankForm, t = state.meta.today;
  const deadline = f.dl === "none" ? null : /^\d{4}/.test(String(f.dl)) ? f.dl : addDays(t, Number(f.dl));
  const r = await api("POST", "/bank", { title: f.title, category: f.cat, difficulty: f.diff, est_min: f.est || null, deadline });
  toast(`🗃 ${r.heat_emoji} ${esc(r.title)} — в банке`);
  celebrate(r);
  f.title = "";
  await renderBank();
};
actions.bankSub = async form => {
  const parent = Number(form.dataset.id);
  const p = (await api("GET", "/bank")).tasks.find(x => x.id === parent);
  const r = await api("POST", "/bank", { title: form.title.value, category: p.category, difficulty: 2,
                                         est_min: Number(form.est.value), parent_id: parent });
  celebrate(r);
  await renderBank();
};

// ================= Статы: неделя, календарь, сезоны =================

function statsTabs() {
  const tab = state.statsTab || "main";
  return `<div class="chips" style="margin:10px 0 4px">${[["main", "Обзор"], ["week", "Неделя"], ["cal", "Календарь"], ["season", "Сезоны"]].map(([k, l]) =>
    `<button class="chip ${tab === k ? "on" : ""}" data-act="statsTab" data-t="${k}">${l}</button>`).join("")}</div>`;
}
actions.statsTab = el => { state.statsTab = el.dataset.t; return renderStats(); };

function cmp(a, b, money = false) {
  const show = v => money ? rub(v) : fmt(v);
  if (b == null || a === b) return `<span class="muted small">${b == null ? "" : "как на прошлой"}</span>`;
  const up = a > b;
  return `<span class="small" style="color:${up ? "var(--good)" : "var(--muted)"}">${up ? "▲" : "▼"} ${show(Math.abs(a - b))}</span>`;
}

const STATS = {};
STATS.week = async () => {
  const r = await api("GET", "/review");
  const a = r.this, b = r.last, rt = r.rating;
  const tile = (label, val, sub) => `<div class="tile"><div class="stat-label">${label}</div><div class="stat-value">${val}</div><div class="stat-sub">${sub}</div></div>`;
  let html = `<div class="h1">Статистика</div>` + statsTabs() + `<div class="muted small" style="margin-bottom:8px">Неделя с ${ddmm(r.week_start)} · сравнение с прошлой</div>
    <div class="tiles">
      ${tile("XP", fmt(a.xp), cmp(a.xp, b.xp))}
      ${tile("Квестов", `${a.quests_done}<span class="muted" style="font-size:16px">/${a.quests_total}</span>`, cmp(a.quests_done, b.quests_done))}
      ${tile("Из банка", a.bank_done, cmp(a.bank_done, b.bank_done))}
      ${tile("Обещания", a.promises_kept, cmp(a.promises_kept, b.promises_kept))}
      ${tile("Привычки", a.habit_checks, cmp(a.habit_checks, b.habit_checks))}
      ${tile("Оценка дня", a.rating_avg ?? "—", a.rated_days ? `${a.rated_days} дн оценено` : "оцени день на главном")}
      ${tile("Смены", rub(a.shifts_sum), `${a.shifts} шт. ${b.shifts_sum ? "· " : ""}${cmp(a.shifts_sum, b.shifts_sum, true)}`)}
      ${tile("Траты", rub(a.expense), cmp(b.expense, a.expense, true).replace("▲", "↓").replace("▼", "↑"))}
    </div>`;
  if (rt.count >= 3) {
    html += `<div class="h2">⭐ Оценки за 30 дней</div><div class="card small">
      Средняя: <b>${rt.avg}</b>/10 · оценено ${rt.count} дн.<br>
      ${rt.n_good && rt.n_bad ? `В хорошие дни (7+) ты набирал в среднем <b>${fmt(rt.xp_good)} XP</b>, в тяжёлые (≤4) — <b>${fmt(rt.xp_bad)} XP</b>.` :
        "Когда наберётся больше оценок, покажу, как настроение связано с продуктивностью."}</div>`;
  }
  view.innerHTML = html;
};

STATS.cal = async () => {
  const t = state.meta.today;
  const month = state.calMonth || t.slice(0, 7);
  const c = await api("GET", "/calendar?month=" + month);
  const [y, m] = month.split("-").map(Number);
  const first = new Date(y, m - 1, 1), daysIn = new Date(y, m, 0).getDate();
  const shift = (first.getDay() + 6) % 7;
  const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  const prevM = isoDay(new Date(y, m - 2, 1)).slice(0, 7), nextM = isoDay(new Date(y, m, 1)).slice(0, 7);
  let cells = "";
  for (let i = 0; i < shift; i++) cells += `<div class="cal-cell out"></div>`;
  for (let d = 1; d <= daysIn; d++) {
    const iso = `${month}-${String(d).padStart(2, "0")}`, x = c.days[iso] || {};
    const maxHeat = (x.deadlines || []).reduce((h, z) => Math.max(h, z.heat), -1);
    const icons = [
      maxHeat >= 0 ? ["❄️", "🌤", "🔥", "🔥", "🔥"][maxHeat] : "",
      (x.shifts || []).length ? "💼" : "", (x.plans || []).length ? "📅" : "", (x.promises || []).length ? "💌" : "",
    ].join("");
    const dot = x.quests ? `<div class="cal-dots">${x.done}/${x.quests}</div>` : "";
    cells += `<button class="cal-cell ${iso === t ? "today" : ""} ${state.calDay === iso ? "sel" : ""} ${maxHeat >= 3 ? "hot" : ""}" data-act="calDay" data-day="${iso}">
      <span class="cal-num">${d}</span><span class="cal-icons">${icons}</span>${dot}${x.rating ? `<span class="cal-rate">${x.rating}</span>` : ""}</button>`;
  }
  let html = `<div class="h1">Статистика</div>` + statsTabs() + `<div class="row" style="margin:8px 0">
      <button class="btn btn-icon" data-act="calMonth" data-m="${prevM}" aria-label="Прошлый месяц">‹</button>
      <div class="h3" style="margin:0;flex:1;text-align:center;font-size:16px">${MONTHS[m - 1]} ${y}</div>
      <button class="btn btn-icon" data-act="calMonth" data-m="${nextM}" aria-label="Следующий месяц">›</button></div>
    <div class="cal-head">${["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map(w => `<span>${w}</span>`).join("")}</div>
    <div class="cal">${cells}</div>
    <div class="legend" style="margin-top:8px">🔥 дедлайн · 💼 смена · 📅 платёж · 💌 обещание · 3/4 квесты · ⭐ оценка</div>`;
  if (state.calDay && state.calDay.startsWith(month)) {
    const x = c.days[state.calDay] || {};
    const items = [
      ...(x.deadlines || []).map(z => `${["❄️", "🌤", "🔥", "🔥🔥", "🔥🔥🔥"][z.heat]} Дедлайн: ${esc(z.parent ? z.parent + ": " : "")}${esc(z.title)}`),
      ...(x.shifts || []).map(z => `💼 ${esc(z.company)} · ${esc(z.work_type)} · ${rub(z.amount)} ${z.paid ? "✓" : "(ждём)"}`),
      ...(x.plans || []).map(z => `📅 ${esc(z.title)} · ${rub(z.amount)}`),
      ...(x.promises || []).map(z => `💌 ${esc(z)}`),
    ];
    if (x.quests) items.unshift(`🎮 Квесты: ${x.done}/${x.quests} · ${fmt(x.xp)} XP`);
    if (x.habits) items.push(`🔁 Привычки: ${x.habits}`);
    if (x.rating) items.push(`⭐ Оценка: ${x.rating}/10`);
    html += `<div class="h2">${WEEKDAYS[parseDay(state.calDay).getDay()]}, ${ddmm(state.calDay)}</div>` +
      (items.length ? `<ul class="list-plain card">${items.map(i => `<li>${i}</li>`).join("")}</ul>` : `<div class="empty small">Ничего</div>`);
  }
  view.innerHTML = html;
};
actions.calMonth = el => { state.calMonth = el.dataset.m; state.calDay = null; return renderStats(); };
actions.calDay = el => { state.calDay = state.calDay === el.dataset.day ? null : el.dataset.day; return renderStats(); };

STATS.season = async () => {
  const s = await api("GET", "/season" + (state.seasonMonth ? "?month=" + state.seasonMonth : ""));
  const cur = s.month === state.meta.today.slice(0, 7);
  const row = (icon, label, val) => val ? `<div class="season-row"><span>${icon}</span><span class="q-body">${label}</span><b>${val}</b></div>` : "";
  let html = `<div class="h1">Статистика</div>` + statsTabs() +
    `<div class="chips" style="margin:8px 0">${s.months.slice(0, 12).map(m => `<button class="chip ${m === s.month ? "on" : ""}" data-act="seasonM" data-m="${m}">${m.slice(5)}.${m.slice(2, 4)}</button>`).join("")}</div>
    <div class="season-card">
      <div class="season-title">${esc(s.title)}</div>${cur ? `<div class="muted small">сезон идёт — итоги придут в боте 1-го числа</div>` : ""}
      <div class="season-xp">${fmt(s.xp)} <span>XP</span></div>
      ${row("✅", "Квестов выполнено", s.quests_total ? `${s.quests_done}/${s.quests_total}${s.rate != null ? ` · ${s.rate}%` : ""}` : "")}
      ${row("📆", "Активных дней", s.active_days)}
      ${row("🔥", "Лучшая серия", s.best_streak ? s.best_streak + " дн" : "")}
      ${row("💯", "Идеальных дней", s.perfect_days)}
      ${row(s.top_category ? s.top_category.emoji : "🎯", "Главное направление", s.top_category ? s.top_category.title : "")}
      ${row("🗃", "Задач из банка", s.bank_done)}
      ${row("💀", "Побеждено боссов", s.bosses)}
      ${row("💌", "Сдержано обещаний", s.promises_kept)}
      ${row("🔁", "Отметок привычек", s.habit_checks)}
      ${row("💼", "Смен", s.shifts ? `${s.shifts} · ${rub(s.shifts_sum)}` : "")}
      ${row("💰", "Доходы / расходы", s.income || s.expense ? `${rub(s.income)} / ${rub(s.expense)}` : "")}
      ${row("⭐", "Средняя оценка дня", s.rating_avg ? s.rating_avg + "/10" : "")}
      ${s.achievements.length ? `<div class="season-ach">${s.achievements.map(a => `<span title="${esc(a.title)}">${a.emoji}</span>`).join("")}</div>` : ""}
    </div>`;
  view.innerHTML = html;
};
actions.seasonM = el => { state.seasonMonth = el.dataset.m; return renderStats(); };

// ================= Привычки в «Ещё» =================

async function habitsSettingsHtml() {
  const hs = await api("GET", "/habits");
  return `<div class="h2">🔁 Привычки</div>
    ${hs.length ? `<ul class="list-plain card">${hs.map(h => `<li><span style="font-size:20px">${h.emoji}</span>
      <div class="q-body"><b>${esc(h.title)}</b><div class="muted small">${esc(h.goal_label)} · +${h.xp} XP · рекорд ${h.best} ${h.unit}</div></div>
      <button class="btn btn-sm btn-ghost" data-act="habitDel" data-id="${h.id}" aria-label="Убрать">✕</button></li>`).join("")}</ul>` : ""}
    <form class="card" data-submit="habitAdd">
      <div class="row"><input class="input" name="emoji" value="🔁" maxlength="4" style="width:60px;text-align:center">
        <input class="input" name="title" maxlength="60" placeholder="Спорт, вода, лечь до 00:00…" required></div>
      <div class="row" style="margin-top:10px">
        <label class="field" style="flex:2"><span>Как часто</span><select class="input" name="per_week">
          <option value="7">Каждый день</option>${[1, 2, 3, 4, 5, 6].map(n => `<option value="${n}" ${n === 2 ? "" : ""}>${n} ${plural(n, "раз", "раза", "раз")} в неделю</option>`).join("")}</select></label>
        <label class="field" style="flex:1"><span>XP</span><input class="input" name="xp" type="number" min="0" max="200" value="20"></label></div>
      <p class="muted small" style="margin-top:0">Для «N раз в неделю» серия считается в неделях: сделал норму — неделя засчитана 🔥</p>
      <button class="btn btn-accent wide" type="submit">Добавить привычку</button></form>`;
}
actions.habitAdd = async form => {
  await api("POST", "/habits", { title: form.title.value, emoji: form.emoji.value || "🔁",
                                 per_week: Number(form.per_week.value), xp: Number(form.xp.value) || 0 });
  toast("🔁 Привычка добавлена");
  await refresh();
};
actions.habitDel = async el => {
  if (!confirm("Убрать привычку? История останется в статистике.")) return;
  await api("DELETE", "/habits/" + el.dataset.id);
  await refresh();
};

// ---------- 📚 Расписание пар ----------
function pairRow(p) {
  const off = p.status === "cancelled";
  return `<div class="pair ${off ? "off" : ""}"><span class="pair-time">${p.allday ? "весь день" : `${p.start}–${p.end}`}</span>
    <span class="pair-title">${off ? "🎉 " : ""}${esc(p.title)}${p.location ? ` <span class="muted">· ${esc(p.location)}</span>` : ""}</span></div>`;
}
function schedTodayHtml(s) {
  if (!s || !s.connected) return "";
  const pairs = s.pairs.filter(p => !p.allday);
  const allday = s.pairs.filter(p => p.allday && p.status === "ok").map(p => `<div class="small muted">🗓 ${esc(p.title)}</div>`).join("");
  let head;
  if (s.now) {
    head = `<div class="pair-now"><span class="pair-tag">Сейчас</span> <b>${esc(s.now.title)}</b>${s.now.location ? ` · ${esc(s.now.location)}` : ""}
      <div class="small muted">до ${s.now.end} · ещё ${fmtMin(s.now_left_min)}</div></div>`;
  } else if (s.next && s.next.day === s.day) {
    head = `<div class="pair-now"><span class="pair-tag next">Дальше</span> <b>${esc(s.next.title)}</b> в ${s.next.start}${s.next.location ? ` · ${esc(s.next.location)}` : ""}
      <div class="small muted">через ${fmtMin(s.next_in_min)}${s.leave_at && s.next_in_min > 60 ? ` · выходить в ${s.leave_at}` : ""}</div></div>`;
  } else if (pairs.length) {
    head = `<div class="small muted">📚 Пары на сегодня закончились ✌️</div>`;
  } else {
    head = `<div class="small muted">📚 Сегодня пар нет${s.next ? ` · ближайшая ${WD_SHORT[parseDay(s.next.day).getDay()]} ${s.next.start} — ${esc(s.next.title)}` : ""}</div>`;
  }
  const after = s.now && s.next && s.next.day === s.day ? `<div class="small" style="margin-top:6px">⏭ Дальше: ${esc(s.next.title)} в ${s.next.start}${s.next.location ? ` · ${esc(s.next.location)}` : ""}</div>` : "";
  const list = pairs.length ? `<details class="pairs-more"><summary class="small muted">Все пары сегодня · ${pairs.filter(p => p.status === "ok").length}</summary>${pairs.map(pairRow).join("")}</details>` : "";
  return `<div class="card sched-card">${allday}${head}${after}${list}</div>`;
}
function schedDayHtml(s) {
  if (!s || !s.pairs.length) return "";
  const pairs = s.pairs.filter(p => !p.allday);
  const b = s.busy;
  return `<div class="card sched-card">
    <div class="row small"><b>📚 ${pairs.length ? `Пары ${b.first}–${b.last}` : "Пар нет"}</b><span class="spacer"></span>
      ${s.leave_at ? `<span class="muted">🚇 выходить в ${s.leave_at}</span>` : ""}</div>
    ${s.pairs.map(pairRow).join("")}</div>`;
}
function schedSettingsHtml(st, cap) {
  return `<div class="h2">📚 Расписание пар</div>
    <form class="card" data-submit="schedSave">
      ${st.connected ? `<div class="small">✅ Подключено: <span class="muted">${esc(st.url_masked)}</span> · пар впереди: <b>${st.count}</b></div>
        <div class="small muted">Обновлено: ${st.last_sync ? st.last_sync.slice(0, 16).replace("T", " ") : "ещё нет"} · бот сам обновляет раз в 3 часа</div>
        ${st.last_error ? `<div class="small" style="color:var(--bad)">⚠️ ${esc(st.last_error)}</div>` : ""}`
      : `<p class="muted small" style="margin-top:0">В Apple Календаре: «Календари» → ⓘ у «Пары» → «Общий календарь» → скопируй ссылку сюда.</p>`}
      <label class="field" style="margin-top:8px"><span>${st.connected ? "Новая ссылка (пусто — оставить как есть)" : "Ссылка на календарь"}</span>
        <input class="input" name="url" placeholder="webcal://p…-caldav.icloud.com/published/2/…" autocomplete="off"></label>
      <div class="row">
        <label class="field" style="flex:1"><span>Дорога в день с парами, мин (туда и обратно)</span><input class="input" type="number" name="commute" min="0" max="600" value="${st.commute_min}"></label>
        <label class="field" style="flex:1"><span>Часов на квесты в день с парами</span><input class="input" type="number" name="cap_pair" min="0" max="16" step="0.5" value="${cap}"></label></div>
      <label class="row small" style="margin-bottom:12px"><input type="checkbox" name="leave" ${st.leave ? "checked" : ""}> 🚇 напоминать в боте, когда пора выходить</label>
      <div class="row" style="gap:8px"><button class="btn btn-accent" style="flex:1" type="submit">Сохранить</button>
        ${st.connected ? `<button class="btn" type="button" data-act="schedSync">🔄 Обновить</button>
        <button class="btn btn-ghost" type="button" data-act="schedOff" aria-label="Отключить">✕</button>` : ""}</div>
    </form>`;
}
actions.schedSave = async form => {
  const f = form.elements;
  const body = { commute_min: Number(f.commute.value) || 0, leave: f.leave.checked };
  if (f.url.value.trim()) body.url = f.url.value.trim();
  const r = await api("PUT", "/schedule/settings", body);
  const cur = await api("GET", "/settings");
  await api("PUT", "/settings", { ...cur, capacity_pair_h: Number(f.cap_pair.value) || 0, show: undefined, show_titles: undefined, sessions: undefined, day_start_hour: undefined });
  toast(r.last_error ? `⚠️ ${r.last_error}` : body.url ? `📚 Подключено · пар: ${r.count}` : "Сохранено");
  await render();
};
actions.schedSync = async () => {
  const r = await api("POST", "/schedule/sync");
  toast(`🔄 Обновлено · пар впереди: ${r.count}${r.cancelled ? ` · отменили ${r.cancelled}` : ""}`);
  await render();
};
actions.schedOff = async () => {
  if (!confirm("Отключить расписание? Пары пропадут из игры (в Apple Календаре всё останется).")) return;
  await api("PUT", "/schedule/settings", { url: "" });
  await render();
};
