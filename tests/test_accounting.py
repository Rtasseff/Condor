"""Account engine (condor/accounting.py) — hand-computed verification.

Every number here is checkable with a pencil; the deposit-is-not-return
property is the whole point of the ledger design (ADR 0004).
"""

import numpy as np
import pandas as pd
import pytest

from condor.accounting import (allocation, contribution_plan, daily_state,
                               rebalance_plan, replay, time_weighted_return)


def ev(date, kind, ticker=None, shares=None, price=None, amount=None):
    return {"date": date, "kind": kind, "ticker": ticker,
            "shares": shares, "price": price, "amount": amount}


def frame(*events):
    return pd.DataFrame(list(events))


# ----------------------------------------------------------------------
# replay
# ----------------------------------------------------------------------
class TestReplay:
    def test_cash_and_trades(self):
        shares, cash, contrib = replay(frame(
            ev("2026-01-05", "deposit", amount=1000.0),
            ev("2026-01-06", "buy", "AAA", shares=10, price=50.0),
            ev("2026-02-02", "sell", "AAA", shares=4, price=60.0),
            ev("2026-02-03", "withdraw", amount=100.0),
        ))
        assert shares == {"AAA": 6}
        assert cash == pytest.approx(1000 - 500 + 240 - 100)   # 640
        assert contrib == pytest.approx(900)                    # 1000 - 100

    def test_forces_are_in_kind_contributions(self):
        # forcing shares/cash moves value but books the delta as flow
        shares, cash, contrib = replay(frame(
            ev("2026-01-05", "deposit", amount=100.0),
            ev("2026-01-06", "buy", "AAA", shares=2, price=50.0),
            ev("2026-01-07", "set_shares", "AAA", shares=5, price=40.0),
            ev("2026-01-08", "set_cash", amount=25.0),
        ))
        assert shares == {"AAA": 5}
        assert cash == 25.0
        # 100 deposit + 3 extra shares @40 (120) + cash forced 0 -> 25
        assert contrib == pytest.approx(100 + 120 + 25)

    def test_empty_and_unknown(self):
        assert replay(None) == ({}, 0.0, 0.0)
        with pytest.raises(ValueError):
            replay(frame(ev("2026-01-05", "bribe", amount=1.0)))

    def test_out_of_order_input_is_sorted(self):
        shares, cash, _ = replay(frame(
            ev("2026-01-07", "set_shares", "AAA", shares=1, price=10.0),
            ev("2026-01-05", "buy", "AAA", shares=3, price=10.0),
        ))
        assert shares == {"AAA": 1}         # the later force wins


# ----------------------------------------------------------------------
# daily_state + TWR: injecting money is not a return
# ----------------------------------------------------------------------
class TestHistory:
    @pytest.fixture()
    def closes(self):
        idx = pd.bdate_range("2026-01-05", periods=4)   # Mon..Thu
        return pd.DataFrame({"AAA": [50.0, 50.0, 60.0, 60.0]}, index=idx)

    def test_hand_case(self, closes):
        events = frame(
            ev("2026-01-05", "deposit", amount=1000.0),
            ev("2026-01-06", "buy", "AAA", shares=10, price=50.0),
            ev("2026-01-08", "deposit", amount=1100.0),
        )
        d = daily_state(events, closes)
        # Mon: cash 1000. Tue: 500 cash + 10sh@50. Wed: 500 + 600.
        # Thu: deposit 1100 -> 2200.
        assert d["value"].tolist() == [1000.0, 1000.0, 1100.0, 2200.0]
        assert d["flow"].tolist() == [1000.0, 0.0, 0.0, 1100.0]
        assert d["contributions"].iloc[-1] == 2100.0
        # value more than doubled, but the honest return is 10%
        assert time_weighted_return(d) == pytest.approx(0.10)

    def test_weekend_event_lands_next_trading_day(self, closes):
        d = daily_state(frame(ev("2026-01-03", "deposit", amount=10.0)),
                        closes)  # Saturday
        assert d.index[0] == closes.index[0]
        assert d["value"].iloc[0] == 10.0

    def test_force_shows_as_flow_not_return(self, closes):
        events = frame(
            ev("2026-01-05", "deposit", amount=500.0),
            ev("2026-01-06", "set_shares", "AAA", shares=10, price=50.0),
        )
        d = daily_state(events, closes)
        assert d["value"].tolist() == [500.0, 1000.0, 1100.0, 1100.0]
        assert d["flow"].tolist() == [500.0, 500.0, 0.0, 0.0]
        assert time_weighted_return(d) == pytest.approx(0.10)  # only Wed's move

    def test_events_after_last_close_value_on_last_known_day(self, closes):
        # Saturday deposit + buy, data ends Thursday: the account must
        # still be worth shares x last close + cash, not just the cash.
        events = frame(
            ev("2026-01-10", "deposit", amount=1000.0),      # Saturday
            ev("2026-01-10", "buy", "AAA", shares=10, price=60.0),
        )
        d = daily_state(events, closes)
        assert len(d) == 1
        assert d.index[0] == closes.index[-1]
        assert d["value"].iloc[0] == pytest.approx(400 + 10 * 60.0)
        assert d["flow"].iloc[0] == 1000.0

    def test_empty(self):
        assert daily_state(None, pd.DataFrame()).empty
        assert time_weighted_return(pd.DataFrame({"value": [1.0],
                                                  "flow": [1.0]})) == 0.0


