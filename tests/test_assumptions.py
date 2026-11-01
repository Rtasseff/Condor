"""Assumptions object: round trip, validation (one test per rule), resolve."""

import copy

import pytest

from condor.assumptions import Assumptions, Constraints, Group

FULL = {
    "name": "Mine",
    "prior": {"kind": "equilibrium", "reference": "VT", "market_premium": None,
              "t0": 20, "views": [{"ticker": "AAA", "ret": 0.10, "sd": 0.05}]},
    "constraints": {"bounds": {"AAA": {"min": 0.05, "max": 0.30}},
                    "groups": [{"tickers": ["AAA", "BBB"], "max": 0.40}]},
}


def test_round_trip_exact():
    assert Assumptions.from_dict(FULL).to_dict() == FULL


def test_defaults_fill_in():
    a = Assumptions.from_dict({"name": "x"})
    assert a.prior.kind == "equilibrium" and a.prior.reference == "VT"
    assert a.prior.t0 == 20 and a.prior.market_premium is None
    assert a.constraints.bounds == {} and a.constraints.groups == ()


def test_min_max_defaults():
    a = Assumptions.from_dict({"name": "x", "constraints": {
        "bounds": {"AAA": {"max": 0.3}, "BBB": {"min": 0.1}},
        "groups": [{"tickers": ["AAA"], "min": 0.1}]}})
    assert a.constraints.bounds == {"AAA": (0.0, 0.3), "BBB": (0.1, 1.0)}
    assert a.constraints.groups[0] == Group(("AAA",), 0.1, 1.0)


def _bad(mutate, match):
    d = copy.deepcopy(FULL)
    mutate(d)
    with pytest.raises(ValueError, match=match):
        Assumptions.from_dict(d)


def test_validation_rules():
    _bad(lambda d: d.update(name=""), "name")
    _bad(lambda d: d.update(name="x" * 81), "name")
    _bad(lambda d: d.__setitem__("prior", {"kind": "wild"}), "prior.kind")
    _bad(lambda d: d["prior"].update(t0=-1), "prior.t0")
    _bad(lambda d: d["prior"].update(market_premium=-0.01), "market_premium")
    _bad(lambda d: d["prior"].update(reference=""), "reference")
    _bad(lambda d: d["prior"]["views"][0].update(sd=0), "sd")
    _bad(lambda d: d["prior"]["views"][0].update(sd=-1), "sd")
    _bad(lambda d: d["prior"]["views"][0].update(ret="x"), "ret")
    _bad(lambda d: d["prior"].update(views=[
        {"ticker": f"T{i}", "ret": 0.1, "sd": 0.1} for i in range(16)]), "views")
    _bad(lambda d: d["prior"]["views"].append(
        {"ticker": "AAA", "ret": 0.1, "sd": 0.1}), "one view")
    _bad(lambda d: d["constraints"]["bounds"]["AAA"].update(max=1.5),
         "bounds.AAA.max")
    _bad(lambda d: d["constraints"]["bounds"]["AAA"].update(min=-0.1),
         "bounds.AAA.min")
    _bad(lambda d: d["constraints"]["bounds"]["AAA"].update(min=0.4, max=0.3),
         "min is above max")
    _bad(lambda d: d["constraints"]["groups"][0].update(min=0.5, max=0.4),
         "min is above max")
    _bad(lambda d: d["constraints"]["groups"][0].update(max=2), "groups\\[0\\].max")
    _bad(lambda d: d["constraints"]["groups"][0].update(tickers=[]), "tickers")
    _bad(lambda d: d["constraints"].update(
        groups=[{"tickers": ["A"]} for _ in range(21)]), "groups")
    _bad(lambda d: d["constraints"].update(bounds=[]), "bounds")
    _bad(lambda d: d["prior"].update(reference="NOT A TICKER!"), "ticker symbol")
    _bad(lambda d: d["constraints"]["bounds"].update({"A B": {}}), "ticker symbol")
    _bad(lambda d: d["constraints"].update(
        bounds={f"T{i}": {} for i in range(51)}), "bounds")
    with pytest.raises(ValueError, match="assumptions"):
        Assumptions.from_dict([])


def test_max_sizes_allowed():
    d = {"name": "x", "prior": {"views": [
        {"ticker": f"T{i}", "ret": 0.1, "sd": 0.1} for i in range(15)]},
        "constraints": {"groups": [{"tickers": ["A"]} for _ in range(20)]}}
    Assumptions.from_dict(d)


def test_resolve_ignores_absent_tickers():
    c = Assumptions.from_dict(FULL).constraints
    r = c.resolve(["BBB", "AAA", "CCC"])
    assert r.bounds == ((0.0, 1.0), (0.05, 0.30), (0.0, 1.0))
    assert r.groups == (((1, 0), 0.0, 0.40),)
    assert r.ignored == ()
    r = c.resolve(["BBB", "CCC"])           # AAA missing: bound ignored,
    assert r.groups == (((0,), 0.0, 0.40),)  # group keeps BBB
    assert r.ignored == ("AAA",)
    r = c.resolve(["CCC"])                  # group has no members left
    assert r.groups == () and r.ignored == ("AAA", "group AAA + BBB")


def test_violations_in_words():
    c = Constraints.from_dict({"bounds": {"GLDM": {"max": 0.15},
                                          "AAA": {"min": 0.10}},
                               "groups": [{"tickers": ["AAA", "BBB"],
                                           "max": 0.40}]})
    w = {"GLDM": 0.20, "AAA": 0.05, "BBB": 0.50}
    v = c.violations(w)
    assert "GLDM 20.0% is above its 15.0% limit" in v
    assert "AAA 5.0% is below its 10.0% minimum" in v
    assert any("AAA + BBB together 55.0%" in s for s in v)
    assert c.violations({"GLDM": 0.15, "AAA": 0.1, "BBB": 0.3}) == []
    assert c.violations({"ZZZ": 1.0}) == []
