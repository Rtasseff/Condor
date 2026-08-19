"""Object API (model.py) == engine API, number for number.

The verification suite (test_verification.py) pins the engine functions
against legacy code, closed-form Markowitz, and notebook golden numbers.
These tests pin the object layer to the engine, so the chain holds:
AssetSet/Portfolio/Frontier -> engine -> verified truth.
"""

import numpy as np
import pandas as pd
import pytest

from condor import AssetSet, Frontier, Portfolio, compute_analysis, stats
from condor.frontier import _perf, _solve


@pytest.fixture(scope="module")
def prices():
    rng = np.random.default_rng(7)
    n, k = 600, 4
    mu = np.array([0.0006, 0.0004, 0.0002, 0.0005])
    chol = np.linalg.cholesky(np.array([
        [0.00020, 0.00008, 0.00002, 0.00005],
        [0.00008, 0.00015, 0.00001, 0.00004],
        [0.00002, 0.00001, 0.00005, 0.00001],
        [0.00005, 0.00004, 0.00001, 0.00025],
    ]))
    rets = mu + rng.standard_normal((n, k)) @ chol.T
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx,
                        columns=["AAA", "BBB", "CCC", "DDD"])


@pytest.fixture(scope="module", params=["normal", "robust"])
def aset(request, prices):
    return AssetSet(prices, method=request.param)


# ----------------------------------------------------------------------
# AssetSet
# ----------------------------------------------------------------------
class TestAssetSet:
    def test_identity(self, aset, prices):
        assert aset.tickers == list(prices.columns)
        assert len(aset) == 4 and "AAA" in aset and "ZZZ" not in aset
        assert aset["BBB"].ticker == "BBB"
        assert [a.ticker for a in aset] == aset.tickers
        assert aset.n_days == len(prices)
        assert aset.start == str(prices.index[0].date())

    def test_estimates_are_the_engine(self, aset, prices):
        pd.testing.assert_series_equal(
            aset.expected_returns, stats.expected_annual(prices, aset.method))
        pd.testing.assert_frame_equal(
            aset.risk_matrix, stats.risk_matrix_annual(prices, aset.method))
        pd.testing.assert_frame_equal(aset.returns, stats.asset_returns(prices))
        assert aset.mu is aset.expected_returns          # alias, same cached object
        assert aset.sigma is aset.risk_matrix
        np.testing.assert_allclose(
            aset.dispersions.to_numpy(), np.sqrt(np.diag(aset.sigma.to_numpy())))
        assert list(aset.summary().columns) == ["expected_return", "dispersion"]
        assert aset.asset_points() == stats.asset_points(aset.mu, aset.sigma)

    def test_with_method(self, prices):
        a = AssetSet(prices, method="normal")
        b = a.with_method("robust")
        assert a.with_method("normal") is a
        assert b.method == "robust" and b.tickers == a.tickers
        assert not np.allclose(a.mu.to_numpy(), b.mu.to_numpy())

    def test_rejects_bad_inputs(self, prices):
        with pytest.raises(ValueError):
            AssetSet(prices, method="bayesian")
        with pytest.raises(ValueError):
            AssetSet(prices.iloc[:, :0])
        dup = pd.concat([prices["AAA"], prices["AAA"]], axis=1)
        with pytest.raises(ValueError):
            AssetSet(dup)