# ----------------------------------------------------------------------
# allocation
# ----------------------------------------------------------------------
class TestAllocation:
    def test_weights_include_cash_in_the_denominator(self):
        a = allocation({"AAA": 10, "BBB": 4}, pd.Series({"AAA": 60.0, "BBB": 100.0}),
                       cash=0.0)
        assert a.loc["AAA", "weight"] == pytest.approx(0.6)
        assert a.loc["BBB", "weight"] == pytest.approx(0.4)
        b = allocation({"AAA": 10}, pd.Series({"AAA": 60.0}), cash=400.0)
        assert b.loc["AAA", "weight"] == pytest.approx(0.6)

    def test_missing_price_raises(self):
        with pytest.raises(KeyError):
            allocation({"AAA": 1}, pd.Series(dtype=float), cash=0.0)


# ----------------------------------------------------------------------
# rebalance_plan
# ----------------------------------------------------------------------
class TestRebalancePlan:
    def test_first_investment_with_cash_trim(self):
        # 1000 cash, target 60/40 at prices 99/52: nearest-share plan
        # (6, 8) costs 1010 > 1000, so the biggest buy (B: 416) trims.
        plan = rebalance_plan({}, pd.Series({"AAA": 99.0, "BBB": 52.0}),
                              cash=1000.0,
                              target_weights=pd.Series({"AAA": 0.6, "BBB": 0.4}))
        r = plan["rows"]
        assert r.loc["AAA", "trade_shares"] == 6
        assert r.loc["BBB", "trade_shares"] == 7
        assert plan["cash_after"] == pytest.approx(1000 - 6 * 99 - 7 * 52)
        assert plan["cash_after"] >= 0

    def test_drift_back_to_setpoint(self):
        # A drifted rich: 10sh@100 vs 10sh@50, target 50/50 of 1500.
        plan = rebalance_plan({"AAA": 10, "BBB": 10},
                              pd.Series({"AAA": 100.0, "BBB": 50.0}),
                              cash=0.0,
                              target_weights=pd.Series({"AAA": 0.5, "BBB": 0.5}))
        r = plan["rows"]
        # delta A = -250 -> rint(-2.5) = -2; delta B = +250 -> +5,
        # but 5 buys (250) > 200 raised, so B trims to 4.
        assert r.loc["AAA", "trade_shares"] == -2
        assert r.loc["BBB", "trade_shares"] == 4
        assert plan["cash_after"] == pytest.approx(0.0)
        assert r.loc["AAA", "new_weight"] == pytest.approx(800 / 1500)

    def test_cal_target_leaves_cash(self):
        # CAL-style draft: weights sum to 0.6, cash target 0.4
        plan = rebalance_plan({}, pd.Series({"AAA": 10.0}), cash=1000.0,
                              target_weights=pd.Series({"AAA": 0.6}))
        assert plan["target_cash_weight"] == pytest.approx(0.4)
        assert plan["rows"].loc["AAA", "trade_shares"] == 60
        assert plan["cash_after"] == pytest.approx(400.0)

    def test_never_sells_short_and_validates(self):
        plan = rebalance_plan({"AAA": 1}, pd.Series({"AAA": 10.0, "BBB": 10.0}),
                              cash=0.0, target_weights=pd.Series({"BBB": 1.0}))
        assert plan["rows"].loc["AAA", "trade_shares"] == -1   # all of it, no more
        with pytest.raises(ValueError):
            rebalance_plan({}, pd.Series({"AAA": 1.0}), 0.0,
                           pd.Series({"AAA": 1.2}))
        with pytest.raises(ValueError):
            rebalance_plan({}, pd.Series({"AAA": 1.0}), 0.0,
                           pd.Series({"AAA": -0.1}))
        with pytest.raises(KeyError):
            rebalance_plan({"ZZZ": 1}, pd.Series({"AAA": 1.0}), 0.0,
                           pd.Series({"AAA": 1.0}))

    def test_already_at_target_is_a_no_op(self):
        plan = rebalance_plan({"AAA": 6, "BBB": 4},
                              pd.Series({"AAA": 100.0, "BBB": 100.0}),
                              cash=0.0,
                              target_weights=pd.Series({"AAA": 0.6, "BBB": 0.4}))
        assert (plan["rows"]["trade_shares"] == 0).all()


