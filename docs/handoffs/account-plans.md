# Handoff — `feature/account-plans`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/account-plans.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/account-plans` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/account-plans` |
| Base | `main` @ `e44d3e3` (rebased 2026-10-27: price-store fix) |
| Created | 2026-10-24 |
| Runserver port | **8001** (8002 is `stats-honesty`, running in parallel) |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Bucket B of RT’s portfolio-driven account work (A `ledger-mirror` is
merged; C `stats-honesty` runs in parallel). The read-only mirror of
RT’s USD account should answer the monthly check-in questions with the
same numbers as the source repo’s own scripts:

- **R8 pay-in tracker:** “Am I on schedule, and what’s the buy list
  for tranche k?” — whole shares, catch-up sizing, budget trim,
  reservoir sale, completion.
- **R7 rule alerts:** “Did any rule fire?” — index below its 52-week
  high, position below average cost, drift (muted during the pay-in);
  accelerations fold into the buy list.
- **R9 XIRR** next to TWR: “What did my actual dollars earn?”
- **R5 combined total:** “What’s everything worth in USD and in EUR?”

**Read before coding:** `docs/decisions/0007-payin-rules-xirr.md` (the
design), `docs/decisions/0005-ledger-v2-mirror.md`, and
`docs/LEDGER-FORMAT.md` § v1.1 (the contract with the source repo —
don’t change it; park questions). The reference implementation is the
source repo’s `scripts/pflib.py` (`tranche_orders`, `trim_to_budget`,
`reserve_needed`, `usfr_sale`, `payin_complete`, `drift_breaches`) at
`/Users/rtasseff/projects/investments/portfolio` — read it, never edit
it.

## Scope

**In** — in this order; commit at the end of each phase.

### Phase 1 — format v1.1 + storage

- `condor/ledger_io.py`:
  - `read_targets_full(src) -> dict[label, dict[ticker, TargetSpec(weight, timing, line)]]`
    accepting the v1 header *or* v1.1 (`timing`, `line`; `line`
    defaults to the ticker lowercased); `read_targets` keeps its
    signature (weights only) and wraps it.
  - `read_payin(src) -> dict[label, PayInSpec(total, dates)]` and
    `read_rules(src) -> dict[label, list[RuleSpec]]`, same `line N:`
    error style, every rule in LEDGER-FORMAT § v1.1 enforced. Future
    dates are allowed in `payin.csv`.
- Models + one migration:
  - `AccountTarget.timing` (CharField 10, blank, default "") and
    `AccountTarget.line` (CharField 40, blank, default "" = the ticker
    lowercased).
  - `PayInPlan` (OneToOne `Account`, `total` Float, `dates` JSONField
    of ISO strings).
  - `AccountRule` (FK `Account`; `rule_id`, `rule`, `ticker` (24,
    blank), `threshold` Float, `action`, `tranches` (null), `targets`
    (CharField 120, space-separated, blank)); unique (account, rule_id).
- `import_ledger` gains `--payin` and `--rules`, replace semantics like
  `--targets` (given → replaced for every account in the ledger file;
  no rows → none). Cross-file checks, all before writing: payin/rules
  accounts must be in the ledger file; with `--payin` an account’s
  targets must include ≥1 `dca` ticker and at most one `reservoir`;
  rule `target` tickers must be that account’s `dca` targets. Summary
  line adds “pay-in N tranches” / “rules n”.

### Phase 2 — engine

New pure modules; numbers here, nothing in views or JS.

