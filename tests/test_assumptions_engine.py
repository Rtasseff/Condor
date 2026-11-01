"""Assumptions mode (ADR 0008): engine hand cases and the model == engine."""
import numpy as np
import pandas as pd
import pytest

from condor import stats
from condor.assumptions import Assumptions, Constraints, Prior, View
from condor.frontier import (_constrained_max_return, _constrained_tangency,
                             _perf, _solve)
from condor.model import AssetSet


def _res(tickers, bounds=None, groups=None):
    return Constraints.from_dict(
        {"bounds": bounds or {}, "groups": groups or []}).resolve(tickers)


def _ab():
    mu = pd.Series([0.10, 0.04], index=["A", "B"])
    sig = pd.DataFrame(np.diag([0.04, 0.0025]), index=mu.index, columns=mu.index)
    return mu, sig


# ----- T1 / T2: constrained tangency ---------------------------------------
def test_t2_tangency_unconstrained_and_capped():
    mu, sig = _ab()
    w = _constrained_tangency(mu, sig, 0.02, _res(["A", "B"]))
    np.testing.assert_allclose(w, [0.2, 0.8], atol=1e-6)
    p = _perf(w, mu, sig, 0.02)
    assert p["ret"] == pytest.approx(0.052, abs=1e-6)
    assert p["vol"] == pytest.approx(0.05657, abs=1e-5)
    assert p["sharpe"] == pytest.approx(0.5657, abs=1e-4)
    w = _constrained_tangency(mu, sig, 0.02, _res(["A", "B"], {"B": {"max": 0.6}}))
    np.testing.assert_allclose(w, [0.4, 0.6], atol=1e-6)
    p = _perf(w, mu, sig, 0.02)
    assert p["ret"] == pytest.approx(0.064, abs=1e-6)
    assert p["vol"] == pytest.approx(0.08544, abs=1e-5)
    assert p["sharpe"] == pytest.approx(0.5150, abs=1e-4)


def _rand_problem(n, seed):
    rng = np.random.default_rng(seed)
    m = rng.normal(size=(n, n))
    sig = m @ m.T / n * 0.05 + np.eye(n) * 0.01
    names = [f"X{i}" for i in range(n)]
    mu = pd.Series(rng.uniform(0.03, 0.12, n), index=names)
    return mu, pd.DataFrame(sig, index=names, columns=names)


def test_t1_loose_limits_match_unconstrained():
    mu, sig = _rand_problem(5, 1)
    free = _solve(mu, sig, "max_sharpe", risk_free_rate=0.02)
    tight = _constrained_tangency(
        mu, sig, 0.02, _res(list(mu.index), {t: {"max": 1.0} for t in mu.index}))
    np.testing.assert_allclose(tight, free, atol=1e-4)  # pypfopt cleans to 1e-5
    # limits wider than the solution: still the unconstrained answer
    loose = _res(list(mu.index), {t: {"max": min(1, w + 0.2)}
                                  for t, w in zip(mu.index, free)})
    np.testing.assert_allclose(
        _constrained_tangency(mu, sig, 0.02, loose), free, atol=1e-4)


@pytest.mark.parametrize("seed", [2, 3])
def test_constrained_tangency_matches_dense_scan(seed):
    """4 assets, an asset cap and a group cap: QP vs brute-force grid."""
    mu, sig = _rand_problem(4, seed)
    t = list(mu.index)
    res = _res(t, {t[0]: {"max": 0.4}}, [{"tickers": [t[1], t[2]], "max": 0.35}])
    w = _constrained_tangency(mu, sig, 0.02, res)
    step = np.linspace(0, 1, 101)
    g = np.array(np.meshgrid(step, step, step, indexing="ij")).reshape(3, -1).T
    g = np.column_stack([g, 1 - g.sum(1)])
    ok = ((g[:, 3] >= -1e-12) & (g[:, 0] <= 0.4 + 1e-12)
          & (g[:, 1] + g[:, 2] <= 0.35 + 1e-12))
    g = g[ok]
    m, s = mu.to_numpy(), sig.to_numpy()
    sharpe = (g @ m - 0.02) / np.sqrt(np.einsum("ij,jk,ik->i", g, s, g))
    best = sharpe.max()
    got = _perf(w, mu, sig, 0.02)["sharpe"]
    assert got >= best - 1e-9           # the QP is at least as good as the grid
    assert got - best < 2e-3            # and the grid is close to it
    assert w[0] <= 0.4 + 1e-7 and w[1] + w[2] <= 0.35 + 1e-7


