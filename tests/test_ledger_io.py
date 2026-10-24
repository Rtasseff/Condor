"""Ledger exchange format v1 (condor/ledger_io.py): the synthetic fixture
and one failing case per validation rule."""

import io
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from condor import accounting as acct
from condor.ledger_io import (LedgerFormatError, read_ledger, read_targets,
                              write_ledger)

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2028, 12, 31)
HEAD = "date,account,ticker,side,qty,price,fees,ccy,maturity,note\n"
DEP = "2027-01-04,a,CASH,DEPOSIT,1000,1,0,USD,,\n"


def parse(body, today=TODAY, head=HEAD):
    return read_ledger(io.StringIO(head + body), today=today)


def errors(body, **kw):
    with pytest.raises(LedgerFormatError) as e:
        parse(body, **kw)
    return e.value.errors


def test_fixture_parses_into_two_accounts():
    got = read_ledger(FIX / "ledger_sample.csv", today=TODAY)
    assert list(got) == ["broker_a", "tesoro"]
    assert got["broker_a"].currency == "USD"
    assert got["tesoro"].currency == "EUR"
    assert len(got["broker_a"].events) == 9 and len(got["tesoro"].events) == 3
    assert list(got["broker_a"].events.columns) == acct.EVENT_COLUMNS + ["note"]
    s = acct.ledger_state(got["broker_a"].events)
    assert s.cash == pytest.approx(515.70)
    t = acct.ledger_state(got["tesoro"].events)
    assert t.cash == pytest.approx(1000.0)
    assert read_targets(FIX / "ledger_sample_targets.csv") == {
        "broker_a": {"AAA": 0.3, "BBB": 0.3}}


def test_fixture_is_in_the_past_only_after_its_dates():
    assert any("future" in m for m in errors(
        open(FIX / "ledger_sample.csv").read().split("\n", 1)[1],
        today=date(2027, 6, 1)))


def test_round_trip_equal_frames():
    got = read_ledger(FIX / "ledger_sample.csv", today=TODAY)
    buf = io.StringIO()
    write_ledger([(k, v.currency, v.events) for k, v in got.items()], buf)
    again = read_ledger(io.StringIO(buf.getvalue()), today=TODAY)
    assert list(again) == list(got)
    for k in got:
        assert again[k].currency == got[k].currency
        pd.testing.assert_frame_equal(again[k].events, got[k].events)
    assert "970.6," in buf.getvalue() and ",0.9706," in buf.getvalue()


def test_write_refuses_forces():
    ev = pd.DataFrame([("2027-01-04", "set_cash", None, None, None, 5)],
                      columns=acct.EVENT_COLUMNS[:6])
    with pytest.raises(ValueError, match="2027-01-04"):
        write_ledger([("a", "USD", ev)], io.StringIO())


@pytest.mark.parametrize("head", [
    "date,account,ticker,side,qty,price,fees,ccy,maturity\n",
    HEAD.strip() + ",extra\n",
    "date,account,ticker,side,qty,price,fees,ccy,maturity,notes\n"])
def test_header_must_be_exact(head):
    with pytest.raises(LedgerFormatError) as e:
        read_ledger(io.StringIO(head), today=TODAY)
    assert e.value.errors[0].startswith("line 1:")


