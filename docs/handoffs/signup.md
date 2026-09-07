# Handoff — `feature/signup`

**Merged 2026-09-07**; branch and worktree removed.

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/signup.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/signup` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/signup` |
| Base | `main` @ `6948324` |
| Created | 2026-09-07 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Self-serve accounts: a stranger who has been exploring can **sign up
with a username, email, and password**, click a verification link in
their email, and land back in the app with the mix they built as an
anonymous visitor waiting in their account. Plus the other half of
getting RT out of the loop: **self-serve password reset**. RT decided
(2026-09-07): email verification is enough (no CAPTCHA, no admin
approval), volume will be small, and the sender is **RT's Gmail via an
app password** — which to this codebase is nothing but SMTP settings
read from the environment.

Use Django's own auth machinery throughout — `UserCreationForm`,
`default_token_generator` + uidb64 activation links, the built-in
`PasswordReset*` views. No third-party registration package; the
established package here is Django itself.

## Scope

**In:**

1. **Email config** (`settings.py`, env-driven, no secrets in git):
   - `CONDOR_EMAIL_USER` + `CONDOR_EMAIL_PASSWORD` present → SMTP
     backend, `smtp.gmail.com:587`, TLS, `EMAIL_TIMEOUT = 10` (a hung
     SMTP conversation must not hang a request worker).
   - Absent (dev, tests) → console backend.
   - `DEFAULT_FROM_EMAIL = "Condor Funds <{CONDOR_EMAIL_USER}>"`.
   - `SIGNUPS_ENABLED = bool(email configured) or DEBUG`. In
     production with no SMTP configured, `/signup` renders a clear
     "signups are temporarily closed" page rather than minting
     accounts whose activation links go to a log file. Templates get
     the flag; the login page only advertises signup when it's true.
   - Set `PASSWORD_RESET_TIMEOUT = 3 * 24 * 3600` explicitly (governs
     both reset and activation links; say so in a comment).

