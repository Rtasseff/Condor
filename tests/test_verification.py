"""Verification against independent references.

Mirrors the spot-check approach of the legacy notebook
context/legacy/project/202411_refact_optWF.ipynb, made permanent:

  Tier 1  v2 functions vs the legacy Condor functions on identical inputs
          (genStats / genFin / portOpt from context/legacy).
  Tier 2  optimizer output vs closed-form Markowitz solutions.
  Tier 3  golden numbers: reproduce the notebook's MSFT/NEE/CVX results from
          the original S&P 500 CSV, then confirm v2 gives the same portfolio
          statistics from the same inputs.  (Skipped if the CSV is absent —
          it lives in drive_export/, outside git.)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "context" / "legacy" / "analytics"))

from functions import genFin, genStats, portOpt  # noqa: E402  (legacy)

from condor import stats  # noqa: E402
from condor.frontier import _perf, _solve, compute_analysis  # noqa: E402

TOL_SOLVER = 2e-3  # cvxpy default tolerances; weights agree to ~1e-3


# ---------------------------------------------------------------- fixtures --
@pytest.fixture(scope="module")
def rets():
    """Seeded daily returns, 3 assets, some correlation, a few outliers."""
    rng = np.random.default_rng(7)
    n = 800
    corr = np.array([[1, .4, .1], [.4, 1, .2], [.1, .2, 1]])
    x = rng.standard_normal((n, 3)) @ np.linalg.cholesky(corr).T
    x = x * np.array([.018, .011, .009]) + np.array([.0007, .0004, .0002])
    x[10, 0] = 0.25   # outliers, to make robust != normal
    x[20, 1] = -0.30
    return pd.DataFrame(x, columns=["A", "B", "C"],
                        index=pd.bdate_range("2020-01-02", periods=n))


@pytest.fixture(scope="module")
def prices(rets):
    """Prices whose pct_change() reproduces `rets` exactly (leading base row
    so the first return is not lost)."""
    px = 100 * (1 + rets).cumprod()
    base = pd.DataFrame([[100.0] * rets.shape[1]], columns=rets.columns,
                        index=[rets.index[0] - pd.tseries.offsets.BDay(1)])
    return pd.concat([base, px])


# ------------------------------------------------ Tier 1: vs legacy code --
class TestVsLegacy:
    def test_comad_matrix_matches_legacy_loop(self, rets):
        legacy = genStats.codisper_sq(rets.to_numpy(), method="CoMAD")
        v2 = stats._comad_matrix(rets).to_numpy()
        np.testing.assert_allclose(v2, legacy, rtol=0, atol=1e-12)

    def test_comad_handles_nan_pairwise_like_legacy(self, rets):
        r = rets.copy()
        r.iloc[5, 0] = np.nan
        r.iloc[9, 2] = np.nan
        legacy = genStats.codisper_sq(r.to_numpy(), method="CoMAD")
        v2 = stats._comad_matrix(r).to_numpy()
        np.testing.assert_allclose(v2, legacy, atol=1e-12)

    def test_robust_expected_return_matches_legacy_median(self, prices, rets):
        legacy = genFin.returnExp(rets.to_numpy(), method="Robust")
        v2 = stats.expected_annual(prices, method="robust").to_numpy()
        # legacy is per-period; v2 annualizes by 252 (genFin.annualize 'D')
        np.testing.assert_allclose(v2, legacy * 252, rtol=1e-10)

    def test_normal_expected_return_is_arithmetic_mean_x252(self, prices, rets):
        legacy = genFin.returnExp(rets.to_numpy(), method="Normal")
        v2 = stats.expected_annual(prices, method="normal").to_numpy()
        # note pypfopt.mean_historical_return default is geometric; we force
        # compounding=False so this equals legacy mean * 252
        np.testing.assert_allclose(v2, legacy * 252, rtol=1e-9)

    def test_portfolio_perf_matches_legacy_asset_set_perform(self, rets):
        mu = pd.Series(rets.mean() * 252)
        sigma = pd.DataFrame(rets.cov() * 252, index=mu.index, columns=mu.index)
        w = np.array([0.5, 0.3, 0.2])
        r_leg, d_leg = genFin.asset_set_perform(w, mu.to_numpy(), sigma.to_numpy())
        sr_leg = genFin.asset_set_sharpe_ratio(w, mu.to_numpy(), sigma.to_numpy(),
                                               riskFreeRate=0.03)
        p = _perf(w, mu, sigma, rf=0.03)
        assert p["ret"] == pytest.approx(r_leg, rel=1e-12)
        assert p["vol"] == pytest.approx(d_leg, rel=1e-12)
        assert p["sharpe"] == pytest.approx(sr_leg, rel=1e-12)

    def test_max_sharpe_agrees_with_legacy_slsqp(self, rets):
        mu = pd.Series(rets.mean() * 252)
        sigma = pd.DataFrame(rets.cov() * 252, index=mu.index, columns=mu.index)
        w_leg = portOpt.max_sharpe_ratio(mu.to_numpy(), sigma.to_numpy(),
                                         riskFreeRate=0.02)["x"]
        w_v2 = _solve(mu, sigma, "max_sharpe", risk_free_rate=0.02)
        np.testing.assert_allclose(w_v2, w_leg, atol=TOL_SOLVER)

    def test_min_dispersion_agrees_with_legacy_slsqp(self, rets):
        mu = pd.Series(rets.mean() * 252)
        sigma = pd.DataFrame(rets.cov() * 252, index=mu.index, columns=mu.index)
        w_leg = portOpt.min_dispersion(mu.to_numpy(), sigma.to_numpy())["x"]
        w_v2 = _solve(mu, sigma, "min_volatility")
        np.testing.assert_allclose(w_v2, w_leg, atol=TOL_SOLVER)


# --------------------------------------- Tier 2: vs closed-form Markowitz --
class TestClosedForm:
    """Unconstrained analytic solutions; valid whenever the constrained
    (long-only) optimum is interior, which these inputs guarantee."""

    @pytest.fixture
    def mu_sigma(self):
        mu = pd.Series([0.10, 0.07, 0.05], index=list("XYZ"))
        s = np.array([0.20, 0.15, 0.10])
        corr = np.array([[1, .3, .1], [.3, 1, .2], [.1, .2, 1]])
        sigma = pd.DataFrame(np.outer(s, s) * corr, index=mu.index, columns=mu.index)
        return mu, sigma

    def test_min_variance_closed_form(self, mu_sigma):
        mu, sigma = mu_sigma
        inv = np.linalg.inv(sigma.to_numpy())
        ones = np.ones(3)
        w_exact = inv @ ones / (ones @ inv @ ones)
        assert (w_exact > 0).all()
        w = _solve(mu, sigma, "min_volatility")
        np.testing.assert_allclose(w, w_exact, atol=TOL_SOLVER)

    def test_tangency_closed_form(self, mu_sigma):
        mu, sigma = mu_sigma
        rf = 0.02
        inv = np.linalg.inv(sigma.to_numpy())
        ex = mu.to_numpy() - rf
        w_exact = inv @ ex / (np.ones(3) @ inv @ ex)
        assert (w_exact > 0).all()
        w = _solve(mu, sigma, "max_sharpe", risk_free_rate=rf)
        np.testing.assert_allclose(w, w_exact, atol=TOL_SOLVER)

    def test_two_asset_min_variance_textbook(self):
        # w1 = (s2^2 - s12) / (s1^2 + s2^2 - 2 s12)
        s1, s2, rho = 0.25, 0.10, 0.2
        s12 = rho * s1 * s2
        w1_exact = (s2**2 - s12) / (s1**2 + s2**2 - 2 * s12)
        mu = pd.Series([0.08, 0.04], index=["P", "Q"])
        sigma = pd.DataFrame([[s1**2, s12], [s12, s2**2]],
                             index=mu.index, columns=mu.index)
        w = _solve(mu, sigma, "min_volatility")
        assert w[0] == pytest.approx(w1_exact, abs=TOL_SOLVER)

    def test_frontier_points_hit_their_return_targets(self, mu_sigma):
        mu, sigma = mu_sigma
        for target in (0.06, 0.07, 0.08, 0.09):
            w = _solve(mu, sigma, "efficient_return", target_return=target)
            assert float(w @ mu.to_numpy()) == pytest.approx(target, abs=1e-4)


# ------------------------------------------- Tier 3: golden vs notebook --
CSV = REPO / "drive_export" / "files" / "data_analytics_v1" / "sp500_combined.csv"

# Values printed in 202411_refact_optWF.ipynb, cells [6], [7], [14]
# (MSFT, NEE, CVX; monthly relative returns = 21-day lag; sample every 20th;
#  'Normal' estimators; equal weights; annualize monthly x12).
NB_EXPECTED_RETURNS = np.array([0.02116498, 0.01326033, 0.00917267])
NB_CODISP = np.array([[0.00388693, 0.00169858, 0.00162529],
                      [0.00169858, 0.00359167, 0.00116302],
                      [0.00162529, 0.00116302, 0.00754383]])
NB_PORT_MONTHLY = (0.014532659735113574, 0.05163569059196007)
NB_PORT_ANNUAL = (0.1743919168213629, 0.17887127917836224)


@pytest.mark.skipif(not CSV.exists(), reason="legacy S&P CSV not present")
class TestGoldenNotebook:
    @staticmethod
    @pytest.fixture(scope="class")
    def legacy_inputs():
        df = pd.read_csv(CSV, usecols=["Date", "Symbol", "Adj Close"])
        df["Date"] = pd.to_datetime(df["Date"])
        wide = df.pivot_table(index="Date", columns="Symbol", values="Adj Close")
        px = wide[["MSFT", "NEE", "CVX"]].to_numpy()
        r = genFin.returns(px, period=21, metric="Relative")
        r = r[np.arange(0, len(r), 20)]
        mu, disp = genFin.calc_return_prop(r, "Normal")
        cod = genFin.returnCoDispSq(r, "Normal")
        return mu, cod

    def test_reproduces_notebook_asset_stats(self, legacy_inputs):
        mu, cod = legacy_inputs
        np.testing.assert_allclose(mu, NB_EXPECTED_RETURNS, atol=1e-8)
        np.testing.assert_allclose(cod, NB_CODISP, atol=1e-8)

    def test_v2_perf_reproduces_notebook_portfolio(self, legacy_inputs):
        mu, cod = legacy_inputs
        w = np.ones(3) / 3
        idx = ["MSFT", "NEE", "CVX"]
        mu_s = pd.Series(mu, index=idx)
        cod_df = pd.DataFrame(cod, index=idx, columns=idx)
        p = _perf(w, mu_s, cod_df, rf=0.0)
        assert p["ret"] == pytest.approx(NB_PORT_MONTHLY[0], rel=1e-9)
        assert p["vol"] == pytest.approx(NB_PORT_MONTHLY[1], rel=1e-9)
        # annualized: x12 for return, x sqrt(12) for dispersion
        p12 = _perf(w, mu_s * 12, cod_df * 12, rf=0.0)
        assert p12["ret"] == pytest.approx(NB_PORT_ANNUAL[0], rel=1e-9)
        assert p12["vol"] == pytest.approx(NB_PORT_ANNUAL[1], rel=1e-9)
