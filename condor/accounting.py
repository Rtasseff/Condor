"""Account engine: pure functions over a transaction ledger and prices.

See docs/decisions/0004-account-ledger.md. An account is an append-only
ledger of events; everything here derives state from it:

- `replay`             -> shares, cash, net contributions (final state)
- `daily_state`        -> value / flow / contribution series on trading days
- `time_weighted_return` -> return that ignores contribution timing
- `allocation`         -> actual weights (incl. cash) at given prices
- `rebalance_plan`     -> whole-share trades from here to a target

Conventions:
- Valuation uses RAW closes (you own N shares at the actual price);
  adjusted closes are for return statistics elsewhere.
- Event kinds: deposit, withdraw (cash, `amount`); buy, sell
  (`ticker`, `shares`, `price`); set_shares, set_cash (manual forces —
  the delta is an in-kind contribution at the recorded price/amount,
  so forcing state never manufactures return).
- Flows F_t are treated as available at the start of day t:
  r_t = V_t / (V_{t-1} + F_t) - 1, geometrically linked. A deposit
  therefore moves value but not return.

Engine only: no Django, no HTTP. The web layer owns persistence and
validation; this module trusts its inputs' shapes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

KINDS = ("deposit", "withdraw", "buy", "sell", "set_shares", "set_cash")

EVENT_COLUMNS = ["date", "kind", "ticker", "shares", "price", "amount"]


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_COLUMNS)


def _norm_events(events: pd.DataFrame | None) -> pd.DataFrame:
    if events is None or len(events) == 0:
        return _empty_events()
    ev = events.copy()
    ev["date"] = pd.to_datetime(ev["date"])
    # stable order: by date, then input order (ledger insertion order)
    return ev.sort_values("date", kind="stable").reset_index(drop=True)


def replay(events: pd.DataFrame | None) -> tuple[dict, float, float]:
    """Run the ledger -> ({ticker: shares}, cash, net_contributions).

    Manual forces count their delta as contribution (in-kind transfer),
    valued at the event's recorded price (set_shares) or amount delta
    (set_cash).
    """
    shares: dict[str, float] = {}
    cash = 0.0
    contrib = 0.0
    for ev in _norm_events(events).itertuples(index=False):
        kind = ev.kind
        if kind == "deposit":
            cash += ev.amount
            contrib += ev.amount
        elif kind == "withdraw":
            cash -= ev.amount
            contrib -= ev.amount
        elif kind == "buy":
            shares[ev.ticker] = shares.get(ev.ticker, 0.0) + ev.shares
            cash -= ev.shares * ev.price
        elif kind == "sell":
            shares[ev.ticker] = shares.get(ev.ticker, 0.0) - ev.shares
            cash += ev.shares * ev.price
        elif kind == "set_shares":
            delta = ev.shares - shares.get(ev.ticker, 0.0)
            shares[ev.ticker] = ev.shares
            contrib += delta * ev.price          # in-kind flow, not return
        elif kind == "set_cash":
            delta = ev.amount - cash
            cash = ev.amount
            contrib += delta
        else:
            raise ValueError(f"unknown event kind: {kind!r}")
    shares = {t: s for t, s in shares.items() if abs(s) > 1e-12}
    return shares, float(cash), float(contrib)


def daily_state(events: pd.DataFrame | None,
                closes: pd.DataFrame) -> pd.DataFrame:
    """Account history on trading days -> DataFrame[value, flow, contributions].

    `closes` are raw close prices (columns = tickers); gaps are
    forward-filled. Days start at the first event. `flow` is the net
    external flow ON that day (cash deposits/withdrawals plus in-kind
    force deltas); `contributions` is its running total. Events dated
    on non-trading days take effect on the next trading day.
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

    tickers = sorted({t for t in ev["ticker"].dropna().unique()})
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
            d_shares.loc[day, e.ticker] += e.shares
            d_cash[day] -= e.shares * e.price
            running[e.ticker] = running.get(e.ticker, 0.0) + e.shares
            run_cash -= e.shares * e.price
        elif e.kind == "sell":
            d_shares.loc[day, e.ticker] -= e.shares
            d_cash[day] += e.shares * e.price
            running[e.ticker] = running.get(e.ticker, 0.0) - e.shares
            run_cash += e.shares * e.price
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
    if tickers:
        missing = [t for t in tickers if t not in px.columns]
        if missing:
            raise KeyError(f"no close prices for {missing}")
        holdings_value = (shares_path * px.loc[idx, tickers]).sum(axis=1)
    else:
        holdings_value = pd.Series(0.0, index=idx)
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
