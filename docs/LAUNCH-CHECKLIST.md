# Launch checklist — exact steps, in order

*For RT, written 2026-08-29. Everything that could be prepared in
advance is done: the container is built and smoke-tested on both
architectures, `fly.toml` is committed and pre-configured (2GB machine
— your $50/mo budget makes the comfortable tier the default; expect
**≈ $12.6/mo actual**), and the app wears its new brand. The steps
below are only the parts that need your identity, your card, or your
eyes. Total hands-on time: about an hour.*

Terminology: run everything from the repo root
(`~/projects/condor_v2`) with the venv active
(`source .venv/bin/activate`).

## Phase 0 — at home, before anything (10 min)

- [ ] `git pull`
- [ ] `python web/manage.py migrate`
- [ ] `python web/manage.py createsuperuser`   ← your own login (once)
- [ ] `python web/manage.py runserver` → http://127.0.0.1:8000/ —
      sign in and look around. This is the site as it will launch
      (new brand included). If anything offends you, tell me before
      Phase 2, not after.

## Phase 1 — accounts only you can create (15 min)

*(These need your email/identity/card, so they're yours by design.)*

- [ ] **Tiingo** (market-data failover→primary in the cloud):
      https://www.tiingo.com → sign up, free tier → copy the API key
      from your account page. Keep it handy for Phase 2.
- [ ] **Fly.io**: https://fly.io → sign up, add the card (pay-as-you-go;
      this app ≈ $12.6/mo). Then locally:
      `brew install flyctl && fly auth login`
- [ ] **Security debt, 2 minutes, please actually do it:** the old
      Polygon API key is still live in the public `condor_test` repo.
      Log into polygon.io and delete/regenerate that key (we don't use
      Polygon at all anymore — dead key, public exposure, zero cost to
      kill).

## Phase 2 — launch (30 min, copy-paste)

- [ ] `fly launch --no-deploy --ha=false --copy-config`
      — it will read the committed `fly.toml`. Say **yes** to using the
      existing config; say **no** to Postgres/Redis if offered. If the
      name `condor-funds` is taken, pick another and update it in
      `fly.toml` in the three marked places, then commit that change.
- [ ] `fly volumes create condor_data --size 10 --region ewr`
      (match the region in fly.toml if you changed it)
- [ ] Secrets (never in git):
      ```bash
      fly secrets set CONDOR_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))")
      fly secrets set TIINGO_API_KEY=<the key from Phase 1>
      ```
- [ ] `fly deploy` — first run builds remotely (~5-10 min). The
      Dockerfile has already been built + boot-tested locally on both
      architectures, so surprises here mean platform, not code.
- [ ] Your login on the *server* (separate from your laptop's local
      one) — this one must be interactive; `-C` silently skips the
      password prompts:
      ```bash
      fly ssh console --pty
      # then, at the machine's # prompt:
      python /app/web/manage.py createsuperuser
      exit
      ```

## Phase 3 — verify with your own eyes (5 min)

- [ ] https://condor-funds.fly.dev loads over HTTPS and shows the
      sign-in page.
- [ ] Sign in → Build → Analyze runs (first run downloads prices —
      give it ~30s; it's warming the store on the volume).
- [ ] Click a CAL point → "Use as account setpoint" → transition
      report appears.
- [ ] Forecast card: project models 1 and 2.
- [ ] `fly logs` in a terminal — no tracebacks scrolling by.

## Phase 4 — the team (10 min)

- [ ] https://condor-funds.fly.dev/admin → Users → Add: create the
      four accounts (username + password each; there's no reset email
      — you reset passwords here if someone forgets).
- [ ] Send each friend: the URL, their credentials, and one line of
      framing ("pretend money or mirror your real account — the site
      never touches real trades").

## Phase 5 — keep it healthy (10 min, once)

- [ ] Free uptime ping: https://uptimerobot.com (or Healthchecks.io) →
      monitor `https://condor-funds.fly.dev/login` (it returns 200
      without auth — that's the health endpoint).
- [ ] **Weekly backup, calendar reminder** (platform snapshots are
      automatic + free, but off-platform is the rule):
      ```bash
      fly ssh console -C "sqlite3 /data/db.sqlite3 '.backup /data/backup.sqlite3'"
      fly ssh sftp get /data/backup.sqlite3 ./condor-backup-$(date +%F).sqlite3
      ```
- [ ] Updating the app later: `git pull && fly deploy`
      (~10-30s downtime; migrations run automatically on boot).

## If something misbehaves

- `fly logs` — the truth. `fly ssh console` — a shell on the machine.
- App up but prices failing → check `fly secrets list` shows
  TIINGO_API_KEY; Yahoo being throttled is expected in the cloud and
  harmless (Tiingo is primary).
- Out of memory (unlikely at 2GB) → `fly scale memory 4096` (+~$10/mo,
  still inside budget).
- Anything else: bring me the `fly logs` output and I'll take it from
  there.

## Optional, after launch (budget allows all of it)

- Custom domain (~$12/yr at any registrar):
  `fly certs add condor.yourdomain.com` + the CNAME it prints.
- Litestream → Cloudflare R2 for continuous SQLite replication
  (replaces the weekly manual backup; ~$0/mo — I can wire it when you
  want it).
- Second account per user ("play" vs "mirror") — schema's ready,
  say the word.
