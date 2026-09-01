# Deploying the 5-user test (Release 0.1)

*Plan written 2026-08-23. Hosting facts come from
`docs/research/hosting-options.md` (agent-researched with sources,
prices verified that day — re-check before purchase). The code side is
DONE and merged; what remains is RT's host decision plus ~an hour of
runbook.*

## 1. The goal and its shape

Five trusted users in ~4 time zones. Traffic is tiny but the app must
be **always on** (no cold starts — people log in at any hour, and the
first analyze is interactive). The app is a single Django container
that needs:

- **one persistent disk** for two things: `db.sqlite3` (accounts,
  ledgers, saved portfolios) and the Parquet price store
  (`CONDOR_DATA_DIR`) — the store self-heals by re-downloading, but a
  cache wipe causes exactly the burst of Yahoo requests that gets
  cloud IPs rate-limited (see §4);
- **one machine only** (SQLite's rule, and every sane platform
  enforces single-instance-with-disk anyway). Consequence everywhere:
  deploys are stop-then-start with 10–60s of downtime. At our scale,
  fine — don't design around it;
- outbound HTTPS to Yahoo / Tiingo / FRED; TLS in front; ~1GB RAM
  (pandas + cvxpy resident set is 400–700MB).

## 2. What the code already does (merged)

| Concern | Where |
|---|---|
| All config via env — `CONDOR_SECRET_KEY`, `CONDOR_DEBUG`, `CONDOR_ALLOWED_HOSTS`, `CONDOR_CSRF_ORIGINS`, `CONDOR_DB_PATH`, `CONDOR_DATA_DIR`, `CONDOR_SOURCE`, `TIINGO_API_KEY` | `web/config/settings.py`, `condor/data/` |
| Static files without a reverse proxy | whitenoise (compressed, collectstatic baked into the image) |
| App server | gunicorn, 2 workers; PriceStore POSIX locks already make multi-worker safe |
| Container | `Dockerfile` (python:3.11-slim; migrate-then-serve at start). *Validated 2026-08-24: built + smoke-tested on arm64 and cross-built + boot-tested for linux/amd64 — prod env, migrations on a volume, 301→https, proxy-header 200, whitenoise static all confirmed.* |
| One clock for four time zones | `TIME_ZONE = "UTC"` pinned |
| SQLite under concurrency | WAL mode + 20s busy timeout in `DATABASES["OPTIONS"]` |
| Production hardening | SSL redirect (behind proxy header), secure cookies, nosniff, modest HSTS, X-Frame DENY. `check --deploy` is clean except HSTS-subdomain/preload — deliberately skipped while we live on a platform subdomain |
| Data-source failover | `CONDOR_SOURCE=tiingo,yfinance` = explicit ordered chain (new); a lone name still means "exactly that source" |

## 3. Hosting: recommendation and why

