# Handoff — `feature/scenarios`

| | |
|---|---|
| Branch | `feature/scenarios` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/scenarios` |
| Base | `main` @ `a7eb3fb` |
| Created | 2026-11-01 |
| Runserver port | 8002 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory is a
git worktree: it *is* this branch — do not `git checkout` another branch here.
Never run `fly` commands from this directory.

## Goal

Make the picture on Optimize more honest about resting on one market cycle, with two
additions ADR 0008 deferred to “next”, for any user:

1. **Scenarios:** how a mix did in named stress periods (2020 crash, 2022, …) and any
   dates you pick.
2. **Stability bands:** “how much would the best mix move on a different seven years?” A
   bootstrap diagnostic on the tangency weights, not a new answer.

Nothing about the owner’s real plan goes in code, copy or committed fixtures.

**Read:** `docs/decisions/0008-assumptions-mode.md`, `docs/decisions/0006-premium-expected-returns.md`,
`condor/history.py`, `condor/forecast.py` (its block bootstrap), `docs/research/ui-conventions.md`.

## Decisions already made

- **Scenario windows** (constants in `condor/history.py`, S&P 500 closing high to low, plus
  calendar 2022):
  - “2008 financial crisis”: 2007-10-09 → 2009-03-09
  - “2018 Q4 selloff”: 2018-09-20 → 2018-12-24
  - “2020 Covid crash”: 2020-02-19 → 2020-03-23
  - “2022 inflation shock”: 2021-12-31 → 2022-12-30
- A window counts only if the mix’s shared history covers **both** ends (start date no
  earlier than the series’ first date, end no later than its last). Otherwise
  `covered: false`; never a partial number. Say “Not in this mix’s shared history
  (starts {date})”. Start uses the last value on or before the start date.
- Basis is `value_index`: fixed weights, rebalanced every period. Say so.
- **Bands:** block bootstrap of the set’s daily rows, block 21 days (the forecast’s), the
  **same blocks across all assets and the T-bill**, re-running the set’s real estimators
  and the tangency: never a re-implementation. Fixed seed so results reproduce. Percentiles
  p10 / p50 / p90 per asset, plus `held_share` (share of resamples with weight > 1%).
  Default 100 resamples on the web, `--stability N` on the CLI. It works in history mode and
  under an `Assumptions` set (prior and limits applied in every resample).
- Bands run on demand (a button): they take seconds, and `/api/analyze` must not slow down.

## Scope

**In** — commit at the end of each phase.

### Phase 1 — scenarios engine + model

- `condor/history.py`: `window_stats(values, start, end) -> {ret, max_drawdown, covered,
  first}`; `SCENARIOS`.
- `Portfolio.scenarios(windows=None) -> list[dict]`, default `SCENARIOS`; a window is
  `{name, start, end}`. Rejects start ≥ end.
- `AssetSet.analysis()` adds key `scenarios`: `{basis, portfolio: […], tangency: […]}`.
  **Add only**; not on every frontier point (payload size).

### Phase 2 — stability engine + model

- New pure module `condor/stability.py` (block index generation, percentile summary), and
  `AssetSet.stability(risk_free_rate, constraints=None, n=100, block=21, seed=0) -> dict`:
  `{n, n_failed, block, seed, assets: {ticker: {p10, p50, p90, held_share}}}`. A resample
  whose solve fails or has no tangency counts in `n_failed`; never silently dropped.

### Phase 3 — API

- `POST /api/stability`: same input cleaning, rate limit and public access as `/api/analyze`,
  including the optional `assumptions` copy. `n` capped at 300. No storage.
- `/api/analyze` takes optional `scenario_windows`: up to 5 `{name, start, end}`, validated.

### Phase 4 — UI (Optimize; `app.js`, `optimize.html`, `assumptions.js`)

- **“How it would have done”** card below the tiles: rows = windows, columns = Your portfolio ·
  Best mix: return and worst fall in each. Not-covered rows say why, in words. A note: “Fixed
  weights, rebalanced daily. One path through history, not a forecast.” Add-your-own-dates row
  (name, start, end) re-runs analyze; not saved.
- **“How stable is the best mix?”** button in the compare area (history, and under a set when
  one is showing). While running, show progress text (`ui-conventions.md`: the 10-second rule).
  Result: per asset “{p10}–{p90}%, typically {p50}%; held in {held_share}% of resamples”, and one
  line: “Re-running the optimizer on reshuffled versions of your history. Wide ranges mean history
  can’t pin this mix down.”
- Don’t touch `account.js`, `account.html`, `condor/accounting.py` (another agent is there).

### Phase 5 — CLI + docs

- `portfolio` prints scenarios (and `--json` carries them); `analyze --stability [N]` prints the
  bands, honouring `--assumptions`.
- `README.md`, `docs/CLI.md`, `ARCHITECTURE.md` (`stability.py`). **Don’t edit `BACKLOG.md`**; the
  handoff session does that at merge, because parallel branches keep colliding there. Don’t run
  `/code-review` either: the handoff session rebases and runs it (see `docs/WORKTREES.md`), then
  sends you the findings. Review your own diff by hand before reporting.

**Out:** real-return mode, T-bill vs TIPS, Michaud averaging, saving custom windows or results,
scenarios on the account page, any change to `/api/analyze` numbers beyond added keys.

## Acceptance

Hand-checked; pin each in a test.

- **`window_stats`:** values 100, 120, 90, 130 on four dates: window (date 2, date 3) → ret −25%,
  max drawdown −25%. Window (date 1, date 4) → ret +30%, max drawdown −25%. A start between dates
  uses the prior value. A window starting before the series or ending after it → `covered: false`,
  `ret` null.
- **Bands, degenerate:** if every row of the data is identical across time except for a single
  repeated pattern that resamples can’t change (e.g. constant daily returns per asset, with a small
  fixed independent cycle of block length), the bands collapse: p10 = p50 = p90 within solver
  tolerance. **Identity:** a resample index equal to `range(n)` reproduces the set’s own tangency.
- **Same blocks:** the block generator gives every asset and the T-bill the same indices (assert
  on the indices); covers the sample length exactly; same seed → same result, different seed →
  different.
- **Limits in every resample:** a binding cap holds in all resamples (p90 ≤ cap + tolerance); a
  floor likewise.
- **Width shrinks with data:** on synthetic normals with known μ, Σ, bands from 5,000 rows are
  narrower than from 500, for each asset (seeded, so not flaky).
- **`n_failed`:** a set where no asset beats the rate → all failed, reported, no exception.
- **Web:** `scenarios` present, existing keys unchanged; `/api/stability` works anonymously and
  under `assumptions`; `n` cap enforced; bad windows → 400.
- **Real-data smoke check, reported in your final message, not committed:** `python -m condor
  analyze VT AVDV AVEM GLDM STIP --stability 100` and `python -m condor portfolio VT=60 STIP=40`.
- Suites at least at baseline (2026-11-01, base `a7eb3fb`, this worktree): `pytest tests/` **445
  passed, 4 skipped**; `manage.py test explorer` **232 OK**; `check` clean;
  `makemigrations --check --dry-run` clean (no migration expected).

## Status

- [x] Baseline recorded (445 passed, 4 skipped; 232 OK)
- [x] Phase 1 scenarios
- [x] Phase 2 stability
- [x] Phase 3 API
- [x] Phase 4 UI
- [x] Phase 5 CLI + docs + hand review of own diff

Built 2026-11-01. Suites: pytest 474 passed / 4 skipped; `manage.py test explorer` 243 OK; check and
makemigrations clean. Not exercised: a real browser (JS checked with `node --check` and a stub-DOM run).

## Questions for the handoff session

- Own-dates row holds one custom window at a time (4 built-ins + 1 = the API's cap of 5). Say if you want
  the built-ins droppable instead.
- Stability card sits as its own card under the scenarios card, not inside the assumptions card; the
  "under my assumptions" button appears only when a set is showing.
- `/api/stability` has its own rate bucket (`stability`, 6/m) beside analyze's 15/m.

## Return protocol

Keep Status current. Commit locally; **do not push, open a PR or merge**. Report: last commit, test
counts vs baseline, deviations, renamed strings, smoke-check output, timing of a 100-resample run,
anything unverified. The handoff session reviews, merges and pushes.
