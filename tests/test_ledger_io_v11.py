"""Ledger exchange format v1.1 readers (condor/ledger_io.py): targets with
timing/line, payin.csv, rules.csv, on the fixture and one failing case per
validation rule."""

import io
from datetime import date
from pathlib import Path

import pytest

from condor.ledger_io import (LedgerFormatError, PayInSpec, RuleSpec,
                              TargetSpec, read_payin, read_rules,
                              read_targets, read_targets_full)

FIX = Path(__file__).parent / "fixtures"
T_HEAD = "account,ticker,weight,timing,line\n"
P_HEAD = "account,total,date\n"
R_HEAD = "account,id,rule,ticker,threshold,action,tranches,target\n"


def bad(fn, text, *want):
    with pytest.raises(LedgerFormatError) as e:
        fn(io.StringIO(text))
    for w in want:
        assert any(w in m for m in e.value.errors), e.value.errors
    assert all(m.startswith("line ") for m in e.value.errors)


def test_targets_full_fixture():
    got = read_targets_full(FIX / "payin_sample_targets.csv")["broker_b"]
    assert list(got) == ["LMP", "RES", "AAA", "BBB", "CCC", "DDD"]
    assert got["LMP"] == TargetSpec(0.2, "lump", "lump")
    assert got["CCC"] == TargetSpec(0.15, "dca", "sleeve")
    assert got["DDD"].line == "sleeve"
    # weights-only wrapper keeps its signature
    assert read_targets(FIX / "payin_sample_targets.csv")["broker_b"][
        "AAA"] == 0.3


def test_v1_targets_default_timing_and_line():
    got = read_targets_full(FIX / "ledger_sample_targets.csv")
    assert got["broker_a"]["AAA"] == TargetSpec(0.3, "", "aaa")


def test_line_defaults_to_lowercase_ticker_when_empty():
    got = read_targets_full(io.StringIO(T_HEAD + "a,BRK.B,0.5,dca,\n"))
    assert got["a"]["BRK.B"] == TargetSpec(0.5, "dca", "brk.b")


@pytest.mark.parametrize("body,text", [
    ("a,AAA,0.5,weekly,\n", "timing"),
    ("a,AAA,0.5,dca,Bad Key\n", "line"),
    ("a,AAA,0.3,reservoir,\na,BBB,0.3,reservoir,\n", "reservoir"),
])
def test_targets_v11_errors(body, text):
    bad(read_targets_full, T_HEAD + body, text)


def test_targets_header_accepts_only_v1_or_v11():
    bad(read_targets_full, "account,ticker,weight,timing\n", "header")


def test_payin_fixture():
    got = read_payin(FIX / "payin_sample_payin.csv")
    assert got == {"broker_b": PayInSpec(1000.0, (
        date(2027, 1, 4), date(2027, 2, 1), date(2027, 3, 1),
        date(2027, 4, 5)))}


def test_payin_future_dates_allowed():
    got = read_payin(io.StringIO(P_HEAD + "a,100,2099-01-01\n"))
    assert got["a"].dates == (date(2099, 1, 1),)


@pytest.mark.parametrize("body,text", [
    ("a,0,2027-01-04\n", "total must be > 0"),
    ("a,x,2027-01-04\n", "total"),
    ("a,100,2027-01-04\na,200,2027-02-01\n", "differs"),
    ("a,100,2027-02-01\na,100,2027-02-01\n", "strictly increase"),
    ("a,100,2027-02-01\na,100,2027-01-04\n", "strictly increase"),
    ("a,100,04/01/2027\n", "ISO date"),
    ("A!,100,2027-01-04\n", "account"),
])
def test_payin_errors(body, text):
    bad(read_payin, P_HEAD + body, text)


def test_rules_fixture():
    got = read_rules(FIX / "payin_sample_rules.csv")["broker_b"]
    assert got == [
        RuleSpec("idx_drawdown", "below_52w_high", "^IDX", 10.0,
                 "accelerate", 2, ()),
        RuleSpec("ccc_below_cost", "below_avg_cost", "CCC", 20.0,
                 "accelerate", 1, ("CCC", "DDD")),
        RuleSpec("drift", "drift", "", 5.0, "alert", None, ())]


@pytest.mark.parametrize("body,text", [
    ("a,r,nope,X,5,alert,,\n", "rule"),
    ("a,r,below_52w_high,,5,alert,,\n", "needs a ticker"),
    ("a,r,below_avg_cost,,5,alert,,\n", "needs a ticker"),
    ("a,r,drift,AAA,5,alert,,\n", "no ticker"),
    ("a,r,drift,,0,alert,,\n", "threshold must be > 0"),
    ("a,r,drift,,x,alert,,\n", "threshold"),
    ("a,r,drift,,5,sell,,\n", "action"),
    ("a,r,drift,,5,accelerate,,\n", "tranches"),
    ("a,r,drift,,5,accelerate,0,\n", "tranches"),
    ("a,r,drift,,5,accelerate,1.5,\n", "tranches"),
    ("a,r,drift,,5,alert,2,\n", "empty on an alert"),
    ("a,r,drift,,5,alert,,lower\n", "target"),
    ("a,r,drift,,5,alert,,AAA AAA\n", "twice"),
    ("a,R!,drift,,5,alert,,\n", "id"),
    ("a,r,drift,,5,alert,," + " ".join(f"T{i:03d}" for i in range(30))
     + "\n", "120 characters"),
    ("a,r,drift,,5,alert,,\na,r,drift,,5,alert,,\n", "duplicate rule id"),
])
def test_rules_errors(body, text):
    bad(read_rules, R_HEAD + body, text)


def test_same_rule_id_in_two_accounts_is_fine():
    got = read_rules(io.StringIO(
        R_HEAD + "a,r,drift,,5,alert,,\nb,r,drift,,5,alert,,\n"))
    assert set(got) == {"a", "b"}