# ----------------------------------------------------------------------
# contribution_plan (DCA: buys only)
# ----------------------------------------------------------------------
class TestContributionPlan:
    def test_fresh_account_splits_by_weights(self):
        # $350 to a 50/50 target at prices 100/50: A2 (200) + B3 (150),
        # every dollar deployed, deterministic greedy order.
        plan = contribution_plan({}, pd.Series({"AAA": 100.0, "BBB": 50.0}),
                                 cash=0.0,
                                 target_weights=pd.Series({"AAA": 0.5, "BBB": 0.5}),
                                 amount=350.0)
        r = plan["rows"]
        assert r.loc["AAA", "buy_shares"] == 2
        assert r.loc["BBB", "buy_shares"] == 3
        assert plan["spent"] == 350.0 and plan["cash_after"] == 0.0

    def test_new_money_goes_to_the_underweight(self):
        # A is rich (100 vs target 80), B is poor (20 vs 80): the whole
        # $40 contribution goes to B, and nothing is ever sold.
        plan = contribution_plan({"AAA": 10, "BBB": 2},
                                 pd.Series({"AAA": 10.0, "BBB": 10.0}),
                                 cash=0.0,
                                 target_weights=pd.Series({"AAA": 0.5, "BBB": 0.5}),
                                 amount=40.0)
        r = plan["rows"]
        assert r.loc["AAA", "buy_shares"] == 0
        assert r.loc["BBB", "buy_shares"] == 4
        assert (r["buy_shares"] >= 0).all()

    def test_setpoint_cash_share_is_respected(self):
        # CAL-style target: 60% AAA, 40% cash. $100 in + $100 already
        # idle: total 200, cash reserve 80, so 120 is deployable.
        plan = contribution_plan({}, pd.Series({"AAA": 30.0}), cash=100.0,
                                 target_weights=pd.Series({"AAA": 0.6}),
                                 amount=100.0)
        assert plan["rows"].loc["AAA", "buy_shares"] == 4
        assert plan["spent"] == 120.0
        assert plan["cash_after"] == pytest.approx(80.0)   # the 40% reserve

    def test_half_share_rule_and_budget(self):
        # deficit 40 at price 100: less than half a share -> no buy
        plan = contribution_plan({}, pd.Series({"AAA": 100.0}), cash=0.0,
                                 target_weights=pd.Series({"AAA": 1.0}),
                                 amount=40.0)
        assert plan["rows"].loc["AAA", "buy_shares"] == 0
        assert plan["cash_after"] == 40.0
        with pytest.raises(ValueError):
            contribution_plan({}, pd.Series({"AAA": 1.0}), 0.0,
                              pd.Series({"AAA": 1.0}), amount=-5)
