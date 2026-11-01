# Handoff — `feature/assumptions-1`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/assumptions-1.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/assumptions-1` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/assumptions-1` |
| Base | `main` @ `b7b6ff1` |
| Created | 2026-11-01 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Let anyone state their assumptions and rules and see the frontier, best mix
(tangency) and capital line computed under them, next to the history-only
view, with their own plan marked on both: *“under my assumptions and rules,
where is the best point, and how far is my plan from it?”* Today’s best mix
is mostly hindsight, because it fits one historical window.

RT’s real portfolio motivates this, but it is a **general feature for any
user**: nothing about RT’s plan goes in the code, the copy or committed
fixtures.

**Read before coding:** `docs/decisions/0008-assumptions-mode.md` (the design,
committed with this brief) and `docs/decisions/0006-premium-expected-returns.md`
(premium mode, which this builds on). For Optimize-page work, also
`docs/research/ui-conventions.md`.

## Scope

**In** — in this order; commit at the end of each phase.

### Phase 1 — the `Assumptions` object (`condor/assumptions.py`, new, pure)

Frozen dataclasses with `from_dict` / `to_dict` (round-trip exact). `from_dict`
raises `ValueError` naming the bad field; it is the one validator, used by the
API, CLI and storage.

```python
Group(tickers: tuple[str, ...], lo: float = 0.0, hi: float = 1.0)
Constraints(bounds: dict[str, tuple[float, float]], groups: tuple[Group, ...])
View(ticker: str, ret: float, sd: float)   # annual total return, ± in the same units
Prior(kind: "history" | "equilibrium", reference: str = "VT",
      market_premium: float | None = None, t0: float = 20.0,
      views: tuple[View, ...] = ())
Assumptions(name: str, prior: Prior, constraints: Constraints)
```

JSON shape:
```json
{"name": "…",
 "prior": {"kind": "equilibrium", "reference": "VT", "market_premium": null,
           "t0": 20, "views": [{"ticker": "AAA", "ret": 0.10, "sd": 0.05}]},
 "constraints": {"bounds": {"AAA": {"min": 0.05, "max": 0.30}},
                 "groups": [{"tickers": ["AAA", "BBB"], "max": 0.40}]}}
```
`min` defaults 0, `max` defaults 1. Validate: weights in [0, 1], min ≤ max,
`t0` ≥ 0, `sd` > 0, `market_premium` ≥ 0 or null, ≤ 20 groups, ≤ 15 views.
`Constraints` also offers:
- `resolve(tickers)` → per-asset bound list, groups as index lists, and
  `ignored` (names of limits on tickers not in this analysis; a group keeps
  its members that are present, and is ignored if none are);
- `violations(weights)` → human strings like `"GLDM 20.0% is above its 15.0% limit"`.

### Phase 2 — engine

- `condor/stats.py`:
  - `equilibrium_premiums(sigma, reference, market_premium)` — `reference` is a
    ticker in `sigma` or a `{ticker: weight}` dict. `Π = δΣw`, `δ =
    market_premium / (wᵀΣw)`.
  - `blend_premiums(prior, sample, t0, t_years, method)` — `(T₀·Π + T·μ̂) /
    (T₀ + T)`, with `T × 2/π` for robust.
  - `apply_views(mu, sigma, tau, views)` — PyPortfolioOpt
    `BlackLittermanModel` (`absolute_views`, `omega = diag(sd²)`, `tau`); no
    views returns `mu` unchanged.
- `condor/frontier.py`:
  - `_solve(mu, sigma, kind, constraints=None, **kw)`: `None` keeps today’s path
    **exactly** (legacy-pinned tests). Otherwise per-asset `weight_bounds`
    plus `add_constraint` for groups. Constraints arrive already resolved.
  - `_constrained_tangency(mu, sigma, rf, resolved)` — the homogenized QP in
    ADR 0008 §1 (cvxpy, already a dependency via PyPortfolioOpt; use
    `cp.psd_wrap`). `w = y / k`. Returns None when no feasible mix beats
    `rf`; raises `ValueError` when the limits are infeasible.
  - `_constrained_max_return(mu, resolved)` — LP, the frontier’s top end.
  - Infeasible limits (e.g. minimums summing above 1) raise `ValueError("These
    limits can't all hold: …")`.

### Phase 3 — model (`condor/model.py`)

- `AssetSet(..., prior: Prior | None = None, reference_prices: pd.Series | None
  = None)`, keyword-only. A prior needs premium mode (`rf_history`), else
  `ValueError`. `kind="history"` means no blending and no reference needed.
