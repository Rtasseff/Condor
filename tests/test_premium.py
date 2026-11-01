"""Premium-over-T-bill estimation (ADR 0006): hand / closed-form checks."""
import numpy as np
import pandas as pd
import pytest
from pypfopt import risk_models

from condor import stats

N = 600


def _dates():
    return pd.bdate_range("2020-01-01", periods=N + 1)


@pytest.fixture
def prices():
    rng = np.random.default_rng(3)
    idx = _dates()
    r = rng.normal([0.0004, 0.0002, 0.0006], [0.01, 0.006, 0.015], (N + 1, 3))
    r[0] = 0
    return pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx,
                        columns=list("ABC"))


@pytest.mark.parametrize("method", ["robust", "normal"])
@pytest.mark.parametrize("metric", ["relative", "log"])
def test_constant_yield_shifts_by_exactly_y(prices, method, metric):
    """median and mean commute with a constant shift, so
    premium == expected - y and rf_level + premium reproduces expected."""
    y = 0.037
    ys = pd.Series(y, index=prices.index)
    exp = stats.expected_annual(prices, method=method, metric=metric)
    prem = stats.premium_annual(prices, ys, method=method, metric=metric)
    shift = y if metric == "relative" else np.log1p(y / 252) * 252
    np.testing.assert_allclose((exp - prem).to_numpy(), shift, atol=1e-12)


def test_excess_returns_alignment_hand_case():
    idx = pd.bdate_range("2024-01-01", periods=4)
    prices = pd.DataFrame({"A": [100.0, 101, 102.01, 102.01]}, index=idx)
    # yields known only from the 2nd day on, and on the 4th (ffill + bfill)
    ys = pd.Series([0.0252, 0.0504], index=[idx[1], idx[3]])
    ex = stats.excess_returns(prices, ys)
    raw = stats.asset_returns(prices)
    exp = [0.01 - 0.0252 / 252, 0.01 - 0.0252 / 252, 0.0 - 0.0504 / 252]
    np.testing.assert_allclose(ex["A"].to_numpy(), exp, atol=1e-15)
    assert len(ex) == len(raw)


def test_synthetic_cash_fund_has_zero_premium():
    idx = _dates()
    # yields rise 0 -> 5%, concave (fast early): median sits above the mean
    t = np.linspace(0, 1, N + 1)
    ys = pd.Series(0.05 * (1 - (1 - t) ** 4), index=idx)
    rng = np.random.default_rng(1)
    daily = ys.to_numpy()[1:] / 252 + rng.normal(0, 1e-6, N)
    cash = 100 * np.concatenate([[1.0], np.cumprod(1 + daily)])
    prices = pd.DataFrame({"CASH": cash}, index=idx)
    raw_med = stats.expected_annual(prices, method="robust")["CASH"]
    raw_mean = stats.expected_annual(prices, method="normal")["CASH"]
    assert raw_med > raw_mean + 0.005          # median of a trending yield is biased up
    for method in ("robust", "normal"):
        prem = stats.premium_annual(prices, ys, method=method)["CASH"]
        assert abs(prem) < 5e-4, (method, prem)


def test_constant_correlation_lw_properties(prices):
    sig = stats.risk_matrix_annual(prices, method="normal")
    rets = stats.asset_returns(prices)
    sample = rets.cov() * 252
    np.testing.assert_allclose(np.diag(sig), np.diag(sample), atol=1e-12)
    # off-diagonals lie between the sample covariance and the target's
    sd = np.sqrt(np.diag(sample))
    corr = sample.to_numpy() / np.outer(sd, sd)
    n = len(sd)
    rbar = (corr.sum() - n) / (n * (n - 1))
    target = rbar * np.outer(sd, sd)
    lo = np.minimum(sample.to_numpy(), target) - 1e-12
    hi = np.maximum(sample.to_numpy(), target) + 1e-12
    off = ~np.eye(n, dtype=bool)
    assert ((sig.to_numpy() >= lo) & (sig.to_numpy() <= hi))[off].all()


# ----------------------------------------------------------------------
# model: AssetSet in premium mode == the engine
# ----------------------------------------------------------------------
from condor import AssetSet, compute_analysis  # noqa: E402


@pytest.fixture
def hist(prices):
    t = np.linspace(0, 1, len(prices))
    return pd.Series(0.01 + 0.04 * t, index=prices.index)


