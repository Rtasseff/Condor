# Architecture

How the code is layered, where new things go, and what not to do. Read this
before adding a feature. (`README.md` = how to run it; `BACKLOG.md` = what's
next; `context/CONTEXT.md` = where the project came from.)

## The layers

```
web/explorer/views.py      HTTP boundary: validate input, call the facade, return JSON
condor/cli.py              CLI boundary: parse args, call the model, print tables/CSV/JSON
        │
condor/frontier.py         compute_analysis(...)  — procedural facade, one dict out
        │
condor/model.py            DOMAIN MODEL: Asset → AssetSet → Portfolio, Frontier
        │
condor/stats.py            ESTIMATION ENGINE: μ, Σ (normal / robust), returns
condor/frontier.py         OPTIMIZATION ENGINE: _perf, _solve, _weights_dict
condor/forecast.py         FORECAST ENGINE: fan-chart bands (closed form, bootstrap, μ anchors)
condor/accounting.py       ACCOUNT ENGINE: ledger replay, valuation/TWR, rebalance plans
        │
condor/data/               DATA LAYER: PriceStore (~/.condor/prices) + sources + FRED rf
```

Two kinds of code live in `condor/`, on purpose:

- **Engine = functions over DataFrames/arrays.** `stats.py` and the private
  helpers in `frontier.py`. Pure, vectorized, no state. This is the idiomatic
  shape for numeric pandas/numpy code and it is what the verification suite
  pins against legacy code, closed-form Markowitz, and the 2024 notebook.
- **Model = objects that own state that travels together.** `AssetSet`
  owns a set of assets and the μ/Σ estimated for it under one method;
  `Portfolio` owns weights over an AssetSet; `Frontier` owns the curve and
  its anchor portfolios. The objects *call* the engine; they never
  re-implement it.

The rule of thumb: **numbers are computed in the engine; behaviour is
composed in the model.** A method on a domain object should be a few lines
that gather the object's state and hand it to an engine function.

## Where does a new thing go?

| You are adding… | Put it in | Shape |
|---|---|---|
| A new estimator (e.g. Black-Litterman, shrinkage variant, geometric mean option) | `stats.py` | a function; register it in `METHODS` / as an option; `AssetSet` picks it up via `method=` or a new constructor arg |
| A new optimization (constraints, cardinality, efficient_risk variants) | `frontier.py` (`_solve` or a sibling) | a function returning a weight array; expose it as an `AssetSet` method returning a `Portfolio` |
| A new capability **of a portfolio** (forecast, rebalance, DCA schedule, drawdown, scenario replay) | `model.py` → method on `Portfolio` (numerics in a new engine module, e.g. `forecast.py`) | `portfolio.forecast(horizon, ...)` returns a small result object or DataFrame; `to_dict()` for the UI |
| A new capability **of a set of assets** (screening, correlation view, "suggest an addition") | `AssetSet` method (+ engine function) | same pattern |
| A new curve / chart object (e.g. CAL as its own thing, backtest path) | `model.py` class, or a sibling module | has an `AssetSet` or `Portfolio`, exposes `to_dict()` |
| A new data source | `condor/data/sources.py` | a class with `name` and `fetch(ticker, start) -> DataFrame[close, adj_close]`; register in `_REGISTRY` |
| A new HTTP endpoint | `web/explorer/views.py` + `urls.py` | validate → build `AssetSet` → call model → `to_dict()` → `JsonResponse`. No numerics in views. |
| Persistence (saved portfolios) | `web/explorer/models.py` (Django) | store tickers/weights/method/rf; rebuild a `Portfolio` from them — Django models are storage, `condor` objects are behaviour |

Worked example — the forecaster (rung A shipped 2026-08-22 exactly in
this shape; rungs B/C follow the same pattern):

```python
# condor/forecast.py   (engine: pure functions)
def gbm_paths(mu, sigma, horizon_days, n_paths, seed=None) -> np.ndarray: ...
def bootstrap_paths(returns, horizon_days, n_paths, seed=None) -> np.ndarray: ...

# condor/model.py     (model: compose)
class Portfolio:
    def forecast(self, horizon_years=2, n_paths=2000, method="bootstrap", seed=None) -> Forecast:
        ...  # gather self.returns / self.expected_return / self.dispersion, call engine

class Forecast:           # result object: paths, bands(0.65, 0.95), to_dict()
```

Then the view adds `POST /api/forecast` that builds the AssetSet, makes the
portfolio, calls `.forecast()`, returns `to_dict()`. Nothing else changes.

## Conventions

- **Vocabulary.** Condor says *expected return* and *dispersion* (σ), and
  the *robust* method is median / MAD / CoMAD with the 1.4826 factor — keep
  those words in APIs and UI. `mu` / `sigma` are accepted shorthands on
  `AssetSet`. Payload dicts use the short keys `ret` / `vol` / `sharpe`.
- **Everything is annualized** (daily basis, 252) at the engine boundary.
- **Long-only, weights sum to 1** is the prototype's contract. If you add
  shorting/leverage, make it an explicit option, not a silent change.
- **Strict core, lenient boundary.** Domain objects raise on bad input
  (unknown ticker, negative weight). `AssetSet.analysis()` / the view are
  where leniency lives (ignore unknowns, clip, fall back to equal weights).
- **Immutability.** An `AssetSet` is never mutated after construction; use
  `with_method()` or build a new one. Cached μ/Σ depend on it.
- **`to_dict()` is the only thing the UI sees.** Keep payload shapes stable;
  add keys rather than renaming.
- **Use established packages** for numerics (PyPortfolioOpt / cvxpy /
  numpy / pandas / statsmodels). Hand-roll only when the legacy method has
  no equivalent (CoMAD) — and then match the legacy semantics exactly.

## Don'ts

- Don't make `Asset` compute anything. Per-asset stats are columns of the
  set's vectorized estimates (`aset.summary()`). Asset-by-asset loops were
  the slow, inconsistent part of the 2023 code.
- Don't add new keys to `compute_analysis` by reaching around the model.
  Extend `AssetSet.analysis()` / `Frontier.to_dict()` / `Portfolio.to_dict()`.
- Don't put numerics in `views.py`, `cli.py`, or JavaScript.
- Don't let a domain method grow its own math. If it's more than gathering
  state and calling a function, the function belongs in an engine module.
- Don't inherit `Portfolio` from `AssetSet`. A portfolio *has* an asset set
  and *behaves like* an asset (via `returns` / `value_index`); that is the
  "asset of assets" idea from the legacy design, done by composition.

## Recorded decisions

Significant design choices, with the alternatives that lost and the
conditions that would reopen them, live in `docs/decisions/` (ADRs).
Read them before redesigning something they cover; add one when you make
a choice future-you will question.

## Tests are the contract

- `tests/test_verification.py` — engine vs legacy code, closed-form
  Markowitz, and golden numbers from the 2024 notebook. If you change the
  engine, these must still pass or you must explain, in the test, why the
  old number was wrong.
- `tests/test_model.py` — object API == engine, number for number.
- `tests/test_core.py` — structural properties of the payload.

Every new engine function gets a verification-style test (closed form, a
hand-computed case, or legacy agreement). Every new model method gets a
"calls the engine" test. Run `python -m pytest tests/` before committing.