- With `kind="equilibrium"`:
  - Σ for `Π` comes from `stats.risk_matrix_annual` on the set’s prices joined
    with the reference (overlap only), same method. A reference in the set
    uses the set’s prices; otherwise `reference_prices` is required.
  - Market premium: the prior’s value, else `max(MARKET_ANCHOR − rf_level, 0)`,
    importing the forecast constant (no second copy of 8%).
  - `T` = window calendar years (days / 365.25).
  - Posterior premium = `apply_views(blend_premiums(...), Σ, 1/(T₀ + T_eff),
    views)`, each view’s `q = view.ret − rf_level`. Views on tickers not in the
    set are ignored.
- `expected_returns` = `rf_level + posterior`. New read-only:
  `sample_premiums`, `prior_premiums` (None when no equilibrium prior);
  `premiums` is what `expected_returns` uses. `summary()` adds both columns when
  present. `with_options` carries `prior` and `reference_prices`; re-leveling
  must recompute a default market premium.
- `min_vol`, `tangency`, `efficient_return`, `efficient_risk`, `frontier` all
  take `constraints=None`. `Frontier` stores them, runs its range from the
  constrained min-vol to `_constrained_max_return`, and `to_dict()` adds
  `constraints` (bounds, groups, ignored) only when constrained.
- `Frontier.gaps(portfolio) -> dict`: `sharpe_gap` (tangency − plan),
  `return_gap` (`at_dispersion(plan) − plan`), `risk_gap` (plan − `at_return(plan)`),
  `at_risk` / `at_return` (payload dicts, or null), `violations`. **Null, not 0,**
  when the comparison is infeasible or there is no tangency.
- `AssetSet.analysis(..., constraints=None)`: passes through; adds `assumed`-side
  data only, and the unconstrained, prior-free payload stays byte-identical.
- “Equals the engine” tests for all of this.

### Phase 4 — storage and API

- `AssumptionSet` model + migration 0008: `id` uuid, `owner` FK, `name` (80),
  `payload` JSON, timestamps. Storage only (ARCHITECTURE).
- `GET/POST /api/assumptions`, `GET/PUT/DELETE /api/assumptions/<uuid>`: login
  required, owner-scoped, someone else’s id → 404 (same as unknown). Validate
  with `Assumptions.from_dict`. Limit 50 sets per user.
- `/api/analyze` takes an optional `assumptions` object (a **copy**, never an
  id). It stays public, so anonymous visitors can use the feature without
  saving. The history payload is unchanged; the response gains key `assumed`:
  the same analysis shape computed under the set, plus `gaps`, `name`,
  `assumptions` (echo), and `prior_note` = `{t0, t_years, t_effective,
  market_premium, reference}`. Any failure (infeasible limits, bad reference,
  no T-bill history, `premium: false`) becomes `assumed: {"error": "…"}` and the
  history result still renders.
- If the reference isn’t in `tickers`, fetch it separately (`fetch_prices`/store)
  so it can’t shorten the analysis window.

### Phase 5 — UI (Optimize page)

Opt-in: history stays exactly as it is until the user asks. No numerics in JS.

- New card under the chart, collapsed: **“Under my assumptions”**, one line of
  explanation: “History alone mostly picks whatever won lately. State your limits
  and a long-run view to see the best mix under them, next to history.”
- **Editor:**
  - Limits: a min % and max % input per current asset, plus group rows (assets +
    a max %, optional min %).
  - Long-run view: market premium (placeholder shows the computed default),
    “Weight of the long-run view, in years of data” (default 20), market proxy
    (default VT). A plain “Use history only” switch sets `kind: "history"`.
  - Your views, optional rows: asset, expected return %, ± points.
- **Saved sets** dropdown, Save / Save as / Delete (logged in). Signed out: the
  editor works and Save invites sign-in. Editing never changes a saved set until
  Save, and a saved set is copied into the request.
- **Result:**
  - A second chart (`#chart-assumed`, same styling and traces) beside the main
    one on wide screens, stacked on phones (16px gutters, no horizontal scroll;
    follow `touch-action`/config conventions in `ui-conventions.md`).
    “Your portfolio” marked on both. Copy above it: “Under: {name}”.
  - The long-run note: “The long-run view counts as {t0} years of data; your
    history as {t_effective} years.” (say “robust method: history counts less”
    when `t_effective` < `t_years`).
  - A compare table, History vs Under: best mix weights, and your portfolio’s
    return / dispersion / Sharpe.
  - “How far is your portfolio from the best mix?” Three rows: “Risk-adjusted
    return (Sharpe) gap”, “Return you could add at the same risk”, “Risk you could
    shed at the same return”. Null → “n/a: {why}”. Then any `violations` as a short
    list headed “Your portfolio breaks these limits”, and `ignored` limits as a
    muted note.
  - `assumed.error` shows in the card, in words; the history chart is untouched.
