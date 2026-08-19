# Condor v2 — Backlog

Prioritized. "Now" = next things to pick up; "Next" = after the core is
solid; "Later" = the pitch-deck vision beyond the prototype. Items carry a
one-line why and, where useful, a pointer to the legacy source of the idea.

## Now

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
- [ ] **Data source hardening.** yfinance is convenient and free but
  unofficial and brittle. Add: offline loader for the legacy Polygon/S&P
  CSVs (`drive_export/files/data_analytics_v1/`), a provider interface so
  Polygon.io / Tiingo / Alpha Vantage / EODHD can slot in, cache
  invalidation strategy, and clear "data as of" messaging in the UI.
- [ ] **Save portfolios** — first real DB models (Portfolio, Holding,
  AnalysisSnapshot), shareable URL per portfolio; users/auth later.

## Next

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
