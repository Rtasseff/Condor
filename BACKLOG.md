# Condor v2 — Backlog

Prioritized. "Now" = next things to pick up; "Next" = after the core is
solid; "Later" = the pitch-deck vision beyond the prototype. Items carry a
one-line why and, where useful, a pointer to the legacy source of the idea.

## Now

Not yet ordered — the newest items (UI review, CLI) were added 2026-08-19
and the sequence is still to be decided.

- [ ] **UI review pass** — RT navigates the current prototype end to end and
  writes down everything that is off: bugs (wrong/missing behaviour), rough
  edges (things that work but feel wrong), and missing features. Output is
  a list in this file (or a `UI-NOTES.md`) with each item tagged bug / UX /
  feature, so the polish work below can be prioritized from evidence
  rather than guesses. Precedes "UI polish" and "API/UX robustness".
- [ ] **CLI** (`python -m condor …`, later a `condor` console script):
  thin boundary over the object API — argument parsing and table/CSV
  output only, no numerics (same rule as `views.py`, see ARCHITECTURE.md).
  Commands: `analyze TICKERS [--method --rf --years]` (summary table,
  min-vol and tangency weights), `portfolio T=w T=w …` (perf of a given
  mix), `frontier … [--csv|--json]`, `data update|ls|purge`. No database
  beyond the price store — for personal use and one-off questions without
  starting Django. Doubles as a second consumer of `condor/` that keeps the
  layering honest. Optional `--html` to write a Plotly chart.
- [ ] **Explorer: wire the data layer in** — prefill the risk-free field
  from `risk_free_rate()` (show maturity + as-of), and show "data as of
  <last trading day>" (`PriceStore.as_of`) next to results. Small; pairs
  well with the UI review pass.
- [ ] **Verification notebook** (`notebooks/01_verify_core.ipynb`): the same
  spot-check story as `202411_refact_optWF.ipynb` — hand-computed value next
  to function output, legacy vs v2 side by side, notebook golden numbers —
  for interactive inspection. `tests/test_verification.py` is the durable
  version; the notebook is the readable one.
- [ ] **Return-calculation options** matching legacy: `metric` (relative /
  log), `timeFrame` (D / M with 21-day lag), sampling interval (`sampInt`,
  legacy default 20 to de-overlap monthly windows), and geometric-vs-
  arithmetic expected return as an explicit choice (pypfopt defaults to
  geometric; v2 forces arithmetic to match legacy — see `stats.py`).
- [ ] **Save portfolios** — first real DB models (Portfolio, Holding,
  AnalysisSnapshot), shareable URL per portfolio; users/auth later.

## Next

- [ ] **Estimation uncertainty / sampling study** — revive the question
  behind the legacy `202411_apa_*.ipynb` work (autocorrelation, sampling
  interval, convergence), reframed: dispersion (Σ) converges fast and
  daily sampling + shrinkage handle it; expected return (μ) does NOT —
  its standard error depends only on the total time span (Merton 1980),
  ≈ σ/√years regardless of sampling frequency, so no interval choice
  rescues it. Deliverables: quantify standard errors for both estimators,
  decide what honesty looks like in the UI (error bars / bands on the
  frontier?), and document why robust stats + (later) Black-Litterman
  views are the mitigation. Park: `sampInt`-style de-overlapping matters
  only if we add monthly windows (see return-calculation options above).
- [ ] **Forecaster** ("Forecast" button, deck slide 25): fan chart with 65%
  and 95% bands, backtest-from-2-years-ago vs project-2-years-forward.
  Start with geometric Brownian motion / bootstrap of historical returns
  (legacy: `analytics_workflow_v1.ipynb` Part 3, GBM cell); RF/LSTM ideas
  from the same notebook are lower priority and need honest validation.
- [ ] **Rebalancing & dollar-cost-averaging recommendations.** Drift from
  target weights, calendar vs threshold rules, DCA schedule simulator.
  References: `reference materials/Portfolio-ManagementProcess/
  Kritzman2008-Portfolio_Rebalancing…`, `MRebalancing.pdf`.
- [ ] **Scenario simulators** — "what if 2008 / 2020 / rates +3%" replay on
  the current portfolio; Monte Carlo on the estimated μ/Σ.
- [ ] **Optimization constraints:** per-asset max weight, min position,
  sector caps, cardinality (max N holdings), leverage/shorting toggle.
  pypfopt supports most; cardinality needs MIQP or heuristics
  (legacy reading list: `reference materials/portfolio-optimization/`
  cardinality papers).
