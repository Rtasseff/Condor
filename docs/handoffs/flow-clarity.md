# Handoff — `feature/flow-clarity`

<!-- Seeded from docs/handoffs/_template.md by scripts/new-worktree.sh.
     Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/flow-clarity` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/flow-clarity` |
| Base | `main` @ `55d1715` |
| Created | 2026-09-04 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

First live-user feedback round on the Build/Optimize split (RT,
2026-09-04). Users like Build, but the flow around it confuses them in
five specific ways, all fixable in `web/` without touching the engine:
(1) Optimize silently analyzes default assets when the user never built
anything; (2) there is no way to optimize starting from the *real*
portfolio (their account holdings) vs the *draft*; (3) "forecast X
dollars" exists but nobody finds it; (4) on My account it is not obvious
that money can enter all-at-once vs over-time, nor that you can forecast
after; (5) two labels mislead — "Robust" reads as "assuming a robust
economy" and the rung-C anchor control reads as a statistics knob, so
even RT could not find the Bayesian prior they asked for.

## Scope

**In:**
- Optimize gating (no silent defaults) + a Draft/Real source picker.
- "Make this my real portfolio →" adoption copy.
- A "What could it become?" dollar-forecast entry on Build that deep-links
  into the Optimize forecast card.
- My account: an "Add money" chooser (at once vs over time) + a
  forecast nudge.
- Label/copy fixes: Robust gloss, forecast model badge de-numbering,
  anchor control renamed to belief language.
- Django tests for the server-visible behavior; JS behavior verified by
  click-through.

**Out** (do not do here — belongs on `main` or another bucket):
- Any `condor/` change, any migration, any new model. Everything here
  runs on existing endpoints (`/api/draft`, `/api/account`,
  `/api/analyze`, `/api/forecast`, target/plan APIs).
- Multiple named drafts (saved portfolios already cover "drafts" plural:
  loading a saved portfolio becomes the working draft — keep that).
- Forecast math, anchor defaults, band semantics — rung C is done;
  this bucket only renames what the user sees.
- The Learn page.

## The five fixes, precisely

### 1. Optimize must not invent a portfolio

Today `/optimize` with no draft falls back to default/hardcoded assets
and auto-analyzes. Instead: if the user has **no draft and no real
holdings**, hide the analyze form/chart column behind a friendly
empty-state card — "Nothing to optimize yet. Pick your assets in
**Build** first →" (link to `/`). No auto-analyze, no quick-add row on
Optimize in that state. (Build keeps its own starter quick-adds — that
is where picking belongs.)

### 2. Optimize off draft OR real

When at least one source exists, show a compact source control above the
asset list: **Optimizing: [Your draft] [Your real portfolio]**.

- "Your real portfolio" appears only when the account has holdings;
  weights come from `/api/account` `positions[].weight` (client-side —
  no new endpoint).
- Switching source loads that source's assets+weights and re-analyzes
  (same auto-analyze the draft prefill already does).
- Editing assets/weights while on "real" forks the working copy into the
  draft and flips the indicator to "Your draft (edited from your real
  portfolio)" — reality only ever changes through the ledger.
- Adopting a point (fix 3) works from either source.

### 3. Adoption speaks the user's language

