# Handoff — `feature/anon-explore`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/anon-explore.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/anon-explore` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/anon-explore` |
| Base | `main` @ `7669651` |
| Created | 2026-09-05 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Let strangers use the whole Explore journey — Build, Optimize,
Forecast — **without an account**. RT decided (2026-09-05): the funnel
is Learn (already public) → play on Explore → the moment they want
"Make this my portfolio", *that's* where we ask them to sign in. Open
registration is a separate, later bucket (needs email infra + policy);
this bucket is try-before-account plus the protection that makes it
safe on a $12/mo single machine: per-IP rate limiting on the compute
endpoints.

Identity boundaries stay exactly where they are: anything that reads
or writes a *user's* data (draft API, saved portfolios, everything
under My portfolio) still requires login. Anonymous visitors get a
draft that lives in their browser.

## Scope

**In:**

1. **Public routes.** Remove `@login_required` from `index`,
   `optimize`, and `shared_portfolio` (`/p/<uuid>` — share links are
   *meant* to be sent to people without accounts; that's the viral
   loop, and the UUID is the capability). Remove `@api_login_required`
   from `api_analyze`, `api_forecast`, `api_asset` only — they compute
   from public price data and carry no user state. **Everything else
   keeps its decorator**: `api_draft`, `api_portfolios*`, `/account`,
   every `/api/account*` route. Regression-test each of those still
   401s / redirects anonymously. Make sure every now-public page still
   gets `@ensure_csrf_cookie` so anonymous fetch() POSTs to
   analyze/forecast carry a token.

2. **Anonymous draft = localStorage.** A small storage adapter shared
   by `home.js` and `app.js`: authenticated → `/api/draft` exactly as
   today (do not change the authenticated path); anonymous →
   `localStorage` key `condor.draft.v1`, holding the *same JSON
   payload shape* the API round-trips (so the import below is a
   straight PUT). Templates expose `user.is_authenticated` to JS via
   `json_script` (both pages). Everything on Explore that reads or
   writes the draft goes through the adapter — including Optimize's
   draft prefill and the draft-source picker.