- Don’t touch `account.js`/`account.html`.

### Phase 6 — CLI

`analyze` and `portfolio` take `--assumptions FILE.json` (fetching the reference
as needed). Text output adds an “Under: {name}” section (`analyze`: per-asset
expected return, sample and prior premium, frontier anchors; `portfolio`: its
stats under the set and the three gaps, and violations). `--json` adds `assumed`.
`--no-premium` with `--assumptions` is an error.

### Phase 7 — docs + review

- `README.md`, `docs/CLI.md`, `ARCHITECTURE.md` (table rows: `assumptions.py`),
  `BACKLOG.md` (move `assumptions-1` to Done; keep A3-narrowed, A5 and stability
  bands open as the next bucket).
- `/code-review medium` (ordered: engine numerics + a migration). **Pass an
  explicit range against this branch’s merge base** so it reviews only this
  branch, e.g. `medium $(git merge-base main HEAD)..HEAD`, and confirm from its
  findings that it read your files. If it reports on code you didn’t touch, it
  compared the wrong thing: review your own diff by hand instead and say so. Land
  fixes as the final commit; summarise in Status.

**Out** (do not do here):

- Real-return mode, T-bill vs TIPS, inflation beta, real-dollar fan (A3); named
  scenario windows (A5); stability bands; Michaud; “smallest weight changes”.
- The forecast fan under a set. Editing accounts or plans. Changing history-only
  numbers.
- Anything specific to RT in code, copy or committed fixtures, and no real ledger
  or amounts anywhere in the repo.

## Acceptance

Hand-checked; pin each in a test (verification style, CLAUDE.md). Annual,
long-only, fully invested. The first five come from the source repo’s
`docs/condor-assumptions-mode.md` and were re-derived.

- **T1 limits that don’t bind:** bounds looser than the unconstrained solution
  → the unconstrained tangency, to 1e-6. (If the solver can’t reach that even with
  tight tolerances, 1e-4, and say so in Status.)
- **T2 a cap that binds:** A μ 10% σ 20%, B μ 4% σ 5%, ρ 0, rf 2%. Unconstrained
  tangency **(0.20, 0.80)**: μ 5.20%, σ 5.657%, Sharpe 0.5657. With B ≤ 0.60:
  **(0.40, 0.60)**: μ 6.40%, σ 8.544%, Sharpe 0.5150. Cross-check the QP against
  a dense frontier scan on a 3–4 asset case with a group cap.
- **T3 no views reproduces the reference:** `Π = δΣw_ref`, no views → posterior
  `Π`, and the tangency on `(Π, Σ, rf = 0)` = **w_ref**, for a multi-asset `w_ref`.
- **T4 one absolute view:** Σ = diag(0.04, 0.0025), τ = 0.05, Π = (0.06, 0.01),
  view “A returns 10%” with sd² = 0.002 → **μ_A = 0.08**, μ_B = 0.01. sd → 0 gives
  μ_A → 0.10; sd → ∞ gives μ_A → 0.06.
- **T5 the blend:** T₀ = 25, T = 6.9, Π = 0.08, μ̂ = 0.16 → **9.73%**. Robust:
  T = π/2, T₀ = 1, Π = 0, μ̂ = 0.10 → **5.00%** (T counts as 1).
- **Equilibrium:** Σ = [[0.04, 0.012], [0.012, 0.0225]], reference the first asset,
  market premium 5% → **Π = (5.0%, 1.5%)** (β = 0.3). Reference outside the set:
  same numbers from the joined Σ.
- **Gaps, assets of T2 with plan (0, 1)** (μ 4%, σ 5%, Sharpe 0.40):
  - Unconstrained: `sharpe_gap` **0.1657**; `return_gap` **0.7059 points** (the
    other mix at σ 5% is w_A = 0.117647, μ 4.7059%); `risk_gap` **0**.
  - With B ≤ 0.60: `sharpe_gap` **0.1150**; `return_gap` and `risk_gap` **null**
    (cheapest allowed risk is 8.544%, lowest allowed return 6.4%); violations names B.
  - The tangency itself as the plan: all three gaps ≈ 0.
