"""History engine: what a value series actually went through.

Pure functions over a prices-like `values` Series (DatetimeIndex, ascending,
positive).  `Portfolio.history()` feeds these its fixed-weight
`value_index`; nothing here knows about portfolios.

    max_drawdown(values)         worst peak-to-trough fall and its dates
    calendar_year_returns(values) return per calendar year (first/last partial)
    cagr(values)                 compound growth per year, years = days / 365.25
"""

from __future__ import annotations

import pandas as pd

DAYS_PER_YEAR = 365.25


def _clean(values: pd.Series) -> pd.Series:
    v = pd.Series(values).dropna()
    if len(v) < 2:
        raise ValueError("need at least two values")
    return v


def max_drawdown(values: pd.Series) -> dict:
    """Worst fall from a running peak.

    Returns {'depth': -0.25, 'peak': date, 'trough': date, 'recovery': date
    | None}.  `depth` is negative (0.0 if the series never falls); `peak` is
    the last time the running maximum was set before the trough; `recovery`
    is the first date after the trough at which the value is back at the
    peak, None if it never was.
    """
    v = _clean(values)
    running = v.cummax()
    dd = v / running - 1.0
    trough = dd.idxmin()
    depth = float(dd.loc[trough])
    if depth >= 0:
        return {"depth": 0.0, "peak": v.index[0], "trough": v.index[0],
                "recovery": v.index[0]}
    peak_value = running.loc[trough]
    before = v.loc[:trough]
    peak = before[before >= peak_value].index[-1]
    after = v.loc[trough:]
    back = after[after >= peak_value]
    return {"depth": depth, "peak": peak, "trough": trough,
            "recovery": back.index[0] if len(back) else None}


def calendar_year_returns(values: pd.Series) -> pd.Series:
    """Return per calendar year, indexed by year.

    Each year runs from the previous year's last value to its own last
    value; the first year starts at the series' first value, so the first
    (and a not-yet-finished last) year is *partial* — the caller labels it.
    """
    v = _clean(values)
    year_end = v.groupby(v.index.year).last()
    start = pd.concat([pd.Series([v.iloc[0]]), year_end.iloc[:-1]]).to_numpy()
    out = pd.Series(year_end.to_numpy() / start - 1.0, index=year_end.index)
    out.index.name = "year"
    return out


def cagr(values: pd.Series) -> float:
    """Compound annual growth rate; years = elapsed days / 365.25."""
    v = _clean(values)
    years = (v.index[-1] - v.index[0]).total_seconds() / 86400 / DAYS_PER_YEAR
    if years <= 0:
        raise ValueError("series spans no time")
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / years) - 1.0)
