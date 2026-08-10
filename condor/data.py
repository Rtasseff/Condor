"""Historical price data via yfinance, with a simple local cache.

Prototype scope: daily adjusted closes for standard market assets.
The cache lives in .condor_cache/ (gitignored) so repeated analyses
don't re-hit the network; entries refresh after CACHE_MAX_AGE_HOURS.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent.parent / ".condor_cache"
CACHE_MAX_AGE_HOURS = 24.0
DEFAULT_YEARS = 10


class DataFetchError(Exception):
    """Raised when no usable price data comes back for a ticker."""


def _cache_path(ticker: str, years: int) -> Path:
    safe = ticker.upper().replace("/", "-").replace("^", "_")
    return CACHE_DIR / f"{safe}_{years}y.csv"


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours < CACHE_MAX_AGE_HOURS


def _fetch_one(ticker: str, years: int) -> pd.Series:
    """Return a daily adjusted-close series for one ticker."""
    path = _cache_path(ticker, years)
    if _cache_fresh(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.iloc[:, 0]

    raw = yf.download(
        ticker,
        period=f"{years}y",
        interval="1d",
        auto_adjust=True,  # adjusted close lands in the Close column
        progress=False,
        threads=False,
    )
    if raw is None or len(raw) == 0:
        raise DataFetchError(f"No price data returned for '{ticker}'.")

    close = raw["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance returns MultiIndex columns
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < 60:
        raise DataFetchError(
            f"Only {len(close)} daily observations for '{ticker}'; "
            "not enough history to estimate statistics."
        )

    CACHE_DIR.mkdir(exist_ok=True)
    close.rename(ticker.upper()).to_frame().to_csv(path)
    return close.rename(ticker.upper())


def fetch_prices(tickers: list[str], years: int = DEFAULT_YEARS) -> pd.DataFrame:
    """Daily adjusted closes, one column per ticker, rows = shared dates.

    Raises DataFetchError naming the first ticker that fails.
    """
    if not tickers:
        raise DataFetchError("No tickers given.")
    series = [_fetch_one(t, years) for t in tickers]
    prices = pd.concat(series, axis=1).dropna()
    if len(prices) < 60:
        raise DataFetchError(
            "After aligning dates the assets share too little history "
            f"({len(prices)} days). Try a shorter lookback or different assets."
        )
    return prices