def test_tangency_none_when_nothing_beats_rf():
    mu, sig = _ab()
    assert _constrained_tangency(mu, sig, 0.5, _res(["A", "B"])) is None
    # A capped at 5% tops out at 4.3%: nothing allowed beats 4.5%, 4.2% is fine
    capped = _res(["A", "B"], {"A": {"max": 0.05}})
    assert _constrained_tangency(mu, sig, 0.045, capped) is None
    assert _constrained_tangency(mu, sig, 0.042, capped) is not None
    assert _constrained_tangency(mu, sig, 0.0999, _res(
        ["A", "B"], {"A": {"max": 0.0}})) is None


def test_infeasible_limits_raise():
    mu, sig = _ab()
    bad = _res(["A", "B"], {"A": {"min": 0.6}, "B": {"min": 0.6}})
    for fn in (lambda: _constrained_tangency(mu, sig, 0.02, bad),
               lambda: _solve(mu, sig, "min_volatility", bad),
               lambda: _constrained_max_return(mu, bad)):
        with pytest.raises(ValueError, match="These limits can't all hold"):
            fn()
    low = _res(["A", "B"], {"A": {"max": 0.3}, "B": {"max": 0.3}})
    with pytest.raises(ValueError, match="These limits can't all hold"):
        _solve(mu, sig, "min_volatility", low)
    grp = _res(["A", "B"], {"A": {"max": 0.2}},
               [{"tickers": ["A", "B"], "max": 0.5}])
    with pytest.raises(ValueError, match="These limits can't all hold"):
        _solve(mu, sig, "min_volatility", grp)


def test_constrained_solves_respect_limits():
    mu, sig = _ab()
    res = _res(["A", "B"], {"B": {"max": 0.6}})
    np.testing.assert_allclose(_solve(mu, sig, "min_volatility", res),
                               [0.4, 0.6], atol=1e-4)
    np.testing.assert_allclose(_constrained_max_return(mu, res),
                               [1, 0], atol=1e-7)
    w = _solve(mu, sig, "efficient_return", res, target_return=0.07)
    assert w[0] == pytest.approx(0.5, abs=1e-4)


def test_exact_return_hand_case():
    mu, sig = _ab()
    w = _solve(mu, sig, "exact_return", None, target_return=0.04)
    np.testing.assert_allclose(w, [0, 1], atol=1e-4)


# ----- T3 / T4 / T5 / equilibrium --------------------------------------------
def test_equilibrium_hand_case_and_reference_outside():
    sig = pd.DataFrame([[0.04, 0.012], [0.012, 0.0225]], index=["A", "B"],
                       columns=["A", "B"])
    pi = stats.equilibrium_premiums(sig, "A", 0.05)
    np.testing.assert_allclose(pi.to_numpy(), [0.05, 0.015], atol=1e-12)
    big = pd.DataFrame(
        [[0.04, 0.012, 0.01], [0.012, 0.0225, 0.005], [0.01, 0.005, 0.09]],
        index=list("ABC"), columns=list("ABC"))
    pi = stats.equilibrium_premiums(big, {"A": 1.0}, 0.05)
    np.testing.assert_allclose(pi[["A", "B"]].to_numpy(), [0.05, 0.015],
                               atol=1e-12)
    assert pi["C"] == pytest.approx(0.05 * 0.01 / 0.04)
    with pytest.raises(ValueError):
        stats.equilibrium_premiums(sig, "Z", 0.05)


def test_t3_no_views_reproduces_reference():
    sig = pd.DataFrame(np.array([[0.04, 0.01, 0.005], [0.01, 0.03, 0.008],
                                 [0.005, 0.008, 0.06]]),
                       index=list("ABC"), columns=list("ABC"))
    wref = {"A": 0.5, "B": 0.3, "C": 0.2}
    pi = stats.equilibrium_premiums(sig, wref, 0.05)
    post = stats.apply_views(pi, sig, 0.05, [])
    pd.testing.assert_series_equal(post, pi)
    w = _constrained_tangency(pi, sig, 0.0, _res(list("ABC")))
    np.testing.assert_allclose(w, [0.5, 0.3, 0.2], atol=1e-6)


def test_t4_one_absolute_view():
    sig = pd.DataFrame(np.diag([0.04, 0.0025]), index=["A", "B"],
                       columns=["A", "B"])
    pi = pd.Series([0.06, 0.01], index=["A", "B"])
    post = stats.apply_views(pi, sig, 0.05, [("A", 0.10, np.sqrt(0.002))])
    np.testing.assert_allclose(post.to_numpy(), [0.08, 0.01], atol=1e-9)
    tight = stats.apply_views(pi, sig, 0.05, [("A", 0.10, 1e-6)])
    assert tight["A"] == pytest.approx(0.10, abs=1e-6)
    loose = stats.apply_views(pi, sig, 0.05, [("A", 0.10, 1e6)])
    assert loose["A"] == pytest.approx(0.06, abs=1e-6)


