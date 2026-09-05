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
  *Round 1 (2026-08-22) landed same-day: key instead of chasing labels,
  "Your portfolio" rename, considering-ring selection, point card under
  the chart, click-anywhere snapping, CAL two-fund mixes with borrowing
  warning, and login/accounts. Keep the notes coming.*
- [ ] **Release 0.1 to the old Condor team** (~5 trusted users, 4 time
  zones) — after RT's UI review and the branding pass. Plan + hosting
  research + runbook: `docs/DEPLOY.md` (2026-08-23). Code prep is DONE
  and merged: env-driven settings (CONDOR_*), whitenoise + gunicorn,
  Dockerfile, TIME_ZONE=UTC pinned, security headers, `check --deploy`
  clean (HSTS-subdomain flags deliberately skipped on a platform
  subdomain). Earlier pre-flight (2026-08-22): PriceStore POSIX locks
  for multi-worker; accounts/login shipped, so 0.1 is multi-user from
  day one. Remaining decisions are RT's: pick the host, get the free
  Tiingo key (yfinance-from-datacenter risk), rotate the old exposed
  Polygon key before anything gets more public.
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
- [ ] **Forecast a selected CAL point in Build** — the engine/model
  side shipped 2026-08-22 (`blend_with_cash`, `Portfolio.forecast(
  cash_weight=, risk_free_rate=)`, whole-account forecast on
  /account); what remains is the Build-page UI: forecast the
  "Considering" point (its cash share included) instead of only the
  sidebar mix.
- [ ] **Forecaster — rung C, the rest of it** (the anchor control itself
  shipped 2026-09-02, see Done; rungs A and B 2026-08-22). What remains
  of the ladder's rung C and its follow-ons: *multi-asset*
  Black-Litterman on the frontier (`pypfopt.BlackLittermanModel`,
  market-cap equilibrium prior, user views as tilts — ties into the B-L
  backlog item below), CAPE / Damodaran-ERP as *live* anchor sources
  instead of the documented 8% constant, the backtest view (project from
  2y ago, overlay reality, report the landed percentile with the
  sample-of-one caveat) and the offline coverage notebook from
  `forecast-validation.md`. Skip the ML tier — ~5 independent 2-year
  observations to learn from. Data shortlist: `forecast-data-sources.md`.
  Legacy: `analytics_workflow_v1.ipynb` Part 3; RF/LSTM deprioritized.
- [ ] **Rebalancing rules & DCA** (drift-triggered vs calendar rules, DCA
  schedule simulator) — the *mechanics* shipped 2026-08-22 with the
  account view (drift display, whole-share plans, confirm-to-ledger);
  what remains is advice about *when*: threshold vs calendar policy,
  and dollar-cost-averaging plans for new money.
  References: `reference materials/Portfolio-ManagementProcess/
  Kritzman2008-Portfolio_Rebalancing…`, `MRebalancing.pdf`.
- [ ] **Account follow-ons:** multiple accounts per user (schema already
  allows it — needs a selector UI); dividends/splits at the account
  level (ledger kinds + replay rules, ADR 0004 "reopens if");
  benchmark overlay on the value chart (SPY / your setpoint held
  passively); CSV export of the ledger.
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

## Later

- Draft PUT race: rapid adds on Build fire overlapping whole-list
  `PUT /api/draft` calls; last writer wins (script-speed only, found
  during flow-clarity's click-through 2026-09-05). Fix = sequencing or a
  version token. (deck vision)

- [ ] **Learn integration** — info boxes with "learning clips" / "technical
  details" links on every concept (Market Expectations, Easy Choice, Tangent
  Portfolio, T-bills…). Content plan lives in `drive_export/text/ExCom/`
  scripts.
- [ ] **Explorer landing view** (deck slides 17–22): S&P 500 "Market
  Expectations" trend chart, "Easy Choice" SPY, "Your Choice" plane with
  Bland/Bad Investment teaching corners.
- [ ] **Compete:** leaderboards (public/private), portfolio sharing, chat.
- [ ] **Broker order facilitation** (report/CSV first). (Users & auth: done
  2026-08-22.)
- [ ] **Deployment:** Docker, Postgres, hosted (AWS per original plan), CI
  running the verification suite.
- [ ] **Open-source hygiene:** LICENSE, CONTRIBUTING, public repo when ready
  (rotate the old credentials first — see CONTEXT.md).

## Done