@pytest.mark.parametrize("method", ["robust", "normal"])
def test_expected_returns_equal_engine(prices, hist, method):
    a = AssetSet(prices, method, rf_history=hist, rf_level=0.045)
    prem = stats.premium_annual(prices, hist, method=method)
    pd.testing.assert_series_equal(a.expected_returns, 0.045 + prem)
    pd.testing.assert_series_equal(a.premiums, prem)
    assert a.premium_mode and a.rf_level == 0.045
    assert a.tbill_window_mean == pytest.approx(hist.mean())
    assert list(a.summary().columns) == ["expected_return", "dispersion", "premium"]
    # sigma stays raw
    pd.testing.assert_frame_equal(
        a.risk_matrix, AssetSet(prices, method).risk_matrix)


def test_rf_level_defaults_to_last_and_off_mode_is_plain(prices, hist):
    a = AssetSet(prices, rf_history=hist)
    assert a.rf_level == hist.iloc[-1]
    b = AssetSet(prices)
    assert not b.premium_mode and b.premiums is None and b.tbill_window_mean is None
    assert list(b.summary().columns) == ["expected_return", "dispersion"]
    pd.testing.assert_series_equal(
        b.expected_returns, stats.expected_annual(prices, method="normal"))


def test_with_options_carries_history_and_relevels(prices, hist):
    a = AssetSet(prices, "robust", rf_history=hist, rf_level=0.03)
    assert a.with_method("normal").premium_mode
    assert a.with_method("normal").rf_level == 0.03
    r = a.with_options(rf_level=0.05)
    assert r.rf_level == 0.05 and a.with_options() is a
    np.testing.assert_allclose((r.mu - a.mu).to_numpy(), 0.02, atol=1e-12)


def test_analysis_relevels_to_the_sharpe_rate(prices, hist):
    a = AssetSet(prices, "robust", rf_history=hist, rf_level=0.03)
    out = a.analysis(risk_free_rate=0.05, n_points=8)
    expected = a.with_options(rf_level=0.05).analysis(risk_free_rate=0.05, n_points=8)
    assert out == expected
    asset_ret = {p["ticker"]: p["ret"] for p in out["assets"]}
    for t, v in asset_ret.items():
        assert v == pytest.approx(0.05 + stats.premium_annual(
            prices, hist, method="robust")[t])
    assert out["meta"]["premium"] is True and out["meta"]["risk_free_rate"] == 0.05
    assert out["meta"]["window"]["n_days"] == len(prices)


def test_off_mode_payload_unchanged_apart_from_meta(prices):
    out = AssetSet(prices, "robust").analysis(risk_free_rate=0.03, n_points=6)
    assert out["meta"] == {
        "window": {"start": str(prices.index[0].date()),
                   "end": str(prices.index[-1].date()), "n_days": len(prices)},
        "method": "robust", "premium": False, "risk_free_rate": 0.03,
        "tbill_window_mean": None}
    legacy = {k: v for k, v in out.items() if k != "meta"}
    assert legacy["assets"] == [
        {"ticker": t, "ret": float(v), "vol": float(np.sqrt(
            AssetSet(prices, "robust").risk_matrix.loc[t, t]))}
        for t, v in stats.expected_annual(prices, method="robust").items()]


def test_compute_analysis_passes_history_through(prices, hist):
    via_fn = compute_analysis(prices, risk_free_rate=0.04, method="robust",
                              n_points=6, rf_history=hist, rf_level=0.04)
    via_obj = AssetSet(prices, "robust", rf_history=hist, rf_level=0.04
                       ).analysis(risk_free_rate=0.04, n_points=6)
    assert via_fn == via_obj


def test_from_members_passes_history(prices, hist):
    a = AssetSet.from_members([prices], "robust", rf_history=hist, rf_level=0.04)
    assert a.premium_mode and a.rf_level == 0.04


def test_tangency_cash_fund_bug_and_fix():
    """One risky asset + a cash fund that earns each day's T-bill.
    Raw mode at today's rate puts most weight on cash (the bug); premium
    mode puts ~0 on it."""
    idx = _dates()
    t = np.linspace(0, 1, N + 1)
    ys = pd.Series(0.05 * (1 - (1 - t) ** 4), index=idx)
    rng = np.random.default_rng(5)
    cash = 100 * np.concatenate([[1.0], np.cumprod(
        1 + ys.to_numpy()[1:] / 252 + rng.normal(0, 2e-5, N))])
    risky = 100 * np.concatenate([[1.0], np.cumprod(
        1 + rng.normal(0.0004, 0.01, N))])
    prices = pd.DataFrame({"CASH": cash, "RISKY": risky}, index=idx)
    today = 0.04   # below the cash fund's median 4.46%: the raw "premium" is fake
    raw = AssetSet(prices, "robust").tangency(today)
    prem = AssetSet(prices, "robust", rf_history=ys, rf_level=today).tangency(today)
    assert raw.weights["CASH"] > 0.5
    assert prem is None or prem.weights.get("CASH", 0.0) < 0.05
