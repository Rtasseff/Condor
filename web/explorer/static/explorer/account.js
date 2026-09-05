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

// Same consumer-chart contract as app.js (docs/research/ui-conventions.md)
const CHART_CONFIG = {
  displayModeBar: false, displaylogo: false, responsive: true,
  scrollZoom: false, doubleClick: false, showTips: false,
  showAxisDragHandles: false, showAxisRangeEntryBoxes: false,
};

const $ = (id) => document.getElementById(id);
const money = (x) => "$" + (+x).toLocaleString(undefined, {
  minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money0 = (x) => "$" + Math.round(+x).toLocaleString();
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

// The cash sleeve of a hypothetical forecast earns this (server-rendered
// from FRED, same number the Optimize field prefills with).
const RF = (() => {
  const raw = parseFloat(document.querySelector("main").dataset.rf);
  return isFinite(raw) ? raw / 100 : 0.04;
})();

// Does the ledger say we actually hold anything? Everything about the two
// bridges hangs off this one question.
const hasHoldings = (d) => (d.positions || []).some((p) => p.shares > 0);
const setpointRows = (d) =>
  (d.positions || []).filter((p) => p.target_weight > 0);

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
  renderStarter();
  renderForecastMode();
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
  // the empty-account copy folded into the starter card above (bridge 1)
  $("a-asof").textContent = d.events.length
    ? `Valued at the ${d.as_of} close. Money you put in counts as ` +
      `contribution, not return — the return above is time-weighted.`
    : "Nothing recorded yet — the card above gets you started.";
}

// ---------- bridge 1: the starter card ----------
// An empty account with a plan is the confusing case: everything reads
// zero and nothing says why. This card crosses the border in one click,
// through the ledger — deposit, then the whole-share buys — never around
// it. Chains three endpoints that already exist; adds no new writer.
function renderStarter() {
  const d = state.data;
  const card = $("startercard");
  const empty = !d.events.length;
  card.hidden = !empty;
  if (!empty) return;
  const planned = setpointRows(d).length > 0;
  $("starterfund").hidden = !planned;
  $("starterguide").hidden = planned;
  syncStarterButton();
}

function syncStarterButton() {
  const amount = Math.max(1, parseFloat($("starter-amount").value) || 10000);
  $("startergo").textContent = `Start with ${money0(amount)} →`;
}

async function startAccount() {
  const amount = Math.max(1, parseFloat($("starter-amount").value) || 10000);
  const btn = $("startergo");
  btn.disabled = true;
  showError("");
  let deposited = false;
  try {
    $("starterstatus").textContent = "Recording the deposit…";
    await api("/api/account/events", {
      method: "POST",
      body: JSON.stringify({ kind: "deposit", amount, note: "opening deposit" }),
    });
    deposited = true;   // from here on, a failure leaves money in the ledger
    $("starterstatus").textContent = "Pricing your plan at the last close…";
    const plan = await api("/api/account/plan");
    const trades = plan.rows
      .filter((r) => r.trade_shares !== 0)
      .map((r) => ({ ticker: r.ticker, shares: r.trade_shares, price: r.price }));
    if (!trades.length) {
      throw new Error(`${money0(amount)} doesn't buy a whole share of `
        + "anything in your plan — try a larger amount.");
    }
    $("starterstatus").textContent = "Booking the buys…";
    render(await api("/api/account/plan/confirm", {
      method: "POST", body: JSON.stringify({ trades }) }));
    $("starterstatus").textContent = "";
  } catch (err) {
    if (deposited) {
      // deposit-only is a real, recoverable state — say so plainly rather
      // than implying nothing happened. Refresh FIRST: render() clears the
      // error banner, so the message has to land after the ledger state it
      // is describing, or the user is told nothing at all.
      const msg = `Your money is in, but the buys didn't book — ${err.message} `
        + "Use the rebalancing plan below to finish.";
      try { render(await api("/api/account")); } catch { /* show it anyway */ }
      showError(msg);
    } else {
      showError(err.message);
    }
  } finally {
    btn.disabled = false;
    if ($("starterstatus").textContent.endsWith("…"))
      $("starterstatus").textContent = "";
  }
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
    xaxis: {
      type: "date", gridcolor: C.grid, zerolinecolor: C.axis,
      fixedrange: true, showspikes: true, spikethickness: 1,
      spikedash: "dot", spikecolor: C.axis,
      // the consumer way to "zoom": preset ranges, not drag gestures
      rangeselector: {
        bgcolor: C.surface, activecolor: C.axis, bordercolor: C.grid,
        borderwidth: 1, font: { color: C.ink2, size: 12 },
        buttons: [
          { count: 1, label: "1m", step: "month", stepmode: "backward" },
          { count: 6, label: "6m", step: "month", stepmode: "backward" },
          { count: 1, label: "YTD", step: "year", stepmode: "todate" },
          { count: 1, label: "1y", step: "year", stepmode: "backward" },
          { step: "all", label: "All" },
        ],
      },
    },
    yaxis: { tickprefix: "$", tickformat: ",.0f",
             gridcolor: C.grid, zerolinecolor: C.axis, fixedrange: true },
    hovermode: "x unified", hoverdistance: 30,
    legend: { orientation: "h", x: 0, y: 1.12, itemclick: false,
      itemdoubleclick: false, font: { color: C.ink2, size: 12 } },
    dragmode: false,
    hoverlabel: { bgcolor: "#182238", font: { color: C.ink, size: 13 } },
  }, CHART_CONFIG);
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
  const btn = $("planbtn");
  btn.setAttribute("aria-disabled", "true");
  $("targethint").textContent = "Pricing at the last close…";
  try {
    const plan = await api("/api/account/plan");
    state.plan = plan;
    renderPlan();
  } catch (err) { showError(err.message); } finally {
    btn.removeAttribute("aria-disabled");
    if ($("targethint").textContent === "Pricing at the last close…")
      $("targethint").textContent = "";
  }
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
  $("scplan").setAttribute("aria-disabled", "true");
  $("scstatus").textContent = "Pricing…";
  try {
    state.contrib = await api(`/api/account/contribution${q}`);
    renderContribution();
  } catch (err) { showError(err.message); } finally {
    $("scplan").removeAttribute("aria-disabled");
    if ($("scstatus").textContent === "Pricing…") $("scstatus").textContent = "";
  }
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
// Expected-return anchor (rung C), same control as the Build page: an
// anchor is a claim about the market, so the server applies it to the
// invested sleeve and leaves the cash share at the T-bill rate.
function anchorParams() {
  const mode = $("af-anchor").value;
  $("af-anchorcustom").hidden = mode !== "custom";
  renderPriorChip();
  return mode === "custom"
    ? { anchor: mode, anchor_value: parseFloat($("af-anchorvalue").value) / 100 }
    : { anchor: mode };
}