Rename "Use as account setpoint →" to **"Make this my real portfolio →"**
(button + title: "Copies this mix to your account and opens the plan —
whole shares at the last close — for turning what you hold now into
this."). The destination (transition report → confirm) already exists
and already does whole-share math; this is copy + the source-agnostic
wiring from fix 2. The report page heading should echo it: "How to get
there from what you hold."

### 4. "I just wanted to forecast X dollars"

- **Build**: a small card after "Your assets" — "**What could it
  become?** \$[input, default 10,000] in this mix over [2 years ▾] →
  **See the range**". Clicking navigates to
  `/optimize?forecast=<amount>&years=<n>`; Optimize reads the params,
  auto-analyzes, runs Project with that starting amount/horizon, and
  scrolls to the forecast card. No fan chart on Build itself this round.
- **My account**: the ledger card grows a one-line chooser header —
  "**Add money:** all at once → record a deposit below · over time →
  set a schedule" (anchor links to the existing forms), and after the
  value tiles a nudge line: "Curious where it could go? **Forecast your
  account →**" (anchor to the account forecast card).

### 5. Words that mislead

- **Method dropdown (Optimize toolbar):** option text becomes
  "Robust statistics (outlier-resistant)" / "Classic statistics
  (mean / SD)", label stays "Method", and add a gloss under the control:
  *"How we measure history — not a view about the economy."* Keep
  *robust* as the term (project vocabulary) — the gloss carries the
  clarification. Mirror the same wording in the "What am I looking at?"
  explainer bullet.
- **Forecast model badge** (`app.js` ~722 and the account twin): drop
  the "model N of 3" numbering — say "steady rates (simplest)" /
  "resampled history (21-day blocks)". The "of 3" advertised a third
  model that is actually the anchor control, which is what sent RT
  looking for a missing feature.
- **Anchor control** (`optimize.html` #fanchor + account twin): label
  becomes "**What to assume about returns**", options: "My mix's own
  history" / "**Return to normal** ({{ market_anchor_pct }}%/yr)" /
  "My own number…". Gloss under it: *"A belief about the future,
  blended with your data by how sure each is — never swapped in."*
  Update the details fold to match. API values (`historical`/`market`/
  `custom`) do not change.

## Acceptance

- [ ] Fresh user (no draft, empty account): `/optimize` renders the
  empty-state card, no chart, no default assets; Django test asserts the
  empty-state marker and absence of the analyze form.
- [ ] With a draft only: picker hidden or draft-only; behavior as today.
- [ ] With holdings: picker shows both; switching to real loads account
  weights (verified live); editing forks to draft with the indicator.
- [ ] Adopt button reads "Make this my real portfolio →" from either
  source; transition report unchanged mechanically.
- [ ] Build card deep-link: `/optimize?forecast=25000&years=5` analyzes,
  projects \$25,000 over 5y, scrolls to the card (verified live);
  malformed params fall back silently to defaults.
- [ ] Account page shows the add-money chooser and the forecast nudge;
  anchors land on the right cards.
- [ ] All renamed strings present; no occurrence of "of 3" in served
  JS/templates; Django template tests updated (several assert current
  copy — e.g. the anchor-control test).
- [ ] Suites not worse than baseline (expect ~219 passed + 2 skipped
  core — some data tests need network, note skips; 60 Django); `check`
  + `makemigrations --check` clean; **no new migrations**.

## Context & decisions already made — do not re-open

- Draft is the single working copy (`DraftPortfolio`, one per user,
  `/api/draft`); adopting a point already syncs it. Saved portfolios =
  named drafts; loading one overwrites the working draft (existing).
- Real portfolio = account positions at last close from `/api/account`;
  it is read-only from Optimize's perspective.
- Charts stay interaction-locked (`CHART_CONFIG`); do not change chart
  config or the forecast card's mechanics — only its words.
- Vocabulary (CLAUDE.md): *expected return*, *dispersion*, *robust* —
  glosses explain, they don't replace canon terms.
- UI conventions research (`docs/research/ui-conventions.md`) still
  governs: visible glosses over `title=` attributes, one dismissible
  hint, honest empty states.

## Conflict watchlist

Nothing else is in flight. You will touch the same files rung C and
home-builder just merged into (`optimize.html`, `app.js`, `account.js`,
`account.html`, `home.html`, `home.js`, `views.py`, `tests.py`) — all
settled on `main` now. Rebase onto `origin/main` before the PR anyway.

## Status

- [ ] Baseline suite counts recorded
- [ ] Fix 1: Optimize gating + tests
- [ ] Fix 2: source picker + fork-to-draft
- [ ] Fix 3: adoption copy
- [ ] Fix 4: Build dollar-forecast card + deep link; account chooser + nudge
- [ ] Fix 5: renames + glosses; template tests updated
- [ ] Click-through on port 8001 (all five fixes); screenshots in PR
- [ ] Rebase on origin/main; suites re-run
- [ ] PR opened against `main`

## Questions for the handoff session

- None yet. Copy is specified above — if a string reads badly in place,
  improve the wording but keep the meaning; note it here.

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
3. This bucket is **copy + ordinary UI flow** (no engine, no migration,
   no new endpoints): no automated review. The handoff session will read
   the diff at merge.
4. Push the branch and open a PR against `main`. PR body = what changed
   and why, deviations, test counts vs baseline, **every renamed
   user-facing string quoted** (before → after), screenshots of the five
   fixes, any pre-existing bug noticed but not fixed.
5. The handoff session reviews proportionately to risk
   (`docs/WORKTREES.md` § Review policy), merges, deploys from `main`,
   and updates the registry.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/flow-clarity
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store)
were copied from the `main` checkout at creation time; both are
per-worktree and gitignored.