# ----------------------------------------------------------------------
# Portfolio
# ----------------------------------------------------------------------
class TestPortfolio:
    def test_equal_weight_default(self, aset):
        p = aset.portfolio()
        np.testing.assert_allclose(p.weight_array, 0.25)
        assert aset.equal_weight().label == "Equal weights"

    def test_weight_inputs_normalize_and_agree(self, aset):
        by_dict = aset.portfolio({"AAA": 2, "CCC": 2})          # missing -> 0
        by_seq = aset.portfolio([0.5, 0, 0.5, 0])
        by_ser = aset.portfolio(pd.Series({"CCC": 1.0, "AAA": 1.0}))  # by ticker, not order
        by_port = aset.portfolio(by_dict)                       # copy from a Portfolio
        for p in (by_dict, by_seq, by_ser, by_port):
            np.testing.assert_allclose(p.weight_array, [0.5, 0, 0.5, 0])
            assert p.weights.index.tolist() == aset.tickers
            assert p.weights.sum() == pytest.approx(1.0)

    def test_weight_validation(self, aset):
        with pytest.raises(KeyError):
            aset.portfolio({"AAA": 1, "ZZZ": 1})
        with pytest.raises(ValueError):
            aset.portfolio([1, 1, 1])
        with pytest.raises(ValueError):
            aset.portfolio({"AAA": -1, "BBB": 2})
        with pytest.raises(ValueError):
            aset.portfolio({"AAA": 0, "BBB": 0})

    def test_perf_is_the_engine(self, aset):
        p = aset.portfolio({"AAA": 0.4, "BBB": 0.1, "CCC": 0.3, "DDD": 0.2})
        rf = 0.03
        eng = _perf(p.weight_array, aset.mu, aset.sigma, rf)
        assert p.perf(rf) == eng
        assert p.expected_return == eng["ret"]
        assert p.dispersion == eng["vol"]
        assert p.sharpe(rf) == eng["sharpe"]
        d = p.to_dict(rf)
        assert set(d) == {"weights", "ret", "vol", "sharpe"}
        assert d["weights"] == {"AAA": 0.4, "BBB": 0.1, "CCC": 0.3, "DDD": 0.2}
        assert "Portfolio(" in repr(p)

    def test_asset_like_face(self, aset):
        """A portfolio's return series is the weighted asset returns, and
        its value_index reproduces them through pct_change."""
        p = aset.portfolio({"AAA": 0.6, "DDD": 0.4}, label="Mix")
        expected = aset.returns.to_numpy() @ p.weight_array
        np.testing.assert_allclose(p.returns.to_numpy(), expected)
        assert p.returns.name == "Mix"
        vi = p.value_index
        assert vi.iloc[0] == 100.0 and len(vi) == aset.n_days
        np.testing.assert_allclose(vi.pct_change().dropna().to_numpy(), expected)
        assert p.as_asset().ticker == "Mix"

    def test_portfolio_as_member_of_another_set(self, prices):
        """'A portfolio is an asset of assets': nest one and check its
        normal expected return is the same number either way (the mean
        is linear in the weights). Dispersion is re-estimated from the
        nested series, which is the point of nesting."""
        base = AssetSet(prices[["AAA", "BBB"]], method="normal")
        mix = base.portfolio({"AAA": 0.7, "BBB": 0.3}, label="AB mix")
        outer = AssetSet.from_members([mix, prices["CCC"]], method="normal")
        assert outer.tickers == ["AB mix", "CCC"]
        assert outer.mu["AB mix"] == pytest.approx(mix.expected_return, rel=1e-9)
        assert outer.mu["CCC"] == pytest.approx(
            stats.expected_annual(prices[["CCC"]])["CCC"], rel=1e-9)
        assert outer.min_vol().dispersion <= outer.portfolio().dispersion + 5e-5


# ----------------------------------------------------------------------
# Frontier
# ----------------------------------------------------------------------
RF = 0.02


@pytest.fixture(scope="module")
def fr(aset):
    return aset.frontier(risk_free_rate=RF, n_points=25)


