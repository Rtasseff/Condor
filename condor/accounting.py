"""Account engine: pure functions over a transaction ledger and prices.

See docs/decisions/0004-account-ledger.md and 0005-ledger-v2-mirror.md.
An account is an append-only ledger of events; everything here derives
state from it:

- `ledger_state`       -> shares, cash, contributions, cost, realized, income
- `replay`             -> (shares, cash, net contributions) of `ledger_state`
- `daily_state`        -> value / flow / contribution series on trading days
- `time_weighted_return` -> return that ignores contribution timing
- `holdings`           -> per-position cost / unrealized / realized / income
- `bill_prices`        -> straight-line accretion of zero-coupon bills
- `allocation`         -> actual weights (incl. cash) at given prices
- `rebalance_plan`     -> whole-share trades from here to a target

Conventions:
- Valuation uses RAW closes (you own N shares at the actual price);
  adjusted closes are for return statistics elsewhere.
- Event kinds: deposit, withdraw (cash, `amount`); buy, sell, redeem
  (`ticker`, `shares`, `price`, `fees`); dividend, interest, fee
  (`amount`, `fees` withheld; ticker optional for interest/fee);
  set_shares, set_cash (manual forces — the delta is an in-kind
  contribution at the recorded price/amount, so forcing state never
  manufactures return). A buy carrying a `maturity` opens a bill lot.
- Cost basis is average cost; buy fees go into cost, sell fees come off
  proceeds. Income and fees are return, not flows.
- The engine has no notion of currency: every amount is in the
  account's own.
- Flows F_t are treated as available at the start of day t:
  r_t = V_t / (V_{t-1} + F_t) - 1, geometrically linked. A deposit
  therefore moves value but not return.

Engine only: no Django, no HTTP. The web layer owns persistence and
validation; this module trusts its inputs' shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

KINDS = ("deposit", "withdraw", "buy", "sell", "set_shares", "set_cash",
         "dividend", "interest", "fee", "redeem")

EVENT_COLUMNS = ["date", "kind", "ticker", "shares", "price", "amount",
                 "fees", "maturity"]

_EPS = 1e-12
_CASH = "CASH"


@dataclass(frozen=True)
class BillLot:
    settle: date
    maturity: date
    nominal: float
    cost: float


@dataclass(frozen=True)
class LedgerState:
    shares: dict[str, float]        # open positions; a bill's "shares" = nominal held
    cash: float
    contributions: float
    cost: dict[str, float]          # cost basis of open positions
    realized: dict[str, float]      # by ticker, closed positions included
    income: dict[str, float]        # gross; interest on cash keyed "CASH"
    charges: float                  # standalone fees + fees withheld from income
    trade_fees: float               # buy/sell/redeem fees (already inside cost/realized)
    bills: dict[str, list[BillLot]]  # open lots per bill ticker

    def avg_cost(self, ticker) -> float:
        n = self.shares.get(ticker, 0.0)
        return self.cost.get(ticker, 0.0) / n if n else 0.0


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_COLUMNS)


def _norm_events(events: pd.DataFrame | None) -> pd.DataFrame:
    if events is None or len(events) == 0:
        return _empty_events()
    ev = events.copy()
    ev["date"] = pd.to_datetime(ev["date"])
    # frames from before ADR 0005 have six columns
    ev["fees"] = (ev["fees"].fillna(0.0).astype(float)
                  if "fees" in ev else 0.0)
    ev["maturity"] = (pd.to_datetime(ev["maturity"]) if "maturity" in ev
                      else pd.NaT)
    # stable order: by date, then input order (ledger insertion order)
    return ev.sort_values("date", kind="stable").reset_index(drop=True)


def _is_set(x) -> bool:
    return x is not None and not pd.isna(x)


def bill_tickers(events: pd.DataFrame | None) -> set[str]:
    """Tickers having any buy with a non-null `maturity`."""
    ev = _norm_events(events)
    if ev.empty:
        return set()
    b = ev[(ev["kind"] == "buy") & ev["maturity"].notna()]
    return set(b["ticker"])


def _scale_lots(lots: list[BillLot], frac_left: float) -> list[BillLot]:
    return [BillLot(l.settle, l.maturity, l.nominal * frac_left,
                    l.cost * frac_left) for l in lots]


def ledger_state(events: pd.DataFrame | None) -> LedgerState:
    """The one replay loop: run the ledger -> `LedgerState`.

    Raises ValueError on an unknown kind or a `redeem` of a ticker that
    is not a bill, or a set_shares on a bill."""
    shares: dict[str, float] = {}
    cost: dict[str, float] = {}
    realized: dict[str, float] = {}
    income: dict[str, float] = {}
    bills: dict[str, list[BillLot]] = {}
    bill_set: set[str] = set()
    cash = contrib = charges = trade_fees = 0.0

    def dispose(t, n, proceeds):
        """Remove n from t at average cost, booking the realized gain."""
        nonlocal cash
        held = shares.get(t, 0.0)
        avg = cost.get(t, 0.0) / held if abs(held) > _EPS else 0.0
        cost[t] = cost.get(t, 0.0) - avg * n
        realized[t] = realized.get(t, 0.0) + proceeds - avg * n
        shares[t] = held - n
        cash += proceeds
        if t in bill_set and abs(held) > _EPS:
            bills[t] = _scale_lots(bills.get(t, []), 1.0 - n / held)

    for ev in _norm_events(events).itertuples(index=False):
        kind = ev.kind
        fee = float(ev.fees)
        if kind == "deposit":
            cash += ev.amount
            contrib += ev.amount
        elif kind == "withdraw":
            cash -= ev.amount
            contrib -= ev.amount
        elif kind == "buy":
            outlay = ev.shares * ev.price + fee
            shares[ev.ticker] = shares.get(ev.ticker, 0.0) + ev.shares
            cost[ev.ticker] = cost.get(ev.ticker, 0.0) + outlay
            cash -= outlay
            trade_fees += fee
            if _is_set(ev.maturity):
                bill_set.add(ev.ticker)
                bills.setdefault(ev.ticker, []).append(BillLot(
                    ev.date.date(), ev.maturity.date(), ev.shares, outlay))
        elif kind in ("sell", "redeem"):
            if kind == "redeem" and ev.ticker not in bill_set:
                raise ValueError(f"redeem of {ev.ticker!r}: not a bill")
            dispose(ev.ticker, ev.shares, ev.shares * ev.price - fee)
            trade_fees += fee
        elif kind in ("dividend", "interest"):
            key = ev.ticker if _is_set(ev.ticker) and ev.ticker else _CASH
            income[key] = income.get(key, 0.0) + ev.amount
            cash += ev.amount - fee
            charges += fee
        elif kind == "fee":
            cash -= ev.amount
            charges += ev.amount
        elif kind == "set_shares":
            if ev.ticker in bill_set:
                raise ValueError(f"set_shares on bill {ev.ticker!r}")
            held = shares.get(ev.ticker, 0.0)
            delta = ev.shares - held
            contrib += delta * ev.price          # in-kind flow, not return
            if delta > 0:
                cost[ev.ticker] = cost.get(ev.ticker, 0.0) + delta * ev.price
            elif delta < 0:
                avg = cost.get(ev.ticker, 0.0) / held if abs(held) > _EPS else 0.0
                cost[ev.ticker] = cost.get(ev.ticker, 0.0) - avg * -delta
                realized[ev.ticker] = (realized.get(ev.ticker, 0.0)
                                       + -delta * (ev.price - avg))
            shares[ev.ticker] = ev.shares
        elif kind == "set_cash":
            delta = ev.amount - cash
            cash = ev.amount
            contrib += delta
        else:
            raise ValueError(f"unknown event kind: {kind!r}")

    open_ = {t for t, s in shares.items() if abs(s) > _EPS}
    return LedgerState(
        shares={t: float(shares[t]) for t in shares if t in open_},
        cash=float(cash), contributions=float(contrib),
        cost={t: float(cost.get(t, 0.0)) for t in open_},
        realized={t: float(v) for t, v in realized.items()},
        income={t: float(v) for t, v in income.items()},
        charges=float(charges), trade_fees=float(trade_fees),
        bills={t: lots for t, lots in bills.items() if t in open_})


def replay(events: pd.DataFrame | None) -> tuple[dict, float, float]:
    """Run the ledger -> ({ticker: shares}, cash, net_contributions).

    Manual forces count their delta as contribution (in-kind transfer),
    valued at the event's recorded price (set_shares) or amount delta
    (set_cash).
    """
    s = ledger_state(events)
    return s.shares, s.cash, s.contributions


def accrued_value(lot: BillLot, on) -> float:
    """Straight-line value of a lot on a day: cost at settlement, nominal
    at maturity, nominal thereafter."""
    on = pd.Timestamp(on).date()
    span = (lot.maturity - lot.settle).days
    frac = 1.0 if span <= 0 else min(max((on - lot.settle).days / span, 0.0), 1.0)
    return lot.cost + (lot.nominal - lot.cost) * frac


def bill_prices(events: pd.DataFrame | None, index) -> pd.DataFrame:
    """Value per 1 nominal of the lots held at the END of each day in
    `index`, one column per bill ticker (0.0 when none is held). Events
    land on the first index day on/after their date, as in `daily_state`."""
    ev = _norm_events(events)
    index = pd.DatetimeIndex(index)
    tick = sorted(bill_tickers(ev))
    out = pd.DataFrame(0.0, index=index, columns=tick)
    if not tick or len(index) == 0:
        return out
    lots: dict[str, list[BillLot]] = {t: [] for t in tick}
    held: dict[str, float] = {t: 0.0 for t in tick}
    by_day: dict[int, list] = {}
    for e in ev.itertuples(index=False):
        if e.ticker not in lots:
            continue
        pos = min(int(index.searchsorted(pd.Timestamp(e.date).normalize())),
                  len(index) - 1)
        by_day.setdefault(pos, []).append(e)
    for pos, day in enumerate(index):
        for e in by_day.get(pos, []):
            t = e.ticker
            if e.kind == "buy" and _is_set(e.maturity):
                lots[t].append(BillLot(e.date.date(), e.maturity.date(),
                                       e.shares, e.shares * e.price + e.fees))
                held[t] += e.shares
            elif e.kind in ("sell", "redeem") and held[t] > _EPS:
                lots[t] = _scale_lots(lots[t], 1.0 - e.shares / held[t])
                held[t] -= e.shares
        for t in tick:
            nominal = sum(l.nominal for l in lots[t])
            if held[t] > _EPS and nominal > _EPS:
                out.iloc[pos, out.columns.get_loc(t)] = (
                    sum(accrued_value(l, day) for l in lots[t]) / nominal)
    return out


def holdings(state: LedgerState, prices: pd.Series) -> pd.DataFrame:
    """Open positions -> DataFrame indexed by ticker with [shares, price,
    value, cost, avg_cost, unrealized, unrealized_pct, realized, income].
    `prices` covers every open ticker (bills at their `bill_prices`
    value). unrealized_pct = value / cost - 1."""
    cols = ["shares", "price", "value", "cost", "avg_cost", "unrealized",
            "unrealized_pct", "realized", "income"]
    tick = sorted(state.shares)
    if not tick:
        return pd.DataFrame(columns=cols)
    px = pd.Series(prices).reindex(tick)
    if px.isna().any():
        raise KeyError(f"no price for {list(px.index[px.isna()])}")
    sh = pd.Series({t: state.shares[t] for t in tick})
    cost = pd.Series({t: state.cost.get(t, 0.0) for t in tick})
    value = sh * px
    return pd.DataFrame({
        "shares": sh, "price": px, "value": value, "cost": cost,
        "avg_cost": pd.Series({t: state.avg_cost(t) for t in tick}),
        "unrealized": value - cost,
        "unrealized_pct": (value / cost - 1.0).where(cost > _EPS, 0.0),
        "realized": pd.Series({t: state.realized.get(t, 0.0) for t in tick}),
        "income": pd.Series({t: state.income.get(t, 0.0) for t in tick}),
    })


def daily_state(events: pd.DataFrame | None,
                closes: pd.DataFrame) -> pd.DataFrame:
    """Account history on trading days -> DataFrame[value, flow, contributions].

    `closes` are raw close prices (columns = tickers); gaps are
    forward-filled. Bills are valued internally by `bill_prices`, so
    `closes` need no bill columns. Days start at the first event.
    `flow` is the net external flow ON that day (cash deposits/withdrawals
    plus in-kind force deltas — never income or fees, which are return);
    `contributions` is its running total. Events dated on non-trading
    days take effect on the next trading day.
    """
    ev = _norm_events(events)
    if ev.empty:
        return pd.DataFrame(columns=["value", "flow", "contributions"])
    px = closes.sort_index().ffill()
    idx = px.index[px.index >= ev["date"].iloc[0].normalize()]
    if len(idx) == 0:
        # every event is dated after the last close (e.g. a weekend
        # deposit before Monday's data): value it on the last known day
        idx = px.index[-1:]
    if len(idx) == 0:
        return pd.DataFrame(columns=["value", "flow", "contributions"])

    held_kinds = ("buy", "sell", "redeem", "set_shares")
    bills = bill_tickers(ev)
    tickers = sorted(set(ev.loc[ev["kind"].isin(held_kinds), "ticker"]
                         .dropna()))
    d_shares = pd.DataFrame(0.0, index=idx, columns=tickers)  # increments
    d_cash = pd.Series(0.0, index=idx)
    d_flow = pd.Series(0.0, index=idx)

    running: dict[str, float] = {}
    run_cash = 0.0
    for e in ev.itertuples(index=False):
        pos = int(idx.searchsorted(pd.Timestamp(e.date).normalize()))
        if pos >= len(idx):
            pos = len(idx) - 1  # late events land on the last known day
        day = idx[pos]
        if e.kind == "deposit":
            d_cash[day] += e.amount
            d_flow[day] += e.amount
            run_cash += e.amount
        elif e.kind == "withdraw":
            d_cash[day] -= e.amount
            d_flow[day] -= e.amount
            run_cash -= e.amount
        elif e.kind == "buy":
            out = e.shares * e.price + e.fees
            d_shares.loc[day, e.ticker] += e.shares
            d_cash[day] -= out
            running[e.ticker] = running.get(e.ticker, 0.0) + e.shares
            run_cash -= out
        elif e.kind in ("sell", "redeem"):
            net = e.shares * e.price - e.fees
            d_shares.loc[day, e.ticker] -= e.shares
            d_cash[day] += net
            running[e.ticker] = running.get(e.ticker, 0.0) - e.shares
            run_cash += net
        elif e.kind in ("dividend", "interest"):
            d_cash[day] += e.amount - e.fees
            run_cash += e.amount - e.fees
        elif e.kind == "fee":
            d_cash[day] -= e.amount
            run_cash -= e.amount
        elif e.kind == "set_shares":
            delta = e.shares - running.get(e.ticker, 0.0)
            d_shares.loc[day, e.ticker] += delta
            d_flow[day] += delta * e.price
            running[e.ticker] = e.shares
        elif e.kind == "set_cash":
            delta = e.amount - run_cash
            d_cash[day] += delta
            d_flow[day] += delta
            run_cash = e.amount
        else:
            raise ValueError(f"unknown event kind: {e.kind!r}")

    shares_path = d_shares.cumsum()
    cash_path = d_cash.cumsum()
    listed = [t for t in tickers if t not in bills]
    missing = [t for t in listed if t not in px.columns]
    if missing:
        raise KeyError(f"no close prices for {missing}")
    holdings_value = pd.Series(0.0, index=idx)
    if listed:
        holdings_value = holdings_value + (
            shares_path[listed] * px.loc[idx, listed].fillna(0.0)).sum(axis=1)
    billed = [t for t in tickers if t in bills]
    if billed:
        bp = bill_prices(ev, idx)
        holdings_value = holdings_value + (
            shares_path[billed] * bp[billed]).sum(axis=1)
    out = pd.DataFrame({
        "value": holdings_value + cash_path,
        "flow": d_flow,
        "contributions": d_flow.cumsum(),
    })
    return out


def time_weighted_return(daily: pd.DataFrame) -> float:
    """Geometrically-linked daily returns with start-of-day flows.

    r_t = V_t / (V_{t-1} + F_t) - 1. The first day is the base (its
    flow funds the account). Days where the denominator is 0 are
    skipped (empty account). -> total TWR over the whole series.
    """
    if len(daily) < 2:
        return 0.0
    v = daily["value"].to_numpy(dtype=float)
    f = daily["flow"].to_numpy(dtype=float)
    denom = v[:-1] + f[1:]
    ok = denom > 1e-12
    growth = np.ones_like(denom)
    growth[ok] = v[1:][ok] / denom[ok]
    return float(np.prod(growth) - 1.0)


def allocation(shares: dict | pd.Series, prices: pd.Series,
               cash: float) -> pd.DataFrame:
    """Actual weights at given prices -> DataFrame indexed by ticker
    with [shares, price, value, weight]; cash is NOT a row (callers
    show it separately; its weight is 1 - sum(weight))."""
    sh = pd.Series(dict(shares), dtype=float)
    if sh.empty:
        return pd.DataFrame(columns=["shares", "price", "value", "weight"])
    px = prices.reindex(sh.index)
    if px.isna().any():
        raise KeyError(f"no price for {list(px.index[px.isna()])}")
    value = sh * px
    total = float(value.sum()) + float(cash)
    weight = value / total if total > 0 else value * 0.0
    return pd.DataFrame({"shares": sh, "price": px, "value": value,
                         "weight": weight})


def rebalance_plan(shares: dict | pd.Series, prices: pd.Series, cash: float,
                   target_weights: pd.Series) -> dict:
    """Whole-share trades from current state to `target_weights`.

    Targets are fractions of total account value; the remainder
    (1 - sum) is the target cash weight — a CAL draft plugs in
    directly. Trades are rounded to the nearest whole share at the
    given prices ("within one unit"); if the rounded plan would
    overspend the cash on hand, buys are trimmed one share at a time —
    cheapest buy first, so the least dollar-distance from target is
    given up and idle cash stays minimal. Deterministic.

    -> {"rows": DataFrame[price, current_shares, current_value,
        current_weight, target_weight, trade_shares, trade_value,
        new_shares, new_value, new_weight],
        "total": float, "cash_before": float, "cash_after": float,
        "target_cash_weight": float}
    """
    tw = pd.Series(target_weights, dtype=float)
    if (tw < -1e-12).any():
        raise ValueError("target weights must be non-negative")
    if float(tw.sum()) > 1.0 + 1e-9:
        raise ValueError("target weights must sum to at most 1")

    tickers = sorted(set(pd.Series(dict(shares)).index) | set(tw.index))
    sh = pd.Series(dict(shares), dtype=float).reindex(tickers).fillna(0.0)
    tw = tw.reindex(tickers).fillna(0.0)
    px = prices.reindex(tickers)
    if px.isna().any():
        raise KeyError(f"no price for {list(px.index[px.isna()])}")

    cur_val = sh * px
    total = float(cur_val.sum()) + float(cash)
    target_val = tw * total
    trade = np.rint((target_val - cur_val) / px)   # nearest whole share
    trade = np.maximum(trade, -sh)                 # can't sell short

    def cash_after(tr):
        return float(cash) - float((tr * px).sum())

    # trim buys one share at a time (cheapest first) until affordable
    while cash_after(trade) < -1e-9:
        buys = trade[trade > 0]
        if buys.empty:
            break
        cheapest = px[buys.index].idxmin()
        trade[cheapest] -= 1

    new_sh = sh + trade
    new_val = new_sh * px
    rows = pd.DataFrame({
        "price": px,
        "current_shares": sh,
        "current_value": cur_val,
        "current_weight": cur_val / total if total > 0 else cur_val * 0.0,
        "target_weight": tw,
        "trade_shares": trade,
        "trade_value": trade * px,
        "new_shares": new_sh,
        "new_value": new_val,
        "new_weight": new_val / total if total > 0 else new_val * 0.0,
    })
    return {"rows": rows, "total": total, "cash_before": float(cash),
            "cash_after": cash_after(trade),
            "target_cash_weight": float(1.0 - tw.sum())}


def contribution_plan(shares: dict | pd.Series, prices: pd.Series,
                      cash: float, target_weights: pd.Series,
                      amount: float) -> dict:
    """Route a new contribution toward the setpoint — buys only (DCA).

    The classic "where does this week's money go": after depositing
    `amount`, keep the setpoint's cash share in cash and spend the rest
    on whole shares, one share at a time to the asset with the largest
    dollar deficit vs its target, while its deficit exceeds half a
    share (never overshoot a target by half a unit or more).
    Overweight assets simply receive nothing — nothing is ever sold,
    so this is NOT the rebalance plan; it is the gentle version that
    lets regular contributions do the rebalancing. Idle cash above the
    setpoint's reserve is deployed along with the contribution.

    -> {"rows": DataFrame[price, current_shares, current_value,
        current_weight (of the pre-deposit total), target_weight,
        buy_shares, buy_value, new_weight (of the post-deposit total)],
        "amount", "spent", "total_after", "cash_after",
        "target_cash_weight"}
    """
    if amount < 0:
        raise ValueError("amount must be >= 0")
    tw = pd.Series(target_weights, dtype=float)
    if (tw < -1e-12).any():
        raise ValueError("target weights must be non-negative")
    if float(tw.sum()) > 1.0 + 1e-9:
        raise ValueError("target weights must sum to at most 1")

    tickers = sorted(set(pd.Series(dict(shares)).index) | set(tw.index))
    sh = pd.Series(dict(shares), dtype=float).reindex(tickers).fillna(0.0)
    tw = tw.reindex(tickers).fillna(0.0)
    px = prices.reindex(tickers)
    if px.isna().any():
        raise KeyError(f"no price for {list(px.index[px.isna()])}")

    cur_val = sh * px
    total_before = float(cur_val.sum()) + float(cash)
    total_after = total_before + float(amount)
    target_val = tw * total_after
    target_cash = (1.0 - float(tw.sum())) * total_after
    budget = max(0.0, float(cash) + float(amount) - target_cash)

    buy = pd.Series(0.0, index=pd.Index(tickers))
    while True:
        deficit = target_val - (cur_val + buy * px)
        ok = (px <= budget + 1e-9) & (deficit > px / 2)
        if not ok.any():
            break
        pick = deficit[ok].idxmax()      # ties: first alphabetically
        buy[pick] += 1
        budget -= float(px[pick])

    spent = float((buy * px).sum())
    new_val = cur_val + buy * px
    rows = pd.DataFrame({
        "price": px,
        "current_shares": sh,
        "current_value": cur_val,
        "current_weight": (cur_val / total_before if total_before > 0
                           else cur_val * 0.0),
        "target_weight": tw,
        "buy_shares": buy,
        "buy_value": buy * px,
        "new_weight": new_val / total_after if total_after > 0 else new_val * 0.0,
    })
    return {"rows": rows, "amount": float(amount), "spent": spent,
            "total_after": total_after,
            "cash_after": float(cash) + float(amount) - spent,
            "target_cash_weight": float(1.0 - tw.sum())}
