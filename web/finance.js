/* LifeGame — вкладка «Финансы». Использует общие функции из app.js (api, esc, toast, barChart…). */
"use strict";

function rub(k, sign = false) {
  if (k == null) return "—";
  const s = k < 0 ? "−" : sign && k > 0 ? "+" : "";
  return s + (Math.abs(k) / 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + " ₽";
}
const bar = (v, max) => `<div class="dayprog-bar"><div class="dayprog-fill" style="width:${max ? Math.min(100, (100 * v) / max) : 0}%;background:${max && v > max ? "var(--bad)" : "var(--money)"}"></div></div>`;

state.finTab = "home";
state.finPeriod = 30;
let finMeta = null;

const FIN_TABS = [["home", "Обзор"], ["tx", "Операции"], ["shifts", "Смены"], ["plans", "Платежи"],
                  ["wishes", "Желания"], ["savings", "Копилки"], ["stats", "Статистика"]];

screens.finance = async function renderFinance() {
  [finMeta] = await Promise.all([api("GET", "/fin/meta"), loadHud()]);
  const head = `<div class="h1">Финансы</div>
    <div class="chips" style="margin:12px 0 4px">${FIN_TABS.map(([k, l]) =>
      `<button class="chip ${state.finTab === k ? "on" : ""}" data-act="finTab" data-t="${k}">${l}</button>`).join("")}</div>`;
  const body = await FIN[state.finTab]();
  view.innerHTML = head + body.html;
  if (body.after) body.after();
};
actions.finTab = el => { state.finTab = el.dataset.t; return screens.finance(); };
const reFin = () => screens.finance();

const catOpts = (kind, sel) => (kind === "in" ? finMeta.in : finMeta.out)
  .map(c => `<option value="${c.key}" ${c.key === sel ? "selected" : ""}>${c.emoji} ${esc(c.title)}</option>`).join("");

function txRow(t) {
  const sign = t.kind === "in" ? "+" : t.kind === "out" ? "−" : "";
  const color = t.kind === "in" ? "var(--money)" : "var(--ink)";
  return `<li><span style="font-size:20px">${t.emoji}</span>
    <div class="q-body"><div>${esc(t.note || t.cat_title)}</div><div class="muted small">${ddmm(t.day)} · ${esc(t.cat_title)}${t.in_limit ? "" : t.kind === "out" ? " · вне лимита" : ""}</div></div>
    <b style="color:${color};white-space:nowrap">${sign}${rub(t.amount)}</b>
    ${t.kind !== "move" ? `<button class="btn btn-sm btn-ghost" data-act="txDel" data-id="${t.id}" aria-label="Удалить">✕</button>` : ""}</li>`;
}

const FIN = {};

// ---------- Обзор ----------
FIN.home = async () => {
  const o = await api("GET", "/fin/overview");
  const lim = o.daily_limit, spent = o.spent_today;
  let html = `<div class="wallet"><div class="stat-label">Свободно</div><div class="wallet-num">${rub(o.balance)}</div>
      <div class="muted small">месяц: <span style="color:var(--money)">${rub(o.month_in, true)}</span> / −${rub(o.month_out)}</div></div>
    <form class="row" data-submit="finQuick" style="margin:14px 0">
      <input class="input" name="text" maxlength="100" placeholder="кофе 250 · +5000 монтаж" required>
      <button class="btn btn-accent" type="submit">＋</button></form>
    <div class="tiles">
      <div class="tile"><div class="stat-label">Сегодня</div><div class="stat-value" style="${lim && spent > lim ? "color:var(--bad)" : ""}">${rub(spent)}</div>
        <div class="stat-sub">${lim ? `лимит ${rub(lim)}${o.limit_streak ? ` · 🛡 ${o.limit_streak} дн` : ""}` : "лимит не задан"}</div>${lim ? bar(spent, lim) : ""}</div>
      <div class="tile"><div class="stat-label">Ждём зарплату</div><div class="stat-value" style="color:var(--accent)">${rub(o.expected_salary)}</div>
        <div class="stat-sub">${o.companies_owed.map(c => esc(c.company)).join(", ") || "все выплатили"}</div></div>
      <div class="tile"><div class="stat-label">Копилки</div><div class="stat-value">${rub(o.savings_total)}</div><div class="stat-sub">накопления и вложения</div></div>
      <div class="tile"><div class="stat-label">На желания</div><div class="stat-value">${rub(o.wishes_saved)}</div><div class="stat-sub">${o.wishes.length} в карте</div></div>
    </div>`;
  const soon = o.plans_soon.filter(p => p.days_left <= 7);
  if (soon.length) {
    html += `<div class="h2">Скоро платить</div>` + soon.map(planCard).join("");
  }
  html += `<div class="h2">Последние операции</div>` +
    (o.recent.length ? `<ul class="list-plain card">${o.recent.filter(t => t.kind !== "move").slice(0, 10).map(txRow).join("")}</ul>`
                     : `<div class="empty small">Пусто. Запиши трату строкой выше или в боте: «кофе 250».</div>`);
  html += `<details class="card" style="margin-top:18px"><summary>⚙ Настройки финансов</summary>
    <form data-submit="finSettings">
      <label class="field"><span>Лимит трат в день, ₽ (0 — без лимита)</span><input class="input" name="limit" type="number" min="0" step="1" inputmode="numeric" value="${finMeta.daily_limit / 100}"></label>
      <label class="field"><span>Сколько денег было на старте, ₽</span><input class="input" name="start" type="number" step="0.01" inputmode="decimal" value="${finMeta.start_balance / 100}"></label>
      <label class="field"><span>Типы работы для смен (через запятую)</span><input class="input" name="types" value="${esc(finMeta.work_types.join(", "))}"></label>
      <p class="muted small">В лимит не считаются плановые платежи, покупки желаний и переводы в копилки.</p>
      <button class="btn btn-accent wide" type="submit">Сохранить</button></form></details>`;
  return { html };
};
actions.finQuick = async form => {
  const t = await api("POST", "/fin/quick", { text: form.text.value });
  toast(`${t.kind === "in" ? "💵 +" : "💸 −"}${rub(t.amount)} · ${t.emoji} ${esc(t.cat_title)}`);
  await reFin();
};
actions.txDel = async el => {
  if (!confirm("Удалить операцию?")) return;
  await api("DELETE", "/fin/tx/" + el.dataset.id);
  await reFin();
};
actions.finSettings = async form => {
  await api("PUT", "/fin/settings", {
    daily_limit: Number(form.limit.value) || 0, start_balance: Number(form.start.value) || 0,
    work_types: form.types.value.split(",").map(s => s.trim()).filter(Boolean),
  });
  toast("Сохранено");
  await reFin();
};

// ---------- Операции ----------
FIN.tx = async () => {
  const t = state.meta.today;
  const list = await api("GET", `/fin/tx?start=${addDays(t, -state.finPeriod + 1)}&end=${t}`);
  const k = state.txKind || "out";
  let html = `<form class="card" data-submit="txAdd">
      <div class="chips" style="margin-bottom:12px">
        <button type="button" class="chip ${k === "out" ? "on" : ""}" data-act="txKind" data-k="out">💸 Трата</button>
        <button type="button" class="chip ${k === "in" ? "on" : ""}" data-act="txKind" data-k="in">💵 Доход</button></div>
      <div class="row"><input class="input" name="amount" type="number" min="0.01" step="0.01" inputmode="decimal" placeholder="Сумма, ₽" required style="flex:1">
        <input class="input" name="day" type="date" value="${t}" max="${t}" style="width:150px"></div>
      <label class="field" style="margin-top:10px"><span>Категория</span><select class="input" name="category"><option value="">Угадать по описанию</option>${catOpts(k)}</select></label>
      <label class="field"><span>Описание</span><input class="input" name="note" maxlength="200" placeholder="${k === "in" ? "монтаж ролика" : "кофе"}"></label>
      <button class="btn btn-accent wide" type="submit">Добавить</button></form>
    <div class="row" style="margin-top:14px"><div class="h3" style="margin:0">За ${state.finPeriod} дней</div><span class="spacer"></span>
      <div class="chips">${[7, 30, 90].map(n => `<button class="chip ${state.finPeriod === n ? "on" : ""}" data-act="finPeriod" data-n="${n}">${n} дн</button>`).join("")}</div></div>`;
  const shown = list.filter(x => x.kind !== "move");
  html += shown.length ? `<ul class="list-plain card" style="margin-top:8px">${shown.map(txRow).join("")}</ul>` : `<div class="empty small" style="margin-top:8px">Операций нет</div>`;
  return { html };
};
actions.txKind = el => { state.txKind = el.dataset.k; return reFin(); };
actions.finPeriod = el => { state.finPeriod = Number(el.dataset.n); return reFin(); };
actions.txAdd = async form => {
  await api("POST", "/fin/tx", { kind: state.txKind || "out", amount: Number(form.amount.value), category: form.category.value || null,
                                 note: form.note.value, day: form.day.value });
  toast("Записано");
  await reFin();
};

// ---------- Смены ----------
FIN.shifts = async () => {
  const d = await api("GET", "/fin/shifts");
  const t = state.meta.today;
  let html = `<div class="wallet" style="padding-top:8px"><div class="stat-label">Ждём зарплату</div><div class="wallet-num" style="color:var(--accent)">${rub(d.expected)}</div></div>`;
  if (d.companies.length) {
    html += `<div class="h2">По компаниям</div>` + d.companies.map(c => `<div class="card">
      <div class="row"><b style="font-size:17px">${esc(c.company)}</b><span class="spacer"></span>
        ${c.owed ? `<button class="btn btn-sm btn-accent" data-act="compPay" data-c="${esc(c.company)}">Оплатили всё</button>` : `<span class="tag" style="color:var(--good)">✓ всё выплачено</span>`}</div>
      <div class="tiles" style="margin-top:10px;grid-template-columns:repeat(4,1fr)">
        <div><div class="stat-label">Смен</div><b>${c.shifts}</b></div>
        <div><div class="stat-label">Часов</div><b>${fmt(Math.round(c.hours * 10) / 10)}</b></div>
        <div><div class="stat-label">Заработано</div><b>${rub(c.earned)}</b></div>
        <div><div class="stat-label">Должны</div><b style="color:${c.owed ? "var(--accent)" : "var(--muted)"}">${rub(c.owed)}</b></div></div>
      ${c.owed ? `<div class="muted small" style="margin-top:6px">ждём с ${ddmm(c.oldest_unpaid)}</div>` : ""}</div>`).join("");
  }
  html += `<details class="card" ${d.shifts.length ? "" : "open"} style="margin-top:14px"><summary>＋ Записать смену</summary>
    <form data-submit="shiftAdd">
      <div class="row"><label class="field" style="flex:1"><span>Дата</span><input class="input" type="date" name="day" value="${t}"></label>
        <label class="field" style="flex:1"><span>Тип работы</span><select class="input" name="type">${d.work_types.map(w => `<option>${esc(w)}</option>`).join("")}</select></label></div>
      <label class="field"><span>Компания</span><input class="input" name="company" list="companies" maxlength="60" required value="${esc(d.recent_companies[0] || "")}">
        <datalist id="companies">${d.recent_companies.map(c => `<option value="${esc(c)}">`).join("")}</datalist></label>
      <div class="row"><label class="field" style="flex:1"><span>Часы</span><input class="input" name="hours" type="number" step="0.5" min="0" inputmode="decimal" placeholder="8"></label>
        <label class="field" style="flex:1"><span>Ставка ₽/ч</span><input class="input" name="rate" type="number" min="0" inputmode="decimal" placeholder="400"></label>
        <label class="field" style="flex:1"><span>или сумма ₽</span><input class="input" name="amount" type="number" min="0" inputmode="decimal" placeholder="3200"></label></div>
      <label class="field"><span>Заметка</span><input class="input" name="note" maxlength="200" placeholder="необязательно"></label>
      <button class="btn btn-accent wide" type="submit">Записать</button></form></details>`;
  if (d.shifts.length) {
    html += `<div class="h2">Смены</div><ul class="list-plain card">` + d.shifts.map(s => `<li>
      <div class="q-body"><div>${ddmm(s.day)} · <b>${esc(s.company)}</b> · ${esc(s.work_type)}</div>
        <div class="muted small">${s.hours ? `${fmt(s.hours)}ч × ${rub(s.rate)} · ` : ""}${s.paid ? `оплачено ${ddmm(s.paid_day)}` : "ждём оплату"}${s.note ? " · " + esc(s.note) : ""}</div></div>
      <b style="white-space:nowrap;color:${s.paid ? "var(--money)" : "var(--accent)"}">${rub(s.amount)}</b>
      <button class="btn btn-sm ${s.paid ? "btn-ghost" : ""}" data-act="shiftPay" data-id="${s.id}" data-paid="${s.paid}" aria-label="${s.paid ? "Отменить оплату" : "Оплачено"}">${s.paid ? "↩" : "💰"}</button>
      <button class="btn btn-sm btn-ghost" data-act="shiftDel" data-id="${s.id}" aria-label="Удалить">✕</button></li>`).join("") + `</ul>`;
  }
  return { html };
};
actions.shiftAdd = async form => {
  const amount = Number(form.amount.value) || null, hours = Number(form.hours.value) || null, rate = Number(form.rate.value) || null;
  if (!amount && !(hours && rate)) throw new Error("Укажи сумму или часы и ставку");
  await api("POST", "/fin/shifts", { day: form.day.value, company: form.company.value, work_type: form.type.value,
                                     amount, hours, rate, note: form.note.value });
  toast("💼 Смена записана");
  await reFin();
};
actions.shiftPay = async el => {
  await api("PATCH", "/fin/shifts/" + el.dataset.id, { action: el.dataset.paid === "1" ? "unpay" : "pay" });
  await reFin();
};
actions.shiftDel = async el => {
  if (!confirm("Удалить смену?")) return;
  await api("DELETE", "/fin/shifts/" + el.dataset.id);
  await reFin();
};
actions.compPay = async el => {
  if (!confirm(`${el.dataset.c} оплатили все смены?`)) return;
  const r = await api("POST", "/fin/companies/pay", { company: el.dataset.c });
  splash("Зарплата пришла", `+${rub(r.total)}`, "level");
  celebrate(r);
  await reFin();
};

// ---------- Платежи ----------
function planCard(p) {
  const rep = { none: "", week: " · 🔁 каждую неделю", month: " · 🔁 каждый месяц" }[p.repeat];
  const when = p.days_left < 0 ? `⚠️ просрочено на ${-p.days_left} дн` : p.days_left === 0 ? "сегодня" : p.days_left === 1 ? "завтра" : `${ddmm(p.due)}, через ${p.days_left} дн`;
  return `<div class="card item">
    <span style="font-size:22px">${p.emoji}</span>
    <div class="q-body"><div class="q-title">${esc(p.title)}</div><div class="muted small">${when}${rep}</div></div>
    <div class="price" style="color:var(--ink)">${rub(p.amount)}</div>
    <button class="btn btn-sm btn-accent" data-act="planPay" data-id="${p.id}">Оплатил</button>
    <button class="btn btn-sm btn-ghost" data-act="planDel" data-id="${p.id}" aria-label="Удалить">✕</button></div>`;
}
FIN.plans = async () => {
  const ps = await api("GET", "/fin/plans");
  const total = ps.filter(p => p.days_left <= 30).reduce((s, p) => s + p.amount, 0);
  let html = `<p class="muted small">Оплатил — нажми «Оплатил»: трата запишется сама (вне дневного лимита), повторяющийся платёж переедет на следующий срок. Бот напомнит накануне.</p>`;
  if (ps.length) html += `<div class="row small" style="margin-bottom:8px"><span>В ближайшие 30 дней:</span><b>${rub(total)}</b></div>` + ps.map(planCard).join("");
  else html += `<div class="empty small">Платежей нет</div>`;
  html += `<form class="card" data-submit="planAdd" style="margin-top:14px"><div class="h3">＋ Новый платёж</div>
    <label class="field"><span>Что</span><input class="input" name="title" maxlength="100" placeholder="VPS, подписка, подарок…" required></label>
    <div class="row"><label class="field" style="flex:1"><span>Сумма ₽</span><input class="input" name="amount" type="number" min="1" step="0.01" inputmode="decimal" required></label>
      <label class="field" style="flex:1"><span>Когда</span><input class="input" name="due" type="date" value="${addDays(state.meta.today, 1)}" required></label></div>
    <div class="row"><label class="field" style="flex:1"><span>Повтор</span><select class="input" name="repeat"><option value="none">Разово</option><option value="month">Каждый месяц</option><option value="week">Каждую неделю</option></select></label>
      <label class="field" style="flex:1"><span>Категория</span><select class="input" name="category">${catOpts("out", "subs")}</select></label></div>
    <button class="btn btn-accent wide" type="submit">Добавить</button></form>`;
  return { html };
};
actions.planAdd = async form => {
  await api("POST", "/fin/plans", { title: form.title.value, amount: Number(form.amount.value), due: form.due.value,
                                    repeat: form.repeat.value, category: form.category.value });
  toast("📅 Добавлено");
  await reFin();
};
actions.planPay = async el => { await api("POST", `/fin/plans/${el.dataset.id}/pay`); toast("✅ Оплачено"); await reFin(); };
actions.planDel = async el => { if (confirm("Удалить платёж?")) { await api("DELETE", "/fin/plans/" + el.dataset.id); await reFin(); } };

// ---------- Желания ----------
FIN.wishes = async () => {
  const d = await api("GET", "/fin/wishes");
  let html = `<p class="muted small">Свободно: <b>${rub(d.balance)}</b>. Отложенное на желания не считается свободными деньгами.</p>`;
  const active = d.wishes.filter(w => !w.done), done = d.wishes.filter(w => w.done);
  html += active.length ? active.map(w => `<div class="card">
      <div class="row"><b style="font-size:17px">🎯 ${esc(w.title)}</b><span class="spacer"></span><b>${w.progress}%</b></div>
      <div style="margin:10px 0 6px">${bar(w.saved, w.target)}</div>
      <div class="row small"><span>${rub(w.saved)} из ${rub(w.target)}</span><span class="spacer"></span><span class="muted">осталось ${rub(Math.max(0, w.target - w.saved))}</span></div>
      <div class="row wrap" style="margin-top:10px">
        <button class="btn btn-sm btn-accent" data-act="wishMoney" data-id="${w.id}" data-s="1">＋ Отложить</button>
        ${w.saved ? `<button class="btn btn-sm" data-act="wishMoney" data-id="${w.id}" data-s="-1">− Забрать</button>` : ""}
        ${w.saved >= w.target ? `<button class="btn btn-sm btn-good" data-act="wishDone" data-id="${w.id}">✓ Купил!</button>` : ""}
        <span class="spacer"></span><button class="btn btn-sm btn-ghost" data-act="wishDel" data-id="${w.id}" aria-label="Удалить">✕</button></div></div>`).join("")
    : `<div class="empty small">Карта желаний пуста</div>`;
  html += `<form class="card" data-submit="wishAdd" style="margin-top:14px"><div class="h3">＋ Новое желание</div>
    <div class="row"><input class="input" name="title" maxlength="100" placeholder="Наушники" required style="flex:2">
      <input class="input" name="target" type="number" min="1" inputmode="decimal" placeholder="Цена ₽" required style="flex:1"></div>
    <button class="btn btn-accent wide" type="submit" style="margin-top:10px">Добавить</button></form>`;
  if (done.length) html += `<div class="h2">Исполнено</div>` + done.map(w => `<div class="card item bought"><div class="q-body"><div class="q-title">🌠 ${esc(w.title)}</div><div class="muted small">${ddmm(w.done_day)}</div></div><div class="price">${rub(w.target)}</div></div>`).join("");
  return { html };
};
actions.wishAdd = async form => { await api("POST", "/fin/wishes", { title: form.title.value, target: Number(form.target.value) }); await reFin(); };
actions.wishMoney = async el => {
  const v = prompt(el.dataset.s === "1" ? "Сколько отложить, ₽?" : "Сколько забрать обратно, ₽?");
  if (!v) return;
  await api("POST", `/fin/wishes/${el.dataset.id}/money`, { amount: Number(v.replace(",", ".")) * Number(el.dataset.s) });
  await reFin();
};
actions.wishDone = async el => {
  if (!confirm("Купил? Отложенные деньги запишутся как покупка.")) return;
  const r = await api("POST", `/fin/wishes/${el.dataset.id}/done`);
  splash("Мечта сбылась", r.wish.title, "level");
  celebrate(r);
  await reFin();
};
actions.wishDel = async el => { if (confirm("Удалить желание? Отложенное вернётся в свободные деньги.")) { await api("DELETE", "/fin/wishes/" + el.dataset.id); await reFin(); } };

// ---------- Копилки ----------
FIN.savings = async () => {
  const d = await api("GET", "/fin/savings");
  const total = d.savings.reduce((s, x) => s + x.current, 0);
  let html = `<div class="wallet" style="padding-top:8px"><div class="stat-label">Накопления и вложения</div><div class="wallet-num">${rub(total)}</div>
    <div class="muted small">свободно ещё ${rub(d.balance)}</div></div>`;
  html += d.savings.map(s => `<div class="card">
    <div class="row"><b style="font-size:17px">${s.kind === "invest" ? "📈" : "🏦"} ${esc(s.title)}</b><span class="spacer"></span><b style="font-size:18px">${rub(s.current)}</b></div>
    ${s.kind === "invest" ? `<div class="muted small" style="margin-top:4px">вложено ${rub(s.invested)} · <span style="color:${s.profit >= 0 ? "var(--good)" : "var(--bad)"}">${rub(s.profit, true)}</span>${s.value_day ? ` · оценка от ${ddmm(s.value_day)}` : ""}</div>` : ""}
    <div class="row wrap" style="margin-top:10px">
      <button class="btn btn-sm btn-accent" data-act="savMove" data-id="${s.id}" data-s="1">＋ Пополнить</button>
      <button class="btn btn-sm" data-act="savMove" data-id="${s.id}" data-s="-1">− Снять</button>
      ${s.kind === "invest" ? `<button class="btn btn-sm" data-act="savValue" data-id="${s.id}">📊 Стоимость</button>` : ""}
      <span class="spacer"></span>${s.current === 0 ? `<button class="btn btn-sm btn-ghost" data-act="savDel" data-id="${s.id}" aria-label="Убрать">✕</button>` : ""}</div></div>`).join("") ||
    `<div class="empty small">Копилок нет. Заведи «Подушку» или «Вклад», а для акций и крипты — вложение.</div>`;
  html += `<form class="card" data-submit="savAdd" style="margin-top:14px"><div class="h3">＋ Новая копилка</div>
    <div class="row"><input class="input" name="title" maxlength="60" placeholder="Подушка безопасности" required style="flex:2">
      <select class="input" name="kind" style="flex:1"><option value="saving">🏦 Накопление</option><option value="invest">📈 Вложение</option></select></div>
    <button class="btn btn-accent wide" type="submit" style="margin-top:10px">Создать</button></form>`;
  return { html };
};
actions.savAdd = async form => { await api("POST", "/fin/savings", { title: form.title.value, kind: form.kind.value }); await reFin(); };
actions.savMove = async el => {
  const v = prompt(el.dataset.s === "1" ? "Сколько положить, ₽?" : "Сколько снять, ₽?");
  if (!v) return;
  await api("POST", `/fin/savings/${el.dataset.id}/move`, { amount: Number(v.replace(",", ".")) * Number(el.dataset.s) });
  await reFin();
};
actions.savValue = async el => {
  const v = prompt("Сколько вложение стоит сейчас, ₽?");
  if (!v) return;
  await api("POST", `/fin/savings/${el.dataset.id}/value`, { amount: Number(v.replace(",", ".")) });
  await reFin();
};
actions.savDel = async el => { if (confirm("Убрать копилку?")) { await api("DELETE", "/fin/savings/" + el.dataset.id); await reFin(); } };

// ---------- Статистика ----------
function statRange() {
  const t = state.meta.today, p = state.statPeriod || "month";
  if (p === "week") return [addDays(t, -6), t];
  if (p === "month") return [t.slice(0, 8) + "01", t];
  if (p === "prev") { const d = parseDay(t.slice(0, 8) + "01"); d.setDate(0); const end = isoDay(d); return [end.slice(0, 8) + "01", end]; }
  if (p === "3m") return [addDays(t, -89), t];
  return [state.statStart || addDays(t, -29), state.statEnd || t];
}
FIN.stats = async () => {
  const [start, end] = statRange();
  const s = await api("GET", `/fin/stats?start=${start}&end=${end}`);
  const P = [["week", "7 дней"], ["month", "Этот месяц"], ["prev", "Прошлый"], ["3m", "3 месяца"], ["custom", "Свой"]];
  let html = `<div class="chips" style="margin-bottom:10px">${P.map(([k, l]) => `<button class="chip ${(state.statPeriod || "month") === k ? "on" : ""}" data-act="statPeriod" data-p="${k}">${l}</button>`).join("")}</div>`;
  if ((state.statPeriod || "month") === "custom") {
    html += `<div class="row" style="margin-bottom:10px"><input class="input" type="date" data-input="statStart" value="${start}"><input class="input" type="date" data-input="statEnd" value="${end}"></div>`;
  }
  html += `<div class="muted small" style="margin-bottom:8px">${ddmm(s.start)} — ${ddmm(s.end)}</div>
    <div class="tiles">
      <div class="tile"><div class="stat-label">Доходы</div><div class="stat-value" style="color:var(--money)">${rub(s.income)}</div></div>
      <div class="tile"><div class="stat-label">Расходы</div><div class="stat-value">${rub(s.expense)}</div><div class="stat-sub">≈ ${rub(s.avg_day_out)} в день</div></div>
      <div class="tile"><div class="stat-label">Итог</div><div class="stat-value" style="color:${s.net >= 0 ? "var(--good)" : "var(--bad)"}">${rub(s.net, true)}</div></div>
      <div class="tile"><div class="stat-label">Смены</div><div class="stat-value" style="color:var(--accent)">${rub(s.shifts_total)}</div><div class="stat-sub">${s.shifts.reduce((a, x) => a + x.n, 0)} шт.</div></div>
    </div>
    <div class="h2">Траты по дням</div><div id="fin-days"></div>`;
  const outs = s.by_category.filter(c => c.kind === "out"), ins = s.by_category.filter(c => c.kind === "in");
  const hb = (rows, total) => rows.map(c => `<div class="hbar" data-tip="${esc(`${c.title}: <b>${rub(c.sum)}</b> · ${c.count} опер. · ${total ? Math.round((100 * c.sum) / total) : 0}%`)}">
      <div class="hbar-name">${c.emoji} ${esc(c.title)}</div><div class="hbar-track"><div class="hbar-fill" style="width:${(100 * c.sum) / Math.max(1, rows[0].sum)}%"></div></div>
      <div class="hbar-val" style="width:auto">${rub(c.sum)}</div></div>`).join("");
  html += `<div class="h2">Куда ушли деньги</div>` + (outs.length ? hb(outs, s.expense) : `<div class="muted small">Трат нет</div>`);
  html += `<div class="h2">Откуда пришли</div>` + (ins.length ? hb(ins, s.income) : `<div class="muted small">Доходов нет</div>`);
  if (s.shifts.length) {
    html += `<div class="h2">Смены по компаниям</div><ul class="list-plain card">` + s.shifts.map(c => `<li><div class="q-body"><b>${esc(c.company)}</b><div class="muted small">${c.n} ${plural(c.n, "смена", "смены", "смен")}${c.h ? ` · ${fmt(c.h)} ч` : ""}</div></div><b>${rub(c.s)}</b></li>`).join("") + `</ul>`;
  }
  return {
    html,
    after() {
      const days = s.days;
      barChart($("#fin-days"), {
        labels: days.map(d => String(parseDay(d.day).getDate())),
        values: days.map(d => Math.round(d.out / 100)),
        tips: days.map(d => `${WD_SHORT[parseDay(d.day).getDay()]} ${ddmm(d.day)}: <b>${rub(d.out)}</b>${d.in ? ` · доход ${rub(d.in)}` : ""}`),
        showEvery: Math.max(1, Math.ceil(days.length / 8)),
      });
    },
  };
};
actions.statPeriod = el => { state.statPeriod = el.dataset.p; return reFin(); };
actions.statStart = el => { if (el.value) { state.statStart = el.value; reFin().catch(toastErr); } };
actions.statEnd = el => { if (el.value) { state.statEnd = el.value; reFin().catch(toastErr); } };
