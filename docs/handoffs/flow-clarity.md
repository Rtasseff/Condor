# Handoff — `feature/flow-clarity` (v2)

**Merged 2026-09-05.**

<!-- v2, rewritten 2026-09-04 after a second feedback round, before any
     implementation started. v1's five fixes are all still here (§fixes
     1–5); v2 adds the Explore/Real worlds and the account bridge. -->

| | |
|---|---|
| Branch | `feature/flow-clarity` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/flow-clarity` |
| Base | `main` @ `55d1715` — **rebase onto `origin/main` before starting** |
| Created | 2026-09-04 (v2 same day) |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Two rounds of live-user feedback (RT, 2026-09-04) point at one root
problem: **the app has two worlds — a pretend world (Build/Optimize:
drafts, exploration) and a real world (My account: a ledger of money and
shares) — and nothing explains the border.** Users pick assets, set a
portfolio, walk into My account and find an empty room: no holdings, so
no value, no drift, no forecast. Technically correct; humanly baffling.

This branch makes the worlds explicit, builds honest bridges between
them, and fixes the five smaller confusions from round 1 (silent default
portfolios on Optimize, no way to optimize off the real portfolio,
"forecast \$X" undiscoverable, deposit paths unclear, and labels —
"Robust", "model N of 3", and a priors control that even the owner
couldn't find twice). Everything is `web/`-side: **no engine changes, no
migrations, no new models.** Accuracy is untouchable — the ledger stays
the only source of reality; the app just guides people through it.

## Scope

**In:**
- Explore/Real world chips on every page (§worlds).
- Account starter card: one-click fund-from-plan (§bridge-1).
- Hypothetical account forecast when holdings are empty (§bridge-2).
- Optimize gating + Draft/Real source picker + adoption copy (§fixes 1–3).
- "Forecast \$X" entry on Build + account add-money chooser (§fix 4).
- Honest labels + the **Advanced priors disclosure** (§fix 5).
- Django tests for server-visible behavior; click-through for JS.

**Out** (do not do here):
- Any `condor/` change, migration, or new model. The bridge is client
  orchestration of **existing** endpoints only.
- Multiple accounts, multiple named drafts (saved portfolios already
  cover that), the Learn page, forecast math or anchor defaults.
- A global mode toggle — RT chose visible borders, not a mode switch.

## The worlds (decided by RT 2026-09-04: "visible borders")

- Build and Optimize get a small chip in the page header:
  **"Exploring — pretend money; nothing here touches your account."**
- My account gets the counterpart chip: **"Real — the record of what
  this account actually holds."** ("Real" here = the tracked account,
  which may itself be pretend money or a mirror of a brokerage — the
  existing framing; don't claim actual trades.)
- Style: one shared `.worldchip` component, two variants (explore =
  teal-tinted, real = amber-tinted), defined once in `style.css` with
  existing tokens. Quiet — a label, not a banner.
- The only two border crossings both announce themselves:
  "Make this my real portfolio →" (Optimize → account setpoint) and the
  starter card (§bridge-1). Their button copy says what crosses.

## Bridge 1 — the starter card (account empty, plan exists)

On My account, when the account has **no ledger events** but a setpoint
exists: a prominent card above the tiles —

> **Start your account.** Put in \$[input, default 10,000] and we'll
> record the deposit and the whole-share buys to match your plan at the
> last close. Pretend money or a mirror of a real deposit — your call;
> nothing real is traded. **[Start with \$10,000 →]**

Mechanics — chain the three **existing** endpoints client-side, in
order: POST `/api/account/events` (deposit) → GET `/api/account/plan`
→ POST `/api/account/plan/confirm`. Then refresh the page state; value,
drift and forecast all light up. Failures surface the API's message and
leave the ledger exactly as far as it got (deposit-only is a valid,
recoverable state — say so in the error copy: "money is in; the buys
didn't book — use the plan below").

If the account is empty AND no setpoint exists, the card instead guides:
"Pick a mix in **Build**, fine-tune it in **Optimize**, then *Make this
my real portfolio* — the plan lands back here." Links included. The
existing empty-state copy this replaces should fold into it.

## Bridge 2 — hypothetical forecast (account empty)

The account forecast card, when there are no holdings, must not error or
sit dead. It runs the forecast on the **setpoint weights** with a typed
starting amount, clearly labeled: chip/eyebrow **"Not yet real — your
plan with \$X"**, and a one-liner linking the starter card ("make it
real above"). Use the Build-page forecast API (`/api/forecast`) with the
setpoint's symbols/weights and cash share — same params the Optimize
card sends; no new endpoint. No setpoint → the card shows the same
guidance as the starter card's fallback. Once holdings exist, behavior
is exactly today's.

## Fix 1 — Optimize must not invent a portfolio

With no draft and no real holdings, `/optimize` shows a friendly
empty-state card — "Nothing to optimize yet. Pick your assets in
**Build** first →" — and no analyze form, chart, or default assets.
(Build keeps its starter quick-adds; that's where picking belongs.)
Django test asserts the empty-state marker and absent form.

## Fix 2 — optimize off draft OR real

When at least one source exists: **Optimizing: [Your draft] [Your real
portfolio]** above the asset list. "Real" appears only when the account
has holdings; weights come client-side from `/api/account`
`positions[].weight`. Switching sources loads assets+weights and
re-analyzes. Editing while on "real" forks the working copy into the
draft and flips the indicator ("Your draft — edited from your real
portfolio"); reality only changes through the ledger.

## Fix 3 — adoption speaks the user's language

"Use as account setpoint →" becomes **"Make this my real portfolio →"**
(title: "Copies this mix to your account and opens the plan — whole
shares at the last close — for turning what you hold now into this.").
Works from either source. The transition report heading echoes it:
"How to get there from what you hold."

## Fix 4 — "I just wanted to forecast X dollars"

- **Build:** a small card after "Your assets" — "**What could it
  become?** \$[input, default 10,000] in this mix over [2 years ▾] →
  **See the range**" → navigates to `/optimize?forecast=<amt>&years=<n>`;
  Optimize reads the params, auto-analyzes, projects with that amount
  and horizon, scrolls to the forecast card. Malformed params fall back
  silently to defaults.
- **My account:** the ledger card grows a one-line chooser header —
  "**Add money:** all at once → record a deposit below · over time →
  set a schedule" (anchor links) — and after the tiles a nudge:
  "Curious where it could go? **Forecast your account →**".

## Fix 5 — words that mislead, and the Advanced priors disclosure

- **Method dropdown (Optimize toolbar):** options become "Robust
  statistics (outlier-resistant)" / "Classic statistics (mean / SD)";
  gloss under the control: *"How we measure history — not a view about
  the economy."* Mirror in the "What am I looking at?" explainer.
  (*Robust* stays — project vocabulary; the gloss clarifies.)
- **Forecast model badge** (`app.js` ~722 + account twin): kill the
  "model N of 3" numbering — "steady rates (simplest)" / "resampled
  history (21-day blocks)". The phantom third model is what sent RT
  hunting twice.
- **Priors (decided by RT: Advanced toggle, not a third model):** the
  Model dropdown keeps its two entries. The anchor control moves inside
  a disclosure on both forecast cards:

  > **▸ Advanced — set your expectations (priors)**

  Open it and the control reads: label "**What to assume about
  returns**", options "My mix's own history" / "**Return to normal**
  ({{ market_anchor_pct }}%/yr)" / "My own number…", gloss: *"A belief
  about the future, blended with your data by how sure each is — never
  swapped in."* It applies to **both** models (the API already supports
  that). Discoverability guard so it can't vanish again: the summary
  row is always visible under the model picker, and when a non-default
  prior is active the collapsed summary shows it as a chip ("prior:
  return to normal, 8%") so the state is never hidden. API values
  (`historical`/`market`/`custom`) unchanged.

## Acceptance

- [ ] World chips on Build, Optimize, My account (both variants styled,
  light+dark obey the token system).
- [ ] Empty account + setpoint: starter card funds in one click —
  verified live: deposit + buys appear in the ledger, tiles/forecast
  light up. Partial-failure copy verified by forcing a plan error.
- [ ] Empty account, no setpoint: guidance card with working links.
- [ ] Empty account: forecast card runs the hypothetical, labeled "Not
  yet real"; with holdings it behaves exactly as today.
- [ ] Fresh user: `/optimize` empty state (Django test: marker present,
  form absent). With draft: today's behavior. With holdings: source
  picker works, real→edit forks to draft (verified live).
- [ ] "Make this my real portfolio →" from either source lands on the
  transition report.
- [ ] `/optimize?forecast=25000&years=5` analyzes, projects, scrolls
  (verified live).
- [ ] Account add-money chooser + forecast nudge anchors land right.
- [ ] No "of 3" in served JS/templates; Method + priors copy as
  specified; existing template tests updated (several assert current
  strings — e.g. the anchor-control test).
- [ ] Suites not worse than baseline (expect ~219+2 core — some data
  tests need network; 60 Django); `check` + `makemigrations --check`
  clean; **no new migrations**.

## Context & decisions already made — do not re-open

- RT decisions 2026-09-04: priors = **Advanced disclosure** (not a third
  model); account bridge = **starter card AND hypothetical forecast**;
  worlds = **visible borders, no mode toggle**.
- Draft is the single working copy (`DraftPortfolio`, `/api/draft`);
  adopting a point already syncs it. Saved portfolios = named drafts.
- The ledger is the only writer of reality; the starter card *uses* the
  ledger (deposit → plan → confirm), never bypasses it. Buys-require-
  cash stays enforced — that's why the deposit books first.
- Charts stay interaction-locked (`CHART_CONFIG`); forecast mechanics
  and anchor defaults unchanged — this branch only re-homes the words
  and the entry points.
- Vocabulary (CLAUDE.md): *expected return*, *dispersion*, *robust*.
- UI conventions research (`docs/research/ui-conventions.md`) governs:
  visible glosses over `title=`, honest empty states, one dismissible
  hint max per page.

## Conflict watchlist

Nothing else is in flight. All target files settled on `main`
(`optimize.html`, `home.html`, `account.html`, `app.js`, `home.js`,
`account.js`, `views.py`, `account.py` — read-only for the bridge —
`style.css`, `tests.py`). Rebase onto `origin/main` before starting
(registry commits landed after this branch was cut) and again before
the PR.

## Status

- [x] Rebased onto origin/main; baseline suite counts recorded
      (217 passed / 4 skipped core; 60 Django; check + makemigrations clean)
- [x] World chips (all three pages)
- [x] Bridge 1: starter card (fund-from-plan) — happy path + failure copy
- [x] Bridge 2: hypothetical account forecast
- [x] Fix 1: Optimize gating + tests
- [x] Fix 2: source picker + fork-to-draft
- [x] Fix 3: adoption copy
- [x] Fix 4: Build dollar-forecast deep link; account chooser + nudge
- [x] Fix 5: renames, glosses, Advanced priors disclosure; tests updated
- [x] Click-through on port 8001 (worlds, both bridges, all five fixes);
      screenshots in PR
- [x] Rebase again; suites re-run (217/4 core, 66 Django, no new migrations)
- [ ] PR opened against `main`

## Deviations from the brief (v2)

1. **`/api/forecast` gained an optional `cash_weight`.** §bridge-2 says to
   run the hypothetical on "the setpoint's symbols/weights **and cash
   share**" via `/api/forecast` with "the same params the Optimize card
   sends". That endpoint had no cash parameter — the Optimize card never
   needs one — so the cash share would have been silently dropped and a
   setpoint holding, say, 20% cash would have been projected as if fully
   invested. Added `cash_weight` (0–1) to the existing view, forwarding to
   the `cash_weight` / `risk_free_rate` options `Portfolio.forecast` has
   had since rung A. No new endpoint, no engine change, no migration. The
   rate is only forwarded when a sleeve exists, so the all-risky payload
   is byte-identical to before. Covered by
   `ForecastApiTests.test_cash_sleeve_reaches_the_model`.
2. **The account page now gets `rf_context()`.** The hypothetical's cash
   sleeve needs a rate; the account template had no risk-free number.
   Factored `rf_context()` out of `_render_optimize` and used it in both,
   surfaced as `<main data-rf>`.
3. **Cash clause in the forecast sentence is now conditional.** A fully
   invested mix was reading "0% of it is cash at the 0.0% T-bill rate".
   Dropped the clause when `cash_weight` is ~0. Affects the real account
   forecast too, where it was equally noisy.
4. **Optimize's `?years=` deep-link param is the forecast horizon,** not
   the lookback — as the acceptance line
   (`/optimize?forecast=25000&years=5`) specifies. Worth knowing that the
   page also has a *Lookback* control in years; the param does not touch
   it. Flagged rather than renamed, since the acceptance line is explicit.
5. **No light theme to verify.** §acceptance asks that both chip variants
   "light+dark obey the token system". `style.css` is dark-only
   (`color-scheme: dark`, a single `:root`). Read that as "derive from
   tokens, don't hardcode": both variants take their hue from a
   `--world-hue` custom property set to existing tokens (`--accent-hi`,
   `--series-you`), so a future light theme follows automatically.

## Found while testing — fixed here

- **The partial-failure message was invisible.** `render()` starts with
  `showError("")`, so the starter card's deposit-succeeded/buys-failed
  message was wiped by the very state refresh that followed it: the user
  saw money appear and no explanation. Now the refresh runs first and the
  message lands after it. Verified live by forcing `/api/account/plan` to
  503 — this is exactly the case §acceptance asked to force, and it was
  broken until that test.

## Code review (medium, as the return protocol asks)

Run against `main...HEAD` after the first commit; eight findings, all
real, all fixed and re-verified live in the second commit:

1. **Stale fan relabelled.** Projecting the hypothetical and then funding
   left the old "your plan" chart and sentence on screen under the new
   "whole account" badge. The fan is now dropped on any hypo↔real flip.
2. **Fork dropped assets.** `forkIfReal()` rebuilt the draft from
   `state.weights`, which is sparse: a just-added ticker has no entry, and
   "Equal weights" empties the map, so the PUT either omitted the new
   asset or wrote nothing while the indicator claimed a draft was saved.
   Rebuilds from `state.assets` now, absent weight = equal share.
3. **`runAccountForecast` dereferenced a null state.** If the first
   `/api/account` failed, Project threw a TypeError at the user instead of
   a message. Guarded.
4. **Cash-only accounts fell between the two bridges.** Deposit recorded,
   no buys: the hypothetical's "Make it real above →" pointed at a starter
   card that had already retired, and it projected the stock $10,000
   rather than the cash actually sitting there. Now links to `#holdings`
   ("Put your cash to work below →") and starts from the real balance.
   This is precisely the state a partial failure leaves behind.
