# Handoff — `feature/home-builder`

<!-- Seeded from docs/handoffs/_template.md by scripts/new-worktree.sh.
     Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/home-builder` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/home-builder` |
| Base | `main` @ `b6fda19` |
| Created | 2026-09-02 |
| Runserver port | 8002 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Give the app a friendly front door. Today the page at `/` is really an
*optimizer* — frontier curves, Sharpe ratios, fan charts — and there is
nowhere to just *build a portfolio*. This branch adds a new **Build** home
page where a user searches for assets, checks the ones they like, sees
their draft as a pie chart with plain-language info per asset, and then
carries that draft into the technical pages. The current page is renamed
**Optimize** and auto-loads the draft. RT's flow (2026-09-02): *Build
(pick assets, friendly) → Optimize (curves, fine-tune) → Forecast (card on
Optimize) → adopt → the existing transition report / account setpoint.*

## Scope

**In:**
- **New `DraftPortfolio` model** — the single thread through the app.
- **New Build page at `/`** (login lands there): asset search, draft list
  with weights, pie chart, plain-language per-asset info, account summary
  card, CTA to Optimize.
- **Rename the current index page to Optimize at `/optimize`**, nav
  `Build / Optimize / My account`, and make Optimize prefill from the
  draft.
- Draft sync: adopting a point on Optimize ("Make this my portfolio")
  also updates the draft.
- Django tests for every new endpoint and the redirects.

**Out** (do not do here — belongs on `main` or another bucket):
- Anything inside the **forecast card** on the Optimize page or the
  account forecast — `feature/forecast-anchors` owns that region *right
  now, in parallel* (see Conflict watchlist).
- A separate Forecast nav page (deliberately deferred; the card stays on
  Optimize this round).
- Asset fundamentals (P/E, sectors, news), watchlists, multiple drafts,
  the Learn page, any frontier/engine math change.
- Any change to `condor/` — this bucket is entirely `web/`.

## Acceptance

- [ ] Logged-in visit to `/` shows the new Build page; `/optimize` shows
  the old page under the heading "Optimize"; nav order is
  Build / Optimize / My account with correct active states.
- [ ] Search for a ticker (bundled `tickers.json` autocomplete), add it:
  it joins the draft with an equal slice carved proportionally from the
  others; pie redraws; weights editable as %; "Even out" equalises;
  remove works; server round-trip persists it all.
- [ ] Per-asset row shows name, last close, and a plain-words 1-year
  change ("up 12% over the past year"), plus an external "More about X →"
  link to `https://finance.yahoo.com/quote/<SYMBOL>` opening in a new tab.
  An asset with no data degrades gracefully ("no price history yet"),
  never a traceback.
- [ ] "Optimize this mix →" lands on `/optimize` with the draft's assets
  and weights prefilled, ready to Analyze.
- [ ] On Optimize, "Make this my portfolio" also updates the draft
  (verify: change it there, return to Build, pie matches).
- [ ] Account summary card: with an account, shows value at last close,
  TWR, and drift status, linking to My account (reuse the existing
  `/api/account` payload — no new account queries). Without one, a
  friendly one-liner inviting them to My account.
- [ ] Django tests: draft GET/PUT auth-scoping (401 anonymous, owner-only),
  weight normalisation server-side, asset-info endpoint (data and no-data
  cases), `/` and `/optimize` render for a logged-in user, login redirect
  still lands on `/`.
- [ ] `makemigrations --check` clean after the new migration; full suites
  not worse than baseline (expect ~202 passed + 2 skipped core, 41 Django).
- [ ] No new pip dependencies.

## Context & decisions already made — do not re-open

- **Nav naming and page split were decided by RT 2026-09-02:**
  Build (new, at `/`) / Optimize (old index, at `/optimize`) / My account.
  Forecast stays a card on Optimize this round.
- **Build and My account stay separate.** Build is *intent* (a draft);
  My account is *reality* (ledger, dollars, TWR). The bridge is the
  summary card, nothing more. Do not move account features onto Build.
