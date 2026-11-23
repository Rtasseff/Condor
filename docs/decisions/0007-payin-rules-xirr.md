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

## Amendment 2026-11-23: bought through, followed, no reservoir buy-back

A fired accelerate rule was acted on, but the panel kept saying "Fired",
titled the list for the tranche now due, and told the investor to put
spare cash back in the reservoir right after selling it. Four changes,
all display or settle-the-cash only; the buy-list sizing in §1 and §4
is unchanged.

1. **Bought through N** (`payin.bought_through`): the largest k in 0..N
   for which the dca buy list through k buys nothing, judged with the
   list's own half-up whole-share test (0.49 of a share still due counts
   as bought, 0.51 does not). It measures holdings, not cash: no budget,
   no lump, no reservoir. Unlike `k_due` it survives an acceleration. A
   missing price is a `KeyError`; the API reports `null` instead.
2. **Followed** (`alerts.rule_target`, then `followed = bought_through >=
   target`). The target is the tranche a fired accelerate rule asks to
   be bought through: untargeted `min(k_due + tranches, N)`, targeted
   `min(max(k_due, 1) + tranches, N)`, i.e. what `accelerations` gives
   for that rule alone. A targeted rule is judged on its own tickers
   only; an untargeted one on every dca ticker. The page shows
   "Fired · followed". `followed` is `null` when not fired, an alert
   rule, muted, no plan, or a price is missing.
3. **The list is titled by what is left**: "Left to buy through tranche
   K". The list itself is unchanged.
4. **No reservoir buy-back after day 1** (supersedes the "spare cash
   buys `floor(spare / price)`" half of §2). A shortfall still sells
   reservoir shares, exactly as before. Spare cash buys reservoir shares
   only while the reservoir has never been bought (`bought[reservoir] ==
   0`: day 1, when it is funded); afterwards the cash is held until the
   next tranche, which is what the investor's own tool does. Not inferred
   from shares held: a reservoir sold down to zero is still funded. The
   cash left after the list and the trade is `payin.leftover_cash`,
   returned by `/api/account/tranche` as `carry` and shown as a note.

**Pending decision O7 (the owner's, not resolved here).** What happens
at the *next* tranche date while an untargeted rule stays fired:

- *Reading A (implemented, stands until the owner answers):* "stay two
  ahead while fired". `through = k_due + tranches`, re-evaluated every
  day, so the target moves up with each tranche date.
- *Reading B:* "once per fall". A firing buys the next two unbought
  tranches once, and the rule re-arms when the index closes back within
  its threshold.

Nothing in the amendment assumes B, and the page says nothing about the
next date's list.
