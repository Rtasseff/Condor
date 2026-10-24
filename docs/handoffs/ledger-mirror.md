# Handoff — `feature/ledger-mirror`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/ledger-mirror.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/ledger-mirror` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/ledger-mirror` |
| Base | `main` @ `5b1a39e` |
| Created | 2026-10-23 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Make a Condor account a **faithful, read-only mirror of an external
CSV ledger**, driven by RT's real portfolio: a USD ETF account
(`etrade`) and a EUR account of Spanish T-bills (`tesoro`). That
portfolio lives in its own repo (`~/projects/investments/portfolio`),
which stays the record; Condor imports it one-way, locally, and shows
what the current ledger can't: average cost, realized/unrealized gain,
dividends/interest/fees as return, per-account currency, and bills that
accrete to nominal. This is bucket A of three (B = fractional plans,
rule alerts, pay-in tracker, XIRR, FX total; C = statistics fixes) —
do not start B or C here.

**Read these before coding** (they are the spec; this brief adds the
build decisions):

- `docs/decisions/0005-ledger-v2-mirror.md` — the design (committed with
  this brief). It reopens ADR 0004; read 0004 too.
- `docs/LEDGER-FORMAT.md` — exchange format v1, the contract with the
  other repo. Do not change it; if you think it's wrong, park a
  question.
- `tests/fixtures/ledger_sample.csv`, `ledger_sample_targets.csv` —
  synthetic sample (invented tickers AAA/BBB). Its hand-checked
  numbers are in § Acceptance.

## Scope

**In** — in this order; commit at the end of each phase.

### Phase 1 — account engine (`condor/accounting.py`)

Pure functions, no Django. Existing functions keep their signatures
and existing tests pass **untouched**.

- `KINDS` += `dividend`, `interest`, `fee`, `redeem`.
  `EVENT_COLUMNS` += `fees`, `maturity`. `_norm_events` fills a missing
  `fees` column (or NaN) with 0 and a missing `maturity` with NaT, so
  six-column frames from today's callers still work.
- New frozen dataclasses:
  ```python
  @dataclass(frozen=True)
  class BillLot:
      settle: date; maturity: date; nominal: float; cost: float

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
      bills: dict[str, list[BillLot]] # open lots per bill ticker
      def avg_cost(self, ticker) -> float: ...   # cost / shares; 0 if flat
  ```
