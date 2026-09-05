# Handoff — `feature/explore-first`

**Merged 2026-09-05** (`e6089f0`); branch and worktree removed.

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/explore-first.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/explore-first` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/explore-first` |
| Base | `main` @ `ea26e41` |
| Created | 2026-09-05 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

User testing after flow-clarity says the app is *better but still
confusing*: people land, see a lot of information, and don't know what
to do. RT's direction (2026-09-05, verbatim intent): **exploring is the
primary thing** — most visitors are here to play. Everything except the
account page should read as one Explore journey (pick assets → optimize
→ forecast), you can start it from scratch *or* from your current
portfolio, and "make this my portfolio" (with the trade report) is the
clear, celebrated exit. The account page should be called **My
portfolio**, not "My account". And since we already hold daily closes
for every asset, browsing an asset should *show* its recent performance
— a sparkline per asset, a bigger chart on demand — instead of only
linking out to Yahoo.

This bucket delivers that: a two-world IA (Explore | My portfolio), a
visible journey stepper, decluttered pages with one primary action each,
and in-app price history.

## Scope

**In:**

1. **Nav: two worlds.** `base.html` nav becomes
   **Explore | My portfolio** (plus Log out). "Build" and "Optimize"
   stop being top-level tabs; both `/` and `/optimize` light the
   Explore tab. Keep the URLs `/`, `/optimize`, `/account` exactly as
   they are (bookmarks, tests, deep links like
   `/optimize?forecast=…` must keep working) — this is a *labeling and
   framing* change, not a routing change. `/account` page `<h1>` and
   `<title>` become "My portfolio". The `contribution_due` dot moves
   with the tab.

2. **Journey stepper.** Both Explore pages get a compact stepper under
   the page head: **1 Pick your assets → 2 Optimize → 3 Forecast**,
   with a visually distinct end-cap **→ Make it my portfolio** (a
   destination, not a numbered step). Rules from the research digest
   below apply: linear presentation, every completed/current step is a
   revisitable link (step 1 → `/`, steps 2–3 → `/optimize`, forecast
   anchors to the forecast card), current step highlighted. On the
   account page there is **no stepper** — that world is calm and real.

