# Handoff — `feature/forecast-anchors`

<!-- Seeded from docs/handoffs/_template.md by scripts/new-worktree.sh.
     Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/forecast-anchors` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/forecast-anchors` |
| Base | `main` @ `b6fda19` |
| Created | 2026-09-02 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Forecaster **rung C** of the research ladder (green-lit by RT 2026-08-23):
an **expected-return anchor control** on the forecast card. The sample
mean is the forecast's weakest input (SE ≈ s·√ppy/√n — for a 10-year
window that's ±5–6 pp/yr on a typical equity mix), so the user gets to
choose what the fan chart's centre assumes: their portfolio's own history,
a long-run market anchor blended with that history, or a custom number.
The fan redraws live so the user *sees* that the whole chart hinges on
this one number — that visibility is the most educational thing the
feature can do. Both forecast models (steady + bootstrap) honour the
choice.

## Scope

**In:**
- Engine: posterior-blend function in `condor/forecast.py` (pure, tested).
- Model: `Portfolio.forecast(...)` grows anchor parameters; `Forecast.to_dict()`
  reports what was assumed so the UI can badge it.
- Web API: `api_forecast` (Build page) and the account forecast endpoint
  (`web/explorer/account.py`) accept the anchor parameters.
- UI: a three-way control on the forecast card on **both** Build and My
  account pages — `Historical (x%)` / `Long-run market (y%)` / `Custom __%`
  — with the assumption sentence updated to say what the centre line now
  assumes and where the number came from.
- Tests per the acceptance list below.

**Out** (do not do here — belongs on `main` or another bucket):
- Multi-asset Black–Litterman on the *frontier* (`pypfopt.BlackLittermanModel`,
  market-cap priors, user views/tilts). That is the fuller rung-C version and
  a separate BACKLOG item; this bucket is the univariate (portfolio-level)
  Bayesian blend only. Do not touch frontier construction or `AssetSet`.
- Auto-fetching CAPE or Damodaran ERP data. The long-run anchor is a
  documented constant for now (see decisions); live anchor sources are a
  future bucket.
- The backtest panel / coverage notebook (queued separately).
- Probability-of-goal displays of any kind.

## Acceptance

- [ ] `anchored moments` engine function with verification tests:
  - closed-form hand case: known μ̂, SE, anchor, prior SD → posterior mean
    and SD computed by hand match to 1e-12;
  - prior SD → ∞ recovers the historical μ̂ and SE exactly;
  - prior SD → 0 recovers the anchor exactly with zero posterior SD;
  - posterior SD < min(SE, prior SD) whenever both are finite and > 0.
- [ ] Steady model: with an anchor selected, `lognormal_bands` centres on
  the posterior mean and its `_est` (estimate-error) columns use the
  posterior SD. Model-equals-engine test.
- [ ] Bootstrap model: the per-path drift draw becomes N(posterior mean −
  sample mean, posterior SD²) applied as a constant per-path log-drift
  offset (today it is N(0, s²/n) around the sample drift — recentre and
  rescale, same mechanism). The `band_floor` guard still floors model 2 at
  model 1's bands *computed under the same anchor*.
- [ ] API: anchor params validated (mode ∈ {historical, market, custom};
  custom value bounded, say −20%..+30%/yr; garbage → 400 with a message,
  not a traceback). Django tests for both endpoints.
- [ ] UI: control renders on Build and Account forecast cards; switching
  redraws the fan without a full analyze; the assumption sentence names
  the number and its source; badge shows e.g. "anchored 8% ± 3 pp".
  Historical remains the default — zero behaviour change unless the user
  touches the control.
- [ ] Full suites not worse than baseline (record counts before starting:
  expect ~202 passed + 2 skipped core, 41 Django).

## Context & decisions already made — do not re-open

- **Research basis:** `docs/research/forecast-methods-ladder.md` § "Rung C"
  and § 7a (Black–Litterman as a prior on μ). Read both before coding.
  Existing engine: `condor/forecast.py` (rungs A and B, docstrings explain
  the math); model layer: `Forecast` in `condor/model.py`.
- **The blend is precision-weighted (conjugate normal):**
  `μ_post = (μ̂/SE² + a/τ²) / (1/SE² + 1/τ²)`, `σ_post² = 1/(1/SE² + 1/τ²)`,
  where `a` = anchor, `τ` = prior SD. Work in **log-return space**: convert
  the annual simple anchor via `log(1 + a)` and treat τ as log-space
  directly (document the approximation in the docstring; at these
  magnitudes the error is second-order).
- **Long-run market anchor value:** a module-level constant, **8%/yr
  nominal, τ = 3 pp**, with a comment citing the ladder doc's §7a
  discussion (CAPM/equilibrium range 7–8%). Not fetched from anywhere.
- **Custom anchor:** user types an annual %, same τ = 3 pp default so the
  estimate-error band stays alive and honest. (An "I'm certain" τ=0 mode
  is deliberately not offered.)
- **Historical mode is the identity:** it must produce bit-identical
  output to today's forecasts — assert this in a test.
- **Vocabulary:** *expected return*, *dispersion* (CLAUDE.md). UI copy
  follows the ladder's honesty rules: name what the median assumes, keep
  the ± sentence, dollars-and-multiples formatting stays as is.
- **UI mechanics:** follow the existing forecast-card pattern in
  `web/explorer/static/explorer/app.js` / `account.js` (model picker
  already re-fetches without a full analyze — the anchor control does the
  same). Charts are interaction-locked (`CHART_CONFIG`) — do not change
  chart config.

## Conflict watchlist

Nothing else is in flight on `main` right now. Highest-churn files if that
changes: `web/explorer/static/explorer/app.js`, `index.html`,
`condor/forecast.py`. Rebase onto `main` before opening the PR
(`git fetch origin && git rebase origin/main`).

## Status

- [ ] Baseline suite counts recorded
- [ ] Engine: anchored moments + tests
- [ ] Steady model anchored + tests
- [ ] Bootstrap model anchored + tests
- [ ] API params + Django tests (Build + Account)
- [ ] UI control on Build
- [ ] UI control on My account
- [ ] `/code-review` at medium on this branch (engine numerics → required)
- [ ] PR opened against `main`

## Questions for the handoff session

- None yet. If the 8% / 3 pp defaults feel wrong once you see them on
  screen, park a note here — do not invent different numbers.

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
   legacy agreement); model changes need an "equals the engine" test.
3. This bucket touches engine numerics → run **one** `/code-review` at
   *medium* on this branch before opening the PR, and land the fixes here.
4. Push the branch and open a PR against `main`. PR body = the review
   packet: what changed and why, deviations from this brief, the test
   counts vs baseline, the new UI copy quoted for review, and any
   pre-existing bug you noticed but did not fix.
5. The handoff session reviews proportionately to risk
   (`docs/WORKTREES.md` § Review policy), merges, deploys from `main`,
   and updates the registry.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/forecast-anchors
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
