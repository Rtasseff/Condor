"""Expected returns and risk models.

Two estimation methods, mirroring the legacy Condor design (genFin/genStats):

- "normal": arithmetic mean daily return x 252 + Ledoit-Wolf shrunk
  covariance (via PyPortfolioOpt) with the constant-correlation target:
  each asset keeps its own sample variance, only correlations shrink (the
  default constant-variance target dragged a T-bill fund's variance up
  5x; ADR 0006). Arithmetic, not geometric/CAGR, so it
  matches legacy genFin.returnExp + annualize and is on the same footing
  as the robust median x 252.
- "robust": median return + CoMAD co-dispersion matrix with the 1.4826
  normality correction — the legacy Condor approach, resistant to outliers.
  CoMAD is not guaranteed positive semi-definite, so it gets a spectral
  PSD repair before any convex optimization sees it.

How the return series itself is built is a separate set of choices, all
carried over from legacy Condor (`CondorCoreObs.Returns` + `genFin.returns`)
and all defaulting to today's behaviour:

- `metric`     "relative" (default, (x_t - x_0) / x_0) or "log".
- `timeframe`  "D" (default, 1-row lag, annualize x252) or "M" (21-row
               lag — the legacy "trading days in a month" — annualize x12).
- `samp_int`   keep every n-th return row (legacy `sampInt`).  Defaults to
               1 for "D" and 20 for "M", which de-overlaps the 21-day
               windows; the annualization factor depends only on the
               timeframe, never on `samp_int` (legacy `genFin.annualize`).
- `basis`      "arithmetic" (default, legacy) or "geometric" (CAGR-style,
               PyPortfolioOpt's own default) for the "normal" expected
               return.

Expected return can also be built as `rf level + premium`, where the
premium is the same estimator applied to *excess* returns (asset return
minus the T-bill's return per period): `excess_returns`, `premium_annual`.
This removes the period mismatch that made a T-bill fund look like a
winner (ADR 0006).  Sigma always stays on raw returns.

Assumptions mode (ADR 0008) adds a prior on premiums: `equilibrium_premiums`
(`Pi = delta * Sigma w_ref`), `blend_premiums` (the prior counts as T0 years
of data) and `apply_views` (Black-Litterman absolute views).

Everything is annualized at the engine boundary (252 for "D", 12 for "M").
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pypfopt import expected_returns, risk_models

TRADING_DAYS = 252
MONTHS_PER_YEAR = 12
MONTH_DAYS = 21  # legacy genFin: "rough estimate of open market days in a month"
MAD_NORMAL_COR = 1.4826  # MAD -> std consistency factor for normal data

METHODS = ("normal", "robust")
METRICS = ("relative", "log")
TIMEFRAMES = ("D", "M")
BASES = ("arithmetic", "geometric")

# per timeframe: price-row lag used for one return, annualization factor,
# and the legacy default sampling interval (20 de-overlaps the 21-day window)
_TIMEFRAME_SPEC = {
    "D": {"window": 1, "annual": TRADING_DAYS, "samp_int": 1},
    "M": {"window": MONTH_DAYS, "annual": MONTHS_PER_YEAR, "samp_int": 20},
}


# ----------------------------------------------------------------------
# option handling
# ----------------------------------------------------------------------
def _check_method(method: str) -> None:
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}'; expected one of {METHODS}")


def _check_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown return metric '{metric}'; expected one of {METRICS}")


def _check_timeframe(timeframe: str) -> None:
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"Unknown timeframe '{timeframe}'; expected one of {TIMEFRAMES}")


def _check_basis(basis: str) -> None:
    if basis not in BASES:
        raise ValueError(f"Unknown basis '{basis}'; expected one of {BASES}")


def return_window(timeframe: str = "D") -> int:
    """Price rows spanned by one return: 1 for "D", 21 for "M" (legacy lag)."""
    _check_timeframe(timeframe)
    return _TIMEFRAME_SPEC[timeframe]["window"]


def annual_factor(timeframe: str = "D") -> int:
    """Annualization factor: 252 for "D", 12 for "M" (legacy genFin.annualize).

    Depends only on the timeframe — `samp_int` changes how many return
    observations there are, not what period each one covers.
    """
    _check_timeframe(timeframe)
    return _TIMEFRAME_SPEC[timeframe]["annual"]


def default_samp_int(timeframe: str = "D") -> int:
    """Legacy default sampling interval: 1 for "D", 20 for "M"."""
    _check_timeframe(timeframe)
    return _TIMEFRAME_SPEC[timeframe]["samp_int"]


def resolve_samp_int(timeframe: str = "D", samp_int: int | None = None) -> int:
    """`samp_int` as a positive int; None means the timeframe's default."""
    if samp_int is None:
        return default_samp_int(timeframe)
    _check_timeframe(timeframe)
    step = int(samp_int)
    if step < 1:
        raise ValueError(f"samp_int must be a positive integer, got {samp_int!r}")
    return step


