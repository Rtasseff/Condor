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
from condor.forecast import (ANCHOR_PRIOR_SD, DEFAULT_LEVELS, MARKET_ANCHOR,
                             anchored_log_drift, anchored_moments, band_floor,
                             blend_with_cash, bootstrap_bands, horizon_grid,
                             log_moments, lognormal_bands, mu_standard_error)

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
        assert set(d) == {"model", "anchor", "block", "n_paths", "guarded",
                          "horizon_years", "cash_weight",
                          "risk_free_rate", "t", "median", "bands",
                          "bands_est", "mu_annual", "mu_se_annual", "mu_ci95",
                          "sigma_annual", "n_obs", "span_years"}
        assert set(d["anchor"]) == {"mode", "value", "prior_sd", "effective",
                                    "prior_sd_effective", "mu_historical",
                                    "mu_se_historical"}
        assert d["anchor"]["mode"] == "historical"
        assert d["anchor"]["value"] is None
        assert d["block"] is None and d["n_paths"] is None   # steady model
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

    def test_blend_with_cash_closed_form(self):
        rng = np.random.default_rng(5)
        r = pd.Series(0.0005 + 0.01 * rng.standard_normal(500))
        rf = 0.04
        rf_daily = (1 + rf) ** (1 / 252) - 1
        half = blend_with_cash(r, 0.5, rf, 252)
        pd.testing.assert_series_equal(half, 0.5 * r + 0.5 * rf_daily)
        pd.testing.assert_series_equal(blend_with_cash(r, 0.0, rf, 252), r)
        # pure cash: deterministic, zero dispersion
        m, s, n = log_moments(blend_with_cash(r, 1.0, rf, 252))
        assert s == pytest.approx(0.0, abs=1e-15)
        assert (1 + rf) ** (1 / 252) == pytest.approx(np.exp(m))
        with pytest.raises(ValueError):
            blend_with_cash(r, 1.2, rf, 252)

    def test_complete_portfolio_forecast(self, prices):
        """cash_weight=1 grows exactly at rf with zero-width bands;
        a 50% blend halves the dispersion and keeps band nesting."""
        p = AssetSet(prices).portfolio()
        rf = 0.04
        allcash = p.forecast(horizon_years=2, cash_weight=1.0,
                             risk_free_rate=rf)
        t = allcash.table
        assert t["median"].iloc[-1] == pytest.approx((1 + rf) ** 2, rel=1e-9)
        assert t["lo95"].iloc[-1] == pytest.approx(t["hi95"].iloc[-1], rel=1e-12)
        assert allcash.sigma_annual == pytest.approx(0.0, abs=1e-12)
        assert allcash.mu_annual == pytest.approx(rf, rel=1e-9)

        risky = p.forecast(horizon_years=2)
        half = p.forecast(horizon_years=2, cash_weight=0.5,
                          risk_free_rate=rf)
        assert half.sigma_annual == pytest.approx(risky.sigma_annual / 2,
                                                  rel=1e-3)
        d = half.to_dict()
        assert d["cash_weight"] == 0.5 and d["risk_free_rate"] == rf
        with pytest.raises(ValueError):
            p.forecast(cash_weight=1.5)

    def test_horizon_validation(self, prices):
        p = AssetSet(prices).portfolio()
        for bad in (0, -1, 51):
            with pytest.raises(ValueError):
                p.forecast(horizon_years=bad)