5. **`prior: my own number, NaN%`** whenever the custom box was cleared
   to retype. Guarded on both cards.
6. **Client and server disagreed on "held".** `has_real` uses
   `shares > 0`; the client used `weight > 0`, so a position with no price
   (weight 0) had the server offering a source the client refused. Client
   now matches the server, and a failed load says so instead of silently
   showing the example deck.
7. **`GET /optimize` wrote to the database** — the holdings check called
   the get-or-create account helper. Read-only now.
8. **Build could navigate before its draft landed.** `fc-go` raced the
   fire-and-forget `PUT /api/draft`; with the new server-side gate, losing
   that race meant landing on "Nothing to optimize yet" holding a mix you
   had just built. Awaits the pending sync now — verified by adding an
   asset and clicking through in the same tick.

## Found while testing — NOT fixed (pre-existing)

- **`PUT /api/draft` races itself.** Adding assets on Build faster than a
  round-trip (three quick-add clicks in the same tick) fires overlapping
  whole-list PUTs; last writer wins, so the draft can end up holding only
  the first asset. Hit while driving the page from a script, not
  reachable at human speed. Untouched by this branch — it predates it and
  a fix (sequencing or a version token) is its own bucket.

## Questions for the handoff session

- Deviation 1 is the only one that touches a server contract. It is
  additive and defaulted off, but it is a param the brief did not
  authorise in so many words — worth a look during review.

## Return protocol

1. Keep this doc's **Status** current; note anything you deviated from.
2. Record your baseline **before starting**, re-run before pushing — do
   not make any count worse:
   ```bash
   source .venv/bin/activate
   python -m pytest tests/
   python web/manage.py test explorer
   python web/manage.py check
   python web/manage.py makemigrations --check --dry-run
   ```
3. This bucket chains ledger-writing endpoints from new UI (the starter
   card). That's existing, tested server code — but run **one**
   `/code-review` at *medium* on this branch before the PR anyway,
   scoped to the bridge orchestration and the fork-to-draft logic, and
   land the fixes here.
4. Push and open a PR against `main`. PR body = what changed and why,
   deviations, test counts vs baseline, **every renamed user-facing
   string quoted** (before → after), screenshots (worlds, both bridges,
   five fixes), any pre-existing bug noticed but not fixed.
5. The handoff session reviews proportionately (`docs/WORKTREES.md`
   § Review policy), merges, deploys from `main`, updates the registry.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/flow-clarity
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` and `.condor_cache/` were copied from `main` at
creation; per-worktree, gitignored. To test the empty-account states,
use a throwaway user (`python web/manage.py createsuperuser` variants or
the admin) rather than emptying RT's data.