# ----------------------------------------------------------------------
# returns
# ----------------------------------------------------------------------
def asset_returns(prices: pd.DataFrame, metric: str = "relative",
                  timeframe: str = "D", samp_int: int | None = None) -> pd.DataFrame:
    """Return series from a prices frame (columns = assets).

    One row per return, dated at the *end* of its window, exactly like
    legacy `genFin.returns(x, period=window)` paired with
    `prices.times[window:]`; every `samp_int`-th row is then kept, from the
    first one (legacy `TimeCourse._sample`).
    """
    _check_metric(metric)
    window = return_window(timeframe)
    step = resolve_samp_int(timeframe, samp_int)
    if metric == "relative":
        rets = prices.pct_change(window)
    else:
        rets = np.log(prices / prices.shift(window))
    rets = rets.dropna(how="all")
    if rets.empty:
        raise ValueError(
            f"not enough price history for timeframe {timeframe!r}: "
            f"{len(prices)} rows, need more than {window}")
    return rets.iloc[::step] if step > 1 else rets


def growth_factors(returns, metric: str = "relative"):
    """Per-period growth multipliers: 1 + r for relative, exp(r) for log."""
    _check_metric(metric)
    return np.exp(returns) if metric == "log" else 1.0 + returns


# ----------------------------------------------------------------------
# estimates
# ----------------------------------------------------------------------
def _estimate_annual(rets: pd.DataFrame, method: str, metric: str,
                     timeframe: str, basis: str) -> pd.Series:
    """The one expected-return estimator, over any return frame.

    Shared by `expected_annual` (raw returns) and `premium_annual` (excess
    returns) so the two can never drift apart.
    """
    freq = annual_factor(timeframe)
    if method == "robust":
        return rets.median() * freq
    # compounding=False -> arithmetic mean * freq (pypfopt's default is the
    # geometric/CAGR form, which is NOT what legacy Condor computed)
    return expected_returns.mean_historical_return(
        rets, returns_data=True, frequency=freq,
        compounding=(basis == "geometric" and metric != "log"),
    )


def expected_annual(prices: pd.DataFrame, method: str = "normal",
                    metric: str = "relative", timeframe: str = "D",
                    samp_int: int | None = None,
                    basis: str = "arithmetic") -> pd.Series:
    """Annualized expected return per asset.

    `basis` applies to the "normal" method only: "arithmetic" is the legacy
    mean x annual factor, "geometric" is PyPortfolioOpt's CAGR form.  Log
    returns already compound additively, so for `metric="log"` the two
    coincide and the arithmetic form is used.  The "robust" method is the
    median x annual factor, which has no compounding analogue.
    """
    _check_method(method)
    _check_basis(basis)
    rets = asset_returns(prices, metric=metric, timeframe=timeframe,
                         samp_int=samp_int)
    return _estimate_annual(rets, method, metric, timeframe, basis)


def excess_returns(prices: pd.DataFrame, rf_yields: pd.Series,
                   metric: str = "relative", timeframe: str = "D",
                   samp_int: int | None = None) -> pd.DataFrame:
    """`asset_returns` minus the T-bill's return over the same period.

    `rf_yields` is the daily annual-decimal yield history (DatetimeIndex).
    Each return row gets the yield on its date (forward-filled from the
    previous fixing, back-filled for a leading gap) divided by the annual
    factor; for `metric="log"` the period rate is `log1p` of that.
    """
    rets = asset_returns(prices, metric=metric, timeframe=timeframe,
                         samp_int=samp_int)
    y = rf_yields.dropna().sort_index()
    if y.empty:
        raise ValueError("rf_yields is empty")
    y = y.groupby(level=0).last()
    aligned = (y.reindex(y.index.union(rets.index)).ffill()
                .reindex(rets.index).bfill())
    per_period = aligned / annual_factor(timeframe)
    if metric == "log":
        per_period = np.log1p(per_period)
    return rets.sub(per_period, axis=0)


def premium_annual(prices: pd.DataFrame, rf_yields: pd.Series,
                   method: str = "normal", metric: str = "relative",
                   timeframe: str = "D", samp_int: int | None = None,
                   basis: str = "arithmetic") -> pd.Series:
    """Annualized premium over T-bills: the `expected_annual` estimator
    applied to `excess_returns`.  Expected return = rf level + premium
    (docs/decisions/0006-premium-expected-returns.md).
    """
    _check_method(method)
    _check_basis(basis)
    ex = excess_returns(prices, rf_yields, metric=metric, timeframe=timeframe,
                        samp_int=samp_int)
    return _estimate_annual(ex, method, metric, timeframe, basis)