# ----------------------------------------------------------------------
# rung B: block bootstrap
# ----------------------------------------------------------------------
class TestBootstrap:
    @pytest.fixture(scope="class")
    def iid(self):
        rng = np.random.default_rng(3)
        return pd.Series(np.expm1(M + S * rng.standard_normal(2520)))

    def test_matches_closed_form_on_iid_data(self, iid):
        """Cross-method regression check from the research: on i.i.d.
        data the bootstrap must recover the lognormal bands within
        Monte-Carlo tolerance."""
        m, s, n = log_moments(iid)
        closed = lognormal_bands(m, s, n, 504, PPY, step=5)
        boot = bootstrap_bands(iid, 504, PPY, step=5, block=21,
                               n_paths=8000, seed=1)
        assert boot.index.equals(closed.index)
        assert list(boot.columns) == list(closed.columns)
        last_b, last_c = boot.iloc[-1], closed.iloc[-1]
        assert last_b["median"] == pytest.approx(last_c["median"], rel=0.02)
        for tag in ("65", "95", "95_est"):
            wb = np.log(last_b[f"hi{tag}"]) - np.log(last_b[f"lo{tag}"])
            wc = np.log(last_c[f"hi{tag}"]) - np.log(last_c[f"lo{tag}"])
            assert wb == pytest.approx(wc, rel=0.08)

    def test_deterministic_per_seed(self, iid):
        a = bootstrap_bands(iid, 126, PPY, n_paths=1000, seed=42)
        b = bootstrap_bands(iid, 126, PPY, n_paths=1000, seed=42)
        c = bootstrap_bands(iid, 126, PPY, n_paths=1000, seed=43)
        pd.testing.assert_frame_equal(a, b)
        assert not a.equals(c)

    def test_row_zero_is_today(self, iid):
        boot = bootstrap_bands(iid, 126, PPY, n_paths=500, seed=0)
        assert set(boot.iloc[0]) == {1.0}

    def test_validation(self, iid):
        with pytest.raises(ValueError):
            bootstrap_bands(iid, 126, PPY, block=0)
        with pytest.raises(ValueError):
            bootstrap_bands(iid, 126, PPY, n_paths=10)
        with pytest.raises(ValueError):
            bootstrap_bands(pd.Series([0.01]), 126, PPY)

    def test_band_floor_envelope_and_material_flag(self, iid):
        m, s, n = log_moments(iid)
        closed = lognormal_bands(m, s, n, 504, PPY, step=5)
        # an artificially narrowed table must be floored and flagged
        narrow = closed.copy()
        for col in narrow.columns:
            if col.startswith("lo"):
                narrow[col] = closed[col.replace("lo", "hi")] * 0.99
            elif col.startswith("hi"):
                narrow[col] = narrow[col]
        floored, flagged = band_floor(narrow, closed)
        assert flagged
        for col in closed.columns:
            if col.startswith("lo"):
                assert (floored[col] <= closed[col] + 1e-12).all()
            elif col.startswith("hi"):
                assert (floored[col] >= closed[col] - 1e-12).all()
        # a table identical to the floor is not flagged
        same, flagged2 = band_floor(closed.copy(), closed)
        assert not flagged2
        with pytest.raises(ValueError):
            band_floor(closed.iloc[:-1], closed)

    def test_mean_reverting_sample_triggers_the_guard(self, prices):
        """The research trap made executable: strictly alternating
        returns have almost no long-horizon variance, so an unguarded
        block bootstrap would report absurdly narrow bands. The model
        must floor them at the closed form and say so."""
        alt = pd.DataFrame(
            {"AAA": 100 * np.cumprod(1 + np.tile([0.02, -0.02], 630))},
            index=pd.bdate_range("2021-01-01", periods=1260))
        fc = AssetSet(alt).portfolio().forecast(2, model="bootstrap",
                                                n_paths=2000, seed=0)
        assert fc.guarded
        m, s, n = log_moments(AssetSet(alt).portfolio().returns)
        closed = lognormal_bands(m, s, n, 504, 252, step=5)
        assert (fc.table["lo95"] <= closed["lo95"] + 1e-12).all()
        assert (fc.table["hi95"] >= closed["hi95"] - 1e-12).all()

    def test_model_pins_to_engine(self, prices):
        p = AssetSet(prices).portfolio({"AAA": 0.7, "BBB": 0.3})
        fc = p.forecast(2, model="bootstrap", block=21, n_paths=2000, seed=5)
        m, s, n = log_moments(p.returns)
        closed = lognormal_bands(m, s, n, 504, 252, step=5)
        boot = bootstrap_bands(p.returns, 504, 252, step=5, block=21,
                               n_paths=2000, seed=5)
        expected, guarded = band_floor(boot, closed)
        pd.testing.assert_frame_equal(fc.table, expected)
        assert fc.guarded == guarded
        d = fc.to_dict()
        assert d["model"] == "block-bootstrap"
        assert d["block"] == 21 and d["n_paths"] == 2000
        assert isinstance(d["guarded"], bool)

    def test_all_cash_bootstrap_is_exact(self, prices):
        """cw=1 makes every resampled path identical: zero width, rf
        growth — and it can never be flagged narrower than closed."""
        fc = AssetSet(prices).portfolio().forecast(
            2, model="bootstrap", cash_weight=1.0, risk_free_rate=0.04,
            n_paths=500, seed=0)
        t = fc.table
        assert t["median"].iloc[-1] == pytest.approx(1.04 ** 2, rel=1e-6)
        assert t["lo95"].iloc[-1] == pytest.approx(t["hi95"].iloc[-1], rel=1e-9)
        assert not fc.guarded

    def test_unknown_model_rejected(self, prices):
        with pytest.raises(ValueError):
            AssetSet(prices).portfolio().forecast(2, model="oracle")


