"""Stability bands: the generator, the identity, and the diagnostics."""
import numpy as np
import pandas as pd
import pytest

from condor import AssetSet, stability
from condor.assumptions import Assumptions, Constraints, Prior


def make_prices(mu, vol, n_rows, seed=0, cov=None):
    rng = np.random.default_rng(seed)
    mu, vol = np.asarray(mu), np.asarray(vol)
    r = rng.normal(mu / 252, vol / np.sqrt(252), (n_rows, len(mu)))
    idx = pd.bdate_range("2012-01-02", periods=n_rows + 1)
    p = 100 * np.vstack([np.ones(len(mu)), np.cumprod(1 + r, axis=0)])
    return pd.DataFrame(p, index=idx, columns=[f"A{i}" for i in range(len(mu))])


# ---------------------------------------------------------------- generator
def test_block_indices_cover_exactly_and_are_contiguous():
    rng = np.random.default_rng(3)
    for n in (21, 50, 105, 7):
        idx = stability.block_indices(n, 21, rng)
        assert len(idx) == n and idx.min() >= 0 and idx.max() < n
        b = min(21, n)
        for s in range(0, n, b):  # each block is a run of consecutive rows
            seg = idx[s:s + b]
            assert (np.diff(seg) == 1).all()


def test_same_seed_same_blocks_different_seed_differs():
    a = stability.block_indices(500, 21, np.random.default_rng(1))
    b = stability.block_indices(500, 21, np.random.default_rng(1))
    c = stability.block_indices(500, 21, np.random.default_rng(2))
    assert (a == b).all() and not (a == c).all()


def test_same_indices_for_every_asset_and_the_tbill():
    prices = make_prices([0.1, 0.05, 0.08], [0.2, 0.1, 0.15], 210, seed=4)
    rf = pd.Series(np.linspace(0.01, 0.04, len(prices)), index=prices.index)
    idx = stability.block_indices(210, 21, np.random.default_rng(0))
    p2 = stability.resample_prices(prices, idx)
    r_orig = prices.pct_change().iloc[1:].to_numpy()
    r_new = p2.pct_change().iloc[1:].to_numpy()
    np.testing.assert_allclose(r_new, r_orig[idx], atol=1e-12)  # all columns
    rf2 = stability.resample_series(rf, prices.index[1:], idx)
    np.testing.assert_allclose(rf2.to_numpy(), rf.iloc[1:].to_numpy()[idx])
    assert rf2.index.equals(prices.index[1:])


def test_summarize_hand_case():
    out = stability.summarize([np.array([0.5, 0.5]), np.array([1.0, 0.0]),
                               np.array([0.0, 1.0])], ["X", "Y"])
    assert out["X"]["p50"] == pytest.approx(0.5)
    assert out["X"]["held_share"] == pytest.approx(2 / 3)
    assert stability.summarize([], ["X"])["X"]["p50"] is None


# ----------------------------------------------------------------- identity
def test_identity_resample_reproduces_the_sets_tangency():
    prices = make_prices([0.1, 0.05, 0.08], [0.2, 0.1, 0.15], 400, seed=5)
    aset = AssetSet(prices)
    want = aset.tangency(0.02).weight_array
    got = aset._resampled(np.arange(400)).tangency(0.02).weight_array
    np.testing.assert_allclose(got, want, atol=1e-8)


def test_identity_in_premium_mode_with_a_prior_and_limits():
    prices = make_prices([0.1, 0.05, 0.08], [0.2, 0.1, 0.15], 400, seed=5)
    rf = pd.Series(np.linspace(0.01, 0.04, len(prices)), index=prices.index)
    prior = Prior(kind="equilibrium", reference="A0", t0=10.0)
    aset = AssetSet(prices, rf_history=rf, rf_level=0.03, prior=prior)
    con = Constraints.from_dict({"bounds": {"A1": {"max": 0.5}}})
    want = aset.tangency(0.03, con).weight_array
    got = aset._resampled(np.arange(400)).tangency(0.03, con).weight_array
    np.testing.assert_allclose(got, want, atol=1e-7)


