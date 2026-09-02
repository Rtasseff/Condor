/* Condor Funds v2 — Portfolio Explorer front end. */
"use strict";

// ---------- palette ----------
// Read from the CSS theme block (docs/BRANDING.md): restyling the app is
// an edit to style.css :root only — the chart follows automatically.
// Current values were validated for CVD on the dark surface.
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
  select: cssVar("--series-select"),
};

// ---------- state ----------
const state = {
  busy: false,          // one analyze at a time
  assets: ["AAPL", "MSFT", "JNJ", "ABBV", "XOM", "CVX", "COP"], // deck's example
  weights: {},          // ticker -> percent (UI units); empty = equal
  names: {},            // ticker -> company name (from bundled list)
  result: null,         // last /api/analyze payload
  selected: null,       // selected frontier point (or named portfolio)
  savedId: null,        // uuid of the saved portfolio this came from
  savedName: "",
};

// Consumer-chart interaction contract (docs/research/ui-conventions.md):
// hover + click only. No drag zoom, no axis handles, no double-click
// reset, no "double-click to zoom back" tips for interactions we removed.
const CHART_CONFIG = {
  displayModeBar: false, displaylogo: false, responsive: true,
  scrollZoom: false, doubleClick: false, showTips: false,
  showAxisDragHandles: false, showAxisRangeEntryBoxes: false,
};

const $ = (id) => document.getElementById(id);
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

function csrftoken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
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

// ---------- sidebar ----------
function renderAssets() {
  const ul = $("assetlist");
  ul.replaceChildren();
  for (const t of state.assets) {
    const li = document.createElement("li");

    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = t;

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = state.names[t] || "";

    const w = document.createElement("input");
    w.className = "w";
    w.type = "number";
    w.min = "0";
    w.step = "1";
    w.value = state.weights[t] ?? "";
    w.placeholder = "eq";
    w.title = `Weight for ${t} (%)`;
    w.addEventListener("change", () => {
      const v = parseFloat(w.value);
      if (isFinite(v) && v >= 0) state.weights[t] = v;
      else delete state.weights[t];
    });

    const p = document.createElement("span");
    p.className = "pct";
    p.textContent = "%";

    const rm = document.createElement("button");
    rm.className = "rm";
    rm.type = "button";
    rm.setAttribute("aria-label", `Remove ${t}`);
    rm.textContent = "×";
    rm.addEventListener("click", () => {
      state.assets = state.assets.filter((x) => x !== t);
      delete state.weights[t];
      renderAssets();
    });

    li.append(tick, name, w, p, rm);
    ul.appendChild(li);
  }
}

