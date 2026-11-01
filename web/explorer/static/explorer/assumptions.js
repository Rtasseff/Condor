/* "Under my assumptions" card on Optimize (docs/decisions/0008).
 *
 * Presentation only: the editor builds an assumptions object (percent in the
 * boxes, fractions on the wire), /api/analyze returns `assumed`, and this file
 * draws it. All numbers come from the server. Loaded after app.js, whose
 * `asmHooks`, `$` and `pct` it uses. */
"use strict";

const asm = {
  on: false,          // the user asked for the comparison
  id: null,           // saved set loaded in the editor, if any
  histOnly: false,
  mp: "", t0: "20", ref: "VT",          // text as typed (percent for mp)
  bounds: {},         // ticker -> {min, max} as typed, percent
  groups: [],         // [{tickers: [...], min, max}]
  views: [],          // [{ticker, ret, sd}] percent
  sets: [],           // saved-set list rows
  built: false,
};

const asmFrac = (txt, field) => {
  const t = String(txt).trim();
  if (t === "") return null;
  const v = Number(t);
  if (!isFinite(v)) throw new Error(`${field} must be a number.`);
  return +(v / 100).toFixed(8);
};
const asmTxt = (frac) => (frac == null ? "" : String(+(100 * frac).toFixed(4)));

function asmMk(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") el.textContent = v;
    else if (k === "class") el.className = v;
    else if (k in el) el[k] = v;
    else el.setAttribute(k, v);
  }
  el.append(...kids);
  return el;
}

// ---------- editor state -> request ----------
function asmBuild() {
  const name = ($("asmname").value || "").trim() || "My assumptions";
  const bounds = {};
  for (const [t, b] of Object.entries(asm.bounds)) {
    const lo = asmFrac(b.min, `${t} minimum`), hi = asmFrac(b.max, `${t} maximum`);
    if (lo == null && hi == null) continue;
    bounds[t] = {};
    if (lo != null) bounds[t].min = lo;
    if (hi != null) bounds[t].max = hi;
  }
  const groups = [];
  for (const g of asm.groups) {
    if (!g.tickers.length) continue;
    const lo = asmFrac(g.min, "group minimum"), hi = asmFrac(g.max, "group maximum");
    if (lo == null && hi == null) continue;
    const out = { tickers: g.tickers.slice() };
    if (lo != null) out.min = lo;
    if (hi != null) out.max = hi;
    groups.push(out);
  }
  const views = [];
  for (const v of asm.views) {
    if (!v.ticker || String(v.ret).trim() === "") continue;
    views.push({
      ticker: v.ticker,
      ret: asmFrac(v.ret, `${v.ticker} view`),
      sd: asmFrac(v.sd, `${v.ticker} view ± points`),
    });
  }
  const t0 = Number(String(asm.t0).trim() === "" ? 20 : asm.t0);
  if (!isFinite(t0)) throw new Error("Weight of the long-run view must be a number.");
  return {
    name,
    prior: {
      kind: asm.histOnly ? "history" : "equilibrium",
      reference: (asm.ref || "VT").trim().toUpperCase(),
      market_premium: asmFrac(asm.mp, "Market premium"),
      t0,
      views,
    },
    constraints: { bounds, groups },
  };
}

// ---------- request / response hooks ----------
asmHooks.request = () => {
  if (!asm.on) return null;
  try {
    asmShowError("");
    return asmBuild();
  } catch (err) {
    asm.on = false;
    asmShowError(err.message);
    asmSyncButtons();
    return null;
  }
};

function asmShowError(msg) {
  const e = $("asmerror");
  e.textContent = msg;
  e.hidden = !msg;
}

function asmSyncButtons() {
  $("asmoff").hidden = !asm.on;
  $("asmrun").textContent = asm.on
    ? "Update the comparison" : "Show the best mix under these";
}

asmHooks.render = (assumed) => {
  const box = $("asmresult");
  $("asmchip").hidden = true;
  if (!asm.on || !assumed) { box.hidden = true; return; }
  if (assumed.error) {
    box.hidden = true;
    asmShowError(`Couldn't compute this: ${assumed.error}`);
    return;
  }
  asmShowError("");
  box.hidden = false;
  $("asmtitle").textContent = `Under: ${assumed.name}`;
  $("asmcolunder").textContent = `Under: ${assumed.name}`;
  $("asmchip").textContent = assumed.name;
  $("asmchip").hidden = false;
  if (assumed.prior_note && assumed.prior_note.market_premium != null)
    $("asmmp").placeholder = `${(100 * assumed.prior_note.market_premium).toFixed(1)} (default)`;
  $("asmnote").textContent = asmNote(assumed.prior_note, state.result.method);
  drawFrontier("chart-assumed", assumed, { clickable: false });
  asmCompare(state.result, assumed);
  asmGaps(assumed);
};

