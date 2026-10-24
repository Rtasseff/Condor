# Handoff — `feature/stats-honesty`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/stats-honesty.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/stats-honesty` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/stats-honesty` |
| Base | `main` @ `f99dd69` (rebased 2026-10-24, after `ledger-mirror` merged) |
| Created | 2026-10-24 |
| Runserver port | 8002 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Make Condor’s default statistics honest about cash-like assets, and
report what portfolios actually went through. Run on RT’s planned ETF
mix, the robust tangency came out **95% USFR** (a T-bill fund): a 7-year
median return was compared with today’s T-bill rate, inventing a 0.78%
premium that premium ÷ variance turned into a 95% weight. RT approved
the fixes on 2026-10-24 (bucket C of three; bucket A `ledger-mirror` runs
merged 2026-10-24; bucket B `account-plans` runs in parallel):

- **F1** expected return = today’s T-bill rate + the historical premium
  measured on excess returns (fixes F2 for cash-like assets too);
- **F3** Ledoit-Wolf with the constant-correlation target;
- **F4** worst fall, worst calendar year, growth per year for a portfolio;
- **F5** CLI `--json` says which window, method and rate it used.

**Read before coding:** `docs/decisions/0006-premium-expected-returns.md`
(the design, committed with this brief).

## Scope

**In** — in this order; commit at the end of each phase.

### Phase 1 — T-bill history (`condor/data/rates.py`)

- `risk_free_history(maturity="3m", store=None) -> pd.Series` — the full
  FRED daily series (annual decimal yields, DatetimeIndex, NaNs
  dropped), using the existing `_fetch_series` (the CSV is already the
  whole history). Cache it as Parquet next to `rates.json` in the store
  root, refreshed after `CACHE_HOURS` like the rate; if FRED is down,
  serve the cache however old; neither → `DataFetchError`. Export it
  from `condor.data` and `condor`.
- Tests: no network — patch `_fetch_series`; cache hit, refresh,
  stale fallback, and failure.

### Phase 2 — engine (`condor/stats.py`)

- `excess_returns(prices, rf_yields, metric="relative", timeframe="D",
  samp_int=None) -> DataFrame` — `asset_returns(...)` minus the
  per-row T-bill return. Per-row rate = the yield on the row’s date
  (reindex to the return index, ffill, then bfill for a leading gap)
  ÷ `annual_factor(timeframe)`; for `metric="log"` use `log1p` of that.
- `premium_annual(prices, rf_yields, method, metric, timeframe,
  samp_int, basis) -> Series` — the **same estimator** as
  `expected_annual` (robust: median × freq; normal: pypfopt
  `mean_historical_return` with the same `compounding` rule), applied
  to `excess_returns`. Refactor so both functions share one estimator
  helper; `expected_annual`’s output must not change.
- `risk_matrix_annual` normal branch:
  `.ledoit_wolf(shrinkage_target="constant_correlation")`. Update the
  module docstring.
- Verification tests (hand / closed form):
  - Constant yield `y`: `premium_annual == expected_annual − y`
    exactly, both methods (median and mean commute with a constant
    shift), so `rf_level + premium` with `rf_level == y` reproduces
    today’s numbers.
  - Synthetic cash fund: daily return = that day’s T-bill (yields
    rising 0 → 5% over the sample) + tiny noise. Raw robust μ ≫ raw
    mean; premium ≈ 0 under both methods.
  - Constant-correlation LW keeps every diagonal entry equal to the
    sample variance × freq (1e-12), and off-diagonals lie between the
    sample covariance and the target’s.
  - Any previously pinned normal-method Σ number that moves: update it
    and say in the test why the old one was wrong (ARCHITECTURE
    “Tests are the contract”). Legacy-pinned tests that feed their own
    Σ (`test_verification.py`) must not move.

### Phase 3 — model (`condor/model.py`, `condor/frontier.py`)

