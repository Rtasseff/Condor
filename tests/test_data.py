"""Data layer: store round-trips, the seam check catches corporate
actions, TTL prevents needless network hits, and the facade keeps its
v1 contract. All offline via a scripted FakeSource; a couple of
network smoke tests run only with CONDOR_NET_TESTS=1."""

import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from condor.data import DataFetchError, PriceStore, fetch_prices
from condor.data.store import SEAM_ROWS


def make_history(n=400, seed=3, end=None):
    rng = np.random.default_rng(seed)
    end = end or date.today()
    idx = pd.bdate_range(end=end, periods=n)
    close = 100 * np.cumprod(1 + 0.0004 + 0.01 * rng.standard_normal(n))
    return pd.DataFrame({"close": close, "adj_close": close * 0.98}, index=idx)


class FakeSource:
    """Serves slices of a fixed 'true' history; counts calls."""
    name = "fake"

    def __init__(self, history):
        self.history = history
        self.calls = []

    def fetch(self, ticker, start=None):
        self.calls.append(start)
        out = self.history if start is None else self.history.loc[str(start):]
        if out.empty:
            raise DataFetchError(f"no data for {ticker}")
        return out.copy()


@pytest.fixture
def store(tmp_path):
    return PriceStore(tmp_path / "prices")


@pytest.fixture
def fake(store, monkeypatch):
    src = FakeSource(make_history())
    monkeypatch.setattr("condor.data.store.get_sources", lambda s=None: [src])
    return src


START = date.today() - timedelta(days=365)


class TestStore:
    def test_roundtrip_and_slice(self, store, fake):
        got = store.get("msft", start=START)
        pd.testing.assert_frame_equal(got, fake.history.loc[str(START):])
        stored = store.read("MSFT")               # kept from requested start
        pd.testing.assert_frame_equal(stored, fake.history.loc[str(START):],
                                      check_freq=False)
        assert store.as_of("msft") == str(fake.history.index[-1].date())
        assert store.info().loc["MSFT", "source"] == "fake"

    def test_ttl_no_second_hit(self, store, fake):
        store.get("MSFT", start=START)
        store.get("MSFT", start=START)
        assert len(fake.calls) == 1               # second get served from disk

    def test_seam_append(self, store, fake):
        full = fake.history
        fake.history = full.iloc[:-10]            # world as of 10 days ago
        store.get("MSFT", start=START)
        _age(store, "MSFT", hours=30)             # make it stale
        fake.history = full                       # same series, 10 more days
        got = store.get("MSFT", start=START)
        assert got.index[-1] == full.index[-1]
        assert fake.calls[1] is not None          # update was incremental...
        assert len(fake.calls) == 2               # ...and no full re-fetch
        pd.testing.assert_frame_equal(store.read("MSFT"),
                                      full.loc[str(START):], check_freq=False)

    def test_seam_detects_split_and_refetches(self, store, fake):
        store.get("MSFT", start=START)
        _age(store, "MSFT", hours=30)
        fake.history = fake.history / 2.0         # 2:1 split rewrites the past
        got = store.get("MSFT", start=START)
        # stored history was fully replaced by the re-adjusted series
        pd.testing.assert_frame_equal(store.read("MSFT"),
                                      fake.history.loc[str(START):],
                                      check_freq=False)
        assert len(fake.calls) == 3               # initial + seam + full refetch
        assert got["adj_close"].iloc[-1] == fake.history["adj_close"].iloc[-1]

    def test_earlier_start_triggers_full_refetch(self, store, fake):
        fake.history = make_history(n=1500)
        store.get("MSFT", start=START)
        earlier = date.today() - timedelta(days=4 * 365)
        got = store.get("MSFT", start=earlier)
        assert got.index[0] <= pd.Timestamp(earlier) + pd.Timedelta(days=4)
        assert len(fake.calls) == 2

    def test_stale_served_when_source_down(self, store, fake):
        store.get("MSFT", start=START)
        _age(store, "MSFT", hours=30)
        fake.history = fake.history.iloc[:0]      # source now fails
        got = store.get("MSFT", start=START)      # no raise
        assert len(got) > 200

    def test_failover_chain(self, store, monkeypatch):
        bad, good = FakeSource(make_history().iloc[:0]), FakeSource(make_history())
        bad.name, good.name = "dead", "alive"
        monkeypatch.setattr("condor.data.store.get_sources",
                            lambda s=None: [bad, good])
        store.get("MSFT", start=START)
        assert store.info().loc["MSFT", "source"] == "alive"


def _age(store, ticker, hours):
    m = store._manifest()
    old = datetime.now(timezone.utc) - timedelta(hours=hours)
    m[ticker]["fetched_at"] = old.isoformat(timespec="seconds")
    store._write_manifest(m)


class TestFacade:
    def test_contract_unchanged(self, store, fake):
        prices = fetch_prices(["msft", "nee"], years=1, store=store)
        assert list(prices.columns) == ["MSFT", "NEE"]
        assert len(prices) > 200 and prices.notna().all().all()
        with pytest.raises(DataFetchError):
            fetch_prices([], store=store)

    def test_short_overlap_raises(self, store, monkeypatch):
        a = FakeSource(make_history(n=400))
        cut = make_history(n=400)
        b = FakeSource(cut.iloc[-50:])            # only 50 recent days
        sources = {"A": a, "B": b}
        monkeypatch.setattr("condor.data.store.get_sources", lambda s=None: [a])
        fetch_prices(["A"], years=1, store=store)
        monkeypatch.setattr("condor.data.store.get_sources", lambda s=None: [b])
        with pytest.raises(DataFetchError):
            fetch_prices(["A", "B"], years=1, store=store)