- [x] **UX conventions pass** — 2026-09-01, from RT's live feedback
      ("zoom so sensitive I'm refreshing constantly... not super
      intuitive") + researched conventions (docs/research/
      ui-conventions.md, NN/g + consumer-finance chart audits, which
      also audited our code). Charts: full interaction lockdown
      (dragmode/axis-handles/double-click/tips all off, fixedrange —
      hover + click are the only interactions, like every consumer
      finance chart), touch-action so charts never trap page scroll,
      legends locked as keys, unified-hover + crosshair spikes on
      time-series, preset range buttons (1m/6m/YTD/1y/All) on the
      account value chart — "zoom" the consumer way. Guidance:
      dismissible 3-step first-visit strip, "What am I looking at?"
      explainer, visible plain-language glosses under every stat tile
      (title= tooltips removed as the weakest pattern), click-cue
      under the chart that retires after first selection, example tag
      on the preloaded portfolio, honest empty state, login page says
      what Condor is, dead nav marked "coming soon". Feedback: staged
      fast-early progress messages during long fetches (Conrad et al.
      2010), aria-disabled buttons that keep focus, feedback on plan/
      contribution pricing, aria roles/labels on all charts.
      Remaining "do soon" ideas queued: /learn glossary page,
      data-table fallbacks under charts.

- [x] **Branding pass** — 2026-08-29 (RT: "make the site look nicer,
      legally free media", $0 by design). IBM Plex Sans/Mono
      self-hosted under OFL (licenses committed); original fan-wing
      mark (logo + favicon — a condor wing that is also a fan chart,
      rising from the "you are here" dot); ambient radial-glow ground,
      card depth, gradient primary buttons with hover lift,
      focus-visible rings, Plex Mono tabular numerals for all money;
      Plotly charts follow `--font-body`. Also fixed: `[hidden]` vs
      `display:flex` (empty due-banner showed for schedule-less
      users). Launch prep: committed ready `fly.toml` (2GB per the
      $50/mo budget) + `docs/LAUNCH-CHECKLIST.md` — RT's exact
      phase-by-phase steps.

- [x] **Forecaster rung C — an anchor on the expected return** —
      2026-09-02. The sample mean is the forecast's weakest input (SE ≈
      5-6 pp/yr on a decade of equity data), so the user now chooses
      what the fan's centre assumes: their own history, a long-run
      market anchor, or their own number. Engine `anchored_moments`
      (conjugate-normal precision blend, exact at both limits, and
      exact data beats any prior so cash stays exact) +
      `anchored_log_drift` (annual simple anchor in via log1p,
      per-period posterior drift and sd out); `lognormal_bands
      (drift_sd=)` and `bootstrap_bands(drift_shift=, drift_sd=)` carry
      it into both models, with model 2 still floored at model 1's
      bands *computed under the same anchor*. Historical is the default
      and bit-identical to before. `MARKET_ANCHOR` 8%/yr, τ = 3 pp, per
      the ladder's §7a; not fetched from anywhere. On a complete
      portfolio the anchor applies to the risky sleeve — cash is known
      to earn rf — so it enters as (1-cw)·a + cw·rf with τ scaled to
      match. Control + honest assumption sentence on both forecast
      cards; the fan redraws live, which is the educational point. 17
      new engine/model tests + 5 API/page tests. Also fixed a
      pre-existing bug the live redraw exposed: `#fchart` had no CSS
      height, so a second `Plotly.react()` collapsed it to 0 px.

- [x] **Forecaster rung B — resampled history (block bootstrap)** —
      2026-08-22. Engine `bootstrap_bands`: stationary bootstrap
      (Politis-Romano, geometric blocks, mean 21 days, disclosed in
      the UI badge) over the portfolio's own log returns, streaming
      accumulation (no path matrix; 10y × 10k paths < 1s), Merton
      per-path drift draw for the `_est` bands, seeded/deterministic.
      `band_floor`: element-wise envelope against the closed form —
      the research guard rail — flagged `guarded` only on material
      (>5%) narrowing. "Model" select in both forecast cards (Build +
      whole-account) with a plain-language note when the guard fires;
      it DOES fire on real 2016-26 data, exactly as the research
      measured (VR(2y) ≈ 0.06 on SPY). Verification: bootstrap
      recovers the lognormal closed form on i.i.d. data; alternating
      mean-reverting series triggers the guard; cw=1 collapses to
      exact rf growth. 9 new engine/model tests + 1 API test.

