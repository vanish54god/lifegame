/* LifeGame — вкладка «Финансы». Использует общие функции из app.js (api, esc, toast, barChart…). */
"use strict";

function rub(k, sign = false) {
  if (k == null) return "—";
  const s = k < 0 ? "−" : sign && k > 0 ? "+" : "";
  return s + (Math.abs(k) / 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + " ₽";
}
const rubR = (k, sign = false) => rub(Math.round(k / 100) * 100, sign);   // без копеек — для конвертов
const bar = (v, max) => `<div class="dayprog-bar"><div class="dayprog-fill" style="width:${max ? Math.min(100, (100 * v) / max) : 0}%;background:${max && v > max ? "var(--bad)" : "var(--money)"}"></div></div>`;

state.finTab = "home";
state.finPeriod = 30;
let finMeta = null;

const FIN_TABS = [["home", "Обзор"], ["plans", "📅 Обязательное"], ["env", "Конверты"], ["tx", "Операции"], ["shifts", "Смены"],
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
    ${t.kind === "out" && t.source === "manual" && t.envelope ? `<button class="btn btn-sm btn-ghost" data-act="txEnv" data-id="${t.id}" data-env="${t.envelope === "oblig" && t.slot ? t.slot : t.envelope}" title="Откуда: ${esc(t.env_title)} (нажми, чтобы сменить)">${t.env_emoji}</button>` : ""}
    <b style="color:${color};white-space:nowrap">${sign}${rub(t.amount)}</b>
    ${t.kind !== "move" && t.source === "manual" ? `<label class="btn btn-sm btn-ghost tx-date" aria-label="Изменить дату">📅<input type="date" data-input="txDay" data-id="${t.id}" value="${t.day}" max="${state.meta.today}"></label>` : ""}
    ${t.kind !== "move" ? `<button class="btn btn-sm btn-ghost" data-act="txDel" data-id="${t.id}" aria-label="Удалить">✕</button>` : ""}</li>`;
}

const FIN = {};

// ---------- Обзор ----------
function obLine(e) {
  if (!e.oblig_total) return `<div class="small muted" style="margin-top:4px">📅 Обязательных платежей пока нет — добавь во вкладке «📅 Обязательное»</div>`;
  const dots = "🟢".repeat(e.oblig_green) + (e.oblig_late ? "🔴".repeat(e.oblig_late) : "") + "🟡".repeat(Math.max(0, e.oblig_total - e.oblig_green - e.oblig_late));
  return `<div class="ob-status small" data-act="finTab" data-t="plans" style="cursor:pointer">
    <span class="ob-dots">${dots}</span>
    ${e.oblig_gap ? `<span style="color:var(--bad)">📅 До следующих денег не хватает <b>${rubR(e.oblig_gap)}</b></span>`
     : e.oblig_late ? `<span style="color:var(--bad)">📅 ${e.oblig_late} отстаёт от графика — бот догоняет</span>`
                  : `<span style="color:var(--good)">📅 Обязательное под контролем · ${e.oblig_green} из ${e.oblig_total}</span>`}</div>`;
}

function envCard(e) {
  const E = e.envs;
  let html = "";
  if (e.on) {
    const left = e.left_today, nxt = e.next_income;
    const until = nxt ? `до ${ddmm(nxt.next)} (${esc(nxt.title)}) — ${e.days_left} дн` : `горизонт ${e.days_left} дн`;
    html += `<div class="budget-card">
      <div class="row"><div class="stat-label">Можно сегодня</div><span class="spacer"></span>${e.streak ? `<span class="tag">🛡 ${e.streak} дн в лимите</span>` : ""}</div>
      <div class="wallet-num" style="text-align:left;${left < 0 ? "color:var(--bad)" : ""}">${rubR(Math.max(0, left))}</div>
      <div class="muted small">${left < 0 ? `больше лимита на ${rubR(-left)} · ` : ""}потрачено ${rubR(e.spent_today)} из ${rubR(e.limit)} · ${until}</div>
      <div style="margin:8px 0">${bar(e.spent_today, Math.max(e.limit, 1))}</div>
      <div class="small">${e.forecast >= 0 ? `🔮 К следующим деньгам останется ~<b>${rubR(e.forecast)}</b>` : `⚠️ В текущем темпе не хватит <b>${rubR(-e.forecast)}</b> — притормози`}</div>
      ${obLine(e)}
      <div class="env-row">${["oblig", "me", "rel", "want"].map(k => `<div class="env"><span>${E[k].emoji}</span><b>${rubR(e.balances[k])}</b><span class="muted">${esc(E[k].title)}</span></div>`).join("")}</div>
      ${e.saved_month > 0 ? `<div class="small muted" style="margin-top:6px">🏦 В копилку за месяц: ${rubR(e.saved_month)}</div>` : ""}
    </div>`;
  } else {
    html += `<div class="budget-card"><div class="h3" style="color:var(--ink)">💌 Конверты</div>
      <p class="small muted" style="margin:4px 0 0">Пришли деньги → сначала 📅 обязательные платежи, потом 🏦 копилка, остальное по конвертам 🧍 Я · ❤️ Отношения · 🎯 Хотелки.
      Лимит на день будет считаться сам до следующих денег, а день в лимите даёт +20 XP.</p>
      ${e.unallocated <= 0 ? `<p class="small" style="margin:8px 0 0">👉 Сначала укажи, сколько денег у тебя сейчас: ниже, в «⚙ Настройки финансов» → «Сколько денег было на старте». Или просто запиши следующий доход — его и разложим.</p>` : ""}</div>`;
  }
  if (e.on && e.unallocated < 0) {
    html += `<div class="card" style="border-color:var(--bad);margin-top:10px"><b>⚠️ В конвертах больше денег, чем есть на самом деле</b>
      <p class="small muted" style="margin:6px 0 10px">Разница ${rubR(-e.unallocated)}. Так бывает, если «стартовый баланс» указан неточно или что-то записано мимо конвертов.
      Поправь стартовый баланс в настройках ниже или пересчитай конверты: деньги вернутся в «неразложенные», и ты разложишь их заново.</p>
      <button class="btn btn-sm" data-act="envReset">↺ Пересчитать конверты</button></div>`;
  }
  if (e.plan) {
    const p = e.plan;
    html += `<div class="card alloc"><div class="row"><b>📥 Не разложено: ${rubR(e.unallocated)}</b></div>
      <div class="alloc-parts small">${p.oblig_now ? `<span>📅 ${rubR(p.oblig_now)}</span>` : ""}${p.funds ? `<span>🎁 ${rubR(p.funds)}</span>` : ""}${p.sched ? `<span title="Копим на далёкие платежи">📆 ${rubR(p.sched)}</span>` : ""}${p.ahead ? `<span title="На следующие платежи">⏭ ${rubR(p.ahead)}</span>` : ""}${p.save ? `<span>🏦 ${rubR(p.save)}</span>` : ""}
        <span>🧍 ${rubR(p.me)}</span><span>❤️ ${rubR(p.rel)}</span><span>🎯 ${rubR(p.want)}</span></div>
      ${p.funds_short ? `<div class="small muted" style="margin:6px 0">🎁 Фондам недодам ${rubR(p.funds_short)} — чтобы осталось на жизнь. Догонят со следующих денег.</div>` : ""}
      <button class="btn btn-accent wide" data-act="envApply">💌 Разложить</button></div>`;
  }
  return html;
}
actions.envReset = async () => {
  if (!confirm("Обнулить конверты? Все деньги вернутся в «неразложенные», и их можно будет разложить заново.")) return;
  await api("POST", "/fin/envelopes/reset");
  toast("↺ Конверты обнулены — разложи заново");
  await reFin();
};
actions.envApply = async () => {
  const r = await api("POST", "/fin/envelopes/apply", {});
  splash("Разложено", rub(r.amount), "level");
  celebrate(r);
  await reFin();
};

FIN.home = async () => {
  const [o, e] = await Promise.all([api("GET", "/fin/overview"), api("GET", "/fin/envelopes")]);
  for (const r of e.rewards || []) toast(`💰 ${ddmm(r.day)} в лимите · сэкономил ${rub(r.saved)} · +20 XP`, "ach");
  const lim = e.on ? e.limit : o.daily_limit, spent = e.on ? e.spent_today : o.spent_today;
  const inEnv = e.on ? Object.values(e.balances).reduce((a, b) => a + b, 0) : 0;
  let html = envCard(e) + `<div class="wallet" style="padding-top:12px"><div class="stat-label">На руках</div><div class="wallet-num" style="font-size:34px">${rubR(o.balance)}</div>
      <div class="muted small">${e.on ? `в конвертах ${rubR(inEnv)} · не разложено ${rubR(e.unallocated)} · ` : ""}месяц: <span style="color:var(--money)">${rubR(o.month_in, true)}</span> / −${rubR(o.month_out)}</div>
      <div class="muted small">Копилки и деньги на желания сюда не входят — они отложены отдельно.</div></div>
    <form class="row" data-submit="finQuick" style="margin:14px 0">
      <input class="input" name="text" maxlength="100" placeholder="кофе 250 · +5000 монтаж" required>
      <select class="input" name="day" style="width:auto;flex:none" aria-label="Когда">
        <option value="">Сегодня</option><option value="${addDays(state.meta.today, -1)}">Вчера</option>
        <option value="${addDays(state.meta.today, -2)}">Позавчера</option></select>
      <button class="btn btn-accent" type="submit">＋</button></form>
    <div class="tiles">
      ${e.on ? "" : `<div class="tile"><div class="stat-label">Сегодня</div><div class="stat-value" style="${lim && spent > lim ? "color:var(--bad)" : ""}">${rub(spent)}</div>
        <div class="stat-sub">${lim ? `лимит ${rub(lim)}${o.limit_streak ? ` · 🛡 ${o.limit_streak} дн` : ""}` : "лимит не задан"}</div>${lim ? bar(spent, lim) : ""}</div>`}
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
      <label class="field"><span>Фиксированный лимит в день, ₽ (0 — без лимита; с конвертами считается сам)</span><input class="input" name="limit" type="number" min="0" step="1" inputmode="numeric" value="${finMeta.daily_limit / 100}"></label>
      <label class="field"><span>Сколько денег было на старте, ₽</span><input class="input" name="start" type="number" step="0.01" inputmode="decimal" value="${finMeta.start_balance / 100}"></label>
      <label class="field"><span>Типы работы для смен (через запятую)</span><input class="input" name="types" value="${esc(finMeta.work_types.join(", "))}"></label>
      <p class="muted small">В лимит не считаются плановые платежи, покупки желаний и переводы в копилки.</p>
      <button class="btn btn-accent wide" type="submit">Сохранить</button></form></details>`;
  return { html };
};
actions.finQuick = async form => {
  const t = await api("POST", "/fin/quick", { text: form.text.value, day: form.day.value || null });
  toast(`${t.kind === "in" ? "💵 +" : "💸 −"}${rub(t.amount)} · ${t.emoji} ${esc(t.cat_title)}${t.day !== state.meta.today ? " · 📅 " + ddmm(t.day) : ""}`);
  await reFin();
};
actions.txEnv = async el => {
  const order = ["me", "rel", "want", ...(finMeta.funds || []).map(f => f.slot)];   // 🧍 → ❤️ → 🎯 → 🎁 фонды
  const next = order[(order.indexOf(el.dataset.env) + 1) % order.length];
  const t = await api("PATCH", "/fin/tx/" + el.dataset.id, { envelope: next });
  toast(`${t.env_emoji} ${esc(t.env_title)}`);
  await reFin();
};
actions.txDay = async el => {
  if (!el.value) return;
  try {
    const t = await api("PATCH", "/fin/tx/" + el.dataset.id, { day: el.value });
    toast("📅 Перенесено на " + ddmm(t.day));
    await reFin();
  } catch (e) { toastErr(e); }
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

// ---------- Конверты ----------
FIN.env = async () => {
  const e = await api("GET", "/fin/envelopes");
  const st = e.settings, E = e.envs, L = e.learned;
  const ob = e.obligations;
  let html = envCard(e);
  html += `<div class="card ob-item ob-${ob.gap ? "late" : ob.total ? "ok" : "progress"}" data-act="finTab" data-t="plans" style="cursor:pointer;margin-top:12px">
      <div class="row"><b>📅 Обязательное и 🎁 фонды</b><span class="spacer"></span><span class="ob-sum">${rubR(ob.reserved)}</span></div>
      <div class="small muted">${ob.total ? `${ob.green} из ${ob.total} закрыто${ob.gap ? ` · до ${ddmm(ob.until)} не хватает ${rubR(ob.gap)}` : ""} · в месяц ~${rubR(ob.month_total)}` : "Пока пусто"} — подробно →</div></div>`;
  html += `
    <div class="h2">Доли конвертов</div>
    <form class="card" data-submit="envSettings">
      <div class="row">${["me", "rel", "want"].map(k => `<label class="field" style="flex:1"><span>${E[k].emoji} ${esc(E[k].title)}, %</span>
        <input class="input" name="${k}" type="number" min="0" max="100" value="${st.shares[k]}"></label>`).join("")}</div>
      ${L ? `<p class="small" style="margin-top:0">🧠 По факту (${L.count} трат с ${ddmm(L.since)}): 🧍 ${L.shares.me}% · ❤️ ${L.shares.rel}% · 🎯 ${L.shares.want}%
        <button type="button" class="btn btn-sm" data-act="envLearn" data-me="${L.shares.me}" data-rel="${L.shares.rel}" data-want="${L.shares.want}">Поставить</button></p>`
        : `<p class="muted small" style="margin-top:0">Через 2–3 недели записей подскажу доли по твоим реальным тратам.</p>`}
      <div class="row">
        <label class="field" style="flex:1"><span>🏦 В копилку, %</span><input class="input" name="save" type="number" min="0" max="80" value="${st.save_pct}"></label>
        <label class="field" style="flex:2"><span>Копилка</span><select class="input" name="target">
          ${e.savings.length ? e.savings.map(x => `<option value="${x.id}" ${x.id === st.save_target ? "selected" : ""}>${esc(x.title)}</option>`).join("") : `<option value="0">«Подушка» (создам сам)</option>`}</select></label></div>
      <label class="field"><span>⏭ С каждых денег — на следующие платежи, % (бот перестанет брать, когда всё с двойным запасом)</span>
        <input class="input" name="ahead" type="number" min="0" max="50" value="${st.ahead_pct}"></label>
      <label class="field"><span>📅 Что закрывать на обязательное сразу</span><select class="input" name="reserve">
        <option value="next" ${st.reserve === "next" ? "selected" : ""}>Только то, что наступит до следующих денег</option>
        <option value="month" ${st.reserve === "month" ? "selected" : ""}>Всё на месяц вперёд (спокойнее, но лимит меньше)</option></select></label>
      <label class="field"><span>Если ожидаемых денег нет — считать лимит на, дней</span><input class="input" name="horizon" type="number" min="3" max="45" value="${st.horizon}"></label>
      <button class="btn btn-accent wide" type="submit">Сохранить</button></form>

    <div class="h2">📆 Ожидаемые деньги</div>
    <p class="muted small">По ближайшей дате считается «до следующих денег» и лимит на день. Ежемесячные сами переезжают на следующий месяц.</p>
    ${e.expected.length ? `<ul class="list-plain card">${e.expected.map(x => `<li><div class="q-body"><b>${esc(x.title)}</b>
      <div class="muted small">${ddmm(x.next)} · через ${x.days_left} дн${x.repeat === "month" ? " · 🔁 каждый месяц" : ""}</div></div>
      <b>${rub(x.amount)}</b><button class="btn btn-sm btn-ghost" data-act="expDel" data-id="${x.id}" aria-label="Удалить">✕</button></li>`).join("")}</ul>` : ""}
    <form class="card" data-submit="expAdd">
      <div class="row"><input class="input" name="title" maxlength="60" placeholder="Карманные" required style="flex:2">
        <input class="input" name="amount" type="number" min="1" inputmode="decimal" placeholder="₽" required style="flex:1"></div>
      <div class="row" style="margin-top:10px"><input class="input" name="day" type="date" value="${addDays(state.meta.today, 7)}" required>
        <select class="input" name="repeat"><option value="month">Каждый месяц</option><option value="none">Разово</option></select></div>
      <button class="btn btn-accent wide" type="submit" style="margin-top:10px">Добавить</button></form>

    <div class="h2">↔️ Переложить</div>
    <form class="card row wrap" data-submit="envMove">
      <select class="input" name="src" style="flex:1">${["me", "rel", "want", "oblig"].map(k => `<option value="${k}">${E[k].emoji} ${esc(E[k].title)} · ${rubR(e.balances[k])}</option>`).join("")}</select>
      <span>→</span>
      <select class="input" name="dst" style="flex:1"><option value="save">🏦 Копилка</option>${["me", "rel", "want", "oblig"].map(k => `<option value="${k}">${E[k].emoji} ${esc(E[k].title)}</option>`).join("")}</select>
      <input class="input" name="amount" type="number" min="1" inputmode="decimal" placeholder="₽" required style="width:100px">
      <button class="btn" type="submit">OK</button></form>`;
  return { html };
};
actions.envSettings = async form => {
  const shares = { me: Number(form.me.value), rel: Number(form.rel.value), want: Number(form.want.value) };
  if (shares.me + shares.rel + shares.want !== 100) throw new Error("Доли должны в сумме давать 100%");
  await api("PUT", "/fin/envelopes/settings", { shares, save_pct: Number(form.save.value), horizon: Number(form.horizon.value),
                                                save_target: Number(form.target.value) || 0, reserve: form.reserve.value,
                                                ahead_pct: Number(form.ahead.value) });
  toast("Сохранено");
  await reFin();
};
actions.envLearn = async el => {
  await api("PUT", "/fin/envelopes/settings", { shares: { me: +el.dataset.me, rel: +el.dataset.rel, want: +el.dataset.want } });
  toast("🧠 Доли по факту");
  await reFin();
};
actions.expAdd = async form => {
  await api("POST", "/fin/expected", { title: form.title.value, amount: Number(form.amount.value), day: form.day.value, repeat: form.repeat.value });
  toast("📆 Добавлено");
  await reFin();
};
actions.expDel = async el => { await api("DELETE", "/fin/expected/" + el.dataset.id); await reFin(); };
actions.envMove = async form => {
  await api("POST", "/fin/envelopes/move", { src: form.src.value, dst: form.dst.value, amount: Number(form.amount.value) });
  toast("↔️ Переложено");
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
      ${k === "out" ? `<label class="field"><span>Конверт</span><select class="input" name="envelope"><option value="">По категории</option>
        <option value="me">🧍 Я</option><option value="rel">❤️ Отношения</option><option value="want">🎯 Хотелки</option>
        ${(finMeta.funds || []).map(f => `<option value="${f.slot}">🎁 ${esc(f.title)}</option>`).join("")}</select></label>` : ""}
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
                                 envelope: form.envelope ? form.envelope.value || null : null,
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

// ---------- 📅 Обязательное: платежи и фонды, у каждого свои деньги ----------
const REP_TITLE = { none: "разово", week: "каждую неделю", month: "каждый месяц", month3: "раз в 3 месяца",
                    month6: "раз в полгода", year: "раз в год" };
const repOpts = sel => ["month", "month3", "month6", "year", "week", "none"].map(k =>
  `<option value="${k}" ${k === sel ? "selected" : ""}>${REP_TITLE[k][0].toUpperCase() + REP_TITLE[k].slice(1)}</option>`).join("");
const OB_BADGE = {
  double: "🟢🟢 и на следующий", ok: "🟢 хватает", progress: "🟡 копится", late: "🔴 не хватает",
};
function whenText(days, due) {
  return days < 0 ? `⚠️ просрочено на ${-days} дн` : days === 0 ? "сегодня" : days === 1 ? "завтра" : `${ddmm(due)}, через ${days} дн`;
}
function planCard(p) {      // короткая карточка для «Скоро платить» на обзоре
  return `<div class="card item"><span style="font-size:22px">${p.emoji}</span>
    <div class="q-body"><div class="q-title">${esc(p.title)}</div><div class="muted small">${whenText(p.days_left, p.due)}</div></div>
    <div class="price" style="color:var(--ink)">${rub(p.amount)}</div>
    <button class="btn btn-sm btn-accent" data-act="planPay" data-id="${p.id}">Оплатил</button></div>`;
}
function obCard(i, e) {
  const bar2 = `<div class="dayprog-bar" style="margin:8px 0 6px"><div class="dayprog-fill" style="width:${i.progress}%;background:${i.status === "late" ? "var(--bad)" : i.status === "progress" ? "var(--accent)" : "var(--good)"}"></div></div>`;
  let hint;
  if (i.kind === "plan") {
    const rep = (i.repeat === "none" ? "" : "🔁 ") + REP_TITLE[i.repeat];
    hint = i.status === "double" ? "Оплатишь спокойно — и на следующий раз уже отложено"
      : i.status === "ok" ? (["week", "month"].includes(i.repeat) ? "Оплатишь спокойно · бот понемногу копит на следующий" : "Оплатишь спокойно")
      : i.status === "late" && i.now ? `До ${ddmm(i.due)} не хватает <b>${rubR(i.need)}</b> — бот доложит с ближайших денег, или докинь сам`
      : i.status === "late" ? `Отстаём от графика: к сегодня должно быть ~${rubR(i.expected)}. Бот догоняет — ~${rubR(i.per_week)} в неделю, или докинь сам`
      : `Копится по графику · ~${rubR(i.per_week)} в неделю, бот откладывает сам`;
    hint = `<span class="muted">${whenText(i.days_left, i.due)} · ${rep}</span><br>${hint}`;
  } else {
    hint = i.status === "ok" ? "Набрано! 🎉 Можно тратить"
      : i.status === "late" ? `Не успеваем по графику — нужно ещё <b>${rubR(i.goal_left)}</b>, докинь`
      : `Осталось ${rubR(i.goal_left)} · ~${rubR(i.per_week)} в неделю, бот откладывает сам`;
    hint = `<span class="muted">${whenText(i.days_left, i.due)}${i.repeat === "year" ? " · 🔁 каждый год" : ""}${i.remind ? " · напомню выбрать за 2 недели" : ""}</span><br>${hint}`;
    if (i.spend && i.balance > 0) hint += `<br><span class="muted">Траты «${esc((finMeta.out.find(c => c.key === i.category) || {}).title || "")}» в эти дни спишутся отсюда сами</span>`;
  }
  const open = state.obOpen === i.slot;
  const srcs = [["free", `📥 Неразложенные · ${rubR(e.unallocated)}`], ["me", `🧍 Я · ${rubR(e.balances.me)}`],
                ["rel", `❤️ Отношения · ${rubR(e.balances.rel)}`], ["want", `🎯 Хотелки · ${rubR(e.balances.want)}`]];
  if (e.obligations.buffer > 0) srcs.splice(1, 0, ["buffer", `📅 Общий запас · ${rubR(e.obligations.buffer)}`]);
  return `<div class="card ob-item ob-${i.status}">
    <div class="row"><span style="font-size:22px">${i.emoji}</span>
      <div class="q-body"><div class="q-title">${esc(i.title)}</div></div>
      <span class="ob-badge">${i.status === "late" && !i.now ? "🔴 отстаём" : OB_BADGE[i.status]}</span>
      ${i.kind === "plan" ? `<button class="btn btn-sm btn-ghost" data-act="planEdit" data-id="${i.id}" aria-label="Изменить">✏️</button>` : ""}
      <button class="btn btn-sm btn-ghost" data-act="${i.kind === "plan" ? "planDel" : "fundDel"}" data-id="${i.id}" aria-label="Удалить">✕</button></div>
    <div class="row" style="margin-top:6px"><span class="ob-sum" style="color:${i.status === "late" ? "var(--bad)" : i.status === "progress" ? "var(--ink)" : "var(--good)"}">${rubR(i.balance)}</span>
      <span class="muted small">из ${rubR(i.kind === "plan" ? Math.max(i.amount, i.need_total) : i.target)}${i.kind === "plan" && i.goal > i.amount ? ` · с запасом ${rubR(i.goal)}` : ""}${i.spent ? ` · уже потрачено ${rubR(i.spent)}` : ""}</span></div>
    ${bar2}<div class="small">${hint}</div>
    <div class="row wrap ob-actions">
      ${i.kind === "plan" ? `<button class="btn btn-sm btn-accent" data-act="planPay" data-id="${i.id}">✅ Оплатил</button>` : ""}
      <button class="btn btn-sm" data-act="obOpen" data-slot="${i.slot}">＋ Докинуть</button>
      ${i.balance > 0 ? `<button class="btn btn-sm" data-act="obTake" data-slot="${i.slot}" data-max="${i.balance}">− Забрать</button>` : ""}
</div>
    ${i.kind === "plan" && state.planEdit === i.id ? `<form data-submit="planSave" data-id="${i.id}" style="margin-top:10px">
      <div class="row"><label class="field" style="flex:1"><span>Сумма ₽</span><input class="input" name="amount" type="number" min="1" step="0.01" value="${i.amount / 100}" required></label>
        <label class="field" style="flex:1"><span>Следующая оплата</span><input class="input" name="due" type="date" value="${i.due}" required></label></div>
      <label class="field"><span>Повтор</span><select class="input" name="repeat">${repOpts(i.repeat)}</select></label>
      <button class="btn btn-accent wide" type="submit">Сохранить</button></form>` : ""}
    ${open ? `<form class="row wrap" data-submit="obPut" data-slot="${i.slot}" style="margin-top:10px">
      <select class="input" name="src" style="flex:2;min-width:160px">${srcs.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <input class="input" name="amount" type="number" min="1" inputmode="decimal" placeholder="₽" value="${i.need > 0 ? Math.ceil(i.need / 100) : ""}" required style="flex:1;min-width:80px">
      <button class="btn btn-accent" type="submit">OK</button></form>` : ""}</div>`;
}
FIN.plans = async () => {
  const e = await api("GET", "/fin/envelopes");
  const ob = e.obligations;
  const add = state.obAdd || "plan";
  let html = `<div class="tiles" style="margin-bottom:10px">
      <div class="tile"><div class="stat-label">Под контролем</div><div class="stat-value" style="color:${ob.late ? "var(--bad)" : "var(--good)"}">${ob.green} / ${ob.total}</div>
        <div class="stat-sub">${ob.double ? `🛡 ${ob.double} с двойным запасом` : ob.total ? "зелёные — можно не думать" : "добавь первый платёж"}</div></div>
      <div class="tile"><div class="stat-label">Отложено</div><div class="stat-value">${rubR(ob.reserved)}</div>
        <div class="stat-sub">${ob.gap ? `<span style="color:var(--bad)">до ${ddmm(ob.until)} не хватает ${rubR(ob.gap)}</span>` : `в месяц ~${rubR(ob.month_total)}`}</div></div></div>`;
  if (!e.on) html += `<div class="banner hot small">💌 Конверты ещё не включены — разложи деньги на «Обзоре», и бот начнёт сам откладывать на каждый платёж.</div>`;
  html += `<p class="muted small">С каждых денег бот сам закрывает платежи до следующих денег, кладёт в 🎁 фонды их долю по графику и ещё ${ob.ahead_pct}% — на следующие платежи (пока всё не будет с двойным запасом). Оплатил — жми «Оплатил», деньги спишутся из ячейки платежа.</p>`;
  html += ob.items.length ? ob.items.map(i => obCard(i, e)).join("") : `<div class="empty small">Пусто. Добавь проездной, связь, подписки — и фонды на праздники.</div>`;
  if (ob.buffer > 0) html += `<div class="small muted" style="margin:8px 2px">📅 Свободный запас в «Обязательном»: ${rubR(ob.buffer)} — уйдёт на новые платежи сам</div>`;
  html += `<div class="card" style="margin-top:14px">
    <div class="chips" style="margin-bottom:12px">
      <button class="chip ${add === "plan" ? "on" : ""}" data-act="obAdd" data-k="plan">＋ Платёж</button>
      <button class="chip ${add === "fund" ? "on" : ""}" data-act="obAdd" data-k="fund">＋ 🎁 Фонд</button></div>
    ${add === "plan" ? `<form data-submit="planAdd">
      <label class="field"><span>Что</span><input class="input" name="title" maxlength="100" placeholder="Проездной, связь, VPS…" required></label>
      <div class="row"><label class="field" style="flex:1"><span>Сумма ₽</span><input class="input" name="amount" type="number" min="1" step="0.01" inputmode="decimal" required></label>
        <label class="field" style="flex:1"><span>Когда платить</span><input class="input" name="due" type="date" value="${addDays(state.meta.today, 1)}" required></label></div>
      <div class="row"><label class="field" style="flex:1"><span>Повтор</span><select class="input" name="repeat">${repOpts("month")}</select></label>
        <label class="field" style="flex:1"><span>Категория</span><select class="input" name="category">${catOpts("out", "subs")}</select></label></div>
      <button class="btn btn-accent wide" type="submit">Добавить платёж</button></form>`
    : `<form data-submit="fundAdd">
      <p class="muted small" style="margin-top:0">Для трат не каждый месяц: праздники, подарки, годовые платежи. Бот растянет сумму до даты и будет откладывать понемногу.</p>
      <label class="field"><span>На что</span><input class="input" name="title" maxlength="60" placeholder="🎄 Новый год, ДР Сони…" required></label>
      <div class="row"><label class="field" style="flex:1"><span>Сколько нужно ₽</span><input class="input" name="target" type="number" min="1" inputmode="decimal" required></label>
        <label class="field" style="flex:1"><span>К какой дате</span><input class="input" name="due" type="date" value="${addDays(state.meta.today, 30)}" required></label></div>
      <label class="field"><span>Повтор</span><select class="input" name="repeat"><option value="year">Каждый год</option><option value="none">Один раз</option></select></label>
      <label class="row small" style="gap:8px;margin:4px 0 12px"><input type="checkbox" name="remind" checked> За 2 недели закинуть в банк задачу «выбрать и купить»</label>
      <button class="btn btn-accent wide" type="submit">Создать фонд</button></form>`}</div>`;
  return { html };
};
actions.planEdit = el => { const id = Number(el.dataset.id); state.planEdit = state.planEdit === id ? null : id; return reFin(); };
actions.planSave = async form => {
  await api("PATCH", "/fin/plans/" + form.dataset.id, { amount: Number(form.amount.value), due: form.due.value, repeat: form.repeat.value });
  state.planEdit = null;
  toast("✏️ Сохранено");
  await reFin();
};
actions.obAdd = el => { state.obAdd = el.dataset.k; return reFin(); };
actions.obOpen = el => { state.obOpen = state.obOpen === el.dataset.slot ? null : el.dataset.slot; return reFin(); };
actions.obPut = async form => {
  const r = await api("POST", `/fin/oblig/${form.dataset.slot}/put`, { amount: Number(form.amount.value), src: form.src.value });
  state.obOpen = null;
  toast(r.status === "ok" || r.status === "double" ? `🟢 ${esc(r.title)}: хватает` : `＋ ${esc(r.title)}: ${rubR(r.balance)}`);
  celebrate(r);
  await reFin();
};
actions.obTake = async el => {
  const v = prompt(`Сколько забрать, ₽? (отложено ${rubR(Number(el.dataset.max))}; вернётся в неразложенные)`);
  if (!v) return;
  await api("POST", `/fin/oblig/${el.dataset.slot}/take`, { amount: Number(v.replace(",", ".")), src: "free" });
  await reFin();
};
actions.planAdd = async form => {
  await api("POST", "/fin/plans", { title: form.title.value, amount: Number(form.amount.value), due: form.due.value,
                                    repeat: form.repeat.value, category: form.category.value });
  toast("📅 Добавлено");
  await reFin();
};
actions.fundAdd = async form => {
  const f = await api("POST", "/fin/funds", { title: form.title.value, target: Number(form.target.value), due: form.due.value,
                                              repeat: form.repeat.value, remind: form.remind.checked });
  toast(`🎁 Фонд создан · ~${rubR(f.per_week)} в неделю`);
  await reFin();
};
actions.planPay = async el => {
  const r = await api("POST", `/fin/plans/${el.dataset.id}/pay`);
  const took = (r.took || []).filter(x => x.src !== "buffer");
  toast(took.length ? `✅ Оплачено · добрал ${took.map(x => `${rubR(x.amount)} из ${x.title}`).join(", ")}` : "✅ Оплачено из отложенного");
  celebrate(r);
  await reFin();
};
actions.planDel = async el => { if (confirm("Удалить платёж? Отложенное на него вернётся в неразложенные.")) { await api("DELETE", "/fin/plans/" + el.dataset.id); await reFin(); } };
actions.fundDel = async el => { if (confirm("Удалить фонд? Отложенное вернётся в неразложенные.")) { await api("DELETE", "/fin/funds/" + el.dataset.id); await reFin(); } };

// ---------- Желания ----------
FIN.wishes = async () => {
  const d = await api("GET", "/fin/wishes");
  let html = d.env_on
    ? `<div class="banner money">🎯 В «Хотелках»: <b>${rubR(d.want)}</b> <span class="muted small">— на желания откладываем отсюда</span></div>`
    : `<p class="muted small">Свободно: <b>${rub(d.balance)}</b>. Отложенное на желания не считается свободными деньгами.</p>`;
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
  const v = prompt(el.dataset.s === "1" ? "Сколько отложить, ₽? (берём из «Хотелок»)" : "Сколько забрать обратно, ₽? (вернётся в «Хотелки»)");
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
  let html = `<div class="wallet" style="padding-top:8px"><div class="stat-label">Накопления и вложения</div><div class="wallet-num">${rubR(total)}</div>
    <div class="muted small">${d.env_on ? `не разложено ${rubR(d.unallocated)} · пополняй из неразложенных или из конверта` : `свободно ещё ${rub(d.balance)}`}</div></div>`;
  html += d.savings.map(s => `<div class="card">
    <div class="row"><b style="font-size:17px">${s.kind === "invest" ? "📈" : "🏦"} ${esc(s.title)}</b><span class="spacer"></span><b style="font-size:18px">${rub(s.current)}</b></div>
    ${s.kind === "invest" ? `<div class="muted small" style="margin-top:4px">вложено ${rub(s.invested)} · <span style="color:${s.profit >= 0 ? "var(--good)" : "var(--bad)"}">${rub(s.profit, true)}</span>${s.value_day ? ` · оценка от ${ddmm(s.value_day)}` : ""}</div>` : ""}
    <div class="row wrap" style="margin-top:10px">
      <button class="btn btn-sm btn-accent" data-act="${d.env_on ? "savOpen" : "savMove"}" data-id="${s.id}" data-s="1">＋ Пополнить</button>
      <button class="btn btn-sm" data-act="savMove" data-id="${s.id}" data-s="-1">− Снять</button>
      ${s.kind === "invest" ? `<button class="btn btn-sm" data-act="savValue" data-id="${s.id}">📊 Стоимость</button>` : ""}
      <span class="spacer"></span>${s.current === 0 ? `<button class="btn btn-sm btn-ghost" data-act="savDel" data-id="${s.id}" aria-label="Убрать">✕</button>` : ""}</div>
    ${state.savOpen === s.id ? `<form class="row wrap" data-submit="savDeposit" data-id="${s.id}" style="margin-top:10px">
      <select class="input" name="src" style="flex:2;min-width:150px">
        <option value="free">📥 Неразложенные · ${rubR(d.unallocated)}</option>
        ${["me", "rel", "want", "oblig"].map(k => `<option value="${k}">${{ me: "🧍 Я", rel: "❤️ Отношения", want: "🎯 Хотелки", oblig: "📅 Обязательное" }[k]} · ${rubR(d.balances[k])}</option>`).join("")}</select>
      <input class="input" name="amount" type="number" min="1" inputmode="decimal" placeholder="₽" required style="flex:1;min-width:80px">
      <button class="btn btn-accent" type="submit">OK</button></form>` : ""}</div>`).join("") ||
    `<div class="empty small">Копилок нет. Заведи «Подушку» или «Вклад», а для акций и крипты — вложение.</div>`;
  html += `<form class="card" data-submit="savAdd" style="margin-top:14px"><div class="h3">＋ Новая копилка</div>
    <div class="row"><input class="input" name="title" maxlength="60" placeholder="Подушка безопасности" required style="flex:2">
      <select class="input" name="kind" style="flex:1"><option value="saving">🏦 Накопление</option><option value="invest">📈 Вложение</option></select></div>
    <button class="btn btn-accent wide" type="submit" style="margin-top:10px">Создать</button></form>`;
  return { html };
};
actions.savAdd = async form => { await api("POST", "/fin/savings", { title: form.title.value, kind: form.kind.value }); await reFin(); };
actions.savOpen = el => { const id = Number(el.dataset.id); state.savOpen = state.savOpen === id ? null : id; return reFin(); };
actions.savDeposit = async form => {
  await api("POST", `/fin/savings/${form.dataset.id}/move`, { amount: Number(form.amount.value), src: form.src.value });
  state.savOpen = null;
  toast("🏦 Пополнено");
  await reFin();
};
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
  const ENVN = { me: ["🧍", "Я"], rel: ["❤️", "Отношения"], want: ["🎯", "Хотелки"], oblig: ["📅", "Обязательное"] };
  if (s.by_envelope && s.by_envelope.length) {
    const envRows = s.by_envelope.map(x => ({ emoji: ENVN[x.envelope][0], title: ENVN[x.envelope][1], sum: x.s, count: x.n }));
    html += `<div class="h2">По конвертам</div>` + hb(envRows, s.expense);
  }
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