- `condor/payin.py`:
  ```python
  @dataclass(frozen=True)
  class PayInPlan:
      total: float
      dates: tuple[date, ...]
      weights: dict[str, float]     # fraction of total, per ticker, in target order
      timing: dict[str, str]        # "dca" | "lump" | "reservoir"
      lines: dict[str, str]         # ticker -> line key
  def gross_bought(events) -> dict[str, float]       # Σ shares × price over buys
  def tranches_due(plan, as_of) -> int               # dates ≤ as_of
  def progress(plan, bought, as_of) -> pd.DataFrame  # per LINE: [timing, tickers, plan, bought, pct, scheduled]
  def reserve_needed(plan, bought) -> float          # reservoir w × total + unfunded lump
  def spendable(plan, bought, cash, reservoir_value) -> float   # max(cash + reservoir_value − reserve, 0)
  def lump_orders(plan, bought, prices) -> pd.DataFrame          # unfunded lump: due = plan − bought
  def tranche_orders(plan, bought, prices, through, extra=None, budget=None) -> pd.DataFrame
      # [due, qty, price, amount, note], dca tickers only, target order
  def reservoir_trade(plan, cash, prices, buy_total) -> dict | None
      # {"side": "SELL"|"BUY", "ticker", "qty", "price", "amount"}
  def is_complete(plan, bought, prices, budget, as_of) -> bool
      # tranches_due == N and tranche_orders(through=N, budget=budget) buys nothing
  ```
  Semantics are ADR 0007 §1–3, ported from `pflib` (`tranche_orders`,
  `trim_to_budget`, `reserve_needed`, `spendable`, `usfr_sale`,
  `payin_complete` as of source commit `4522029`): half-up rounding
  `floor(due / price + 0.5 + 1e-9)`; notes “under half a share due;
  carries forward” and “1 share trimmed to stay within cash; carries
  forward”; trim picks the largest `amount − due`, ties to the first in
  target order. Reservoir trade after the buys (lump + tranche): buys >
  cash → SELL `ceil((buys − cash) / price − 1e-9)`; else BUY
  `floor((cash − buys) / price + 1e-9)` (None when 0). Day 1 (no
  reservoir held, lump unfunded) falls out of the same functions: the
  budget is cash − lump plan − reservoir weight × total, and the rest
  is swept into the reservoir. `scheduled` = plan × k_due / N for dca,
  plan once k_due ≥ 1 for lump, NaN for the reservoir.
- `condor/alerts.py`:
  ```python
  def below_high(closes: pd.Series, as_of=None, days=365) -> float   # last / max − 1
  @dataclass(frozen=True)
  class RuleResult: id, rule, ticker, threshold, measured, fired, muted,
                    action, tranches, targets
  def evaluate(rules, *, holdings, weights, targets, index_closes,
               payin_active) -> list[RuleResult]
  def accelerations(results, k_due, n) -> tuple[int, dict[str, int]]   # (through, extra)
  ```
  All three fire on strictly `>` the threshold (ADR 0007 §4).
  `below_high`: (high − last) / high over closes dated after last date
  − 365 days. `below_avg_cost` = (avg − last) / avg; not held →
  `measured=None`, not fired. `drift`: per line, |line value / total −
  line target| with total including cash and every line checked;
  `measured` = the largest, plus the breaching lines; while
  `payin_active` (a plan exists and is not complete) it is
  `muted=True, fired=False`. `accelerations`: no fired rule → `through
  = max(k_due, 1)`; fired untargeted → `k_due + tranches` (largest if
  several), capped at N; targeted → `extra[ticker] = tranches` (largest
  per ticker). The two kinds **add**, because a ticker’s due uses
  `min(through + extra, N)`: an untargeted +2 and a targeted +1 firing
  together take the targeted tickers to `k_due + 3` and every other
  line to `k_due + 2`, all capped at N (confirmed against `pflib`
  2026-10-24). Pin this with a test (e.g. on the fixture at T2: both
  rules applied, N = 4).
- `condor/accounting.py`:
  - `money_weighted_return(daily) -> float | None` — investor cash
    flows −`flow` on each day plus +final `value` on the last day,
    ACT/365 from the first day, `scipy.optimize.brentq` on (−0.9999,
    10); None if span < 90 days or no sign change.
  - `combined_total(values: dict[ccy, float], fx: dict[str, float],
    base: str) -> float` (`fx` keyed like `"EURUSD"` = USD per EUR).
- Verification tests (hand cases; plus the fixture numbers in
  § Acceptance):
  - XIRR: the two fixture cases in § Acceptance; span < 90 days →
    None.
  - Everything in § Acceptance, built from `tests/fixtures/payin_sample_*`
    (prefixes of the ledger by date; closes from `payin_sample_prices.csv`).

### Phase 3 — web (`web/explorer/account.py`)

- `_state` adds keys (never rename):
  - `payin`: `{total, n, k_due, next_date, complete, reserve,
    rows: [{line, tickers, timing, plan, bought, pct, scheduled}]}` or
    null.
  - `rules`: list of `RuleResult` dicts (with a human `text`), or [].
  - `xirr` (null when not shown).
  - `combined` (only when the user has accounts in 2+ currencies):
    `{"USD": x, "EUR": y, "fx": {"pair": "EURUSD", "rate", "as_of"}}`;
    FX failure → omit it and log.
