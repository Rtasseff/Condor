"""Scenario windows: hand cases for the pure engine + model == engine."""
import numpy as np
import pandas as pd
import pytest

from condor import AssetSet, history


def series(vals, start="2020-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals)),
                     dtype=float)


V = series([100, 120, 90, 130])
D = list(V.index)


def test_window_stats_inside_fall():
    s = history.window_stats(V, D[1], D[2])
    assert s["covered"] and s["ret"] == pytest.approx(-0.25)
    assert s["max_drawdown"] == pytest.approx(-0.25)


def test_window_stats_whole_series():
    s = history.window_stats(V, D[0], D[3])
    assert s["ret"] == pytest.approx(0.30)
    assert s["max_drawdown"] == pytest.approx(-0.25)
    assert s["first"] == "2020-01-01"


def test_start_between_dates_uses_prior_value():
    s = history.window_stats(V, D[1] + pd.Timedelta(hours=12), D[3])
    assert s["ret"] == pytest.approx(130 / 120 - 1)


def test_end_between_dates_uses_prior_value():
    s = history.window_stats(V, D[0], D[2] + pd.Timedelta(hours=12))
    assert s["ret"] == pytest.approx(-0.10)


def test_not_covered_is_null_never_partial():
    before = history.window_stats(V, D[0] - pd.Timedelta(days=5), D[2])
    after = history.window_stats(V, D[1], D[3] + pd.Timedelta(days=1))
    for s in (before, after):
        assert s["covered"] is False
        assert s["ret"] is None and s["max_drawdown"] is None
        assert s["first"] == "2020-01-01"


def test_start_not_before_end():
    with pytest.raises(ValueError):
        history.window_stats(V, D[2], D[2])
    with pytest.raises(ValueError):
        history.window_stats(V, D[3], D[1])


def test_scenario_constants():
    names = [w["name"] for w in history.SCENARIOS]
    assert names == ["2008 financial crisis", "2018 Q4 selloff",
                     "2020 Covid crash", "2022 inflation shock"]
    for w in history.SCENARIOS:
        assert pd.Timestamp(w["start"]) < pd.Timestamp(w["end"])


@pytest.fixture
def aset():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2019-06-03", "2021-06-30")
    r = rng.normal(0.0004, 0.01, (len(idx), 2))
    return AssetSet(pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx,
                                 columns=["AAA", "BBB"]))


def test_portfolio_scenarios_equal_engine(aset):
    p = aset.portfolio({"AAA": 0.6, "BBB": 0.4})
    out = {w["name"]: w for w in p.scenarios()}
    want = history.window_stats(p.value_index, "2020-02-19", "2020-03-23")
    covid = out["2020 Covid crash"]
    assert covid["covered"] and covid["ret"] == want["ret"]
    assert covid["max_drawdown"] == want["max_drawdown"]
    assert (covid["start"], covid["end"]) == ("2020-02-19", "2020-03-23")
    # window earlier than the data / later than the data
    assert out["2008 financial crisis"]["covered"] is False
    assert out["2022 inflation shock"]["covered"] is False
    assert out["2008 financial crisis"]["first"] == str(p.value_index.index[0].date())


def test_custom_windows_and_rejects_bad(aset):
    p = aset.equal_weight()
    got = p.scenarios([{"name": "mine", "start": "2020-01-02", "end": "2020-06-30"}])
    assert [g["name"] for g in got] == ["mine"] and got[0]["covered"]
    with pytest.raises(ValueError):
        p.scenarios([{"name": "x", "start": "2020-06-30", "end": "2020-01-02"}])


def test_analysis_adds_scenarios_only(aset):
    out = aset.analysis({"AAA": 1.0}, 0.02)
    sc = out["scenarios"]
    assert sc["basis"] == "fixed_weights_daily"
    assert len(sc["portfolio"]) == 4
    assert sc["portfolio"][2]["ret"] == aset.portfolio({"AAA": 1.0}).scenarios()[2]["ret"]
    assert out["tangency"] is None or sc["tangency"] is not None
    custom = aset.analysis(None, 0.02, scenario_windows=[
        {"name": "c", "start": "2020-01-02", "end": "2020-02-03"}])
    assert [w["name"] for w in custom["scenarios"]["portfolio"]] == ["c"]
    assert "scenarios" not in out["frontier"][0]


def test_window_with_no_trading_day_is_not_covered():
    # D[1] .. D[1]+12h holds only the opening value: nothing happened in it
    s = history.window_stats(V, D[1], D[1] + pd.Timedelta(hours=12))
    assert s["covered"] is False and s["ret"] is None
    assert s["reason"] == "no_trading_days"
    assert history.window_stats(V, D[0] - pd.Timedelta(days=3), D[2])["reason"] == "before_start"
    assert history.window_stats(V, D[1], D[3] + pd.Timedelta(days=3))["reason"] == "after_end"
    assert history.window_stats(V, D[0], D[3])["reason"] is None


def test_monthly_timeframe_scenarios_use_the_daily_series(aset):
    w = {"AAA": 0.6, "BBB": 0.4}
    daily = aset.portfolio(w).scenarios()
    monthly = aset.with_options(timeframe="M").portfolio(w).scenarios()
    for a, b in zip(daily, monthly):
        assert a["covered"] == b["covered"]
        if a["covered"]:
            assert b["ret"] == pytest.approx(a["ret"], abs=1e-12)
            assert b["max_drawdown"] == pytest.approx(a["max_drawdown"], abs=1e-12)
