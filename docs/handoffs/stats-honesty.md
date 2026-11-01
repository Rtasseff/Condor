# Handoff — `feature/stats-honesty`

**Merged 2026-11-01**; branch and worktree removed.

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/stats-honesty.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/stats-honesty` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/stats-honesty` |
| Base | `main` @ `e44d3e3` (rebased 2026-10-27: `ledger-mirror` merge + price-store fix) |
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
- Suites at least at baseline (2026-10-27, base `e44d3e3`, this
  worktree): `pytest tests/` **288 passed, 4 skipped**; `manage.py
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

- [x] Baseline recorded: 288 passed / 4 skipped; `manage.py test explorer` 172 OK (matches the brief)
- [x] Phase 1 T-bill history (`risk_free_history`, Parquet cache `rates_DGS3MO.parquet` next to `rates.json`)
- [x] Phase 2 engine (`excess_returns`, `premium_annual`, shared `_estimate_annual`, constant-correlation LW)
- [x] Phase 3 model (`AssetSet` premium mode, `meta`, `meta()` method)
- [x] Phase 4 portfolio history (`condor/history.py`, `Portfolio.history()`, `PortfolioHistory`)
- [x] Phase 5 CLI
- [x] Phase 6 web
- [x] Phase 7 docs + code review (see below)

### Test counts vs baseline

| | baseline | now |
|---|---|---|
| `pytest tests/` | 288 passed, 4 skipped | 323 passed, 4 skipped (+35 tests) |
| `manage.py test explorer` | 172 OK | 176 OK (+4) |
| `manage.py check`, `makemigrations --check --dry-run` | clean | clean (no migrations) |

### Deviations / decisions

- **`risk_free_history` cache age** is the Parquet file's mtime (not an entry in `rates.json`); same `CACHE_HOURS`.
- **`AssetSet.meta(risk_free_rate)`** added as a method so the CLI `--json` for `portfolio` / `frontier` reuses the exact analysis `meta` (the brief only named the `meta` key on `analysis`).
- **`Portfolio.to_dict()` gains `history` for every portfolio**, so frontier points, min-vol and tangency carry it too (payload is larger by ~one small block per point; CAL points have none). The point card therefore shows the worst-fall line for any selected frontier/anchor point, not only "Your portfolio". Say so if you want it narrowed.
- `PortfolioHistory.worst_year` prefers full calendar years (a 2-day stub at the edge of the window is not "the worst year"); partial years are used only if there is no full one. A series that never falls reports `peak/trough/recovery: null` (CLI: "none"; web: "No fall below a prior high").
- `PortfolioHistory.to_dict()` marks the first/last calendar year `partial` (first year starting after 7 Jan, last year ending before 24 Dec) and `worst_year` carries that flag; the CLI and the web line say "(partial)".
- **Web history failure** is silent in the payload other than `meta.premium: false`; the Optimize line "Expected returns: historical averages (T-bill history unavailable)." is derived from that (also shown when the client sends `premium: false`).
- `cagr` uses elapsed seconds / 86400 / 365.25, not whole `.days`, so a 730.5-day span is exactly 2.0 years.
- `Frontier` / `AssetSet.tangency(rf)` called directly with an `rf` different from the set's `rf_level` do **not** re-level (only `AssetSet.analysis` does, per the brief). CLI and web always build the set with `rf_level` = the rate they use.
- Forecast endpoint (`/api/forecast`) deliberately left on raw `AssetSet` (ADR 0006 point 6).

### Renamed / changed user-facing strings

- `analyze` header: gains a third line (added, nothing renamed): `expected return = T-bill 4.18% + premium over T-bills (window T-bill mean 2.96%)`, or `expected return = historical average (raw)`.
- `analyze` table: new `Premium` column (premium mode only).
- Optimize page: new muted line under the chart and a new line in the selected-point card. No existing string changed.
- Normal-method risk numbers move (constant-correlation target): see smoke check.
- Payload keys added only: `meta` (analysis, CLI json), `history` (every `Portfolio.to_dict()`), `premium` (summary column). Two key-set assertions updated for them (`tests/test_model.py`, `tests/test_return_options.py`).

### Pinned numbers that moved

- `tests/test_return_options.py::test_normal_risk_matrix_shrinks_the_legacy_series` and `::test_risk_matrix_is_the_old_call`: both pinned `ledoit_wolf()` with the default constant-variance target; now pinned with `shrinkage_target="constant_correlation"`, with the reason written in the test (the old target dragged each asset's own variance toward the average). `test_verification.py` legacy-pinned tests did not move.

### Real-data smoke check (2026-11-01, price window 2019-12-04 to 2026-10-30, T-bill 4.18% as of 2026-10-29)

`python -m condor analyze STIP USFR VT RSP AVDV AVEM GLDM VST URNM` (robust, premium on):
```
expected return = T-bill 4.18% + premium over T-bills (window T-bill mean 2.96%)
STIP 5.34%/1.78% prem 1.16% | USFR 4.13%/0.47% prem -0.05% | VT 23.54%/13.28% | RSP 17.32% | AVDV 28.02% | AVEM 26.74% | GLDM 24.11% | VST 34.84% | URNM 16.00%
Min dispersion   4.22%   0.45%   0.08   STIP 6.4% . USFR 93.6%
Tangency        17.39%   6.44%   2.05   STIP 41.3% . VT 11.4% . AVDV 14.2% . AVEM 4.9% . GLDM 24.2% . VST 3.9%
```
USFR premium is -0.05% and the tangency carries no USFR (brief: STIP 37, GLDM 26, AVDV 16, VT 11, AVEM 6, VST 4; the mix moved a little with a week of new prices).

Same with `--no-premium` (today's bug, on purpose):
```
Tangency   5.92%   0.67%   2.60   USFR 95.4% . VT 0.7% . AVDV 1.1% . AVEM 0.5% . GLDM 1.9% . VST 0.3%
```

`--method normal`: STIP dispersion 2.82%, USFR 0.49% (before the constant-correlation target: STIP 3.84%, USFR 2.67%), as the brief expected. Normal-method tangency (premium on): RSP 13.0 . GLDM 56.9 . VST 22.3 . URNM 7.7.

`python -m condor portfolio STIP=20 USFR=5 VT=20 RSP=10 AVDV=7.5 AVEM=7.5 GLDM=10 VST=10 URNM=10`:
```
Given mix   19.32%  10.20%  1.48
History - fixed weights, rebalanced every period
  worst fall   -26.12%  2020-01-16 -> 2020-03-23, recovered 2020-07-20
  worst year   2022: -6.73%
  growth/year  15.46%