function asmNote(n, method) {
  if (!n) return "";
  if (n.kind === "history")
    return "Using your history only; any views you added sit on top of it.";
  const yrs = (x) => (+x.toFixed(1)).toString();
  let s = `The long-run view counts as ${yrs(n.t0)} years of data; ` +
          `your history as ${yrs(n.t_effective)} years.`;
  if (n.t_effective < n.t_years - 1e-9)
    s += " (Robust method: history counts less.)";
  s += ` Market premium ${pct(n.market_premium)} a year, measured against ${n.reference}.`;
  return s;
}

// ---------- compare table ----------
function asmCompare(hist, under) {
  const tb = $("asmcompare").querySelector("tbody");
  tb.replaceChildren();
  const cell = (txt) => asmMk("td", { class: "num", text: txt });
  const sec = (txt) => tb.append(asmMk("tr", {}, asmMk("th", {
    class: "sec", colSpan: 3, scope: "colgroup", text: txt })));
  const none = "n/a";
  sec("Best mix (max Sharpe)");
  const hw = hist.tangency ? hist.tangency.weights : null;
  const uw = under.tangency ? under.tangency.weights : null;
  const tick = state.assets.filter((t) =>
    ((hw && hw[t]) || 0) > 0.0005 || ((uw && uw[t]) || 0) > 0.0005);
  for (const t of tick) {
    tb.append(asmMk("tr", {}, asmMk("th", { scope: "row", text: t }),
      cell(hw ? pct(hw[t] || 0) : none), cell(uw ? pct(uw[t] || 0) : none)));
  }
  if (!hw || !uw) {
    tb.append(asmMk("tr", {}, asmMk("td", { colSpan: 3, class: "sub",
      text: "No mix beats the risk-free rate" +
        (!hw && !uw ? " in either view." : !hw ? " on history alone." :
         " under these limits.") })));
  }
  sec("Your portfolio");
  const row = (label, a, b) => tb.append(asmMk("tr", {},
    asmMk("th", { scope: "row", text: label }), cell(a), cell(b)));
  row("Expected return", pct(hist.portfolio.ret), pct(under.portfolio.ret));
  row("Dispersion", pct(hist.portfolio.vol), pct(under.portfolio.vol));
  row("Sharpe ratio", hist.portfolio.sharpe.toFixed(2), under.portfolio.sharpe.toFixed(2));
}

// ---------- the three gaps ----------
function asmGaps(under) {
  const g = under.gaps || {};
  const dl = $("asmgaps");
  dl.replaceChildren();
  const pts = (x) => `${(100 * x).toFixed(2)} points`;
  // why a gap is n/a, in words that match the real cause
  const why = {
    no_tangency: "no mix within your limits beats the risk-free rate",
    solver: "the optimizer couldn't finish this comparison",
  };
  const rows = [
    ["Risk-adjusted return (Sharpe) gap", g.sharpe_gap, (x) => x.toFixed(2),
     why[g.sharpe_gap_reason]],
    ["Return you could add at the same risk", g.return_gap, pts,
     g.return_gap_reason === "below_range"
       ? "your portfolio is steadier than any mix your limits allow"
       : why[g.return_gap_reason]],
    ["Risk you could shed at the same return", g.risk_gap, pts,
     g.risk_gap_reason === "below_range"
       ? "your portfolio earns less than any mix your limits allow"
       : g.risk_gap_reason === "above_range"
       ? "your portfolio earns more than any mix your limits allow"
       : why[g.risk_gap_reason]],
  ];
  for (const [label, val, fmt, reason] of rows) {
    dl.append(asmMk("dt", { text: label }));
    dl.append(val == null
      ? asmMk("dd", { class: "na", text: `n/a: ${reason || "no comparison available"}` })
      : asmMk("dd", { text: fmt(val) }));
  }
  const vio = $("asmviolations");
  const list = g.violations || [];
  vio.hidden = !list.length;
  vio.querySelector("ul").replaceChildren(
    ...list.map((v) => asmMk("li", { text: v })));
  const ign = (under.constraints && under.constraints.ignored) || [];
  const note = $("asmignored");
  note.hidden = !ign.length;
  note.textContent = ign.length
    ? `Not used here: ${ign.join("; ")}.` : "";
}

