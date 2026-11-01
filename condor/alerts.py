"""Rule alerts: did a rule fire? (ADR 0007 §4)

Pure functions. Rules are `condor.ledger_io.RuleSpec`-shaped (id, rule,
ticker, threshold, action, tranches, targets). Thresholds are percent
(percentage points for drift) and every rule fires on strictly `>`
the threshold; `measured` is in the same unit so the two compare
directly. Float noise is absorbed by a 1e-9 tolerance (12 − 9.6 over 12
is 20.000000000000004 in floating point, and "exactly 20%" must not
fire).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

_TOL = 1e-9


def below_high(closes: pd.Series, as_of=None, days: int = 365) -> float:
    """(high − last) / high over closes dated after last date − `days`,
    as a fraction >= 0. `last` is the final close on/before `as_of`
    (default: the series end). NaN when there is no close."""
    s = closes.dropna().sort_index()
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    if s.empty:
        return float("nan")
    last_day = s.index[-1]
    window = s[s.index > last_day - pd.Timedelta(days=days)]
    high = float(window.max())
    return (high - float(s.iloc[-1])) / high if high > 0 else float("nan")


@dataclass(frozen=True)
class RuleResult:
    id: str
    rule: str
    ticker: str
    threshold: float
    measured: float | None        # percent (pp for drift); None = not measurable
    fired: bool
    muted: bool
    action: str
    tranches: int | None
    targets: tuple
    breaches: tuple = field(default=())   # drift: ((line, weight %, target %), ...)


def _exceeds(measured, threshold) -> bool:
    return measured is not None and measured > threshold + _TOL


def _spec(v):
    """(weight, timing, line) from a TargetSpec or a plain tuple."""
    return v[0], v[1], v[2]


def evaluate(rules, *, holdings: pd.DataFrame, weights, targets,
             index_closes: dict, payin_active: bool) -> list[RuleResult]:
    """Evaluate every rule against the account's current state.

    holdings     open positions, DataFrame indexed by ticker with `price`
                 and `avg_cost` (as `accounting.holdings`)
    weights      actual weight per ticker incl. cash in the total
                 (`accounting.allocation()["weight"]`)
    targets      {ticker: (weight, timing, line)}
    index_closes {ticker: close Series} for below_52w_high rules
    payin_active a plan exists and is not complete: drift is muted
    """
    out = []
    for r in rules:
        measured, fired, muted, breaches = None, False, False, ()
        if r.rule == "below_52w_high":
            s = index_closes.get(r.ticker)
            if s is not None:
                m = below_high(s)
                measured = None if pd.isna(m) else 100 * m
        elif r.rule == "below_avg_cost":
            if (r.ticker in holdings.index
                    and holdings.loc[r.ticker, "shares"] > 0
                    and holdings.loc[r.ticker, "avg_cost"] > 0):
                avg = float(holdings.loc[r.ticker, "avg_cost"])
                last = float(holdings.loc[r.ticker, "price"])
                measured = 100 * (avg - last) / avg
        elif r.rule == "drift":
            actual: dict[str, float] = {}
            want: dict[str, float] = {}
            for t, v in targets.items():
                w, _, line = _spec(v)
                want[line] = want.get(line, 0.0) + w
                actual[line] = actual.get(line, 0.0) + float(
                    weights.get(t, 0.0))
            if want:
                dev = {ln: 100 * abs(actual[ln] - want[ln]) for ln in want}
                measured = max(dev.values())
                breaches = tuple(
                    (ln, 100 * actual[ln], 100 * want[ln])
                    for ln in want if _exceeds(dev[ln], r.threshold))
        fired = _exceeds(measured, r.threshold)
        if r.rule == "drift" and payin_active:
            muted, fired = True, False
        out.append(RuleResult(
            r.id, r.rule, r.ticker, r.threshold, measured, fired, muted,
            r.action, r.tranches, tuple(r.targets), breaches))
    return out


def accelerations(results, k_due: int, n: int) -> tuple[int, dict[str, int]]:
    """Fold fired `accelerate` rules into the buy list -> (through, extra).

    No fired rule: through = max(k_due, 1). Untargeted: through = k_due +
    tranches (the largest if several), capped at N. Targeted:
    extra[ticker] = tranches (the largest per ticker). The two kinds add,
    because a ticker's due uses min(through + extra, N)."""
    through = max(k_due, 1)
    extra: dict[str, int] = {}
    untargeted = 0
    for r in results:
        if not (r.fired and r.action == "accelerate" and r.tranches):
            continue
        if r.targets:
            for t in r.targets:
                extra[t] = max(extra.get(t, 0), r.tranches)
        else:
            untargeted = max(untargeted, r.tranches)
    if untargeted:
        through = k_due + untargeted
    return min(through, n), extra
