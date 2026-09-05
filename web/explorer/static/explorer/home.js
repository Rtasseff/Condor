/* Condor Funds v2 — Explore (pick assets, see the draft as a pie). */
"use strict";

const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const C = {
  surface: cssVar("--surface"),
  ink: cssVar("--ink"),
  ink2: cssVar("--ink-2"),
  muted: cssVar("--muted"),
  font: cssVar("--font-body"),
  up: cssVar("--change-up"),
  down: cssVar("--change-down"),
  frontier: cssVar("--series-frontier"),
  grid: cssVar("--grid"),
  axis: cssVar("--axis"),
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
  expanded: null,     // ticker whose detail panel is open (one at a time)
  detailRange: "1Y",  // "1M" | "1Y" — the open detail panel's chart range
};

// Does this user hold anything real? (server-rendered; same check /optimize
// uses.) An empty draft + real holdings is the one case Build offers a
// start chooser instead of a bare search box.
const HAS_REAL = (() => {
  const el = $("has_real");
  try { return el ? JSON.parse(el.textContent) : false; } catch { return false; }
})();
let chooserDismissed = false;

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
  if (!empty) chooserDismissed = true;   // a real mix retires the chooser for good
  $("ctacard").hidden = empty;
  $("fcastcta").hidden = empty;   // nothing to project without a mix
  // Exactly one .primary CTA per state: Add is the hero action while the
  // mix is empty; once there is a mix, "Optimize this mix" takes over and
  // Add quiets down.
  $("addform").querySelector("button[type=submit]").className =
    empty ? "primary small" : "ghost small";
  const showChooser = empty && HAS_REAL && !chooserDismissed;
  $("starterchooser").hidden = !showChooser;
  $("searchcard").hidden = showChooser;
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

// One sentence in words, not a bare number — the Robinhood/Yahoo
// convention: the number carries the precision, the sentence carries
// the meaning. Used by the detail panel (research rule 5).
function wordChange(ret, span) {
  if (ret == null) return `Not enough history for a ${span} change yet.`;
  const p = Math.abs(ret) * 100;
  const dir = ret >= 0 ? "Up" : "Down";
  const pStr = p < 1 ? p.toFixed(1) : Math.round(p).toString();
  return `${dir} ${pStr}% over the last ${span}`;
}

// ---------- sparkline (word-sized, undecorated — research rule 5) ----------
const SPARK_W = 90, SPARK_H = 28, SPARK_PAD = 2;

function sparklineSVG(info) {
  const s = info && info.ok ? info.series : null;
  if (!s || s.closes.length < 2) return "";
  const closes = s.closes;
  const n = closes.length;
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const span = hi - lo || 1;
  const x = (i) => SPARK_PAD + (i / (n - 1)) * (SPARK_W - 2 * SPARK_PAD);
  const y = (v) => SPARK_H - SPARK_PAD - ((v - lo) / span) * (SPARK_H - 2 * SPARK_PAD);
  const d = closes.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" ");
  const color = info.year_return == null ? C.muted : info.year_return >= 0 ? C.up : C.down;
  let baseline = "";
  if (info.year_return != null) {
    // the year-ago price, recovered from the return rather than sent
    // separately — one more number the payload doesn't have to carry.
    const yearAgo = info.last_close / (1 + info.year_return);
    const by = y(Math.min(hi, Math.max(lo, yearAgo))).toFixed(1);
    baseline = `<line class="baseline" x1="${SPARK_PAD}" x2="${SPARK_W - SPARK_PAD}"` +
      ` y1="${by}" y2="${by}"></line>`;
  }
  return `<svg class="spark" width="${SPARK_W}" height="${SPARK_H}"` +
    ` viewBox="0 0 ${SPARK_W} ${SPARK_H}" aria-hidden="true">${baseline}` +
    `<path class="sparkline" pathLength="1" d="${d}" style="stroke:${color}"></path></svg>`;
}

// ---------- detail panel (one at a time; not a modal) ----------
function toggleDetail(symbol) {
  state.expanded = state.expanded === symbol ? null : symbol;
  state.detailRange = "1Y";
  renderDraft();
}

// `series` spans up to ~400 days (views.ASSET_INFO_DAYS_BUFFER), so "1Y"
// has to clip to 365 days too — otherwise it silently shows ~13 months
// under a 1-year label. Both ranges reuse the same day-cutoff filter.
const DETAIL_RANGE_DAYS = { "1M": 31, "1Y": 365 };

function detailSeries(info) {
  const s = info.series;
  const days = DETAIL_RANGE_DAYS[state.detailRange];
  if (s.dates.length < 2) return s;
  const cutoff = new Date(s.dates[s.dates.length - 1]);
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const dates = s.dates.filter((d) => d >= cutoffStr);
  const closes = s.closes.slice(s.dates.length - dates.length);
  return dates.length >= 2 ? { dates, closes } : s;
}

function renderDetailChart(symbol) {
  const info = state.info[symbol];
  if (!info || !info.ok) return;
  const s = detailSeries(info);
  const color = info.year_return == null ? C.frontier
    : info.year_return >= 0 ? C.up : C.down;
  Plotly.react("detailchart", [{
    x: s.dates, y: s.closes, mode: "lines",
    line: { color, width: 2 },
    hovertemplate: "%{x}: $%{y:,.2f}<extra></extra>",
  }], {
    paper_bgcolor: C.surface, plot_bgcolor: C.surface,
    font: { family: C.font, color: C.ink2, size: 11 },
    margin: { l: 54, r: 12, t: 8, b: 30 },
    xaxis: { type: "date", gridcolor: C.grid, zerolinecolor: C.axis, fixedrange: true },
    yaxis: { tickprefix: "$", gridcolor: C.grid, zerolinecolor: C.axis, fixedrange: true },
    dragmode: false, hovermode: "closest",
  }, CHART_CONFIG);
}