3. **Import on sign-in.** On Build page load, when authenticated and
   `condor.draft.v1` exists: if the server draft is empty, PUT the
   local one and clear the key; if the server draft is non-empty,
   discard the local key (the account's draft wins — no merge UI).
   One-shot and silent; a person who played anonymously then signs in
   finds their mix waiting.

4. **Sign-in boundaries (copy + controls).** Anonymous versions of
   the identity moments — visible, aspirational, never a dead end:
   - Optimize point card: "Make this my real portfolio →" becomes
     **"Sign in to make it real →"** linking `/login?next=/optimize`.
     The confirm flow for authenticated users is untouched.
   - Save/Saved buttons: hidden when anonymous; in their place a quiet
     "Sign in to save & share this mix".
   - Build's My-portfolio summary card: for anonymous, a quiet card —
     "Have an account? **Sign in** — or just keep exploring."
   - `base.html`: the `{% if user.is_authenticated %}` userbox gains
     an `{% else %}` with a ghost **Sign in** link to `/login`.
   - Any account/starter bridge cards on Explore pages: hidden when
     anonymous.
   Nav links to My portfolio keep working for anonymous users — they
   just redirect to login, which is correct.

5. **Rate limiting** (the protective half — do this properly):
   - Add `django-ratelimit` to `requirements.txt`; configure an
     explicit LocMem `CACHES` in settings.
   - **Key by real client IP.** We run behind Fly's proxy: everyone's
     `REMOTE_ADDR` is the proxy. Write one key function that returns
     the `Fly-Client-IP` header when present, else `REMOTE_ADDR`
     (dev). Do NOT trust a client-suppliable `X-Forwarded-For` chain
     beyond what Fly itself sets. Without this, one visitor's burst
     throttles the whole site — treat it as the bucket's critical
     correctness detail.
   - Limits (per IP): `api_analyze` and `api_forecast` **15/min**
     each; `api_asset` **60/min**; the login POST **10/min** (wrap
     the LoginView dispatch or use the decorator on a small subclass).
     Rate-limited compute endpoints return JSON 429; the JS shows a
     friendly line: "Whoa — that's a lot of number crunching. Give it
     a minute and try again."
   - Known softness, note it in code: LocMem counters are per-gunicorn
     worker (Dockerfile runs 2), so effective limits are ≈2× nominal.
     Acceptable for v1 abuse protection; a shared cache is a later
     upgrade, not this bucket.

**Out** (do not do here):

- Open registration, email/verification, invite codes, CAPTCHA,
  Litestream/backup changes, robots.txt/SEO, engine (`condor/`)
  changes, migrations (this bucket must not add one), Dockerfile/
  fly.toml changes (worker count stays 2).

## Acceptance

- Anonymous: `/`, `/optimize`, `/p/<uuid>` → 200; a full
  analyze + forecast round-trip works through the Django test client
  with no login; `/api/draft` → 401; `/account`, `/api/account`,
  `/api/portfolios` still redirect/401 (explicit regression tests).
- Authenticated: everything behaves byte-for-byte as today — draft
  via API, adoption confirm flow, save/share. No authenticated-path
  regressions.
- Import: authenticated + local key + empty server draft → server
  draft populated, key cleared; non-empty server draft → key cleared,
  server draft untouched (test the server-visible parts; browser-
  verify the rest).
- Rate limit: with test-overridden low limits, the Nth request 429s
  and carries JSON; the key function prefers `Fly-Client-IP`; login
  POST is limited.
- In-browser (dev server, logged out): build a mix, see it survive a
  reload (localStorage), Optimize prefills from it, forecast runs,
  point card shows "Sign in to make it real →"; then sign in and see
  the mix imported.
- Suites not below baseline (219+2 core with network / 93 Django);
  `check` clean; `makemigrations --check --dry-run` clean.

## Context & decisions already made

- RT (2026-09-05): anonymous Explore now; open registration later,
  separately. Share links public by design. Don't re-open.
- The world model stays: Explore chip already says pretend money;
  anonymity changes nothing about the two-worlds framing.
- explore-first + flow-clarity mechanics (draft model, source picker,
  gating flags, adoption confirm) are the substrate — reframe entry
  points, do not rebuild them. `views.learn` (public, static) is the
  pattern for how a public view should look.
- Prices: PriceStore caches on the volume; anonymous load mostly hits
  warm tickers. The rate limits above are the guard for cold-fetch
  abuse (Tiingo quota) and CPU (bootstrap forecast).

## Conflict watchlist

- None active; `views.py`, `urls.py`, `home.js`, `app.js`,
  templates, `tests.py`, `requirements.txt`, `settings.py` are yours.

## Status

<!-- Branch agent keeps this current. Checklist + short dated notes. -->
- [ ] Baseline suites recorded
- [ ] Public routes + CSRF cookies; regression tests for what stays private
- [ ] Draft storage adapter (localStorage anon / API authed)
- [ ] Import on sign-in
- [ ] Sign-in boundary copy/controls (4 sites + userbox)
- [ ] django-ratelimit wired, Fly-Client-IP key fn, 429 JSON + JS copy
- [ ] `/code-review` at medium run; fixes landed
- [ ] Suites re-run; counts vs baseline recorded here

## Questions for the handoff session

<!-- Anything needing the human or main. Don't guess — park it here and continue with what doesn't depend on it. -->
-

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
3. **This brief orders a `/code-review` at medium** — it moves auth
   boundaries, which is squarely the high-risk category. Run it on this
   branch as your final work item, land the fixes, summarise in Status.
   (Template text for reference: it will say so explicitly when
   the bucket touches engine numerics, auth/permissions, ledger
   migrations, or deploy config): run it at *medium* on this branch and
   land the fixes as your final commit, summarised in Status.
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
cd /Users/rtasseff/projects/condor-dev/anon-explore
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
