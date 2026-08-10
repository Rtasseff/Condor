"""Efficient frontier computation and portfolio evaluation.

Produces everything the Explorer UI needs in one plain-dict payload:
per-asset stats, the frontier curve with inspectable weights at every
point, the tangency (max-Sharpe) and minimum-volatility portfolios,
the capital allocation line, and the user's current portfolio point.
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
) -> dict:
    """Full analysis payload for a set of assets.

    weights: optional {ticker: weight} for the user's current portfolio;
             defaults to equal weights. Weights are normalized to sum to 1.
    """
    tickers = list(prices.columns)
    mu = stats.expected_annual(prices, method=method)
    sigma = stats.risk_matrix_annual(prices, method=method)

    result: dict = {
        "tickers": tickers,
        "method": method,
        "risk_free_rate": risk_free_rate,
        "assets": stats.asset_points(mu, sigma),
        "start": str(prices.index[0].date()),
        "end": str(prices.index[-1].date()),
        "n_days": int(len(prices)),
    }

    # --- user's current portfolio -------------------------------------
    if weights:
        w_arr = np.array([max(0.0, float(weights.get(t, 0.0))) for t in tickers])
    else:
        w_arr = np.ones(len(tickers))
    if w_arr.sum() <= 0:
        w_arr = np.ones(len(tickers))
    w_arr = w_arr / w_arr.sum()
    result["portfolio"] = {
        "weights": _weights_dict(w_arr, tickers),
        **_perf(w_arr, mu, sigma, risk_free_rate),
    }

    if len(tickers) < 2:
        # frontier of one asset is a point; nothing more to optimize
        result["frontier"] = []
        result["min_vol"] = result["tangency"] = None
        result["cal"] = None
        return result

    # --- anchor portfolios ---------------------------------------------
    w_minvol = _solve(mu, sigma, "min_volatility")
    minvol = {"weights": _weights_dict(w_minvol, tickers),
              **_perf(w_minvol, mu, sigma, risk_free_rate)}

    tangency = None
    if float(mu.max()) > risk_free_rate:
        w_tan = _solve(mu, sigma, "max_sharpe", risk_free_rate=risk_free_rate)
        tangency = {"weights": _weights_dict(w_tan, tickers),
                    **_perf(w_tan, mu, sigma, risk_free_rate)}

    result["min_vol"] = minvol
    result["tangency"] = tangency

    # --- frontier sweep: min dispersion at each return target ----------
    # (same construction as legacy portOpt.calc_efficient_frontier)
    lo, hi = minvol["ret"], float(mu.max())
    frontier = []
    for target in np.linspace(lo, hi, n_points):
        try:
            w = _solve(mu, sigma, "efficient_return", target_return=float(target))
        except Exception:
            continue  # infeasible edge targets are fine to skip
        frontier.append({"weights": _weights_dict(w, tickers),
                         **_perf(w, mu, sigma, risk_free_rate)})
    result["frontier"] = frontier

    # --- capital allocation line ---------------------------------------
    if tangency:
        x_end = max(
            [p["vol"] for p in frontier + result["assets"]] or [tangency["vol"]]
        )
        result["cal"] = {
            "x": [0.0, x_end * 1.05],
            "y": [risk_free_rate,
                  risk_free_rate + tangency["sharpe"] * x_end * 1.05],
        }
    else:
        result["cal"] = None

    return result
