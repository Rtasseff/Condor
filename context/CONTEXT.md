# Condor Funds — Context for the v2 Relaunch

*Compiled 2026-08-10 from the 2023–2024 project materials. This is the orientation
document: what Condor Funds was, what was built, what was learned, and where
everything lives.*

---

## 1. What Condor Funds is

**Mission** (from the White Paper and pitch deck): increase access to and engagement
in financial investment for mid- to lower-income households — the ~40% of Americans
who own no investments at all. Stable, mid- to long-term investing. Explicitly
*not* a casino.

> "A rising tide lifts all boats … while that means shit all if you don't have any
> boats." Mission: build more boats.

**Four product pillars** (recurring frame across all materials):

| Pillar | Meaning |
|---|---|
| **Learn** | Short video clips, articles, curated links that meet people where they are |
| **Build** | Virtual portfolios, asset screening, industry-standard optimization analytics, reports/orders via 3rd-party brokers |
| **Compete** | Public/private portfolio leaderboards, sharing, chat — gamified without trivializing |
| **Develop** | Fully open-source platform; community contributions; free robo-adviser ambitions |

**Positioning insight** (pitch deck): tips, trading platforms, cheap ETFs, and
education all already exist. What's missing are **rigorous, easy-to-use tools to
build a diversified portfolio**. That tool gap is the product.

## 2. The product concept (UI vision)

The last slides of `pitch/cF_pitch_v0.pdf` (rendered in `pitch/concept_slides/`)
mock up the **Explorer** — the core screen the v2 prototype should echo:

- **Risk/Reward plane** — x-axis Low→High Risk (yellow→red), y-axis Low→High
  Reward (yellow→green), dark navy/teal background, rounded cards, neon accents.
- Reference points on the plane:
  - **Market Expectations** — the S&P 500 index (can't buy directly; educational)
  - **Easy Choice** — a passive index ETF (e.g. SPY) as the simple default
  - **Your Choice** — the user's own portfolio, movable along the curve
  - **Bland Investment** (low risk/low reward) and **Bad Investment** (high
    risk/low reward) corners as teaching devices
- **Sidebar card "Your choice:"** — searchable **Add** for assets, scrollable
  holdings list (mock used AAPL, MSFT, JNJ, ABBV, XOM, CVX, COP), **Suggest**
  button, and **Portfolio: [Data] [Forecast]** buttons.
- **Data view** — efficient frontier curve with the individual assets as dots,
  the **'Reasonable Guess' Tangent Portfolio** highlighted, **US Treasury Bills**
  as the risk-free point, dashed capital-allocation line connecting them.
- **Forecast view** *(future feature)* — fan chart with 65% and 95% confidence
  bands, either backtested from 2 years ago or projected 2 years forward.
- Everywhere: contextual info boxes with plain-language explanations plus links to
  "learning clips" and "technical details" — the Learn pillar woven into the tool.

## 3. What was built (legacy code, `context/legacy/`)

Copied from `~/projects/condor_test` (the real parts; the Django `site/` there was
an unmodified tutorial skeleton and was deliberately left behind).

### Architecture (the OO direction worth keeping)

`analytics/classes/CondorCoreObs.py` — the domain model:

- **`PriceLoader`** — loads price CSVs, returns DataFrames/arrays/Asset lists
- **`TimeCourse`** — (times, values) series with sampling interval
- **`Asset`** — symbol + loader + lazy `prices`/`returns`/`expectedReturn`/
  `returnDispersion` (deliberately not precomputed — memory-vs-compute tradeoff
  is documented in comments)
- **`Returns(TimeCourse)`** — returns over D/M/Y timeframes with pluggable metric
  and estimation method
- **`Portfolio`** — assets + weights (must sum to 1); expected return, dispersion,
  Sharpe; `optimal()`/`optimize()` for max-Sharpe or min-dispersion weights

`analytics/classes/Curves.py` — **`EF`** (efficient frontier via return-target
sweep), **`CAL`** (capital allocation line), **`Plotter`** (Plotly figure of
frontier + CAL + assets).

In-code note-to-self (CondorCoreObs ~line 168): an **AssetSet** base class should
unify Asset/Portfolio — "a portfolio is an asset in a real sense, an asset of
assets" — with Portfolio inheriting from it. The v2 model (`condor/model.py`,
2026-08-19) keeps the instinct but not the inheritance: `Portfolio` *has* an
`AssetSet` (composition), and gets its asset-like face from exposing a daily
`returns` series / prices-like `value_index`, so a Portfolio can be a member
of another AssetSet. `Asset` is identity-only; all statistics are estimated
for the set, vectorized.