function renderDetailPanel(a) {
  const li = document.createElement("li");
  li.className = "detailrow";
  const info = state.info[a.symbol];
  if (!info || !info.ok) {
    li.innerHTML = `<p class="sub">No price history yet for ${a.symbol}.</p>`;
    return li;
  }
  const head = document.createElement("div");
  head.className = "detailhead";
  const range = document.createElement("div");
  range.className = "rangepick";
  for (const r of ["1M", "1Y"]) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "rangebtn" + (state.detailRange === r ? " active" : "");
    b.textContent = r;
    b.setAttribute("aria-pressed", String(state.detailRange === r));
    b.addEventListener("click", () => { state.detailRange = r; renderDraft(); });
    range.appendChild(b);
  }
  head.append(range);

  const chart = document.createElement("div");
  chart.id = "detailchart";
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `${a.symbol} price history`);

  const stats = document.createElement("p");
  stats.className = "sub";
  stats.textContent = `${money(info.last_close)} as of ${info.as_of} · ` +
    `${wordChange(info.year_return, "year")} · ${wordChange(info.month_return, "month")}`;

  const more = document.createElement("a");
  more.className = "sub detaillink";
  more.href = `https://finance.yahoo.com/quote/${encodeURIComponent(a.symbol)}`;
  more.target = "_blank";
  more.rel = "noopener";
  more.textContent = `More about ${a.symbol} on Yahoo Finance →`;

  li.append(head, chart, stats, more);
  return li;
}

function renderDraft() {
  const ul = $("draftlist");
  ul.replaceChildren();
  $("draftempty").hidden = state.assets.length > 0;
  $("evenout").disabled = state.assets.length < 2;

  for (const a of state.assets) {
    const li = document.createElement("li");
    li.className = "draftrow";
    // Row click expands the detail panel; interactive children (weight,
    // remove, the Yahoo link) opt out via closest() so they still work.
    li.addEventListener("click", (e) => {
      if (e.target.closest("input,button,a")) return;
      toggleDetail(a.symbol);
    });

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

    const spark = document.createElement("span");
    spark.className = "sparkwrap";
    spark.innerHTML = sparklineSVG(state.info[a.symbol]);

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

    const expand = document.createElement("button");
    expand.type = "button";
    expand.className = "expandbtn";
    const isOpen = state.expanded === a.symbol;
    expand.textContent = isOpen ? "▾" : "▸";
    expand.setAttribute("aria-expanded", String(isOpen));
    expand.setAttribute("aria-label", `${isOpen ? "Hide" : "Show"} price history for ${a.symbol}`);
    expand.addEventListener("click", () => toggleDetail(a.symbol));

    line1.append(tick, name, spark, wwrap, rm, expand);

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
    if (state.expanded === a.symbol) ul.appendChild(renderDetailPanel(a));
  }
  if (state.expanded && state.assets.some((a) => a.symbol === state.expanded)) {
    renderDetailChart(state.expanded);
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

// ---------- My portfolio summary (link, value, return — kept small) ----------
function renderAccountCard(d) {
  const has = d.events && d.events.length > 0;
  $("acct-tiles").hidden = !has;
  $("acct-empty").hidden = has;
  if (!has) {
    $("acct-empty").textContent =
      "You don't have a tracked portfolio yet — head to My portfolio to pair " +
      "this mix with real (or pretend) money.";
    return;
  }
  $("acct-empty").textContent = "";
  $("acct-value").textContent = money(d.total_value);
  const r = $("acct-twr");
  r.textContent = (d.twr >= 0 ? "+" : "") + pct(d.twr);
  r.classList.toggle("neg", d.twr < 0);
}

async function loadAccount() {
  try {
    renderAccountCard(await api("/api/account"));
  } catch {
    $("acct-empty").hidden = false;
    $("acct-tiles").hidden = true;
    $("acct-empty").textContent = "Couldn't load your portfolio right now.";
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

// ---------- start chooser: explore from scratch, or from what's real ----------
// The piece user testing said was missing: one click, right on landing,
// to fork real holdings into the draft (same mechanics as Optimize's
// source picker — see app.js loadRealHoldings). Read-only on the real
// side; the draft is the only thing that changes.
$("startfresh").addEventListener("click", () => {
  chooserDismissed = true;
  renderAll();
});
$("loadreal").addEventListener("click", async () => {
  showError("");
  const btn = $("loadreal");
  btn.setAttribute("aria-disabled", "true");
  try {
    const d = await api("/api/account");
    const held = (d.positions || []).filter((p) => p.shares > 0).slice(0, 15);
    if (!held.length) throw new Error("Your real portfolio holds no assets yet.");
    state.assets = held.map((p) => ({ symbol: p.ticker, weight: p.weight }));
    for (const a of state.assets) colorFor(a.symbol);
    chooserDismissed = true;
    renderAll();
    renderQuickAdd();
    await Promise.all(state.assets.map((a) => fetchInfo(a.symbol)));
    syncDraft();
  } catch (err) {
    showError(err.message);
  } finally {
    btn.removeAttribute("aria-disabled");
  }
});

(async function init() {
  await loadTickers();
  await loadDraft();
  renderAll();
  renderQuickAdd();
  await Promise.all(state.assets.map((a) => fetchInfo(a.symbol)));
  loadAccount();
})();
