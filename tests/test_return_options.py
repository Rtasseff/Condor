"""Return-calculation options: metric, timeframe, samp_int, basis.

Same three-tier shape as the rest of the suite:

  Tier 1  the engine vs the legacy Condor functions on identical inputs
          (genFin.returns / returnExp / returnCoDispSq + the sampling from
          CondorCoreObs.TimeCourse._sample), with and without NaNs.
  Tier 2  sanity / self-consistency (annualization factors, de-overlapped
          row counts, geometric < arithmetic, log != relative) and the
          "defaults are unchanged" pin that guards every other test in the
          suite.
  Tier 3  the object layer equals the engine, option for option.

Legacy semantics being replicated (context/legacy/analytics):

  Returns(prices, timeFrame, metric, sampInt)   CondorCoreObs.py
      timeFrame 'D' -> period 1, 'M' -> period 21
      values = genFin.returns(prices, period, metric)
      dates  = prices.times[period:]            (window END)
      estimates run on values[np.arange(0, n, sampInt)]
  annualizeBy = timeFrame                       genFin.annualize
      'D' -> x252, 'M' -> x12                   (never a function of sampInt)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pypfopt import expected_returns as pfopt_returns
from pypfopt import risk_models as pfopt_risk

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "context" / "legacy" / "analytics"))

from functions import genFin, genStats  # noqa: E402  (legacy)

from condor import AssetSet, compute_analysis, stats  # noqa: E402

TICKERS = ["AAA", "BBB", "CCC"]
TOL = 1e-14  # legacy (xi-x0)/x0 vs pandas xi/x0-1: float noise only


# ---------------------------------------------------------------- fixtures --
@pytest.fixture(scope="module")
def prices():
    """Seeded correlated price paths, ~3 years of business days."""
    rng = np.random.default_rng(11)
    n = 760
    corr = np.array([[1, .5, .2], [.5, 1, .3], [.2, .3, 1]])
    shocks = rng.standard_normal((n, 3)) @ np.linalg.cholesky(corr).T
    rets = shocks * np.array([.016, .011, .008]) + np.array([.0007, .0004, .0002])
    rets[30, 0] = 0.22    # outliers, so robust != normal
    rets[400, 1] = -0.25
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0),
                        index=pd.bdate_range("2021-01-04", periods=n),
                        columns=TICKERS)


@pytest.fixture(scope="module")
def gappy_prices(prices):
    """Prices with scattered per-asset holes (never a whole missing row)."""
    px = prices.copy()
    px.iloc[17, 0] = np.nan
    px.iloc[18, 0] = np.nan
    px.iloc[123, 1] = np.nan
    px.iloc[300, 2] = np.nan
    px.iloc[301, 0] = np.nan
    return px


def legacy_returns(px: pd.DataFrame, timeframe: str, samp_int: int,
                   metric: str = "Relative") -> np.ndarray:
    """The legacy return series: genFin.returns + TimeCourse._sample."""
    period = {"D": 1, "M": 21}[timeframe]
    r = genFin.returns(px.to_numpy(dtype=float), period=period, metric=metric)
    return r[np.arange(0, len(r), samp_int)]


# ------------------------------------------------ Tier 1: vs legacy code --
@pytest.mark.parametrize("timeframe,samp_int", [("D", 1), ("D", 5),
                                                ("M", 1), ("M", 20)])
@pytest.mark.parametrize("metric,legacy_metric", [("relative", "Relative"),
                                                  ("log", "Log")])
class TestReturnsVsLegacy:
    """asset_returns == genFin.returns(period) sampled every samp_int."""

    def test_values(self, prices, timeframe, samp_int, metric, legacy_metric):
        legacy = legacy_returns(prices, timeframe, samp_int, legacy_metric)
        v2 = stats.asset_returns(prices, metric=metric, timeframe=timeframe,
                                 samp_int=samp_int)
        assert v2.shape == legacy.shape
        np.testing.assert_allclose(v2.to_numpy(), legacy, rtol=0, atol=TOL)

    def test_values_with_nans(self, gappy_prices, timeframe, samp_int,
                              metric, legacy_metric):
        legacy = legacy_returns(gappy_prices, timeframe, samp_int, legacy_metric)
        v2 = stats.asset_returns(gappy_prices, metric=metric,
                                 timeframe=timeframe, samp_int=samp_int)
        assert v2.shape == legacy.shape
        # the holes land in the same places, and the rest agrees
        np.testing.assert_array_equal(np.isnan(v2.to_numpy()), np.isnan(legacy))
        np.testing.assert_allclose(v2.to_numpy(), legacy, rtol=0, atol=TOL,
                                   equal_nan=True)

    def test_dates_are_the_window_end(self, prices, timeframe, samp_int,
                                      metric, legacy_metric):
        period = {"D": 1, "M": 21}[timeframe]
        v2 = stats.asset_returns(prices, metric=metric, timeframe=timeframe,
                                 samp_int=samp_int)
        expected = prices.index[period:][::samp_int]  # legacy times[period:]
        pd.testing.assert_index_equal(v2.index, expected, exact=False)


@pytest.mark.parametrize("timeframe,samp_int", [("D", 1), ("M", 20)])
class TestEstimatesVsLegacy:
    """μ and Σ on the legacy series, annualized by the legacy factor."""

    @staticmethod
    def _legacy_frame(px, timeframe, samp_int):
        return pd.DataFrame(legacy_returns(px, timeframe, samp_int),
                            columns=px.columns)

    def test_robust_expected_return(self, gappy_prices, timeframe, samp_int):
        r = legacy_returns(gappy_prices, timeframe, samp_int)
        factor = {"D": 252, "M": 12}[timeframe]  # genFin.annualize
        legacy = genFin.returnExp(r, method="Robust") * factor
        v2 = stats.expected_annual(gappy_prices, method="robust",
                                   timeframe=timeframe, samp_int=samp_int)
        np.testing.assert_allclose(v2.to_numpy(), legacy, rtol=1e-12)

    def test_normal_expected_return_is_arithmetic(self, gappy_prices,
                                                  timeframe, samp_int):
        r = legacy_returns(gappy_prices, timeframe, samp_int)
        factor = {"D": 252, "M": 12}[timeframe]
        legacy = genFin.returnExp(r, method="Normal") * factor
        v2 = stats.expected_annual(gappy_prices, method="normal",
                                   timeframe=timeframe, samp_int=samp_int,
                                   basis="arithmetic")
        np.testing.assert_allclose(v2.to_numpy(), legacy, rtol=1e-12)

    def test_robust_risk_matrix_is_annualized_comad(self, gappy_prices,
                                                    timeframe, samp_int):
        r = legacy_returns(gappy_prices, timeframe, samp_int)
        factor = {"D": 252, "M": 12}[timeframe]
        legacy = pd.DataFrame(genFin.returnCoDispSq(r, method="Robust") * factor,
                              index=gappy_prices.columns,
                              columns=gappy_prices.columns)
        # v2 adds the PSD repair legacy never did; apply it to both sides
        legacy = pfopt_risk.fix_nonpositive_semidefinite(legacy, "spectral")
        v2 = stats.risk_matrix_annual(gappy_prices, method="robust",
                                      timeframe=timeframe, samp_int=samp_int)
        np.testing.assert_allclose(v2.to_numpy(), legacy.to_numpy(), atol=1e-15)

    def test_normal_risk_matrix_shrinks_the_legacy_series(self, gappy_prices,
                                                          timeframe, samp_int):
        """v2 keeps Ledoit-Wolf shrinkage (legacy used the raw covariance),
        so pin the *inputs*: the legacy series and the legacy factor."""
        rets = self._legacy_frame(gappy_prices, timeframe, samp_int)
        factor = {"D": 252, "M": 12}[timeframe]
        expected = pfopt_risk.CovarianceShrinkage(
            rets, returns_data=True, frequency=factor).ledoit_wolf()
        v2 = stats.risk_matrix_annual(gappy_prices, method="normal",
                                      timeframe=timeframe, samp_int=samp_int)
        np.testing.assert_allclose(v2.to_numpy(), expected.to_numpy(), atol=1e-15)


def test_monthly_annualization_ignores_samp_int(prices):
    """legacy annualizeBy = timeFrame, whatever the sampling interval."""
    assert stats.annual_factor("M") == 12 and stats.annual_factor("D") == 252
    coarse = stats.expected_annual(prices, timeframe="M", samp_int=20)
    fine = stats.expected_annual(prices, timeframe="M", samp_int=1)
    # different samples of the same 21-day returns -> same order of magnitude,
    # both x12 (a factor-21-vs-12 slip would show up as a ~2x gap)
    np.testing.assert_allclose(coarse.to_numpy(), fine.to_numpy(), rtol=0.5)


def test_defaults_match_the_legacy_daily_series(prices):
    """The v2 default really is legacy 'D' returns with sampInt 1."""
    np.testing.assert_allclose(stats.asset_returns(prices).to_numpy(),
                               legacy_returns(prices, "D", 1), rtol=0, atol=TOL)


# ------------------------------------------- Tier 2: defaults and sanity --
class TestDefaultsUnchanged:
    """The new options must not have moved a single existing number."""

    def test_returns_are_pct_change(self, prices):
        pd.testing.assert_frame_equal(stats.asset_returns(prices),
                                      prices.pct_change().dropna(how="all"))

    def test_expected_return_is_the_old_call(self, prices):
        for method in ("normal", "robust"):
            old = (pfopt_returns.mean_historical_return(
                       prices, frequency=252, compounding=False)
                   if method == "normal"
                   else prices.pct_change().dropna(how="all").median() * 252)
            pd.testing.assert_series_equal(
                stats.expected_annual(prices, method=method), old)

    def test_risk_matrix_is_the_old_call(self, prices):
        old_normal = pfopt_risk.CovarianceShrinkage(
            prices, frequency=252).ledoit_wolf()
        pd.testing.assert_frame_equal(stats.risk_matrix_annual(prices), old_normal)
        rets = prices.pct_change().dropna(how="all")
        old_robust = pfopt_risk.fix_nonpositive_semidefinite(
            stats._comad_matrix(rets) * 252, fix_method="spectral")
        pd.testing.assert_frame_equal(
            stats.risk_matrix_annual(prices, method="robust"), old_robust)

    def test_default_options_on_the_object(self, prices):
        aset = AssetSet(prices)
        assert (aset.metric, aset.timeframe, aset.samp_int, aset.basis) == \
            ("relative", "D", 1, "arithmetic")


class TestSanity:
    def test_log_and_relative_returns_differ(self, prices):
        rel = stats.asset_returns(prices, metric="relative")
        log = stats.asset_returns(prices, metric="log")
        assert rel.shape == log.shape
        assert not np.allclose(rel.to_numpy(), log.to_numpy())
        # ...but only in second order: log(1+r) ~ r for small r
        np.testing.assert_allclose(log.to_numpy(),
                                   np.log1p(rel.to_numpy()), atol=1e-12)

    def test_monthly_de_overlapped_row_count(self, prices):
        n = len(prices)
        full = stats.asset_returns(prices, timeframe="M", samp_int=1)
        assert len(full) == n - 21
        deoverlapped = stats.asset_returns(prices, timeframe="M")  # samp_int 20
        assert stats.default_samp_int("M") == 20
        assert len(deoverlapped) == -(-(n - 21) // 20)  # ceil((n-21)/20)
        assert len(deoverlapped) == pytest.approx(n / 20, rel=0.1)

    def test_de_overlapped_rows_are_21_trading_days_apart(self, prices):
        rows = stats.asset_returns(prices, timeframe="M")
        pos = prices.index.get_indexer(rows.index)
        assert set(np.diff(pos)) == {20}  # windows touch but never overlap

    def test_geometric_is_below_arithmetic_for_a_volatile_series(self, prices):
        arith = stats.expected_annual(prices, basis="arithmetic")
        geo = stats.expected_annual(prices, basis="geometric")
        # AM-GM: the compounded per-period return is always the smaller one,
        # by roughly half the variance ("variance drag")
        per_period_geo = (1 + geo) ** (1 / 252) - 1
        assert (per_period_geo < arith / 252).all()
        drag = arith / 252 - per_period_geo
        np.testing.assert_allclose(drag.to_numpy(),
                                   stats.asset_returns(prices).var().to_numpy() / 2,
                                   rtol=0.1)
        # these assets are volatile enough that the ordering survives
        # annualizing (it need not: exp() is convex, and at low volatility
        # the annualized geometric figure can come out above the arithmetic)
        assert (geo < arith).all()
        # geometric is exactly pypfopt's own default (CAGR)
        pd.testing.assert_series_equal(
            geo, pfopt_returns.mean_historical_return(prices, frequency=252))

    def test_basis_is_a_no_op_for_log_returns(self, prices):
        """Log returns compound additively, so CAGR == mean x factor."""
        kw = dict(metric="log", timeframe="M")
        pd.testing.assert_series_equal(
            stats.expected_annual(prices, basis="geometric", **kw),
            stats.expected_annual(prices, basis="arithmetic", **kw))

    def test_basis_does_not_touch_the_robust_median(self, prices):
        pd.testing.assert_series_equal(
            stats.expected_annual(prices, method="robust", basis="geometric"),
            stats.expected_annual(prices, method="robust", basis="arithmetic"))

    def test_bad_options_raise(self, prices):
        with pytest.raises(ValueError):
            stats.asset_returns(prices, metric="Relative")   # legacy spelling
        with pytest.raises(ValueError):
            stats.asset_returns(prices, timeframe="W")
        with pytest.raises(ValueError):
            stats.asset_returns(prices, samp_int=0)
        with pytest.raises(ValueError):
            stats.expected_annual(prices, basis="harmonic")
        with pytest.raises(ValueError):
            stats.asset_returns(prices.iloc[:10], timeframe="M")  # too short


# --------------------------------------- Tier 3: the object == the engine --
OPTIONS = [
    dict(metric="log"),
    dict(timeframe="M"),
    dict(timeframe="M", samp_int=1),
    dict(timeframe="D", samp_int=5),
    dict(basis="geometric"),
    dict(metric="log", timeframe="M", samp_int=7, basis="geometric"),
]


class TestAssetSetThreading:
    @pytest.mark.parametrize("opts", OPTIONS)
    @pytest.mark.parametrize("method", ["normal", "robust"])
    def test_estimates_are_the_engine(self, prices, opts, method):
        aset = AssetSet(prices, method=method, **opts)
        resolved = dict(metric=aset.metric, timeframe=aset.timeframe,
                        samp_int=aset.samp_int)
        pd.testing.assert_frame_equal(aset.returns,
                                      stats.asset_returns(prices, **resolved))
        pd.testing.assert_series_equal(
            aset.expected_returns,
            stats.expected_annual(prices, method=method, basis=aset.basis,
                                  **resolved))
        pd.testing.assert_frame_equal(
            aset.risk_matrix,
            stats.risk_matrix_annual(prices, method=method, **resolved))

    def test_samp_int_defaults_to_the_timeframe(self, prices):
        assert AssetSet(prices, timeframe="M").samp_int == 20
        assert AssetSet(prices, timeframe="D").samp_int == 1
        assert AssetSet(prices, timeframe="M", samp_int=3).samp_int == 3

    def test_options_are_read_only(self, prices):
        aset = AssetSet(prices)
        for name in ("metric", "timeframe", "samp_int", "basis"):
            with pytest.raises(AttributeError):
                setattr(aset, name, "log")

    def test_with_options_is_immutable_and_lazy(self, prices):
        a = AssetSet(prices, method="robust")
        b = a.with_options(timeframe="M")
        assert a.timeframe == "D" and a.samp_int == 1      # untouched
        assert (b.timeframe, b.samp_int, b.method) == ("M", 20, "robust")
        assert b.tickers == a.tickers and b.prices is a.prices
        assert not np.allclose(a.mu.to_numpy(), b.mu.to_numpy())
        assert a.with_options() is a
        assert a.with_options(metric="relative", timeframe="D") is a
        assert a.with_method("robust") is a                # still short-circuits
        assert a.with_method("normal").method == "normal"

    def test_with_options_keeps_an_explicit_samp_int(self, prices):
        a = AssetSet(prices, timeframe="D", samp_int=5)
        assert a.with_options(metric="log").samp_int == 5   # carried over
        assert a.with_options(timeframe="M").samp_int == 20  # re-derived
        assert a.with_options(timeframe="M", samp_int=5).samp_int == 5

    def test_repr_shows_only_non_default_options(self, prices):
        assert "timeframe" not in repr(AssetSet(prices))
        r = repr(AssetSet(prices, metric="log", timeframe="M"))
        assert "metric='log'" in r and "timeframe='M'" in r
        assert "samp_int" not in r                          # 20 is M's default
        assert "samp_int=3" in repr(AssetSet(prices, timeframe="M", samp_int=3))

    def test_bad_options_raise_on_the_object(self, prices):
        for bad in (dict(metric="Log"), dict(timeframe="Q"),
                    dict(basis="cagr"), dict(samp_int=-1)):
            with pytest.raises(ValueError):
                AssetSet(prices, **bad)

    def test_from_members_threads_the_options(self, prices):
        outer = AssetSet.from_members([prices["AAA"], prices["BBB"]],
                                      timeframe="M", basis="geometric")
        assert (outer.timeframe, outer.samp_int, outer.basis) == \
            ("M", 20, "geometric")
        pd.testing.assert_series_equal(
            outer.expected_returns,
            stats.expected_annual(prices[["AAA", "BBB"]], timeframe="M",
                                  basis="geometric"))


class TestPortfolioOnOptionedSets:
    @pytest.mark.parametrize("opts", OPTIONS)
    def test_returns_and_value_index_stay_consistent(self, prices, opts):
        aset = AssetSet(prices, **opts)
        p = aset.portfolio({"AAA": 0.5, "BBB": 0.5}, label="Half")
        np.testing.assert_allclose(p.returns.to_numpy(),
                                   aset.returns.to_numpy() @ p.weight_array)
        vi = p.value_index
        assert len(vi) == len(p.returns) + 1
        assert vi.iloc[0] == 100.0 and vi.index.is_monotonic_increasing
        # the value index replays the portfolio's own returns, in its metric
        replay = (np.log(vi / vi.shift(1)) if aset.metric == "log"
                  else vi.pct_change())
        np.testing.assert_allclose(replay.dropna().to_numpy(),
                                   p.returns.to_numpy(), atol=1e-12)

    def test_daily_default_value_index_still_spans_the_prices(self, prices):
        p = AssetSet(prices).portfolio()
        pd.testing.assert_index_equal(p.value_index.index, prices.index,
                                      exact=False)

    def test_monthly_value_index_starts_at_the_first_window(self, prices):
        p = AssetSet(prices, timeframe="M").portfolio()
        assert p.value_index.index[0] == prices.index[0]
        assert p.value_index.index[1] == prices.index[21]

    def test_an_optioned_portfolio_can_be_a_member(self, prices):
        inner = AssetSet(prices[["AAA", "BBB"]], timeframe="M")
        mix = inner.portfolio({"AAA": 0.6, "BBB": 0.4}, label="AB mix")
        outer = AssetSet.from_members([mix, prices["CCC"]], timeframe="M")
        assert outer.tickers == ["AB mix", "CCC"]
        assert np.isfinite(outer.mu.to_numpy()).all()


class TestAnalysisFacade:
    OPTS = dict(metric="log", timeframe="M", samp_int=10, basis="geometric")

    def test_compute_analysis_equals_the_object(self, prices):
        w = {"AAA": 1, "BBB": 3}
        via_fn = compute_analysis(prices, weights=w, risk_free_rate=0.03,
                                  method="normal", n_points=8, **self.OPTS)
        via_obj = AssetSet(prices, "normal", **self.OPTS).analysis(
            w, 0.03, n_points=8)
        assert via_fn == via_obj

    def test_analysis_overrides_go_through_with_options(self, prices):
        base = AssetSet(prices)
        assert base.analysis(n_points=6, **self.OPTS) == \
            base.with_options(**self.OPTS).analysis(n_points=6)

    def test_default_payload_is_untouched(self, prices):
        """Options are opt-in: no new keys, and the same numbers as before."""
        aset = AssetSet(prices, "robust")
        assert aset.analysis(n_points=6) == compute_analysis(
            prices, method="robust", n_points=6)
        assert set(aset.analysis(n_points=6)) == {
            "tickers", "method", "risk_free_rate", "assets", "start", "end",
            "n_days", "portfolio", "min_vol", "tangency", "frontier", "cal"}

    def test_monthly_analysis_is_a_different_frontier(self, prices):
        daily = compute_analysis(prices, n_points=8)
        monthly = compute_analysis(prices, n_points=8, timeframe="M")
        assert daily["min_vol"]["vol"] != monthly["min_vol"]["vol"]
        assert len(monthly["frontier"]) >= 4
        for p in monthly["frontier"]:
            assert abs(sum(p["weights"].values()) - 1) < 1e-3
