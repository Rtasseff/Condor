"""Optimization engine: portfolio evaluation and single-shot solves.

`_perf` (return / dispersion / Sharpe for a weight vector), `_solve` (one
PyPortfolioOpt solve) and `_weights_dict` are the numeric primitives the
domain model in `model.py` is built on.  `compute_analysis` is the
procedural facade that produces the Explorer's one-dict payload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import cvxpy as cp
from pypfopt import EfficientFrontier

from . import stats

N_FRONTIER_POINTS = 40
N_CAL_POINTS = 41  # two-fund mixes sampled along the capital allocation line
WEIGHT_BOUNDS = (0.0, 1.0)  # long-only, no leverage (prototype)


def _perf(w: np.ndarray, mu: pd.Series, sigma: pd.DataFrame, rf: float) -> dict:
    """Return/vol/Sharpe for a weight vector (legacy asset_set_perform)."""
    m = mu.to_numpy()
    s = sigma.to_numpy()
    ret = float(w @ m)
    vol = float(np.sqrt(w @ s @ w))
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return {"ret": ret, "vol": vol, "sharpe": sharpe}


def _cal_mix(risky_fraction: float, risk_free_rate: float,
             tangency_ret: float, tangency_vol: float) -> dict:
    """Return/vol/Sharpe of a two-fund mix on the capital allocation line.

    `risky_fraction` (k) of wealth is held in the tangency portfolio and
    1-k at the risk-free rate; k > 1 means borrowing at that rate.  Both
    moments are linear in k -- that IS the CAL -- so Sharpe is constant
    along the line (NaN at k=0, where dispersion is zero).
    """
    k = float(risky_fraction)
    rf = float(risk_free_rate)
    ret = rf + k * (tangency_ret - rf)
    vol = k * float(tangency_vol)
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return {"ret": ret, "vol": vol, "sharpe": sharpe}


def _weights_dict(w: np.ndarray, tickers: list[str]) -> dict[str, float]:
    return {t: round(float(x), 6) for t, x in zip(tickers, w) if abs(x) > 1e-5}


def _solve(mu: pd.Series, sigma: pd.DataFrame, kind: str, constraints=None,
           **kw) -> np.ndarray:
    """One-shot pypfopt solve (EfficientFrontier objects are single-use).

    `constraints` is None (today's path, untouched) or a resolved set of
    limits (`Constraints.resolve`): per-asset bounds plus group limits.
    Infeasible limits raise ValueError("These limits can't all hold: ...").
    """
    if constraints is None:
        ef = EfficientFrontier(mu, sigma, weight_bounds=WEIGHT_BOUNDS)
        _run(ef, mu, kind, kw)
        w = ef.clean_weights()
        return np.array([w[t] for t in mu.index])
    _check_limits(constraints)
    ef = EfficientFrontier(mu, sigma, weight_bounds=list(constraints.bounds))
    for idx, lo, hi in constraints.groups:
        ix = list(idx)
        if lo > 0.0:
            ef.add_constraint(lambda w, ix=ix, lo=lo: cp.sum(w[ix]) >= lo)
        if hi < 1.0:
            ef.add_constraint(lambda w, ix=ix, hi=hi: cp.sum(w[ix]) <= hi)
    try:
        _run(ef, mu, kind, kw)
    except Exception as e:
        _raise_if_infeasible(constraints)
        raise ValueError(f"The optimizer couldn't solve this ({e}).") from e
    w = ef.clean_weights()
    return np.array([w[t] for t in mu.index])


def _run(ef: EfficientFrontier, mu: pd.Series, kind: str, kw: dict) -> None:
    if kind == "exact_return":
        # minimum dispersion at *exactly* this expected return (the
        # comparison "same return" in the gaps); efficient_return is ">= ".
        target, m = float(kw["target_return"]), mu.to_numpy(dtype=float)
        ef.add_constraint(lambda w: m @ w == target)
        ef.min_volatility()
    else:
        getattr(ef, kind)(**kw)


def _return_range(mu: pd.Series, resolved=None) -> tuple[float, float]:
    """(lowest, highest) expected return any allowed mix can have."""
    if resolved is None:
        return float(mu.min()), float(mu.max())
    m = mu.to_numpy(dtype=float)
    hi = _max_return_lp(m, resolved)
    lo = _max_return_lp(-m, resolved)
    if hi is None or lo is None:
        _raise_if_infeasible(resolved)
        raise ValueError(f"{_LIMITS_MSG}no mix satisfies them.")
    return float(lo @ m), float(hi @ m)


# ----------------------------------------------------------------------
# constraints (ADR 0008): limits on weights, long-only, fully invested
# ----------------------------------------------------------------------
_LIMITS_MSG = "These limits can't all hold: "


def _check_limits(resolved) -> None:
    """Cheap arithmetic checks that name the conflict in plain words."""
    lo_sum = sum(lo for lo, _ in resolved.bounds)
    hi_sum = sum(hi for _, hi in resolved.bounds)
    if lo_sum > 1 + 1e-9:
        raise ValueError(f"{_LIMITS_MSG}the minimums add up to "
                         f"{100 * lo_sum:.1f}%, above 100%.")
    if hi_sum < 1 - 1e-9:
        raise ValueError(f"{_LIMITS_MSG}the maximums add up to "
                         f"only {100 * hi_sum:.1f}%, below 100%.")


def _feasible_set(resolved, w):
    """cvxpy constraints for `w` (fully invested) under the limits."""
    lo = np.array([b[0] for b in resolved.bounds])
    hi = np.array([b[1] for b in resolved.bounds])
    cons = [cp.sum(w) == 1, w >= lo, w <= hi]
    for idx, glo, ghi in resolved.groups:
        ix = list(idx)
        if glo > 0.0:
            cons.append(cp.sum(w[ix]) >= glo)
        if ghi < 1.0:
            cons.append(cp.sum(w[ix]) <= ghi)
    return cons


def _max_return_lp(mu: np.ndarray, resolved) -> np.ndarray | None:
    """argmax of mu'w within the limits (LP), or None if none exist."""
    w = cp.Variable(len(mu))
    prob = cp.Problem(cp.Maximize(mu @ w), _feasible_set(resolved, w))
    try:
        prob.solve(solver=cp.CLARABEL)
    except cp.error.SolverError:
        return None
    if prob.status not in ("optimal", "optimal_inaccurate") or w.value is None:
        return None
    return np.asarray(w.value, dtype=float)


def _raise_if_infeasible(resolved) -> None:
    """After a solver failure: say so if the limits themselves conflict."""
    _check_limits(resolved)
    if _max_return_lp(np.zeros(len(resolved.bounds)), resolved) is None:
        raise ValueError(f"{_LIMITS_MSG}a group limit conflicts with the "
                         "limits on its assets or on the rest.")


def _constrained_max_return(mu: pd.Series, resolved) -> np.ndarray:
    """The highest-return mix within the limits (the frontier's top end)."""
    _check_limits(resolved)
    w = _max_return_lp(mu.to_numpy(dtype=float), resolved)
    if w is None:
        _raise_if_infeasible(resolved)
        raise ValueError(f"{_LIMITS_MSG}no mix satisfies them.")
    return _clean(w, resolved)


def _clean(w: np.ndarray, resolved) -> np.ndarray:
    """Drop solver dust and clip into the per-asset bounds."""
    lo = np.array([b[0] for b in resolved.bounds])
    hi = np.array([b[1] for b in resolved.bounds])
    w = np.clip(np.where(np.abs(w) < 1e-9, 0.0, w), lo, hi)
    return w / w.sum()


def _constrained_tangency(mu: pd.Series, sigma: pd.DataFrame, rf: float,
                          resolved) -> np.ndarray | None:
    """Max-Sharpe mix within the limits, or None if none beats `rf`.

    The homogenized convex QP of ADR 0008 section 1: with ``y = k w``,
    minimize ``y' Sigma y`` subject to ``(mu - rf)' y = 1``, ``sum(y) = k``,
    ``k lo <= y <= k hi`` and group limits scaled by k; then ``w = y / k``.
    Raises ValueError when the limits themselves are infeasible.
    """
    _check_limits(resolved)
    m = mu.to_numpy(dtype=float)
    best = _max_return_lp(m, resolved)
    if best is None:
        _raise_if_infeasible(resolved)
        raise ValueError(f"{_LIMITS_MSG}no mix satisfies them.")
    if float(best @ m) - rf <= 1e-12:
        return None  # nothing allowed beats the risk-free rate
    n = len(m)
    y = cp.Variable(n)
    k = cp.Variable()
    lo = np.array([b[0] for b in resolved.bounds])
    hi = np.array([b[1] for b in resolved.bounds])
    cons = [(m - rf) @ y == 1, cp.sum(y) == k, k >= 0, y >= k * lo, y <= k * hi]
    for idx, glo, ghi in resolved.groups:
        ix = list(idx)
        if glo > 0.0:
            cons.append(cp.sum(y[ix]) >= k * glo)
        if ghi < 1.0:
            cons.append(cp.sum(y[ix]) <= k * ghi)
    S = cp.psd_wrap(sigma.to_numpy(dtype=float))
    prob = cp.Problem(cp.Minimize(cp.quad_form(y, S)), cons)
    try:
        prob.solve(solver=cp.CLARABEL)
    except cp.error.SolverError as e:
        raise ValueError(f"The optimizer couldn't solve this ({e}).") from e
    if prob.status not in ("optimal", "optimal_inaccurate") or y.value is None:
        raise ValueError(f"The optimizer couldn't solve this ({prob.status}).")
    return _clean(np.asarray(y.value, dtype=float) / float(k.value), resolved)


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
    rf_history: pd.Series | None = None,
    rf_level: float | None = None,
    scenario_windows=None,
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
    rf_history / rf_level: T-bill history and level for premium mode
             (expected return = rf_level + premium); see `AssetSet`.
    """
    from .model import AssetSet  # local import: model builds on this module

    return AssetSet(prices, method=method, metric=metric, timeframe=timeframe,
                    samp_int=samp_int, basis=basis, rf_history=rf_history,
                    rf_level=rf_level).analysis(
        weights=weights, risk_free_rate=risk_free_rate, n_points=n_points,
        scenario_windows=scenario_windows
    )