- [ ] **Bayesian views / Black-Litterman** — the notebook intro mentions
  "a bayesian approach to incorporate expectations derived from other
  sources"; pypfopt has `BlackLittermanModel`. Reference:
  `Black-GlobalPortfolioOptimization-1992.pdf`.
- [ ] **Asset pre-assessment / screening** (legacy `assetPreassess.py`,
  `202411_apa_*.ipynb`): trend fit, drawdown, per-asset stats page;
  sector correlation matrix view (`analytics_workflow_v1` Part 1) to
  guide diversification.
- [ ] **"Suggest" button** — propose additions that improve the frontier
  (lowest-correlation candidates from a universe).
- [ ] **UI polish:** weights that don't sum to 100 (show normalized preview
  live), hover-to-preview a frontier point before clicking, mobile layout,
  keyboard access for the chart's frontier points, loading skeletons.
- [ ] **API/UX robustness:** async fetch with progress, rate-limit and
  retry on yfinance, request timeouts, cache warming for the quick-add list.

## Later (deck vision)

- [ ] **Learn integration** — info boxes with "learning clips" / "technical
  details" links on every concept (Market Expectations, Easy Choice, Tangent
  Portfolio, T-bills…). Content plan lives in `drive_export/text/ExCom/`
  scripts.
- [ ] **Explorer landing view** (deck slides 17–22): S&P 500 "Market
  Expectations" trend chart, "Easy Choice" SPY, "Your Choice" plane with
  Bland/Bad Investment teaching corners.
- [ ] **Compete:** leaderboards (public/private), portfolio sharing, chat.
- [ ] **Users & auth**, then **broker order facilitation** (report/CSV first).
- [ ] **Deployment:** Docker, Postgres, hosted (AWS per original plan), CI
  running the verification suite.
- [ ] **Open-source hygiene:** LICENSE, CONTRIBUTING, public repo when ready
  (rotate the old credentials first — see CONTEXT.md).

## Done

- [x] **Data layer v2 — store + sources** (`condor/data/`) — 2026-08-22.
      `PriceStore`: one Parquet per ticker in `~/.condor/prices`
      (`CONDOR_DATA_DIR` to move), incremental updates with a
      corporate-action seam check (ADR 0001), provenance manifest,
      `as_of()`; flat files not a DB (ADR 0002). Sources behind one
      protocol: yfinance default, Tiingo failover when `TIINGO_API_KEY`
      is set (primary by request). `risk_free_rate()` from FRED Treasury
      constant-maturity yields (3m default; 1m/1y/10y). `fetch_prices`
      contract unchanged — web app untouched. Dropped along the way:
      Polygon loader (never really used; snapshot in `drive_export/` is
      2yr/Apr-2024, worse than free sources) and Stooq (now fronts its
      CSV endpoint with a JS proof-of-work challenge — not scriptable).
      +12 tests offline via a scripted fake source, live smoke tests
      behind `CONDOR_NET_TESTS=1`.
- [x] **Domain model** `Asset` → `AssetSet` → `Portfolio`, plus `Frontier`
      (`condor/model.py`) — 2026-08-19. Thin object layer over the unchanged
      engine; `compute_analysis` is now a facade over `AssetSet.analysis()`.
      Deviations from the original plan, on purpose: `Asset` is identity-only
      (stats are estimated for the set, vectorized, never per asset);
      `Portfolio` *has* an `AssetSet` rather than inheriting; the "asset of
      assets" idea is delivered via `Portfolio.returns` / `value_index` +
      `AssetSet.from_members`. Verification suite passed unchanged;
      `tests/test_model.py` adds 32 tests pinning objects to engine.
- [x] Context consolidation (`context/`, `drive_export/`) — 2026-08-10
- [x] Analytics core, procedural (`condor/`) + Django Explorer (`web/`) — 2026-08-10
- [x] Verification suite vs legacy code, closed-form Markowitz, and notebook
      golden numbers (`tests/test_verification.py`, 20 tests) — 2026-08-18
- [x] Fix: normal expected return was geometric (pypfopt default); now
      arithmetic ×252 to match legacy and the robust method — 2026-08-18
- [x] Fix: CoMAD NaN semantics now identical to legacy pairwise-complete
      medians — 2026-08-18