class TestFrontier:
    RF = RF

    def test_anchors_are_the_engine_solves(self, aset, fr):
        np.testing.assert_allclose(
            fr.min_vol.weight_array, _solve(aset.mu, aset.sigma, "min_volatility"))
        np.testing.assert_allclose(
            fr.tangency.weight_array,
            _solve(aset.mu, aset.sigma, "max_sharpe", risk_free_rate=self.RF))
        assert fr.min_vol.label == "Min dispersion" and fr.tangency.label == "Tangency"

    def test_points_and_container(self, fr):
        assert 0 < len(fr) <= 25
        assert all(isinstance(p, Portfolio) for p in fr)
        assert fr[0] is fr.points[0]
        rets = [p.expected_return for p in fr]
        assert rets == sorted(rets)
        assert fr.curve.shape == (len(fr), 2)
        assert fr.min_vol.dispersion <= min(p.dispersion for p in fr) + 5e-5
        assert max(p.sharpe(self.RF) for p in fr) <= fr.tangency.sharpe(self.RF) + 1e-4

    def test_pick_any_point(self, fr):
        lo, hi = fr[0].expected_return, fr[-1].expected_return
        target = 0.5 * (lo + hi)
        p = fr.at_return(target)
        assert p.expected_return == pytest.approx(target, abs=1e-4)
        q = fr.at_dispersion(p.dispersion * 1.01)
        assert q.dispersion == pytest.approx(p.dispersion * 1.01, abs=1e-4)
        assert q.expected_return >= p.expected_return - 1e-6
        n = fr.nearest(expected_return=target)
        assert abs(n.expected_return - target) == min(
            abs(x.expected_return - target) for x in fr)
        with pytest.raises(ValueError):
            fr.nearest()
        with pytest.raises(ValueError):
            fr.nearest(expected_return=0.1, dispersion=0.1)

    def test_cal(self, fr):
        cal = fr.cal
        assert cal["x"][0] == 0.0 and cal["y"][0] == self.RF
        slope = (cal["y"][1] - cal["y"][0]) / cal["x"][1]
        assert slope == pytest.approx(fr.tangency.sharpe(self.RF))

    def test_to_dict_shape(self, fr):
        d = fr.to_dict()
        assert set(d) == {"min_vol", "tangency", "frontier", "cal"}
        assert len(d["frontier"]) == len(fr)
        assert d["tangency"] == fr.tangency.to_dict(self.RF)

    def test_no_tangency_when_rf_too_high(self, aset):
        fr = aset.frontier(risk_free_rate=5.0, n_points=5)
        assert fr.tangency is None and fr.cal is None
        assert fr.to_dict()["tangency"] is None

    def test_single_asset_is_a_point(self, prices):
        one = AssetSet(prices[["AAA"]])
        fr = one.frontier()
        assert len(fr) == 0 and fr.min_vol is None and fr.tangency is None
        assert fr.cal is None
        with pytest.raises(ValueError):
            one.min_vol()
        with pytest.raises(ValueError):
            fr.nearest(expected_return=0.1)


# ----------------------------------------------------------------------
# Facade
# ----------------------------------------------------------------------
class TestFacade:
    def test_compute_analysis_is_asset_set_analysis(self, prices):
        w = {"AAA": 1, "BBB": 1, "ZZZ": 5}   # unknown ticker ignored at the boundary
        via_fn = compute_analysis(prices, weights=w, risk_free_rate=0.03,
                                  method="robust", n_points=12)
        via_obj = AssetSet(prices, "robust").analysis(w, 0.03, n_points=12)
        assert via_fn == via_obj
        assert via_fn["portfolio"]["weights"] == {"AAA": 0.5, "BBB": 0.5}
        assert len(via_fn["frontier"]) <= 12
        assert set(via_fn) == {"tickers", "method", "risk_free_rate", "assets",
                               "start", "end", "n_days", "portfolio",
                               "min_vol", "tangency", "frontier", "cal"}

    def test_boundary_leniency(self, prices):
        # negatives clipped, all-zero -> equal weights; core API would raise
        res = AssetSet(prices).analysis({"AAA": -1, "BBB": 0}, 0.02, n_points=3)
        assert res["portfolio"]["weights"] == {t: 0.25 for t in prices.columns}
