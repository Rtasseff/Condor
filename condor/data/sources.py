"""Price sources: one protocol, several providers.

A source turns (ticker, start) into a daily DataFrame with two columns:

    close      raw closing price (as traded that day)
    adj_close  total-return price: close adjusted for splits AND dividends

`adj_close` is what the analytics consume — its daily percent changes are
total returns. Note that a split or dividend rewrites the *entire past*
adjusted series; the store (store.py) deals with that via a seam check
(see docs/decisions/0001-price-store-seam-check.md).

Providers:

- YFinanceSource  — default. Free, no key, widest coverage; unofficial
                    scraper of Yahoo's private API, so it breaks occasionally.
- TiingoSource    — official REST API; needs TIINGO_API_KEY (free tier is
                    ample at personal scale). When the key is set it joins
                    the chain as FAILOVER — primary only by explicit
                    request, so numbers don't silently change providers.

(Stooq was evaluated as a no-key failover but now fronts its CSV endpoint
with a JavaScript proof-of-work challenge — no longer scriptable, dropped
2026-08-22. Free no-key EOD APIs have essentially disappeared; an official
key-based source is the honest fallback.)
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd


class DataFetchError(Exception):
    """Raised when no usable price data comes back for a ticker."""


MIN_OBS = 60  # fewer daily observations than this -> refuse to estimate


def _clean(frame: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    """Normalize a provider frame: naive DatetimeIndex, sorted, deduped."""
    if frame.empty:
        raise DataFetchError(f"No price data returned for '{ticker}' ({source}).")
    idx = pd.DatetimeIndex(frame.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    frame = frame.set_axis(idx.normalize()).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame[["close", "adj_close"]].astype(float).dropna(how="any")
    if len(frame) < MIN_OBS:
        raise DataFetchError(
            f"Only {len(frame)} daily observations for '{ticker}' ({source}); "
            "not enough history to estimate statistics."
        )
    return frame


class YFinanceSource:
    name = "yfinance"

    def fetch(self, ticker: str, start: date | None = None) -> pd.DataFrame:
        import yfinance as yf

        kwargs = {"start": str(start)} if start else {"period": "max"}
        raw = yf.download(
            ticker, interval="1d", auto_adjust=False,  # keep raw AND adjusted
            progress=False, threads=False, **kwargs,
        )
        if raw is None or len(raw) == 0:
            raise DataFetchError(f"No price data returned for '{ticker}' (yfinance).")
        if isinstance(raw.columns, pd.MultiIndex):  # single ticker still nests
            raw = raw.droplevel(axis=1, level=1)
        out = pd.DataFrame({"close": raw["Close"], "adj_close": raw["Adj Close"]})
        return _clean(out, ticker, self.name)


class TiingoSource:
    name = "tiingo"
    URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TIINGO_API_KEY")

    def fetch(self, ticker: str, start: date | None = None) -> pd.DataFrame:
        import requests

        if not self.api_key:
            raise DataFetchError(
                "Tiingo needs an API key (set TIINGO_API_KEY; free at tiingo.com)."
            )
        params = {"token": self.api_key, "format": "json"}
        if start:
            params["startDate"] = str(start)
        try:
            resp = requests.get(self.URL.format(ticker=ticker.lower()),
                                params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json()
        except requests.RequestException as e:
            raise DataFetchError(f"Tiingo request failed for '{ticker}': {e}") from e
        if not rows:
            raise DataFetchError(f"No price data returned for '{ticker}' (tiingo).")
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime(frame["date"])
        out = pd.DataFrame({"close": frame["close"], "adj_close": frame["adjClose"]})
        return _clean(out, ticker, self.name)


_REGISTRY = {
    "yfinance": YFinanceSource,
    "tiingo": TiingoSource,
}


def get_sources(source: str | None = None) -> list:
    """Resolve a source spec into an ordered failover chain.

    None -> yfinance, with tiingo as failover when TIINGO_API_KEY is
    set. A single name ("tiingo") -> exactly that source, no silent
    switching. A comma list ("tiingo,yfinance") -> that explicit chain,
    in order — the production shape (docs/DEPLOY.md): datacenter IPs
    get rate-limited by Yahoo, so cloud deploys run Tiingo first with
    Yahoo as the opportunistic fallback. Explicit is still explicit:
    the chain never contains anything the spec didn't name.
    """
    if source is None:
        source = os.environ.get("CONDOR_SOURCE")
    if source is None:
        chain = [YFinanceSource()]
        if os.environ.get("TIINGO_API_KEY"):
            chain.append(TiingoSource())
        return chain
    names = [n.strip() for n in str(source).split(",") if n.strip()]
    unknown = [n for n in names if n not in _REGISTRY]
    if unknown or not names:
        raise DataFetchError(
            f"Unknown source '{source}'; expected names from "
            f"{sorted(_REGISTRY)} (comma-separated for a failover chain)")
    return [_REGISTRY[n]() for n in names]
