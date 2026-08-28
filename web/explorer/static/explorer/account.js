/* Condor Funds v2 — My account (ledger, drift, rebalancing). */
"use strict";

const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const C = {
  surface: cssVar("--surface"),
  ink: cssVar("--ink"),
  ink2: cssVar("--ink-2"),
  muted: cssVar("--muted"),
  grid: cssVar("--grid"),
  axis: cssVar("--axis"),
  frontier: cssVar("--series-frontier"),
  cal: cssVar("--series-cal"),
  you: cssVar("--series-you"),
  font: cssVar("--font-body"),
};

const $ = (id) => document.getElementById(id);
const money = (x) => "$" + (+x).toLocaleString(undefined, {
  minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

function csrftoken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
}

const state = { data: null, plan: null, contrib: null };

function showError(msg) {
  const e = $("error");
  e.textContent = msg;
  e.hidden = !msg;
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
  return data;
}

// ---------- rendering ----------
function render(data) {
  state.data = data;
  showError("");
  renderTiles();
  renderChart();
  renderPositions();
  renderEvents();
  renderSchedule();
}

function renderTiles() {
  const d = state.data;
  $("acctname").textContent = d.account.name;
  $("a-value").textContent = money(d.total_value);
  $("a-contrib").textContent = money(d.net_contributions);
  const g = $("a-gain");
  g.textContent = (d.gain >= 0 ? "+" : "−") + money(Math.abs(d.gain)).slice(0);
  g.classList.toggle("neg", d.gain < 0);
  const r = $("a-twr");
  r.textContent = (d.twr >= 0 ? "+" : "") + pct(d.twr);
  r.classList.toggle("neg", d.twr < 0);
  $("a-asof").textContent = d.events.length
    ? `Valued at the ${d.as_of} close. Money you put in counts as ` +
      `contribution, not return — the return above is time-weighted.`
    : "Empty account — record a deposit below, or set a setpoint and ask " +
      "for a plan.";
}

function renderChart() {
  const s = state.data.series;
  const has = s.dates.length > 1;
  $("chartcard2").hidden = !has;
  if (!has) return;
  Plotly.react("achart", [
    {
      x: s.dates, y: s.value, mode: "lines", name: "Account value",
      line: { color: C.frontier, width: 2.5 },
      hovertemplate: "%{x}: $%{y:,.0f}<extra>value</extra>",
    },
    {
      x: s.dates, y: s.contributions, mode: "lines", name: "Money put in",
      line: { color: C.you, width: 1.5, dash: "dash" },
      hovertemplate: "%{x}: $%{y:,.0f}<extra>contributions</extra>",
    },
  ], {
    paper_bgcolor: C.surface, plot_bgcolor: C.surface,
    font: { family: C.font, color: C.ink2 },
    margin: { l: 70, r: 20, t: 10, b: 40 },
    xaxis: { gridcolor: C.grid, zerolinecolor: C.axis },
    yaxis: { tickprefix: "$", tickformat: ",.0f",
             gridcolor: C.grid, zerolinecolor: C.axis },
    legend: { orientation: "h", x: 0, y: 1.12, font: { color: C.ink2, size: 12 } },
    hoverlabel: { bgcolor: "#182238", font: { color: C.ink, size: 13 } },
  }, { displayModeBar: false, responsive: true });
}

function td(text, cls) {
  const el = document.createElement("td");
  if (cls) el.className = cls;
  el.textContent = text;
  return el;
}

function renderPositions() {
  const d = state.data;
  const tb = $("postable").querySelector("tbody");
  tb.replaceChildren();
  for (const p of d.positions) {
    const drift = p.weight - p.target_weight;
    const tr = document.createElement("tr");
    tr.append(
      td(p.ticker),
      td(p.shares.toLocaleString(), "num"),
      td(p.price == null ? "—" : money(p.price), "num"),
      td(money(p.value), "num"),
      td(pct(p.weight), "num"),
      td(pct(p.target_weight), "num"),
      td((drift >= 0 ? "+" : "") + pct(drift), "num " +
         (Math.abs(drift) > 0.02 ? "drifted" : "")),
    );
    tb.appendChild(tr);
  }
  // cash row
  const total = d.total_value || 1;
  const cw = d.total_value > 0 ? d.cash / d.total_value : 0;
  const tr = document.createElement("tr");
  tr.className = "cashrow";
  const cd = d.target_cash_weight;
  tr.append(
    td("Cash"), td("", "num"), td("", "num"),
    td(money(d.cash), "num"),
    td(pct(cw), "num"),
    td(pct(cd), "num"),
    td((cw - cd >= 0 ? "+" : "") + pct(cw - cd), "num"),
  );
  tb.appendChild(tr);
  $("targethint").textContent =
    d.positions.every((p) => p.target_weight === 0)
      ? "No setpoint yet — edit it here, or send a point over from Build."
      : "";
}

function kindLabel(e) {
  switch (e.kind) {
    case "deposit": return `deposited ${money(e.amount)}`;
    case "withdraw": return `withdrew ${money(e.amount)}`;
    case "buy": return `bought ${e.shares} × ${e.ticker} @ ${money(e.price)}`;
    case "sell": return `sold ${e.shares} × ${e.ticker} @ ${money(e.price)}`;
    case "set_shares": return `forced ${e.ticker} to ${e.shares} shares @ ${money(e.price)}`;
    case "set_cash": return `forced cash to ${money(e.amount)}`;
  }
  return e.kind;
}

function renderEvents() {
  const ul = $("eventlist");
  ul.replaceChildren();
  if (!state.data.events.length) {
    const li = document.createElement("li");
    li.className = "empty-row";
    li.textContent = "Ledger is empty.";
    ul.appendChild(li);
    return;
  }
  for (const e of state.data.events) {
    const li = document.createElement("li");
    const main = document.createElement("span");
    main.textContent = `${e.date} — ${kindLabel(e)}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = e.note || "";
    const del = document.createElement("button");
    del.type = "button";
    del.className = "rm";
    del.textContent = "×";
    del.setAttribute("aria-label", "Delete ledger entry");
    del.addEventListener("click", async () => {
      if (!del.dataset.armed) {
        del.dataset.armed = "1";
        del.textContent = "delete?";
        del.classList.add("armed");
        return;
      }
      try {
        render(await api(`/api/account/events/${e.id}`, { method: "DELETE" }));
      } catch (err) { showError(err.message); }
    });
    li.append(main, meta, del);
    ul.appendChild(li);
  }
}

// ---------- ledger form ----------
const FIELDS = {
  deposit: ["amount"],
  withdraw: ["amount"],
  buy: ["ticker", "shares", "price"],
  sell: ["ticker", "shares", "price"],
  set_shares: ["ticker", "shares", "price"],
  set_cash: ["amount"],
};

function syncEventForm() {
  const kind = $("ev-kind").value;
  for (const label of document.querySelectorAll("#eventform label[data-for]")) {
    label.hidden = !FIELDS[kind].includes(label.dataset.for);
  }
}

async function addEvent(e) {
  e.preventDefault();
  const kind = $("ev-kind").value;
  const body = { kind, date: $("ev-date").value || null,
                 note: $("ev-note").value.trim() };
  if (FIELDS[kind].includes("ticker")) body.ticker = $("ev-ticker").value;
  if (FIELDS[kind].includes("shares")) body.shares = $("ev-shares").value;
  if (FIELDS[kind].includes("price") && $("ev-price").value !== "")
    body.price = $("ev-price").value;
  if (FIELDS[kind].includes("amount")) body.amount = $("ev-amount").value;
  try {
    render(await api("/api/account/events", {
      method: "POST", body: JSON.stringify(body) }));
    for (const id of ["ev-ticker", "ev-shares", "ev-price", "ev-amount", "ev-note"])
      $(id).value = "";
  } catch (err) { showError(err.message); }
}

// ---------- setpoint editor ----------
function targetRow(ticker, percent) {
  const row = document.createElement("div");
  row.className = "targetrow";
  const tick = document.createElement("span");
  tick.className = "tick";
  tick.textContent = ticker;
  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = "0.1";
  input.value = percent;
  input.dataset.ticker = ticker;
  input.addEventListener("input", sumTargets);
  const unit = document.createElement("span");
  unit.textContent = "%";
  const rm = document.createElement("button");
  rm.type = "button";
  rm.className = "rm";
  rm.textContent = "×";
  rm.addEventListener("click", () => { row.remove(); sumTargets(); });
  row.append(tick, input, unit, rm);
  return row;
}

function sumTargets() {
  let sum = 0;
  for (const inp of document.querySelectorAll("#targetrows input"))
    sum += parseFloat(inp.value) || 0;
  $("targetsum").textContent =
    `${sum.toFixed(1)}% allocated — ${(100 - sum).toFixed(1)}% stays in cash` +
    (sum > 100.05 ? " — over 100%!" : "");
}

function openTargetEditor() {
  const box = $("targetrows");
  box.replaceChildren();
  for (const p of state.data.positions) {
    box.appendChild(targetRow(p.ticker, +(100 * p.target_weight).toFixed(1)));
  }
  sumTargets();
  $("targetpanel").hidden = false;
  $("planpanel").hidden = true;
}

async function saveTarget() {
  const weights = {};
  for (const inp of document.querySelectorAll("#targetrows input")) {
    const w = parseFloat(inp.value);
    if (isFinite(w) && w > 0) weights[inp.dataset.ticker] = w / 100;
  }
  try {
    render(await api("/api/account/target", {
      method: "POST", body: JSON.stringify({ weights }) }));
    $("targetpanel").hidden = true;
  } catch (err) { showError(err.message); }
}

// ---------- rebalancing plan ----------
async function loadPlan() {
  try {
    const plan = await api("/api/account/plan");
    state.plan = plan;
    renderPlan();
  } catch (err) { showError(err.message); }
}

function renderPlan() {
  const plan = state.plan;
  const tb = $("plantable").querySelector("tbody");
  tb.replaceChildren();
  for (const r of plan.rows) {
    const tr = document.createElement("tr");
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.value = r.trade_shares;
    input.className = "planshares";
    input.dataset.ticker = r.ticker;
    input.dataset.price = r.price;
    input.addEventListener("input", planCash);
    const tdIn = document.createElement("td");
    tdIn.className = "num";
    tdIn.appendChild(input);
    tr.append(
      td(r.ticker),
      td(money(r.price), "num"),
      td(`${r.current_shares} sh (${pct(r.current_weight)})`, "num"),
      tdIn,
      td(money(r.trade_value), "num"),
      td(pct(r.new_weight), "num"),
      td(pct(r.target_weight), "num"),
    );
    tb.appendChild(tr);
  }
  planCash();
  $("planpanel").hidden = false;
  $("targetpanel").hidden = true;
}

function planCash() {
  const plan = state.plan;
  let spend = 0;
  for (const inp of document.querySelectorAll("#plantable .planshares"))
    spend += (parseFloat(inp.value) || 0) * parseFloat(inp.dataset.price);
  const after = plan.cash_before - spend;
  $("plancash").textContent =
    `Prices as of ${plan.as_of}. Cash: ${money(plan.cash_before)} now → ` +
    `${money(after)} after these trades (setpoint keeps ` +
    `${pct(plan.target_cash_weight)} in cash).` +
    (after < -0.005 ? " That overspends your cash — trim a buy." : "");
}

async function confirmPlan() {
  const trades = [];
  for (const inp of document.querySelectorAll("#plantable .planshares")) {
    const n = parseFloat(inp.value) || 0;
    if (n !== 0) trades.push({ ticker: inp.dataset.ticker, shares: n,
                               price: parseFloat(inp.dataset.price) });
  }
  if (!trades.length) { $("planpanel").hidden = true; return; }
  try {
    render(await api("/api/account/plan/confirm", {
      method: "POST", body: JSON.stringify({ trades }) }));
    $("planpanel").hidden = true;
  } catch (err) { showError(err.message); }
}

// ---------- regular contributions (DCA) ----------
function renderSchedule() {
  const sc = state.data.schedule;
  if (sc) {
    $("sc-amount").value = sc.amount;
    $("sc-cadence").value = sc.cadence;
    $("sc-due").value = sc.next_due;
    $("sc-enabled").checked = sc.enabled;
  }
  const due = sc && sc.due;
  $("duebanner").hidden = !due;
  if (due) {
    $("duetext").textContent =
      `Your ${sc.cadence} contribution of ${money(sc.amount)} is due ` +
      `(scheduled ${sc.next_due}).`;
  }
}

async function saveSchedule() {
  try {
    render(await api("/api/account/schedule", {
      method: "POST",
      body: JSON.stringify({
        amount: $("sc-amount").value,
        cadence: $("sc-cadence").value,
        next_due: $("sc-due").value || null,
        enabled: $("sc-enabled").checked,
      }),
    }));
    $("scstatus").textContent = "Saved.";
    setTimeout(() => { $("scstatus").textContent = ""; }, 2000);
  } catch (err) { showError(err.message); }
}

async function loadContribution() {
  showError("");
  const amt = $("sc-amount").value;
  const q = amt ? `?amount=${encodeURIComponent(amt)}` : "";
  try {
    state.contrib = await api(`/api/account/contribution${q}`);
    renderContribution();
  } catch (err) { showError(err.message); }
}

function renderContribution() {
  const plan = state.contrib;
  $("contribtitle").textContent =
    `Contribution plan — ${money(plan.amount)} in`;
  const tb = $("contribtable").querySelector("tbody");
  tb.replaceChildren();
  for (const r of plan.rows) {
    const tr = document.createElement("tr");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "any";
    input.value = r.buy_shares;
    input.className = "planshares";
    input.dataset.ticker = r.ticker;
    input.dataset.price = r.price;
    input.addEventListener("input", contribCash);
    const tdIn = document.createElement("td");
    tdIn.className = "num";
    tdIn.appendChild(input);
    tr.append(
      td(r.ticker),
      td(money(r.price), "num"),
      td(pct(r.current_weight), "num"),
      td(pct(r.target_weight), "num"),
      tdIn,
      td(money(r.buy_value), "num"),
      td(pct(r.new_weight), "num"),
    );
    tb.appendChild(tr);
  }
  contribCash();
  $("contribpanel").hidden = false;
}

function contribCash() {
  const plan = state.contrib;
  let spend = 0;
  for (const inp of document.querySelectorAll("#contribtable .planshares"))
    spend += (parseFloat(inp.value) || 0) * parseFloat(inp.dataset.price);
  const leftover = plan.amount + state.data.cash - spend;
  $("contribcash").textContent =
    `Prices as of ${plan.as_of}. ${money(plan.amount)} in, ` +
    `${money(spend)} to buys, cash ends at ${money(leftover)} ` +
    `(setpoint keeps ${pct(plan.target_cash_weight)} in cash).` +
    (leftover < -0.005 ? " That overspends — trim a buy." : "");
}

async function confirmContribution() {
  const plan = state.contrib;
  const trades = [];
  for (const inp of document.querySelectorAll("#contribtable .planshares")) {
    const n = parseFloat(inp.value) || 0;
    if (n > 0) trades.push({ ticker: inp.dataset.ticker, shares: n,
                             price: parseFloat(inp.dataset.price) });
  }
  try {
    render(await api("/api/account/contribution/confirm", {
      method: "POST",
      body: JSON.stringify({ amount: plan.amount, trades }),
    }));
    $("contribpanel").hidden = true;
  } catch (err) { showError(err.message); }
}

// ---------- whole-account forecast ----------
async function runAccountForecast() {
  showError("");
  const btn = $("aforecast");
  btn.disabled = true;
  $("afstatus").textContent = "Projecting…";
  try {
    const f = await api("/api/account/forecast", {
      method: "POST",
      body: JSON.stringify({
        horizon_years: parseInt($("af-horizon").value, 10),
        model: $("af-model").value }),
    });
    renderAccountForecast(f);
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    $("afstatus").textContent = "";
  }
}

function renderAccountForecast(f) {
  const start = f.start_value;
  const dollars = (mults) => mults.map((m) => start * m);
  const t = f.t;
  const traces = [];
  const est95 = f.bands_est[f.bands_est.length - 1];
  traces.push({
    x: t, y: dollars(est95.hi), mode: "lines",
    name: "95% + return-estimate error",
    line: { color: C.you, width: 1.5, dash: "dash" },
    hovertemplate: "$%{y:,.0f}<extra>95% high, incl. estimate error</extra>",
  });
  traces.push({
    x: t, y: dollars(est95.lo), mode: "lines", showlegend: false,
    line: { color: C.you, width: 1.5, dash: "dash" },
    hovertemplate: "$%{y:,.0f}<extra>95% low, incl. estimate error</extra>",
  });
  const fills = ["rgba(57,135,229,0.16)", "rgba(57,135,229,0.34)"];
  f.bands.forEach((b, i) => {
    traces.push({ x: t, y: dollars(b.lo), mode: "lines", showlegend: false,
                  line: { width: 0 }, hoverinfo: "skip" });
    traces.push({
      x: t, y: dollars(b.hi), mode: "lines",
      name: `${b.level}% band (market randomness)`,
      fill: "tonexty", fillcolor: fills[i] || fills[0],
      line: { width: 0 },
      hovertemplate: `$%{y:,.0f}<extra>${b.level}% high</extra>`,
    });
  });
  traces.push({
    x: t, y: dollars(f.median), mode: "lines",
    name: "Median — if the past average holds",
    line: { color: C.frontier, width: 2.5 },
    hovertemplate: "$%{y:,.0f} at year %{x:.1f}<extra>median</extra>",
  });
  Plotly.react("afchart", traces, {
    paper_bgcolor: C.surface, plot_bgcolor: C.surface,
    font: { family: C.font, color: C.ink2 },
    margin: { l: 70, r: 20, t: 10, b: 45 },
    xaxis: { title: { text: "Years from today", font: { color: C.muted } },
             gridcolor: C.grid, zerolinecolor: C.axis },
    yaxis: { tickprefix: "$", tickformat: ",.0f",
             gridcolor: C.grid, zerolinecolor: C.axis },
    legend: { orientation: "h", x: 0, y: 1.12, font: { color: C.ink2, size: 12 } },
    hoverlabel: { bgcolor: "#182238", font: { color: C.ink, size: 13 } },
  }, { displayModeBar: false, responsive: true });

  $("afbadge").textContent = (f.model === "block-bootstrap"
    ? `model 2 — resampled history (${f.block}-day blocks)`
    : "model 1 — steady rates") + " · whole account";
  $("afguard").hidden = !f.guarded;
  const pctpt = (x) => (100 * x).toFixed(1);
  $("afmu").textContent =
    `Whole-account growth rate: ${pctpt(f.mu_annual)}%/yr ` +
    `(${pct(f.cash_weight, 0)} of the account is cash at the ` +
    `${pctpt(f.risk_free_rate)}% T-bill rate) from ` +
    `${f.span_years.toFixed(1)} years of data — good to about ` +
    `±${pctpt(f.mu_se_annual)} points; plausibly ` +
    `${pctpt(f.mu_ci95[0])}% to ${pctpt(f.mu_ci95[1])}%. ` +
    `Dispersion: ${pctpt(f.sigma_annual)}%/yr.`;
  for (const id of ["afchart", "afmu", "afnote"]) $(id).hidden = false;
}

// ---------- wire up ----------
$("ev-kind").addEventListener("change", syncEventForm);
$("eventform").addEventListener("submit", addEvent);
$("edittarget").addEventListener("click", openTargetEditor);
$("targetcancel").addEventListener("click", () => { $("targetpanel").hidden = true; });
$("targetsave").addEventListener("click", saveTarget);
$("targetadd").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("targetticker").value.trim().toUpperCase();
  $("targetticker").value = "";
  if (!/^[A-Z0-9.\-^]{1,10}$/.test(t)) { showError(`'${t}' does not look like a ticker.`); return; }
  if ([...document.querySelectorAll("#targetrows input")]
      .some((i) => i.dataset.ticker === t)) return;
  $("targetrows").appendChild(targetRow(t, 0));
  sumTargets();
});
$("planbtn").addEventListener("click", loadPlan);
$("scsave").addEventListener("click", saveSchedule);
$("scplan").addEventListener("click", loadContribution);
$("duego").addEventListener("click", () => {
  loadContribution();
  $("contribpanel").scrollIntoView({ behavior: "smooth", block: "center" });
});
$("contribcancel").addEventListener("click", () => { $("contribpanel").hidden = true; });
$("contribconfirm").addEventListener("click", confirmContribution);
$("aforecast").addEventListener("click", runAccountForecast);
$("plancancel").addEventListener("click", () => { $("planpanel").hidden = true; });
$("planconfirm").addEventListener("click", confirmPlan);

(async function init() {
  syncEventForm();
  try {
    render(await api("/api/account"));
    // arriving from Build with a fresh draft target: show the plan
    if (new URLSearchParams(location.search).get("plan")) loadPlan();
  } catch (err) {
    showError(err.message);
  }
})();