class TestRates:
    def test_parse_and_cache(self, store, monkeypatch):
        from condor.data import rates
        csv_vals = pd.Series([4.1, 4.2, np.nan, 4.31],
                             index=pd.to_datetime(
                                 ["2026-08-17", "2026-08-18", "2026-08-19",
                                  "2026-08-20"]))
        calls = []
        def fake_fetch(series):
            calls.append(series)
            return csv_vals.dropna()
        monkeypatch.setattr(rates, "_fetch_series", fake_fetch)
        r = rates.risk_free_rate("3m", store=store)
        assert r == {"rate": 0.0431, "as_of": "2026-08-20",
                     "maturity": "3m", "series": "DGS3MO"}
        r2 = rates.risk_free_rate("3m", store=store)   # cached
        assert r2 == r and len(calls) == 1
        with pytest.raises(ValueError):
            rates.risk_free_rate("7y", store=store)


NET = os.environ.get("CONDOR_NET_TESTS") == "1"
TIINGO = bool(os.environ.get("TIINGO_API_KEY"))


@pytest.mark.skipif(not NET, reason="set CONDOR_NET_TESTS=1 for network tests")
class TestLive:
    @pytest.mark.skipif(not TIINGO, reason="needs TIINGO_API_KEY")
    def test_sources_agree_on_returns(self, tmp_path):
        """yfinance and tiingo daily total returns should nearly match."""
        from condor.data.sources import TiingoSource, YFinanceSource
        start = date.today() - timedelta(days=400)
        yf = YFinanceSource().fetch("AAPL", start=start)["adj_close"]
        ti = TiingoSource().fetch("AAPL", start=start)["adj_close"]
        both = pd.concat([yf.pct_change(), ti.pct_change()], axis=1,
                         join="inner").dropna()
        diff = (both.iloc[:, 0] - both.iloc[:, 1]).abs()
        assert diff.median() < 1e-4
        assert (diff > 5e-3).mean() < 0.02        # dividends/rounding days

    def test_fred(self, tmp_path):
        from condor.data import risk_free_rate
        r = risk_free_rate("3m", store=PriceStore(tmp_path))
        assert 0.0 < r["rate"] < 0.15 and r["series"] == "DGS3MO"


class TestConcurrency:
    """Several web workers / CLI runs may share one store (ADR 0002)."""

    def test_same_ticker_fetched_once(self, store, monkeypatch):
        import threading, time as _t
        history = make_history()

        class SlowSrc:
            name = "slow"
            calls = 0
            def fetch(self, ticker, start=None):
                SlowSrc.calls += 1
                _t.sleep(0.05)
                return history.copy()
        monkeypatch.setattr("condor.data.store.get_sources",
                            lambda source=None: [SlowSrc()])
        results = []
        def worker():
            results.append(store.get("AAA", start=START))
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert SlowSrc.calls == 1                 # waiters reused the download
        assert len(results) == 5
        assert all(len(r) == len(results[0]) for r in results)

    def test_manifest_survives_parallel_tickers(self, store, monkeypatch):
        import threading
        history = make_history()

        class Src:
            name = "fake"
            def fetch(self, ticker, start=None):
                return history.copy()
        monkeypatch.setattr("condor.data.store.get_sources",
                            lambda source=None: [Src()])
        tickers = [f"T{i}" for i in range(8)]
        threads = [threading.Thread(target=store.get,
                                    kwargs={"ticker": t, "start": START})
                   for t in tickers]
        for t in threads: t.start()
        for t in threads: t.join()
        assert store.tickers() == sorted(tickers)  # no lost manifest entries


class TestSourceChains:
    """get_sources: single name = exactly that source; comma list = an
    explicit ordered failover chain (the production shape)."""

    def test_single_name_is_alone(self):
        from condor.data.sources import get_sources
        (only,) = get_sources("tiingo")
        assert only.name == "tiingo"

    def test_comma_list_is_an_ordered_chain(self):
        from condor.data.sources import get_sources
        chain = get_sources("tiingo,yfinance")
        assert [s.name for s in chain] == ["tiingo", "yfinance"]
        chain = get_sources(" yfinance , tiingo ")   # whitespace tolerated
        assert [s.name for s in chain] == ["yfinance", "tiingo"]

    def test_env_var_carries_the_chain(self, monkeypatch):
        from condor.data.sources import get_sources
        monkeypatch.setenv("CONDOR_SOURCE", "tiingo,yfinance")
        assert [s.name for s in get_sources()] == ["tiingo", "yfinance"]

    def test_unknown_names_rejected(self):
        from condor import DataFetchError
        from condor.data.sources import get_sources
        import pytest
        for bad in ("stooq", "tiingo,stooq", ",,"):
            with pytest.raises(DataFetchError):
                get_sources(bad)