def test_t5_blend():
    s = lambda x: pd.Series([x])  # noqa: E731
    assert stats.blend_premiums(s(0.08), s(0.16), 25, 6.9)[0] == \
        pytest.approx(0.0973, abs=5e-5)
    r = stats.blend_premiums(s(0.0), s(0.10), 1, np.pi / 2, "robust")[0]
    assert r == pytest.approx(0.05, abs=1e-12)


# ----- model == engine -------------------------------------------------------
N = 900


def _prices(seed=5, cols="ABC"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=N + 1)
    r = rng.normal([0.0005, 0.0003, 0.0007, 0.0004][:len(cols)],
                   [0.01, 0.006, 0.015, 0.012][:len(cols)], (N + 1, len(cols)))
    r[0] = 0
    return pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx,
                        columns=list(cols))


def _rf(prices, y=0.03):
    return pd.Series(y, index=prices.index)


@pytest.mark.parametrize("method", ["normal", "robust"])
def test_model_posterior_equals_engine(method):
    p = _prices()
    rf = _rf(p)
    prior = Prior("equilibrium", "A", 0.05, 15.0,
                  (View("B", 0.09, 0.04), View("ZZZ", 0.5, 0.1)))
    a = AssetSet(p, method=method, rf_history=rf, rf_level=0.03, prior=prior)
    sigma = stats.risk_matrix_annual(p, method=method)
    sample = stats.premium_annual(p, rf, method=method)
    pi = stats.equilibrium_premiums(sigma, "A", 0.05)
    T = (p.index[-1] - p.index[0]).days / 365.25
    blended = stats.blend_premiums(pi, sample, 15.0, T, method)
    tau = 1 / (15.0 + stats.effective_years(T, method))
    post = stats.apply_views(blended, sigma, tau, [("B", 0.09 - 0.03, 0.04)])
    pd.testing.assert_series_equal(a.sample_premiums, sample)
    pd.testing.assert_series_equal(a.prior_premiums, pi, check_names=False)
    np.testing.assert_allclose(a.premiums.to_numpy(), post.to_numpy())
    np.testing.assert_allclose(a.expected_returns.to_numpy(),
                               (0.03 + post).to_numpy())
    cols = a.summary().columns
    assert {"premium", "sample_premium", "prior_premium"} <= set(cols)
    note = a.prior_note()
    assert note["t0"] == 15.0 and note["reference"] == "A"
    assert note["t_years"] == pytest.approx(T)
    assert note["t_effective"] == pytest.approx(stats.effective_years(T, method))


def test_default_market_premium_and_releveling():
    from condor.forecast import MARKET_ANCHOR
    p = _prices()
    a = AssetSet(p, rf_history=_rf(p), rf_level=0.03,
                 prior=Prior("equilibrium", "A"))
    assert a.market_premium == pytest.approx(MARKET_ANCHOR - 0.03)
    b = a.with_options(rf_level=0.05)
    assert b.market_premium == pytest.approx(MARKET_ANCHOR - 0.05)
    assert b.prior is a.prior
    assert AssetSet(p, rf_history=_rf(p), rf_level=0.2,
                    prior=Prior("equilibrium", "A")).market_premium == 0.0


def test_reference_outside_set_uses_joined_sigma():
    p = _prices(cols="ABCD")
    ref = p["D"].iloc[10:]            # shorter: overlap only
    sub = p[["A", "B", "C"]]
    a = AssetSet(sub, rf_history=_rf(p), rf_level=0.03,
                 prior=Prior("equilibrium", "D", 0.05), reference_prices=ref)
    joined = sub.join(ref.rename("D"), how="inner")
    pi = stats.equilibrium_premiums(stats.risk_matrix_annual(joined), "D", 0.05)
    np.testing.assert_allclose(a.prior_premiums.to_numpy(),
                               pi[["A", "B", "C"]].to_numpy())
    with pytest.raises(ValueError, match="needs its prices"):
        AssetSet(sub, rf_history=_rf(p), prior=Prior("equilibrium", "D"))


def test_prior_needs_premium_mode_and_history_kind():
    p = _prices()
    with pytest.raises(ValueError, match="premium mode"):
        AssetSet(p, prior=Prior("history"))
    h = AssetSet(p, rf_history=_rf(p), rf_level=0.03, prior=Prior("history"))
    plain = AssetSet(p, rf_history=_rf(p), rf_level=0.03)
    np.testing.assert_allclose(h.expected_returns.to_numpy(),
                               plain.expected_returns.to_numpy())
    assert h.prior_premiums is None and h.prior_note()["t0"] == 0.0