function addAsset(raw) {
  const t = raw.trim().toUpperCase();
  if (!t) return;
  if (!/^[A-Z0-9.\-^]{1,10}$/.test(t)) {
    showError(`'${t}' does not look like a ticker symbol.`);
    return;
  }
  if (state.assets.includes(t)) return;
  if (state.assets.length >= 15) {
    showError("Prototype is capped at 15 assets.");
    return;
  }
  state.assets.push(t);
  renderAssets();
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

// ---------- analyze ----------
function showError(msg) {
  const e = $("error");
  e.textContent = msg;
  e.hidden = !msg;
}

async function analyze() {
  showError("");
  if (!state.assets.length) {
    showError("Add at least one asset.");
    return;
  }
  if (state.busy) return;        // double-submit guard (the real one)
  state.busy = true;
  const btn = $("analyze");
  btn.setAttribute("aria-disabled", "true");   // keeps keyboard focus
  btn.textContent = "Analyzing…";
  $("chart").setAttribute("aria-busy", "true");
  $("status").textContent = "Fetching prices & optimizing…";
  if (!state.result) {           // first run: the chart area explains the wait
    $("chart-empty").style.display = "none";
    $("chart-loading").hidden = false;
  }
  // staged, fast-early progress text (Conrad et al. 2010: framing that
  // starts fast nearly halves abandonment)
  const stages = [
    [0, "Fetching price history…"],
    [4, "Downloading market data…"],
    [9, "Computing statistics & the frontier…"],
    [15, "Still working — the first run for a new ticker downloads " +
         "10 years of history."],
  ];
  const t0 = Date.now();
  const stageTimer = setInterval(() => {
    const secs = (Date.now() - t0) / 1000;
    const msg = stages.filter(([at]) => secs >= at).pop()[1];
    $("chart-loading").lastChild.textContent = " " + msg;
    $("status").textContent = msg;
  }, 1000);
  try {
    const body = {
      tickers: state.assets,
      years: parseInt($("years").value, 10),
      risk_free_rate: parseFloat($("rf").value) / 100,
      method: $("method").value,
      weights: Object.keys(state.weights).length ? state.weights : null,
    };
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    state.result = data;
    state.selected = null;
    // reflect normalized weights back into the sidebar
    // (0 for excluded assets — the server omits near-zero weights)
    state.weights = {};
    for (const t of state.assets) {
      state.weights[t] = +(100 * (data.portfolio.weights[t] || 0)).toFixed(1);
    }
    renderAssets();
    renderAll();
    clearForecast();
  } catch (err) {
    showError(err.message);
  } finally {
    clearInterval(stageTimer);
    state.busy = false;
    btn.removeAttribute("aria-disabled");
    btn.textContent = "Analyze";
    $("chart").removeAttribute("aria-busy");
    $("status").textContent = "";
    $("chart-loading").hidden = true;
  }
}

// ---------- rendering ----------
function renderAll() {
  renderChart();
  renderTiles();
  renderTable();
  renderPoint(state.selected);
}

function hoverStyle() {
  return {
    bgcolor: "#182238",
    bordercolor: "rgba(255,255,255,0.2)",
    font: { color: C.ink, size: 13 },
  };
}

function calMixLabel(p) {
  if (p.risky_frac < 0.005) return "100% T-bills";
  if (p.borrowing)
    return `Borrow ${pct(-p.cash_frac, 0)} + tangency mix ${pct(p.risky_frac, 0)}`;
  return `T-bills ${pct(p.cash_frac, 0)} + tangency mix ${pct(p.risky_frac, 0)}`;
}

function calMixTitle(p) {
  if (p.risky_frac < 0.005) return "100% T-bills (risk-free)";
  if (p.borrowing)
    return `Capital allocation — ${pct(p.risky_frac, 0)} tangency mix, ` +
           `borrowing ${pct(-p.cash_frac, 0)} at the risk-free rate`;
  return `Capital allocation — ${pct(p.cash_frac, 0)} T-bills + ` +
         `${pct(p.risky_frac, 0)} tangency mix`;
}

function renderChart() {
  const r = state.result;
  if (!r) return;
  $("chart-empty").style.display = "none";
  $("clickcue").hidden = !!state.selected;   // cue retires after first click

  const traces = [];
  // Identity lives in the key (legend) — no annotations chasing markers
  // around the plane. Selection is the "Considering" ring.

  // capital allocation line (under everything)
  if (r.cal) {
    traces.push({
      x: r.cal.x, y: r.cal.y,
      mode: "lines", name: "Capital allocation line",
      line: { color: C.cal, width: 2, dash: "dash" },
      hoverinfo: "skip",
    });
    // …dotted with clickable two-fund mixes (T-bills + tangency)
    if (r.cal.points) {
      traces.push({
        x: r.cal.points.map((p) => p.vol),
        y: r.cal.points.map((p) => p.ret),
        text: r.cal.points.map(calMixLabel),
        mode: "markers", name: "cal-mixes", showlegend: false,
        marker: { size: 4, color: C.cal, opacity: 0.55 },
        hovertemplate:
          "%{text} · reward %{y:.1%} · risk %{x:.1%}" +
          "<br><i>click to inspect this mix</i><extra></extra>",
      });
    }
  }

  // efficient frontier
  if (r.frontier.length) {
    traces.push({
      x: r.frontier.map((p) => p.vol),
      y: r.frontier.map((p) => p.ret),
      customdata: r.frontier.map((p) => p.sharpe),
      mode: "lines+markers", name: "Efficient frontier",
      line: { color: C.frontier, width: 2.5 },
      marker: { size: 7, color: C.frontier, opacity: 0.85 },
      hovertemplate:
        "Reward %{y:.1%} · Risk %{x:.1%} · Sharpe %{customdata:.2f}" +
        "<br><i>click to inspect this mix</i><extra></extra>",
    });
  }

  // individual assets (identity carried by ticker labels, not color)
  traces.push({
    x: r.assets.map((a) => a.vol),
    y: r.assets.map((a) => a.ret),
    text: r.assets.map((a) => a.ticker),
    mode: "markers+text", name: "Your assets",
    textposition: "top center",
    textfont: { color: C.ink2, size: 12 },
    marker: {
      size: 9, color: C.muted, symbol: "circle",
      line: { color: C.surface, width: 2 },
    },
    hovertemplate: "%{text}: reward %{y:.1%} · risk %{x:.1%}<extra></extra>",
  });

  // min-vol (leftmost frontier point)
  if (r.min_vol) {
    traces.push({
      x: [r.min_vol.vol], y: [r.min_vol.ret],
      mode: "markers", name: "Min dispersion",
      marker: {
        size: 11, symbol: "square", color: C.ink,
        line: { color: C.surface, width: 2 },
      },
      hovertemplate:
        "Minimum dispersion · reward %{y:.1%} · risk %{x:.1%}" +
        "<br><i>click to inspect</i><extra></extra>",
    });
  }

  // tangency — frontier-blue diamond
  if (r.tangency) {
    traces.push({
      x: [r.tangency.vol], y: [r.tangency.ret],
      customdata: [[r.tangency.sharpe]],
      mode: "markers", name: "Tangent ('reasonable guess')",
      marker: {
        size: 15, symbol: "diamond", color: C.frontier,
        line: { color: C.ink, width: 2 },
      },
      hovertemplate:
        "Tangent portfolio · reward %{y:.1%} · risk %{x:.1%}" +
        " · Sharpe %{customdata[0]:.2f}<br><i>click to inspect</i><extra></extra>",
    });
  }

  // risk-free anchor
  traces.push({
    x: [0], y: [r.risk_free_rate],
    mode: "markers", name: "T-bills (risk-free)",
    marker: {
      size: 11, color: C.cal, symbol: "circle",
      line: { color: C.surface, width: 2 },
    },
    hovertemplate: "Risk-free rate %{y:.1%}<extra></extra>",
  });

  // your portfolio
  const p = r.portfolio;
  traces.push({
    x: [p.vol], y: [p.ret],
    customdata: [[p.sharpe]],
    mode: "markers", name: "Your portfolio",
    marker: {
      size: 14, color: C.you, symbol: "circle",
      line: { color: C.ink, width: 2 },
    },
    hovertemplate:
      "Your portfolio · reward %{y:.1%} · risk %{x:.1%}" +
      " · Sharpe %{customdata[0]:.2f}<extra></extra>",
  });

  // the point being considered (selection ring)
  if (state.selected) {
    traces.push({
      x: [state.selected.vol], y: [state.selected.ret],
      mode: "markers", name: "Considering",
      marker: {
        size: 22, symbol: "circle-open", color: C.select,
        line: { width: 3, color: C.select },
      },
      hoverinfo: "skip",
    });
  }

  const layout = {
    paper_bgcolor: C.surface,
    plot_bgcolor: C.surface,
    font: { family: C.font, color: C.ink2 },
    margin: { l: 70, r: 20, t: 10, b: 55 },
    xaxis: {
      title: { text: "Risk — annualized dispersion (σ)", font: { color: C.muted } },
      tickformat: ".0%", gridcolor: C.grid, zerolinecolor: C.axis,
      rangemode: "tozero", fixedrange: true,
    },
    yaxis: {
      title: { text: "Reward — expected annual return", font: { color: C.muted } },
      tickformat: ".0%", gridcolor: C.grid, zerolinecolor: C.axis,
      fixedrange: true,
    },
    hoverdistance: 30,
    legend: {
      orientation: "h", x: 0, y: 1.1,
      itemclick: false, itemdoubleclick: false,   // a key, not a toggle
      font: { color: C.ink2, size: 12 },
    },
    dragmode: false,
    hoverlabel: hoverStyle(),
  };

  Plotly.react("chart", traces, layout, CHART_CONFIG);
}

// ---------- click-anywhere selection ----------
// Everything inspectable, with the title the point card will show.
function clickTargets() {
  const r = state.result, out = [];
  if (!r) return out;
  r.frontier.forEach((p, i) => out.push({
    point: p, kind: "frontier",
    title: `Frontier point ${i + 1} of ${r.frontier.length}`,
  }));
  if (r.tangency) out.push({
    point: r.tangency, kind: "frontier",
    title: "Tangent portfolio — the 'reasonable guess'",
  });
  if (r.min_vol) out.push({
    point: r.min_vol, kind: "frontier",
    title: "Minimum-dispersion portfolio",
  });
  if (r.cal && r.cal.points) {
    for (const p of r.cal.points) {
      out.push({ point: p, kind: "cal", title: calMixTitle(p) });
    }
  }
  return out;
}

// A click anywhere on the plot snaps to the nearest inspectable point in
// *pixel* distance — no need to hit a marker exactly. Drags (zoom) and
// clicks outside the plotting area (legend, axes) are ignored.
function wireChartClicks() {
  const gd = $("chart");
  let down = null;
  gd.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  gd.addEventListener("click", (e) => {
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const fl = gd._fullLayout;
    if (!fl || !fl.xaxis || !state.result) return;
    const rect = gd.getBoundingClientRect();
    const xpx = e.clientX - rect.left - fl.xaxis._offset;
    const ypx = e.clientY - rect.top - fl.yaxis._offset;
    if (xpx < 0 || ypx < 0 || xpx > fl.xaxis._length || ypx > fl.yaxis._length) return;
    let best = null, bestD = Infinity;
    for (const c of clickTargets()) {
      const dx = fl.xaxis.d2p(c.point.vol) - xpx;
      const dy = fl.yaxis.d2p(c.point.ret) - ypx;
      const d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = c; }
    }
    if (best) selectPoint(best.point, best.title, best.kind);
  });
}

