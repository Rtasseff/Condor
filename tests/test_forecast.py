"""Forecast engine (condor/forecast.py) verification, and model pin.

House rule: every engine function gets a closed-form / hand-case test.
Here the engine IS a closed form, so it is pinned directly against
scipy's lognormal quantiles and against the √(1 + T/N) band-inflation
identity from the research pass (Merton estimation error). The model
tests then pin Forecast/Portfolio.forecast to the engine, number for
number.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import lognorm, norm

from condor import AssetSet, Forecast
from condor.forecast import (DEFAULT_LEVELS, horizon_grid, log_moments,
                             lognormal_bands, mu_standard_error)

M, S, N = 0.0004, 0.011, 2520  # per-day log drift/dispersion, 10y of obs
PPY = 252


# ----------------------------------------------------------------------
# engine
# ----------------------------------------------------------------------
class TestEngine:
    def test_moments_hand_case(self):
        r = pd.Series([0.01, -0.02, 0.03, 0.0, None])
        lr = np.log1p([0.01, -0.02, 0.03, 0.0])
        m, s, n = log_moments(r)
        assert n == 4
        assert m == pytest.approx(lr.mean())
        assert s == pytest.approx(lr.std(ddof=1))
        with pytest.raises(ValueError):
            log_moments([0.01])

    def test_mu_se_is_merton_span_only(self):
        # SE of the annualized drift == sigma_annual / sqrt(span years),
        # however finely the same 10 years are sampled
        daily = mu_standard_error(S, N, PPY)
        assert daily == pytest.approx((S * np.sqrt(PPY)) / np.sqrt(N / PPY))
        monthly = mu_standard_error(S * np.sqrt(21), N // 21, 12)
        assert monthly == pytest.approx(daily, rel=1e-9)

    def test_grid_keeps_endpoint(self):
        h = horizon_grid(504, 5)
        assert h[0] == 0 and h[-1] == 504 and np.all(np.diff(h) > 0)
        assert horizon_grid(3, 5).tolist() == [0, 3]
        with pytest.raises(ValueError):
            horizon_grid(0, 5)

    def test_bands_are_scipy_lognormal_quantiles(self):
        t = lognormal_bands(M, S, N, 504, PPY, step=5)
        for h_years, row in t.iterrows():
            h = h_years * PPY
            if h == 0:
                assert set(row) == {1.0}
                continue
            dist = lognorm(s=S * np.sqrt(h), scale=np.exp(M * h))
            assert row["lo95"] == pytest.approx(dist.ppf(0.025), rel=1e-9)
            assert row["hi95"] == pytest.approx(dist.ppf(0.975), rel=1e-9)
            assert row["lo65"] == pytest.approx(dist.ppf(0.175), rel=1e-9)
            assert row["hi65"] == pytest.approx(dist.ppf(0.825), rel=1e-9)
            assert row["median"] == pytest.approx(np.exp(M * h), rel=1e-9)

    def test_estimate_error_inflates_by_sqrt_1_plus_T_over_N(self):
        t = lognormal_bands(M, S, N, 504, PPY, step=5)
        T, span = 2.0, N / PPY                       # 2y horizon, 10y window
        row = t.loc[t.index[-1]]
        width = np.log(row["hi95"]) - np.log(row["lo95"])
        width_est = np.log(row["hi95_est"]) - np.log(row["lo95_est"])
        assert width_est / width == pytest.approx(np.sqrt(1 + T / span), rel=1e-9)
        # and the est band strictly contains the path-only band
        assert (t["lo95_est"] <= t["lo95"]).all()
        assert (t["hi95_est"] >= t["hi95"]).all()

    def test_band_nesting_and_monotonicity(self):
        t = lognormal_bands(M, S, N, 504, PPY)
        assert (t["lo95"] <= t["lo65"]).all() and (t["hi65"] <= t["hi95"]).all()
        assert (t["lo65"] <= t["median"]).all() and (t["median"] <= t["hi65"]).all()
        assert t["median"].is_monotonic_increasing          # M > 0
        assert t.index[0] == 0 and t.index[-1] == pytest.approx(2.0)

    def test_input_validation(self):
        with pytest.raises(ValueError):
            lognormal_bands(M, S, 1, 504, PPY)
        with pytest.raises(ValueError):
            lognormal_bands(M, S, N, 504, PPY, levels=(1.5,))


# ----------------------------------------------------------------------
# model pin
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def prices():
    rng = np.random.default_rng(11)
    n, mu, sig = 2520, 0.0005, 0.012
    rets = mu + sig * rng.standard_normal((n, 2)) @ np.array(
        [[1.0, 0.3], [0.0, 0.9]])
    idx = pd.bdate_range("2016-01-01", periods=n)
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx,
                        columns=["AAA", "BBB"])


class TestModel:
    def test_forecast_equals_engine(self, prices):
        p = AssetSet(prices).portfolio({"AAA": 0.6, "BBB": 0.4})
        fc = p.forecast(horizon_years=2)
        m, s, n = log_moments(p.returns)
        expected = lognormal_bands(m, s, n, 504, 252,
                                   levels=DEFAULT_LEVELS, step=5)
        pd.testing.assert_frame_equal(fc.table, expected)
        assert fc.mu_se_annual == mu_standard_error(s, n, 252)
        assert fc.mu_annual == pytest.approx(np.exp(m * 252) - 1)
        assert fc.sigma_annual == pytest.approx(s * np.sqrt(252))
        assert fc.span_years == pytest.approx(n / 252)
        lo, hi = fc.mu_ci95
        assert lo < fc.mu_annual < hi

    def test_to_dict_shape(self, prices):
        fc = AssetSet(prices).portfolio().forecast(horizon_years=1)
        d = fc.to_dict()
        assert set(d) == {"model", "horizon_years", "t", "median", "bands",
                          "bands_est", "mu_annual", "mu_se_annual", "mu_ci95",
                          "sigma_annual", "n_obs", "span_years"}
        assert d["model"] == "constant-rate"
        assert d["t"][0] == 0 and d["median"][0] == 1
        assert [b["level"] for b in d["bands"]] == [65, 95]
        for b, be in zip(d["bands"], d["bands_est"]):
            assert len(b["lo"]) == len(d["t"]) == len(be["hi"])
        # est 95 is the outermost thing in the payload at the horizon
        assert d["bands_est"][1]["lo"][-1] <= d["bands"][1]["lo"][-1]

    def test_monthly_timeframe_uses_its_own_clock(self, prices):
        aset = AssetSet(prices, timeframe="M")
        fc = aset.portfolio().forecast(horizon_years=2)
        assert fc.periods_per_year == 12
        assert fc.table.index[-1] == pytest.approx(2.0)
        m, s, n = log_moments(aset.portfolio().returns)
        assert fc.mu_se_annual == mu_standard_error(s, n, 12)

    def test_horizon_validation(self, prices):
        p = AssetSet(prices).portfolio()
        for bad in (0, -1, 51):
            with pytest.raises(ValueError):
                p.forecast(horizon_years=bad)