- `ledger_state(events) -> LedgerState` — the one replay loop. Rules
  (all amounts in the account's currency; the engine has no notion of
  currency):

  | kind | cash | contributions | basis / other |
  |---|---|---|---|
  | deposit / withdraw | ± amount | ± amount | — |
  | buy | − (shares × price + fees) | — | cost += shares × price + fees; if `maturity` is set, append a `BillLot(settle=date, maturity, nominal=shares, cost=shares × price + fees)` |
  | sell | + (shares × price − fees) | — | avg = cost/shares before; cost −= avg × shares; realized += proceeds − avg × shares; bill: scale every open lot (nominal and cost) by (1 − shares/held) |
  | redeem | as sell | — | as sell; raise `ValueError` if the ticker is not a bill |
  | dividend / interest | + (amount − fees) | — | income[ticker or "CASH"] += amount; charges += fees |
  | fee | − amount | — | charges += amount |
  | set_shares | — | += delta × price (unchanged) | delta > 0: cost += delta × price. delta < 0: cost −= avg × \|delta\| **and realized += \|delta\| × (price − avg)** (an in-kind withdrawal at the recorded price — this keeps the identity below exact). Raise on a bill ticker. |
  | set_cash | unchanged | unchanged | — |

  `trade_fees` += fees on buy/sell/redeem. A position whose shares fall
  below 1e-12 drops out of `shares`, `cost`, `bills` (realized/income
  stay). Like today, the engine trusts its inputs (validation is the
  boundary's job) except for the two `ValueError`s above and unknown
  kinds.
- `replay(events)` becomes `s = ledger_state(events); return s.shares,
  s.cash, s.contributions` — same tuple as today.
- `bill_tickers(events) -> set[str]` — tickers having any buy with a
  non-null `maturity`.
- `accrued_value(lot, on) -> float` — `cost + (nominal − cost) ×
  clip((on − settle).days / (maturity − settle).days, 0, 1)`.
- `bill_prices(events, index) -> DataFrame` — for each bill ticker and
  each day in `index`, the value per 1 nominal of the lots held at the
  end of that day (Σ accrued_value / Σ nominal); 0.0 when none is
  held. A straightforward loop is fine (few days × few lots).
- `holdings(state, prices) -> DataFrame` indexed by ticker:
  `[shares, price, value, cost, avg_cost, unrealized, unrealized_pct,
  realized, income]`. `prices` covers every open ticker (bills at their
  `bill_prices` value). `unrealized_pct = value / cost − 1`.
- `daily_state(events, closes)` — **same signature**. Bills are valued
  internally from `bill_prices(events, idx)`; `closes` need not (and
  from the web never will) contain bill columns, and the "missing
  closes" `KeyError` ignores bill tickers. Cash moves per the table
  above; `flow` is unchanged (deposit/withdraw/forces only), so income
  raises value without a flow (return) and fees lower it (negative
  return). Keep the existing "events on non-trading days land on the
  next index day" behaviour. NaN-safe: multiply after `fillna(0)`.
- `allocation`, `rebalance_plan`, `contribution_plan`,
  `time_weighted_return`: untouched.

### Phase 2 — format I/O (`condor/ledger_io.py`, new, pure)

- `class LedgerFormatError(ValueError)` carrying `errors: list[str]`,
  each prefixed `line N:` (header = line 1). Collect **all** errors
  before raising; never partial results.
- `read_ledger(src, today=None) -> dict[label, LedgerImport]` where
  `LedgerImport = (currency: str, events: DataFrame[EVENT_COLUMNS + note])`
  in file order. `src` is a path or text stream; `today` defaults to
  `date.today()` (tests inject it — the fixture is dated 2027–28).
- Every rule in `docs/LEDGER-FORMAT.md` is enforced. Also:
  - exact header set (unknown or missing column → error);
  - after the per-row checks, a running replay per account in file
    order (via `ledger_state` over the growing prefix, or an
    equivalent running tally): cash < −1e-6 or any position < −1e-9
    at any row → error naming the row;
  - REDEEM: date ≥ that bill's maturity; qty ≤ nominal held;
  - bill ticker regex `^[A-Z][A-Z0-9]*-\d{4}-\d{2}-\d{2}$`; other
    tickers use the web's `TICKER_RE` (copy the pattern; condor must
    not import from web);
  - note with a run of 7+ digits → error "looks like an identifier".
- Side → engine kind: DEPOSIT→deposit (amount=qty), WITHDRAW→withdraw,
  DIV→dividend (ticker, amount=qty, fees), INTEREST→interest (ticker
  or None for CASH), FEE→fee (ticker or None), BUY→buy (shares=qty,
  price, fees, maturity), SELL→sell, REDEEM→redeem (shares=qty,
  price=1, fees). Cash tickers are stored as None/"" — export maps
  them back to `CASH`.
- `read_targets(src) -> dict[label, dict[ticker, weight]]`, same error
  style.
- `write_ledger(accounts, dst)` where `accounts` = iterable of
  `(label, currency, events)`. Numbers formatted with up to 6 dp,
  trailing zeros stripped (`1000`, `970.6`, `0.9706`). Raise
  `ValueError` naming dates if an account has `set_shares`/`set_cash`
  events (v1 has no such sides).

### Phase 3 — storage and commands

- Migration on `web/explorer/models.py`:
  - `Account`: `label` (CharField 40, blank, default ""), `currency`
    (CharField 3, default "USD"), `mirror` (Boolean, default False),
    `imported_at` (DateTimeField, null). Conditional
    `UniqueConstraint(owner, label)` where `label != ""`.
  - `AccountEvent`: `KINDS` extended; `fees` (Float, default 0);
    `maturity` (DateField, null); `ticker` max_length 10 → 24.
    `events_frame()` emits the two new columns.
  - Admin: show the new Account fields.