def test_no_prior_payload_unchanged():
    p = _prices()
    a = AssetSet(p, rf_history=_rf(p), rf_level=0.03)
    out = a.analysis(risk_free_rate=0.03)
    assert not {"gaps", "prior_note", "premiums"} & set(out)
    assert "constraints" not in out["tangency"] and "constraints" not in out


# ----- constrained frontier + gaps ---------------------------------------------
def _t2_set():
    """AssetSet whose mu / sigma are exactly the T2 hand case."""
    p = _prices(cols="AB")
    a = AssetSet(p)
    mu, sig = _ab()
    a.__dict__["expected_returns"] = mu
    a.__dict__["risk_matrix"] = sig
    return a


def test_gaps_hand_numbers_unconstrained():
    a = _t2_set()
    fr = a.frontier(0.02)
    plan = a.portfolio({"B": 1.0})
    g = fr.gaps(plan)
    assert g["sharpe_gap"] == pytest.approx(0.1657, abs=1e-4)
    assert g["return_gap"] == pytest.approx(0.007059, abs=1e-6)
    assert g["at_risk"]["weights"]["A"] == pytest.approx(0.117647, abs=1e-4)
    assert g["at_risk"]["ret"] == pytest.approx(0.047059, abs=1e-6)
    assert g["risk_gap"] == pytest.approx(0.0, abs=1e-6)
    assert g["violations"] == []


def test_gaps_hand_numbers_capped():
    a = _t2_set()
    con = Constraints.from_dict({"bounds": {"B": {"max": 0.6}}})
    fr = a.frontier(0.02, constraints=con)
    plan = a.portfolio({"B": 1.0})
    g = fr.gaps(plan)
    assert g["sharpe_gap"] == pytest.approx(0.1150, abs=1e-4)
    assert g["return_gap"] is None and g["risk_gap"] is None
    assert g["at_risk"] is None and g["at_return"] is None
    assert len(g["violations"]) == 1 and "B 100.0%" in g["violations"][0]
    # frontier runs from the capped min-vol to the capped max return
    assert fr.min_vol.dispersion == pytest.approx(0.08544, abs=1e-4)
    assert fr.points[-1].expected_return == pytest.approx(0.10, abs=1e-6)
    d = fr.to_dict()
    assert d["constraints"]["bounds"] == {"B": {"min": 0.0, "max": 0.6}}
    assert fr.tangency.weights["B"] == pytest.approx(0.6, abs=1e-6)


def test_gaps_zero_at_the_tangency():
    a = _t2_set()
    for con in (None, Constraints.from_dict({"bounds": {"B": {"max": 0.6}}})):
        fr = a.frontier(0.02, constraints=con)
        g = fr.gaps(fr.tangency)
        assert g["sharpe_gap"] == pytest.approx(0, abs=1e-6)
        assert g["return_gap"] == pytest.approx(0, abs=1e-5)
        assert g["risk_gap"] == pytest.approx(0, abs=1e-5)


def test_gaps_null_without_tangency():
    a = _t2_set()
    fr = a.frontier(0.5, constraints=Constraints.from_dict({}))
    assert fr.tangency is None
    assert fr.gaps(a.portfolio({"B": 1.0}))["sharpe_gap"] is None


def test_model_equals_engine_constrained():
    a = _t2_set()
    con = Constraints.from_dict({"bounds": {"B": {"max": 0.6}, "ZZZ": {"max": .1}}})
    res = con.resolve(a.tickers)
    assert res.ignored == ("ZZZ",)
    w = _constrained_tangency(a.expected_returns, a.risk_matrix, 0.02, res)
    np.testing.assert_allclose(a.tangency(0.02, con).weight_array, w)
    np.testing.assert_allclose(a.min_vol(con).weight_array,
                               _solve(a.expected_returns, a.risk_matrix,
                                      "min_volatility", res))
    assert a.frontier(0.02, constraints=con).to_dict()["constraints"]["ignored"] \
        == ["ZZZ"]


def test_analysis_with_constraints_adds_gaps_only():
    p = _prices()
    a = AssetSet(p, rf_history=_rf(p), rf_level=0.03,
                 prior=Prior("equilibrium", "A"))
    base = a.analysis(risk_free_rate=0.03)
    out = a.analysis(risk_free_rate=0.03, constraints=Constraints.from_dict(
        {"bounds": {"C": {"max": 0.2}}}))
    assert out["tangency"]["weights"].get("C", 0) <= 0.2 + 1e-6
    assert set(out) - set(base) == {"gaps", "constraints"}
    assert base["prior_note"]["reference"] == "A"


def test_infeasible_limits_through_model():
    a = _t2_set()
    con = Constraints.from_dict({"bounds": {"A": {"min": 0.7}, "B": {"min": 0.7}}})
    with pytest.raises(ValueError, match="These limits can't all hold"):
        a.frontier(0.02, constraints=con)