- New preview endpoint `GET /api/account/tranche?account=&through=&apply_rules=1`
  → `{through, n, applied_rules: [ids], cash, reserve, budget,
  orders: [{ticker, timing, due, qty, price, amount, note}],
  reservoir_trade}` — lump orders first (when unfunded), then the
  tranche orders.
  Allowed on mirrors (advice only); no confirm endpoint.
- Index and FX closes come from the existing `PriceStore` (raw
  `close`), fetched only when a rule or a second currency needs them.
  If `^GSPC` or `EURUSD=X` doesn’t round-trip through the store’s
  file naming, fix it in `condor/data/store.py` with a test — do not
  touch `condor/data/rates.py` (bucket C).
- Django tests: payload keys; tranche endpoint on the imported fixture
  (`--today` / patched clock and patched prices, as bucket A’s tests
  do); mirror still refuses every writer.

### Phase 4 — UI (`account.html`, `account.js`)

- **XIRR** tile beside TWR: “Money-weighted (XIRR)” — “n/a under 3
  months” when null.
- **Combined line** under the account selector (2+ currencies): “All
  accounts: $X · €Y (EURUSD {rate}, {as_of})”.
- **Pay-in panel** (when `payin`): heading “Pay-in: tranche {k_due} of
  {n} · next {next_date}” (“complete” when done); progress table per
  line: Line (its tickers) · Timing · Plan · Bought · %; then “Buy list
  for tranche {through}” from the tranche endpoint: Ticker · Due ·
  Shares · Price · Amount · Note (lump rows labelled “lump”), then
  “Sell {qty} {reservoir} (~{amount}) to fund it” or “Put the rest in
  {reservoir}: buy {qty} (~{amount})”, and “Cash available above
  reserve: {budget}”. Always under the list: “Cancel last month’s
  unfilled orders before placing these — this list already includes
  what they didn’t buy.” (catch-up sizes on fills, so an open or
  never-placed order would double-buy). A small selector for
  `through` (1…N). When rules
  changed the list: “Includes: {rule texts}”.
- **Rules panel** (when `rules`): one row per rule — its text, measured
  value, threshold, status as a word: **Fired** / Not fired / **Muted
  during pay-in** (never colour alone).
- Mirror accounts keep “Advice only — place trades at your broker and
  record them in your ledger.”

### Phase 5 — docs + review

- `README.md` (My account paragraph), `ARCHITECTURE.md` (layer table:
  `payin.py`, `alerts.py`), `BACKLOG.md` (bucket B → Done, one line).
- `docs/LEDGER-FORMAT.md` § v1.1 is already written (by the handoff
  session, with this brief) — only fix typos you find.
- `/code-review medium` (ordered: money math in plans + a migration on
  account tables). Land fixes as the final commit; summarise in Status.

**Out** (do not do here):

- `condor/stats.py`, `model.py`, `frontier.py`, `cli.py`,
  `condor/data/rates.py`, Optimize page JS — bucket C is there.
- Pay-in/rule editing in the UI for manual accounts; confirm endpoints
  for tranches; automatic rule actions; fractional plans.
- Kill-criteria checklists (qualitative; they stay in the source repo).
- Real ledgers or real amounts in tests or commits.

## Acceptance

*Fixture numbers below come from the source repo’s `pflib`, cross-checked
there — pin every one in a test.*

Fixture `tests/fixtures/payin_sample_*` (copied unchanged from the
source repo’s `condor_b_*`, commit `b92d94b`; its
`docs/condor-bucket-b.md` has the working). Account `broker_b`, USD,
total 1,000, N = 4 (2027-01-04, 02-01, 03-01, 04-05). Targets: LMP 0.20
lump · RES 0.10 reservoir · AAA 0.30 dca · BBB 0.20 dca · CCC 0.15 +
DDD 0.05 dca, both in line `sleeve`. “Ledger through D” = the ledger’s
rows dated ≤ D (or < D when the step is “before that day’s buys”).

1. **Day 1 (2027-01-04, before its buys; cash 1,000)** — lump: LMP 4 =
   200. Budget 1000 − 200 − 100 = **700**. T1: AAA due 75 → 2 = 80; BBB
   50 → 2 = 60; CCC 37.5 → 3 = 36; DDD 12.5 → 2 = 14; total **190**.
   Reservoir: BUY floor(610 / 10) = **61** RES; cash after 0. Progress
   after day 1: aaa 80/300 = 26.7%, bbb 60/200 = 30.0%, sleeve 50/200 =
   25.0%.