def test_identity_with_outside_market_proxy():
    prices = make_prices([0.1, 0.05], [0.2, 0.1], 400, seed=5)
    ref = make_prices([0.07], [0.15], 400, seed=9)["A0"]
    ref.index = prices.index
    rf = pd.Series(0.02, index=prices.index)
    prior = Prior(kind="equilibrium", reference="MKT", t0=10.0)
    aset = AssetSet(prices, rf_history=rf, rf_level=0.02, prior=prior,
                    reference_prices=ref.rename("MKT"))
    want = aset.premiums.to_numpy()
    got = aset._resampled(np.arange(400)).premiums.to_numpy()
    np.testing.assert_allclose(got, want, atol=1e-8)


# --------------------------------------------------------------- diagnostics
def test_degenerate_cycle_collapses_the_bands():
    k, block = 20, 21
    rng = np.random.default_rng(7)
    cycle = rng.normal(0, 0.004, (block, 3))
    cycle -= cycle.mean(axis=0)
    r = np.array([0.0004, 0.0003, 0.0005]) + np.tile(cycle, (k, 1))
    idx = pd.bdate_range("2015-01-02", periods=k * block + 1)
    prices = pd.DataFrame(100 * np.vstack([np.ones(3), np.cumprod(1 + r, axis=0)]),
                          index=idx, columns=list("XYZ"))
    out = AssetSet(prices).stability(0.0, n=12, block=block, seed=1)
    assert out["n_failed"] == 0
    for t, b in out["assets"].items():
        assert b["p90"] - b["p10"] < 1e-5, t
        assert b["p50"] == pytest.approx(
            AssetSet(prices).tangency(0.0).weights[t], abs=1e-5)


def test_result_shape_and_reproducible():
    aset = AssetSet(make_prices([0.1, 0.05, 0.08], [0.2, 0.1, 0.15], 300, seed=2))
    a = aset.stability(0.02, n=8, seed=3)
    b = aset.stability(0.02, n=8, seed=3)
    c = aset.stability(0.02, n=8, seed=4)
    assert a == b and a != c
    assert (a["n"], a["block"], a["seed"]) == (8, 21, 3)
    assert set(a["assets"]) == {"A0", "A1", "A2"}
    for v in a["assets"].values():
        assert v["p10"] <= v["p50"] <= v["p90"]
        assert 0 <= v["held_share"] <= 1


def test_limits_hold_in_every_resample():
    prices = make_prices([0.12, 0.05, 0.07], [0.2, 0.1, 0.15], 500, seed=6)
    aset = AssetSet(prices)
    free = aset.tangency(0.02).weights
    cap = float(free.max()) / 2
    top = free.idxmax()
    con = Constraints.from_dict({"bounds": {top: {"max": cap}}})
    out = aset.stability(0.02, constraints=con, n=15, seed=1)
    assert out["n_failed"] == 0
    assert out["assets"][top]["p90"] <= cap + 1e-6
    floor = Constraints.from_dict({"bounds": {"A1": {"min": 0.3}}})
    out = aset.stability(0.02, constraints=floor, n=15, seed=1)
    assert out["assets"]["A1"]["p10"] >= 0.3 - 1e-6


def test_assumptions_prior_and_limits_apply_in_every_resample():
    prices = make_prices([0.12, 0.05, 0.07], [0.2, 0.1, 0.15], 500, seed=6)
    rf = pd.Series(0.02, index=prices.index)
    aset = AssetSet(prices, rf_history=rf, rf_level=0.02)
    a = Assumptions.from_dict({
        "name": "t", "prior": {"kind": "equilibrium", "reference": "A0", "t0": 20},
        "constraints": {"bounds": {"A0": {"max": 0.4}}}})
    under = aset.with_options(prior=a.prior)
    out = under.stability(0.02, constraints=a.constraints, n=10, seed=1)
    assert out["n_failed"] == 0 and out["assets"]["A0"]["p90"] <= 0.4 + 1e-6