// ---------- editor rendering ----------
function asmRenderLimits() {
  const tb = $("asmlimits").querySelector("tbody");
  tb.replaceChildren();
  for (const t of state.assets) {
    const b = asm.bounds[t] || (asm.bounds[t] = { min: "", max: "" });
    const mk = (key, ph) => {
      const inp = asmMk("input", { type: "number", min: "0", max: "100",
        step: "1", value: b[key], placeholder: ph });
      inp.setAttribute("aria-label", `${t} ${key === "min" ? "at least" : "at most"} %`);
      inp.addEventListener("input", () => { b[key] = inp.value; });
      return asmMk("td", { class: "num" }, inp);
    };
    tb.append(asmMk("tr", {}, asmMk("th", { scope: "row", text: t }),
      mk("min", "0"), mk("max", "100")));
  }
  asmRenderGroups();
  asmRenderViews();
}

function asmRenderGroups() {
  const box = $("asmgroups");
  box.replaceChildren();
  asm.groups.forEach((g, i) => {
    const row = asmMk("div");
    for (const t of state.assets) {
      const cb = asmMk("input", { type: "checkbox", checked: g.tickers.includes(t) });
      cb.addEventListener("change", () => {
        g.tickers = cb.checked ? [...g.tickers, t] : g.tickers.filter((x) => x !== t);
      });
      row.append(asmMk("label", { class: "chk" }, cb, t));
    }
    const num = (key, label) => {
      const inp = asmMk("input", { type: "number", min: "0", max: "100",
        step: "1", value: g[key], placeholder: label });
      inp.setAttribute("aria-label", `Group ${label}`);
      inp.addEventListener("input", () => { g[key] = inp.value; });
      return inp;
    };
    const rm = asmMk("button", { type: "button", class: "rm", text: "×" });
    rm.setAttribute("aria-label", "Remove this group limit");
    rm.addEventListener("click", () => { asm.groups.splice(i, 1); asmRenderGroups(); });
    row.append(num("min", "at least %"), num("max", "at most %"), rm);
    box.append(row);
  });
}

function asmRenderViews() {
  const box = $("asmviews");
  box.replaceChildren();
  asm.views.forEach((v, i) => {
    const sel = asmMk("select");
    sel.setAttribute("aria-label", "View asset");
    const tickers = state.assets.includes(v.ticker) || !v.ticker
      ? state.assets : [...state.assets, v.ticker];
    for (const t of tickers) sel.append(asmMk("option", { value: t, text: t }));
    if (!v.ticker && state.assets.length) v.ticker = state.assets[0];
    sel.value = v.ticker;
    sel.addEventListener("change", () => { v.ticker = sel.value; });
    const num = (key, label) => {
      const inp = asmMk("input", { type: "number", step: "0.5", value: v[key],
        placeholder: label });
      inp.setAttribute("aria-label", label);
      inp.addEventListener("input", () => { v[key] = inp.value; });
      return inp;
    };
    const rm = asmMk("button", { type: "button", class: "rm", text: "×" });
    rm.setAttribute("aria-label", "Remove this view");
    rm.addEventListener("click", () => { asm.views.splice(i, 1); asmRenderViews(); });
    box.append(asmMk("div", {}, sel, num("ret", "expected return %"),
      asmMk("span", { class: "sub", text: "±" }), num("sd", "± points"),
      asmMk("span", { class: "sub", text: "points" }), rm));
  });
}

function asmRenderPrior() {
  $("asmhistonly").checked = asm.histOnly;
  $("asmmp").value = asm.mp;
  $("asmt0").value = asm.t0;
  $("asmref").value = asm.ref;
  for (const id of ["asmmp", "asmt0", "asmref"]) $(id).disabled = asm.histOnly;
}

asmHooks.assetsChanged = () => { if ($("asmlimits")) asmRenderLimits(); };

// ---------- saved sets ----------
const asmAuth = () => !!$("asmsaved");
const asmHeaders = () => ({ "Content-Type": "application/json", "X-CSRFToken": csrftoken() });

function asmSay(msg) {
  const el = $("asmstatus");
  el.textContent = msg;
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 3000);
}

async function asmApi(url, opts = {}) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
  return data;
}

async function asmRefreshSets(selectId) {
  if (!asmAuth()) return;
  try {
    asm.sets = await asmApi("/api/assumptions");
  } catch (err) { asmShowError(err.message); return; }
  const sel = $("asmsaved");
  sel.replaceChildren(asmMk("option", { value: "", text: "New (not saved)" }),
    ...asm.sets.map((r) => asmMk("option", { value: r.id, text: r.name })));
  sel.value = selectId || asm.id || "";
  asmSyncSaveButtons();
}

