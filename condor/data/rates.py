"""Risk-free rate from FRED (St. Louis Fed), no API key needed.

Uses Treasury *constant-maturity* yields (H.15 release): secondary-market
trading yields interpolated to a fixed maturity, quoted bond-equivalent —
i.e. directly comparable to an annualized return, which is what the
Sharpe ratio wants. Default is the 3-month series (DGS3MO), the standard
"risk-free rate" convention; other maturities are offered because the
right comparison depends on horizon, but note that long bonds are NOT
risk-free over short horizons (their prices swing).

Cached next to the price store for CACHE_HOURS; falls back to the cached
value (however old) if FRED is unreachable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

from .store import PriceStore, _age_hours

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
MATURITIES = {"1m": "DGS1MO", "3m": "DGS3MO", "1y": "DGS1", "10y": "DGS10"}
DEFAULT_MATURITY = "3m"
CACHE_HOURS = 12.0


def _fetch_series(series: str) -> pd.Series:
    """Latest values of a FRED daily series (last ~2 weeks are plenty)."""
    import requests

    resp = requests.get(FRED_URL.format(series=series), timeout=30)
    resp.raise_for_status()
    from io import StringIO
    frame = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True,
                        na_values=".")
    return frame.iloc[:, 0].dropna()


def risk_free_rate(maturity: str = DEFAULT_MATURITY,
                   store: PriceStore | None = None) -> dict:
    """{'rate': 0.0431, 'as_of': '2026-08-21', 'maturity': '3m', 'series': ...}

    `rate` is a decimal annual yield, ready to use as `risk_free_rate=` in
    the analytics. Raises DataFetchError only if FRED is unreachable AND
    nothing is cached.
    """
    if maturity not in MATURITIES:
        raise ValueError(f"Unknown maturity '{maturity}'; one of {sorted(MATURITIES)}")
    series = MATURITIES[maturity]
    store = store or PriceStore()
    cache_path = store.root / "rates.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    entry = cache.get(series)
    if entry and _age_hours(entry["fetched_at"]) < CACHE_HOURS:
        return {k: entry[k] for k in ("rate", "as_of", "maturity", "series")}

    try:
        values = _fetch_series(series)
    except Exception as e:
        if entry:  # stale beats nothing
            return {k: entry[k] for k in ("rate", "as_of", "maturity", "series")}
        from .sources import DataFetchError
        raise DataFetchError(f"Could not fetch {series} from FRED: {e}") from e

    result = {
        "rate": round(float(values.iloc[-1]) / 100.0, 6),
        "as_of": str(values.index[-1].date()),
        "maturity": maturity,
        "series": series,
    }
    cache[series] = {**result,
                     "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    store.root.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return result


def risk_free_history(maturity: str = DEFAULT_MATURITY,
                      store: PriceStore | None = None) -> pd.Series:
    """The full daily yield history, annual decimals, DatetimeIndex.

    Same FRED series as `risk_free_rate` (the CSV is the whole history).
    Cached as Parquet next to rates.json and refreshed after CACHE_HOURS;
    if FRED is unreachable the cache is served however old. Raises
    DataFetchError only if FRED is unreachable AND nothing is cached.
    """
    if maturity not in MATURITIES:
        raise ValueError(f"Unknown maturity '{maturity}'; one of {sorted(MATURITIES)}")
    series = MATURITIES[maturity]
    store = store or PriceStore()
    path = store.root / f"rates_{series}.parquet"

    def _read() -> pd.Series:
        s = pd.read_parquet(path)["yield"]
        s.index = pd.DatetimeIndex(s.index)
        s.name = series
        return s

    cached: pd.Series | None = None
    if path.exists():
        try:
            cached = _read()
        except Exception:  # truncated / corrupt cache: treat as absent
            cached = None
    if cached is not None:
        age = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600
        if age < CACHE_HOURS:
            return cached
    try:
        values = _fetch_series(series).dropna()
        if values.empty:
            raise ValueError("empty series")
    except Exception as e:
        if cached is not None:  # stale beats nothing
            return cached
        from .sources import DataFetchError
        raise DataFetchError(f"Could not fetch {series} from FRED: {e}") from e

    hist = (values.astype(float) / 100.0).rename(series)
    hist.index = pd.DatetimeIndex(hist.index)
    store.root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    hist.to_frame("yield").to_parquet(tmp)
    os.replace(tmp, path)  # atomic: a concurrent reader never sees a partial file
    return hist