// Same discoverability guard as the Optimize card: a non-default prior has
// to be legible while the disclosure is shut.
function renderPriorChip() {
  const chip = $("af-priorchip");
  const sel = $("af-anchor");
  if (!chip) return;
  const mode = sel.value;
  if (mode === "historical") {
    chip.hidden = true;
    chip.textContent = "";
    return;
  }
  const typed = parseFloat($("af-anchorvalue").value);
  if (mode === "custom" && !Number.isFinite(typed)) {
    chip.hidden = true;      // mid-edit: an empty box is not a prior
    chip.textContent = "";
    return;
  }
  const value = mode === "market"
    ? sel.dataset.market
    : String(+typed.toFixed(1));
  chip.textContent = `prior: ${mode === "market" ? "return to normal" :
    "my own number"}, ${value}%`;
  chip.hidden = false;
}

// ---------- bridge 2: forecasting a plan that isn't real yet ----------
// With no holdings the account forecast used to refuse. It still can't
// pretend the money exists — but it can project the *setpoint*, clearly
// labelled, so an empty account isn't a dead end.
let forecastMode = null;   // "hypothetical" | "real" — what the fan shows

function clearForecastFan() {
  for (const id of ["afchart", "afmu", "afnote", "afguard"]) $(id).hidden = true;
}