function asmSyncSaveButtons() {
  if (!asmAuth()) return;
  $("asmsavenew").hidden = !asm.id;
  $("asmdelete").hidden = !asm.id;
  const d = $("asmdelete");
  d.textContent = "Delete";
  delete d.dataset.armed;
}

// Copy a saved payload into the editor. The saved set is never touched again
// until Save; analysis sends this editor's contents as a copy.
function asmLoad(id, a) {
  asm.id = id;
  $("asmname").value = a.name;
  asm.histOnly = a.prior.kind === "history";
  asm.mp = asmTxt(a.prior.market_premium);
  asm.t0 = String(a.prior.t0);
  asm.ref = a.prior.reference;
  asm.bounds = {};
  for (const [t, b] of Object.entries(a.constraints.bounds || {})) {
    asm.bounds[t] = { min: asmTxt(b.min), max: b.max == null ? "" : asmTxt(b.max) };
  }
  asm.groups = (a.constraints.groups || []).map((g) => ({
    tickers: g.tickers.slice(), min: asmTxt(g.min),
    max: g.max == null ? "" : asmTxt(g.max) }));
  asm.views = (a.prior.views || []).map((v) => ({
    ticker: v.ticker, ret: asmTxt(v.ret), sd: asmTxt(v.sd) }));
  asmRenderPrior();
  asmRenderLimits();
  asmSyncSaveButtons();
}

async function asmSave(asNew) {
  asmShowError("");
  let payload;
  try { payload = asmBuild(); } catch (err) { asmShowError(err.message); return; }
  const update = asm.id && !asNew;
  try {
    const data = await asmApi(update ? `/api/assumptions/${asm.id}` : "/api/assumptions", {
      method: update ? "PUT" : "POST", headers: asmHeaders(),
      body: JSON.stringify(payload) });
    asm.id = data.id;
    asmSay(`Saved “${data.name}”.`);
    await asmRefreshSets(data.id);
  } catch (err) { asmShowError(err.message); }
}

async function asmDelete() {
  const d = $("asmdelete");
  if (!d.dataset.armed) {      // two steps, no confirm() dialog
    d.dataset.armed = "1";
    d.textContent = "Delete? Click again";
    return;
  }
  try {
    await asmApi(`/api/assumptions/${asm.id}`, { method: "DELETE", headers: asmHeaders() });
    asm.id = null;
    asmSay("Deleted.");
    await asmRefreshSets("");
  } catch (err) { asmShowError(err.message); }
}

// ---------- wiring ----------
function asmWire() {
  if (asm.built) return;
  asm.built = true;
  $("asmhistonly").addEventListener("change", (e) => {
    asm.histOnly = e.target.checked;
    asmRenderPrior();
  });
  for (const [id, key] of [["asmmp", "mp"], ["asmt0", "t0"], ["asmref", "ref"]]) {
    $(id).addEventListener("input", (e) => { asm[key] = e.target.value; });
  }
  $("asmaddgroup").addEventListener("click", () => {
    asm.groups.push({ tickers: [], min: "", max: "" });
    asmRenderGroups();
  });
  $("asmaddview").addEventListener("click", () => {
    asm.views.push({ ticker: state.assets[0] || "", ret: "", sd: "" });
    asmRenderViews();
  });
  $("asmrun").addEventListener("click", () => {
    asm.on = true;
    asmSyncButtons();
    analyze();
  });
  $("asmoff").addEventListener("click", () => {
    asm.on = false;
    asmShowError("");
    asmSyncButtons();
    $("asmresult").hidden = true;
    $("asmchip").hidden = true;
  });
  if (asmAuth()) {
    $("asmsave").addEventListener("click", () => asmSave(false));
    $("asmsavenew").addEventListener("click", () => asmSave(true));
    $("asmdelete").addEventListener("click", asmDelete);
    $("asmsaved").addEventListener("change", async (e) => {
      asmShowError("");
      if (!e.target.value) { asm.id = null; asmSyncSaveButtons(); return; }
      try {
        const d = await asmApi(`/api/assumptions/${e.target.value}`);
        asmLoad(d.id, d.assumptions);
      } catch (err) { asmShowError(err.message); }
    });
    asmRefreshSets();
  }
  asmRenderPrior();
  asmSyncButtons();
}

if ($("asmcard")) asmWire();