def test_width_shrinks_with_more_data():
    mu, vol = [0.10, 0.08, 0.06], [0.15, 0.15, 0.15]
    widths = {}
    for rows in (500, 5000):
        s = AssetSet(make_prices(mu, vol, rows, seed=11)).stability(
            0.02, n=30, seed=0)
        assert s["n_failed"] == 0
        widths[rows] = {t: v["p90"] - v["p10"] for t, v in s["assets"].items()}
    for t in widths[500]:
        assert widths[5000][t] < widths[500][t], (t, widths)


def test_no_asset_beats_the_rate_is_all_failed_not_an_error():
    aset = AssetSet(make_prices([0.03, 0.02], [0.1, 0.1], 300, seed=1))
    out = aset.stability(0.50, n=5)
    assert out["n_failed"] == 5 and out["n"] == 5
    assert all(v["p50"] is None for v in out["assets"].values())


def test_needs_two_assets():
    with pytest.raises(ValueError):
        AssetSet(make_prices([0.1], [0.2], 100)).stability(0.02, n=2)


# ----------------------------------------------------- feasibility and proxies
def test_infeasible_limits_raise_instead_of_counting_as_failed():
    aset = AssetSet(make_prices([0.1, 0.05, 0.08], [0.2, 0.1, 0.15], 300, seed=2))
    con = Constraints.from_dict({"bounds": {"A0": {"min": 0.7}, "A1": {"min": 0.7}}})
    with pytest.raises(ValueError):
        aset.stability(0.02, constraints=con, n=3)


def test_proxy_with_too_little_overlap_raises():
    prices = make_prices([0.1, 0.05], [0.2, 0.1], 400, seed=5)
    ref = make_prices([0.07], [0.15], 400, seed=9)["A0"]
    ref.index = prices.index
    ref = ref.iloc[-30:].rename("MKT")        # 30 days: too few to price assets
    rf = pd.Series(0.02, index=prices.index)
    aset = AssetSet(prices, rf_history=rf, rf_level=0.02, reference_prices=ref,
                    prior=Prior(kind="equilibrium", reference="MKT", t0=10.0))
    with pytest.raises(ValueError):
        aset.stability(0.02, n=3)


def younger_proxy_set(rows=400, start=150):
    prices = make_prices([0.1, 0.05], [0.2, 0.1], rows, seed=5)
    ref = make_prices([0.07], [0.15], rows, seed=9)["A0"].rename("MKT")
    ref.index = prices.index
    ref = ref.iloc[start:]
    rf = pd.Series(0.02, index=prices.index)
    aset = AssetSet(prices, rf_history=rf, rf_level=0.02, reference_prices=ref,
                    prior=Prior(kind="equilibrium", reference="MKT", t0=10.0))
    return aset, start


def test_younger_proxy_identity_and_same_rows():
    aset, start = younger_proxy_set()
    got = aset._resampled(np.arange(400)).premiums.to_numpy()
    np.testing.assert_allclose(got, aset.premiums.to_numpy(), atol=1e-8)
    # a real resample: the proxy covers exactly the dates from its start on,
    # every one of its returns taken from a row that has a proxy return
    rng = np.random.default_rng(0)
    idx = stability.split_block_indices(400, 21, rng, start)
    assert len(idx) == 400 and (idx[start:] >= start).all()
    assert (idx[:start] < start).all()
    ref2 = stability.resample_reference(aset._aligned_reference(), idx)
    assert ref2.index.equals(aset.prices.index[start:])
    assert not ref2.isna().any()
    r_orig = aset._aligned_reference().pct_change().iloc[1:].to_numpy()
    np.testing.assert_allclose(ref2.pct_change().to_numpy()[1:],
                               r_orig[idx[start:]], atol=1e-12)


def test_younger_proxy_stability_runs_and_is_reproducible():
    aset, _ = younger_proxy_set()
    a = aset.stability(0.02, n=5, seed=1)
    assert a["n_failed"] == 0 and a == aset.stability(0.02, n=5, seed=1)