2. **Signup flow**:
   - `GET/POST /signup` — public. Form: username, email (required,
     unique **case-insensitively** against existing users — Django
     doesn't enforce this, you do, at the form), password twice
     (Django's validators), a required consent checkbox — label:
     "This is an educational prototype: pretend money, real market
     data, not investment advice." — and a **honeypot**: a hidden
     `website` text input; if it comes back non-empty, return the
     normal "check your email" page and create nothing.
   - Success: create the user `is_active=False`, email an activation
     link `/activate/<uidb64>/<token>` (`default_token_generator`),
     show "Check your email" with the address echoed back. The email
     is plain text: one line of what it is, the link, one line of
     who to ignore it as.
   - **Send failure → nothing created.** Wrap create+send in a
     transaction; on `SMTPException`/timeout, roll back and render an
     honest "couldn't send the email, nothing was created, try again
     in a minute" error. No half-registered users.
   - `GET /activate/<uidb64>/<token>` — valid: `is_active=True`,
     `login(request, user)`, redirect to `/` with a one-time "You're
     in — pretend money, go play." message (the anon-draft import
     from anon-explore then fires on its own; test that chain).
     Invalid/expired: a page that says so and links `/signup`.
   - **"Email never arrived" without a resend endpoint**: a signup
     POST whose username belongs to an existing **inactive** user
     with the **same email** (case-insensitive) updates that user's
     password to the newly typed one and resends the link. Same
     username with a different email, or any clash with an **active**
     user → normal form errors ("already registered — sign in or
     reset your password").
   - Rate limit: add `"signup": "5/h"` to `CONDOR_RATE_LIMITS`, POST
     only, via the existing `explorer.throttle` machinery. The 429
     re-renders the form with the friendly line (follow
     `ThrottledLoginView`'s pattern).

3. **Password reset** — Django's four built-in views wired under
   `/password-reset/…` with our templates (the four pages plus the
   email subject/body templates; plain text, same voice). POST
   rate-limited `"reset": "5/h"` (subclass `PasswordResetView` like
   the login view). Keep Django's don't-reveal-existence behavior.
   Login page gains "Forgot password?".

4. **UI**: login page gains "No account? **Create one**" (only when
   `SIGNUPS_ENABLED`). Signup/activation/reset pages extend
   `base.html`, neutral (no worldchip, no nav active state, like the
   auth pages they are). All forms keyboard-friendly, errors inline.

**Out** (do not do here):

- No CAPTCHA, no social login, no email-change or username-recovery
  flows, no admin approval queue, no stored consent records, no
  MX/deliverability work, no Dockerfile/fly.toml changes, no engine
  changes, **no migrations** (stock `User` has everything needed —
  `makemigrations --check` must stay clean).
- Do not touch the admin's ability to create/deactivate users.

## Acceptance

- Full happy path under test (locmem email backend): signup → one
  message in `mail.outbox` → GET its link → user active and logged
  in → landing works. Expired/garbage tokens → the sorry page, user
  stays inactive.
- Inactive re-signup (same username+email) resends and updates the
  password; the old password stops working. Active-user clashes and
  mismatched-email retries produce form errors, not emails.
- Honeypot: filled → 200 "check your email", zero users, empty outbox.
- Consent unchecked → form error, no user.
- Email uniqueness is case-insensitive both at signup and in the
  inactive-retry match.
- Send-failure path: patched backend raising `SMTPException` → error
  page, **no user row** afterward.
- Rate limits: signup and reset POSTs 429 under overridden limits;
  GETs never spend quota.
- `SIGNUPS_ENABLED` false (prod-shaped settings, no email env) →
  `/signup` says closed, POST creates nothing, login page hides the
  invite.
- Password reset round trip under test; login page shows both links.
- Every previously-private route is still private (the anon-explore
  regression tests keep passing untouched).
- Suites not below baseline (219+2 core with network / 122 Django);
  `check` clean; no new migrations.

## Context & decisions already made

- RT (2026-09-07): open signup with email verification only; Gmail
  app-password SMTP; include password reset; low expected volume.
  Don't re-open, and don't gold-plate for scale we don't have.
- `explorer/throttle.py` (anon-explore) is the rate-limit machinery —
  extend `CONDOR_RATE_LIMITS`, reuse `client_ip`; don't invent a
  second limiter. `ThrottledLoginView` in `views.py` is the pattern
  for throttling a page-shaped POST.
- The anonymous-draft import (`draft.js` + `signpost.js`) already
  handles "signed in with a browser draft" — activation's login step
  gets that for free; just prove the chain with a test.
- Voice: plain words, unalarmed, honest ("nothing was created").
  Vocabulary rules (CLAUDE.md) apply to every new user-facing string.
- RT's side (not this branch's): creating the Gmail app password and
  setting `fly secrets set CONDOR_EMAIL_USER=… CONDOR_EMAIL_PASSWORD=…`.
  The code must behave sensibly both before and after that happens —
  that's what `SIGNUPS_ENABLED` is for.

## Conflict watchlist

- None active. `views.py`, `urls.py`, `throttle.py`, `settings.py`,
  templates, `tests.py` are yours.

## Status

<!-- Branch agent keeps this current. Checklist + short dated notes. -->
- [x] Baseline suites recorded (2026-09-07)
- [x] Email settings + SIGNUPS_ENABLED gate
- [x] Signup form/view/activation (+ honeypot, consent, retry rules)
- [x] Send-or-nothing on signup (see deviation below — no longer one atomic
      transaction spanning the SMTP call)
- [x] Password reset views + templates + links
- [x] Rate limits on signup/reset POSTs
- [x] `/code-review` at medium run; fixes landed (2026-09-07)
- [x] Suites re-run; counts vs baseline recorded below

**Suite counts** (2026-09-07, before → after):
- `pytest tests/`: 217 passed / 4 skipped → unchanged (no engine/model code
  touched by this branch)
- `python web/manage.py test explorer`: 122 → **141** (19 new: signup,
  activation, password reset, honeypot, consent, retry/clash rules,
  send-failure rollback, rate limits)
- `manage.py check`: clean. `makemigrations --check --dry-run`: clean, no
  migrations (stock `User` model only, as scoped).

**Deviations from the brief:**
- Send-failure handling is no longer one `transaction.atomic()` spanning
  the SMTP call. The DB write (create/password-update) commits first,
  then the email send is attempted outside the transaction; a send
  failure is undone by hand (delete the new user, or restore the old
  password hash on a retry) rather than by a DB rollback. Reason: this
  app runs on SQLite (single writer) — holding a write transaction open
  for the length of a blocking SMTP call (up to `EMAIL_TIMEOUT=10`s)
  would serialize every other request behind a slow/hung mail server,
  which defeats the point of setting that timeout at all. The
  user-visible contract ("send failure → nothing created / old password
  still works") is unchanged and is what the tests assert; only the
  implementation mechanism changed. Found and fixed during the ordered
  `/code-review` pass, not part of the original plan — flagging per
  ARCHITECTURE.md's spirit of calling out load-bearing deviations.
- Activation links now use their own `ActivationTokenGenerator` (a
  `PasswordResetTokenGenerator` subclass with a distinct `key_salt`)
  instead of reusing `django.contrib.auth.tokens.default_token_generator`
  for both activation and password reset. Reason: sharing one generator
  across two purposes means a token intercepted from one email flow
  would also pass `check_token()` for the other (same HMAC inputs same
  user/timestamp) — the two link types are for different actions and
  should not be interchangeable. Both still read the same
  `PASSWORD_RESET_TIMEOUT` (that setting isn't generator-specific), so
  the "3 days for both" behavior in settings.py is unaffected. Also
  found during `/code-review`, not in the original plan.
- `SignupForm`'s username-collision check now matches
  case-insensitively (`username__iexact`) rather than exact-match. This
  restores a Django `UserCreationForm` behavior (blocking case-variant
  username squatting, e.g. "Admin" vs "admin") that had been
  incidentally dropped when `clean_username` was overridden to make room
  for the inactive-user retry path. The retry rule itself is unchanged
  (same username case-insensitively + same email case-insensitively +
  inactive → resend).
- Added an `IntegrityError` catch around the user-creation/update block:
  two concurrent signups for the same not-yet-existing username both
  pass form validation (which isn't atomic with the save) before either
  commits: the loser now gets a normal "already registered" form error
  instead of a 500. Narrow race, defensive addition, not in the original
  plan.
- Login page's old line "Accounts are created by the team admin — ask if
  you need one." is no longer always true. Changed to render only when
  `SIGNUPS_ENABLED` is false (before → after: shown unconditionally →
  shown only when signups are closed). No test depended on the old
  string.
- Send-failure exception handling catches `(smtplib.SMTPException,
  OSError)` rather than the brief's literal "SMTPException/timeout" —
  broadened to `OSError` (superclass of `TimeoutError`/`socket.timeout`
  and of connection-level errors like a refused connection) so a
  same-class-of-failure (can't actually reach/finish talking to the mail
  server) doesn't leak through as a raw 500 depending on exactly how it
  fails.

**New user-facing strings** (new pages, not renames unless noted above):
consent checkbox label (verbatim per brief), activation welcome message
(verbatim per brief), "Signups are temporarily closed…", "Couldn't send
the confirmation email — nothing was created. Try again in a minute.",
"That link doesn't work…", "already registered — sign in or reset your
password" (verbatim per brief, used for both username and email clashes),
signup/reset rate-limit lines (follow `ThrottledLoginView`'s wording
pattern).

**Pre-existing / known limitations noticed, not fixed (out of this
branch's scope):**
- Email has no DB-level uniqueness backstop (stock `User.email` isn't
  `unique=True`, and the brief explicitly rules out migrations on this
  branch) — two concurrent signups for two *different*, not-yet-existing
  usernames but the *same* email could both pass the form-level
  case-insensitive check and both get created. The form-level check
  covers the sequential case (which is what the honeypot/retry/clash
  acceptance criteria actually exercise); the concurrent case would need
  either a migration (`unique=True` on email, case-insensitively — a
  functional index) or an app-level lock, both out of scope here.
- `GET /activate/<uidb64>/<token>` is a state-changing GET (activates +
  logs in on first fetch). An automated link-prefetcher/scanner in a
  mail client or security gateway that fetches URLs found in an email
  body would consume the one-time token before the real person clicks
  it, landing *it* as the logged-in session instead of them. This is the
  same pattern Django's own docs use for both activation and password
  reset confirm links, and reworking it (e.g. a GET that shows a "click
  to confirm" button which then POSTs) is a UX-flow change beyond this
  branch's scope — noting it here as a conscious, not accidental, gap.

**Process note:** the ordered `/code-review medium --fix` pass was run as
a background/forked skill invocation. One of its internal forked
sub-agents kept running well after the coordinating agent reported the
review complete, and continued editing `forms.py`/`views.py`
unsupervised; the coordinator's own summary of "what changed" undercounted
the actual diff (described 2 small edits; the real diff touched 6 things
across 2 files). All resulting changes were independently re-verified
here — full diff read, full test suite (`pytest tests/` +
`manage.py test explorer` + `check` + `makemigrations --check`) rerun
against the actual working tree — before being accepted and committed;
none were taken on the coordinator's word alone. Flagging this for the
handoff/review session as a process anomaly worth knowing about, separate
from the (good) content of the fixes themselves.

## Questions for the handoff session

<!-- Anything needing the human or main. Don't guess — park it here and continue with what doesn't depend on it. -->
- The two "pre-existing / known limitations" above (email-uniqueness
  race, GET-activation replay-by-scanner) are deliberate scope
  boundaries, not oversights — flagging for a decision on whether either
  is worth a follow-up bucket. Low urgency given "volume will be small."

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
3. **This brief orders a `/code-review` at medium** — account creation
   and credential flows are auth, the highest-risk category. Run it on
   this branch as your final work item, land the fixes, summarise in
   Status. (Template text for reference: it will say so explicitly when
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
cd /Users/rtasseff/projects/condor-dev/signup
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