- **Draft model:** `DraftPortfolio` in `web/explorer/models.py` —
  `owner OneToOneField(User)`, `payload JSONField` shaped
  `{"assets": [{"symbol": "MSFT", "weight": 0.25}, ...]}`,
  `updated_at auto_now`. One per user, created lazily. Server normalises
  weights to sum to 1 on save and rejects unknown/duplicate symbols with
  a 400 message. Endpoints: `GET/PUT /api/draft` (login-required, owner
  only — follow the `api_login_required` pattern in
  `web/explorer/views.py`).
- **Add-asset weighting rule:** a new asset gets `1/n` and existing
  weights scale by `(n-1)/n` — predictable, preserves proportions.
- **Asset info endpoint:** `GET /api/asset?symbol=X` returns display name
  (from `tickers.json`'s entry if present), last close and its date, and
  1-year simple return, computed from the cached `PriceStore` (see how
  `web/explorer/account.py` `_close_history` reads raw closes). Never
  trigger more than one store fetch per request; a store miss returns
  `{"ok": false, ...}` and the UI degrades.
- **Pie chart:** Plotly pie in a new `web/explorer/static/explorer/home.js`,
  using the existing `CHART_CONFIG` lockdown object and series colors from
  the CSS variables (see how `app.js` reads them via `cssVar`). Charts are
  interaction-locked app-wide — copy the pattern, don't invent config.
- **Copy register:** Build is the *friendly* page — no Sharpe, no
  dispersion jargon, no Greek. Where statistics do appear elsewhere,
  CLAUDE.md vocabulary applies (*expected return*, *dispersion*).
  Plain-words helpers ("up 12% over the past year") belong on Build.
- **Style:** reuse `style.css` tokens, cards, buttons, and the brand
  exactly — this page should look like it always belonged. New CSS goes
  in `style.css` under a clearly commented section.
- **Login redirect** stays `/` (`LOGIN_REDIRECT_URL`) — it now lands on
  Build. `redirect_authenticated_user` on the login view already handles
  the rest.
- **URL renames:** keep Django url *names* stable where practical
  (`index` may become `optimize`; update `{% url %}` references —
  grep templates). `/p/<uuid>` share pages are untouched.

## Conflict watchlist

**`feature/forecast-anchors` is in flight in parallel** and edits:
`condor/forecast.py`, `condor/model.py`, `web/explorer/views.py`
(api_forecast), `web/explorer/account.py` (account forecast),
`web/explorer/static/explorer/app.js` (forecast card region),
`account.js`, `web/explorer/templates/explorer/index.html` (forecast
card), `web/explorer/tests.py`.

Rules for you:
- Do not touch the forecast card markup/JS at all.
- Keep your `app.js` changes confined to init/prefill (reading the draft),
  your `views.py` changes to new endpoints + the index/optimize rename,
  and your `tests.py` additions in a clearly separated new test class.
- `base.html` (nav) will conflict trivially with anything — rebase onto
  `origin/main` before opening the PR: `git fetch origin && git rebase
  origin/main`, and re-run suites after.

## Status

- [ ] Baseline suite counts recorded
- [ ] `DraftPortfolio` model + migration + draft API + tests
- [ ] Asset info API + tests
- [ ] Build page (template, home.js, styles)
- [ ] Optimize rename + draft prefill + adopt-syncs-draft
- [ ] Account summary card
- [ ] Click-through on port 8002; screenshots in PR
- [ ] Rebase on origin/main; suites re-run
- [ ] PR opened against `main`

## Questions for the handoff session

- None yet. Park anything ambiguous here rather than guessing —
  especially any urge to expand scope (fundamentals, news, watchlists:
  already declined for this round).

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
3. This bucket is an **ordinary feature** (new table + login-scoped
   endpoints, no money math): no automated review needed. The handoff
   session will do a targeted read of the endpoint auth and the migration
   at merge time.
4. Push the branch and open a PR against `main`. PR body = the review
   packet: what changed and why, deviations from this brief, the test
   counts vs baseline, screenshots of Build and the renamed Optimize, the
   new user-facing copy quoted, and any pre-existing bug you noticed but
   did not fix.
5. The handoff session reviews proportionately to risk
   (`docs/WORKTREES.md` § Review policy), merges, deploys from `main`,
   and updates the registry.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/home-builder
source .venv/bin/activate
python web/manage.py runserver 8002
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
