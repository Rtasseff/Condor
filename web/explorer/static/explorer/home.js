/* Condor Funds v2 — Build (pick assets, see the draft as a pie). */
"use strict";

const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const C = {
  surface: cssVar("--surface"),
  ink: cssVar("--ink"),
  ink2: cssVar("--ink-2"),
  muted: cssVar("--muted"),
  font: cssVar("--font-body"),
};
// Validated 8-hue categorical set (dark-mode steps; docs/BRANDING.md).
// Assigned per-holding in the order it was added, not by weight rank, so
// a ticker keeps its color as the mix changes (see colorFor()).
const PIE_COLORS = [
  cssVar("--series-frontier"), cssVar("--series-2"), cssVar("--series-3"),
  cssVar("--series-you"), cssVar("--series-cal"), cssVar("--series-6"),
  cssVar("--series-7"), cssVar("--series-8"),
];

// Same consumer-chart contract as app.js/account.js.
const CHART_CONFIG = {
  displayModeBar: false, displaylogo: false, responsive: true,
  scrollZoom: false, doubleClick: false, showTips: false,
  showAxisDragHandles: false, showAxisRangeEntryBoxes: false,
};

const $ = (id) => document.getElementById(id);
const money = (x) => "$" + (+x).toLocaleString(undefined, {
  minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

function csrftoken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
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

const state = {
  assets: [],   // [{symbol, weight}] — weight a raw fraction, not required to sum to 1
  names: {},    // ticker -> company name (bundled tickers.json)
  colors: {},   // ticker -> assigned pie color, stable in add-order
  info: {},     // ticker -> /api/asset payload once fetched
};

function showError(msg) {
  const e = $("error");
  e.textContent = msg;
  e.hidden = !msg;
}

// ---------- ticker list / autocomplete ----------
async function loadTickers() {
  const res = await fetch(window.TICKERS_URL || "/static/explorer/tickers.json");
  const list = await res.json();
  const dl = $("tickerlist");
  for (const { t, n } of list) {
    state.names[t] = n;
    const opt = document.createElement("option");
    opt.value = t;
    opt.label = `${t} — ${n}`;
    dl.appendChild(opt);
  }
}

const QUICK = ["SPY", "QQQ", "GLD", "BND", "NEE", "VNQ", "EEM"];
function renderQuickAdd() {
  const box = $("quickadd");
  box.replaceChildren();
  for (const t of QUICK) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = "+ " + t;
    b.title = state.names[t] || t;
    b.addEventListener("click", () => addAsset(t));
    box.appendChild(b);
  }
}

// ---------- color assignment (stable per ticker, not per rank) ----------
function colorFor(symbol) {
  if (!state.colors[symbol]) {
    const idx = Object.keys(state.colors).length % PIE_COLORS.length;
    state.colors[symbol] = PIE_COLORS[idx];
  }
  return state.colors[symbol];
}

// ---------- draft mutation ----------
function addAsset(raw) {
  const t = raw.trim().toUpperCase();
  if (!t) return;
  if (!/^[A-Z0-9.\-^]{1,10}$/.test(t)) {
    showError(`'${t}' does not look like a ticker symbol.`);
    return;
  }
  if (state.assets.some((a) => a.symbol === t)) return;
  if (state.assets.length >= 15) {
    showError("Prototype is capped at 15 assets.");
    return;
  }
  showError("");
  // new asset gets 1/n; everyone else scales by (n-1)/n — preserves
  // relative proportions, predictable to watch happen on the pie.
  const n = state.assets.length + 1;
  for (const a of state.assets) a.weight *= (n - 1) / n;
  state.assets.push({ symbol: t, weight: 1 / n });
  colorFor(t);
  renderAll();
  fetchInfo(t);
  syncDraft();
}

function removeAsset(t) {
  state.assets = state.assets.filter((a) => a.symbol !== t);
  const total = state.assets.reduce((s, a) => s + a.weight, 0);
  if (total > 0) for (const a of state.assets) a.weight /= total;
  renderAll();
  syncDraft();
}

function evenOut() {
  const n = state.assets.length;
  if (!n) return;
  for (const a of state.assets) a.weight = 1 / n;
  renderAll();
  syncDraft();
}

function setWeight(t, weightPct) {
  const a = state.assets.find((x) => x.symbol === t);
  if (!a) return;
  a.weight = Math.max(0, weightPct) / 100;
  renderAll();
  syncDraft();
}

// ---------- server round-trip ----------
// Every edit round-trips the whole list. Leaving happens on a click, so
// the last PUT can still be in flight — and Optimize now decides
// server-side whether there is anything to optimize, which would strand
// the user on "Nothing to optimize yet". Anything that navigates awaits
// this instead of racing it.
let pendingSync = Promise.resolve();

async function syncDraft() {
  const assets = state.assets
    .filter((a) => a.weight > 0)
    .map((a) => ({ symbol: a.symbol, weight: a.weight }));
  if (!assets.length) return;
  pendingSync = api("/api/draft", {
    method: "PUT", body: JSON.stringify({ assets }),
  }).catch((err) => { showError(err.message); });
  await pendingSync;
}

async function fetchInfo(symbol) {
  try {
    state.info[symbol] = await api(`/api/asset?symbol=${encodeURIComponent(symbol)}`);
  } catch {
    state.info[symbol] = { ok: false };
  }
  renderDraft();
}

// ---------- rendering ----------
function renderAll() {
  renderDraft();
  renderPie();
  const empty = state.assets.length === 0;
  $("ctacard").hidden = empty;
  $("fcastcta").hidden = empty;   // nothing to project without a mix
}

function plainChange(info) {
  if (!info) return "Loading…";
  if (!info.ok) return "No price history yet.";
  const closeText = `Last close ${money(info.last_close)} (${info.as_of})`;
  if (info.year_return == null) return `${closeText} · not enough history for a 1-year change yet.`;
  const p = Math.abs(info.year_return) * 100;
  const dir = info.year_return >= 0 ? "up" : "down";
  const pStr = p < 1 ? p.toFixed(1) : Math.round(p).toString();
  return `${closeText} · ${dir} ${pStr}% over the past year`;
}

function renderDraft() {
  const ul = $("draftlist");
  ul.replaceChildren();
  $("draftempty").hidden = state.assets.length > 0;
  $("evenout").disabled = state.assets.length < 2;

  for (const a of state.assets) {
    const li = document.createElement("li");
    li.className = "draftrow";

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = colorFor(a.symbol);
    swatch.setAttribute("aria-hidden", "true");

    const main = document.createElement("div");
    main.className = "draftmain";

    const line1 = document.createElement("div");
    line1.className = "draftline1";

    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = a.symbol;

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = state.names[a.symbol] || "";

    const wwrap = document.createElement("span");
    wwrap.className = "pctwrap";
    const w = document.createElement("input");
    w.className = "w";
    w.type = "number";
    w.min = "0";
    w.step = "1";
    w.value = (a.weight * 100).toFixed(1);
    w.setAttribute("aria-label", `Weight for ${a.symbol} (%)`);
    w.addEventListener("change", () => {
      const v = parseFloat(w.value);
      setWeight(a.symbol, isFinite(v) ? v : 0);
    });
    wwrap.append(w, document.createTextNode(" %"));

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "rm";
    rm.textContent = "×";
    rm.setAttribute("aria-label", `Remove ${a.symbol}`);
    rm.addEventListener("click", () => removeAsset(a.symbol));

    line1.append(tick, name, wwrap, rm);

    const line2 = document.createElement("div");
    line2.className = "draftline2 sub";
    line2.textContent = plainChange(state.info[a.symbol]) + " ";
    const more = document.createElement("a");
    more.href = `https://finance.yahoo.com/quote/${encodeURIComponent(a.symbol)}`;
    more.target = "_blank";
    more.rel = "noopener";
    more.textContent = `More about ${a.symbol} →`;
    line2.appendChild(more);

    main.append(line1, line2);
    li.append(swatch, main);
    ul.appendChild(li);
  }
}

function renderPie() {
  const has = state.assets.length > 0;
  $("piechart").hidden = !has;
  $("pie-empty").hidden = has;
  if (!has) return;
  const labels = state.assets.map((a) => a.symbol);
  const values = state.assets.map((a) => Math.max(0, a.weight));
  const colors = labels.map(colorFor);

  Plotly.react("piechart", [{
    type: "pie",
    labels, values,
    textinfo: "label+percent",
    textposition: "inside",
    insidetextorientation: "radial",
    hovertemplate: "%{label}: %{percent}<extra></extra>",
    marker: { colors, line: { color: C.surface, width: 2 } },
  }], {
    paper_bgcolor: C.surface,
    font: { family: C.font, color: C.ink, size: 12 },
    margin: { l: 10, r: 10, t: 10, b: 10 },
    showlegend: false,
  }, CHART_CONFIG);
}

// ---------- account summary ----------
function driftStatus(d) {
  const hasTarget = d.positions.some((p) => p.target_weight > 0) ||
    d.target_cash_weight < 1;
  if (!hasTarget) return { text: "No setpoint yet", warn: false };
  let maxDrift = 0;
  for (const p of d.positions) {
    maxDrift = Math.max(maxDrift, Math.abs(p.weight - p.target_weight));
  }
  if (maxDrift > 0.02) {
    return { text: `${Math.round(100 * maxDrift)}% off target`, warn: true };
  }
  return { text: "On target", warn: false };
}

function renderAccountCard(d) {
  const has = d.events && d.events.length > 0;
  $("acct-tiles").hidden = !has;
  $("acct-empty").hidden = has;
  if (!has) {
    $("acct-empty").textContent =
      "You don't have a tracked account yet — head to My account to pair " +
      "this mix with real (or pretend) money.";
    return;
  }
  $("acct-empty").textContent = "";
  $("acct-value").textContent = money(d.total_value);
  const r = $("acct-twr");
  r.textContent = (d.twr >= 0 ? "+" : "") + pct(d.twr);
  r.classList.toggle("neg", d.twr < 0);
  const drift = driftStatus(d);
  const dEl = $("acct-drift");
  dEl.textContent = drift.text;
  dEl.classList.toggle("neg", drift.warn);
}

async function loadAccount() {
  try {
    renderAccountCard(await api("/api/account"));
  } catch {
    $("acct-empty").hidden = false;
    $("acct-tiles").hidden = true;
    $("acct-empty").textContent = "Couldn't load your account right now.";
  }
}

// ---------- initial draft ----------
async function loadDraft() {
  try {
    const d = await api("/api/draft");
    state.assets = (d.assets || []).map((a) => ({ symbol: a.symbol, weight: a.weight }));
    for (const a of state.assets) colorFor(a.symbol);
  } catch (err) {
    showError(err.message);
  }
}

// ---------- wire up ----------
$("addform").addEventListener("submit", (e) => {
  e.preventDefault();
  addAsset($("addticker").value);
  $("addticker").value = "";
});
$("evenout").addEventListener("click", evenOut);
// "I just wanted to know what $X becomes": hand Optimize the amount and
// horizon in the query string; it analyzes, projects and scrolls there.
$("fc-go").addEventListener("click", async () => {
  const amount = Math.max(1, parseFloat($("fc-amount").value) || 10000);
  const years = parseInt($("fc-years").value, 10) || 2;
  const btn = $("fc-go");
  btn.disabled = true;
  await pendingSync;          // land the draft before Optimize looks for it
  window.location.href =
    `/optimize?forecast=${encodeURIComponent(amount)}&years=${years}`;
});

(async function init() {
  await loadTickers();
  await loadDraft();
  renderAll();
  renderQuickAdd();
  await Promise.all(state.assets.map((a) => fetchInfo(a.symbol)));
  loadAccount();
})();
