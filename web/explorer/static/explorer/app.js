/* Condor Funds v2 — Portfolio Explorer front end. */
"use strict";

// ---------- palette (validated for CVD on this surface) ----------
const C = {
  surface: "#121a2b",
  ink: "#f2f5fa",
  ink2: "#b7c0d0",
  muted: "#8791a5",
  grid: "#1e2a44",
  axis: "#2c3a5c",
  frontier: "#3987e5",
  cal: "#d55181",
  you: "#c98500",
};

// ---------- state ----------
const state = {
  assets: ["AAPL", "MSFT", "JNJ", "ABBV", "XOM", "CVX", "COP"], // deck's example
  weights: {},          // ticker -> percent (UI units); empty = equal
  names: {},            // ticker -> company name (from bundled list)
  result: null,         // last /api/analyze payload
  selected: null,       // selected frontier point (or named portfolio)
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
  const btn = $("analyze");
  btn.disabled = true;
  $("status").textContent = "Fetching prices & optimizing…";
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
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    $("status").textContent = "";
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

function renderChart() {
  const r = state.result;
  if (!r) return;
  $("chart-empty").style.display = "none";

  const traces = [];
  const annotations = [];

  // capital allocation line (under everything)
  if (r.cal) {
    traces.push({
      x: r.cal.x, y: r.cal.y,
      mode: "lines", name: "Capital allocation line",
      line: { color: C.cal, width: 2, dash: "dash" },
      hoverinfo: "skip",
    });
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

  // min-vol (leftmost frontier point) — labeled ink marker, not a series
  if (r.min_vol) {
    traces.push({
      x: [r.min_vol.vol], y: [r.min_vol.ret],
      mode: "markers", name: "Min dispersion", showlegend: false,
      marker: {
        size: 11, symbol: "square", color: C.ink,
        line: { color: C.surface, width: 2 },
      },
      hovertemplate:
        "Minimum dispersion · reward %{y:.1%} · risk %{x:.1%}<extra></extra>",
    });
    annotations.push({
      x: r.min_vol.vol, y: r.min_vol.ret,
      text: "Min dispersion", showarrow: true, arrowcolor: C.axis,
      ax: -60, ay: 20, font: { color: C.ink2, size: 12 },
    });
  }

  // tangency — frontier-blue diamond with ring + label
  if (r.tangency) {
    traces.push({
      x: [r.tangency.vol], y: [r.tangency.ret],
      customdata: [[r.tangency.sharpe]],
      mode: "markers", name: "Tangent portfolio", showlegend: false,
      marker: {
        size: 15, symbol: "diamond", color: C.frontier,
        line: { color: C.ink, width: 2 },
      },
      hovertemplate:
        "'Reasonable guess' tangent · reward %{y:.1%} · risk %{x:.1%}" +
        " · Sharpe %{customdata[0]:.2f}<br><i>click to inspect</i><extra></extra>",
    });
    annotations.push({
      x: r.tangency.vol, y: r.tangency.ret,
      text: "'Reasonable guess'<br>tangent portfolio",
      showarrow: true, arrowcolor: C.axis,
      ax: -80, ay: -40, font: { color: C.ink2, size: 12 },
    });
  }

  // risk-free anchor
  annotations.push({
    x: 0, y: r.risk_free_rate,
    text: "US T-bills<br>(risk-free)", showarrow: true, arrowcolor: C.axis,
    ax: 30, ay: 30, font: { color: C.ink2, size: 12 },
  });
  traces.push({
    x: [0], y: [r.risk_free_rate],
    mode: "markers", name: "Risk-free", showlegend: false,
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
    mode: "markers", name: "Your choice",
    marker: {
      size: 14, color: C.you, symbol: "circle",
      line: { color: C.ink, width: 2 },
    },
    hovertemplate:
      "Your choice · reward %{y:.1%} · risk %{x:.1%}" +
      " · Sharpe %{customdata[0]:.2f}<extra></extra>",
  });
  annotations.push({
    x: p.vol, y: p.ret,
    text: "Your choice", showarrow: true, arrowcolor: C.axis,
    ax: 45, ay: 25, font: { color: C.you, size: 12 },
  });

  const layout = {
    paper_bgcolor: C.surface,
    plot_bgcolor: C.surface,
    font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: C.ink2 },
    margin: { l: 70, r: 20, t: 10, b: 55 },
    xaxis: {
      title: { text: "Risk — annualized dispersion (σ)", font: { color: C.muted } },
      tickformat: ".0%", gridcolor: C.grid, zerolinecolor: C.axis,
      rangemode: "tozero",
    },
    yaxis: {
      title: { text: "Reward — expected annual return", font: { color: C.muted } },
      tickformat: ".0%", gridcolor: C.grid, zerolinecolor: C.axis,
    },
    legend: {
      orientation: "h", x: 0, y: 1.08,
      font: { color: C.ink2, size: 12 },
    },
    hoverlabel: hoverStyle(),
    annotations,
  };

  Plotly.newPlot("chart", traces, layout, {
    displayModeBar: false, responsive: true,
  }).then((gd) => {
    gd.on("plotly_click", (ev) => {
      const pt = ev.points && ev.points[0];
      if (!pt) return;
      if (pt.data.name === "Efficient frontier") {
        selectPoint(state.result.frontier[pt.pointIndex],
          `Frontier point ${pt.pointIndex + 1} of ${state.result.frontier.length}`);
      } else if (pt.data.name === "Tangent portfolio") {
        selectPoint(state.result.tangency, "'Reasonable guess' — tangent portfolio");
      }
    });
  });
}

function renderTiles() {
  const p = state.result.portfolio;
  $("tiles").hidden = false;
  $("t-ret").textContent = pct(p.ret);
  $("t-vol").textContent = pct(p.vol);
  $("t-sharpe").textContent = p.sharpe.toFixed(2);
}

function selectPoint(point, title) {
  state.selected = { ...point, title };
  renderPoint(state.selected);
  $("pointcard").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderPoint(sel) {
  const card = $("pointcard");
  if (!sel) { card.hidden = true; return; }
  card.hidden = false;
  $("pointtitle").textContent = sel.title || "Selected portfolio";
  $("pointstats").textContent =
    `Reward ${pct(sel.ret)} · risk ${pct(sel.vol)} · Sharpe ${sel.sharpe.toFixed(2)}`;

  const box = $("pointweights");
  box.replaceChildren();
  const entries = Object.entries(sel.weights).sort((a, b) => b[1] - a[1]);
  for (const [t, w] of entries) {
    const row = document.createElement("div");
    row.className = "wrow";
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = t;
    const barwrap = document.createElement("div");
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.width = Math.max(1, 100 * w) + "%";
    barwrap.appendChild(bar);
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = pct(w);
    row.append(tick, barwrap, val);
    box.appendChild(row);
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
    `Based on ${r.n_days.toLocaleString()} trading days, ${r.start} to ${r.end}` +
    ` · ${r.method === "robust" ? "robust (median/CoMAD)" : "normal (mean/Ledoit-Wolf)"} statistics.`;
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
$("adoptpoint").addEventListener("click", () => {
  if (state.selected) useWeights(state.selected.weights);
});

(async function init() {
  await loadTickers();
  renderAssets();
  renderQuickAdd();
  analyze(); // first paint with the deck's example portfolio
})();
