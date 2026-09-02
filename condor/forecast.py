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


# ---------------------------------------------------------------- anchors
# Rung C. The sample mean is the forecast's weakest input: SE(m) is
# s*sqrt(ppy)/sqrt(n) -- five or six points a year on a typical equity
# mix estimated from a decade. A long-run anchor is a second source of
# information about the same quantity, so the honest thing to do with it
# is a precision-weighted blend, not a replacement.
MARKET_ANCHOR = 0.08      # long-run nominal market expectation, simple %/yr
ANCHOR_PRIOR_SD = 0.03    # tau: 3 points/yr, how firmly the anchor is held
ANCHOR_MIN, ANCHOR_MAX = -0.20, 0.30   # sane range for a user-typed anchor


def anchored_moments(mu_hat: float, se: float, anchor: float,
                     prior_sd: float) -> tuple[float, float]:
    """Conjugate-normal blend of an estimate with a prior -> (mean, sd).

        mu_post = (mu_hat/se^2 + a/tau^2) / (1/se^2 + 1/tau^2)
        sd_post = sqrt(1 / (1/se^2 + 1/tau^2))

    Unit-agnostic: all four arguments must live in the same space (Condor
    passes the *annualized log* drift; see `anchored_log_drift`). This is
    the generalizable core of Black-Litterman -- shrink the sample mean
    toward an equilibrium anchor with weight set by the ratio of prior to
    sampling variance (docs/research/forecast-methods-ladder.md 7a).

    Limits, exactly: `prior_sd = inf` is "no prior at all" and returns
    (mu_hat, se) unchanged; `prior_sd = 0` is total certainty and returns
    (anchor, 0). `se = 0` means the data are exact (an all-cash mix), and
    no prior can improve on that -- it wins over a zero prior_sd. With
    both finite and positive the posterior sd is strictly below either
    input: bringing in information narrows the estimate error.
    """
    se, prior_sd = float(se), float(prior_sd)
    if se < 0 or prior_sd < 0:
        raise ValueError("se and prior_sd must be non-negative")
    if se == 0:
        return float(mu_hat), 0.0
    if prior_sd == 0:
        return float(anchor), 0.0
    if np.isinf(prior_sd):
        return float(mu_hat), se
    w_data, w_prior = 1.0 / se ** 2, 1.0 / prior_sd ** 2
    post_var = 1.0 / (w_data + w_prior)
    return (float(post_var * (mu_hat * w_data + anchor * w_prior)),
            float(np.sqrt(post_var)))


def anchored_log_drift(m: float, s: float, n_obs: int,
                       periods_per_year: int, anchor: float,
                       prior_sd: float) -> tuple[float, float]:
    """`anchored_moments` in the units the forecaster actually holds.

    Takes the per-period log drift `m` and its sample (s, n_obs), plus an
    anchor quoted as an **annual simple** return and a prior sd quoted in
    annual log points; returns the posterior *per-period* log drift and
    the posterior *per-period* sd of that drift (the quantity that drives
    the `_est` bands, in the same units as the s/sqrt(n) it replaces).

    The anchor is converted with log(1 + a); tau is treated as log-space
    directly. At these magnitudes the difference between a simple-space
    and a log-space sd is second-order (3 points of return around 8% maps
    to ~2.8 log points), and pretending to more precision about the width
    of a prior belief than that would be false.
    """
    se = mu_standard_error(s, n_obs, periods_per_year)
    post_m, post_sd = anchored_moments(m * periods_per_year, se,
                                       float(np.log1p(anchor)), prior_sd)
    return post_m / periods_per_year, post_sd / periods_per_year


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
                    step: int = 5, drift_sd: float | None = None) -> pd.DataFrame:
    """Closed-form fan-chart table, indexed by horizon in years.

    Columns: `median`, and per level L (as an int percent, e.g. 65):
    `lo{L}`/`hi{L}` (path-only) and `lo{L}_est`/`hi{L}_est` (drift
    estimation error included). All values are wealth multiples of 1.
    Row 0 is "today": everything exactly 1.

    `drift_sd` overrides the per-period uncertainty in the drift, which
    defaults to the sample SE s/sqrt(n). Rung C passes the posterior sd
    from `anchored_log_drift` (with `m` its posterior mean) so the fan
    centres on the anchored expectation and carries the anchored, usually
    narrower, estimate error.
    """
    if s < 0 or n_obs < 2:
        raise ValueError("need s >= 0 and n_obs >= 2")
    if drift_sd is not None and drift_sd < 0:
        raise ValueError("drift_sd must be non-negative")
    h = horizon_grid(horizon_periods, step).astype(float)
    var_path = h * s ** 2
    var_est = (var_path + (h * s) ** 2 / n_obs   # + h²s²/n: Var of h·m̂
               if drift_sd is None else var_path + (h * drift_sd) ** 2)
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
                    n_paths: int = 10_000, seed: int = 0,
                    drift_shift: float = 0.0,
                    drift_sd: float | None = None) -> pd.DataFrame:
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

    Rung C enters through the same door: `drift_shift` is a per-period
    log-drift offset added to every path (recentring the resampled
    history on an anchored expectation without disturbing its shape —
    the streaks and drawdowns are still the real ones), and `drift_sd`
    replaces s/sqrt(n) as the sd of the per-path drift draw. Relative to
    the unshifted resample, the overlay is then
    N(drift_shift, drift_sd²) — the posterior recentring and its
    estimate error in one constant-per-path term.
    """
    if block < 1:
        raise ValueError("block must be >= 1")
    if n_paths < 100:
        raise ValueError("n_paths must be >= 100")
    if drift_sd is not None and drift_sd < 0:
        raise ValueError("drift_sd must be non-negative")
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

    # anchoring (rung C) recentres every path by a constant drift; the
    # median and the path-only bands move with it
    if drift_shift:
        out = out + float(drift_shift) * h[None, :]

    # Merton overlay: an uncertain drift shifts each whole path
    sd = r.std(ddof=1) / np.sqrt(n) if drift_sd is None else float(drift_sd)
    delta = rng.normal(0.0, sd, n_paths)
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
