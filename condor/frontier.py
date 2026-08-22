"""Optimization engine: portfolio evaluation and single-shot solves.

`_perf` (return / dispersion / Sharpe for a weight vector), `_solve` (one
PyPortfolioOpt solve) and `_weights_dict` are the numeric primitives the
domain model in `model.py` is built on.  `compute_analysis` is the
procedural facade that produces the Explorer's one-dict payload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier

from . import stats

N_FRONTIER_POINTS = 40
WEIGHT_BOUNDS = (0.0, 1.0)  # long-only, no leverage (prototype)


def _perf(w: np.ndarray, mu: pd.Series, sigma: pd.DataFrame, rf: float) -> dict:
    """Return/vol/Sharpe for a weight vector (legacy asset_set_perform)."""
    m = mu.to_numpy()
    s = sigma.to_numpy()
    ret = float(w @ m)
    vol = float(np.sqrt(w @ s @ w))
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return {"ret": ret, "vol": vol, "sharpe": sharpe}


def _weights_dict(w: np.ndarray, tickers: list[str]) -> dict[str, float]:
    return {t: round(float(x), 6) for t, x in zip(tickers, w) if abs(x) > 1e-5}


def _solve(mu: pd.Series, sigma: pd.DataFrame, kind: str, **kw) -> np.ndarray:
    """One-shot pypfopt solve (EfficientFrontier objects are single-use)."""
    ef = EfficientFrontier(mu, sigma, weight_bounds=WEIGHT_BOUNDS)
    getattr(ef, kind)(**kw)
    w = ef.clean_weights()
    return np.array([w[t] for t in mu.index])


def compute_analysis(
    prices: pd.DataFrame,
    weights: dict[str, float] | None = None,
    risk_free_rate: float = 0.02,
    method: str = "normal",
    n_points: int = N_FRONTIER_POINTS,
    *,
    metric: str = "relative",
    timeframe: str = "D",
    samp_int: int | None = None,
    basis: str = "arithmetic",
) -> dict:
    """Full analysis payload for a set of assets (procedural facade).

    Equivalent to ``AssetSet(prices, method, metric=..., timeframe=...,
    samp_int=..., basis=...).analysis(weights, risk_free_rate, n_points)`` —
    kept as the one-call entry point for the web view and for tests that
    pin the numbers.

    weights: optional {ticker: weight} for the user's current portfolio;
             defaults to equal weights. Weights are normalized to sum to 1.
    metric / timeframe / samp_int / basis: return-calculation options,
             documented on `AssetSet` and `stats.py`.
    """
    from .model import AssetSet  # local import: model builds on this module

    return AssetSet(prices, method=method, metric=metric, timeframe=timeframe,
                    samp_int=samp_int, basis=basis).analysis(
        weights=weights, risk_free_rate=risk_free_rate, n_points=n_points
    )