- [x] **Regular contributions (DCA) + whole-account forecast** —
      2026-08-22. Engine: `contribution_plan` (buys-only whole-share
      routing of new money toward the setpoint — underweights first,
      the setpoint's cash share respected, idle cash deployed, more
      than half a share short before a buy; nothing is ever sold) and
      `forecast.blend_with_cash` (constant-mix risky + cash at rf ⇒
      dispersion scales by 1-cw; cw=1 pins to exact rf growth).
      `ContributionSchedule` (amount, weekly/monthly/quarterly/yearly,
      next_due; advancing steps from the due date so cadence never
      drifts). Reminders: due dot on the "My account" nav link on
      every page (context processor) + banner with "Where should it
      go?" on the account page. Confirming books deposit + edited
      buys and advances the schedule. "Forecast" card on /account
      projects the complete account (holdings value-weighted + cash
      share at the live T-bill rate) in dollars from current value.
      9 new engine tests, 6 API tests; verified live in Chrome.

- [x] **Account view — ledger, drift, rebalancing** — 2026-08-22 (ADR
      0004). `condor/accounting.py` engine (replay, daily valuation at
      raw closes, time-weighted return where deposits are flows not
      gains, whole-share `rebalance_plan` with cheapest-buy trimming;
      16 hand-computed tests) + `Account`/`AccountTarget`/
      `AccountEvent` models + `/account` page (tiles, value-vs-
      contributions chart, holdings with actual-vs-setpoint drift,
      setpoint editor, plan panel with editable executed trades,
      ledger form incl. set_shares/set_cash force kinds). Explorer
      point card gained "Use as account setpoint →" — any frontier or
      CAL point becomes the target and lands on the transition report
      (CAL cash share carries through as the setpoint's cash). Also:
      base.html extracted (trigger met: second page), working topbar
      nav. 8 API tests; full flow verified live in Chrome.

- [x] **Forecaster rung A — the simplest honest fan chart** — 2026-08-22.
      `condor/forecast.py` (engine: `log_moments`, `mu_standard_error`,
      `lognormal_bands` — pure closed form, no simulation) +
      `Forecast` / `Portfolio.forecast()` in the model, `/api/forecast`,
      and a Forecast card in the Explorer labeled "model 1 of 3 —
      simplest: steady rates". Two nested band sets exactly per the
      research: shaded "market randomness" (65/95%) and a dashed
      "+ return-estimate error" outer band (the Merton overlay — the
      dominant term); median uses the log/geometric drift (no
      arithmetic-compounding bias); the card prints the μ error bar as
      a sentence and the blind-spot line. 11 engine/model tests pinned
      to scipy lognormal quantiles and the √(1+T/N) identity; 3 API
      tests; verified live in Chrome.

- [x] **Accounts & login** — 2026-08-22. Django auth wired in (sessions,
      admin for user management, styled login page, logout in the
      topbar). Every page and API requires a login; API returns JSON
      401s so a lost session shows an error instead of a redirect.
      `SavedPortfolio.owner`: the Saved list is per-user; `/p/<uuid>`
      links stay readable by any logged-in user (that is the sharing
      model) but only the owner can overwrite/delete (403 + "Save as
      new" hint); pre-account rows are visible to all and claimed by
      whoever edits them. Local setup: `migrate` + `createsuperuser`;
      teammates added at /admin. 6 new Django tests (23 total).

- [x] **UI review round 1** (RT's live notes) — 2026-08-22. Chart
      identity moved from arrow-annotations to a key (legend); "Your
      choice" → "Your portfolio" everywhere; clicking marks the point
      with a teal "Considering" ring and the details card sits directly
      under the chart; clicks snap to the nearest inspectable point
      (no pixel-hunting); the CAL is selectable as two-fund mixes —
      `Frontier.cal_mix()` grid in the payload, T-bills share as a bar,
      borrowing region flagged with a warning that nobody borrows at
      the T-bill rate. 6 new model tests; verified live in Chrome.

- [x] **Branding & theming readiness** — 2026-08-22. Per docs/BRANDING.md
      + ADR 0003: `--font-body`/`--font-display` tokens (body/wordmark
      wired), `--danger-bg` replaces the last hardcoded color, `app.js`
      chart palette now reads the CSS theme block via getComputedStyle
      (hex literals gone), `static/explorer/brand/` with placeholder
      logo.svg + favicon.svg wired into the template. The branding pass
      is now: new token values + new SVGs, nothing else. `base.html`
      extraction deferred until a second page exists.

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