```
`--json` keys: `weights, ret, vol, sharpe, history, meta`; `meta` = window 2019-12-04..2026-10-30 (1,736 days), method robust, premium true, risk_free_rate 0.0418, tbill_window_mean 0.02959, risk_free_source "4.18% (3-mo T-bill, FRED, as of 2026-10-29)".

### What was and was not exercised

- Exercised: pytest, Django test client on `/api/analyze` (premium default, `premium: false`, history failure -> raw, re-level), CLI end to end on real data, `node --check` on `app.js`.
- **Not exercised in a real browser**: the new Optimize basis line (`#basisnote`) and the point-card worst-fall line (`#histnote`) and its `title` tooltip are untested beyond a JS syntax check and template inspection. RT should click through once.

### Pre-existing / noticed, not fixed

- Intermittent CLI failure `error: If using all scalar values, you must pass an index` on the 9-ticker `analyze` (about 4 of ~25 runs, all runs showed yfinance deprecation warnings in stderr, i.e. a price-store refresh path; the identical command succeeded on the next try and in-process with a traceback hook never reproduced it). Not caused by this branch as far as I can tell (it appeared on `--no-premium` runs, which never touch the new code), not investigated further.

### Code review

The `code-review` skill ran twice through the Skill tool at `medium`. The first run reviewed the wrong checkout (the main worktree's `condor/accounting.py`, nothing of mine), so its three findings were discarded as out of scope. The second was pointed at this branch's diff against main. Findings and disposition:

Fixed in the final commit:
- `Portfolio.history()` was rebuilt on every `to_dict()` -> now cached per portfolio.
- `risk_free_history` Parquet write was not atomic and a corrupt cache stayed "fresh" -> write to temp + `os.replace`; an unreadable cache is treated as absent (refetch, or stale-serve of nothing).
- CLI caught only `DataFetchError` around the history fetch -> any failure now warns once and runs raw.
- `worst_year` could be a 2-day stub year -> prefers full years.
- A never-falling series reported a bogus peak/trough/recovery -> nulls, handled in CLI and JS.

Considered and left (by design or out of scope; flagging for the handoff session):
- Forecast endpoint and `account.py` still use a raw `AssetSet`, so the same mix can show a different expected return in the forecast than on the frontier. This is ADR 0006 point 6 ("forecast untouched") and `account.py` is bucket B's file; revisit when forecast centres move (ADR "Reopens if").
- `AssetSet.analysis()` re-levels μ when `risk_free_rate != rf_level` (this is the brief's wording); `frontier(rf)` / `tangency(rf)` called directly do not. Documented above.
- The constant-correlation Σ applies to `--no-premium` / raw mode too (ADR 0006 point 5; the opt-out is about μ only). Old normal-method Σ is not reproducible from the CLI.
- `risk_free_rate()` and `risk_free_history()` fetch the same FRED CSV into two caches (two round trips on a cold start, independent expiry). Deriving the rate from the history is a sensible follow-up but changes bucket-neutral code; left.
- `/api/analyze` blocks on a FRED fetch when there is no cached history and FRED is slow; it then falls back to raw (visible only in `meta.premium` and the basis line).
- `to_dict()` repeats `history` for each frontier point (payload size); cheap to compute, kept to match the brief.


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
