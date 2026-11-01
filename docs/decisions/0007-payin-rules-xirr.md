# 0007 — Pay-in plans, rule alerts, XIRR, combined total

Date: 2026-10-24. Status: accepted. Builds on [0005](0005-ledger-v2-mirror.md).

## Context

RT’s USD account is bought in N dated tranches from a planned total:
some lines at once (`lump`), most in equal steps (`dca`), funded by a
T-bill fund that is sold down (`reservoir`). Each month the question is
“what do I buy for tranche k?” (whole shares only), “did any rule fire?”
(index well below its 52-week high → buy the next two tranches now; a
position well below average cost → pull its next tranche forward;
drift → rebalance, but only once the pay-in is done), and “what did my
money actually earn?”. The source repo (`~/projects/investments/portfolio`,
`scripts/pflib.py`) already computes all of this; Condor mirrors it so
the read-only account view answers the same questions with the same
numbers. Plan and rules come from that repo (format v1.1), like the
ledger and targets.

## Decision

1. **Pay-in is catch-up sizing on gross buy dollars.** For a `dca`
   ticker, the amount due through tranche k is
   `max(total × w × min(k + extra, N) / N − bought, 0)`, where `bought`
   is Σ shares × price over its buys (fees excluded). Whole shares,
   rounded half up; rounding this month is absorbed next month because
   `bought` is what was actually spent. `lump` tickers are due in full
   (plan − bought) and are listed whenever unfunded — on day 1 that is
   “buy the lump first”. The `reservoir` ticker funds the list.
2. **Budget = cash + reservoir value − reserve**, floored at 0, with
   reserve = reservoir weight × total + unfunded lump. Over budget →
   trim one share at a time from the ticker rounded up the most (ties:
   target order). After the buys, the reservoir trade settles the cash:
   a shortfall sells `ceil(shortfall / price)` reservoir shares, spare
   cash buys `floor(spare / price)` (day 1’s “the rest goes to the
   reservoir”; later months’ leftovers are under one share).
3. **Complete = all N dates have passed and the full-plan buy list
   (through N, within budget) buys nothing.** The source repo’s first
   rule (“every line ≥ 98% of plan”) never passes with whole shares
   when a share is large relative to its line (RT’s RSP ends at 93%);
   it was replaced 2026-10-24 and Condor uses the replacement. Drift
   rules are muted until complete (being off target is the point of a
   pay-in). Progress, drift and completion are judged per **line** (a
   group of tickers; default one ticker per line).
4. **Rules are data, evaluated fresh**, firing on strictly `>` the
   threshold: `below_52w_high` = (high − last) / high over raw closes
   dated after last − 365 days; `below_avg_cost` = (avg − last) / avg;
   `drift` = |line value / total − line target|, total including cash,
   every line checked. A fired `accelerate` rule extends the buy list:
   untargeted → through `k_due + tranches` (capped at N; several fired
   → the largest); targeted → `extra[ticker] += tranches` (several →
   the largest per ticker). Nothing is bought automatically.
5. **XIRR from the ledger’s external flows** (deposits, withdrawals,
   forces) and the final value, ACT/365, solved by `scipy.optimize.brentq`;
   not shown under 90 days (annualizing a few weeks misleads).
6. **Combined total across currencies** converts each account at the
   latest daily FX close from the price store (`EURUSD=X`); amounts
   never leave the machine — only the FX ticker is fetched.
7. **Mirrors stay read-only.** Plan and rules arrive by import; the
   buy list is advice. Manual accounts get no pay-in UI in v1.

## Alternatives rejected

- *Sizing on current value instead of gross buys:* market moves would
  change what is “due”, and rounding would never self-correct.
- *Automatic rule actions:* violates read-only mirrors and RT’s “confirm
  every trade” habit.
- *Fractional plans:* dropped 2026-10-24 (RT buys whole shares).
- *Completion at 98% of plan per line:* unreachable with whole shares
  for expensive shares in small lines (see §3).

## Reopens if

- Manual accounts need pay-in plans edited in the UI.
- Unequal tranches, or tranches defined in dollars instead of k/N.
- A base currency other than USD/EUR, or FX conversions inside accounts.
