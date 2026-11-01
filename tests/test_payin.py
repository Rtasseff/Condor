"""Pay-in engine, rule alerts, XIRR and combined total, pinned to the
hand-checked fixture numbers (tests/fixtures/payin_sample_*; working in
the source repo's docs/condor-bucket-b.md, cross-checked there against
its own engine)."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from condor import accounting as acct
from condor import alerts, payin
from condor.ledger_io import (read_ledger, read_payin, read_rules,
                              read_targets_full)

FIX = Path(__file__).parent / "fixtures"
LEDGER = read_ledger(FIX / "payin_sample_ledger.csv",
                     today=date(2027, 4, 5))["broker_b"].events
SPECS = read_targets_full(FIX / "payin_sample_targets.csv")["broker_b"]
PAYIN = read_payin(FIX / "payin_sample_payin.csv")["broker_b"]
RULES = read_rules(FIX / "payin_sample_rules.csv")["broker_b"]
RULE = {r.id: r for r in RULES}
PX = pd.read_csv(FIX / "payin_sample_prices.csv", parse_dates=["date"]
                 ).pivot(index="date", columns="ticker", values="close")
PLAN = payin.PayInPlan.build(
    PAYIN.total, PAYIN.dates,
    [(t, s.weight, s.timing, s.line) for t, s in SPECS.items()])

D1, T2, T3, T4 = "2027-01-04", "2027-02-01", "2027-03-01", "2027-04-05"


def ledger(through=None, before=None):
    """Ledger rows dated <= `through` (or < `before`)."""
    d = LEDGER["date"]
    if before is not None:
        return LEDGER[d < pd.Timestamp(before)]
    return LEDGER[d <= pd.Timestamp(through)]


def closes(day):
    return PX.loc[pd.Timestamp(day)].dropna()


def state(ev):
    s = acct.ledger_state(ev)
    return s, s.shares, s.cash


def idx_closes(day, level=None):
    s = PX["^IDX"].dropna()
    s = s[s.index <= pd.Timestamp(day)].copy()
    if level is not None:
        s.iloc[-1] = level
    return {"^IDX": s}


def rv(day, shares):
    return shares.get("RES", 0) * closes(day)["RES"]


def buy_list(ev, day, through=None, extra=None):
    s, shares, cash = state(ev)
    bought = payin.gross_bought(ev)
    px = closes(day)
    budget = payin.spendable(PLAN, bought, cash, rv(day, shares))
    k = payin.tranches_due(PLAN, day)
    lump = payin.lump_orders(PLAN, bought, px)
    t = payin.tranche_orders(PLAN, bought, px, through or k, extra, budget)
    buys = lump["amount"].sum() + t["amount"].sum()
    return budget, lump, t, payin.reservoir_trade(PLAN, cash, px, buys), cash


# --------------------------------------------------------- 1. day 1


def test_day_one_lump_budget_tranche_and_reservoir():
    ev = LEDGER.iloc[:1]                       # only the opening deposit
    assert state(ev)[2] == 1000
    budget, lump, t, rt, cash = buy_list(ev, D1)
    assert payin.tranches_due(PLAN, D1) == 1
    assert list(lump.index) == ["LMP"] and lump.loc["LMP", "qty"] == 4
    assert lump.loc["LMP", "amount"] == 200
    assert budget == pytest.approx(700)
    assert list(t.index) == ["AAA", "BBB", "CCC", "DDD"]
    assert t["due"].tolist() == pytest.approx([75, 50, 37.5, 12.5])
    assert t["qty"].tolist() == [2, 2, 3, 2]
    assert t["amount"].tolist() == [80, 60, 36, 14]
    assert t["amount"].sum() == 190
    assert rt == {"side": "BUY", "ticker": "RES", "qty": 61, "price": 10.0,
                  "amount": 610.0}


def test_progress_after_day_one():
    ev = ledger(D1)
    p = payin.progress(PLAN, payin.gross_bought(ev), D1)
    assert list(p.index) == ["lump", "reservoir", "aaa", "bbb", "sleeve"]
    assert p.loc["aaa", "pct"] == pytest.approx(80 / 300 * 100)
    assert round(p.loc["aaa", "pct"], 1) == 26.7
    assert round(p.loc["bbb", "pct"], 1) == 30.0
    assert round(p.loc["sleeve", "pct"], 1) == 25.0
    assert p.loc["sleeve", "tickers"] == ("CCC", "DDD")
    assert p.loc["sleeve", "plan"] == pytest.approx(200)
    assert p.loc["aaa", "scheduled"] == pytest.approx(300 / 4)
    assert p.loc["lump", "scheduled"] == 200            # k_due >= 1
    assert np.isnan(p.loc["reservoir", "scheduled"])
    assert payin.progress(PLAN, {}, "2026-12-31").loc[
        "lump", "scheduled"] == 0


# ------------------------------------------------------------ 2. T2


def test_t2_catch_up_corrects_rounding_and_sells_reservoir():
    ev = ledger(D1)
    budget, lump, t, rt, cash = buy_list(ev, T2)
    assert cash == 0
    assert budget == pytest.approx(511.22)
    assert payin.tranches_due(PLAN, T2) == 2
    assert lump.empty                                   # lump is funded
    assert t["due"].tolist() == pytest.approx([70, 40, 39, 11])
    assert t["qty"].tolist() == [2, 1, 4, 2]
    assert t["amount"].tolist() == [84, 31, 36, 14]
    assert t["amount"].sum() == 165
    assert rt["side"] == "SELL" and rt["qty"] == 17
    assert rt["qty"] * 10.02 - 165 == pytest.approx(5.34)   # cash after


def test_reservoir_trade_edges():
    px = {"RES": 10.0}
    assert payin.reservoir_trade(PLAN, 100, px, 100) is None   # exact
    assert payin.reservoir_trade(PLAN, 105, px, 100) is None   # < 1 share
    assert payin.reservoir_trade(PLAN, 100, px, 101)["qty"] == 1
    assert payin.reservoir_trade(PLAN, 100, px, 100.01)["qty"] == 1
    assert payin.reservoir_trade(PLAN, 100, {}, 150) is None   # no price
    no_res = payin.PayInPlan.build(100, PLAN.dates, [("AAA", 1, "dca", "")])
    assert payin.reservoir_trade(no_res, 100, px, 150) is None


# --------------------------------------------------------- 3. rules at T2


def holdings_at(ev, day, ccc=None):
    s, shares, cash = state(ev)
    px = closes(day).copy()
    if ccc is not None:
        px["CCC"] = ccc
    h = acct.holdings(s, px)
    w = acct.allocation(shares, px, cash)["weight"]
    return h, w


def t2_rules(ccc, idx=None, active=True):
    ev = ledger(D1)
    h, w = holdings_at(ev, T2, ccc)
    return alerts.evaluate(
        RULES, holdings=h, weights=w, targets=SPECS,
        index_closes=idx_closes(T2, idx), payin_active=active)


@pytest.mark.parametrize("price,measured,fired", [
    (9.00, 25.0, True), (9.60, 20.0, False), (9.59, 20.0833, True)])
def test_ccc_below_cost_is_strictly_greater(price, measured, fired):
    r = {x.id: x for x in t2_rules(price)}["ccc_below_cost"]
    assert r.measured == pytest.approx(measured, abs=1e-3)
    assert r.fired is fired and not r.muted


def test_idx_drawdown_at_t2_is_six_percent_not_fired():
    r = {x.id: x for x in t2_rules(9.0)}["idx_drawdown"]
    assert r.measured == pytest.approx(6.0)
    assert not r.fired


def test_t2_with_ccc_rule_applied():
    results = t2_rules(9.0)
    through, extra = alerts.accelerations(results, 2, 4)
    assert (through, extra) == (2, {"CCC": 1, "DDD": 1})
    budget, lump, t, rt, cash = buy_list(ledger(D1), T2, through, extra)
    assert t.loc["CCC", "due"] == pytest.approx(76.5)
    assert t.loc["CCC", "qty"] == 9 and t.loc["CCC", "amount"] == 81
    assert t.loc["DDD", "due"] == pytest.approx(23.5)
    assert t.loc["DDD", "qty"] == 3 and t.loc["DDD", "amount"] == 21
    assert t["amount"].sum() == 217
    assert rt["side"] == "SELL" and rt["qty"] == 22


def _r(id, action="accelerate", tranches=1, targets=(), fired=True):
    return alerts.RuleResult(id, "below_52w_high", "X", 1.0, 5.0, fired,
                             False, action, tranches, tuple(targets))


def test_untargeted_and_targeted_accelerations_add():
    """An untargeted +2 and a targeted +1 together: targeted tickers reach
    k_due + 3, every other line k_due + 2 (confirmed against pflib)."""
    res = [_r("a", tranches=2), _r("b", tranches=1, targets=["CCC", "DDD"])]
    # fixture at T2 (k_due 2, N 4): everything caps at 4
    through, extra = alerts.accelerations(res, 2, 4)
    assert (through, extra) == (4, {"CCC": 1, "DDD": 1})
    _, _, t, _, _ = buy_list(ledger(D1), T2, through, extra)
    assert t["due"].tolist() == pytest.approx([300 - 80, 200 - 60,
                                               150 - 36, 50 - 14])
    # a 10-tranche plan: no cap in sight
    plan = payin.PayInPlan.build(1000, [date(2027, 1, i + 1) for i in
                                        range(10)],
                                 [("AAA", 0.5, "dca", ""),
                                  ("CCC", 0.5, "dca", "")])
    through, extra = alerts.accelerations(res, 1, 10)
    assert (through, extra) == (3, {"CCC": 1, "DDD": 1})
    o = payin.tranche_orders(plan, {}, {"AAA": 1.0, "CCC": 1.0}, through,
                             extra)
    assert o["due"].tolist() == pytest.approx([500 * 3 / 10, 500 * 4 / 10])


def test_acceleration_folding_rules():
    assert alerts.accelerations([], 0, 4) == (1, {})
    assert alerts.accelerations([], 3, 4) == (3, {})
    assert alerts.accelerations([_r("a", fired=False)], 2, 4) == (2, {})
    assert alerts.accelerations([_r("a", action="alert", tranches=None)],
                                2, 4) == (2, {})
    # several untargeted: the largest; several targeted: largest per ticker
    res = [_r("a", tranches=1), _r("b", tranches=2),
           _r("c", tranches=1, targets=["X"]),
           _r("d", tranches=3, targets=["X", "Y"])]
    assert alerts.accelerations(res, 1, 10) == (3, {"X": 3, "Y": 3})
    assert alerts.accelerations([_r("a", tranches=9)], 2, 4) == (4, {})


def test_below_high_window_excludes_old_highs():
    s = PX["^IDX"].dropna()
    s = s[s.index <= pd.Timestamp(T3)]
    assert alerts.below_high(s) == pytest.approx(0.101)
    assert alerts.below_high(s, as_of=T2) == pytest.approx(0.06)
    assert alerts.below_high(s, days=10_000) == pytest.approx(1 - 899 / 1200)
    assert np.isnan(alerts.below_high(pd.Series(dtype=float)))


# ------------------------------------------------------------ 4. T3


def test_t3_drawdown_through_capped_trim_and_reservoir():
    ev = ledger(T2)
    s, shares, cash = state(ev)
    assert shares["RES"] == 44 and cash == pytest.approx(5.34)
    h, w = holdings_at(ev, T3)
    res = alerts.evaluate(RULES, holdings=h, weights=w, targets=SPECS,
                          index_closes=idx_closes(T3), payin_active=True)
    idx = {r.id: r for r in res}["idx_drawdown"]
    assert idx.measured == pytest.approx(10.1) and idx.fired
    at900 = {r.id: r for r in alerts.evaluate(
        RULES, holdings=h, weights=w, targets=SPECS,
        index_closes=idx_closes(T3, 900), payin_active=True)}
    assert at900["idx_drawdown"].measured == pytest.approx(10.0)
    assert not at900["idx_drawdown"].fired
    through, extra = alerts.accelerations(res, 3, 4)
    assert (through, extra) == (4, {})

    bought = payin.gross_bought(ev)
    px = closes(T3)
    budget = payin.spendable(PLAN, bought, cash, rv(T3, shares))
    assert budget == pytest.approx(346.66)
    raw = payin.tranche_orders(PLAN, bought, px, through)
    assert raw["due"].tolist() == pytest.approx([136, 109, 78, 22])
    assert raw["qty"].tolist() == [3, 3, 8, 3]
    assert raw["amount"].sum() == pytest.approx(354.5)
    t = payin.tranche_orders(PLAN, bought, px, through, budget=budget)
    assert t["qty"].tolist() == [3, 2, 8, 3]            # BBB trimmed
    assert t.loc["BBB", "note"] == payin.NOTE_TRIM
    assert t["amount"].sum() == pytest.approx(317.0)
    rt = payin.reservoir_trade(PLAN, cash, px, 317.0)
    assert rt["side"] == "SELL" and rt["qty"] == 32
    assert 32 * 10.03 + cash - 317 == pytest.approx(9.30)
    assert 44 - 32 == 12
    assert not payin.is_complete(PLAN, bought, px, budget, T3)


def test_trim_ties_go_to_the_first_in_target_order():
    plan = payin.PayInPlan.build(
        100, [date(2027, 1, 1)],
        [("AAA", 0.5, "dca", ""), ("BBB", 0.5, "dca", "")])
    px = {"AAA": 10.0, "BBB": 10.0}
    # both due 50 -> 5 shares each; budget 90 drops exactly one, from AAA
    o = payin.tranche_orders(plan, {}, px, 1, budget=90)
    assert o["qty"].tolist() == [4, 5]


def test_small_due_note():
    o = payin.tranche_orders(PLAN, {"AAA": 299.0}, closes(T2), 4)
    assert o.loc["AAA", "qty"] == 0
    assert o.loc["AAA", "note"] == payin.NOTE_SMALL
    assert o.loc["AAA", "due"] == pytest.approx(1.0)


# --------------------------------------------- 5. T4 completion, mute


def test_t4_complete_with_bbb_at_83_percent():
    ev = ledger(T4)
    s, shares, cash = state(ev)
    assert shares["RES"] == 12 and cash == pytest.approx(9.30)
    bought = payin.gross_bought(ev)
    px = closes(T4)
    budget = payin.spendable(PLAN, bought, cash, rv(T4, shares))
    assert budget == pytest.approx(29.78)
    raw = payin.tranche_orders(PLAN, bought, px, 4)
    assert raw.loc["BBB", "due"] == pytest.approx(34)
    assert raw.loc["BBB", "qty"] == 1 and raw["qty"].sum() == 1
    trimmed = payin.tranche_orders(PLAN, bought, px, 4, budget=budget)
    assert trimmed["qty"].sum() == 0
    assert payin.is_complete(PLAN, bought, px, budget, T4)
    assert not payin.is_complete(PLAN, bought, px, budget, "2027-04-04")
    assert not payin.is_complete(PLAN, bought, px, 100.0, T4)  # a share fits
    assert not payin.is_complete(PLAN, bought, px.drop("BBB"), budget, T4)
    p = payin.progress(PLAN, bought, T4)
    assert p.loc["bbb", "pct"] == pytest.approx(83.0)
    assert bought["BBB"] == 166


def test_drift_is_muted_during_the_payin():
    ev = ledger(D1)
    h, w = holdings_at(ev, T2)
    kw = dict(holdings=h, weights=w, targets=SPECS,
              index_closes=idx_closes(T2))
    drift = lambda active: {r.id: r for r in alerts.evaluate(   # noqa: E731
        RULES, payin_active=active, **kw)}["drift"]
    muted, live = drift(True), drift(False)
    assert muted.muted and not muted.fired
    assert live.fired and not live.muted
    assert dict((b[0], round(b[1], 2)) for b in live.breaches)[
        "reservoir"] == pytest.approx(61.11, abs=0.01)
    assert muted.measured == live.measured


# ----------------------------------------------- 6. drift after completion


def final_state(ccc=None, ddd=None):
    ev = ledger(T4)
    s, shares, cash = state(ev)
    px = closes(T4).copy()
    if ccc is not None:
        px["CCC"] = ccc
    if ddd is not None:
        px["DDD"] = ddd
    a = acct.allocation(shares, px, cash)
    return s, shares, cash, px, a, acct.holdings(s, px)


def drift(ccc=None, ddd=None):
    s, shares, cash, px, a, h = final_state(ccc, ddd)
    total = a["value"].sum() + cash
    res = alerts.evaluate(RULES, holdings=h, weights=a["weight"],
                          targets=SPECS, index_closes=idx_closes(T4),
                          payin_active=False)
    return total, {r.id: r for r in res}["drift"]


def test_drift_after_completion_no_breach():
    total, r = drift()
    assert total == pytest.approx(1049.28)
    assert not r.fired and r.breaches == ()
    _, shares, cash, px, a, _ = final_state()
    line = lambda ts: 100 * a.loc[ts, "value"].sum() / total       # noqa
    assert line(["AAA"]) == pytest.approx(30.69, abs=0.005)
    assert line(["BBB"]) == pytest.approx(17.87, abs=0.005)
    assert line(["CCC", "DDD"]) == pytest.approx(19.63, abs=0.005)
    assert line(["LMP"]) == pytest.approx(19.44, abs=0.005)
    assert line(["RES"]) == pytest.approx(11.48, abs=0.005)


def test_drift_breach_on_bbb_and_sleeve():
    total, r = drift(ccc=20, ddd=16)
    assert total == pytest.approx(1255.28)
    assert r.fired
    got = {ln: (round(wt, 2), round(tg, 2)) for ln, wt, tg in r.breaches}
    assert set(got) == {"bbb", "sleeve"}
    assert got["bbb"][0] == pytest.approx(14.94, abs=0.005)
    assert got["bbb"][0] - got["bbb"][1] == pytest.approx(-5.06, abs=0.005)
    assert got["sleeve"][0] == pytest.approx(32.82, abs=0.005)
    assert got["sleeve"][0] - got["sleeve"][1] == pytest.approx(12.82,
                                                                abs=0.005)
    assert r.measured == pytest.approx(12.82, abs=0.005)


def test_below_avg_cost_not_held_is_not_fired():
    h = pd.DataFrame(columns=["shares", "price", "avg_cost"])
    r = alerts.evaluate([RULE["ccc_below_cost"]], holdings=h,
                        weights=pd.Series(dtype=float), targets=SPECS,
                        index_closes={}, payin_active=False)[0]
    assert r.measured is None and not r.fired


def test_missing_index_closes_is_not_fired():
    r = alerts.evaluate([RULE["idx_drawdown"]], holdings=pd.DataFrame(),
                        weights={}, targets=SPECS, index_closes={},
                        payin_active=False)[0]
    assert r.measured is None and not r.fired


# --------------------------------------------------------------- misc


def test_gross_bought_excludes_fees_and_other_kinds():
    ev = pd.DataFrame([
        dict(kind="buy", ticker="A", shares=2, price=10.0, fees=5.0),
        dict(kind="buy", ticker="A", shares=1, price=11.0, fees=0.0),
        dict(kind="sell", ticker="A", shares=1, price=12.0, fees=0.0),
        dict(kind="deposit", ticker=None, shares=np.nan, price=np.nan,
             fees=0.0)])
    assert payin.gross_bought(ev) == {"A": 31.0}
    assert payin.gross_bought(None) == {}


def test_reserve_and_spendable():
    assert payin.reserve_needed(PLAN, {}) == pytest.approx(300)
    assert payin.reserve_needed(PLAN, {"LMP": 200}) == pytest.approx(100)
    assert payin.spendable(PLAN, {}, 50, 10) == 0           # floored
    assert payin.spendable(PLAN, {"LMP": 200}, 500, 0) == 400


# ----------------------------------------------------------------- XIRR


def daily(rows, last_value):
    idx = pd.to_datetime([d for d, _ in rows])
    v = [0.0] * len(rows)
    v[-1] = last_value
    return pd.DataFrame({"value": v, "flow": [f for _, f in rows]},
                        index=idx)


def test_xirr_single_year_ten_percent():
    d = daily([("2027-01-01", 1000), ("2028-01-01", 0)], 1100)
    assert acct.money_weighted_return(d) == pytest.approx(0.10, abs=1e-6)


def test_xirr_with_a_second_deposit():
    d = daily([("2027-01-01", 1000), ("2027-07-02", 500),
               ("2028-01-01", 0)], 1600)
    r = acct.money_weighted_return(d)
    assert r == pytest.approx(0.080266, abs=1e-6)
    # the NPV identity from the source repo's working
    assert 1000 + 500 * (1 + r) ** (-182 / 365) == pytest.approx(
        1600 / (1 + r), abs=1e-6)


def test_xirr_none_when_short_or_no_sign_change():
    short = daily([("2027-01-01", 1000), ("2027-03-01", 0)], 1100)  # 59 d
    assert acct.money_weighted_return(short) is None
    edge = daily([("2027-01-01", 1000), ("2027-04-01", 0)], 1100)   # 90 d
    assert acct.money_weighted_return(edge) is not None
    allpos = daily([("2027-01-01", 0), ("2028-01-01", 0)], 1100)
    assert acct.money_weighted_return(allpos) is None
    assert acct.money_weighted_return(daily([("2027-01-01", 1)], 1)) is None


def test_xirr_loss_and_flow_on_last_day():
    d = daily([("2027-01-01", 1000), ("2028-01-01", 100)], 1000)
    # -1000 at t0; +1000 - 100 = +900 at t=1  -> -10%
    assert acct.money_weighted_return(d) == pytest.approx(-0.10, abs=1e-6)


def test_xirr_equals_a_plain_ledger_replay():
    """equals the engine: XIRR of the real fixture ledger's daily series is
    the root of its own NPV."""
    ev = ledger(T4)
    d = acct.daily_state(ev, PX.drop(columns=["^IDX"]))
    r = acct.money_weighted_return(d)
    assert r is not None
    idx = d.index
    t = np.array([(i - idx[0]).days for i in idx]) / 365
    cf = -d["flow"].to_numpy().copy()
    cf[-1] += d["value"].iloc[-1]
    assert np.sum(cf * (1 + r) ** (-t)) == pytest.approx(0, abs=1e-6)


# ------------------------------------------------------- combined total


def test_combined_total():
    fx = {"EURUSD": 1.25}
    assert acct.combined_total({"USD": 1000, "EUR": 800}, fx,
                               "USD") == pytest.approx(2000)
    assert acct.combined_total({"USD": 1000, "EUR": 800}, fx,
                               "EUR") == pytest.approx(1600)
    assert acct.combined_total({"USD": 5}, {}, "USD") == 5
    with pytest.raises(KeyError):
        acct.combined_total({"GBP": 1}, fx, "USD")


# ------------------------------------------------ coordinator review fixes


def test_unfunded_lump_blocks_completion():
    ev = ledger(T4)
    bought = payin.gross_bought(ev)
    px = closes(T4)
    s, shares, cash = state(ev)
    budget = payin.spendable(PLAN, bought, cash, rv(T4, shares))
    assert payin.is_complete(PLAN, bought, px, budget, T4)      # funded lump
    no_lump = dict(bought, LMP=0.0)
    # plenty of budget for the dca side: only the lump holds it open
    assert not payin.is_complete(PLAN, no_lump, px, budget, T4)


def test_unbought_at_t4_is_34_or_3_4_percent():
    bought = payin.gross_bought(ledger(T4))
    assert payin.unbought(PLAN, bought) == pytest.approx(34)
    assert 100 * payin.unbought(PLAN, bought) / PLAN.total == pytest.approx(3.4)
    assert payin.unbought(PLAN, {}) == pytest.approx(900)   # reservoir excluded


def test_reservoir_sale_is_capped_at_shares_held():
    px = {"RES": 10.0}
    t = payin.reservoir_trade(PLAN, 0, px, 165, held=10)
    assert (t["side"], t["qty"], t["amount"]) == ("SELL", 10, 100.0)
    assert t["short"] == pytest.approx(65)
    t = payin.reservoir_trade(PLAN, 0, px, 165, held=0)
    assert t["qty"] == 0 and t["short"] == pytest.approx(165)
    # enough shares: unchanged, no `short`
    t = payin.reservoir_trade(PLAN, 0, px, 165, held=61)
    assert t["qty"] == 17 and "short" not in t
    assert payin.reservoir_trade(PLAN, 0, px, 165)["qty"] == 17   # held unknown


def test_trim_note_reports_the_real_count():
    plan = payin.PayInPlan.build(
        100, [date(2027, 1, 1)], [("AAA", 1.0, "dca", "")])
    one = payin.tranche_orders(plan, {}, {"AAA": 10.0}, 1, budget=95)
    assert one.loc["AAA", "note"] == payin.NOTE_TRIM
    three = payin.tranche_orders(plan, {}, {"AAA": 10.0}, 1, budget=65)
    assert three.loc["AAA", "qty"] == 6
    assert three.loc["AAA", "note"] == \
        "4 shares trimmed to stay within cash; carries forward"