# ----------------------------------------------------------------------
# rung C: an anchor on the expected return
# ----------------------------------------------------------------------
class TestAnchorEngine:
    def test_hand_computed_posterior(self):
        """Conjugate normal, worked by hand: precisions add, and the
        posterior mean is the precision-weighted average."""
        mu_hat, se, a, tau = 0.14, 0.056, 0.077, 0.03
        w_d, w_p = 1 / 0.056 ** 2, 1 / 0.03 ** 2
        mean = (0.14 * w_d + 0.077 * w_p) / (w_d + w_p)
        sd = np.sqrt(1 / (w_d + w_p))
        got_mean, got_sd = anchored_moments(mu_hat, se, a, tau)
        assert got_mean == pytest.approx(mean, abs=1e-12)
        assert got_sd == pytest.approx(sd, abs=1e-12)
        # the research doc's worked example: ~9.5%/yr, ~2.6 pp, from a
        # 14.3% sample mean with a 5.7 pp SE and an 8% +/- 3 pp prior
        m2, sd2 = anchored_moments(np.log1p(0.1426), 0.057, np.log1p(0.08), 0.03)
        assert np.expm1(m2) == pytest.approx(0.095, abs=0.005)
        assert sd2 == pytest.approx(0.026, abs=0.002)

    def test_diffuse_prior_is_the_identity(self):
        """tau -> inf is "no prior at all": historical mu-hat and SE back,
        exactly (not approximately)."""
        for tau in (np.inf, float("inf")):
            mean, sd = anchored_moments(0.14, 0.056, 0.077, tau)
            assert mean == 0.14 and sd == 0.056
        # and a merely huge tau converges to it
        mean, sd = anchored_moments(0.14, 0.056, 0.077, 1e6)
        assert mean == pytest.approx(0.14, abs=1e-12)
        assert sd == pytest.approx(0.056, abs=1e-12)

    def test_certain_prior_is_the_anchor(self):
        mean, sd = anchored_moments(0.14, 0.056, 0.077, 0.0)
        assert mean == 0.077 and sd == 0.0

    def test_posterior_is_sharper_than_either_input(self):
        rng = np.random.default_rng(0)
        for mu_hat, se, a, tau in rng.uniform(0.01, 0.3, size=(50, 4)):
            mean, sd = anchored_moments(mu_hat, se, a, tau)
            assert sd < min(se, tau)
            assert min(mu_hat, a) <= mean <= max(mu_hat, a)

    def test_exact_data_beats_any_prior(self):
        """se = 0 is an all-cash mix: its rate is known, so no anchor can
        improve on it (and this keeps cash forecasts exact)."""
        assert anchored_moments(0.04, 0.0, 0.08, 0.03) == (0.04, 0.0)
        assert anchored_moments(0.04, 0.0, 0.08, 0.0) == (0.04, 0.0)

    def test_rejects_negative_widths(self):
        with pytest.raises(ValueError):
            anchored_moments(0.1, -0.01, 0.08, 0.03)
        with pytest.raises(ValueError):
            anchored_moments(0.1, 0.05, 0.08, -0.03)

    def test_log_drift_adapter_pins_to_the_blend(self):
        """The units wrapper: annual simple anchor -> log via log1p, and
        the result comes back per period."""
        post_m, post_sd = anchored_log_drift(M, S, N, PPY, 0.08, 0.03)
        se = mu_standard_error(S, N, PPY)
        mean, sd = anchored_moments(M * PPY, se, np.log1p(0.08), 0.03)
        assert post_m == pytest.approx(mean / PPY, abs=1e-15)
        assert post_sd == pytest.approx(sd / PPY, abs=1e-15)
        # a diffuse prior leaves the sample drift and its SE untouched
        d_m, d_sd = anchored_log_drift(M, S, N, PPY, 0.08, np.inf)
        assert d_m == M and d_sd * PPY == se

    def test_drift_sd_drives_the_est_bands_only(self):
        """Passing drift_sd replaces s/sqrt(n); zero uncertainty in the
        drift collapses the est bands onto the path-only bands."""
        base = lognormal_bands(M, S, N, 504, PPY, step=5)
        same = lognormal_bands(M, S, N, 504, PPY, step=5,
                               drift_sd=S / np.sqrt(N))
        for tag in ("65", "95"):
            np.testing.assert_allclose(same[f"hi{tag}_est"],
                                       base[f"hi{tag}_est"], rtol=1e-12)
        exact = lognormal_bands(M, S, N, 504, PPY, step=5, drift_sd=0.0)
        for tag in ("65", "95"):
            np.testing.assert_allclose(exact[f"lo{tag}_est"], exact[f"lo{tag}"],
                                       rtol=1e-12)
        # tighter drift knowledge => tighter est bands, path-only untouched
        tight = lognormal_bands(M, S, N, 504, PPY, step=5,
                                drift_sd=S / np.sqrt(N) / 2)
        assert tight["hi95_est"].iloc[-1] < base["hi95_est"].iloc[-1]
        np.testing.assert_allclose(tight["hi95"], base["hi95"], rtol=1e-12)
        with pytest.raises(ValueError):
            lognormal_bands(M, S, N, 504, PPY, drift_sd=-0.1)

    def test_bootstrap_drift_shift_is_exactly_multiplicative(self):
        """Recentring adds a constant log drift to every path, so every
        band moves by exp(shift*h) and the shape of the resample — its
        streaks, its skew — is untouched."""
        rng = np.random.default_rng(3)
        iid = pd.Series(np.expm1(M + S * rng.standard_normal(2520)))
        shift = 0.0002
        base = bootstrap_bands(iid, 252, PPY, n_paths=1000, seed=7)
        moved = bootstrap_bands(iid, 252, PPY, n_paths=1000, seed=7,
                                drift_shift=shift)
        h = base.index.values * PPY
        for col in base.columns:
            np.testing.assert_allclose(moved[col], base[col] * np.exp(shift * h),
                                       rtol=1e-12)
        # zero shift and default sd are the untouched rung-B path
        pd.testing.assert_frame_equal(
            bootstrap_bands(iid, 252, PPY, n_paths=1000, seed=7,
                            drift_shift=0.0, drift_sd=None), base)
        # a certain drift collapses the est bands onto the path-only ones
        exact = bootstrap_bands(iid, 252, PPY, n_paths=1000, seed=7,
                                drift_sd=0.0)
        np.testing.assert_allclose(exact["hi95_est"], exact["hi95"], rtol=1e-12)
        with pytest.raises(ValueError):
            bootstrap_bands(iid, 252, PPY, n_paths=1000, drift_sd=-1.0)


