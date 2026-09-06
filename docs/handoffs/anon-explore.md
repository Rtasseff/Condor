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
- [x] Baseline suites recorded
- [x] Public routes + CSRF cookies; regression tests for what stays private
- [x] Draft storage adapter (localStorage anon / API authed)
- [x] Import on sign-in
- [x] Sign-in boundary copy/controls (4 sites + userbox)
- [x] django-ratelimit wired, Fly-Client-IP key fn, 429 JSON + JS copy
- [x] `/code-review` at medium run; fixes landed
- [x] Suites re-run; counts vs baseline recorded here

**2026-09-05 — complete. Implementation, review and fixes are committed locally; nothing pushed.**

### Test counts

| Suite | Baseline | Now |
|---|---|---|
| `pytest tests/` | 217 passed, 4 skipped | 217 passed, 4 skipped (untouched — no engine change) |
| `manage.py test explorer` | 93 | 122 |
| `check` | clean | clean |
| `makemigrations --check` | no changes | no changes |

The engine suite reports 217+4 here, not the brief's "219+2": two of the
four skips are the network tests, which this machine skips.

29 new Django tests: `AnonymousExploreTests` (public routes, share links,
an analyze+forecast round trip with no login, CSRF cookies, and the
explicit list of routes that still 401), `SignInBoundaryTests` (the four
copy sites + the userbox, and that a signed-in visitor sees exactly what
they saw before), `AnonymousDraftGateTests` (who decides "nothing to
optimize yet"), `DraftStorageAdapterTests` (both pages wired to the
adapter; neither talks to `/api/draft` behind it), `RateLimitTests`.

Seven existing tests asserted the old boundary and now assert the new one
— renamed where the name was the assertion:
`AuthTests.test_anonymous_page_redirects_to_login` →
`test_anonymous_can_explore`, `ForecastApiTests.test_requires_login` →
`test_is_public`, `AssetInfoApiTests.test_anonymous_gets_401` →
`test_anonymous_is_served`, `PageTests.test_optimize_anonymous_redirects_to_login`
→ `test_optimize_renders_for_anonymous_visitors`,
`LearnPageTests.test_every_other_page_still_requires_a_login` →
`test_my_portfolio_still_requires_a_login`, plus
`AuthTests.test_anonymous_api_gets_json_401` and
`LearnPageTests.test_base_template_survives_anonymous_users` updated in
place. No test was deleted.

### User-facing strings (before → after)

All four are **anonymous-only variants**; every signed-in string is
untouched, and a test asserts that.

| Where | Signed in (unchanged) | Anonymous |
|---|---|---|
| Optimize point card | "Make this my real portfolio →" | **"Sign in to make it real →"** → `/login?next=/optimize` |
| Optimize toolbar | "Save" / "Saved" buttons | **"Sign in to save & share this mix"** |
| Build, My-portfolio card | "You don't have a tracked portfolio yet — head to My portfolio…" + "Go to My portfolio →" | **"Have an account? Sign in — or just keep exploring."** |
| `base.html` userbox | username + "Log out" | **"Sign in"** (ghost link, `?next=` the current page) |

New strings: the rate-limit line **"Whoa — that's a lot of number
crunching. Give it a minute and try again."** (`throttle.TOO_MANY`), and
on a throttled sign-in **"Too many sign-in attempts from here. Give it a
minute, then try again."**

### Deviations and judgement calls

1. **The import runs on both Explore pages, not just Build.** As written,
   scope 3 ("on Build page load") and scope 4 (`/login?next=/optimize`)
   contradict each other: signing in from the point card lands you back
   on Optimize, where the server draft is still empty, so the server
   renders "Nothing to optimize yet" — the dead end the brief forbids.
   The import is therefore part of the adapter (`CondorDraft.get()`), and
   `signpost.js` runs it on the signed-in signpost page: if it populated
   the account's draft, the page reloads into the workbench. Verified in
   the browser end to end.
2. **`client_gated` (anonymous Optimize).** The server cannot see
   localStorage, so for anonymous visitors only, the page ships both the
   signpost and the workbench and an inline head script picks between
   them from `condor.draft.v1` before first paint — no flash, same
   promise fix 1 made. Signed-in rendering is byte-for-byte as it was
   (still server-decided, still no `app.js` on the signpost).
