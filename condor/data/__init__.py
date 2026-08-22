"""Data layer: price store + pluggable sources + risk-free rate.

    fetch_prices(["MSFT", "NEE"], years=10)   # adj-close frame, as before
    risk_free_rate()                          # {'rate': .., 'as_of': ..}
    PriceStore().info()                       # what's on disk

Store: one Parquet per ticker in ~/.condor/prices (CONDOR_DATA_DIR to
move it), incremental updates with a corporate-action seam check.
Sources: yfinance -> stooq failover; tiingo by explicit request
(source="tiingo", needs TIINGO_API_KEY). Design notes: docs/decisions/.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .sources import DataFetchError, get_sources  # noqa: F401
from .store import PriceStore
from .rates import risk_free_rate  # noqa: F401

DEFAULT_YEARS = 10


def fetch_prices(tickers: list[str], years: int = DEFAULT_YEARS,
                 source: str | None = None,
                 store: PriceStore | None = None) -> pd.DataFrame:
    """Daily adjusted closes, one column per ticker, rows = shared dates.

    Same contract as v1: inner-joins on date, requires >= 60 shared days,
    raises DataFetchError naming the first ticker that fails. Now served
    from the PriceStore (any lookback is a slice of one stored history).
    """
    if not tickers:
        raise DataFetchError("No tickers given.")
    store = store or PriceStore()
    start = date.today() - timedelta(days=round(years * 365.25))
    series = []
    for t in tickers:
        frame = store.get(t, start=start, source=source)
        series.append(frame["adj_close"].rename(t.upper()))
    prices = pd.concat(series, axis=1).dropna()
    if len(prices) < 60:
        raise DataFetchError(
            "After aligning dates the assets share too little history "
            f"({len(prices)} days). Try a shorter lookback or different assets."
        )
    return prices