class TestAnchorModel:
    def test_historical_is_bit_identical(self, prices):
        """The default must be a no-op: same table, same payload, for
        both models. Anything else is a behaviour change nobody asked
        for."""
        p = AssetSet(prices).portfolio({"AAA": 0.6, "BBB": 0.4})
        for kw in ({}, {"model": "bootstrap", "n_paths": 500, "seed": 2}):
            base = p.forecast(2, **kw)
            same = p.forecast(2, anchor="historical", **kw)
            assert base.table.equals(same.table)
            assert base.to_dict() == same.to_dict()
            assert same.drift_sd is None and same.anchor_value is None
            assert same.mu_annual == same.mu_historical

    def test_steady_anchored_equals_engine(self, prices):
        p = AssetSet(prices).portfolio({"AAA": 0.6, "BBB": 0.4})
        fc = p.forecast(2, anchor="market")
        m, s, n = log_moments(p.returns)
        post_m, post_sd = anchored_log_drift(m, s, n, 252, MARKET_ANCHOR,
                                             ANCHOR_PRIOR_SD)
        expected = lognormal_bands(post_m, s, n, 504, 252,
                                   levels=DEFAULT_LEVELS, step=5,
                                   drift_sd=post_sd)
        pd.testing.assert_frame_equal(fc.table, expected)
        assert fc.mu_annual == pytest.approx(np.exp(post_m * 252) - 1)
        assert fc.mu_se_annual == pytest.approx(post_sd * 252)
        assert fc.mu_historical == pytest.approx(np.exp(m * 252) - 1)
        assert fc.mu_se_historical == mu_standard_error(s, n, 252)

    def test_anchor_pulls_the_centre_and_sharpens_the_estimate(self, prices):
        """The educational point, made numerically: an 8% anchor on a
        15%/yr sample pulls the median down and narrows the estimate-error
        band, while market randomness (the inner band) is untouched."""
        p = AssetSet(prices).portfolio()
        hist, mkt = p.forecast(2), p.forecast(2, anchor="market")
        assert hist.mu_annual > mkt.mu_annual > MARKET_ANCHOR
        assert mkt.mu_se_annual < hist.mu_se_annual
        assert mkt.table["median"].iloc[-1] < hist.table["median"].iloc[-1]
        width = lambda t, c: np.log(t["hi95" + c]).iloc[-1] - np.log(t["lo95" + c]).iloc[-1]
        assert width(mkt.table, "") == pytest.approx(width(hist.table, ""),
                                                     rel=1e-12)
        assert width(mkt.table, "_est") < width(hist.table, "_est")
        # a custom anchor above the sample mean pushes the centre up
        high = p.forecast(2, anchor="custom", anchor_value=0.25)
        assert high.mu_annual > hist.mu_annual
        assert high.anchor_value == 0.25

    def test_bootstrap_anchored_equals_engine_and_floors_under_the_anchor(
            self, prices):
        p = AssetSet(prices).portfolio({"AAA": 0.7, "BBB": 0.3})
        fc = p.forecast(2, model="bootstrap", block=21, n_paths=2000, seed=5,
                        anchor="custom", anchor_value=0.05)
        m, s, n = log_moments(p.returns)
        post_m, post_sd = anchored_log_drift(m, s, n, 252, 0.05,
                                             ANCHOR_PRIOR_SD)
        closed = lognormal_bands(post_m, s, n, 504, 252, step=5,
                                 drift_sd=post_sd)
        boot = bootstrap_bands(p.returns, 504, 252, step=5, block=21,
                               n_paths=2000, seed=5, drift_shift=post_m - m,
                               drift_sd=post_sd)
        expected, guarded = band_floor(boot, closed)
        pd.testing.assert_frame_equal(fc.table, expected)
        assert fc.guarded == guarded
        # the floor is the anchored closed form, not the historical one:
        # its median sits at the anchored centre
        assert closed["median"].iloc[-1] == pytest.approx(
            np.exp(post_m * 504), rel=1e-12)

    def test_anchor_applies_to_the_risky_sleeve_of_a_complete_portfolio(
            self, prices):
        """A market anchor is a claim about the market, not about T-bills:
        on a half-cash account it enters as 0.5*8% + 0.5*rf, held half as
        firmly."""
        p = AssetSet(prices).portfolio()
        rf = 0.04
        fc = p.forecast(2, cash_weight=0.5, risk_free_rate=rf, anchor="market")
        assert fc.anchor_value == MARKET_ANCHOR
        assert fc.anchor_effective == pytest.approx(0.5 * MARKET_ANCHOR
                                                    + 0.5 * rf)
        m, s, n = log_moments(blend_with_cash(p.returns, 0.5, rf, 252))
        post_m, post_sd = anchored_log_drift(m, s, n, 252, fc.anchor_effective,
                                             0.5 * ANCHOR_PRIOR_SD)
        assert fc.m == post_m and fc.drift_sd == post_sd
        d = fc.to_dict()["anchor"]
        assert d["value"] == MARKET_ANCHOR and d["effective"] == 0.06
        # the prior's *width* is scaled with the sleeve too, and the payload
        # says so — the UI must quote the width actually used, not the 3 pp
        assert d["prior_sd"] == ANCHOR_PRIOR_SD
        assert d["prior_sd_effective"] == pytest.approx(0.5 * ANCHOR_PRIOR_SD)

    def test_all_cash_anchored_stays_exact(self, prices):
        """No anchor can move a rate that is already known."""
        p = AssetSet(prices).portfolio()
        fc = p.forecast(2, cash_weight=1.0, risk_free_rate=0.04,
                        anchor="market")
        assert fc.mu_annual == pytest.approx(0.04, rel=1e-9)
        assert fc.mu_se_annual == 0.0
        assert fc.table["lo95"].iloc[-1] == pytest.approx(
            fc.table["hi95"].iloc[-1], rel=1e-12)

    def test_payload_reports_what_was_assumed(self, prices):
        d = AssetSet(prices).portfolio().forecast(2, anchor="market").to_dict()
        a = d["anchor"]
        assert a["mode"] == "market"
        assert a["value"] == MARKET_ANCHOR and a["prior_sd"] == ANCHOR_PRIOR_SD
        assert a["effective"] == MARKET_ANCHOR      # no cash sleeve
        assert a["prior_sd_effective"] == ANCHOR_PRIOR_SD
        assert a["mu_historical"] > d["mu_annual"] > 0
        assert d["mu_se_annual"] < a["mu_se_historical"]

    def test_validation(self, prices):
        p = AssetSet(prices).portfolio()
        with pytest.raises(ValueError):
            p.forecast(2, anchor="vibes")
        with pytest.raises(ValueError):
            p.forecast(2, anchor="custom")               # needs a value
        for bad in (-0.5, 0.9):
            with pytest.raises(ValueError):
                p.forecast(2, anchor="custom", anchor_value=bad)