def _comad_matrix(rets: pd.DataFrame) -> pd.DataFrame:
    """Co-variate Median Absolute Deviation matrix (legacy genStats.comad).

    comad_ij = median[(x_i - med(x_i)) * (x_j - med(x_j))] * 1.4826^2

    Same semantics as the legacy loop, including NaN handling: for each
    pair, rows where either series is NaN are dropped and the medians are
    recomputed on the pairwise-complete rows.  With <= ~20 assets the pair
    loop is trivial; a column-wide-median vectorization was tried and gives
    subtly different numbers whenever NaNs are present, so it was rejected
    (see tests/test_verification.py).
    """
    x = rets.to_numpy(dtype=float)
    n = x.shape[1]
    out = np.empty((n, n))
    for i in range(n):
        for j in range(i, n):
            keep = ~(np.isnan(x[:, i]) | np.isnan(x[:, j]))
            xi, xj = x[keep, i], x[keep, j]
            v = np.median((xi - np.median(xi)) * (xj - np.median(xj)))
            out[i, j] = out[j, i] = v
    out *= MAD_NORMAL_COR**2
    return pd.DataFrame(out, index=rets.columns, columns=rets.columns)


def risk_matrix_annual(prices: pd.DataFrame, method: str = "normal",
                       metric: str = "relative", timeframe: str = "D",
                       samp_int: int | None = None) -> pd.DataFrame:
    """Annualized co-dispersion-squared (covariance-like) matrix."""
    _check_method(method)
    rets = asset_returns(prices, metric=metric, timeframe=timeframe,
                         samp_int=samp_int)
    freq = annual_factor(timeframe)
    if method == "normal":
        return risk_models.CovarianceShrinkage(
            rets, returns_data=True, frequency=freq
        ).ledoit_wolf(shrinkage_target="constant_correlation")
    comad = _comad_matrix(rets) * freq
    # CoMAD may be slightly non-PSD; repair so cvxpy accepts it
    return risk_models.fix_nonpositive_semidefinite(comad, fix_method="spectral")


def asset_points(mu: pd.Series, sigma: pd.DataFrame) -> list[dict]:
    """Per-asset (risk, reward) points for plotting."""
    vols = np.sqrt(np.diag(sigma.to_numpy()))
    return [
        {"ticker": t, "ret": float(mu[t]), "vol": float(v)}
        for t, v in zip(mu.index, vols)
    ]


# ----------------------------------------------------------------------
# assumptions mode: a prior on premiums (ADR 0008)
# ----------------------------------------------------------------------
def equilibrium_premiums(sigma: pd.DataFrame, reference,
                         market_premium: float) -> pd.Series:
    """Equilibrium premiums ``Pi = delta * Sigma w`` for a reference mix.

    `reference` is a ticker in `sigma` or a ``{ticker: weight}`` dict
    (normalized).  ``delta = market_premium / (w' Sigma w)``, so the
    reference's own premium is exactly `market_premium` and every asset's
    premium is ``market_premium * beta_i`` (its covariance with the
    reference over the reference's variance).
    """
    if isinstance(reference, str):
        reference = {reference: 1.0}
    missing = [t for t in reference if t not in sigma.index]
    if missing:
        raise ValueError(f"reference {missing[0]} is not in the risk matrix")
    w = pd.Series(0.0, index=sigma.index)
    for t, x in reference.items():
        w[t] = float(x)
    if (w < 0).any() or w.sum() <= 0:
        raise ValueError("reference weights must be non-negative and sum above 0")
    w = w / w.sum()
    s = sigma.to_numpy(dtype=float)
    var = float(w.to_numpy() @ s @ w.to_numpy())
    if var <= 0:
        raise ValueError("the reference has no dispersion")
    pi = (float(market_premium) / var) * (s @ w.to_numpy())
    return pd.Series(pi, index=sigma.index, name="prior_premium")


def effective_years(t_years: float, method: str = "normal") -> float:
    """Years of data the history counts as: the robust (median) estimator is
    less efficient than the mean by 2/pi, so its window counts for less."""
    _check_method(method)
    return float(t_years) * (2.0 / np.pi if method == "robust" else 1.0)


def blend_premiums(prior: pd.Series, sample: pd.Series, t0: float,
                   t_years: float, method: str = "normal") -> pd.Series:
    """``(T0 * prior + T * sample) / (T0 + T)``: the prior counts as `t0`
    years of data.  For ``method="robust"`` T is scaled by 2/pi."""
    t_eff = effective_years(t_years, method)
    total = float(t0) + t_eff
    if total <= 0:
        return sample.copy()
    return (float(t0) * prior + t_eff * sample) / total


def apply_views(mu: pd.Series, sigma: pd.DataFrame, tau: float,
                views) -> pd.Series:
    """Black-Litterman absolute views on top of `mu`.

    `views` is a sequence of ``(ticker, q, sd)``: the view's value in the same
    units as `mu`, and its standard deviation (``omega = diag(sd^2)``).  With
    no views `mu` comes back unchanged.
    """
    views = list(views)
    if not views:
        return mu
    from pypfopt.black_litterman import BlackLittermanModel

    absolute = {t: float(q) for t, q, _ in views}
    omega = np.diag([float(sd) ** 2 for _, _, sd in views])
    # The posterior uses only tau * Sigma, and pypfopt rejects tau > 1 (short
    # windows, T0 = 0), so hand it tau * Sigma with tau = 1: same numbers.
    bl = BlackLittermanModel(sigma * float(tau), pi=mu, absolute_views=absolute,
                             omega=omega, tau=1.0)
    post = bl.bl_returns()
    return post.reindex(mu.index).astype(float)