- **Infeasible limits** (mins summing above 1) → the error message in the engine
  and `assumed.error` in the API, with the history payload intact.
- **Round trip:** `Assumptions.from_dict(x).to_dict() == x`; one failing test per
  validation rule.
- **Web:** `assumed` present only when asked; anonymous analyze with `assumptions`
  works; CRUD is owner-scoped, foreign id → 404; editing a saved set doesn’t change
  an earlier response (copy semantics). Without `assumptions` the payload is
  unchanged (compare to a stored dict from the same inputs). Patch fetches as
  existing tests do.
- **Real-data smoke check, reported, not asserted, and NOT committed.** Run
  `python -m condor portfolio STIP=20 USFR=5 VT=20 RSP=10 AVDV=7.5 AVEM=7.5 GLDM=10 VST=10 URNM=6.67 DNN=3.33 --assumptions /private/tmp/claude-501/-Users-rtasseff-projects-condor-v2/8952d0db-4b93-4f69-99ef-221c42dee656/scratchpad/assumptions_seed.json`
  and the same under `analyze`, robust and normal. Put the output in your final
  report to the handoff session, not in Status or any repo file: that file holds
  RT’s real limits and must stay out of the repo.
- Suites at least at baseline (2026-11-01, base `b7b6ff1`, this worktree):
  `pytest tests/` **395 passed, 4 skipped**; `manage.py test explorer` **215 OK**;
  `check` clean; `makemigrations --check --dry-run` clean after your migration.

## Context & decisions already made

- ADR 0008 is decided; park questions, don’t reopen it. RT’s defaults are the
  product defaults: market premium `MARKET_ANCHOR − T-bill`, T₀ 20, VT, opt-in.
- Payloads: add keys, never rename. History-only must stay byte-identical.
- Vocabulary: *expected return*, *dispersion*, *robust*. Say “best mix” in UI copy
  and “tangency” in code.

## Conflict watchlist

- Nothing else is in flight on `main` as of this brief. RT’s portfolio session may
  ask for small account fixes on `main`; rebase if `main` moves. Your files are
  mostly new or in `stats.py`, `frontier.py`, `model.py`, `cli.py`, `views.py`,
  `app.js`, `optimize.html`.

## Status

- [x] Baseline recorded: 395 passed / 4 skipped; 215 OK (matched the brief)
- [x] Phase 1 `Assumptions` (`condor/assumptions.py`, `tests/test_assumptions.py`)
- [x] Phase 2 engine (`stats.py`, `frontier.py`; `tests/test_assumptions_engine.py`)
- [x] Phase 3 model (`model.py`; same test file)
- [x] Phase 4 storage + API (migration 0008, `/api/assumptions`, `assumed`;
      `web/explorer/test_assumptions.py`)
- [x] Phase 5 UI (`assumptions.js`, card in `optimize.html`, `drawFrontier`
      in `app.js`)
- [x] Phase 6 CLI (`--assumptions`; `tests/test_cli.py::TestAssumptions`)
- [x] Phase 7 docs + `/code-review medium b7b6ff1..HEAD` (see below)

**Final counts:** `pytest tests/` 432 passed, 4 skipped (baseline 395/4);
`manage.py test explorer` 230 OK (baseline 215); `check` clean;
`makemigrations --check --dry-run` clean. Legacy-pinned tests untouched.

**Hand-checked numbers, all pinned and passing:** T1 (non-binding limits equal
the unconstrained tangency, to 1e-4 only because pypfopt's `clean_weights`
rounds the unconstrained side to 1e-5; the QP itself agrees to ~1e-10 on the
T2 case), T2 ((0.2, 0.8) and (0.4, 0.6), Sharpe 0.5657 / 0.5150, plus a
dense-grid cross-check on 4 assets with an asset cap and a group cap), T3, T4
(0.08 / 0.01, sd to 0 and infinity), T5 (9.73% and 5.00%), equilibrium
(5.0% / 1.5%, reference inside and outside the set), gaps (0.1657 / 0.7059
points / 0 unconstrained; 0.1150 / null / null with B <= 0.60; ~0 at the
tangency), infeasible limits, round trip and one test per validation rule,
and the web items.

**Deviations and interpretations (please check):**
- *Result layout:* the brief says `#chart-assumed` sits "beside the main
  chart". The history chart shares a row with the sidebar, so the assumed
  chart sits in the new card directly under it (chart on the left, compare
  table and gaps on the right on wide screens, stacked on phones).
