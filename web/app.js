/* LifeGame — веб-приложение. Без сборки и фреймворков: просто открой и читай. */
"use strict";

// ================= Утилиты =================

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const WD_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

function parseDay(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); }
function isoDay(dt) {
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}
function addDays(iso, n) { const d = parseDay(iso); d.setDate(d.getDate() + n); return isoDay(d); }
function ddmm(iso) { const d = parseDay(iso); return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`; }
function dayName(iso) {
  const t = state.meta.today;
  if (iso === t) return "Сегодня";
  if (iso === addDays(t, 1)) return "Завтра";
  if (iso === addDays(t, -1)) return "Вчера";
  return WEEKDAYS[parseDay(iso).getDay()];
}
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}
const fmt = n => Number(n).toLocaleString("ru-RU");

// ================= API =================

class ApiError extends Error {}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = store.get("token");
  if (token) headers.Authorization = "Bearer " + token;
  let res;
  try {
    res = await fetch("/api" + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError("Нет связи с сервером");
  }
  if (res.status === 401 && path !== "/login") { showLogin(); throw new ApiError("Нужно войти"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = "Проверь поля формы";
    throw new ApiError(msg || "Ошибка " + res.status);
  }
  return data;
}

// ================= Эффекты =================

function toast(text, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = text;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 3300);
}
const toastErr = e => toast(esc(e.message || e), "err");

const splashQueue = [];
let splashBusy = false;
function splash(title, sub, cls = "") {
  splashQueue.push({ title, sub, cls });
  if (!splashBusy) nextSplash();
}
function nextSplash() {
  const s = splashQueue.shift();
  const el = $("#splash");
  if (!s) { splashBusy = false; el.hidden = true; return; }
  splashBusy = true;
  el.className = "splash " + s.cls;
  $("#splash-title").textContent = s.title;
  $("#splash-sub").textContent = s.sub;
  el.hidden = false;
  const band = $(".splash-band", el);
  band.style.animation = "none"; void band.offsetWidth; band.style.animation = "";
  if (navigator.vibrate) navigator.vibrate(s.cls === "fail" ? [60, 40, 60] : 40);
  setTimeout(nextSplash, 2400);
}

function celebrate(res, quest) {
  if (quest && quest.status === "done") splash("Задание выполнено", `+${fmt(quest.xp)} XP`);
  if (quest && quest.status === "failed") splash("Задание провалено", "Бывает. Завтра отыграешься.", "fail");
  if (res.level_after > res.level_before) splash("Новый уровень", `Уровень ${res.level_after}`, "level");
  for (const a of res.new_achievements || []) {
    toast(`${a.secret ? "🤫 <b>Секретное достижение!</b>" : "🏆 <b>Достижение:</b>"} ${a.emoji} ${esc(a.title)}`, "ach");
  }
}

// Подсказки для графиков: наведи мышкой или тапни
const tip = $("#tooltip");
function showTip(el, x, y) {
  tip.innerHTML = el.dataset.tip;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x - r.width / 2)) + "px";
  tip.style.top = Math.max(8, y - r.height - 12) + "px";
}
document.addEventListener("pointermove", e => {
  const el = e.target.closest?.("[data-tip]");
  if (el && e.pointerType === "mouse") showTip(el, e.clientX, e.clientY); else if (e.pointerType === "mouse") tip.hidden = true;
});
document.addEventListener("click", e => {
  const el = e.target.closest?.("[data-tip]");
  if (el) { showTip(el, e.clientX, e.clientY); clearTimeout(showTip.t); showTip.t = setTimeout(() => (tip.hidden = true), 2200); }
});
window.addEventListener("scroll", () => (tip.hidden = true), { passive: true });

// ================= Состояние =================

const state = {
  meta: null,
  tab: "today",
  playerDay: null,
  adminDay: null,
  form: { cat: "study", xp: 200, title: "", saveTpl: false },
  editing: null,
  tplEdit: false,
  shopEdit: false,
  chartDays: 30,
  catRange: "xp30",
  stats: null,
};

// ================= HUD =================

async function loadHud() {
  const s = await api("GET", "/stats");
  state.stats = s;
  const lv = s.level;
  $("#hud-lvl").textContent = lv.level;
  $("#hud-xp-fill").style.width = Math.round((100 * lv.into) / lv.need) + "%";
  $("#hud-xp-text").textContent = `${fmt(lv.into)} / ${fmt(lv.need)} XP`;
  $("#hud-coins").textContent = "₵" + fmt(s.coins);
  $("#hud-streak").textContent = "🔥 " + s.streak;
  return s;
}

// ================= Навигация =================

const screens = { today: renderToday, admin: renderAdmin, stats: renderStats, shop: renderShop, settings: renderSettings };

async function go(tab, { animate = true } = {}) {
  if (!screens[tab]) tab = "today";
  state.tab = tab;
  document.querySelectorAll(".tabbar button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  try {
    await screens[tab]();
    if (animate) { view.classList.remove("fade"); void view.offsetWidth; view.classList.add("fade"); }
  } catch (e) { if (!(e instanceof ApiError && e.message === "Нужно войти")) toastErr(e); }
}
const refresh = () => go(state.tab, { animate: false });

document.querySelector(".tabbar").addEventListener("click", e => {
  const b = e.target.closest("button[data-tab]");
  if (b) { go(b.dataset.tab); window.scrollTo({ top: 0 }); }
});

// Все кнопки внутри экранов работают через data-act
const actions = {};
view.addEventListener("click", async e => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  e.preventDefault();
  try { await actions[el.dataset.act](el); } catch (err) { if (err instanceof ApiError || err instanceof Error) toastErr(err); }
});
view.addEventListener("input", e => {
  const el = e.target.closest("[data-input]");
  if (el && actions[el.dataset.input]) actions[el.dataset.input](el);
});
view.addEventListener("submit", async e => {
  const f = e.target.closest("form[data-submit]");
  if (!f) return;
  e.preventDefault();
  try { await actions[f.dataset.submit](f); } catch (err) { toastErr(err); }
});

// ================= Квест-карточка =================

function catOf(key) { return state.meta.categories.find(c => c.key === key); }

function questCard(q, mode) {
  const c = catOf(q.category);
  let actionsHtml = "";
  const isToday = q.day === state.meta.today;
  if (mode === "player") {
    const timerBtn = isToday && c.pickable
      ? `<button class="btn btn-icon btn-sm ${q.timer_running ? "btn-accent" : ""}" data-act="timer" data-id="${q.id}" data-a="${q.timer_running ? "pause" : "start"}" aria-label="${q.timer_running ? "Пауза" : "Таймер"}">${q.timer_running ? "⏸" : "⏱"}</button>` : "";
    actionsHtml = q.status === "todo"
      ? `<button class="btn btn-icon btn-good" data-act="mark" data-id="${q.id}" data-s="done" aria-label="Выполнено">✓</button>
         ${timerBtn}
         <button class="btn btn-icon btn-bad" data-act="mark" data-id="${q.id}" data-s="failed" aria-label="Провалено">✕</button>`
      : `<button class="btn btn-icon" data-act="mark" data-id="${q.id}" data-s="todo" aria-label="Отменить">↩</button>`;
  } else if (mode === "admin") {
    actionsHtml = `<button class="btn btn-icon btn-sm" data-act="edit" data-id="${q.id}" aria-label="Изменить">✎</button>`;
  }
  let html = `<div class="quest ${q.is_main ? "main" : ""} ${q.status}">
    <div class="q-body">
      <div class="q-title">${esc(q.title)}</div>
      <div class="q-meta"><span class="tag">${c.emoji} ${esc(c.title)}</span>
        ${q.bank_id ? `<span class="tag">🗃</span>` : ""}
        ${q.est_min && q.status === "todo" ? `<span class="tag">~${fmtMin(q.est_min)}</span>` : ""}
        ${timerHtml(q)}
        ${q.pace ? `<span class="tag">${{ fast: "⚡", ok: "👌", slow: "🐢" }[q.pace]}</span>` : ""}</div>
    </div>
    <div class="q-xp">${fmt(q.xp)} XP</div>
    ${actionsHtml ? `<div class="q-actions">${actionsHtml}</div>` : ""}
  </div>`;
  if (mode === "player" && isToday && q.status === "done" && q.est_min && !q.pace && q.timer_sec < 60 && c.pickable) {
    html += `<div class="pace-ask small"><span class="muted">По времени как вышло?</span>
      <button class="chip" data-act="pace" data-id="${q.id}" data-p="fast">⚡ быстрее</button>
      <button class="chip" data-act="pace" data-id="${q.id}" data-p="ok">👌 как думал</button>
      <button class="chip" data-act="pace" data-id="${q.id}" data-p="slow">🐢 дольше</button></div>`;
  }
  if (mode === "admin" && state.editing === q.id) {
    html += `<form class="card" data-submit="saveEdit" data-id="${q.id}">
      <label class="field"><span>Название</span><input class="input" name="title" value="${esc(q.title)}" maxlength="200" required></label>
      <div class="row"><label class="field" style="flex:1"><span>XP</span><input class="input" name="xp" type="number" min="0" inputmode="numeric" value="${q.xp}" required></label>
        <label class="field" style="flex:1"><span>Время, мин</span><input class="input" name="est" type="number" min="0" max="1440" inputmode="numeric" value="${q.est_min || ""}" placeholder="—"></label></div>
      <div class="row wrap">
        <button class="btn btn-accent" type="submit">Сохранить</button>
        ${q.status !== "done" ? `<button class="btn" data-act="move" data-id="${q.id}" type="button">→ на день позже</button>` : ""}
        <button class="btn" data-act="toTpl" data-id="${q.id}" type="button">💾 В шаблоны</button>
        <span class="spacer"></span>
        ${q.status !== "done" ? `<button class="btn btn-bad" data-act="del" data-id="${q.id}" type="button">Удалить</button>` : ""}
      </div>
    </form>`;
  }
  return html;
}

// ================= Экран: Сегодня (игрок) =================

async function renderToday() {
  const day = state.playerDay || state.meta.today;
  const isToday = !state.playerDay || state.playerDay === state.meta.today;
  const [d, , prom, plan, habits, rating, money] = await Promise.all([api("GET", "/day/" + day), loadHud(),
    isToday ? api("GET", "/promises") : null, isToday ? api("GET", "/plan/day/" + day) : null,
    isToday ? api("GET", "/habits") : null, api("GET", "/rating/" + day),
    isToday ? api("GET", "/fin/envelopes").catch(() => null) : null]);
  const [sched, marks, story] = isToday ? await Promise.all([api("GET", "/schedule/now").catch(() => null),
    api("GET", "/schedule/marks").catch(() => null), api("GET", "/story").catch(() => null)]) : [null, null, null];
  state.meta.today = d.today;
  const qs = d.quests.filter(q => q.category !== "habit" && q.category !== "money");
  const canPlay = day <= d.today;
  const planned = qs.reduce((s, q) => s + q.xp, 0);
  const got = d.stats.xp_on_day;
  const main = qs.filter(q => q.is_main), bonus = qs.filter(q => !q.is_main && q.category !== "promise");
  const keptToday = qs.filter(q => q.category === "promise");
  const mainDone = main.filter(q => q.status === "done").length;

  let html = `<div class="dayhead">
      <div><div class="h1">${esc(dayName(day))}</div><div class="muted small">${WEEKDAYS[parseDay(day).getDay()]}, ${ddmm(day)}</div></div>
      <div class="nav">
        <button class="btn btn-icon" data-act="pday" data-n="-1" aria-label="Предыдущий день">‹</button>
        ${day !== d.today ? `<button class="btn btn-sm" data-act="pday" data-n="0">Сегодня</button>` : ""}
        <button class="btn btn-icon" data-act="pday" data-n="1" aria-label="Следующий день" ${day > d.today ? "disabled" : ""}>›</button>
      </div>
    </div>`;
  html += storyStripHtml(story) + schedTodayHtml(sched) + studyHtml(marks);
  if (plan) html += startByHtml(plan.start_by);
  if (money && money.on) {
    const left = money.left_today;
    html += `<div class="banner money" data-act="toMoney">💰 ${left >= 0 ? `Можно сегодня <b>${rubR(left)}</b>` : `Больше лимита на <b>${rubR(-left)}</b>`}
      <span class="muted small">· до ${money.next_income ? ddmm(money.next_income.next) : money.days_left + " дн"}${money.unallocated > 0 ? " · 📥 есть неразложенные" : ""}</span></div>`;
  }

  if (qs.length) {
    html += `<div class="dayprog">
      <div class="row small"><span>${canPlay ? `Набрано <b>${fmt(got)}</b> из ${fmt(planned)} XP` : `Можно взять ${fmt(planned)} XP`}</span>
      <span class="spacer"></span><span class="muted">основные ${mainDone}/${main.length}</span></div>
      <div class="dayprog-bar"><div class="dayprog-fill" style="width:${planned ? Math.round((100 * got) / planned) : 0}%"></div></div>
    </div>`;
  }

  if (!qs.some(q => q.category !== "promise")) {
    html += `<div class="empty" style="margin-top:16px"><div class="h3">${canPlay ? "Квестов нет" : "План пуст"}</div>
      <p>Админ ещё не настроил ${day === d.today ? "этот день" : "день"}.</p>
      <button class="btn btn-accent" data-act="toAdmin" data-day="${day}">Настроить</button></div>`;
  } else {
    const mode = canPlay ? "player" : "view";
    if (main.length) html += `<div class="h2">Основные</div>` + main.map(q => questCard(q, mode)).join("");
    if (bonus.length) html += `<div class="h2">Бонусные</div>` + bonus.map(q => questCard(q, mode)).join("");
    if (!main.length && qs.some(q => catOf(q.category).pickable)) html += `<p class="muted small">⚠️ Нет основных квестов — день не пойдёт в серию.</p>`;
    if (canPlay && main.length && mainDone === main.length) {
      html += `<div class="card center" style="margin-top:14px;border-color:var(--good)"><b>✓ День засчитан в серию.</b> <span class="muted">Бонусы — сверху.</span></div>`;
    }
  }
  if (habits) html += habitsHtml(habits);
  if (prom) html += promisesBlock(prom, keptToday);
  else if (keptToday.length) html += `<div class="h2">💌 Сдержано</div>` + keptToday.map(q => questCard(q, canPlay ? "player" : "view")).join("");
  if (canPlay && (parseDay(d.today) - parseDay(day)) / 86400000 <= 1) html += ratingHtml(day, rating.score);
  view.innerHTML = html;
}

// ---------- Обещания ----------

function promiseDueOptions(p) {
  const t = state.meta.today, sat = addDays(t, (6 - parseDay(t).getDay()) % 7);
  const opts = [["", "📅"], [t, "Сегодня"], [addDays(t, 1), "Завтра"], [sat, "На выходных"], [addDays(t, 7), "Через неделю"], ["none", "Без срока"]];
  return opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
}

function promisesBlock(prom, keptToday = []) {
  const st = prom.stats;
  let html = `<div class="h2">💌 Обещания</div>
    <form class="row" data-submit="addPromise" style="margin-bottom:10px">
      <input class="input" name="text" maxlength="300" placeholder="забрать посылку в пятницу" required>
      <button class="btn btn-accent" type="submit">＋</button>
    </form>`;
  if (!prom.open.length) {
    html += `<div class="empty small">Открытых обещаний нет 🧹 Срок можно писать прямо в тексте: «завтра», «в пятницу», «на выходных», «до 12.11».</div>`;
  }
  for (const p of prom.open) {
    const meta = [p.due_label];
    if (!p.due && p.age >= 2) meta.push(`висит ${p.age} дн`);
    if (p.postponed) meta.push(`переносил ${p.postponed}×`);
    html += `<div class="quest promise ${p.overdue ? "overdue" : ""}">
      <div class="q-body"><div class="q-title">${esc(p.text)}</div>
        <div class="q-meta"><span class="tag">${p.overdue ? "⚠️ " : ""}${esc(meta.join(" · "))}</span></div></div>
      <div class="q-xp">${p.xp_now} XP</div>
      <div class="q-actions">
        <button class="btn btn-icon btn-good" data-act="pKeep" data-id="${p.id}" aria-label="Сдержал">✓</button>
        <select class="btn btn-icon pdue" data-input="pDue" data-id="${p.id}" aria-label="Срок">${promiseDueOptions(p)}</select>
        <button class="btn btn-icon btn-sm btn-ghost" data-act="pCancel" data-id="${p.id}" aria-label="Отменили вместе">✕</button>
      </div></div>`;
  }
  if (keptToday.length) html += `<div class="h3" style="margin-top:14px">Сдержано сегодня</div>` + keptToday.map(q => questCard(q, "player")).join("");
  html += `<p class="muted small">✓ сдержал: +${prom.xp} XP, за ${prom.fast_days} дня — +${prom.fast_xp}. ✕ — отменили вместе, без штрафа.
    ${st.kept ? `<br>Сдержано всего: <b>${st.kept}</b>, из них в срок ${st.on_time}.` : ""}</p>`;
  return html;
}

actions.addPromise = async form => {
  const p = await api("POST", "/promises", { text: form.text.value });
  toast(`💌 Записал: ${esc(p.text)} · <b>${esc(p.due_label)}</b>`);
  await renderToday();
};
actions.pKeep = async el => {
  el.disabled = true;
  const res = await api("PATCH", "/promises/" + el.dataset.id, { action: "keep" });
  splash("Обещание сдержано", `+${res.xp} XP${res.fast ? " · быстро!" : ""}`);
  celebrate(res);
  await renderToday();
};
actions.pCancel = async el => {
  if (!confirm("Отменили вместе? (без XP и без штрафа)")) return;
  await api("PATCH", "/promises/" + el.dataset.id, { action: "cancel" });
  await renderToday();
};
actions.pDue = async el => {
  if (!el.value) return;
  const body = el.value === "none" ? { clear_due: true } : { due: el.value };
  try {
    const r = await api("PATCH", "/promises/" + el.dataset.id, body);
    toast("📅 Срок: " + esc(r.promise.due_label));
    await renderToday();
  } catch (e) { toastErr(e); }
};

actions.pday = el => {
  const n = Number(el.dataset.n);
  state.playerDay = n === 0 ? state.meta.today : addDays(state.playerDay || state.meta.today, n);
  return renderToday();
};
actions.mark = async el => {
  el.disabled = true;
  const res = await api("PATCH", "/quests/" + el.dataset.id, { status: el.dataset.s });
  celebrate(res, res.quest);
  await renderToday();
};
actions.toMoney = () => { state.finTab = "home"; return go("finance"); };
actions.toAdmin = el => { state.adminDay = el.dataset.day; return go("admin"); };

// ================= Экран: Админ =================

async function renderAdmin() {
  const t = state.meta.today;
  if (!state.adminDay || state.adminDay < t) state.adminDay = addDays(t, 1);
  if (state.adminTab === "bank") { await loadHud(); return renderBank(); }
  if (state.adminTab === "story") { await loadHud(); return renderStory(); }
  const day = state.adminDay;
  const [d, tpls, pl, sch] = await Promise.all([api("GET", "/day/" + day), api("GET", "/templates"), api("GET", "/plan/day/" + day),
    api("GET", "/schedule/day/" + day).catch(() => null), loadHud()]);
  const qs = d.quests.filter(q => q.category !== "habit");
  const mains = qs.filter(q => q.is_main).length;
  const f = state.form;
  const cat = catOf(f.cat);
  const sliderMax = Math.max(cat.xp_max * 2, 100);

  const dayChip = (iso, label) => `<button class="chip ${day === iso ? "on" : ""}" data-act="aday" data-day="${iso}">${label}</button>`;

  let html = adminTabs() + `
    <p class="muted small" style="margin:4px 0 12px">Вечером настраиваешь игру — утром играешь.</p>
    <div class="chips">
      ${dayChip(t, "Сегодня")}${dayChip(addDays(t, 1), "Завтра")}${dayChip(addDays(t, 2), WD_SHORT[parseDay(addDays(t, 2)).getDay()] + " " + ddmm(addDays(t, 2)))}
      <input type="date" class="chip" data-input="adayPick" value="${day}" min="${t}" aria-label="Другая дата">
    </div>

    <div class="h2">${esc(dayName(day))}, ${ddmm(day)}</div>
    <div class="row small" style="margin-bottom:10px">
      <span>Основных <b style="color:${mains ? "var(--ink)" : "var(--bad)"}">${mains}/${state.meta.max_main}</b></span>
      <span class="muted">·</span><span>${qs.length} ${plural(qs.length, "квест", "квеста", "квестов")}</span>
      <span class="muted">·</span><span><b>${fmt(qs.reduce((s, q) => s + q.xp, 0))}</b> XP</span>
    </div>${schedDayHtml(sch)}${loadHtml(pl.load)}
    <button class="btn btn-sm" data-act="adminTab" data-t="bank" style="margin-bottom:10px">🗃 Взять из банка</button>
    ${qs.length ? qs.map(q => questCard(q, "admin")).join("") : `<div class="empty">Пусто. Добавь 1–3 основных квеста и бонусы.</div>`}

    <div class="h2">Шаблоны <span class="spacer"></span></div>
    <div class="row" style="margin:-4px 0 8px"><span class="muted small">Тапни — квест добавится в выбранный день.</span><span class="spacer"></span>
      <button class="btn btn-sm btn-ghost" data-act="tplEdit">${state.tplEdit ? "Готово" : "Изменить"}</button></div>
    <div class="chips">
      ${tpls.length ? tpls.map(tp => {
        const c = catOf(tp.category);
        return state.tplEdit
          ? `<button class="chip" data-act="tplDel" data-id="${tp.id}">✕ ${esc(tp.title)}</button>`
          : `<button class="chip" data-act="tplUse" data-id="${tp.id}">${c.emoji} ${esc(tp.title)} · ${tp.xp}</button>`;
      }).join("") : `<span class="muted small">Шаблонов нет. Отметь «сохранить в шаблоны» при добавлении.</span>`}
    </div>

    <div class="h2">Новый квест</div>
    <form class="card" data-submit="addQuest">
      <label class="field"><span>Категория</span></label>
      <div class="chips" style="margin:-6px 0 14px">
        ${state.meta.categories.filter(c => c.pickable).map(c => `<button type="button" class="chip ${f.cat === c.key ? "on" : ""}" data-act="fcat" data-cat="${c.key}">${c.emoji} ${esc(c.title)}</button>`).join("")}
      </div>
      <label class="field"><span>XP — обычно ${cat.xp_min}–${cat.xp_max}</span>
        <div class="row">
          <input type="range" min="0" max="${sliderMax}" step="10" value="${Math.min(f.xp, sliderMax)}" data-input="fxpRange" aria-label="XP">
          <input class="input" style="width:96px" type="number" min="0" inputmode="numeric" value="${f.xp}" data-input="fxpNum" aria-label="XP числом">
        </div>
        <div id="xp-hint" class="small" style="margin-top:4px">${xpHint(cat, f.xp)}</div>
      </label>
      <label class="field"><span>Примерно времени</span></label>
      <div class="chips" style="margin:-6px 0 14px">${[0, ...TIME_PRESETS.slice(0, 7)].map(m =>
        `<button type="button" class="chip ${(f.est || 0) === m ? "on" : ""}" data-act="fest" data-m="${m}">${m ? fmtMin(m) : "не знаю"}</button>`).join("")}</div>
      <label class="field"><span>Название</span>
        <input class="input" name="title" maxlength="200" placeholder="Например: Лаба по криптографии" value="${esc(f.title)}" data-input="ftitle" required></label>
      <label class="row small" style="margin-bottom:12px"><input type="checkbox" data-input="ftpl" ${f.saveTpl ? "checked" : ""}> сохранить в шаблоны</label>
      <button class="btn btn-accent wide" type="submit">Добавить на ${esc(dayName(day).toLowerCase())}</button>
    </form>`;
  view.innerHTML = html;
}

function xpHint(cat, xp) {
  if (xp > cat.xp_max) return `<span style="color:var(--accent)">🔥 Ультра хард — больше обычного</span>`;
  if (xp < cat.xp_min) return `<span class="muted">Меньше обычного</span>`;
  return `<span class="muted">≈ ${fmt(Math.floor(xp / state.meta.coins_per_xp))} монет</span>`;
}

actions.aday = el => { state.adminDay = el.dataset.day; state.editing = null; return renderAdmin(); };
actions.adayPick = el => { if (el.value) { state.adminDay = el.value; renderAdmin().catch(toastErr); } };
actions.fcat = el => {
  const c = catOf(el.dataset.cat);
  state.form.cat = c.key;
  state.form.xp = Math.round((c.xp_min + c.xp_max) / 2 / 10) * 10;
  return renderAdmin();
};
function syncXp(v) {
  const f = state.form;
  f.xp = Math.max(0, Number(v) || 0);
  const cat = catOf(f.cat);
  const range = $('[data-input="fxpRange"]'), num = $('[data-input="fxpNum"]');
  if (document.activeElement !== range) range.value = Math.min(f.xp, Number(range.max));
  if (document.activeElement !== num) num.value = f.xp;
  $("#xp-hint").innerHTML = xpHint(cat, f.xp);
}
actions.fxpRange = el => syncXp(el.value);
actions.fxpNum = el => syncXp(el.value);
actions.ftitle = el => { state.form.title = el.value; };
actions.fest = el => { state.form.est = Number(el.dataset.m); return renderAdmin(); };
actions.ftpl = el => { state.form.saveTpl = el.checked; };

actions.addQuest = async () => {
  const f = state.form;
  const res = await api("POST", "/quests", { day: state.adminDay, category: f.cat, title: f.title, xp: f.xp, est_min: f.est || null });
  if (f.saveTpl) await api("POST", "/templates", { category: f.cat, title: f.title, xp: f.xp, est_min: f.est || null });
  toast(`➕ ${esc(res.quest.title)}${res.warning ? " · ⚠️ XP " + esc(res.warning) : ""}`);
  f.title = "";
  await renderAdmin();
};
actions.edit = el => { const id = Number(el.dataset.id); state.editing = state.editing === id ? null : id; return renderAdmin(); };
actions.saveEdit = async form => {
  await api("PATCH", "/quests/" + form.dataset.id, { title: form.title.value, xp: Number(form.xp.value), est_min: Number(form.est.value) || null });
  state.editing = null;
  toast("Сохранено");
  await renderAdmin();
};
actions.move = async el => {
  const q = (await api("GET", "/day/" + state.adminDay)).quests.find(x => x.id === Number(el.dataset.id));
  await api("PATCH", "/quests/" + el.dataset.id, { day: addDays(q.day, 1) });
  state.editing = null;
  toast("Перенесено на " + ddmm(addDays(q.day, 1)));
  await renderAdmin();
};
actions.del = async el => {
  if (!confirm("Удалить квест?")) return;
  await api("DELETE", "/quests/" + el.dataset.id);
  state.editing = null;
  await renderAdmin();
};
actions.toTpl = async el => {
  const q = (await api("GET", "/day/" + state.adminDay)).quests.find(x => x.id === Number(el.dataset.id));
  await api("POST", "/templates", { category: q.category, title: q.title, xp: q.xp, est_min: q.est_min });
  toast("💾 Сохранено в шаблоны");
  await renderAdmin();
};
actions.tplEdit = () => { state.tplEdit = !state.tplEdit; return renderAdmin(); };
actions.tplUse = async el => {
  const res = await api("POST", "/quests/from-template", { day: state.adminDay, template_id: Number(el.dataset.id) });
  toast(`➕ ${esc(res.quest.title)}`);
  await renderAdmin();
};
actions.tplDel = async el => { await api("DELETE", "/templates/" + el.dataset.id); await renderAdmin(); };

// ================= Экран: Статы =================

// Красивый «круглый» максимум для оси: 1, 2, 5 × 10^k
function niceMax(v) {
  if (v <= 0) return 100;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

// Столбик со скруглённым верхом (4px), прижатый к оси
function barPath(x, y, w, h, r = 4) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// Столбчатый график: факт поверх плана (план — бледная «тень»)
function barChart(el, { labels, values, planned, tips, showEvery = 1 }) {
  const W = Math.max(280, el.clientWidth), H = 190;
  const padL = 38, padB = 22, padT = 8;
  const n = values.length;
  const maxV = niceMax(Math.max(...values, ...(planned || [0])));
  const plotW = W - padL, plotH = H - padB - padT;
  const slot = plotW / n, gap = Math.max(2, slot * 0.22), bw = slot - gap;
  const y = v => padT + plotH - (v / maxV) * plotH;

  let svg = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">`;
  for (const g of [0, 0.5, 1]) {
    const gy = y(maxV * g);
    svg += `<line class="grid" x1="${padL}" x2="${W}" y1="${gy}" y2="${gy}"/>`;
    svg += `<text x="${padL - 6}" y="${gy + 4}" text-anchor="end">${fmt(maxV * g)}</text>`;
  }
  for (let i = 0; i < n; i++) {
    const x = padL + i * slot + gap / 2;
    if (planned && planned[i] > values[i]) {
      svg += `<path class="bar-plan" d="${barPath(x, y(planned[i]), bw, plotH + padT - y(planned[i]))}"/>`;
    }
    svg += `<path class="bar" d="${barPath(x, y(values[i]), bw, plotH + padT - y(values[i]))}"/>`;
    svg += `<rect class="hit" x="${padL + i * slot}" y="${padT}" width="${slot}" height="${plotH}" data-tip="${esc(tips[i])}"/>`;
    if ((n - 1 - i) % showEvery === 0) {
      svg += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(labels[i])}</text>`;
    }
  }
  svg += `</svg>`;
  el.innerHTML = svg;
}

const HEAT = ["var(--surface-2)", "var(--cal1)", "var(--cal2)", "var(--cal3)", "var(--cal4)"];
function heatLevel(xp) { return xp <= 0 ? 0 : xp < 200 ? 1 : xp < 500 ? 2 : xp < 900 ? 3 : 4; }

async function renderStats() {
  if (state.statsTab && state.statsTab !== "main") { await loadHud(); return STATS[state.statsTab](); }
  const s = await loadHud();
  const lv = s.level;
  const hist = s.history;
  const rate = s.completion_30 == null ? "—" : s.completion_30 + "%";

  let html = `<div class="h1">Статистика</div>` + statsTabs() + `
    <div class="tiles" style="margin-top:12px">
      <div class="tile"><div class="stat-label">Уровень</div><div class="stat-value" style="color:var(--accent)">${lv.level}</div><div class="stat-sub">${fmt(lv.into)} / ${fmt(lv.need)} XP</div></div>
      <div class="tile"><div class="stat-label">Серия</div><div class="stat-value">🔥 ${s.streak}</div><div class="stat-sub">рекорд ${s.best_streak} ${plural(s.best_streak, "день", "дня", "дней")}</div></div>
      <div class="tile"><div class="stat-label">Всего XP</div><div class="stat-value">${fmt(s.total_xp)}</div><div class="stat-sub">лучший день ${fmt(s.best_day_xp)}</div></div>
      <div class="tile"><div class="stat-label">За 30 дней</div><div class="stat-value">${rate}</div><div class="stat-sub">квестов выполнено · всего ${fmt(s.quests_done)}</div></div>
    </div>

    <div class="h2">XP по дням</div>
    <div class="row"><div class="legend"><span><i style="background:var(--accent)"></i>получено</span><span><i style="background:var(--surface-2);border:1px solid var(--chart-line)"></i>было в плане</span></div>
      <span class="spacer"></span>
      <div class="chips">${[14, 30].map(n => `<button class="chip ${state.chartDays === n ? "on" : ""}" data-act="chartDays" data-n="${n}">${n} дн</button>`).join("")}</div></div>
    <div id="ch-days"></div>

    <div class="h2">XP по неделям</div>
    <div id="ch-weeks"></div>

    <div class="h2">Карта активности</div>
    <div id="heat"></div>
    <div class="legend" style="justify-content:flex-end;margin-top:8px">меньше ${HEAT.map(c => `<i style="background:${c};margin:0"></i>`).join(" ")} больше</div>

    <div class="h2">По категориям</div>
    <div class="chips" style="margin-bottom:12px">
      <button class="chip ${state.catRange === "xp30" ? "on" : ""}" data-act="catRange" data-r="xp30">30 дней</button>
      <button class="chip ${state.catRange === "xp" ? "on" : ""}" data-act="catRange" data-r="xp">Всё время</button>
    </div>
    <div id="cats"></div>

    <div class="h2">Достижения · ${s.achievements.filter(a => a.done).length}/${s.achievements.length}</div>
    <div class="ach-grid">${s.achievements.map(a => `<div class="ach ${a.done ? "" : "locked"} ${a.secret ? "secret" : ""}">
      <div class="ach-emoji">${a.emoji}</div><div class="ach-title">${esc(a.title)}</div><div class="ach-desc">${esc(a.desc)}</div></div>`).join("")}</div>`;
  view.innerHTML = html;

  // По дням
  const last = hist.slice(-state.chartDays);
  barChart($("#ch-days"), {
    labels: last.map(h => String(parseDay(h.day).getDate())),
    values: last.map(h => h.xp),
    planned: last.map(h => h.planned),
    tips: last.map(h => `${WD_SHORT[parseDay(h.day).getDay()]} ${ddmm(h.day)}: <b>${fmt(h.xp)}</b> из ${fmt(h.planned)} XP${h.complete ? " · ✓ в серию" : ""}`),
    showEvery: state.chartDays > 14 ? 5 : 2,
  });

  // По неделям (понедельник — начало недели)
  const weeks = [];
  for (const h of hist) {
    const dt = parseDay(h.day);
    const monday = addDays(h.day, -((dt.getDay() + 6) % 7));
    let w = weeks[weeks.length - 1];
    if (!w || w.start !== monday) weeks.push((w = { start: monday, xp: 0, planned: 0 }));
    w.xp += h.xp; w.planned += h.planned;
  }
  barChart($("#ch-weeks"), {
    labels: weeks.map(w => ddmm(w.start)),
    values: weeks.map(w => w.xp),
    planned: weeks.map(w => w.planned),
    tips: weeks.map(w => `Неделя с ${ddmm(w.start)}: <b>${fmt(w.xp)}</b> XP`),
    showEvery: 3,
  });

  // Тепловая карта: колонки — недели, строки — дни недели
  const first = hist[0].day;
  const start = addDays(first, -((parseDay(first).getDay() + 6) % 7));
  const byDay = Object.fromEntries(hist.map(h => [h.day, h]));
  const t = state.meta.today;
  let cells = "";
  const end = addDays(t, 6 - ((parseDay(t).getDay() + 6) % 7));
  for (let d = start; d <= end; d = addDays(d, 1)) {
    const h = byDay[d];
    if (!h || d > t) { cells += `<div class="out"></div>`; continue; }
    cells += `<div class="${d === t ? "today" : ""}" style="background:${HEAT[heatLevel(h.xp)]}" data-tip="${esc(`${WD_SHORT[parseDay(d).getDay()]} ${ddmm(d)}: <b>${fmt(h.xp)}</b> XP${h.complete ? " · ✓" : ""}`)}"></div>`;
  }
  $("#heat").innerHTML = `<div class="heat-wrap"><div class="heat-days">${["Пн", "", "Ср", "", "Пт", "", "Вс"].map(x => `<span>${x}</span>`).join("")}</div><div class="heat">${cells}</div></div>`;

  // Категории
  const cats = state.meta.categories.map(c => ({ c, v: s.by_category[c.key][state.catRange] }));
  const cmax = Math.max(1, ...cats.map(x => x.v));
  $("#cats").innerHTML = cats.sort((a, b) => b.v - a.v).map(({ c, v }) => `<div class="hbar" data-tip="${esc(`${c.title}: <b>${fmt(v)}</b> XP`)}">
      <div class="hbar-name">${c.emoji} ${esc(c.title)}</div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${(100 * v) / cmax}%"></div></div>
      <div class="hbar-val">${fmt(v)}</div></div>`).join("");
}

actions.chartDays = el => { state.chartDays = Number(el.dataset.n); return renderStats(); };
actions.catRange = el => { state.catRange = el.dataset.r; return renderStats(); };
let resizeT;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => { if (state.tab === "stats") renderStats().catch(() => {}); }, 250);
});

// ================= Экран: Магазин =================

function avgCoinsPerDay(s) {
  const last = s.history.slice(-15, -1);   // 14 полных дней
  const xp = last.reduce((a, h) => a + h.xp, 0);
  return xp / 14 / state.meta.coins_per_xp;
}

async function renderShop() {
  const [shop, s] = await Promise.all([api("GET", "/shop"), loadHud()]);
  const kinds = state.meta.shop_kinds;
  const perDay = avgCoinsPerDay(s);

  let html = `<div class="wallet"><div class="stat-label">Монеты</div><div class="wallet-num">₵${fmt(shop.coins)}</div>
    <div class="muted small">${perDay > 0 ? `в среднем +${fmt(Math.round(perDay))} в день` : `1 XP = 1/${state.meta.coins_per_xp} монеты`}</div></div>
    <div class="row" style="margin-top:8px"><span class="spacer"></span>
      <button class="btn btn-sm btn-ghost" data-act="shopEdit">${state.shopEdit ? "Готово" : "Изменить"}</button></div>`;

  if (!shop.items.length) {
    html += `<div class="empty">Магазин пуст. Добавь награды: вещи из вишлиста, походы, маленькие интерактивы.</div>`;
  }
  for (const [kind, label] of Object.entries(kinds)) {
    const items = shop.items.filter(i => i.kind === kind);
    if (!items.length) continue;
    html += `<div class="h2">${esc(label)}</div>`;
    for (const it of items) {
      const sold = !it.repeatable && it.bought > 0;
      const lack = it.cost - shop.coins;
      let btn;
      if (state.shopEdit) btn = `<button class="btn btn-sm btn-bad" data-act="itemDel" data-id="${it.id}">Убрать</button>`;
      else if (sold) btn = `<span class="tag">куплено</span>`;
      else if (lack > 0) btn = `<button class="btn btn-sm" disabled>ещё ₵${fmt(lack)}</button>`;
      else btn = `<button class="btn btn-sm btn-accent" data-act="buy" data-id="${it.id}" data-title="${esc(it.title)}" data-cost="${it.cost}">Купить</button>`;
      const eta = !sold && lack > 0 && perDay > 0 ? ` · ≈ ${Math.ceil(lack / perDay)} ${plural(Math.ceil(lack / perDay), "день", "дня", "дней")}` : "";
      html += `<div class="card item ${sold ? "bought" : ""}">
        <div class="q-body"><div class="q-title">${esc(it.title)}</div>
          <div class="q-meta"><span class="tag">${it.repeatable ? `многоразовое${it.bought ? " · куплено " + it.bought : ""}` : "одноразовое"}${eta}</span></div></div>
        <div class="price">₵${fmt(it.cost)}</div>${btn}</div>`;
    }
  }

  html += `<details class="card" style="margin-top:18px" ${shop.items.length ? "" : "open"}><summary>＋ Добавить награду</summary>
    <form data-submit="addItem">
      <label class="field"><span>Название</span><input class="input" name="title" maxlength="200" placeholder="Например: сходить в квест-комнату" required></label>
      <label class="field"><span>Цена в монетах</span><input class="input" name="cost" type="number" min="1" inputmode="numeric" required></label>
      <label class="field"><span>Тип</span><select class="input" name="kind">${Object.entries(kinds).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <label class="row small" style="margin-bottom:12px"><input type="checkbox" name="repeatable"> можно покупать много раз</label>
      <p class="muted small">Ориентир: за день набирается ~60–100 монет. Мелочь — 30–80, поход — 200–500, большая вещь из вишлиста — 1000+.</p>
      <button class="btn btn-accent wide" type="submit">Добавить</button>
    </form></details>`;

  if (shop.purchases.length) {
    html += `<div class="h2">История покупок</div><ul class="list-plain card">
      ${shop.purchases.map(p => `<li><div class="q-body"><div>${esc(p.title)}</div><div class="muted small">${ddmm(p.created_at.slice(0, 10))}</div></div>
        <span class="price" style="font-size:16px">−₵${fmt(p.cost)}</span>
        <button class="btn btn-sm btn-ghost" data-act="refund" data-id="${p.id}" aria-label="Отменить покупку">↩</button></li>`).join("")}
    </ul>`;
  }
  view.innerHTML = html;
}

actions.shopEdit = () => { state.shopEdit = !state.shopEdit; return renderShop(); };
actions.buy = async el => {
  if (!confirm(`Купить «${el.dataset.title}» за ₵${el.dataset.cost}?`)) return;
  const res = await api("POST", `/shop/items/${el.dataset.id}/buy`);
  splash("Куплено", res.item.title, "level");
  celebrate(res);
  await renderShop();
};
actions.addItem = async form => {
  await api("POST", "/shop/items", {
    title: form.title.value, cost: Number(form.cost.value), kind: form.kind.value, repeatable: form.repeatable.checked,
  });
  toast("🛒 Добавлено в магазин");
  await renderShop();
};
actions.itemDel = async el => {
  if (!confirm("Убрать товар из магазина?")) return;
  await api("DELETE", "/shop/items/" + el.dataset.id);
  await renderShop();
};
actions.refund = async el => {
  if (!confirm("Отменить покупку и вернуть монеты?")) return;
  await api("DELETE", "/shop/purchases/" + el.dataset.id);
  toast("↩ Монеты возвращены");
  await renderShop();
};

// ================= Тема =================
const THEMES = [
  ["auto", "Авто", ["#fff6ef", "#e2588f", "#0d0f11", "#f0a53a"]],
  ["vice", "Vice City", ["#fff6ef", "#e2588f", "#23977a"]],
  ["night", "Ночной город", ["#0d0f11", "#f0a53a", "#8fd18a"]],
];
function themePicker() {
  const cur = window.LGTheme ? LGTheme.get() : "auto";
  return `<div class="theme-pick">${THEMES.map(([k, title, sw]) => `<button class="${k === cur ? "on" : ""}" data-act="setTheme" data-k="${k}">
    <span class="sw">${sw.map(c => `<i style="background:${c};border:1px solid var(--line)"></i>`).join("")}</span>
    <span class="small">${title}</span></button>`).join("")}</div>`;
}
actions.setTheme = el => {
  LGTheme.set(el.dataset.k);
  document.querySelectorAll(".theme-pick button").forEach(b => b.classList.toggle("on", b.dataset.k === el.dataset.k));
};

// ================= Экран: Настройки =================

async function renderSettings() {
  const [st, , habitsBlock, sch] = await Promise.all([api("GET", "/settings"), loadHud(), habitsSettingsHtml(),
    api("GET", "/schedule/settings")]);
  const m = state.meta;
  view.innerHTML = `<div class="h1">Настройки</div>

    <div class="h2">🎨 Тема</div>
    <div class="card">${themePicker()}
      <p class="muted small" style="margin-bottom:0">«Авто»: днём, пока ты игрок, — светлый Vice City, с 20:00 до 6:00, в режиме админа, — ночной город. Тема запоминается на этом устройстве.</p></div>

    ${schedSettingsHtml(sch, st.capacity_pair_h)}

    <div class="h2">⏰ Время</div>
    <form class="card" data-submit="saveSettings">
      <div class="row">
        <label class="field" style="flex:1"><span>Отбой</span><input class="input" type="time" name="bedtime" value="${esc(st.bedtime)}"></label>
        <label class="field" style="flex:1"><span>Часов на дела в свободный день</span><input class="input" type="number" name="capacity" min="1" max="16" step="0.5" value="${st.capacity_h}"></label>
      </div>
      <p class="muted small" style="margin-top:0">По отбою считается «начни не позже», по часам на дела — перегруз дня в админке.</p>
      <label class="row small" style="margin-bottom:12px"><input type="checkbox" name="startby" ${st.remind_startby ? "checked" : ""}> напомнить в боте, когда пора садиться</label>
      <button class="btn btn-accent wide" type="submit">Сохранить</button>
    </form>
    ${habitsBlock}

    <div class="h2">🤖 Что бот показывает в «Сегодня» сразу</div>
    <div class="card">${Object.entries(st.show).map(([k, on]) => `<label class="row small" style="padding:6px 0">
      <input type="checkbox" data-input="botShow" data-k="${k}" ${on ? "checked" : ""}> ${esc(st.show_titles[k])}</label>`).join("")}
      <p class="muted small" style="margin-bottom:0">Выключенное остаётся в боте — по маленьким кнопкам под квестами. То же самое: в боте ☰ Ещё → ⚙.</p></div>

    <div class="h2">Напоминания в Telegram</div>
    <form class="card" data-submit="saveSettings">
      <p class="muted small" style="margin-top:0">Необязательно. Оставь поле пустым — напоминания не будет.</p>
      <label class="field"><span>☀️ Утро: «игра началась» + квесты</span><input class="input" type="time" name="morning" value="${esc(st.remind_morning)}"></label>
      <label class="field"><span>🌙 Вечер: «время админа»</span><input class="input" type="time" name="evening" value="${esc(st.remind_evening)}"></label>
      <label class="field"><span>☀️ Сводка: обещания и платежи</span><input class="input" type="time" name="promises" value="${esc(st.remind_promises)}"></label>
      <div class="h3" style="margin-top:6px">👋 Умные чек-ины</div>
      <p class="muted small" style="margin-top:0">Бот спросит «всё по плану?», только если ты давно ничего не отмечал. Два без ответа подряд — замолкает до твоей активности.</p>
      <label class="row small" style="margin-bottom:10px"><input type="checkbox" name="ci_on" ${st.checkin_on ? "checked" : ""}> включены</label>
      <div class="row">
        <label class="field" style="flex:1"><span>Если тишина, ч</span><select class="input" name="ci_every">${[1, 2, 3, 4, 5, 6].map(n => `<option ${st.checkin_every === n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label class="field" style="flex:1"><span>С (час)</span><input class="input" name="ci_from" type="number" min="0" max="23" value="${st.checkin_from}"></label>
        <label class="field" style="flex:1"><span>До (час)</span><input class="input" name="ci_to" type="number" min="1" max="24" value="${st.checkin_to}"></label>
      </div>
      <button class="btn btn-accent wide" type="submit">Сохранить</button>
    </form>

    <div class="h2">Правила</div>
    <div class="card">
      ${m.categories.map(c => `<div class="row" style="padding:4px 0"><span>${c.emoji} ${esc(c.title)}${c.is_main ? "" : " (бонус)"}</span><span class="spacer"></span><b>${c.xp_min}–${c.xp_max} XP</b></div>`).join("")}
      <p class="muted small" style="margin-bottom:0">Основных — до ${m.max_main} в день. Уровень: ${m.level_base} XP на первый, дальше +${m.level_step}. Монеты = XP / ${m.coins_per_xp}.
      Новый игровой день начинается в ${st.day_start_hour}:00. Серия идёт, если все основные квесты дня выполнены.</p>
    </div>

    <div class="h2">Установить как приложение</div>
    <div class="card small">
      <p style="margin-top:0"><b>iPhone / iPad:</b> Safari → кнопка «Поделиться» → «На экран „Домой“».</p>
      <p style="margin-bottom:0"><b>Android / ПК:</b> меню браузера → «Установить приложение».</p>
    </div>

    <div class="h2">Аккаунт</div>
    <div class="card">
      <p class="muted small" style="margin-top:0">Активных входов: ${st.sessions}. Выйти на всех устройствах — команда <code>/logout_all</code> в боте.</p>
      <button class="btn wide" data-act="logout">Выйти на этом устройстве</button>
    </div>`;
}

actions.saveSettings = async form => {
  // форм несколько — берём текущие настройки и меняем только поля этой формы
  const cur = await api("GET", "/settings");
  const body = {
    remind_morning: cur.remind_morning, remind_evening: cur.remind_evening, remind_promises: cur.remind_promises,
    checkin_on: cur.checkin_on, checkin_every: cur.checkin_every, checkin_from: cur.checkin_from, checkin_to: cur.checkin_to,
    bedtime: cur.bedtime, capacity_h: cur.capacity_h, capacity_pair_h: cur.capacity_pair_h, remind_startby: cur.remind_startby,
  };
  const f = form.elements;
  if (f.morning) Object.assign(body, {
    remind_morning: f.morning.value, remind_evening: f.evening.value, remind_promises: f.promises.value,
    checkin_on: f.ci_on.checked, checkin_every: Number(f.ci_every.value),
    checkin_from: Number(f.ci_from.value), checkin_to: Number(f.ci_to.value),
  });
  if (f.bedtime) Object.assign(body, { bedtime: f.bedtime.value || "00:00", capacity_h: Number(f.capacity.value) || 6,
                                       remind_startby: f.startby.checked });
  await api("PUT", "/settings", body);
  toast("Сохранено");
};
actions.botShow = async el => {
  await api("PUT", "/settings/show", { [el.dataset.k]: el.checked });
  toast("Сохранено");
};
actions.logout = async () => {
  try { await api("POST", "/logout"); } catch {}
  store.set("token", null);
  showLogin();
};

// ================= Вход =================

function showLogin(msg = "") {
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#login-error").textContent = msg;
}

async function doLogin(code) {
  $("#login-error").textContent = "";
  try {
    const { token } = await api("POST", "/login", { code });
    store.set("token", token);
    await start();
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
}

$("#login-form").addEventListener("submit", e => {
  e.preventDefault();
  const code = $("#login-code").value.trim();
  if (code) doLogin(code);
});

async function start() {
  state.meta = await api("GET", "/meta");
  $("#login").hidden = true;
  $("#app").hidden = false;
  const tab = location.hash.slice(1);
  await go(screens[tab] ? tab : "today");
}

// Когда приложение снова открыли (утром) — обновить «сегодня»
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState === "visible" && state.meta) {
    try { state.meta = await api("GET", "/meta"); state.playerDay = null; refresh(); } catch {}
  }
});

(async function boot() {
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  // Ссылка из бота: /#code=XXXX — входим автоматически, код убираем из адреса
  const m = location.hash.match(/code=([A-Za-z0-9-]+)/);
  if (m) {
    history.replaceState(null, "", location.pathname);
    $("#login-code").value = m[1];
    showLogin();
    return doLogin(m[1]);
  }
  if (!store.get("token")) return showLogin();
  try { await start(); } catch (e) { if (!$("#login").hidden) return; showLogin(e.message); }
})();
