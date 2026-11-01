"""Broker reconciliation (handoff broker-reconcile): hand-checked,
synthetic numbers. Brokers book each event to the cent; the exact engine
(`ledger_state`) must not move."""

import pandas as pd
import pytest

from condor import accounting as acct

COLS = acct.EVENT_COLUMNS


def frame(rows):
    return pd.DataFrame(rows, columns=COLS)


def e(kind, ticker=None, shares=None, price=None, amount=None, fees=0,
      maturity=None, day="2027-01-05"):
    return (day, kind, ticker, shares, price, amount, fees, maturity)


LEDGER = frame([
    e("deposit", amount=200, day="2027-01-04"),
    e("buy", "AAA", 1, 80.355),
    e("buy", "BBB", 18, 2.18),
    e("dividend", "AAA", amount=15.75, day="2027-02-01"),
    e("interest", amount=0.01, day="2027-02-02"),
])
PRICES = pd.Series({"AAA": 76.83, "BBB": 2.21})


def test_booked_cash_walk_and_exact_engine_unchanged():
    assert acct.broker_cash(LEDGER.iloc[:1]) == 200
    assert acct.broker_cash(LEDGER.iloc[:2]) == pytest.approx(119.64)
    assert acct.broker_cash(LEDGER.iloc[:3]) == pytest.approx(80.40)
    assert acct.broker_cash(LEDGER.iloc[:4]) == pytest.approx(96.15)
    assert acct.broker_cash(LEDGER) == pytest.approx(96.16)
    st = acct.ledger_state(LEDGER)
    assert st.cash == pytest.approx(96.165)
    assert st.cost["AAA"] == pytest.approx(80.355)


def test_expected_values():
    r = acct.reconcile(LEDGER, PRICES)
    assert r["cash"] == pytest.approx(96.16)
    assert [(p["ticker"], p["value"]) for p in r["positions"]] == [
        ("AAA", 76.83), ("BBB", 39.78)]
    assert r["securities"] == pytest.approx(116.61)
    assert r["value"] == pytest.approx(212.77)
    assert r["cash_check"] is None and r["value_check"] is None
    assert r["securities_check"] is None


def test_checks():
    r = acct.reconcile(LEDGER, PRICES, 96.16, 212.77, 116.61)
    assert r["cash_check"]["match"] and r["value_check"]["match"]
    assert r["securities_check"]["match"]
    r = acct.reconcile(LEDGER, PRICES, reported_cash=80.40)
    assert r["cash_check"]["difference"] == pytest.approx(-15.76)
    assert not r["cash_check"]["match"]
    r = acct.reconcile(LEDGER, PRICES, reported_cash=96.17)
    assert r["cash_check"]["difference"] == pytest.approx(0.01)
    assert not r["cash_check"]["match"]
    r = acct.reconcile(LEDGER, PRICES, reported_securities=116.71)
    assert r["securities_check"]["difference"] == pytest.approx(0.10)
    assert not r["securities_check"]["match"]


def test_value_tolerance_is_per_position_plus_a_cent():
    # two positions: within 0.03 matches, 0.04 does not
    assert acct.reconcile(LEDGER, PRICES, reported_value=212.80)[
        "value_check"]["match"]
    assert not acct.reconcile(LEDGER, PRICES, reported_value=212.81)[
        "value_check"]["match"]


@pytest.mark.parametrize("rows,want", [
    ([e("buy", "X", 1, 1.005)], -1.01),
    ([e("buy", "X", 3, 1.115)], -3.35),
    ([e("set_cash", amount=0), e("sell", "X", 1.5, 33.333)], 50.00),
    ([e("buy", "X", 2.5, 100, fees=1)], -251.00),
    ([e("sell", "X", 1.5, 110, fees=0.50)], 164.50),
    ([e("dividend", "X", amount=1.005)], 1.01),
    ([e("fee", amount=2.675)], -2.68),
    ([e("withdraw", amount=0.125)], -0.13),
])
def test_half_up_on_exact_decimals(rows, want):
    assert acct.broker_cash(frame(rows)) == pytest.approx(want)


def test_close_noise():
    assert float(acct.shown_close(101.199997)) == 101.20
    assert float(acct.shown_close(0.87654)) == 0.8765


def test_set_cash_then_events_and_set_shares():
    ev = frame([e("deposit", amount=500), e("set_cash", amount=100.004),
                e("set_shares", "X", 3, 10), e("deposit", amount=0.5)])
    assert acct.broker_cash(ev) == pytest.approx(100.50)


def test_bill_uses_accreted_value_and_redeem_credits_nominal():
    ev = frame([e("deposit", amount=1000, day="2027-01-01"),
                e("buy", "BILL", 10, 0.98, maturity="2027-07-01",
                  day="2027-01-01")])
    px = acct.bill_prices(ev, pd.DatetimeIndex(["2027-04-01"])).iloc[0]
    r = acct.reconcile(ev, px)
    # the exact accreted price, not a display-rounded one
    assert r["positions"][0]["value"] == pytest.approx(
        round(10 * px["BILL"], 2))
    assert r["positions"][0]["is_bill"]
    assert 9.8 < r["securities"] < 10.0
    ev2 = pd.concat([ev, frame([e("redeem", "BILL", 10, 1.0,
                                  day="2027-07-01")])], ignore_index=True)
    assert acct.broker_cash(ev2) == pytest.approx(1000 - 9.80 + 10.0)
    assert acct.reconcile(ev2, px)["positions"] == []


def test_missing_price_raises():
    with pytest.raises(ValueError):
        acct.reconcile(LEDGER, pd.Series({"AAA": 1.0}))


def test_bill_value_rounds_nominal_times_exact_price_not_the_price():
    """10,000 nominal at accreted 0.97994475 is 9,799.4475 -> 9,799.45.
    Rounding the price to 4 dp first (0.9799) would give 9,799.00, which
    is wrong: a broker values the bill, not a rounded quote."""
    ev = frame([e("deposit", amount=20000, day="2027-01-01"),
                e("buy", "BILL", 10000, 0.97, maturity="2027-07-01",
                  day="2027-01-01")])
    r = acct.reconcile(ev, pd.Series({"BILL": 0.97994475}))
    assert r["positions"][0]["value"] == 9799.45
    assert r["securities"] == 9799.45


def test_no_prices_still_checks_cash():
    r = acct.reconcile(LEDGER, None, reported_cash=96.16, reported_value=1)
    assert r["cash_check"]["match"]
    assert r["securities"] is None and r["value"] is None
    assert r["positions"] is None and r["value_check"] is None


def test_rounding_flags():
    r = acct.reconcile(LEDGER, PRICES)
    assert r["rounding"]["cash"] is True       # 96.16 booked vs 96.165 exact
    assert r["rounding"]["prices"] is False
    ev = frame([e("deposit", amount=100, day="2027-01-04"),
                e("buy", "X", 3, 10.0)])
    r = acct.reconcile(ev, pd.Series({"X": 10.0}))
    assert r["rounding"] == {"cash": False, "prices": False}
    r = acct.reconcile(ev, pd.Series({"X": 10.004}))   # 30.012 exact, 30.00 shown
    assert r["rounding"] == {"cash": False, "prices": True}


def test_precomputed_state_gives_same_answer():
    st = acct.ledger_state(LEDGER)
    assert acct.reconcile(LEDGER, PRICES, state=st,
                          bills=acct.bill_tickers(LEDGER)) \
        == acct.reconcile(LEDGER, PRICES)