function renderTiles() {
  const p = state.result.portfolio;
  $("tiles").hidden = false;
  $("t-ret").textContent = pct(p.ret);
  $("t-vol").textContent = pct(p.vol);
  $("t-sharpe").textContent = p.sharpe.toFixed(2);
}

function selectPoint(point, title, kind) {
  state.selected = { ...point, title, kind: kind || "frontier" };
  renderChart(); // paints the "Considering" ring
  renderPoint(state.selected);
  // the card can sit below the fold — bring it in if it is
  $("pointcard").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderPoint(sel) {
  const card = $("pointcard");
  if (!sel) { card.hidden = true; return; }
  card.hidden = false;
  $("pointtitle").textContent = sel.title || "Selected portfolio";
  const sharpe = sel.sharpe == null ? "—" : sel.sharpe.toFixed(2);
  $("pointstats").textContent =
    `Reward ${pct(sel.ret)} · risk ${pct(sel.vol)} · Sharpe ${sharpe}`;

  const box = $("pointweights");
  box.replaceChildren();
  const entries = Object.entries(sel.weights).sort((a, b) => b[1] - a[1]);
  if (sel.kind === "cal" && sel.cash_frac > 0.0005) {
    entries.unshift(["T-BILLS", sel.cash_frac]);
  }
  for (const [t, w] of entries) {
    const row = document.createElement("div");
    row.className = "wrow";
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = t;
    const barwrap = document.createElement("div");
    const bar = document.createElement("div");
    bar.className = t === "T-BILLS" ? "bar cash" : "bar";
    bar.style.width = Math.min(100, Math.max(1, 100 * w)) + "%";
    barwrap.appendChild(bar);
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = pct(w);
    row.append(tick, barwrap, val);
    box.appendChild(row);
  }

  // CAL mixes aren't adoptable (the sidebar tracks only risky assets);
  // explain the split instead — with a warning in the borrowing region.
  const note = $("calnote");
  const adopt = $("adoptpoint");
  $("settarget").hidden = false;
  if (sel.kind === "cal") {
    adopt.hidden = true;
    note.hidden = false;
    if (sel.borrowing) {
      note.className = "sub warn";
      note.textContent =
        `This point borrows ${pct(-sel.cash_frac, 0)} of your wealth at the ` +
        `risk-free rate to lever up the tangency mix. Most investors can't ` +
        `borrow at the T-bill rate, so real results would be worse than shown.`;
    } else {
      note.className = "sub";
      note.textContent =
        `To hold this mix, keep ${pct(sel.cash_frac, 0)} of your money in ` +
        `T-bills and put the remaining ${pct(sel.risky_frac, 0)} into the ` +
        `tangency portfolio (bars are fractions of your total wealth).`;
    }
  } else {
    adopt.hidden = false;
    note.hidden = true;
  }
}

function renderTable() {
  const r = state.result;
  $("tablecard").hidden = false;
  const tb = $("assettable").querySelector("tbody");
  tb.replaceChildren();
  for (const a of r.assets) {
    const tr = document.createElement("tr");
    const w = r.portfolio.weights[a.ticker] || 0;
    const cells = [
      a.ticker,
      state.names[a.ticker] || "—",
      pct(w),
      pct(a.ret),
      pct(a.vol),
    ];
    cells.forEach((txt, i) => {
      const td = document.createElement("td");
      if (i >= 2) td.className = "num";
      td.textContent = txt;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  }
  $("datarange").textContent =
    `Data as of ${r.end} · ${r.n_days.toLocaleString()} trading days from ${r.start}` +
    ` · ${r.method === "robust" ? "robust (median/CoMAD)" : "normal (mean/Ledoit-Wolf)"} statistics.`;
}

// ---------- forecast ----------
// The expected-return anchor (rung C): what the middle line assumes.
// "historical" is the default and sends nothing the server didn't
// already assume; the other two blend that history with a stated
// long-run number, so the chart visibly hinges on the choice.
function anchorParams() {
  const mode = $("fanchor").value;
  $("fanchorcustom").hidden = mode !== "custom";
  return mode === "custom"
    ? { anchor: mode, anchor_value: parseFloat($("fanchorvalue").value) / 100 }
    : { anchor: mode };
}

const pctpt = (x) => (100 * x).toFixed(1);
const pctnum = (x) => String(+(100 * x).toFixed(1));

// One sentence naming the centre line's number AND where it came from —
// the honesty rule from docs/research/forecast-methods-ladder.md.
function assumptionSentence(f) {
  const a = f.anchor;
  const error = `good to about ±${pctpt(f.mu_se_annual)} points, so the true `
    + `long-run rate is plausibly ${pctpt(f.mu_ci95[0])}% to `
    + `${pctpt(f.mu_ci95[1])}%`;
  const dispersion = ` Dispersion: ${pctpt(f.sigma_annual)}%/yr.`;
  if (a.mode === "historical") {
    return `Middle line: ${pctpt(f.mu_annual)}%/yr — your mix's own average `
      + `over ${f.span_years.toFixed(1)} years of data, and nothing else. `
      + `That estimate is ${error}.` + dispersion;
  }
  const source = a.mode === "market"
    ? `the long-run market anchor of ${pctnum(a.value)}%`
    : `your own ${pctnum(a.value)}% assumption`;
  return `Middle line: ${pctpt(f.mu_annual)}%/yr — your mix's `
    + `${pctpt(a.mu_historical)}%/yr over ${f.span_years.toFixed(1)} years `
    + `blended with ${source} (held to ±${pctnum(a.prior_sd)} points), each `
    + `weighted by how well it is known. History alone was good only to `
    + `±${pctpt(a.mu_se_historical)} points; the blend is ${error}.`
    + dispersion;
}

function clearForecast() {
  $("forecastcard").hidden = !state.result;
  for (const id of ["fchart", "fmu", "fnote", "fguard"]) $(id).hidden = true;
  $("fanchor").options[0].textContent = "Historical";   // it named the old mix
}

let forecastSeq = 0;   // only the newest request may paint the card

async function runForecast() {
  showError("");
  if (!state.result) return;
  const seq = ++forecastSeq;
  const btn = $("forecast");
  btn.disabled = true;
  $("fstatus").textContent = "Projecting…";
  try {
    const body = {
      tickers: state.assets,
      years: parseInt($("years").value, 10),
      risk_free_rate: parseFloat($("rf").value) / 100,
      method: $("method").value,
      weights: Object.keys(state.weights).length ? state.weights : null,
      horizon_years: parseInt($("fhorizon").value, 10),
      model: $("fmodel").value,
      ...anchorParams(),
    };
    const res = await fetch("/api/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (seq !== forecastSeq) return;      // a later change already won
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    renderForecast(data);
  } catch (err) {
    showError(err.message);
  } finally {
    if (seq === forecastSeq) {
      btn.disabled = false;
      $("fstatus").textContent = "";
    }
  }
}

function renderForecast(f) {
  const amount = Math.max(1, parseFloat($("famount").value) || 10000);
  const dollars = (mults) => mults.map((m) => amount * m);
  const t = f.t;
  const traces = [];

  // widest first so fills stack correctly; est-95 band as dashed outline
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

  // path-only bands, wide to narrow (95 under 65)
  const fills = ["rgba(57,135,229,0.16)", "rgba(57,135,229,0.34)"];
  f.bands.forEach((b, i) => {
    traces.push({
      x: t, y: dollars(b.lo), mode: "lines", showlegend: false,
      line: { width: 0 }, hoverinfo: "skip",
    });
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

  Plotly.react("fchart", traces, {
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
    hoverlabel: hoverStyle(),
  }, CHART_CONFIG);

  $("fbadge").textContent = (f.model === "block-bootstrap"
    ? `model 2 of 3 — resampled history (${f.block}-day blocks)`
    : "model 1 of 3 — simplest: steady rates")
    + (f.anchor.mode === "historical" ? ""
       : ` · anchored ${pctnum(f.anchor.value)}% ± ${pctnum(f.anchor.prior_sd)} pp`);
  $("fguard").hidden = !f.guarded;
  // the control's own label carries what history says, so the choice is
  // a comparison of two numbers rather than a leap in the dark
  $("fanchor").options[0].textContent =
    `Historical (${pctpt(f.anchor.mu_historical)}%)`;
  $("fmu").textContent = assumptionSentence(f);
  for (const id of ["fchart", "fmu", "fnote"]) $(id).hidden = false;
  // (fguard visibility is set above from the payload)
}

// ---------- weight shortcuts ----------
function useWeights(weights) {
  state.weights = {};
  for (const t of state.assets) {
    // explicit 0 for assets the adopted mix excludes — an empty box
    // means "equal weights", which is not what adoption implies
    state.weights[t] = +(100 * (weights[t] || 0)).toFixed(1);
  }
  renderAssets();
  analyze();
}

// ---------- save & share ----------
// The server stores the configuration only (tickers, weights, method,
// lookback, rf) and normalizes weights to fractions of 1; the sidebar
// works in percent, so conversion happens at this boundary.
function currentConfig() {
  const weights = {};
  const even = state.assets.length ? 100 / state.assets.length : 0;
  for (const t of state.assets) weights[t] = state.weights[t] ?? even;
  return {
    weights,
    method: $("method").value,
    years: parseInt($("years").value, 10),
    risk_free_rate: parseFloat($("rf").value) / 100,
  };
}

function applyConfig(cfg) {
  const tag = $("exampletag");
  if (tag) tag.hidden = true;   // a loaded portfolio is not the example
  state.assets = (cfg.tickers || []).slice(0, 15);
  state.weights = {};
  for (const t of state.assets) {
    state.weights[t] = +(100 * ((cfg.weights || {})[t] || 0)).toFixed(1);
  }
  pickOption($("method"), cfg.method, cfg.method);
  pickOption($("years"), String(cfg.years), `${cfg.years} years`);
  $("rf").value = +(100 * cfg.risk_free_rate).toFixed(2);
  state.savedId = cfg.id || null;
  state.savedName = cfg.name || "";
  $("savename").value = state.savedName;
  $("savecopy").hidden = !state.savedId;
  renderAssets();
}

// a saved lookback/method the <select> doesn't offer still has to load
function pickOption(sel, value, label) {
  if (![...sel.options].some((o) => o.value === value)) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
  }
  sel.value = value;
}

function showSavePanel(open) {
  $("savepanel").hidden = !open;
  if (open) {
    $("savename").value = state.savedName;
    $("savecopy").hidden = !state.savedId;
    $("savename").focus();
  }
}

async function savePortfolio(asNew) {
  showError("");
  const name = $("savename").value.trim();
  if (!name) {
    showError("Give the portfolio a name.");
    return;
  }
  if (!state.assets.length) {
    showError("Add at least one asset.");
    return;
  }
  const body = { name, ...currentConfig() };
  if (!asNew && state.savedId) body.id = state.savedId;
  try {
    const res = await fetch("/api/portfolios", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    state.savedId = data.id;
    state.savedName = data.name;
    $("savecopy").hidden = false;
    $("sharelink").value = data.url;
    $("sharerow").hidden = false;
    $("status").textContent = `Saved “${data.name}”.`;
    setTimeout(() => { $("status").textContent = ""; }, 3000);
    if (!$("savedpanel").hidden) refreshSaved();
  } catch (err) {
    showError(err.message);
  }
}

async function refreshSaved() {
  const ul = $("savedlist");
  try {
    const res = await fetch("/api/portfolios");
    const rows = await res.json();
    if (!res.ok) throw new Error(rows.error || `Server error (${res.status})`);
    ul.replaceChildren();
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "empty-row";
      li.textContent = "Nothing saved yet — hit Save above.";
      ul.appendChild(li);
      return;
    }
    for (const row of rows) ul.appendChild(savedRow(row));
  } catch (err) {
    showError(err.message);
  }
}

function savedRow(row) {
  const li = document.createElement("li");

  const load = document.createElement("button");
  load.type = "button";
  load.className = "linkish";
  load.textContent = row.name;
  load.title = "Load this portfolio and analyze it";
  load.addEventListener("click", () => loadSaved(row.id));

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent =
    `${row.tickers.join(" · ")} — ${row.method}, ` +
    `saved ${row.updated_at.slice(0, 10)}`;

  const share = document.createElement("a");
  share.className = "chip";
  share.href = `/p/${row.id}`;
  share.textContent = "link";
  share.title = "Shareable page for this portfolio";

  const del = document.createElement("button");
  del.type = "button";
  del.className = "rm";
  del.textContent = "×";
  del.setAttribute("aria-label", `Delete ${row.name}`);
  // two-step delete: no confirm() dialog (they block automation)
  del.addEventListener("click", () => {
    if (del.dataset.armed) {
      deleteSaved(row.id);
    } else {
      del.dataset.armed = "1";
      del.textContent = "delete?";
      del.classList.add("armed");
    }
  });

  li.append(load, meta, share, del);
  return li;
}

async function deleteSaved(id) {
  showError("");
  try {
    const res = await fetch(`/api/portfolios/${id}`, {
      method: "DELETE",
      headers: { "X-CSRFToken": csrftoken() },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Server error (${res.status})`);
    }
    if (state.savedId === id) {
      state.savedId = null;
      state.savedName = "";
      $("savecopy").hidden = true;
      $("sharerow").hidden = true;
    }
  } catch (err) {
    showError(err.message);
  }
  refreshSaved();
}

async function loadSaved(id) {
  showError("");
  try {
    const res = await fetch(`/api/portfolios/${id}`);
    const cfg = await res.json();
    if (!res.ok) throw new Error(cfg.error || `Server error (${res.status})`);
    applyConfig(cfg);
    $("sharelink").value = cfg.url;
    $("sharerow").hidden = false;
    analyze();
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
$("analyze").addEventListener("click", analyze);
$("equalw").addEventListener("click", () => {
  state.weights = {};
  renderAssets();
  analyze();
});
$("tangentw").addEventListener("click", () => {
  if (state.result && state.result.tangency) {
    useWeights(state.result.tangency.weights);
  } else {
    showError("Run Analyze first — the tangent portfolio comes from the optimization.");
  }
});
$("forecast").addEventListener("click", runForecast);
// The anchor redraws the fan on the spot (no re-analyze): seeing the
// whole chart swing on this one number is the point of the control.
for (const id of ["fanchor", "fanchorvalue"]) {
  $(id).addEventListener("change", () => {
    anchorParams();                       // keep the custom box in sync
    if (!$("fchart").hidden) runForecast();
  });
}
$("settarget").addEventListener("click", async () => {
  // Send the considered mix to the account as its new setpoint, then
  // open the transition plan there. Weights are total-wealth fractions,
  // so a CAL mix carries its cash share implicitly.
  if (!state.selected) return;
  try {
    const res = await fetch("/api/account/target", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify({ weights: state.selected.weights }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    window.location.href = "/account?plan=1";
  } catch (err) {
    showError(err.message);
  }
});
$("adoptpoint").addEventListener("click", () => {
  if (state.selected) useWeights(state.selected.weights);
});

$("save").addEventListener("click", () => showSavePanel($("savepanel").hidden));
$("savecancel").addEventListener("click", () => showSavePanel(false));
$("saveform").addEventListener("submit", (e) => {
  e.preventDefault();
  savePortfolio(false);
});
$("savecopy").addEventListener("click", () => savePortfolio(true));
$("sharelink").addEventListener("focus", (e) => e.target.select());
$("copylink").addEventListener("click", async () => {
  const link = $("sharelink");
  link.select();
  try {
    await navigator.clipboard.writeText(link.value);
  } catch {
    document.execCommand("copy"); // older browsers / insecure origins
  }
  $("copylink").textContent = "Copied";
  setTimeout(() => { $("copylink").textContent = "Copy"; }, 1500);
});
$("saved").addEventListener("click", () => {
  const open = $("savedpanel").hidden;
  $("savedpanel").hidden = !open;
  $("saved").setAttribute("aria-expanded", String(open));
  if (open) refreshSaved();
});

(async function init() {
  if (!localStorage.getItem("condor_hint_done")) $("hintstrip").hidden = false;
  $("hintdismiss").addEventListener("click", () => {
    localStorage.setItem("condor_hint_done", "1");
    $("hintstrip").hidden = true;
  });
  wireChartClicks();
  await loadTickers();
  const presetEl = $("preset"); // /p/<uuid> injects the saved config
  if (presetEl) {
    applyConfig(JSON.parse(presetEl.textContent));
    $("sharelink").value = window.location.href;
    $("sharerow").hidden = false;
  }
  renderAssets();
  renderQuickAdd();
  analyze(); // first paint: the shared portfolio, else the deck's example
})();
