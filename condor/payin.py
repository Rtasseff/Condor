"""Pay-in engine: whole-share catch-up buy lists for a tranche plan.

ADR 0007 §1-3, ported from the source repo's `pflib` (`tranche_orders`,
`trim_to_budget`, `reserve_needed`, `spendable`, `usfr_sale`,
`payin_complete`). Pure functions over a plan, the gross dollars already
bought, and prices; no Django, no I/O. Amounts are in the account's own
currency.

Vocabulary: a ticker has a *timing* — `dca` (equal tranches), `lump`
(all at once, first), `reservoir` (the fund that is sold down to pay for
the rest) — and belongs to a *line* (a group key; default one ticker per
line). Progress is judged per line; orders are per ticker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

_EPS = 1e-9
ORDER_COLUMNS = ["due", "qty", "price", "amount", "note"]
NOTE_SMALL = "under half a share due; carries forward"
NOTE_TRIM = "1 share trimmed to stay within cash; carries forward"


@dataclass(frozen=True)
class PayInPlan:
    total: float
    dates: tuple[date, ...]
    weights: dict[str, float]     # fraction of total, per ticker, in target order
    timing: dict[str, str]        # "dca" | "lump" | "reservoir" | ""
    lines: dict[str, str]         # ticker -> line key

    @classmethod
    def build(cls, total, dates, specs) -> "PayInPlan":
        """`specs`: iterable of (ticker, weight, timing, line) in target
        order."""
        specs = list(specs)
        return cls(
            float(total), tuple(dates),
            {t: float(w) for t, w, _, _ in specs},
            {t: tm for t, _, tm, _ in specs},
            {t: (ln or t.lower()) for t, _, _, ln in specs})

    @property
    def n(self) -> int:
        return len(self.dates)

    def tickers(self, timing: str) -> list[str]:
        return [t for t in self.weights if self.timing.get(t) == timing]

    @property
    def reservoir(self) -> str | None:
        r = self.tickers("reservoir")
        return r[0] if r else None


# ---------------------------------------------------------------- inputs


def gross_bought(events: pd.DataFrame | None) -> dict[str, float]:
    """Σ shares × price over buys, per ticker (fees excluded: catch-up
    sizing works on dollars actually spent on the shares)."""
    if events is None or len(events) == 0:
        return {}
    buys = events[events["kind"] == "buy"]
    out: dict[str, float] = {}
    for t, s, p in zip(buys["ticker"], buys["shares"], buys["price"]):
        out[t] = out.get(t, 0.0) + float(s) * float(p)
    return out


def tranches_due(plan: PayInPlan, as_of) -> int:
    """How many tranche dates are on or before `as_of`."""
    d = pd.Timestamp(as_of).date()
    return sum(1 for x in plan.dates if x <= d)


# -------------------------------------------------------------- progress


def progress(plan: PayInPlan, bought: dict, as_of) -> pd.DataFrame:
    """Per LINE -> DataFrame[timing, tickers, plan, bought, pct,
    scheduled]; pct is percent of plan. `scheduled` = plan × k_due / N
    for dca, plan once k_due >= 1 for lump, NaN for the reservoir (and
    for plain setpoints)."""
    k = tranches_due(plan, as_of)
    n = max(plan.n, 1)
    rows: dict[str, dict] = {}
    for t, w in plan.weights.items():
        r = rows.setdefault(plan.lines[t], {
            "timing": plan.timing[t], "tickers": [], "plan": 0.0,
            "bought": 0.0})
        r["tickers"].append(t)
        r["plan"] += plan.total * w
        r["bought"] += float(bought.get(t, 0.0))
    for r in rows.values():
        r["pct"] = 100 * r["bought"] / r["plan"] if r["plan"] > 0 else 0.0
        tm = r["timing"]
        r["scheduled"] = (r["plan"] * k / n if tm == "dca"
                          else (r["plan"] if k >= 1 else 0.0) if tm == "lump"
                          else float("nan"))
        r["tickers"] = tuple(r["tickers"])
    return pd.DataFrame.from_dict(
        rows, orient="index",
        columns=["timing", "tickers", "plan", "bought", "pct", "scheduled"])


# ----------------------------------------------------------- the buy list


def reserve_needed(plan: PayInPlan, bought: dict) -> float:
    """Cash/reservoir that must stay put: the reservoir's plan plus every
    unfunded lump."""
    need = 0.0
    for t, w in plan.weights.items():
        if plan.timing[t] == "reservoir":
            need += plan.total * w
        elif plan.timing[t] == "lump":
            need += max(plan.total * w - bought.get(t, 0.0), 0.0)
    return need


def spendable(plan: PayInPlan, bought: dict, cash: float,
              reservoir_value: float) -> float:
    """Budget for the tranche: cash + reservoir value − reserve, floored
    at 0."""
    return max(max(cash, 0.0) + reservoir_value
               - reserve_needed(plan, bought), 0.0)


def round_qty(dollars: float, price: float) -> int:
    """Nearest whole share, half up (rounding is absorbed next month: the
    amount due is net of what was actually bought)."""
    if dollars <= 0 or price <= 0:
        return 0
    return int(math.floor(dollars / price + 0.5 + _EPS))


def _price(prices, t):
    try:
        p = prices[t]
    except KeyError:
        p = None
    if p is None or pd.isna(p):
        raise KeyError(f"no price for {t}")
    return float(p)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ticker"] + ORDER_COLUMNS
                        ).set_index("ticker")


def lump_orders(plan: PayInPlan, bought: dict, prices) -> pd.DataFrame:
    """Unfunded lump tickers: due = plan − bought, whole shares. Funded
    lumps are not listed."""
    rows = []
    for t in plan.tickers("lump"):
        due = plan.total * plan.weights[t] - bought.get(t, 0.0)
        if due <= _EPS:
            continue
        p = _price(prices, t)
        q = round_qty(due, p)
        rows.append({"ticker": t, "due": due, "qty": q, "price": p,
                     "amount": q * p, "note": NOTE_SMALL if q == 0 else ""})
    return _frame(rows)


def _trim_to_budget(rows: list[dict], budget: float) -> None:
    """Drop one share at a time from the most rounded-up buy (largest
    amount − due; ties to the first in target order) until it fits."""
    while sum(r["amount"] for r in rows) > budget + 1e-6:
        held = [r for r in rows if r["qty"] > 0]
        if not held:
            break
        r = max(held, key=lambda r: r["amount"] - r["due"])  # first on ties
        r["qty"] -= 1
        r["amount"] = r["qty"] * r["price"]
        r["note"] = NOTE_TRIM


def tranche_orders(plan: PayInPlan, bought: dict, prices, through: int,
                   extra: dict | None = None, budget: float | None = None
                   ) -> pd.DataFrame:
    """Whole-share buy list that brings every dca ticker to
    min(through + extra, N)/N of its plan, net of gross dollars already
    bought. -> DataFrame[due, qty, price, amount, note] indexed by
    ticker, dca tickers only, target order. `budget` caps the spend."""
    extra = extra or {}
    n = max(plan.n, 1)
    rows = []
    for t in plan.tickers("dca"):
        k = min(through + extra.get(t, 0), n)
        due = max(plan.total * plan.weights[t] * k / n
                  - bought.get(t, 0.0), 0.0)
        p = _price(prices, t)
        q = round_qty(due, p)
        rows.append({"ticker": t, "due": due, "qty": q, "price": p,
                     "amount": q * p,
                     "note": NOTE_SMALL if q == 0 and due > 0 else ""})
    if budget is not None:
        _trim_to_budget(rows, budget)
    return _frame(rows)


def reservoir_trade(plan: PayInPlan, cash: float, prices, buy_total: float
                    ) -> dict | None:
    """Settle the cash after the buys (lump + tranche) in the reservoir
    ticker. Buys > cash -> SELL ceil((buys − cash)/price); else BUY
    floor((cash − buys)/price) (the rest goes to the reservoir). None
    when there is no reservoir, no price, or nothing to trade."""
    t = plan.reservoir
    if t is None:
        return None
    try:
        p = _price(prices, t)
    except KeyError:
        return None
    cash = max(cash, 0.0)
    if buy_total > cash + _EPS:
        q = int(math.ceil((buy_total - cash) / p - _EPS))
        side = "SELL"
    else:
        q = int(math.floor((cash - buy_total) / p + _EPS))
        side = "BUY"
    if q <= 0:
        return None
    return {"side": side, "ticker": t, "qty": q, "price": p,
            "amount": q * p}


def is_complete(plan: PayInPlan, bought: dict, prices, budget: float,
                as_of) -> bool:
    """Every tranche date has passed and the full-plan buy list (through
    N, within `budget`) buys nothing. A missing price -> not complete."""
    if plan.n == 0 or tranches_due(plan, as_of) < plan.n:
        return False
    try:
        orders = tranche_orders(plan, bought, prices, plan.n, budget=budget)
    except KeyError:
        return False
    return bool((orders["qty"] == 0).all())