function renderForecastMode() {
  const d = state.data;
  const hypo = !hasHoldings(d);
  const planned = setpointRows(d).length > 0;
  const starterVisible = !$("startercard").hidden;
  $("afintro").hidden = hypo;
  $("afhypo").hidden = !(hypo && planned);
  $("afnoplan").hidden = !(hypo && !planned);
  $("af-amountwrap").hidden = !hypo;
  $("aforecast").disabled = hypo && !planned;

  // A chart drawn in one mode must never be relabelled as the other. The
  // obvious way in: project the hypothetical, then fund from the starter
  // card — the fan is still "your plan" but the badge now says "whole
  // account". Any flip drops the old fan.
  const mode = hypo ? "hypothetical" : "real";
  if (mode !== forecastMode) clearForecastFan();
  forecastMode = mode;

  if (hypo) {
    // Cash already on the ledger has nowhere to go through the starter
    // card (it retires once events exist), so send them to the holdings
    // table's plan instead, and start the projection from what is
    // actually there rather than the input's stock $10,000.
    const link = $("afhypolink");
    link.setAttribute("href", starterVisible ? "#startercard" : "#holdings");
    link.textContent = starterVisible
      ? "Make it real above →" : "Put your cash to work below →";
    if (!starterVisible && d.total_value > 0) {
      $("af-amount").value = Math.round(d.total_value);
    }
  } else {
    $("afbadge").textContent = "whole account";
  }
}

const pctpt = (x) => (100 * x).toFixed(1);
const pctnum = (x) => String(+(100 * x).toFixed(1));

function assumptionSentence(f) {
  const a = f.anchor;
  const whole = f.hypothetical ? "your plan" : "the whole account";
  // a fully invested mix has no cash sleeve to explain — saying "0% is
  // cash at the 0.0% T-bill rate" is noise, and reads as a claim
  const cash = f.cash_weight > 0.005
    ? `${pct(f.cash_weight, 0)} of ${f.hypothetical ? "it" : "the account"}`
      + ` is cash at the ${pctpt(f.risk_free_rate)}% T-bill rate`
    : "";
  const error = `good to about ±${pctpt(f.mu_se_annual)} points; plausibly `
    + `${pctpt(f.mu_ci95[0])}% to ${pctpt(f.mu_ci95[1])}%`;
  const dispersion = ` Dispersion: ${pctpt(f.sigma_annual)}%/yr.`;
  if (a.mode === "historical") {
    return `Middle line: ${pctpt(f.mu_annual)}%/yr for ${whole}`
      + (cash ? ` (${cash})` : "")
      + ` — what ${f.hypothetical ? "that mix" : "your holdings"} `
      + `averaged over `
      + `${f.span_years.toFixed(1)} years of data, and nothing else. `
      + `That estimate is ${error}.` + dispersion;
  }
  const source = a.mode === "market"
    ? `the long-run market anchor of ${pctnum(a.value)}%`
    : `your own ${pctnum(a.value)}% assumption`;
  return `Middle line: ${pctpt(f.mu_annual)}%/yr for ${whole} — its `
    + `${pctpt(a.mu_historical)}%/yr over ${f.span_years.toFixed(1)} years `
    + `blended with ${source} (held to ±${pctnum(a.prior_sd)} points), each `
    + `weighted by how well it is known. `
    + (cash
        ? `Because ${cash}, that anchor counts as ${pctpt(a.effective)}%/yr `
          + `— held to ±${pctpt(a.prior_sd_effective)} points — across `
          + `${whole}. `
        : "")
    + `History alone was good only to `
    + `±${pctpt(a.mu_se_historical)} points; the blend is ${error}.`
    + dispersion;
}

let forecastSeq = 0;   // only the newest request may paint the card

// The plan through the same engine the Build page uses: the setpoint's
// weights are fractions of the whole account, so whatever they leave over
// is the cash sleeve. Lookback and method are left at the endpoint's
// defaults — the same ones /api/account/forecast uses — so the two agree.
async function projectSetpoint() {
  const d = state.data;
  const rows = setpointRows(d);
  const weights = {};
  for (const p of rows) weights[p.ticker] = p.target_weight;
  const f = await api("/api/forecast", {
    method: "POST",
    body: JSON.stringify({
      tickers: rows.map((p) => p.ticker),
      weights,
      cash_weight: Math.max(0, Math.min(1, d.target_cash_weight)),
      risk_free_rate: RF,
      horizon_years: parseInt($("af-horizon").value, 10),
      model: $("af-model").value,
      ...anchorParams(),
    }),
  });
  f.start_value = Math.max(1, parseFloat($("af-amount").value) || 10000);
  f.hypothetical = true;    // nothing here is held; the labels must say so
  return f;
}