- `web/explorer/management/commands/import_ledger.py`:
  `import_ledger LEDGER [--targets TARGETS] --user USERNAME --replace
  [--dry-run] [--today YYYY-MM-DD]`.
  - `--replace` is required (v1 has no merge mode); without it, a
    `CommandError` saying so. `--today` exists for tests and back-dated
    checks; default is the real date.
  - Parse both files first (pure module). Any error → print every
    error, exit non-zero, write nothing.
  - One `transaction.atomic()` for all accounts. Per label: get or
    create `Account(owner=user, label=label)`; new ones get `name=label`,
    `currency`, `mirror=True`. Refuse (CommandError, nothing written)
    if the label exists on a non-mirror account or the currency
    differs from the stored one. Delete its events, `bulk_create` the
    file's rows **in file order** (ordering ties fall back to pk),
    set `imported_at=now()`; with `--targets`, replace its targets
    (no rows → none).
  - Accounts not in the file are untouched. Print a one-line summary
    per account (events, cash, open positions).
- `web/explorer/management/commands/export_ledger.py`:
  `export_ledger --user USERNAME [--account LABEL ...] [-o FILE]`
  (stdout by default). Label = `account.label`, or a slug of the name
  for manual accounts. Targets export is out of scope.

### Phase 4 — web layer (`web/explorer/account.py`, `views.py`)

- `_account_for(user)` → `_account_for(request)`: `?account=<uuid>`
  (query string, on GET and POST alike), scoped to `owner=request.user`;
  unknown, malformed or someone else's id → **404 JSON** (same body
  for all three — no existence leak). Without the param: first
  non-mirror account, else first account, else auto-create "My
  account" (today's behaviour). `views._has_holdings` keeps using the
  default-account rule.
- Mirror guard — one helper, called explicitly at the top of every
  writer: events POST, event DELETE, target POST, plan/confirm,
  schedule POST, contribution/confirm → **403** JSON
  `{"error": "This account mirrors the imported ledger 'etrade'. Change the source ledger and re-import; Condor never writes to it."}`
  (label interpolated). Previews stay open: GET account, GET plan, GET
  contribution, POST forecast.
