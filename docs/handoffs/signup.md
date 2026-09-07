# Handoff — `feature/signup`

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
- [ ] Baseline suites recorded
- [ ] Email settings + SIGNUPS_ENABLED gate
- [ ] Signup form/view/activation (+ honeypot, consent, retry rules)
- [ ] Transactional send-or-nothing
- [ ] Password reset views + templates + links
- [ ] Rate limits on signup/reset POSTs
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
