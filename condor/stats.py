"""Expected returns and risk models.

Two estimation methods, mirroring the legacy Condor design (genFin/genStats):

- "normal": arithmetic mean daily return x 252 + Ledoit-Wolf shrunk
  covariance (via PyPortfolioOpt). Arithmetic, not geometric/CAGR, so it
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
    freq = annual_factor(timeframe)
    if method == "robust":
        return rets.median() * freq
    # compounding=False -> arithmetic mean * freq (pypfopt's default is the
    # geometric/CAGR form, which is NOT what legacy Condor computed)
    return expected_returns.mean_historical_return(
        rets, returns_data=True, frequency=freq,
        compounding=(basis == "geometric" and metric != "log"),
    )


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
        ).ledoit_wolf()
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
