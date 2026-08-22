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