- *Gap definitions need "exactly":* `risk_gap` compares with the least
  dispersion at exactly the plan's return (`efficient_return(..., exact=True)`,
  an equality constraint), not pypfopt's `>=`. The brief's hand numbers
  (risk gap 0 for plan (0, 1)) require it. A plan whose return is outside what
  the limits allow gets null. `return_gap` uses `efficient_risk` at the plan's
  dispersion, null when it is below the cheapest allowed dispersion.
  A gap can be negative when the plan itself breaks a limit (it then beats the
  constrained best); the violations list explains it.
- *`kind: "history"` with views:* views still apply on top of the sample
  premiums (tau = 1/T_eff). The brief only says "no blending, no reference".
- *`to_dict` omits default limits* (min 0 / max 1) so the brief's example
  round-trips exactly; `Constraints.resolve` returns a small
  `ResolvedConstraints` dataclass (bounds, groups, ignored).
- *Extra payload keys* (additive only, and only when assumptions are in play):
  `gaps` and `constraints` when `AssetSet.analysis(constraints=...)` is used;
  `prior_note` (also `kind`) and `premiums` {sample, prior, posterior} when the
  set has a prior. `AssetSet.analysis_under`, `AssetSet.max_return`,
  `AssetSet.prior_note`, and `with_options(prior=, reference_prices=)` were
  added. `Frontier.violations` too.
- *Malformed `assumptions` in `/api/analyze`* (fails `from_dict`) becomes
  `assumed: {"error": ...}` with HTTP 200, like the other failures, not a 400.
- *Constraint-path numerics:* frontier points with limits use pypfopt with
  `weight_bounds` and `add_constraint`; the last point's target is lowered by
  1e-9 so the LP's own top end isn't borderline infeasible.
- *y-axis (coordinator request):* `renderChart` now goes through
  `drawFrontier(divId, r, opts)`; the y range is set from the frontier, the
  assets, min-dispersion and tangency points, and the risk-free rate (1.15 x
  their max on top; 8% of the span below the lowest), so the capital line runs
  off the top. Both charts use it. No payload or model change. Checked with a
  stub: a capital line to 120% gives range top / max point = 1.15.
- *touch-action:* `#chart-assumed` has `touch-action: pan-y`; `#chart` did not
  have it and was left alone.

**Renamed user-facing strings:** none (all new). The "Click to inspect" hover
hint is now omitted on the assumed chart, where nothing opens on click.

**What was and wasn't exercised (no real browser):** Django test client for all
endpoints and the page render; `node --check` on `app.js` and
`assumptions.js`; a stub-DOM harness (kept outside the repo) that ran the
card's request building, opt-in, render of a real server payload (compare
table, gaps, n/a rows, violations, ignored note, error), and saved-set
list / load / update / save-as-new / two-step delete flows; a Plotly stub run
of `drawFrontier` for the y range. NOT exercised: real Plotly rendering,
layout/CSS at phone and desktop widths, focus and keyboard behaviour,
`touch-action` in a touch browser.

**Code review:** `/code-review medium b7b6ff1..HEAD` was run and was NOT
usable: all six findings were about `account.js` / `account.html` (pay-in
plan panel, buy-list filter, tickformat, a removed `warn` class), files this
branch never touched (`git diff b7b6ff1..HEAD --stat` has no account file);
it compared against the moved `main` (now 541ead4). Instead I reviewed the
full diff by hand (engine, model, views, JS). Fixes landed from that: ticker
shape validated in `Assumptions.from_dict` (the market proxy is fetched by
name, so an arbitrary string must not reach the data layer), caps of 50
bounds and 50 tickers per group, an unused variable removed. The account.js
findings are for whoever owns `main`'s account work, not this branch.

**Pre-existing, not fixed:** none noticed.

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
3. This brief **orders a `/code-review` at medium** (Phase 7): run it on this
   branch and land the fixes as your final commit, summarised in Status.
4. **Do not push, do not open a PR, do not merge.** Your report packet is THIS
   doc: Status checklist current, deviations listed, every renamed user-facing
   string quoted (before → after), test counts vs baseline, any pre-existing bug
   noticed but not fixed. Commit it all locally and tell the human you are done.
5. The handoff session reviews proportionately — spot-checks, never a redo
   (`docs/WORKTREES.md` § Review policy) — merges your local branch, pushes `main`,
   and the human deploys.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/assumptions-1
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree and
gitignored. The price store self-heals by re-downloading if stale.
