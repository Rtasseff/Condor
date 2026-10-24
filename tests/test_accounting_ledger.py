"""Ledger v2 engine (ADR 0005): hand-checked cases from the handoff
acceptance table (synthetic broker_a / tesoro fixture numbers)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from condor import accounting as acct

COLS = acct.EVENT_COLUMNS


def frame(rows):
    """rows: (date, kind, ticker, shares, price, amount, fees, maturity)"""
    return pd.DataFrame(rows, columns=COLS)


BROKER_A = [
    ("2027-01-04", "deposit", None, None, None, 1000, 0, None),
    ("2027-01-05", "buy", "AAA", 2.5, 100, None, 1.00, None),
    ("2027-01-05", "buy", "BBB", 10, 20, None, 0, None),
    ("2027-02-01", "buy", "AAA", 1.25, 80, None, 0, None),
    ("2027-02-15", "dividend", "AAA", None, None, 3.00, 0, None),
    ("2027-03-01", "sell", "AAA", 1.5, 110, None, 0.50, None),
    ("2027-03-02", "interest", None, None, None, 1.20, 0, None),
    ("2027-03-03", "fee", None, None, None, 2.00, 0, None),
    ("2027-03-10", "withdraw", None, None, None, 100, 0, None),
]
# state after each prefix: cash, contrib, income total, realized total
STEPS = [(1000.00, 1000.0, 0, 0), (749.00, 1000.0, 0, 0),
         (549.00, 1000.0, 0, 0), (449.00, 1000.0, 0, 0),
         (452.00, 1000.0, 3.00, 0), (616.50, 1000.0, 3.00, 24.10),
         (617.70, 1000.0, 4.20, 24.10), (615.70, 1000.0, 4.20, 24.10),
         (515.70, 900.0, 4.20, 24.10)]


@pytest.mark.parametrize("n", range(1, 10))
def test_broker_a_state_after_each_event(n):
    s = acct.ledger_state(frame(BROKER_A[:n]))
    cash, contrib, income, realized = STEPS[n - 1]
    assert s.cash == pytest.approx(cash)
    assert s.contributions == pytest.approx(contrib)
    assert sum(s.income.values()) == pytest.approx(income)
    assert sum(s.realized.values()) == pytest.approx(realized)


def test_broker_a_positions():
    s = acct.ledger_state(frame(BROKER_A[:2]))
    assert (s.shares["AAA"], s.cost["AAA"], s.avg_cost("AAA")) == \
        pytest.approx((2.5, 251.00, 100.40))
    s = acct.ledger_state(frame(BROKER_A[:4]))
    assert (s.shares["AAA"], s.cost["AAA"], s.avg_cost("AAA")) == \
        pytest.approx((3.75, 351.00, 93.60))
    assert (s.shares["BBB"], s.cost["BBB"], s.avg_cost("BBB")) == \
        pytest.approx((10, 200.00, 20.00))
    s = acct.ledger_state(frame(BROKER_A))
    assert (s.shares["AAA"], s.cost["AAA"], s.avg_cost("AAA")) == \
        pytest.approx((2.25, 210.60, 93.60))
    assert s.avg_cost("ZZZ") == 0.0


def test_broker_a_holdings_and_identity():
    s = acct.ledger_state(frame(BROKER_A))
    h = acct.holdings(s, pd.Series({"AAA": 90.0, "BBB": 22.0}))
    assert h.loc["AAA", "value"] == pytest.approx(202.50)
    assert h.loc["AAA", "unrealized"] == pytest.approx(-8.10)
    assert h.loc["AAA", "unrealized_pct"] == pytest.approx(-0.0385, abs=5e-5)
    assert h.loc["BBB", "value"] == pytest.approx(220.00)
    assert h.loc["BBB", "unrealized"] == pytest.approx(20.00)
    assert h.loc["BBB", "unrealized_pct"] == pytest.approx(0.10)
    assert h.loc["AAA", "realized"] == pytest.approx(24.10)
    assert h.loc["AAA", "income"] == pytest.approx(3.00)
    total = float(h["value"].sum()) + s.cash
    assert total == pytest.approx(938.20)
    assert h.loc["AAA", "value"] / total == pytest.approx(0.2158, abs=5e-5)
    assert h.loc["BBB", "value"] / total == pytest.approx(0.2345, abs=5e-5)
    assert (h.loc["AAA", "value"] / total - 0.30) == pytest.approx(-0.0842, abs=5e-5)
    assert (h.loc["BBB", "value"] / total - 0.30) == pytest.approx(-0.0655, abs=5e-5)
    assert s.charges == pytest.approx(2.00)
    assert s.trade_fees == pytest.approx(1.50)
    assert 900.00 + 24.10 + 11.90 + 4.20 - 2.00 == pytest.approx(938.20)
    assert total == pytest.approx(
        s.contributions + sum(s.realized.values())
        + float(h["unrealized"].sum()) + sum(s.income.values()) - s.charges)
    # AAA at 74
    h74 = acct.holdings(s, pd.Series({"AAA": 74.0, "BBB": 22.0}))
    assert h74.loc["AAA", "unrealized_pct"] == pytest.approx(74 / 93.60 - 1)


def test_replay_is_ledger_state_tuple():
    s = acct.ledger_state(frame(BROKER_A))
    assert acct.replay(frame(BROKER_A)) == (s.shares, s.cash, s.contributions)


def test_six_column_frames_still_work():
    six = pd.DataFrame([("2027-01-04", "deposit", None, None, None, 50),
                        ("2027-01-05", "buy", "AAA", 1, 10, None)],
                       columns=COLS[:6])
    shares, cash, contrib = acct.replay(six)
    assert (shares, cash, contrib) == ({"AAA": 1.0}, 40.0, 50.0)


def test_unknown_kind_and_bad_redeem_raise():
    with pytest.raises(ValueError, match="unknown"):
        acct.ledger_state(frame([("2027-01-04", "bogus", None, None, None, 1, 0, None)]))
    with pytest.raises(ValueError, match="not a bill"):
        acct.ledger_state(frame([
            ("2027-01-04", "deposit", None, None, None, 100, 0, None),
            ("2027-01-05", "buy", "AAA", 1, 10, None, 0, None),
            ("2027-01-06", "redeem", "AAA", 1, 1, None, 0, None)]))


# ------------------------------------------------------------- bills

BILL = "LETRA-2028-01-14"
TESORO = [
    ("2027-01-14", "deposit", None, None, None, 970.60, 0, None),
    ("2027-01-14", "buy", BILL, 1000, 0.9706, None, 0, "2028-01-14"),
    ("2028-01-14", "redeem", BILL, 1000, 1, None, 0, None),
]


def bday_closes(start, end):
    return pd.DataFrame(index=pd.bdate_range(start, end))


def test_accrued_value_line():
    lot = acct.BillLot(date(2027, 1, 14), date(2028, 1, 14), 1000, 970.60)
    assert acct.accrued_value(lot, date(2027, 1, 14)) == pytest.approx(970.60)
    assert acct.accrued_value(lot, date(2027, 3, 31)) == pytest.approx(
        970.60 + 29.40 * 76 / 365)
    assert acct.accrued_value(lot, date(2027, 1, 1)) == pytest.approx(970.60)
    assert acct.accrued_value(lot, date(2030, 1, 1)) == pytest.approx(1000)


def test_tesoro_daily_state_hand_values():
    ev = frame(TESORO)
    d = acct.daily_state(ev, bday_closes("2027-01-01", "2028-01-14"))
    v = d["value"]
    assert v[pd.Timestamp("2027-01-14")] == pytest.approx(970.60)
    assert round(v[pd.Timestamp("2027-03-31")], 2) == 976.72
    assert round(v[pd.Timestamp("2027-07-15")], 2) == 985.26
    assert v.iloc[-1] == pytest.approx(1000.00)
    assert d["flow"].sum() == pytest.approx(970.60)
    # TWR: no flows after day one -> 1000/970.60 - 1
    assert acct.time_weighted_return(d) == pytest.approx(
        1000 / 970.60 - 1)
    assert round(acct.time_weighted_return(d) * 100, 4) == 3.0291
    s = acct.ledger_state(ev)
    assert s.cash == pytest.approx(1000.0)
    assert s.realized[BILL] == pytest.approx(29.40)
    assert s.contributions == pytest.approx(970.60)
    assert s.shares == {} and s.bills == {}
    assert acct.bill_tickers(ev) == {BILL}


def test_bill_prices_per_nominal():
    ev = frame(TESORO)
    idx = pd.DatetimeIndex(["2027-01-13", "2027-01-14", "2027-03-31",
                            "2028-01-14", "2028-01-17"])
    bp = acct.bill_prices(ev, idx)[BILL]
    assert bp.iloc[0] == 0.0
    assert bp.iloc[1] == pytest.approx(0.9706)
    assert bp.iloc[2] == pytest.approx((970.60 + 29.40 * 76 / 365) / 1000)
    assert bp.iloc[3] == 0.0      # redeemed that day
    assert bp.iloc[4] == 0.0


def test_bill_pro_rata_sale_keeps_per_nominal_price():
    rows = [
        ("2027-01-04", "deposit", None, None, None, 2000, 0, None),
        ("2027-01-04", "buy", BILL, 600, 0.96, None, 0, "2028-01-14"),
        ("2027-04-05", "buy", BILL, 400, 0.98, None, 0, "2028-01-14"),
        ("2027-06-01", "sell", BILL, 250, 0.99, None, 0, None),
    ]
    ev = frame(rows)
    before = acct.ledger_state(ev.iloc[:3])
    after = acct.ledger_state(ev)
    assert [l.nominal for l in before.bills[BILL]] == [600, 400]
    # 250 of 1000 sold -> every lot keeps 75%
    assert [l.nominal for l in after.bills[BILL]] == pytest.approx([450, 300])
    assert [l.cost for l in after.bills[BILL]] == pytest.approx(
        [576 * .75, 392 * .75])
    assert after.shares[BILL] == pytest.approx(750)
    avg = (576 + 392) / 1000
    assert after.realized[BILL] == pytest.approx(250 * 0.99 - avg * 250)
    on = pd.DatetimeIndex(["2027-06-01"])
    bp = acct.bill_prices(ev, on)[BILL]
    no_sale = acct.bill_prices(ev.iloc[:3], on)[BILL]
    assert bp.iloc[0] == pytest.approx(no_sale.iloc[0])  # price unchanged by the sale
    assert bp.iloc[0] == pytest.approx(
        sum(acct.accrued_value(l, date(2027, 6, 1))
            for l in after.bills[BILL]) / 750)


def test_daily_state_ignores_missing_bill_close_but_not_stocks():
    ev = frame(TESORO[:2])
    acct.daily_state(ev, bday_closes("2027-01-01", "2027-02-01"))
    stock = frame([("2027-01-04", "deposit", None, None, None, 50, 0, None),
                   ("2027-01-05", "buy", "AAA", 1, 10, None, 0, None)])
    with pytest.raises(KeyError):
        acct.daily_state(stock, bday_closes("2027-01-01", "2027-02-01"))


# ------------------------------------------------- return, identity

def twr(rows):
    d = acct.daily_state(frame(rows), bday_closes("2027-01-04", "2027-01-08"))
    return acct.time_weighted_return(d)


def test_twr_counts_income_and_fees():
    dep = ("2027-01-04", "deposit", None, None, None, 1000, 0, None)
    inc = ("2027-01-06", "interest", None, None, None, 10, 0, None)
    assert twr([dep, inc]) == pytest.approx(0.01)
    assert twr([("2027-01-04", "deposit", None, None, None, 1000, 0, None),
                ("2027-01-06", "deposit", None, None, None, 10, 0, None)]) == \
        pytest.approx(0.0)
    fee = ("2027-01-06", "fee", None, None, None, 10, 0, None)
    assert twr([dep, fee]) == pytest.approx(-0.01)


def test_identity_with_forces():
    rows = [
        ("2027-01-04", "deposit", None, None, None, 500, 0, None),
        ("2027-01-05", "set_shares", "AAA", 10, 20, None, 0, None),   # +200 in kind
        ("2027-01-06", "buy", "AAA", 5, 30, None, 2, None),           # cost 152
        ("2027-01-07", "set_shares", "AAA", 9, 40, None, 0, None),    # out 6 @40
        ("2027-01-08", "set_cash", None, None, None, 480, 0, None),   # -> delta -? 
        ("2027-01-08", "dividend", "AAA", None, None, 10, 1, None),
    ]
    ev = frame(rows)
    s = acct.ledger_state(ev)
    # hand: cash 500 -> 350 after buy(150+2) -> set_cash 480 (+130 contrib) -> +9
    assert s.cash == pytest.approx(489.0)
    # avg before force-out = (200+152)/15; realized = 6*(40-avg)
    avg = 352 / 15
    assert s.realized["AAA"] == pytest.approx(6 * (40 - avg))
    assert s.cost["AAA"] == pytest.approx(352 - 6 * avg)
    px = pd.Series({"AAA": 45.0})
    h = acct.holdings(s, px)
    value = float(h["value"].sum()) + s.cash
    assert value == pytest.approx(
        s.contributions + sum(s.realized.values())
        + float(h["unrealized"].sum()) + sum(s.income.values()) - s.charges)
    assert s.charges == pytest.approx(1.0)