### Methods (`analytics/functions/`)

- `genFin.py` — return metrics (**Relative / Delta / Simple / Log**); expected
  return & dispersion with **method='Robust' (median/MAD/CoMAD) or 'Normal'
  (mean/std/cov)**; portfolio performance from weights + covariance;
  Sharpe ratio; annualization (M×12, D×252, dispersion ×√factor)
- `genStats.py` — the robust/normal statistics primitives
- `portOpt.py` — SciPy SLSQP: `max_sharpe_ratio`, `min_dispersion` (optionally
  with a return-target constraint), `calc_efficient_frontier` as a sweep of
  min-dispersion over return targets
- `assetPreassess.py` — initial asset screening
- `data_mining/` — **Polygon.io** fetchers (aggregates, tickers) and CSV loaders;
  bulk downloads live in `drive_export/files/Data from Polygon.io/` and
  `drive_export/files/data_analytics_v1/` (sp500 10y histories, ~750 MB)

Distinctive methodological choice: **robust statistics as the default**
(median/MAD/CoMAD instead of mean/std/cov) to resist outliers in return
distributions. Keep this as an option in v2.

### Workflows (notebooks)

- `analytics/data_visualizations/analytics_workflow_v1.ipynb` — the end-to-end
  story: sector correlation matrix → pick weakly-correlated assets (used MSFT,
  NEE, CVX) → efficient frontier + max-Sharpe via SLSQP → predictive models
  (Random Forest, LSTM, geometric Brownian motion simulation). Parts 1–2 are the
  prototype's scope; Part 3 is the future Forecast feature.
- `project/202411_refact_optWF.ipynb` — last refactor of the optimization
  workflow using the class-based API (the most recent thinking).
- `project/202411_apa_*.ipynb` — asset pre-assessments (S&P 500, Russell 2000, GLD).
- `tests/` + `UNIT_TESTS.md` — pytest suite for genFin/genStats/portOpt.

## 4. Team & status at wind-down (2024)

From `drive_export/text/Important Info.md` and `Live Action Items.md`:

- Ryan Tasseff (lead), Cecilia Garmendia, Brennan Tasseff (associates),
  Penny Jackson (tech lead), Claudie Labbe (design lead)
- MVP goal: concept slides + learning modules + SM campaign + consumer feedback
  + **web-functional analytical stack** focused on portfolio creation
- Open items when it paused: refactor initial-assessment code (RT), refactor
  portfolio-optimization code (PJ)
- Consumer research: friends-and-family qualitative interviews were run
  (~15k words of notes in `drive_export/text/Consumer Research/`)

## 5. Where everything lives

| Material | Location |
|---|---|
| This synthesis | `context/CONTEXT.md` |
| Pitch deck (PDF + key slides as PNG) | `context/pitch/` |
| Legacy code snapshot (read-only reference) | `context/legacy/` |
| Work-drive text corpus (43 docs, indexed) | `drive_export/text/` + `drive_export/INDEX.md` |
| Work-drive originals & bulk data (not in git) | `drive_export/files/` |
| Reference library (~50 PDFs: Markowitz, BKM Investments, portfolio-optimization papers, rebalancing, prediction) | `~/Library/CloudStorage/GoogleDrive-rtasseff@gmail.com/My Drive/condor/reference materials/` |
| White paper & proposal (best prose on vision) | `drive_export/text/Writings/` |
| Old repo (public) | https://github.com/Rtasseff/condor_test |

## 6. Decisions for v2 (agreed at relaunch, 2026-08-10)

1. **Don't port the hand-rolled numerics.** Use established quant libraries
   (PyPortfolioOpt/cvxpy family) for expected returns, risk models, and frontier
   optimization; keep the legacy code as the conceptual spec. The legacy robust
   (median/MAD) option is preserved as a first-class choice in the new core.
2. **Data**: historical daily prices via a free source (yfinance) with local
   caching; Polygon.io bulk CSVs remain available for offline/backtest work.
   Expandable later.
3. **Stack**: Python venv, analytics package + Django backend, server-rendered
   UI with Plotly charts. Dark navy/teal aesthetic per the concept slides —
   nice, not fancy.
4. **Prototype scope**: build portfolio from real assets → per-asset and
   portfolio expected return & dispersion → efficient frontier with every point
   inspectable → tangency (max-Sharpe) highlighted with CAL vs. risk-free rate →
   user may pick *any* frontier point, not just tangency.
5. **Out of scope for now** (future features, per pitch deck): forecaster (fan
   charts), rebalancing / dollar-cost-averaging recommendations, scenario
   simulators, leaderboards, learning-content integration.