- `_validated_event` (manual accounts only): accept `dividend`
  (ticker + amount), `interest` (optional ticker + amount), `fee`
  (amount), optional `fees` ≥ 0 on buy/sell/dividend/interest. Refuse
  `redeem` and any `maturity` ("Bills come in through import_ledger
  only."). The existing no-negative-cash/no-short replay check covers
  the new kinds.
- `_state` — **add keys only**; nothing renamed:
  - `account`: + `label`, `currency`, `mirror`, `imported_at` (ISO or
    null). New top-level `accounts`: `[{id, name, label, currency,
    mirror}]` for the selector.
  - Prices are fetched for **non-bill** tickers only; when there are
    none, use the existing business-day calendar branch. Bills are
    priced by `bill_prices` on the last day.
  - Each position: + `cost`, `avg_cost`, `unrealized`,
    `unrealized_pct`, `realized`, `income`, `is_bill`, `maturity`
    (bills; `shares` is then the nominal and `price` the accreted
    value per 1 nominal).
  - Top level: + `realized_total`, `unrealized_total`, `income_total`,
    `charges_total`, `trade_fees_total`. Keep `gain` = total −
    contributions (the identity makes it equal realized + unrealized +
    income − charges).
  - Events: + `fees`, `maturity`.
- Plans (`rebalance_plan`, `contribution_plan`) run over non-bill
  positions + cash only; bills are left out of the plan math entirely.
- Forecast: bills join the cash sleeve at their accreted value; a
  non-USD account returns 400 `{"error": "The forecast is USD-only for now."}`
  (its cash leg is the US T-bill rate).

### Phase 5 — UI (`account.html`, `account.js`; small touches elsewhere)

- **Selector** at the top of `/account` when the user has 2+ accounts:
  a `<select>` of `name` (plus `· mirror` and the currency code). The
  chosen id lives in the URL (`?account=`, `history.replaceState`) and
  every `/api/account*` call from `account.js` carries it.
- **Currency**: `money()` / `money0()` format with the account's ISO
  code (`Intl.NumberFormat(undefined, {style: "currency", currency})`);
  no hard-coded `$` left in `account.js`.
- **Mirror banner** (mirror accounts):
  "Mirror of **{label}**, imported {imported_at, local time}. Read-only
  here: change the source ledger and re-import." Hide the add-event
  form, delete buttons and setpoint editing; plans still render, with
  confirm buttons replaced by "Advice only — place trades at your
  broker and record them in your ledger."
- **Holdings table**: + Avg cost, Unrealized (amount and %), Realized
  columns. Bill rows: shares column shows "{nominal} nominal", price
  column "accreting to {nominal} on {maturity}".
- **Gain breakdown** under the gain figure: "Realized {r} · Unrealized
  {u} · Income {i} · Fees −{c}".
- **Ledger table**: Fees column; kinds shown as Dividend / Interest /
  Fee / Redeemed.
- **Add-event form** (manual accounts): the three new kinds and a fees
  field.
- Non-USD account: the forecast panel shows "The forecast is USD-only
  for now." instead of running.
- `home.js` "Load my portfolio" and `app.js` `loadRealHoldings`: skip
  positions with `is_bill`.

### Phase 6 — docs

- `README.md` (My account paragraph + Layers table: `condor/ledger_io.py`),
  `ARCHITECTURE.md` (layer diagram + "where does it go" row for format
  I/O), `BACKLOG.md` (tick dividends + CSV export under "Account
  follow-ons"; add "Mirror import (ADR 0005)" to Done).
- `docs/handoffs/ledger-mirror.md` Status, as you go.

### Phase 7 — review

`/code-review medium` on this branch (ordered: ledger migration +
money math + a permission change). Land the fixes as the final commit
and summarise them in Status.

**Out** (do not do here):

- Fractional/minimum-order plans, rule alerts, pay-in tracker, XIRR,
  combined FX total — bucket B.
- Any change to `stats.py`, `frontier.py`, `cli.py`, Sharpe/rf,
  shrinkage, drawdowns — bucket C.
- Bills entered through the web form; coupon bonds; FIFO lots; two
  currencies in one account.
- Importing RT's **real** ledger. Never commit a real ledger or real
  amounts; tests use only the synthetic fixture. Never point anything
  at the Fly deployment.
- Any change to `docs/LEDGER-FORMAT.md` semantics (park a question).

## Acceptance

All hand-checked; pin each in a test (verification style, CLAUDE.md).

**Engine, `broker_a` (USD) — state after each event** (`ledger_state`
over the prefix):

| # | Event | AAA shares / cost / avg | BBB | Cash | Contrib | Income | Realized |
|---|---|---|---|---|---|---|---|
| 1 | DEPOSIT 1000 | — | — | 1000.00 | 1000.00 | 0 | 0 |
| 2 | BUY AAA 2.5 @100, fee 1 | 2.5 / 251.00 / 100.40 | — | 749.00 | 1000.00 | 0 | 0 |
| 3 | BUY BBB 10 @20 | 〃 | 10 / 200.00 / 20.00 | 549.00 | 1000.00 | 0 | 0 |
| 4 | BUY AAA 1.25 @80 | 3.75 / 351.00 / 93.60 | 〃 | 449.00 | 1000.00 | 0 | 0 |
| 5 | DIV AAA 3.00 | 〃 | 〃 | 452.00 | 1000.00 | 3.00 | 0 |
| 6 | SELL AAA 1.5 @110, fee 0.50 | 2.25 / 210.60 / 93.60 | 〃 | 616.50 | 1000.00 | 3.00 | 24.10 |
| 7 | INTEREST 1.20 | 〃 | 〃 | 617.70 | 1000.00 | 4.20 | 24.10 |
| 8 | FEE 2.00 | 〃 | 〃 | 615.70 | 1000.00 | 4.20 | 24.10 |
| 9 | WITHDRAW 100 | 〃 | 〃 | 515.70 | 900.00 | 4.20 | 24.10 |

- At closes AAA 90, BBB 22 (`holdings`): AAA value 202.50, unrealized
  −8.10, −3.85%; BBB 220.00, +20.00, +10.0%; total 938.20; weights
  AAA 21.58%, BBB 23.45%; drift vs targets 0.30/0.30 = −8.42 / −6.55
  pp. Identity: 900.00 + 24.10 + 11.90 + 4.20 − 2.00 = 938.20 (charges
  = 2.00; trade_fees = 1.50).
- AAA at 74: 74 / 93.60 − 1 = −20.94%.
- **`tesoro` (EUR)**: value 970.60 on 2027-01-14 (cash 0); 976.72 on
  2027-03-31 (day 76/365); 985.26 on 2027-07-15 (day 182/365);
  1000.00 on 2028-01-14 after REDEEM (cash 1000, realized 29.40,
  contributions 970.60). `daily_state` on a business-day calendar with
  no closes gives those values; TWR to 2028-01-14 = 1000/970.60 − 1 =
  3.0291% (no flows after day one, so linking telescopes).
- **TWR counts income and fees** (hand cases, cash-only): deposit 1000
  then interest 10 → TWR +1.00%; same with a deposit of 10 instead →
  0; with a fee of 10 → −1.00%.
- **Identity** `value = contributions + realized + unrealized + income
  − charges` holds on the sample and on a ledger with `set_shares` in
  and out and `set_cash` (hand case of your choice, numbers in the
  test).
- **Bill pro rata**: two lots of one bill ticker, then a partial sell —
  hand case showing both lots scaled and the per-nominal price
  unchanged by the sale.
- **Format**: the fixture parses (`today=2028-12-31`) into the two
  accounts; one failing test per validation rule, each asserting the
  `line N:` prefix; a file with several bad rows reports all of them;
  `write_ledger` → `read_ledger` round-trips the fixture to equal
  frames.
- **Django**: import the fixture (`--today 2028-12-31`) → two mirror
  accounts with the right currencies and targets; importing twice
  gives identical state; a bad file writes nothing; a label clash
  with a manual account and a currency change are refused; every
  writer returns 403 on a mirror and the previews work; another
  user's account id → 404; the default-account rule; export
  round-trip. Patch the price fetch the way existing tests do (AAA /
  BBB are invented).
- Suites at least at baseline (2026-10-23 on this branch's base):
  `pytest tests/` **217 passed, 4 skipped**; `manage.py test explorer`
  **141 OK**; `check` clean; `makemigrations --check --dry-run` clean
  after your migration.
- RT's click-through (after you're done): import the fixture locally
  with `--today 2028-12-31` into a scratch user, switch between
  accounts, see € on `tesoro`, the banner, and no write controls.

## Context & decisions already made

- ADR 0005 and `docs/LEDGER-FORMAT.md` are decided — don't reopen;
  park questions instead.
- Engine rules here (cost, realized, bill accretion, set_shares-out
  realizing at the recorded price) are decided; the identity test is
  the guard.
- Mirrors are read-only in the web, full stop. RT's portfolio repo is
  the record.
- Default-account rule, 404-not-403 for foreign ids, and query-string
  account selection are decided.
- Payload: add keys, never rename (ARCHITECTURE "to_dict() is the only
  thing the UI sees").

## Conflict watchlist

- Nothing else is in flight on `main` (2026-10-23). Bucket C may later
  touch `cli.py` / `stats.py` — not your files.
- `web/explorer/static/explorer/app.js` and `home.js`: touch only the
  two "load real holdings" spots.

## Status

- [x] Baseline recorded (217 passed / 4 skipped; 141 OK)
- [x] Phase 1 engine
- [x] Phase 2 format I/O
- [x] Phase 3 migration + commands
- [x] Phase 4 web layer
- [x] Phase 5 UI
- [x] Phase 6 docs
- [x] Phase 7 `/code-review medium` + fixes

### Results

`pytest tests/` 286 passed / 4 skipped (baseline 217 / 4);
`manage.py test explorer` 172 OK (baseline 141); `check` clean;
`makemigrations --check --dry-run` clean (migration `0006_ledger_mirror`).
New tests: `tests/test_accounting_ledger.py`, `tests/test_ledger_io.py`,
`web/explorer/test_ledger_mirror.py`. Browser smoke test on a scratch
user + scratch (past-dated) ledger: both accounts render, € on the bill
account, banner, no write controls, no console errors.

### Deviations / additions

- `Account.events_frame()` also emits a `note` column (export needs it).
- `Account.default_for(user)` classmethod holds the default-account rule
  (used by `account.py` and `views._has_holdings`); `_has_holdings` also
  ignores bills (they can't load into the workbench).
- Pre-existing bug fixed: `_state` fetched closes only for held/target
  tickers, so a fully sold-out ticker made `daily_state` raise KeyError.
  It now fetches every non-bill ticker ever traded.
- The ledger list on `/account` became a table (Date, Type, Ticker, Qty,
  Price, Amount, Fees, Note). Per-unit prices show up to 4 dp.
- `read_ledger` skips the running cash/position check for an account once
  one of its rows has errored (no cascading false errors).
- Renamed user-facing strings (ledger rows), before → after:
  "deposited $X" → Deposit; "withdrew $X" → Withdraw; "bought N × T @ $P"
  → Buy; "sold …" → Sell; "forced T to N shares" → Forced shares;
  "forced cash to $X" → Forced cash (the details now sit in table
  columns). Hard-coded "$" → the account's currency symbol/ISO format.
  Form label "Amount $" → "Amount <symbol>".
- Click-through caveat: the fixture's AAA/BBB are invented (no prices)
  and dated 2027–28, so `broker_a` cannot be valued live; `tesoro` can.

### Code-review (medium) — landed / not landed

Landed: account-switch race in `switchAccount` (stale response could
overwrite a newer one) — now sequence-guarded.
Not landed (by design of the brief, or left as notes):
- Plans exclude bills, so plan weights use a different denominator than
  the drift column when bills are held (brief: bills out of plan math).
- Forecast on a bills-only USD account says "Nothing to project yet".
- "Fees" in the gain breakdown is charges only; trade fees live in cost /
  realized (brief wording; `trade_fees_total` is in the payload).
- `write_ledger` rounds to 6 dp and copies manual notes verbatim, so a
  manual account with a 7+ digit note re-fails import.
- A replace-import leaves mirror accounts absent from the file untouched
  (brief: "accounts not in the file are untouched").
- Refactor ideas: share lot tracking between `ledger_state` and
  `bill_prices`; load `events_frame()` once per request.

## Questions for the handoff session

- (none yet)

## Return protocol

1. Keep this doc's **Status** current; note anything you deviated from.
2. Record your baseline **before starting**, then re-run before pushing —
   do not make any count worse:
   ```bash
   source .venv/bin/activate
   python -m pytest tests/
   python web/manage.py test explorer
   python web/manage.py check
   python web/manage.py makemigrations --check --dry-run
   ```
   Engine changes need a verification-style test (closed form / hand case /
   legacy agreement); model changes need an "equals the engine" test
   (CLAUDE.md rules apply on branches too).
3. This brief **orders a `/code-review` at medium** (Phase 7): run it on
   this branch and land the fixes as your final commit, summarised in
   Status.
4. **Do not push, do not open a PR, do not merge.** Your report packet
   is THIS doc: Status checklist current, deviations listed, every
   renamed user-facing string quoted (before → after), test counts vs
   baseline, any pre-existing bug noticed but not fixed. Commit it all
   locally and tell the human you are done.
5. The handoff session reviews proportionately — spot-checks, never a
   redo (`docs/WORKTREES.md` § Review policy) — merges your local
   branch, pushes `main`, and the human deploys.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/ledger-mirror
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