- `AssetSet(..., rf_history: pd.Series | None = None, rf_level: float | None = None)`
  (keyword-only, after the existing options). With `rf_history`:
  `expected_returns = rf_level + premium_annual(...)`; `rf_level`
  defaults to the history’s last value. Without it: exactly today.
- New read-only properties: `premium_mode: bool`, `rf_level`,
  `premiums` (Series; None when off), `tbill_window_mean` (mean of the
  history over the set’s window; None when off).
- `summary()` gains a `premium` column when on (add, don’t rename).
- `with_options(...)` carries both through and accepts `rf_level=`.
- `AssetSet.analysis(weights, risk_free_rate, ...)`: in premium mode,
  if `risk_free_rate != self.rf_level`, run on
  `self.with_options(rf_level=risk_free_rate)` so the expected returns
  and the Sharpe rate are always the same number. Then add a `meta`
  key: `{"window": {"start", "end", "n_days"}, "method", "premium":
  bool, "risk_free_rate", "tbill_window_mean"}`.
- `AssetSet.from_members` and `compute_analysis(...)`: pass
  `rf_history` / `rf_level` through.
- “Equals the engine” tests: `AssetSet(...).expected_returns ==
  rf_level + stats.premium_annual(...)`; analysis with a different rf
  re-levels; off-mode is byte-identical to today’s payload apart from
  the new `meta` key.
- Tangency check (closed form, synthetic): one risky asset + the
  synthetic cash fund from Phase 2. Raw mode at today’s rate puts most
  of the weight on the cash fund (reproduces the bug); premium mode
  puts ~0 on it.

### Phase 4 — portfolio history (F4)

- New engine module `condor/history.py` (pure):
  `max_drawdown(values) -> dict(depth, peak, trough, recovery)` (dates;
  `recovery` None if never regained), `calendar_year_returns(values)
  -> Series` (first/last years partial, labelled as such by the
  caller), `cagr(values) -> float` with years = days / 365.25.
- `Portfolio.history() -> PortfolioHistory` (small result object over
  `value_index`, with `to_dict()`), and `Portfolio.to_dict()` gains a
  `history` key. Label it what it is: **fixed weights, rebalanced every
  period** (that is what `value_index` is).
- Tests (hand cases): values 100, 120, 90, 130 → depth −25%, peak at
  120, trough at 90, recovered at 130; 100 → 121 over exactly 730.5
  days → CAGR 10%; a two-calendar-year series with known year-end
  values; a never-recovered drawdown.

### Phase 5 — CLI (`condor/cli.py`) — F5 and premium

- `analyze`, `portfolio`, `frontier` build the AssetSet with
  `rf_history=risk_free_history()` and `rf_level=` the resolved rf.
  `--no-premium` turns it off. If the history is unavailable, warn
  once (`expected returns are raw: T-bill history unavailable`) and run
  raw.
- Header line adds the basis, e.g.
  `expected return = T-bill 4.22% + premium over T-bills (window T-bill mean 2.96%)`.
- `analyze` table gains a Premium column when on. `portfolio` prints
  the F4 numbers: worst fall (peak → trough dates, recovery or “not
  yet”), worst calendar year, growth per year.
- `--json` for all three: add a top-level `meta` = the analysis `meta`
  plus `risk_free_source` (the existing `rf_note` text). `portfolio
  --json` includes `history`.
- Tests: patch `risk_free_history` / `risk_free_rate` (no network);
  `meta` keys present on all three; `--no-premium` reproduces today’s
  numbers; history fallback path warns and runs raw.

### Phase 6 — web (`web/explorer/views.py`, Optimize JS)

- `/api/analyze` and the other `AssetSet` call sites in `views.py`:
  pass `rf_history` (`risk_free_history()`, failure → raw mode) and
  `rf_level` = the request’s risk-free rate. Accept an optional
  `premium: false` in the request body (no UI control).