BAD = {   # rule -> (row, text expected in the message)
    "date format": ("27-01-04,a,CASH,DEPOSIT,1000,1,0,USD,,\n", "ISO date"),
    "future": ("2030-01-04,a,CASH,DEPOSIT,1000,1,0,USD,,\n", "future"),
    "label": ("2027-01-04,Acct 1,CASH,DEPOSIT,1000,1,0,USD,,\n", "account"),
    "side": ("2027-01-04,a,CASH,GIFT,1000,1,0,USD,,\n", "side"),
    "qty zero": ("2027-01-04,a,CASH,DEPOSIT,0,1,0,USD,,\n", "qty must be > 0"),
    "qty negative": ("2027-01-04,a,CASH,DEPOSIT,-5,1,0,USD,,\n", "qty"),
    "thousands": ("2027-01-04,a,CASH,DEPOSIT,\"1,000\",1,0,USD,,\n", "qty"),
    "price zero": ("2027-01-04,a,CASH,DEPOSIT,10,0,0,USD,,\n", "price"),
    "cash price": ("2027-01-04,a,CASH,DEPOSIT,10,2,0,USD,,\n", "exactly 1"),
    "fees on deposit": ("2027-01-04,a,CASH,DEPOSIT,10,1,1,USD,,\n", "fees"),
    "fees on fee": ("2027-01-04,a,CASH,FEE,10,1,1,USD,,\n", "fees"),
    "ccy": ("2027-01-04,a,CASH,DEPOSIT,10,1,0,usd,,\n", "ccy"),
    "deposit ticker": ("2027-01-04,a,AAA,DEPOSIT,10,1,0,USD,,\n", "CASH"),
    "buy cash": ("2027-01-04,a,CASH,BUY,1,1,0,USD,,\n", "BUY"),
    "div on cash": ("2027-01-04,a,CASH,DIV,1,1,0,USD,,\n", "DIV"),
    "ticker shape": ("2027-01-04,a,aaa!,BUY,1,1,0,USD,,\n", "ticker"),
    "decimals": (DEP + "2027-01-05,a,AAA,BUY,0.1234567,1,0,USD,,\n",
                 "6 decimals"),
    "maturity on stock": (DEP + "2027-01-05,a,AAA,BUY,1,1,0,USD,2028-01-14,\n",
                          "maturity"),
    "bill without maturity": (DEP + "2027-01-05,a,LETRA-2028-01-14,BUY,100,0.9,0,USD,,\n",
                              "needs a maturity"),
    "maturity mismatch": (DEP + "2027-01-05,a,LETRA-2028-01-14,BUY,100,0.9,0,USD,2028-02-14,\n",
                          "differs"),
    "bill on deposit": ("2027-01-04,a,LETRA-2028-01-14,DEPOSIT,10,1,0,USD,,\n",
                        "bill"),
    "redeem non-bill": (DEP + "2027-01-05,a,AAA,REDEEM,1,1,0,USD,,\n", "REDEEM"),
    "note identifier": ("2027-01-04,a,CASH,DEPOSIT,10,1,0,USD,,acct 12345678\n",
                        "identifier"),
    "note long": ("2027-01-04,a,CASH,DEPOSIT,10,1,0,USD,," + "x" * 121 + "\n",
                  "120"),
    "column count": ("2027-01-04,a,CASH,DEPOSIT,10\n", "columns"),
    "date order": (DEP + "2027-01-03,a,CASH,DEPOSIT,10,1,0,USD,,\n",
                   "backwards"),
    "mixed ccy": (DEP + "2027-01-05,a,CASH,DEPOSIT,10,1,0,EUR,,\n", "mixes"),
    "negative cash": (DEP + "2027-01-05,a,AAA,BUY,11,100,0,USD,,\n", "cash"),
    "negative position": (DEP + "2027-01-05,a,AAA,BUY,1,10,0,USD,,\n"
                          "2027-01-06,a,AAA,SELL,2,10,0,USD,,\n", "negative position"),
    "redeem early": (DEP + "2027-01-05,a,LETRA-2028-01-14,BUY,1000,0.9,0,USD,2028-01-14,\n"
                     "2027-06-01,a,LETRA-2028-01-14,REDEEM,1000,1,0,USD,,\n",
                     "before maturity"),
    "redeem too much": (DEP + "2027-01-05,a,LETRA-2028-01-14,BUY,1000,0.9,0,USD,2028-01-14,\n"
                        "2028-01-14,a,LETRA-2028-01-14,REDEEM,1001,1,0,USD,,\n",
                        "nominal held"),
}


@pytest.mark.parametrize("rule", BAD)
def test_each_rule_reports_line_prefixed_error(rule):
    row, text = BAD[rule]
    errs = errors(row)
    assert all(e.startswith("line ") for e in errs)
    assert any(text in e for e in errs), errs
    # the offending row is on line 2 (or later when a deposit precedes it)
    n_before = row.count("\n") - 1
    assert any(e.startswith(f"line {2 + n_before}:") for e in errs), errs


def test_multiple_bad_rows_all_reported():
    errs = errors("27-01-04,a,CASH,DEPOSIT,1000,1,0,USD,,\n"
                  "2027-01-04,a,CASH,DEPOSIT,-1,1,0,USD,,\n"
                  "2027-01-04,b,CASH,GIFT,1,1,0,USD,,\n")
    assert [e.split(":")[0] for e in errs] == ["line 2", "line 3", "line 4"]


def test_no_partial_results_on_error():
    with pytest.raises(LedgerFormatError):
        parse(DEP + "2027-01-05,a,CASH,GIFT,1,1,0,USD,,\n")


def test_same_day_rows_keep_file_order():
    got = parse(DEP + "2027-01-05,a,AAA,BUY,1,10,0,USD,,x\n"
                "2027-01-05,a,AAA,SELL,1,12,0,USD,,y\n")
    assert list(got["a"].events["kind"]) == ["deposit", "buy", "sell"]


@pytest.mark.parametrize("body,text", [
    ("a,AAA,0.7\na,BBB,0.5\n", "sum"),
    ("a,AAA,1.5\n", "[0, 1]"),
    ("a,AAA,0.5\na,AAA,0.2\n", "duplicate"),
    ("a,LETRA-2028-01-14,0.5\n", "ticker"),
    ("a,AAA,x\n", "weight"),
    ("A!,AAA,0.5\n", "account"),
])
def test_targets_errors(body, text):
    with pytest.raises(LedgerFormatError) as e:
        read_targets(io.StringIO("account,ticker,weight\n" + body))
    assert any(text in m for m in e.value.errors)
    assert all(m.startswith("line ") for m in e.value.errors)


def test_targets_header_exact():
    with pytest.raises(LedgerFormatError):
        read_targets(io.StringIO("account,ticker\n"))