3. **Explore start states** (`/`, `home.html` + `home.js`):
   - Empty draft, no real holdings: today's search card is the hero;
     make the single primary action unmistakable (big search + starter
     chips, everything else quiet).
   - Empty draft, **has** real holdings: show a start chooser —
     **"Load my portfolio"** (forks real holdings into the draft, same
     mechanics as Optimize's source picker) vs **"Start fresh"**. This
     is the piece users couldn't find: exploring *from* your own
     portfolio must be one obvious click on the landing page.
   - Non-empty draft: current layout, decluttered per (5).
   - The Build page's "Your account" summary card is renamed "My
     portfolio" and stays small/secondary (link, value, return).

4. **Asset performance in-app** (the fun part):
   - Extend `GET /api/asset` (`views.api_asset`) with a `series` field:
     ~60 evenly-downsampled points of the ~1y of closes it *already
     fetches and discards* — `{"dates": [...], "closes": [...]}`,
     always including the first and last real point. No extra
     PriceStore fetch; same `{"ok": false}` degradation. Also add
     `month_return` (last close vs ≈30 days prior) computed from the
     same series.
   - Each asset row in the Build mix list gets an **inline SVG
     sparkline** (hand-built path, NOT Plotly — there can be many
     rows): ~90×28px, stroke tinted by sign of 1y return via CSS
     tokens (both themes), faint dotted baseline at the year-ago
     price, no axes/labels (research: sparklines are word-like
     graphics; the number next to it — the 1y % — carries the scale).
     Draw-in animation ≤400ms, disabled under `prefers-reduced-motion`.
   - Clicking an asset row expands an inline **detail panel** (not a
     modal): bigger chart — Plotly is already bundled, reuse it with
     `CHART_CONFIG` lockdown — with a 1M / 1Y range toggle, last
     close + date, 1y and 1M returns in words ("Up 12% over the last
     year"), and the existing Yahoo link. One panel open at a time.
   - Optimize's asset list may reuse the sparkline row if it drops in
     cleanly; if it fights the weight-editing UI, skip it there and
     note the decision in Status.

5. **Declutter pass — one primary action per screen** (research rules
   below):
   - Build: card order = search → mix (pie + list) → "Optimize this
     mix →" CTA → forecast CTA → My-portfolio summary. Exactly one
     `.primary` button visible per state.
   - Optimize: the controls row (method / years / risk-free) collapses
     behind a **"Settings"** disclosure (closed by default —
     auto-analyze already runs on load; the defaults are fine for
     everyone this page is for). Save/Saved become quiet ghost
     controls. The visible spine of the page: chart → click a point →
     point card → **"Make this my portfolio"**.
   - Adoption must end with the payoff RT keeps asking for: after
     "Make this my portfolio", the whole-share **trade report** ("buy
     2 shares of X, sell 1 of Y") is shown immediately and
     unmissably, with a link to My portfolio. If that's already the
     behavior, verify and polish the copy; if the report only lives on
     the account page today, surface it (or a faithful summary of it)
     at the moment of adoption.
   - Copy pass: no user-facing "account" where "portfolio" is meant;
     world chips stay ("Exploring" teal on both Explore pages; the
     real-world chip on `/account` reads **"My portfolio"**, amber).
     Build's sub-line stops apologizing ("No jargon here…") and states
     the journey: pick a few assets, then optimize and forecast them.

**Out** (do not do here — belongs on `main` or another bucket):

- Any engine (`condor/`) change; any model/migration; any ledger or
  auth change. The draft-PUT race in BACKLOG stays parked.
- Route renames or new pages (no `/explore` URL; no onboarding tour
  widget; no glossary page).
- Intraday or auto-refreshing prices — daily closes only, from the
  existing PriceStore.
- Real-portfolio sparklines on the account page (keep that world calm
  this round; revisit after feedback).

## Acceptance

- Nav shows exactly **Explore | My portfolio**; both `/` and
  `/optimize` mark Explore active; `/account` titled "My portfolio".
  All existing URLs and the `/optimize?forecast=…&years=…` deep link
  unchanged.
- Stepper renders on both Explore pages with correct current-step
  highlighting and working links; absent on `/account`.
- A user with real holdings and an empty draft sees "Load my
  portfolio" on the landing page and one click forks it into the
  draft.
- `GET /api/asset?symbol=VTI` returns `series` (≤ ~62 points, first
  and last are real endpoints) and `month_return`; an unknown/new
  ticker still degrades to `{"ok": false}` with no traceback.
- Sparklines render for every mix row with data; assets without data
  show the row without a sparkline (no broken glyph). Reduced motion
  honored.
- Asset detail panel opens/closes, range toggle works, chart renders
  offline from `series` (no external fetches beyond our API).
- Django tests added: api_asset series shape + degradation;
  nav/titles renames; stepper present on `/` and `/optimize`, absent
  on `/account`; start-chooser appears for a holdings-owning user with
  empty draft. Baselines to not regress: **217 passed + 4 skipped**
  core (`python -m pytest tests/`), **66** Django
  (`python web/manage.py test explorer`), `check` clean,
  `makemigrations --check --dry-run` clean (this bucket must add NO
  migration).
- Both themes: sparkline colors, stepper, and chips legible in light
  and dark (tokens only, no hardcoded colors).

## Context & decisions already made

- RT decided (do not re-open): Explore is primary; account tab is
  called **My portfolio**; explore starts from scratch *or* from the
  real portfolio; adoption with trade report is the journey's end and
  must be very clear; in-app price history at daily-close resolution;
  worlds stay visually distinct (visible-border worlds from
  flow-clarity — build on the existing `.worldchip` / `--world-hue`
  tokens, don't invent a parallel system).
- Prior rounds (see `docs/handoffs/flow-clarity.md`,
  `docs/handoffs/home-builder.md`): draft model + `/api/draft`,
  source picker with fork-to-draft, server-side gating flags,
  Advanced priors disclosure. Reuse these mechanics; this bucket
  re-frames, it does not rebuild.
- `views.api_asset` (views.py ~line 456) already pulls ≥1y of closes
  per symbol — the series extension must NOT add a second fetch.
- Design rules from UX research (2026-09-05; NN/g progressive-
  disclosure/wizards/modes/empty-states, Tufte sparkline theory, Stripe
  sandbox docs, Wealthfront/M1 patterns) — follow these:
  1. Progressive disclosure: show only what most users need most of
     the time; split by task frequency, not by what's easy to hide;
     label the disclosure so users can predict what's behind it; cap
     at two levels. Defaults must be good enough that opening
     Settings is optional.
  2. Wizard fit: this exact audience (infrequent task, no domain
     expertise) is what steppers are for — show the whole journey up
     front, highlight the current step, always allow going back with
     data preserved. BUT never split content users must compare
     across steps: assets, weights, and the frontier stay visible
     together on Optimize; the stepper frames pages, it doesn't
     fragment them.
  3. One primary action per screen state; secondary actions styled
     quieter. If two things pulse for attention, demote one.
  4. Explore-vs-real is a mode problem: one small badge is not
     enough — use at least two redundant, persistent indicators
     (chip + tinted world border/chrome, already tokenized as
     `--world-hue`), name the modes distinctly, and make leaving
     Explore an explicit act. Gate "Make this my portfolio" with a
     confirmation that restates consequences — mode slips here mean
     "I thought I was playing."
  5. Sparklines: word-sized and undecorated — no axes, gridlines,
     frames, or boxes; downsampled shape, not a data export; color
     the line by sign of change against a faint dotted baseline; the
     printed number beside it carries the precision (Robinhood/Yahoo
     convention novices already know).
  6. Empty states are the front door: state plainly what this place
     is for, teach one thing in context, offer one direct CTA plus a
     worked example (our starter chips are the M1-style prebuilt
     template pattern — keep them prominent).
  7. Commitment is a distinct, celebrated final step, separate from
     exploration (Wealthfront/M1) — the adoption moment ends with
     the trade report as the payoff.

## Conflict watchlist

- None — no other worktree is active and `main` is quiet. `home.js`,
  `app.js`, `style.css`, `home.html`, `optimize.html`, `base.html`,
  `views.py`, `tests.py` are all yours this round.

## Status

<!-- Branch agent keeps this current. Checklist + short dated notes. -->
- [x] Baseline suites recorded (2026-09-05): `python -m pytest tests/` →
  217 passed, 4 skipped. `python web/manage.py test explorer` → 66 passed.
  `check` clean. `makemigrations --check --dry-run` → no changes.
- [x] Nav + titles (Explore | My portfolio). Nav blocks renamed
  `nav_build`/`nav_optimize`/`nav_account` → `nav_explore`/`nav_portfolio`;
  `/` and `/optimize` both set `nav_explore`, `/account` sets
  `nav_portfolio`. Renames (before → after): nav "Build"/"Optimize" tabs →
  single "Explore" tab; nav "My account" → "My portfolio"; `/` `<title>`
  "Condor Funds — Build" → "Condor Funds — Explore"; `/` `<h1>`Build→Explore;
  `/account` `<title>` "Condor Funds — My account" → "Condor Funds — My
  portfolio"; `/account` `<h1>` "My account" → "My portfolio"; `/account`
  worldchip "Real" → "My portfolio" (kept `.real`/amber class + `--world-hue`
  token, just the label). URLs unchanged as required.
- [x] Stepper on both Explore pages (`_stepper.html` partial, included on
  `/` and `/optimize`, including Optimize's empty state). 1 Pick your
  assets → `/`, 2 Optimize → `/optimize`, 3 Forecast → `/optimize#forecastcard`,
  end-cap "Make it my portfolio" → `/optimize#pointcard` (visually distinct,
  not numbered). Current step highlighted (`aria-current="step"` + `.current`).
  Absent on `/account`.
- [x] Start chooser: empty draft + real holdings → "Start from…" card
  ("Load my portfolio →" primary / "Start fresh" ghost), search card
  hidden while it's showing. `index` view now passes `has_real`
  (read-only, same `_has_holdings` check `/optimize` uses) via
  `json_script`. "Load my portfolio" forks real positions into the draft
  (same weight-fraction mechanics as Optimize's source picker) and syncs
  `/api/draft`. Manually verified in-browser (see below).
- [x] `api_asset` `series` (~60 evenly-downsampled points, first/last
  always real endpoints, no second PriceStore fetch) + `month_return`
  (same trailing-return helper as `year_return`) + tests
  (`AssetInfoApiTests`: happy-path shape + short-history/no-downsample
  case; degrade path unchanged).
- [x] Sparklines (inline SVG, ~90×28, tinted by 1y-return sign via new
  `--change-up`/`--change-down` tokens, dotted baseline at the year-ago
  price recovered from `year_return` — no extra payload field, draw-in
  animation ≤400ms via `pathLength`, `prefers-reduced-motion` respected)
  + inline detail panel (click a Build row → bigger Plotly chart, 1M/1Y
  toggle reslicing the same `series` — no second fetch — last close+date,
  1y/1M returns in words, Yahoo link; one panel open at a time). Verified
  in-browser: sparkline renders, panel opens/closes, 1M toggle re-renders.
  **Deviation**: did *not* add sparklines to Optimize's sidebar asset
  list — it's a narrow 300px column doing weight-editing already: a
  90px sparkline plus name/weight/remove doesn't fit without either
  truncating the name to nothing or wrapping awkwardly, and the brief
  explicitly sanctioned skipping it here if it fights that UI.
- [x] Declutter: Build card order is now search → mix → "Optimize this
  mix →" CTA → forecast CTA → My-portfolio summary (link/value/return
  only, Setpoint tile dropped). Add-asset button swaps `.primary`↔`.ghost`
  by draft emptiness so exactly one `.primary` shows per state; forecast
  CTA (`#fc-go`) demoted to ghost so it doesn't compete with the Optimize
  CTA. Optimize: method/lookback/risk-free now behind a closed-by-default
  `<details class="advanced">` "Settings" disclosure (reuses the existing
  Advanced-priors disclosure styling); Save/Saved moved out to their own
  quiet ghost row, always visible. Copy pass done — see the "account" →
  "portfolio"/"real portfolio" renames throughout home/optimize/account
  templates and JS (kept "account"/"ledger" as-is only where account.html
  is describing the ledger mechanism to itself, e.g. "a ledger-tracked
  account", "whole account").
- [x] Adoption → trade report: gated "Make this my real portfolio →"
  behind an inline confirmation (`#settargetconfirm`, no `window.confirm`)
  restating the consequence before the real POST — design-rules item 4.
  On `/account?plan=1` the plan panel now `scrollIntoView`s and gets a
  2.4s amber highlight (`.justadopted`, reduced-motion-safe) so the
  whole-share trade report is unmissable, not just present. Manually
  verified end-to-end in-browser: Optimize → confirm → real target set →
  landed on My portfolio scrolled straight to "buy 13 shares of SPY"
  under "How to get there from what you hold".
- [x] `/code-review` at medium run; fixes landed. 3 findings, all
  confirmed and fixed:
  1. Detail-panel range toggle was mislabeled/misleading: `series` spans
     up to ~400 days, so "1Y" silently showed ~13 months, and a naive
     uniform downsample gave "1M" only ~5 points (evenly spaced over the
     full 400 days). Fixed both sides: `views._downsample()` now biases
     density toward the most recent 35 days (`SERIES_RECENT_DAYS`) so a
     client-side "last month" slice stays near-daily (verified: 26 of the
     last 35 days present, was ~5), and `home.js`'s `detailSeries()` now
     clips "1Y" to 365 days too, not just "1M" (verified: 1Y → exactly
     365 days / 57 points, 1M → 31 days / 23 points). New test
     `test_downsample_keeps_recent_history_dense`.
  2. `#settargetconfirm` (the real-portfolio confirmation gate) mixed the
     Explore teal (border) with the Real amber (background) — the one
     control whose whole job is marking that boundary. Now amber
     throughout (`var(--series-you)`), matching `.worldchip.real` /
     `.justadopted`. Verified via computed style.
  3. `/account?plan=1`'s scroll+glow fired even when `loadPlan()` failed
     and left `#planpanel` hidden (dead animation after an error the user
     already saw). Now gated on `!$("planpanel").hidden`.
  All three re-verified in-browser after the fix (see below).
- [x] Suites re-run post-fixes: `python -m pytest tests/` → 217 passed, 4
  skipped (unchanged). `python web/manage.py test explorer` → **78
  passed** (baseline 66 + 12 new: 2 `AssetInfoApiTests` for
  short-history/dense-tail downsampling, 10 `ExploreFirstNavTests` for
  nav/stepper/chooser). `check` clean. `makemigrations --check --dry-run`
  → no changes — confirmed no migration was added.

Manual browser verification (2026-09-05, this session): logged in as a
throwaway local user, drove the running dev server (port 8001) via
Chrome automation. Found and fixed one **pre-existing** issue unrelated
to this bucket's code: the worktree's copied `web/db.sqlite3` was missing
migration `0005_draftportfolio` (`python web/manage.py migrate` fixed it
locally; not a code change, nothing to commit). Confirmed: nav labels,
stepper + current-step highlighting, empty/chooser/populated Build
states, sparklines + detail panel + 1M/1Y toggle, Optimize Settings
disclosure collapsed by default, adoption confirmation gate, and the
full "Make this my real portfolio" → confirm → My portfolio trade-report
flow (real whole-share buy computed correctly). No console errors, no
server tracebacks during any of this.

## Questions for the handoff session

<!-- Anything needing the human or main. Don't guess — park it here and continue with what doesn't depend on it. -->
-

## Return protocol

1. Keep this doc's **Status** current; note anything you deviated from.
2. Record your baseline **before starting**, then re-run before
   finishing — do not make any count worse:
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
3. **This brief orders a `/code-review` at medium** — a wide UI
   restructure plus an API change is exactly where self-review pays
   (flow-clarity's caught 8 real bugs). Run it on this branch as your
   final work item, land the fixes, summarize findings in Status.
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
cd /Users/rtasseff/projects/condor-dev/explore-first
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