Full comparison in `docs/research/hosting-options.md`. Headlines
(verified 2026-08-23): Fly.io has no free tier but honest pay-as-you-go;
Hetzner raised US prices ~3x in June 2026 and rations new-customer
capacity; Render's Hobby tier is fine but its only sub-$25 instance has
512MB RAM (tight for our pandas/cvxpy resident set); DigitalOcean App
Platform and PythonAnywhere are **disqualified** (ephemeral filesystem;
NFS-backed disk that SQLite can't trust).

**Recommendation — Fly.io: one `shared-cpu-1x` machine + 10GB volume,
always-on, `--ha=false`.** RT set a $50/mo budget (2026-08-28), so the
committed `fly.toml` defaults to the comfortable **2GB tier ≈
$12.61/mo** (1GB ≈ $7.42 exists if we ever want to pinch). Step-by-step
for launch day: `docs/LAUNCH-CHECKLIST.md`.

Why it fits us specifically: Dockerfile-native; the volume takes both
SQLite and the price store; RAM is billed on *provisioned* size (flat
bill no matter what pandas holds resident); daily volume snapshots are
free at our size; and its anycast edge terminates TLS near each user —
the one thing a single-region box can't otherwise do for a US+EU+Asia
user base. Honest tradeoff: the volume is unreplicated local NVMe on a
platform with a visible 2025–26 incident history — which is why §5's
off-platform backup is part of the deploy, not an optional extra.

**Runner-up — DigitalOcean $6 droplet (1GB/25GB) + daily backups ≈
$7.80/mo**, docker-compose behind Caddy. Zero platform abstractions and
the least likely to surprise us in 18 months; the cost is being the
sysadmin (patching, firewall, monitoring — a real, skippable-and-
therefore-skipped chore). Pick this over Fly only if you'd *enjoy*
owning the box.

**When to switch away from Fly:** if the machine needs >2GB, if
snapshots/incidents bite, or if we outgrow SQLite (BACKLOG's Postgres
triggers) — Render Standard or a managed-Postgres platform become the
conversation, and the env-driven settings make the move boring.

## 4. Market data in production (important)

The research verdict: Yahoo aggressively rate-limits shared datacenter
IPs (PythonAnywhere/Streamlit/EC2 reports through 2025-26; yfinance's
own recommended caching extra is currently broken, issue #2913).
Therefore in production:

- **Tiingo becomes primary, Yahoo the opportunistic fallback:**
  `CONDOR_SOURCE=tiingo,yfinance`. Get the free Tiingo key
  (~2,400 req/hr — plenty; the bucket follows the key, not the IP)
  and set `TIINGO_API_KEY` as a platform secret. Locally, keep the
  default (Yahoo first) — it's fine from residential IPs.
- The Parquet store on the volume is our caching layer (24h TTL,
  seam-checked incremental updates) — it already prevents the request
  pattern that triggers 429s, as long as it survives deploys (§1).
- A Yahoo 429 must never fail a user request — the chain + the
  store's stale-if-source-down behavior already ensure this.
- FRED is key-free and safe at our volume; rate cache is 12h.

## 5. Fly.io runbook (when RT says go)

```bash
brew install flyctl && fly auth signup        # or login
cd condor_v2
fly launch --no-deploy --ha=false             # detects Dockerfile; pick region near you (e.g. ewr)
fly volumes create condor_data --size 10      # same region
```

Edit the generated `fly.toml`: internal_port 8000;
`auto_stop_machines = "off"`, `auto_start_machines = false`,
`min_machines_running = 1`; mount the volume at `/data`; env block:

```toml
[env]
  CONDOR_DEBUG = "0"
  CONDOR_ALLOWED_HOSTS = "<app>.fly.dev"
  CONDOR_CSRF_ORIGINS = "https://<app>.fly.dev"
  CONDOR_DB_PATH = "/data/db.sqlite3"
  CONDOR_DATA_DIR = "/data/condor"
  CONDOR_SOURCE = "tiingo,yfinance"
[mounts]
  source = "condor_data"
  destination = "/data"
```

```bash
fly secrets set CONDOR_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))")
fly secrets set TIINGO_API_KEY=...            # from tiingo.com, free tier
fly deploy                                    # first build validates the Dockerfile
fly ssh console --pty
# then, at the machine's # prompt (interactive — -C has no TTY for the password prompts):
python /app/web/manage.py createsuperuser
exit
fly volumes snapshots list <vol-id>           # confirm dailies are on
```

Then log in at `https://<app>.fly.dev`, add the four teammates at
`/admin` (usernames + passwords you hand them; no reset email — admin
resets passwords, documented team-wide). Custom domain later:
`fly certs add condor.example.com` + a CNAME.

**Backups (non-optional):** platform snapshots (daily, free) protect
against our mistakes; an off-platform copy protects against the
platform. Minimum viable: a weekly `fly ssh console -C "sqlite3
/data/db.sqlite3 '.backup /data/backup.sqlite3'"` + `fly ssh sftp get`
to RT's machine (calendar reminder). Proper version when the test
sticks: Litestream sidecar streaming to Cloudflare R2 (~$0). The price
store needs no backup — it re-downloads.

**Monitoring:** `https://<app>.fly.dev/login` returns 200 anonymously —
point a free pinger (Healthchecks.io / UptimeRobot) at it.

**Updating:** `git pull && fly deploy` (10–30s downtime; migrations run
on boot).

## 6. Cost summary

| Item | $/mo |
|---|---|
| Fly machine 1GB, always-on | 5.92 |
| 10GB volume | 1.50 |
| Snapshots (≤10GB) | 0 |
| Tiingo free tier / FRED | 0 |
| **Total** | **≈ 7.42** (≈ 12.61 if bumped to 2GB) |

## 7. Decisions that are RT's

1. **Host**: Fly (recommended) vs DO droplet (more control, more
   chores). Say the word and the runbook above executes in an hour.
2. **Tiingo key**: create the free account (it lands in `fly secrets`,
   never in git).
3. **Rotate the old Polygon key** in the public condor_test repo
   before anything gets more public (longstanding reminder).
4. **Domain**: `<app>.fly.dev` is fine for the test; a real domain is
   a $10/yr nicety that can wait for branding.
5. **Region**: pick nearest RT (users are spread anyway; Fly's edge
   handles the handshakes).