function projectAccount() {
  return api("/api/account/forecast", {
    method: "POST",
    body: JSON.stringify({
      horizon_years: parseInt($("af-horizon").value, 10),
      model: $("af-model").value,
      ...anchorParams() }),
  });
}

async function runAccountForecast() {
  showError("");
  if (!state.data) {   // the initial /api/account never landed
    showError("Your account hasn't loaded yet — reload the page to try again.");
    return;
  }
  const seq = ++forecastSeq;
  const btn = $("aforecast");
  btn.disabled = true;
  $("afstatus").textContent = "Projecting…";
  try {
    const f = await (hasHoldings(state.data)
      ? projectAccount() : projectSetpoint());
    if (seq !== forecastSeq) return;       // a later change already won
    renderAccountForecast(f);
  } catch (err) {
    if (seq === forecastSeq) showError(err.message);
  } finally {
    if (seq === forecastSeq) {
      btn.disabled = false;
      $("afstatus").textContent = "";
    }
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
    name: f.anchor.mode === "historical"
      ? "Median — if the past average holds"
      : "Median — if the blended assumption holds",
    line: { color: C.frontier, width: 2.5 },
    hovertemplate: "$%{y:,.0f} at year %{x:.1f}<extra>median</extra>",
  });
  Plotly.react("afchart", traces, {
    paper_bgcolor: C.surface, plot_bgcolor: C.surface,
    font: { family: C.font, color: C.ink2 },
    margin: { l: 70, r: 20, t: 10, b: 45 },
    xaxis: { title: { text: "Years from today", font: { color: C.muted } },
             gridcolor: C.grid, zerolinecolor: C.axis, fixedrange: true,
             showspikes: true, spikethickness: 1, spikedash: "dot",
             spikecolor: C.axis },
    yaxis: { tickprefix: "$", tickformat: ",.0f",
             gridcolor: C.grid, zerolinecolor: C.axis, fixedrange: true },
    hovermode: "x unified", hoverdistance: 30,
    legend: { orientation: "h", x: 0, y: 1.12, itemclick: false,
      itemdoubleclick: false, font: { color: C.ink2, size: 12 } },
    dragmode: false,
    hoverlabel: { bgcolor: "#182238", font: { color: C.ink, size: 13 } },
  }, CHART_CONFIG);

  $("afbadge").textContent = f.hypothetical
    ? `not yet real — your plan with ${money0(f.start_value)}`
    : (f.model === "block-bootstrap"
        ? `resampled history (${f.block}-day blocks)`
        : "steady rates (simplest)") + " · whole account"
      + (f.anchor.mode === "historical" ? ""
         : ` · prior ${pctnum(f.anchor.effective)}%`
           + ` ± ${pctnum(f.anchor.prior_sd_effective)} pp`);
  $("afguard").hidden = !f.guarded;
  $("af-anchor").options[0].textContent =
    `My mix's own history (${pctpt(f.anchor.mu_historical)}%)`;
  renderPriorChip();
  $("afmu").textContent = assumptionSentence(f);
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
$("startergo").addEventListener("click", startAccount);
$("starter-amount").addEventListener("input", syncStarterButton);
// the hypothetical's starting amount only scales the fan — no refetch
$("af-amount").addEventListener("change", () => {
  if (!$("afchart").hidden) runAccountForecast();
});
// "all at once" jumps to the ledger form with the right kind preselected
$("depositjump").addEventListener("click", () => {
  $("ev-kind").value = "deposit";
  syncEventForm();
  setTimeout(() => $("ev-amount").focus(), 0);
});
// changing the assumption redraws the fan straight away
for (const id of ["af-anchor", "af-anchorvalue"]) {
  $(id).addEventListener("change", () => {
    anchorParams();
    if (!$("afchart").hidden) runAccountForecast();
  });
}
$("plancancel").addEventListener("click", () => { $("planpanel").hidden = true; });
$("planconfirm").addEventListener("click", confirmPlan);

(async function init() {
  syncEventForm();
  renderPriorChip();
  $("a-asof").textContent = "Valuing your account at the last close…";
  try {
    render(await api("/api/account"));
    // arriving from Optimize's "Make this my real portfolio": show the plan,
    // under a heading that echoes the button that got us here (fix 3)
    if (new URLSearchParams(location.search).get("plan")) {
      $("plantitle").textContent = "How to get there from what you hold";
      loadPlan();
    }
  } catch (err) {
    showError(err.message);
  }
})();
