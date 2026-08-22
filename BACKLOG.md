# Condor v2 — Backlog

Prioritized. "Now" = next things to pick up; "Next" = after the core is
solid; "Later" = the pitch-deck vision beyond the prototype. Items carry a
one-line why and, where useful, a pointer to the legacy source of the idea.

## Now

- [ ] **UI review pass** — RT navigates the current prototype end to end and
  writes down everything that is off: bugs (wrong/missing behaviour), rough
  edges (things that work but feel wrong), and missing features. Output is
  a list in this file (or a `UI-NOTES.md`) with each item tagged bug / UX /
  feature, so the polish work below can be prioritized from evidence
  rather than guesses. Precedes "UI polish" and "API/UX robustness".
- [ ] **Branding & theming readiness** — make restyling a one-block edit
  per docs/BRANDING.md (the contract) and ADR 0003 (stack decision:
  Django templates + tokens, no build step). Implementation: add
  `--font-body`/`--font-display` tokens; bridge the `app.js` chart
  palette to read CSS custom properties via `getComputedStyle` (kill the
  duplicated hex literals); fix the one hardcoded color (`#2a1520`
  error bg); create `static/explorer/brand/` with placeholder logo.svg +
  favicon wired into the template; extract `base.html` when a second
  page appears. Then the branding pass = new token values + new SVGs.
- [ ] **Release 0.1 to the old Condor team** (~5 trusted users) — after
  RT's UI review and the branding pass: pick a small host (Fly.io /
  Railway / small VPS + Docker), Postgres-or-sqlite decision at that
  scale, `DEBUG=0` settings hygiene (SECRET_KEY, ALLOWED_HOSTS, static
  serving). Pre-flight done early (2026-08-22): PriceStore now takes
  per-ticker + manifest POSIX file locks, so multiple web workers can
  share the store. No auth for 0.1 (unguessable URLs); users/auth Later.
## Next

- [ ] **Estimation uncertainty / sampling / regimes** — revive the
  question behind the legacy `202411_apa_*.ipynb` work (autocorrelation,
  sampling interval, convergence), reframed after discussion (2026-08-22):
  - *Sampling interval & independence.* Stats are computed on returns,
    not prices: daily returns are near-uncorrelated serially, so RT's
    "ensure AC≈0 before trusting n" rule is already satisfied for the Σ
    point estimate — finer sampling genuinely helps Σ. It does NOT help
    μ: μ's standard error depends only on total time span (Merton 1980),
    ≈ σ/√years however you slice it.
  - *But returns are uncorrelated, not independent*: volatility
    clustering (r² autocorrelated) means the effective n < nominal n, so
    naive error bars on Σ are too tight — use Newey-West or a block
    bootstrap when quantifying Σ uncertainty. `sampInt`-style
    de-overlapping matters only if monthly windows return (see
    return-calculation options above).
  - *Non-stationarity / regimes.* Piecewise-process view is sound
    (market-wide: Gramm-Leach-Bliley 1999 repealing Glass-Steagall,
    decimalization 2001, QE era 2008+; single names change even harder).
    Window length is a bias-variance tradeoff: long window = stale-regime
    bias, short window = variance explosion (fatal for μ: 3y ⇒ ±10%/yr
    SE). Mitigations in order of establishment: exponentially-weighted
    covariance for Σ (`pypfopt.risk_models.exp_cov`) as a third method —
    recency weighting without a cliff; lookback stays a visible user
    choice; structural-break detection (CUSUM / Bai-Perron) as part of
    asset pre-assessment (breaks in vol are detectable, breaks in mean
    mostly aren't); for μ, Black-Litterman equilibrium prior rather than
    trusting any window.
  - Deliverables: standard errors for both estimators (honest ones for
    Σ), what calibrated uncertainty looks like in the UI (error bars /
    bands on the frontier?), and the EWMA-covariance option.
- [ ] **Expose return-calculation options** in the Explorer (an
  "advanced" disclosure: metric, timeframe, basis) and the CLI (flags).
  Deliberately left out of the analysis payload so far — adding them is
  a payload change plus the key-set test in tests/test_model.py.
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
  structural-break flags (CUSUM / Bai-Perron — see estimation-uncertainty
  item) so a fundamentally-changed company is visible before it poisons
  estimates;
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

- [x] **Return-calculation options** — 2026-08-22. Engine (`stats.py`):
      `metric` relative/log, `timeframe` D/M (21-day windows, ×12
      annualization — factors pinned to legacy genFin), `samp_int`
      de-overlap sampling (legacy default 20 for M, applied after
      returns before estimators, exactly as CondorCoreObs sampled), and
      explicit `basis` arithmetic/geometric for the normal method.
      Threaded through `AssetSet` (keyword-only, immutable,
      `with_options()`), `analysis()`, `compute_analysis`. Defaults are
      byte-identical to prior behaviour. `Portfolio.value_index`
      generalized to the set's return grid (byte-identical for daily).
      77 new tests incl. legacy pins at 1e-12..1e-16 and mutation checks.

- [x] **Save portfolios** — 2026-08-22. `SavedPortfolio` + `Holding`
      Django models (storage only; weights stored as fractions),
      `POST/GET/DELETE /api/portfolios[/<uuid>]` sharing api_analyze's
      validation, shareable `/p/<uuid>` page that preloads the Explorer
      and auto-analyzes. UI: Save panel with name + copy-link, Saved
      list with load and two-step delete. No auth (unguessable uuid4 =
      access control for the 5-user release). 17 Django tests.
      AnalysisSnapshot deferred: analyses recompute live; a stored
      snapshot earns its place only when results must be citable.

- [x] **Verification notebook** (`notebooks/01_verify_core.ipynb`) —
      2026-08-22. The readable twin of `tests/test_verification.py`:
      hand-computed 5-point case for median/MAD/CoMAD, closed-form
      Markowitz vs the optimizer, legacy-vs-v2 side by side (CoMAD exact
      to ~1e-19; normal Σ intentionally differs = Ledoit-Wolf, shown not
      hidden), the 2024 notebook golden numbers, and an object-API demo
      with a frontier plot. Executed offline, outputs saved.

- [x] **CLI** (`condor/cli.py`, `python -m condor`) — 2026-08-22. Thin
      boundary over the object API (no numerics, same rule as views):
      `analyze`, `portfolio T=w…`, `frontier` (table / `--csv` /
      `--json` / `--html` Plotly chart), `data ls|update|purge`.
      `--rf` defaults to live FRED 3-mo T-bill. 9 offline tests.

- [x] **Explorer: data layer wired in** — 2026-08-22. Risk-free field
      prefilled from FRED (3-mo T-bill, with as-of date shown under the
      input; silent fallback to the old default if FRED and cache are
      both unreachable); results caption now leads with "Data as of
      <last trading day>".

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
