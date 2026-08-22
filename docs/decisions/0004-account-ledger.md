# 0004 — Accounts are ledgers; drafts are configurations

Date: 2026-08-22. Status: accepted.

## Context

RT wants to track a (pretend or mirrored-real) account: dollar amounts,
per-asset holdings, value at last close, return over time that does NOT
count injected cash as gain, actual-vs-setpoint allocation drift, and
whole-share rebalancing/transition reports the user confirms or edits.
The optimizer and forecaster must keep working without any account.

## Decision

1. **Two concepts, not one.** `SavedPortfolio` (weights + settings)
   remains *configuration only* — it is also the "draft portfolio":
   anything you build by hand or by clicking the frontier/CAL. A new
   **`Account`** is *money*: an append-only ledger of `AccountEvent`s
   (deposit, withdraw, buy, sell, set_shares, set_cash) plus a setpoint
   (`AccountTarget` rows; cash weight is the implicit remainder —
   which is exactly what a CAL draft produces, since CAL weights are
   total-wealth fractions summing to the risky share).

2. **Everything is derived from the ledger** by pure engine functions
   (`condor/accounting.py`): positions and cash by replay; a daily
   value series from share history × raw closes (the store keeps raw
   `close` for exactly this — valuation uses close, statistics use
   adj_close); net contributions; time-weighted return by daily
   geometric linking, `r_t = V_t / (V_{t-1} + F_t) - 1`, so deposits
   move value but never return. Manual forces (`set_shares`/`set_cash`)
   are treated as in-kind flows: the delta (valued at the recorded
   price) counts as contribution, not gain.

3. **One rebalance mechanism, two entry points.**
   `rebalance_plan(shares, prices, cash, target_weights)` returns
   whole-share trades at last close (round to nearest, then trim the
   largest buys one share at a time until cash stays non-negative).
   "Rebalance to setpoint" calls it with the stored target;
   "transform into this draft" first copies the draft's weights into
   the target (COPY, not link — editing a saved portfolio later must
   not silently move an account's setpoint), then shows the same plan.
   Confirming a plan writes buy/sell events with user-editable
   numbers; nothing trades implicitly.

4. **Schema allows many accounts per user; UI v1 shows one**
   (auto-created "My account"). A selector is cheap later; the flows
   are identical.

## Alternatives rejected

- *Store positions as mutable rows, no ledger*: cannot distinguish
  contributions from returns, cannot reconstruct history, cannot
  honor "manually intervene" without losing the audit trail.
- *Link Account.target to a SavedPortfolio FK*: surprise-at-a-distance
  when the draft is edited or deleted; copy semantics are boring and
  predictable.
- *Track value snapshots in the DB*: derivable from ledger + price
  store; storing results invites drift between the two (same reasoning
  as ADR 0002 and the AnalysisSnapshot deferral).

## Reopens if

- Real brokerage import (lot-level cost basis, dividends, splits at
  the account level) — the ledger grows kinds, replay grows rules.
- Multi-currency or fixed-income positions.
- Tax-aware rebalancing (lot selection) — plan needs lots, not totals.
