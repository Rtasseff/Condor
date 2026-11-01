"""Portfolio history (F4): hand cases for the pure engine + model == engine."""
import numpy as np
import pandas as pd
import pytest

from condor import AssetSet, history


def series(vals, start="2020-01-01", freq="D"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq=freq),
                     dtype=float)


def test_max_drawdown_recovered():
    v = series([100, 120, 90, 130])
    d = history.max_drawdown(v)
    assert d["depth"] == pytest.approx(-0.25)
    assert d["peak"] == v.index[1] and d["trough"] == v.index[2]
    assert d["recovery"] == v.index[3]


def test_max_drawdown_never_recovered():
    v = series([100, 120, 90, 110])
    d = history.max_drawdown(v)
    assert d["depth"] == pytest.approx(-0.25) and d["recovery"] is None


def test_max_drawdown_picks_the_deeper_of_two():
    v = series([100, 90, 100, 150, 75, 160])
    d = history.max_drawdown(v)
    assert d["depth"] == pytest.approx(-0.5)
    assert d["peak"] == v.index[3] and d["trough"] == v.index[4]
    assert d["recovery"] == v.index[5]


def test_cagr_730_5_days_is_ten_percent():
    start = pd.Timestamp("2020-01-01")
    v = pd.Series([100.0, 121.0],
                  index=[start, start + pd.Timedelta(days=730, hours=12)])
    assert history.cagr(v) == pytest.approx(0.10, abs=1e-12)  # 2.0 years exactly


def test_calendar_years_known_year_ends():
    idx = pd.to_datetime(["2020-03-02", "2020-12-31", "2021-06-30", "2021-12-31",
                          "2022-02-01"])
    v = pd.Series([100.0, 110.0, 99.0, 132.0, 66.0], index=idx)
    y = history.calendar_year_returns(v)
    assert list(y.index) == [2020, 2021, 2022]
    assert y.loc[2020] == pytest.approx(0.10)          # partial: first value -> year end
    assert y.loc[2021] == pytest.approx(132 / 110 - 1)
    assert y.loc[2022] == pytest.approx(-0.5)          # partial: year not over


@pytest.fixture
def aset():
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2020-01-01", periods=700)
    r = rng.normal(0.0003, 0.01, (700, 2)); r[0] = 0
    return AssetSet(pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx,
                                 columns=["A", "B"]), "robust")


def test_portfolio_history_equals_the_engine(aset):
    p = aset.portfolio({"A": 0.6, "B": 0.4})
    h = p.history()
    v = p.value_index
    assert h.max_drawdown == history.max_drawdown(v)
    pd.testing.assert_series_equal(h.years, history.calendar_year_returns(v))
    assert h.cagr == history.cagr(v)
    d = p.to_dict(0.02)["history"]
    assert d == h.to_dict()
    assert "fixed weights" in d["basis"]
    assert d["max_drawdown"]["depth"] == h.max_drawdown["depth"]
    assert d["years"][0]["partial"] is False or d["years"][0]["year"] == 2020
    assert d["worst_year"]["ret"] == min(y["ret"] for y in d["years"])