2. **T2 (2027-02-01, ledger before its buys, T2 closes)** — budget 0 +
   61 × 10.02 − 100 = **511.22**. AAA due **70** (150 − 80, not 75) → 2
   = 84; BBB **40** → 1 = 31; CCC 39 → 4 = 36; DDD 11 → 2 = 14; total
   **165**. Reservoir SELL ceil(165 / 10.02) = **17**; cash after
   **5.34**.
3. **Rules at T2** — `ccc_below_cost` (avg 12.00): CCC 9.00 → 25.0% →
   **fired**; 9.60 → exactly 20.0% → **not** fired; 9.59 → 20.08% →
   fired. With it applied (extra 1 on CCC, DDD): CCC due 76.5 → **9** =
   81, DDD 23.5 → **3** = 21; total **217**; SELL **22**.
   `idx_drawdown` at ^IDX 940 (high 1,000) → **6.0%**, not fired.
4. **T3 (2027-03-01, ledger before its buys)** — ^IDX 899; window is
   dates after 2026-03-01, so 2026-01-15’s 1,200 is out; high 1,000 →
   **10.1% fired**; at 900 → 10.0% not fired. through = 3 + 2 → capped
   **4**. Budget 5.34 + 44 × 10.03 − 100 = **346.66**. Dues AAA 136, BBB
   109, CCC 78, DDD 22; untrimmed AAA 3, BBB 3, CCC 8, DDD 3 = **354.50**
   > budget → trim BBB (+3.50, the most rounded up) → **BBB 2**; total
   **317.00**; SELL ceil(311.66 / 10.03) = **32**; cash after **9.30**;
   RES left 12. **Not complete** (dates remain).
5. **T4 (2027-04-05, full ledger, T4 closes)** — budget 9.30 + 12 ×
   10.04 − 100 = **29.78**; BBB due 34 → 1 share at 37.50 > budget →
   trimmed to 0; nothing buyable → **complete**, BBB at 166/200 = 83%.
   Mid-pay-in mute: after day 1 at T2 closes the reservoir line is
   61.11% vs 10% → would breach, **muted**.
6. **Drift after completion (T4 closes)** — total **1,049.28**; aaa
   30.69, bbb 17.87, sleeve 19.63, lump 19.44, reservoir 11.48 → no
   breach. With CCC 20, DDD 16 → total 1,255.28 → **bbb 14.94% (−5.06)
   and sleeve 32.82% (+12.82) fired**; aaa 25.65, lump 16.25 not.
7. **XIRR (ACT/365)** — −1,000 on 2027-01-01, +1,100 on 2028-01-01 →
   **10.0000%**; −1,000 on 2027-01-01, −500 on 2027-07-02, +1,600 on
   2028-01-01 → **8.0266%**.
8. **Import** — the five fixture files import together (`--today
   2027-04-05`): `broker_b` mirror with 6 targets (timing + line), a
   4-tranche plan, 3 rules; a v1 3-column targets file still imports.
- Suites at least at baseline (2026-10-27, base `e44d3e3`, this
  worktree): `pytest tests/` **288 passed, 4 skipped**; `manage.py test
  explorer` **172 OK**; `check` clean; `makemigrations --check
  --dry-run` clean after your migration.
- RT’s click-through: import the fixture (`--today` as the fixture
  says) into a scratch user; pay-in panel, buy list, rules panel and
  XIRR render on the mirror, with no write controls.

## Context & decisions already made

- ADR 0007 and LEDGER-FORMAT § v1.1 are decided; park questions.
- Port the `pflib` semantics exactly; where Condor’s data model differs
  (per-ticker targets instead of lines with components), a line is the
  set of its tickers and the fixture is per ticker.
- Payloads: add keys, never rename.

## Conflict watchlist

- **Bucket C (`feature/stats-honesty`) is in flight**: `stats.py`,
  `model.py`, `frontier.py`, `history.py` (new), `cli.py`,
  `condor/data/rates.py`, `views.py` (analyze paths), Optimize JS.
  Shared files: `README.md`, `ARCHITECTURE.md`, `BACKLOG.md`,
  `condor/__init__.py` — separate hunks; whichever merges second
  rebases.

## Status

- [ ] Baseline recorded (288 passed / 4 skipped; 172 OK)
- [ ] Phase 1 format v1.1 + storage
- [ ] Phase 2 engine
- [ ] Phase 3 web
- [ ] Phase 4 UI
- [ ] Phase 5 docs + `/code-review medium` + fixes

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
3. This brief **orders a `/code-review` at medium** (Phase 5): run it on
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
cd /Users/rtasseff/projects/condor-dev/account-plans
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
