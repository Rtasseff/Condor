"""History engine: what a value series actually went through.

Pure functions over a prices-like `values` Series (DatetimeIndex, ascending,
positive).  `Portfolio.history()` feeds these its fixed-weight
`value_index`; nothing here knows about portfolios.

    max_drawdown(values)         worst peak-to-trough fall and its dates
    calendar_year_returns(values) return per calendar year (first/last partial)
    cagr(values)                 compound growth per year, years = days / 365.25
    window_stats(values, start, end)  return and worst fall inside a date window
    SCENARIOS                    named stress windows (S&P 500 closing high to low)
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
    | None}.  `depth` is negative; a series that never falls gives
    {'depth': 0.0, 'peak': None, 'trough': None, 'recovery': None}.  `peak` is
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
        return {"depth": 0.0, "peak": None, "trough": None, "recovery": None}
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


# Named stress windows: S&P 500 closing high to closing low, plus calendar
# 2022 (the stock-and-bond year).  Dates are ISO strings.
SCENARIOS = (
    {"name": "2008 financial crisis", "start": "2007-10-09", "end": "2009-03-09"},
    {"name": "2018 Q4 selloff", "start": "2018-09-20", "end": "2018-12-24"},
    {"name": "2020 Covid crash", "start": "2020-02-19", "end": "2020-03-23"},
    {"name": "2022 inflation shock", "start": "2021-12-31", "end": "2022-12-30"},
)


def window_stats(values: pd.Series, start, end) -> dict:
    """Return and worst fall of a value series between two dates.

    -> {'ret', 'max_drawdown', 'covered', 'first'}.  The window starts at the
    last value on or before `start` and ends at the last value on or before
    `end`; `max_drawdown` is the worst fall from a running peak along that
    path (negative, 0.0 if it never falls).  A window counts only if the
    series covers *both* ends -- `start` no earlier than its first date and
    `end` no later than its last; otherwise `covered` is False and `ret` /
    `max_drawdown` are None (never a partial number).  `first` is the
    series' first date (ISO string).  Raises ValueError if start >= end.
    """
    v = _clean(values).sort_index()
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start >= end:
        raise ValueError("a window's start must be before its end")
    first = str(v.index[0].date())
    if start < v.index[0] or end > v.index[-1]:
        return {"ret": None, "max_drawdown": None, "covered": False,
                "first": first}
    path = v.loc[:end]
    i0 = path.index.searchsorted(start, side="right") - 1
    path = path.iloc[i0:]
    ret = float(path.iloc[-1] / path.iloc[0] - 1.0)
    dd = float((path / path.cummax() - 1.0).min())
    return {"ret": ret, "max_drawdown": dd, "covered": True, "first": first}
