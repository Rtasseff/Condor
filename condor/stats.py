"""Expected returns and risk models.

Two estimation methods, mirroring the legacy Condor design (genFin/genStats):

- "normal": mean historical return + Ledoit-Wolf shrunk covariance
  (the established defaults, via PyPortfolioOpt).
- "robust": median return + CoMAD co-dispersion matrix with the 1.4826
  normality correction — the legacy Condor approach, resistant to outliers.
  CoMAD is not guaranteed positive semi-definite, so it gets a spectral
  PSD repair before any convex optimization sees it.

Everything is annualized (daily basis, 252 trading days).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pypfopt import expected_returns, risk_models

TRADING_DAYS = 252
MAD_NORMAL_COR = 1.4826  # MAD -> std consistency factor for normal data

METHODS = ("normal", "robust")


def asset_returns(prices: pd.DataFrame, metric: str = "relative") -> pd.DataFrame:
    """Daily returns from a prices frame (columns = assets)."""
    if metric == "relative":
        rets = prices.pct_change()
    elif metric == "log":
        rets = np.log(prices / prices.shift(1))
    else:
        raise ValueError(f"Unknown return metric: {metric}")
    return rets.dropna(how="all")


def _check_method(method: str) -> None:
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}'; expected one of {METHODS}")


def expected_annual(prices: pd.DataFrame, method: str = "normal") -> pd.Series:
    """Annualized expected return per asset."""
    _check_method(method)
    if method == "normal":
        return expected_returns.mean_historical_return(
            prices, frequency=TRADING_DAYS
        )
    rets = asset_returns(prices)
    return rets.median() * TRADING_DAYS


def _comad_matrix(rets: pd.DataFrame) -> pd.DataFrame:
    """Co-variate Median Absolute Deviation matrix (legacy genStats.comad).

    comad_ij = median[(x_i - med(x_i)) * (x_j - med(x_j))] * 1.4826^2
    Vectorized version of the legacy pairwise loop.
    """
    x = rets.to_numpy()
    med = np.nanmedian(x, axis=0)
    dev = x - med
    n = dev.shape[1]
    out = np.empty((n, n))
    for i in range(n):
        # cross-products of deviations, median over time
        prod = dev * dev[:, [i]]
        out[i, :] = np.nanmedian(prod, axis=0)
    out *= MAD_NORMAL_COR**2
    return pd.DataFrame(out, index=rets.columns, columns=rets.columns)


def risk_matrix_annual(prices: pd.DataFrame, method: str = "normal") -> pd.DataFrame:
    """Annualized co-dispersion-squared (covariance-like) matrix."""
    _check_method(method)
    if method == "normal":
        return risk_models.CovarianceShrinkage(
            prices, frequency=TRADING_DAYS
        ).ledoit_wolf()
    rets = asset_returns(prices)
    comad = _comad_matrix(rets) * TRADING_DAYS
    # CoMAD may be slightly non-PSD; repair so cvxpy accepts it
    return risk_models.fix_nonpositive_semidefinite(comad, fix_method="spectral")


def asset_points(mu: pd.Series, sigma: pd.DataFrame) -> list[dict]:
    """Per-asset (risk, reward) points for plotting."""
    vols = np.sqrt(np.diag(sigma.to_numpy()))
    return [
        {"ticker": t, "ret": float(mu[t]), "vol": float(v)}
        for t, v in zip(mu.index, vols)
    ]
