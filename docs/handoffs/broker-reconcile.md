# Handoff — `feature/broker-reconcile`

**Merged 2026-11-01**; branch and worktree removed.

| | |
|---|---|
| Branch | `feature/broker-reconcile` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/broker-reconcile` |
| Base | `main` @ `a7eb3fb` |
| Created | 2026-11-01 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory is a
git worktree: it *is* this branch — do not `git checkout` another branch here.
Never run `fly` commands from this directory.

## Goal

The step that decides whether a mirrored ledger is right is “does it match my
broker to the cent?” Today that’s done by hand across three broker pages plus
mental arithmetic. In its first month of real use it took a person typing
their broker’s cash figure to find three missing events. Add a small
**“Check against your broker”** panel on mirror accounts: what the broker
should show if the ledger is complete, and two boxes to type what it does show,
with a clear match/mismatch.

Read-only, no format change, a general feature for anyone with a mirror account.
Nothing typed is stored.

**Read:** `docs/decisions/0005-ledger-v2-mirror.md`, `docs/LEDGER-FORMAT.md`.

## Decisions already made

1. **Brokers book cash to the cent; Condor’s ledger keeps exact fills.** A 1-share
   fill at 80.355 debits 80.36 at the broker while average cost stays 80.355. So
   “expected at your broker” needs its own replay. **Do not change `ledger_state`,
   `daily_state` or the headline tiles** (their identity tests must not move).
2. **Rounding:** half up, per event, on exact decimals. Use `decimal.Decimal(str(x))`,
   because binary floats get half-cents wrong. BUY debit = round(qty × price + fees);
   SELL/REDEEM credit = round(qty × price − fees); DIV/INTEREST credit = round(amount
   − fees); DEPOSIT/WITHDRAW/FEE round(amount). `set_cash` sets the balance;
   `set_shares` doesn’t move cash.
3. **Expected value** = Σ round(qty × shown close) + expected cash. Shown close is the
   close rounded to 2 dp (4 dp under $1), because stored closes carry float noise
   (101.199997 is 101.20). A bill counts at its accreted value (`bill_prices`).
4. **Comparison:** cash matches if within $0.005 of what was typed. Value matches
   within $0.01 per position plus $0.01, since brokers round differently. Cash is
   the authoritative check; say so.
5. **The server does the arithmetic** (no numerics in JS). Amounts go in a POST body,
   never a query string, and are never stored or logged.

## Scope

**In** — commit at the end of each phase.

### Phase 1 — engine (`condor/accounting.py`)

- `broker_cash(events) -> float`, per decisions 1–2.
- `reconcile(events, prices, reported_cash=None, reported_value=None) -> dict`:
  `{cash, value, positions: [{ticker, qty, price, value}], as_of_note…, cash_check,
  value_check}`; each check is null when nothing was typed, else `{reported,
  expected, difference, match}`.
- Pure; a verification test per rule below.

### Phase 2 — web (`web/explorer/account.py`)

- `POST /api/account/reconcile?account=<uuid>` with optional `{cash, value}`. Allowed on
  mirrors (a preview, like forecast; it writes nothing). Owner-scoped like the other
  account endpoints; refuses non-numeric input with the usual 400. A manual
  (non-mirror) account gets 400: “This check is for accounts mirroring a broker.”
- Response adds `as_of` (last close), `last_event` (the latest ledger date) and
  `imported_at`.

### Phase 3 — UI (`account.html`, `account.js`)

A card on mirror accounts only, after the pay-in and rules cards. Heading **“Check
against your broker”**. One line: “If your ledger is complete, your broker should show
these. Cash is the number to trust; value moves with prices.”

- Expected cash and expected value, with “at the {as_of} close”.
- Two number inputs: “Cash your broker shows”, “Account value your broker shows”, and a
  **Check** button. Typed values stay in the page (not saved, not in the URL).
- Result in words, never colour alone:
  - “Matches to the cent.”
  - “Off by {amount}: your broker shows {more/less} cash than your ledger expects. Your
    ledger’s last event is {last_event}, imported {imported_at}. Look for events not
    yet recorded, such as a dividend, interest, a fee or a fill.”
  - Value mismatch adds: “Value also depends on the price date: compare after the close
    of {as_of}, or check cash first.”
- A collapsed “Positions to compare” with Ticker · Quantity · Close · Value.
- Tile vs panel can differ by a cent. When they do, say why once: “Your total above uses
  exact fill prices; your broker rounds each fill to the cent.”

Follow `docs/research/ui-conventions.md`. Don’t touch `app.js`, `optimize.html` or
`condor/model.py` (another agent is working there).

### Phase 4 — docs

`README.md` (My account paragraph). **Don’t edit `BACKLOG.md`**; the handoff session does
that at merge, because parallel branches keep colliding there. Don’t run `/code-review`
either: the handoff session rebases and runs it (see `docs/WORKTREES.md`), then sends you
the findings. Review your own diff by hand before reporting.

**Out:** any new ledger or format field, open orders, order tickets, storing what’s typed,
changing cash or value anywhere else, real ledgers or amounts in the repo.

## Acceptance

Hand-checked; pin each in a test.

- Ledger: DEPOSIT 200; BUY AAA 1 @ 80.355; BUY BBB 18 @ 2.18; DIV AAA 15.75; INTEREST
  0.01. Booked: 200 → 119.64 (debit 80.36) → 80.40 (39.24) → 96.15 → **96.16**. The exact
  engine says 96.165; `ledger_state` must still say so.
- At closes AAA 76.83, BBB 2.21: positions 76.83 and 39.78, **expected value 212.77**.
- Typed cash 96.16 → match; typed value 212.77 → match. Typed cash 80.40 → **off by
  −15.76**, not a match. Typed cash 96.17 → off by +0.01, not a match.
- Half-up cases where float rounding is wrong: 1 @ 1.005 → 1.01; 3 @ 1.115 → 3.35;
  1.5 @ 33.333 sell → 50.00. With fees: 2.5 @ 100 fee 1 → debit 251.00; 1.5 @ 110 fee
  0.50 sell → credit 164.50.
- Close noise: 101.199997 shows 101.20; 0.87654 shows 0.8765.
- A bill: value uses the accreted price; REDEEM credits nominal. A `set_cash` then events
  replays correctly.
- Web: mirror → 200 with checks; nothing typed → checks null; manual account → 400;
  foreign id → 404; bad input → 400; no row anywhere changes (assert no writes).
- Suites at least at baseline (2026-11-01, base `a7eb3fb`, this worktree): `pytest
  tests/` **445 passed, 4 skipped**; `manage.py test explorer` **232 OK**; `check`
  clean; `makemigrations --check --dry-run` clean (no migration expected).

## Status

- [x] Baseline recorded (445 passed / 4 skipped; 232 OK)
- [x] Phase 1 engine
- [x] Phase 2 web
- [x] Phase 3 UI (node --check only; no real browser)
- [x] Phase 4 docs + hand review of own diff

Change from the handoff session (not a deviation): a third check,
**securities value** (`securities_check`, POST `securities`, third input
"Securities value your broker shows", expected 116.61 on the brief's ledger).

Review round (handoff session rebased onto main, ran the code review and a
real-browser pass with a real account: match, mismatch and positions table
render, no console errors, three real figures matched to the cent). Findings:
1. Bills: FIXED. Value = round(nominal x exact accreted price); the old test
   pinned the wrong number (4 dp price rounding gave 9,799.00 for 9,799.45).
2. Cash independent of market data: FIXED. Cash and `cash_check` always return;
   a price failure gives 200 with `prices_error`, securities/value/positions and
   their checks null. Closes are fetched only for held non-bill tickers.
3. Bad input: FIXED. `validity.badInput` names the box; no request, no verdict.
4. Error banner: FIXED. Reconcile errors show in the card (`rc-error`);
   `showError` is no longer touched by this panel.
5. Stale figures: FIXED. `clearReconcile()` on account switch bumps `reconSeq`
   and clears figures/table/verdict; a failed Check clears the old verdict.
6. No numerics in JS: FIXED. The server returns `rounding: {cash, prices}`; the
   note's wording follows it (cash-rounding, price-rounding, or both).
7. Quantity display: FIXED. Same `toLocaleString()` as the holdings table;
   bills read "N nominal".
8. `_typed_amount`: FIXED. OverflowError caught; strings must match a plain
   decimal regex (rejects "1_000").
9. Efficiency: FIXED. `reconcile` takes `state`/`bills` from the view. The
   page-load round trip (one extra POST on a mirror) is left as is, per the
   handoff session.
10. Dead code: FIXED. Removed `hasattr` branch, `currency`, `exact_cash`,
   `exact_value`, `as_of` through the engine (set in the view); `_is_set` and
   `math.isfinite` used.
Unverified here: the JS changes (node --check only, no browser).

Notes: `reconcile` also returns `securities`, `rounding`. The "value also depends on the price date" line also appears on
a securities mismatch.

## Questions for the handoff session

- (none yet)

## Return protocol

Keep Status current. Commit locally; **do not push, open a PR or merge**. Report: last
commit, test counts vs baseline, deviations, renamed strings, anything unverified. The
handoff session reviews, merges and pushes.
