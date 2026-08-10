"""Core analytics tests on synthetic data (no network needed)."""

import numpy as np
import pandas as pd
import pytest

from condor import stats
from condor.frontier import compute_analysis


@pytest.fixture(scope="module")
def prices():
    """Seeded geometric random walk for 4 assets, ~4 years daily."""
    rng = np.random.default_rng(42)
    n = 1000
    mu_daily = np.array([0.0006, 0.0004, 0.0002, 0.0005])
    vol_daily = np.array([0.020, 0.012, 0.007, 0.016])
    # correlated shocks
    corr = np.array([
        [1.0, 0.5, 0.1, 0.3],
        [0.5, 1.0, 0.2, 0.4],
        [0.1, 0.2, 1.0, 0.1],
        [0.3, 0.4, 0.1, 1.0],
    ])
    chol = np.linalg.cholesky(corr)
    shocks = rng.standard_normal((n, 4)) @ chol.T
    rets = mu_daily + shocks * vol_daily
    px = 100 * np.exp(np.cumsum(np.log1p(rets), axis=0))
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame(px, index=idx, columns=["AAA", "BBB", "CCC", "DDD"])


@pytest.mark.parametrize("method", ["normal", "robust"])
def test_stats_shapes_and_sanity(prices, method):
    mu = stats.expected_annual(prices, method=method)
    sigma = stats.risk_matrix_annual(prices, method=method)
    assert list(mu.index) == list(prices.columns)
    assert sigma.shape == (4, 4)
    # symmetric, PSD after repair
    s = sigma.to_numpy()
    assert np.allclose(s, s.T, atol=1e-10)
    assert np.linalg.eigvalsh(s).min() > -1e-8
    # annualized vols in a plausible range for these inputs (5%-60%)
    vols = np.sqrt(np.diag(s))
    assert (vols > 0.05).all() and (vols < 0.60).all()


@pytest.mark.parametrize("method", ["normal", "robust"])
def test_analysis_payload(prices, method):
    res = compute_analysis(prices, risk_free_rate=0.02, method=method)

    # frontier exists and weights sum to ~1 at every point
    assert len(res["frontier"]) >= 10
    for p in res["frontier"]:
        assert abs(sum(p["weights"].values()) - 1) < 1e-3
        assert all(w >= -1e-6 for w in p["weights"].values())  # long-only

    # frontier is a proper frontier: returns increase along the sweep
    rets = [p["ret"] for p in res["frontier"]]
    assert all(b >= a - 1e-9 for a, b in zip(rets, rets[1:]))

    # min-vol has the lowest volatility of any computed portfolio
    # (5e-5 slack: independent cvxpy solves agree only to solver tolerance)
    vols = [p["vol"] for p in res["frontier"]]
    assert res["min_vol"]["vol"] <= min(vols) + 5e-5

    # tangency has the highest Sharpe of any frontier point
    assert res["tangency"] is not None
    sharpes = [p["sharpe"] for p in res["frontier"]]
    assert res["tangency"]["sharpe"] >= max(sharpes) - 1e-6

    # CAL starts at the risk-free rate
    assert res["cal"]["y"][0] == pytest.approx(0.02)

    # default portfolio is equal-weighted
    assert res["portfolio"]["weights"] == pytest.approx(
        {t: 0.25 for t in prices.columns}
    )


def test_custom_weights_and_normalization(prices):
    res = compute_analysis(prices, weights={"AAA": 2, "BBB": 2}, method="normal")
    assert res["portfolio"]["weights"] == pytest.approx({"AAA": 0.5, "BBB": 0.5})


def test_single_asset_degenerates_gracefully(prices):
    res = compute_analysis(prices[["AAA"]], method="normal")
    assert res["frontier"] == []
    assert res["tangency"] is None
    assert res["portfolio"]["weights"] == {"AAA": 1.0}


def test_robust_differs_from_normal(prices):
    mu_n = stats.expected_annual(prices, method="normal")
    mu_r = stats.expected_annual(prices, method="robust")
    assert not np.allclose(mu_n.to_numpy(), mu_r.to_numpy())
