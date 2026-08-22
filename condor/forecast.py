"""Forecast engine: pure functions over return series and moments.

Rung A of the research ladder (docs/research/forecast-methods-ladder.md,
summarized in forecast-research-summary.pdf): the *simplest honest*
projection. Per-period log returns are treated as i.i.d. Normal(m, s²),
so cumulative wealth is lognormal and every band is a closed-form
quantile — no simulation. Two band sets are produced:

- *path-only*: market randomness with the estimated drift taken as true,
  Var(log W_h) = h·s²;
- *with estimate error*: the drift's own sampling error folded in
  (Merton 1980 — SE(m) depends only on the calendar span),
  Var(log W_h) = h·s² + h²·s²/n.

The second is the honest one; the research pass found the μ estimate is
the dominant uncertainty at multi-year horizons. Later rungs (block
bootstrap, μ anchors) plug in beside this; this closed form stays as the
verification pin for all of them.

Engine only: no HTTP, no Django, no UI strings. The model composes
these (Portfolio.forecast -> Forecast) per ARCHITECTURE.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

DEFAULT_LEVELS = (0.65, 0.95)


def log_moments(returns) -> tuple[float, float, int]:
    """Per-period log-return moments of a simple-return series.

    -> (mean, std [ddof=1], n_obs). Log space is what compounds:
    using the arithmetic mean of simple returns as a drift overstates
    the median outcome by exp(s²·h/2).
    """
    r = np.log1p(np.asarray(pd.Series(returns).dropna(), dtype=float))
    if r.size < 2:
        raise ValueError("need at least 2 returns to estimate moments")
    return float(r.mean()), float(r.std(ddof=1)), int(r.size)


def mu_standard_error(s: float, n_obs: int, periods_per_year: int) -> float:
    """Standard error of the *annualized* log drift.

    SE(m) per period is s/sqrt(n); annualized drift is m·ppy, so its SE
    is s·ppy/sqrt(n) — algebraically sigma_annual/sqrt(span_years),
    Merton's span-only result.
    """
    return float(s) * periods_per_year / np.sqrt(n_obs)


def horizon_grid(horizon_periods: int, step: int) -> np.ndarray:
    """0..horizon inclusive in `step`-period increments (endpoint kept)."""
    if horizon_periods < 1:
        raise ValueError("horizon must be at least 1 period")
    h = np.arange(0, horizon_periods + 1, max(1, int(step)))
    if h[-1] != horizon_periods:
        h = np.append(h, horizon_periods)
    return h


def lognormal_bands(m: float, s: float, n_obs: int, horizon_periods: int,
                    periods_per_year: int, levels=DEFAULT_LEVELS,
                    step: int = 5) -> pd.DataFrame:
    """Closed-form fan-chart table, indexed by horizon in years.

    Columns: `median`, and per level L (as an int percent, e.g. 65):
    `lo{L}`/`hi{L}` (path-only) and `lo{L}_est`/`hi{L}_est` (drift
    estimation error included). All values are wealth multiples of 1.
    Row 0 is "today": everything exactly 1.
    """
    if s < 0 or n_obs < 2:
        raise ValueError("need s >= 0 and n_obs >= 2")
    h = horizon_grid(horizon_periods, step).astype(float)
    var_path = h * s ** 2
    var_est = var_path + (h * s) ** 2 / n_obs   # + h²s²/n: Var of h·m̂
    drift = h * m

    out = {"median": np.exp(drift)}
    for lvl in levels:
        if not 0 < lvl < 1:
            raise ValueError(f"levels must be in (0, 1), got {lvl}")
        z = norm.ppf(0.5 + lvl / 2)
        tag = str(int(round(100 * lvl)))
        out[f"lo{tag}"] = np.exp(drift - z * np.sqrt(var_path))
        out[f"hi{tag}"] = np.exp(drift + z * np.sqrt(var_path))
        out[f"lo{tag}_est"] = np.exp(drift - z * np.sqrt(var_est))
        out[f"hi{tag}_est"] = np.exp(drift + z * np.sqrt(var_est))
    return pd.DataFrame(out, index=pd.Index(h / periods_per_year, name="years"))


def blend_with_cash(returns, cash_weight: float, risk_free_rate: float,
                    periods_per_year: int):
    """Per-period simple returns of a constant-mix blend: (1 - cw) in
    the risky series, cw at the risk-free rate.

    The cash sleeve is deterministic — per period it earns
    (1 + rf)^(1/ppy) - 1 — so blending shifts the mean and scales the
    dispersion by (1 - cw). cw = 1 is pure T-bills (zero-width bands);
    cw = 0 returns the input unchanged. Constant-mix means the blend is
    rebalanced every period, matching a fixed cash_weight assumption.
    """
    cw = float(cash_weight)
    if not 0.0 <= cw <= 1.0:
        raise ValueError("cash_weight must be in [0, 1]")
    rf_p = (1.0 + float(risk_free_rate)) ** (1.0 / periods_per_year) - 1.0
    return (1.0 - cw) * pd.Series(returns) + cw * rf_p


def bootstrap_bands(returns, horizon_periods: int, periods_per_year: int,
                    levels=DEFAULT_LEVELS, step: int = 5, block: int = 21,
                    n_paths: int = 10_000, seed: int = 0) -> pd.DataFrame:
    """Rung B: stationary-block-bootstrap fan-chart table.

    Resamples the portfolio's own per-period log returns in contiguous
    blocks (Politis-Romano stationary bootstrap: block lengths are
    geometric with mean `block`), so volatility clustering and drawdown
    sequences survive into the simulated paths. Same table shape as
    `lognormal_bands`; the `_est` columns fold in the drift's sampling
    error (a per-path N(0, s²/n) drift draw — same Merton overlay).

    Deterministic for a given seed. The research pass (docs/research/)
    warns this method inherits whatever mean-reversion happens to be in
    the sample window — callers must apply `band_floor` against the
    closed form so a lucky decade can never *narrow* the bands.
    """
    if block < 1:
        raise ValueError("block must be >= 1")
    if n_paths < 100:
        raise ValueError("n_paths must be >= 100")
    r = np.log1p(np.asarray(pd.Series(returns).dropna(), dtype=float))
    n = r.size
    if n < 2:
        raise ValueError("need at least 2 returns to bootstrap")
    h = horizon_grid(horizon_periods, step)
    rng = np.random.default_rng(seed)
    p_new = 1.0 / block

    # accumulate log wealth path-by-period, storing only grid columns
    grid_col = {int(hp): k for k, hp in enumerate(h)}
    out = np.zeros((n_paths, len(h)))
    acc = np.zeros(n_paths)
    idx = rng.integers(0, n, n_paths)
    for t in range(1, int(horizon_periods) + 1):
        if t > 1:
            restart = rng.random(n_paths) < p_new
            idx = np.where(restart, rng.integers(0, n, n_paths),
                           (idx + 1) % n)
        acc += r[idx]
        k = grid_col.get(t)
        if k is not None:
            out[:, k] = acc

    # Merton overlay: an uncertain drift shifts each whole path
    delta = rng.normal(0.0, r.std(ddof=1) / np.sqrt(n), n_paths)
    est = out + delta[:, None] * h[None, :]

    cols = {"median": np.exp(np.quantile(out, 0.5, axis=0))}
    for lvl in levels:
        if not 0 < lvl < 1:
            raise ValueError(f"levels must be in (0, 1), got {lvl}")
        qlo, qhi = 0.5 - lvl / 2, 0.5 + lvl / 2
        tag = str(int(round(100 * lvl)))
        cols[f"lo{tag}"] = np.exp(np.quantile(out, qlo, axis=0))
        cols[f"hi{tag}"] = np.exp(np.quantile(out, qhi, axis=0))
        cols[f"lo{tag}_est"] = np.exp(np.quantile(est, qlo, axis=0))
        cols[f"hi{tag}_est"] = np.exp(np.quantile(est, qhi, axis=0))
    table = pd.DataFrame(cols, index=pd.Index(h.astype(float)
                                              / periods_per_year,
                                              name="years"))
    # row 0 is "today" exactly (quantiles of zeros are already 1.0)
    return table


def band_floor(table: pd.DataFrame, floor: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Widen `table`'s bands wherever they are narrower than `floor`'s.

    Element-wise envelope on every lo*/hi* column (medians untouched):
    lo = min(lo, floor_lo), hi = max(hi, floor_hi). The returned flag
    is True only when a band was MATERIALLY narrower than the floor
    (final-horizon log-width more than 5% under it) — Monte-Carlo
    jitter alone doesn't count. This is the research guard rail: a
    bootstrap fed one recovered-every-dip decade must not present
    narrower uncertainty than the closed form admits.
    """
    if not table.index.equals(floor.index):
        raise ValueError("table and floor must share the same horizon grid")
    guarded = table.copy()
    for col in table.columns:
        if col.startswith("lo"):
            guarded[col] = np.minimum(table[col], floor[col])
        elif col.startswith("hi"):
            guarded[col] = np.maximum(table[col], floor[col])

    materially = False
    last = table.index[-1]
    for hi_col in table.columns:
        if not hi_col.startswith("hi"):
            continue
        lo_col = "lo" + hi_col[2:]
        w_table = np.log(table.loc[last, hi_col]) - np.log(table.loc[last, lo_col])
        w_floor = np.log(floor.loc[last, hi_col]) - np.log(floor.loc[last, lo_col])
        if w_table < 0.95 * w_floor:
            materially = True
    return guarded, materially