- Optimize page: one muted line under the chart from `meta`:
  “Expected returns: T-bill rate ({rf}%) + each asset’s premium over
  T-bills, {start} – {end}.” Raw mode: “Expected returns: historical
  averages (T-bill history unavailable).”
- Your-portfolio point card: one line from `history`:
  “Worst fall −{d}% ({peak} → {trough}) · worst year {yyyy} {r}% ·
  {g}%/yr” — fixed-weight backtest; say so in a `title` tooltip.
- Do **not** touch `web/explorer/account.py`, `account.js`,
  `home.js`, `condor/accounting.py` (bucket B is working there).
- Django tests: payload has `meta`; premium on/off; history failure
  → raw with the message; patch the fetch like existing tests.

### Phase 7 — docs + review

- `README.md` (core-analytics example: note `rf_history`), `docs/CLI.md`
  (`--no-premium`, the header line, `meta`), `ARCHITECTURE.md` (layer
  table: `history.py`), `BACKLOG.md` (bucket C → Done with a one-line
  summary).
- `/code-review medium` on this branch (ordered: engine numerics).
  Land the fixes as the final commit; summarise in Status.

**Out** (do not do here):

- Forecast centres (`forecast.py`, anchors) — unchanged by ADR 0006.
- Anything under accounts / ledger (bucket A); plans, alerts, XIRR
  (bucket B).
- Changing the robust median estimator.
- A UI toggle for premium mode; non-USD risk-free rates.

## Acceptance

- All phase tests above, verification-style.
- Suites at least at baseline (2026-10-24, base `f99dd69`, this
  worktree): `pytest tests/` **286 passed, 4 skipped**; `manage.py
  test explorer` **172 OK**; `check` and `makemigrations --check --dry-run` clean (no
  migrations expected).
- Real-data smoke check (record the output in Status; prices move
  daily, so approximately):
  `python -m condor analyze STIP USFR VT RSP AVDV AVEM GLDM VST URNM`
  → USFR premium ≈ 0 and the robust tangency carries **no** material
  USFR (2026-10-24 run: STIP 37 · GLDM 26 · AVDV 16 · VT 11 · AVEM 6 ·
  VST 4). The same with `--no-premium` → ~95% USFR (today’s bug,
  still reachable on purpose).
  `python -m condor analyze ... --method normal` → USFR dispersion
  ≈ 0.49% (was 2.67%), STIP ≈ 2.82% (was 3.84%).
  `python -m condor portfolio STIP=20 USFR=5 VT=20 RSP=10 AVDV=7.5 AVEM=7.5 GLDM=10 VST=10 URNM=10`
  prints a worst fall in early 2020 and `--json` carries `meta` and
  `history`.

## Context & decisions already made

- ADR 0006 is decided; don’t reopen it — park questions.
- Σ stays on raw returns; only μ changes for F1.
- Premium mode on by default; raw mode is the fallback and the
  `--no-premium` / `premium: false` escape hatch.
- Payloads: add keys (`meta`, `history`, `premium`), never rename.

## Conflict watchlist

- Bucket A is merged (this branch is rebased on it). **Bucket B
  (`feature/account-plans`) is in flight**: accounts, ledger, plans,
  alerts. Shared files are only `README.md`, `ARCHITECTURE.md`,
  `BACKLOG.md`, `condor/__init__.py` and possibly `views.py` /
  `condor/data/` — keep edits there in separate hunks; whichever
  branch merges second rebases.
- `condor/__init__.py` exports: both branches may add names — trivial
  merge.

## Status

- [ ] Baseline recorded (286 passed / 4 skipped; 172 OK)
- [ ] Phase 1 T-bill history
- [ ] Phase 2 engine
- [ ] Phase 3 model
- [ ] Phase 4 portfolio history
- [ ] Phase 5 CLI
- [ ] Phase 6 web
- [ ] Phase 7 docs + `/code-review medium` + fixes

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
cd /Users/rtasseff/projects/condor-dev/stats-honesty
source .venv/bin/activate
python web/manage.py runserver 8002
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