3. **The 429 copy lives server-side.** Both pages already render
   `data.error` from a failed fetch, so the friendly line is the `error`
   field of the JSON 429 rather than a second copy in JS.
4. **Rate limits apply to signed-in visitors too** (they are per IP, as
   the brief says). Simpler, and 15 analyses a minute is not a person.
5. **Rate limiting is off under `manage.py test`** (`RATELIMIT_ENABLE`),
   because one shared LocMem counter would leak between tests;
   `RateLimitTests` turns it back on with `override_settings`. That class
   also pins django-ratelimit's `_get_window`: a counting window that
   rolls over between two requests resets the count, which made the tests
   flaky roughly once a run before it was pinned.
6. **Ran `manage.py migrate` on this worktree's dev DB.** The copy taken
   at creation time was one migration behind (`0005_draftportfolio`), so
   the Build page 500'd on a real browser. Local, gitignored, no new
   migration files — `makemigrations --check` is still clean.

### Verified in the browser (dev server, port 8001)

Logged out: built SPY/GLD, survived a reload (localStorage), Optimize
prefilled from it and analyzed, a point click showed "Sign in to make it
real →", the forecast ran. Signing in from that link imported the mix
into the account, cleared the browser copy and landed on the workbench.
With a non-empty account draft, a stale browser copy was discarded and
the account's draft left untouched. The signpost renders clean for an
anonymous visitor with nothing stored (no console errors; `app.js` bails
rather than analyzing behind it). Over the limit, the page shows the
"Whoa —" line in its error card.

### `/code-review` at medium — all seven findings landed

No high-severity correctness bug. Every finding was real; all seven are
fixed in the follow-up commit, and the two that a test can see got one.

1. **`/api/asset` failures lied.** One lookup per asset per Build load
   against a 60/min cap: a big mix reloaded a few times in a minute
   trips it, and `fetchInfo`'s bare `catch` turned that into "No price
   history yet." on every row — a false statement about the assets. The
   error now carries its status and a 429 says what actually happened.
   **For RT:** 60/min is the brief's number and I kept it, but it is the
   limit an honest visitor is most likely to meet (15 assets = 15 calls
   per load). Worth revisiting if anyone reports blank rows.
2. **The head-script gate was laxer than the adapter.** It only checked
   `assets.length`, while `draft.js` also requires a ticker-shaped symbol
   and a non-zero weight. A malformed stored draft therefore painted the
   workbench, the prefill then failed, and `init()` fell through to
   analyzing the built-in example deck — exactly what fix 1 forbids.
   `init()` now flips the page back to the signpost when nothing
   survived validation. Verified in the browser with a hand-corrupted
   `condor.draft.v1`.
3. **Anonymous storage failures were swallowed on Optimize.** `app.js`'s
   `syncDraft` caught everything as "best effort" — true when the account
   API is the draft's home, false when this browser is. Private browsing
   or full storage now shows the message; the signed-in path is unchanged.
4. **LocMem culls at 300 entries**, evicting live rate-limit counters
   under load. `MAX_ENTRIES` is now 10000.
5. **The limiter counted requests that never reached the view.** A GET to
   `/api/analyze` earns a 405 and does no work, but was spending the
   caller's quota. The compute limiters now name their method.
6. **Dead share row.** `#sharerow` sits inside the save panel, which only
   opens from the Save button — absent for anonymous visitors — so
   revealing it on `/p/<uuid>` did nothing. Guarded.
7. **Signing in dropped the query string.** `request.path` lost
   `?forecast=…&years=…`, so someone signing in from Build's deep link
   came back to a bare `/optimize`. All three sign-in links now use
   `request.get_full_path`.

### Noticed, not fixed (pre-existing)

`style.css` styles buttons as `button.primary` / `button.ghost`, so the
existing links that borrow those classes — "Optimize this mix →"
(`.ctacard a.primary`) and "Pick your assets in Explore →"
(`.emptystate a.primary`) — render as default-coloured links, not
buttons. Predates this branch; I styled only the links I added
(`.userbox a.ghost`, `#settargetsignin`) and left those two alone rather
than change the look of pages this bucket is not about.

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
