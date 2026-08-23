<!-- Research agent report, 2026-08-23. Prices/limits are point-in-time; re-verify before purchase. -->

# Hosting a tiny always-on Django 5 monolith — August 2026 decision report

*All prices verified against vendor pages/docs during research on 2026-08-23. Where a third-party aggregator was the only source with a dollar figure, it is flagged. EUR→USD converted at ~1.08.*

---

## Executive summary (read this if nothing else)

Three things changed the landscape since the "just use Hetzner / just use Fly free tier" advice you may remember:

1. **Fly.io has no free tier at all** — new accounts get 2 VM-hours *or* 7 days, whichever comes first. It is pure pay-as-you-go with no plan fee, which is actually good for you: ~$7.40/mo buys a real always-on box.
2. **Hetzner raised cloud prices twice in 2026** (April 1, then a much larger adjustment on **15 June 2026**). US shared-AMD instances went up ~2.9–3.1x — `CPX11` in the USA went **€5.99 → €17.49/mo**. Hetzner is *still* the best RAM-per-euro in the EU, but it is no longer the obvious budget answer, and **new-customer server provisioning has been capacity-restricted since 2026-04-28**.
3. **Render dropped seat fees in April 2026** (Hobby workspace is genuinely free now) but **cut included bandwidth from 100 GB to 5 GB** on Hobby, with $0.15/GB overage. Irrelevant at your traffic, but worth knowing.

**None of your candidates forces a 30s cold start** — that is an opt-in behavior everywhere except Render's *free* tier. Configure it off and move on.

**The SQLite question has a uniform answer:** every platform here that offers a real disk (Fly, Railway, Render, any VPS) *enforces* single-instance-with-disk, which is exactly what SQLite wants. The universal consequence is that **deploys are stop-then-start, not zero-downtime** — 10–60 seconds of unavailability per deploy. For 5 trusted users, that is a non-issue. Say it once, stop worrying about it.

**Two candidates are disqualified on the disk requirement:**
- **DigitalOcean App Platform** — filesystem is ephemeral and explicitly "permanently lost after deployments." Your Parquet cache would re-download on *every deploy*.
- **PythonAnywhere** — home storage is **NFS-backed**, and SQLite over NFS is a documented, long-running source of `database is locked` errors on their own forums. Their staff recommend MySQL/Postgres for anything non-trivial.

---

## 1. Fly.io

**Cost for your shape:** `shared-cpu-1x` @ 1GB = **$5.92/mo** + 10GB volume @ $0.15/GB = **$1.50/mo** → **~$7.42/mo**. (256MB $2.02 · 512MB $3.32 · 1GB $5.92 · 2GB $11.11 — figures shown for Amsterdam; Fly now has some region-specific machine pricing, US/EU are the baseline tier.) Shared IPv4 is free; a dedicated IPv4 is $2/mo and you don't need one. Egress $0.02/GB in NA/EU — rounding error for you.

**Headroom path:** `fly scale memory 2048` gets you 2GB for $11.11 + $1.50 = **$12.61/mo**, still inside budget. RAM is billed on *provisioned* size, so your bill is flat and predictable regardless of what pandas does. This matters — see Railway.

**Free tier:** none. Trial is 2 VM-hours / 7 days / 10 machines / 20GB volumes, and trial machines auto-stop after 5 minutes. No monthly plan fee for paid orgs; support is a $29/mo add-on.

**Always-on:** set `auto_stop_machines = "off"` and `auto_start_machines = false` in `fly.toml`. Stopped/suspended machines aren't billed for CPU/RAM, but you're explicitly not using that.

**SQLite sanity: good, and structurally enforced.** A Fly volume attaches to exactly one machine — a strict 1:1 mapping. Two machines physically cannot mount the same volume, so you can't accidentally corrupt the DB by scaling out. Use `fly launch --ha=false` (or `fly scale count 1`) so Fly doesn't provision the standard two-machine HA pair.

**Deploys:** default strategy is `rolling`. With a single machine + volume, Fly's own docs are blunt: *"you'll have downtime if there's a host or network failure, and whenever you deploy your app."* `bluegreen` is not usable (it needs a second machine, which would need a second volume). Expect ~10–30s per deploy.

**Backups:** daily block-level volume snapshots, 5-day retention by default, configurable 1–60 days. Snapshot storage is $0.08/GB/mo with **the first 10GB free each month** — so at your size, snapshots are free. Fly warns snapshots "may not have your latest data."

**Regions:** 18, including iad/ewr/ord/dfw/sjc/lax (US), ams/fra/lhr/cdg/arn (EU), nrt/sin/bom/syd (APAC).

**Deploy workflow:** Dockerfile-native (`fly deploy`), or buildpacks. TLS + `*.fly.dev` subdomain automatic; custom domains with free Let's Encrypt certs via `fly certs add`.

**Gotchas, honestly:**
- Your data sits on one host's local NVMe with **no replication**. Volumes aren't backed by network storage. Host dies → downtime plus up to 24h of data loss. **You must add your own off-platform backup** (Litestream to S3/R2, or a nightly `sqlite3 .backup` + rclone). This is the single biggest caveat.
- Fly's control plane has had a recurring incident pattern through 2025–26 traced to Consul degradation and Corrosion state-propagation issues; there were incidents in March, June and August 2026. Fly is unusually transparent about this (they publish an infra-log covering incidents that never hit the status page), which is admirable but also means you can read exactly how often it breaks.
- **Real upside for your user distribution:** Fly's anycast proxy terminates TLS at the nearest edge and tunnels to your single machine. Your EU/Asia users get a local TCP+TLS handshake instead of a transatlantic one — worth roughly one round-trip per connection versus a plain single-region VPS.

---

## 2. Railway

**Cost model:** Hobby is **$5/mo including $5 of usage credit**; Pro is $20/mo per workspace including $20 credit. Free plan gives $1/mo credit and caps services at 0.5GB RAM. Metered rates: **$0.00000772/vCPU/s** and **$0.00000386/GB/s**, i.e. **~$20.29/vCPU-month** and **~$10.14/GB-month**. Volumes **$0.00000006/GB/s ≈ $0.158/GB-month**. Egress $0.05/GB.

**Your realistic bill:** Railway meters *actual* resident memory and CPU, not provisioned size. A Django+gunicorn process holding numpy/pandas/pyarrow/cvxpy will sit at 400–700MB RSS **continuously**, because it never gets to idle-out.
- @ 0.5GB RSS, ~0.05 vCPU avg, 5GB volume → ~$6.9/mo
- @ 1.0GB RSS → **~$11.9/mo**

So Railway is inside budget but **prices exactly the thing your app does badly**: hold a large resident set while doing almost nothing. Fly charges flat for the same RAM.

**Hard constraint:** **Hobby caps volumes at 5 GB.** Pro allows 50GB self-serve (up to 1TB). Your stated Parquet cache is 10–100MB so 5GB is genuinely fine — but if you wanted the 5–10GB you asked about as a floor, Hobby doesn't strictly give it, and Pro is $20/mo base.

**SQLite sanity: fine.** Railway explicitly states *"Replicas cannot be used with volumes."*

**Deploys:** Railway prevents two active deployments on a volume-attached service. Their docs confirm *"a small amount of downtime when re-deploying a service that has a volume attached, even if there is a healthcheck endpoint configured."*

**Sleep:** Railway's serverless/app-sleeping is **opt-in**, triggered by 10 minutes of no *outbound* traffic, and the first request after wake "may return a 502 Bad Gateway." Just leave it off — services are otherwise always-on.

**Backups:** manual and automated backups are supported for volume-attached services. Volumes resize live upward; downsizing is unsupported.

**Regions:** us-west2 (California), us-east4 (Virginia), europe-west4 (Amsterdam), asia-southeast1 (Singapore). **EU-West metal is available to Hobby; Singapore has been Pro-only**, with Railway saying they're working toward Hobby access — verify before committing if Asia latency matters.

**Deploy workflow:** git push (Nixpacks/Railpack auto-detect) or Dockerfile. TLS + custom domains included.

---

## 3. Render

**Cost:** Hobby **workspace** is $0/mo (1 member, 25 services max). Instance types for web services: Free (0.1 CPU / 512MB), **Starter $7/mo (0.5 CPU / 512MB)**, **Standard $25/mo (1 CPU / 2GB)**, Pro $85-ish (2 CPU / 4GB) and up. **Persistent disk: $0.25/GB/mo.**

→ Starter + 10GB disk = **$9.50/mo**. Standard + 10GB disk = **$27.50/mo** (over budget).

**The RAM problem:** 512MB is the honest weak point. `import pandas, pyarrow, numpy` plus cvxpy/ECOS is ~200–300MB before you compute anything, and an efficient-frontier solve on top of that can push a gunicorn worker toward the limit. Render OOM-kills and restarts. There is no $12–15 middle rung between Starter and Standard, so if 512MB doesn't hold, Render jumps straight past your budget.

**Free tier — disqualified:** free web services **spin down after 15 minutes of no inbound traffic and take about one minute to spin back up**, are capped at 750 instance-hours/month, cannot scale past one instance, and **cannot have a persistent disk at all**. Free Postgres also **expires 30 days after creation** (1GB, no backups). This is precisely the cold-start scenario you ruled out.

**SQLite sanity: good, and enforced by the platform.** Render's disk docs: adding a disk *"prevents zero-downtime deploys"* and *"you can't scale a service to multiple instances if it has a disk attached."* Deploys stop the old instance before starting the new one, "causing a few seconds of unavailability" — deliberately, to prevent exactly the data corruption you'd worry about.

**Backups: best-in-class here.** Render *"automatically creates a snapshot of your persistent disk once every 24 hours,"* available for **at least seven days**, encrypted at rest. No configuration, no extra cost.

**Bandwidth:** Hobby includes **5 GB/mo** outbound (down from 100 GB in the April 2026 repricing), $0.15/GB over. Your outbound-to-Yahoo/Tiingo traffic is *inbound* to you and free; outbound is just HTML for 5 people. Fine.

**Custom domains:** 2 included on Hobby, $0.25/mo each beyond. TLS automatic.

**Regions:** Oregon, Ohio, Virginia, Frankfurt, Singapore. **A service's region cannot be changed after creation** — you'd rebuild and migrate data.

**Deploy workflow:** git push from GitHub/GitLab, or a Dockerfile, or `render.yaml` blueprint. Lowest-friction of the managed options.

---

## 4. Hetzner Cloud VPS

**This is the candidate whose 2026 story most contradicts its reputation.**

**Post-15-June-2026 EU pricing** (ex-VAT, ex-IPv4):

| Plan | vCPU | RAM | Disk | Traffic | Was | **Now** |
|---|---|---|---|---|---|---|
| CX23 | 2 | 4 GB | 40 GB NVMe | 20 TB | €3.99 | **€5.49** |
| CX33 | 4 | 8 GB | 80 GB | 20 TB | €6.49 | **€8.49** |
| CAX11 (Arm) | 2 | 4 GB | 40 GB | 20 TB | €4.49 | **€5.99** |
| CAX21 (Arm) | 4 | 8 GB | 80 GB | 20 TB | — | **€10.49** |
| CPX22 | 2 | 4 GB | 80 GB | 20 TB | €7.99 | **€19.49** |

**US pricing (Ashburn / Hillsboro) is the shock:** `CPX11` **€5.99 → €17.49**, `CPX21` **€11.99 → €31.99**. CPX in the US rose up to ~3.1x — the largest relative increases on the platform. Also note US regions include only **1 TB** of traffic, not 20 TB. **The cheap CX and CAX lines are EU-only.**

**Extras:** IPv4 **€0.50/mo** per server (billed whether attached or not; IPv6-only saves it). Automatic backups **+20% of instance cost**, up to 7 retained. Block volumes **€0.0572/GB/mo**. Snapshots €0.0143/GB/mo. Traffic overage €1/TB in EU/US.

**Your bill:** CX23 in Falkenstein/Helsinki = €5.49 + €0.50 IPv4 + €1.10 backups = **€7.09 ≈ $7.66/mo — for 2 vCPU, 4 GB RAM and 40 GB of local NVMe.** No separate volume needed. That is roughly **4x the RAM per dollar of anything else in this report.** If your users skew EU, this is objectively the best hardware for the money.

**In the US it is $23/mo for 2GB RAM.** Don't.

**The blockers you need to know about:**
- **Capacity restriction, ongoing since 2026-04-28:** Hetzner states that high demand and hardware-component shortages mean cloud server provisioning is "currently possible only to a limited extent." Creation of new cloud servers is restricted for **new customers** and a randomly selected subset of existing ones. You may simply not be able to buy a CX23 when you try.
- **ID verification friction:** new accounts frequently require a passport/government-ID scan before the first server; activation can take a day. VPN signups and address/billing mismatches are common triggers for extra scrutiny or rejection.
- **No published uptime SLA** for cloud products. Phone support is dedicated-server customers only; cloud gets tickets.
- **No managed anything** — no managed Postgres, no managed backups beyond the snapshot checkbox.

**SQLite sanity:** perfect. It's a real local filesystem on one box. Nothing to reason about.

**Deploy workflow / ops:** You own all of it. Realistic minimum viable setup: Docker + `docker compose`, Caddy as reverse proxy (automatic Let's Encrypt), `unattended-upgrades`, `ufw`, a cron'd `sqlite3 .backup` to an offsite bucket, and something like Uptime Kuma or Healthchecks.io pinging you. Coolify (self-hosted, free) or Dokploy gives you a git-push PaaS UI on top — but **if you use Coolify, set the deploy strategy to recreate, not rolling**, or it will try to start a second container against the same bind-mounted SQLite file.

**Honest ops burden:** the initial build is a focused evening. Steady state is maybe 20 minutes a quarter *if nothing breaks*. The real cost is that "checking in occasionally" and "an internet-facing Ubuntu box you patch" are in mild tension — an unattended box that drifts 8 months out of date is a genuine liability in a way that a managed platform isn't.

---

## 5. DigitalOcean

### Basic Droplets (the viable option)

| vCPU | RAM | SSD | Transfer | $/mo |
|---|---|---|---|---|
| 1 | 512 MiB | 10 GB | 500 GB | **$4** |
| 1 | 1 GB | 25 GB | 1 TB | **$6** |
| 1 | 2 GB | 50 GB | 2 TB | **$12** |
| 2 | 2 GB | 60 GB | 3 TB | **$18** |

**Backups:** percentage-based at **20% (weekly)** or **30% (daily)** of Droplet cost, or usage-based plans from $0.01/GiB/mo. Snapshots $0.06/GB/mo. Block storage volumes $0.10/GiB/mo (you won't need any — 25GB is included on the $6 droplet).

**Your bill:** $6 droplet + 20% weekly backups = **$7.20/mo**; with 30% daily backups = **$7.80/mo**. The 2GB droplet at $12 + $3.60 daily backups = $15.60, marginally over.

**SQLite sanity:** perfect, same as any VPS.

**Regions:** NYC1/2/3, SFO2/3, TOR1, **AMS3, FRA1, LON1**, **SGP1**, BLR1, SYD1. Good US+EU+Asia coverage.

**Deploy workflow / ops:** identical to Hetzner — your Dockerfile, your compose file, your Caddy. Difference from Hetzner: **no capacity restriction, no ID-verification lottery, a published SLA, one-click backups, and by far the largest body of copy-pasteable tutorials for exactly this stack.** You pay for that in RAM — $6 buys 1GB where Hetzner's €5.49 buys 4GB.

### App Platform — **disqualified**

$5/mo (1 vCPU / 512 MiB) and $10/mo (1 vCPU / 1 GiB) for fixed shared-CPU instances; scalable tiers from $12. Free tier is static sites only.

**It has no persistent storage.** DO's own limits doc: *"Data in the host instance's local filesystem is permanently lost after deployments and other container replacements,"* local filesystem capped at 4 GiB, and containers are replaced if the disk fills. Guidance is explicitly to use Spaces or a managed database instead.

For you that means: SQLite is impossible (→ managed Postgres, +$7–15/mo, pushing you to ~$17–25/mo), **and your Parquet cache is destroyed on every single deploy**, triggering a slow full re-download from Yahoo/Tiingo each time — which, given the Yahoo situation below, is the worst possible property. Rule it out.

---

## 6. PythonAnywhere — **disqualified for SQLite, but read the caveat**

**Pricing changed in January 2026:** the $5 Hacker and $12 Web Dev tiers were merged into a single **Developer tier at $10/mo (€10 on the EU system)**. Existing customers keep legacy pricing until they change plans. Free "Beginner" tier: 1 web app, 512MB, 100 CPU-s/day, and **outbound internet restricted to an HTTP(S) allowlist**. Custom tier is $10–$500.

**Developer ($10/mo):** 1 web app, **5 GB disk**, **5,000 CPU-seconds/day**, **unrestricted outbound internet**, 1 always-on task, custom domain + HTTPS included.

**What's genuinely good:** the unrestricted-outbound-access distinction is real and clearly documented — the free-tier allowlist is the thing that breaks yfinance/Tiingo, and $10/mo removes it. Ops burden is the lowest of anything here: no Docker, no OS, no TLS renewal. Deploy is `git pull` + reload.

**Why it's disqualified for your app:**
- **NFS-backed storage.** SQLite explicitly does not support networked filesystems (NFS/SMB/CIFS) because their locking is unreliable. PythonAnywhere's forums have a decade-deep archive of `database is locked` threads, and staff guidance is to use MySQL or Postgres for anything with real database access. Symptoms reportedly worsen once the DB exceeds ~1 MiB and with any write concurrency. WAL mode helps but does not make NFS safe. Your 5 users would probably survive; "probably survive" is not what you want under your primary datastore.
- **5,000 CPU-seconds/day = 83 CPU-minutes.** Interactive cvxpy frontier solves consume this bucket. Five users exploring portfolios could plausibly hit it, and exceeding it throttles you into a low-priority queue.
- **No Docker**, so your Dockerfile-based deploy path doesn't transfer.

If you *did* want PythonAnywhere, the honest configuration is PythonAnywhere + their MySQL — at which point you've abandoned the SQLite simplicity that made the whole plan attractive.

---

## 7. Newer entrants (one line each)

- **Sevalla** — usage-based, all features on every account, git-push or Dockerfile; **persistent storage is $10/mo per 10GB**, which is 6–40x everyone else, though its Cloudflare-R2-backed object storage at $0.02/GB with zero egress is a genuinely good place to park Parquet files and DB backups.
- **Zeabur** — Dev plan **$5/mo including $5 credits** (solo/side-project tier, automatic backups, priority support), Pro $19/mo; credible Railway-alike, smaller company, thinner track record.
- **Coolify Cloud** — **$5/mo for 2 servers**, +$3/server after, no seat fees; note this is a *managed control plane only* — you still bring and pay for your own Hetzner/DO VPS, so read it as "$5/mo to make option 4 or 5 feel like a PaaS."

---

## Comparison table

| Option | $/mo, always-on, ~1GB class | Persistent disk | SQLite sane? | Always-on? | Backups | Region US/EU/Asia | Ops burden (1=easy, 5=hard) |
|---|---|---|---|---|---|---|---|
| **Fly.io** 1GB + 10GB vol | **$7.42** (2GB → $12.61) | Yes, $0.15/GB/mo | **Yes** — 1:1 volume↔machine, can't double-mount | Yes (`auto_stop_machines="off"`) | Daily snapshots, 5d default (1–60 configurable); **free ≤10GB**; no replication | US ✓ EU ✓ Asia ✓ (18 regions) | **3** |
| **Railway** Hobby | ~$7 @0.5GB RSS, **~$12 @1GB RSS** | Yes, ~$0.158/GB/mo, **5GB cap on Hobby** | **Yes** — replicas forbidden with volumes | Yes (sleeping is opt-in) | Manual + automated volume backups | US ✓ EU ✓ Asia (Pro-gated) | **2** |
| **Render** Starter + 10GB | **$9.50** (only 512MB RAM) | Yes, $0.25/GB/mo | **Yes** — platform forces single instance | Yes (only *Free* tier spins down) | **Automatic daily snapshot, 7d retention, free** | US ✓ EU (FRA) ✓ Asia (SIN) ✓ | **1** |
| **Hetzner CX23** (EU only) | **~$7.7** — but **4GB RAM, 40GB NVMe** | Included (local NVMe) | **Yes**, trivially | Yes | +20% for automatic backups (7 retained) | **EU only at this price**; US = ~$23 | **4** + capacity/ID-verification risk |
| **DigitalOcean** 1GB Droplet | **$7.20** (weekly) / **$7.80** (daily) | Included (25GB SSD) | **Yes**, trivially | Yes | 20%/30% checkbox; snapshots $0.06/GB | US ✓ EU ✓ Asia ✓ | **4** |
| **DO App Platform** | $10 + Postgres ≈ $17–25 | **None — ephemeral** | **No** | Yes | N/A | US ✓ EU ✓ Asia ✓ | 2 |
| **PythonAnywhere** Developer | **$10** | 5GB, **NFS-backed** | **No** — documented lock failures | Yes | Yours to arrange | US + EU host; no Asia | **1** |

---

## Ranked recommendation for *this* app

### 🥇 Top pick — Fly.io: 1× `shared-cpu-1x` @ 1GB + 10GB volume, `auto_stop_machines = "off"`, `--ha=false` — **~$7.42/mo**

It is the only option that satisfies every one of your stated constraints simultaneously without a compromise: Dockerfile-native deploys, a first-class persistent volume that your `CONDOR_CACHE_DIR` can point straight into, RAM billed at a flat provisioned rate (so pandas holding 700MB doesn't inflate your bill the way it would on Railway), a one-line always-on config, free daily snapshots at your size, no OS to patch, and an anycast edge that meaningfully cuts handshake latency for your EU and Asia users off a single machine — which is the one thing a plain VPS genuinely cannot do for a globally-spread audience. If 1GB turns out tight, `fly scale memory 2048` is instant and lands at $12.61, still under budget.

> **Honest tradeoff:** your database and Parquet cache live on one host's unreplicated local NVMe on a platform whose control plane visibly broke several times in 2025–26, so this is only a responsible choice if you treat an off-platform backup as part of the deploy — Litestream continuously replicating SQLite to R2/S3, or at minimum a nightly `sqlite3 .backup` piped to object storage — and accept ~10–30 seconds of downtime every time you ship.

### 🥈 Runner-up — DigitalOcean $6 Basic Droplet (1GB / 25GB) + 30% daily backups, running `docker compose` behind Caddy — **~$7.80/mo**

Same money, and it removes every platform abstraction from the problem: SQLite on a normal ext4 filesystem, the Parquet cache in a bind-mounted host directory, daily whole-machine backups as a checkbox, a published SLA, no capacity lottery, no ID verification, and the deepest pile of exactly-this-stack tutorials on the internet. It is the option least likely to surprise you in eighteen months.

> **Honest tradeoff:** you are now the sysadmin — `unattended-upgrades`, `ufw`, Docker version drift, Caddy, and your own uptime monitoring — which is perhaps an hour to set up and 20 minutes a quarter to maintain, and that maintenance is real work that a "checking in occasionally" maintainer is genuinely likely to skip.

### Honorable mentions
- **Render Starter ($9.50)** — pick this if lowest-possible-ops is worth more to you than headroom. Best backup story in the report (free automatic daily snapshots, 7-day retention, zero config) and the platform *enforces* SQLite-safe single-instance behavior for you. **The 512MB ceiling is the whole risk**, and the next rung up is $27.50 with nothing in between.
- **Hetzner CX23 in Falkenstein (~$7.7 for 2 vCPU / 4GB / 40GB)** — if your users are EU-weighted and you can actually get an account provisioned, this is 4x the hardware of anything else here for the same money. The April-2026 capacity restriction on new customers and the ID-verification gate are why it isn't ranked higher; the June price increase is why the US region isn't even a candidate.

### Applies to whichever you choose
1. Point the Parquet cache env var **inside the mounted volume** (e.g. `/data/cache`), not into the image. On a VPS, bind-mount a host directory.
2. Turn on SQLite **WAL mode** and set a `timeout` in Django's `OPTIONS` — cheap insurance under gunicorn's multiple workers.
3. Budget for **off-platform backups regardless of provider**. Platform snapshots protect against your mistakes; they do not protect against the platform.
4. Deploy downtime is 10–60s everywhere. Don't design around avoiding it.

---

## Yahoo Finance from datacenter IPs — the verdict

**Yahoo does not publish an IP-based block policy, and there is no evidence of a hard, permanent ASN-level ban on any cloud provider. What the 2025–2026 record shows is aggressive, opaque, IP-bucketed rate limiting that hits shared cloud egress IPs far harder than residential ones — which in practice looks and feels like "blocked from the cloud."**

The strongest evidence comes from hosting providers themselves. PythonAnywhere staff, on their own yfinance support thread: *"Some services block access from non-domestic sources (like headless servers in data centers). That could be the case."* (Oct 11 2024), and later, unambiguously: *"It's a block on yahoo side, and not us blocking it."* (**Sept 11 2025**). On Streamlit Community Cloud, multiple users independently reported the local-works/cloud-fails split within days of each other in late April–May 2025, and the accepted explanation there is the noisy-neighbor mechanism: *"these requests seem to come from just a bunch of IP addresses… these IPs have been blocked permanently or for a long time, due to high traffic coming from them."*

**But it is not purely datacenter-vs-residential, and you should not believe anyone who says it is.** yfinance discussion #2581 (Aug 6 2025) documents a user getting 429'd on the *first* `.info` call both locally and on EC2. Issue #2658 (Dec 26 2025) shows a raw `curl` to the Yahoo chart endpoint returning 429, with the reporter noting that changing IPs didn't help. Maintainer guidance is consistently "fetch smarter, stop spamming Yahoo." Residential IPs get throttled too — datacenter IPs simply start much closer to the limit because the token bucket is shared across every tenant behind that egress address.

**Per provider:** concrete reports exist only for **PythonAnywhere, Streamlit Community Cloud, and AWS EC2** — all bad. There is **no credible A/B evidence** ranking AWS vs. Hetzner vs. DigitalOcean vs. Fly, and no report of any named provider being permanently hard-blocked. Treat provider choice here as *unpredictable, not solvable* — do not pick your host hoping to dodge this.

**Library state, Aug 2026:** the 2025 churn (Feb 2025 Yahoo redesign and new quotas; cookie/crumb auth since 0.2.32; curl_cffi + `impersonate="chrome"` around 0.2.57–0.2.60; 0.2.62 rate-limit detection during crumb fetch; rejection of plain `requests.Session`) has settled into a maintained 1.x line: 1.1.0 (Jan 2026), 1.2.1 (Apr 2026), **1.4.0 (May 23 2026) added `yf.Auth` Yahoo-account login and made curl_cffi optional**, 1.5.2 (Jul 2026), **1.6.0 (Aug 13 2026, current)**. ⚠️ **Issue #2913 (Jul 21 2026) reports that yfinance's own `nospam` extra is currently broken** — `requests_cache`/`requests_ratelimiter` sessions are rejected by `YfData` and don't compose with curl_cffi (PR #2918 pending). So the library's *own recommended* caching/throttling mitigation is presently unusable. There is still **no official Yahoo API** (shut down May 15 2017) and no first-party paid tier; the "Yahoo Finance APIs" on RapidAPI are third-party resellers. Yahoo's ToS prohibits automated access without written permission.

### What this implies for your deploy plan

**Yes — make Tiingo the primary source in the cloud, and demote Yahoo to an opportunistic fallback.** For a small app on a cloud VM, yfinance failure is not a tail risk; it is an unscheduled outage of unknown duration, with no appeal channel, no support contact, and no quota you can buy your way out of. Concretely:

- Flip the source priority by environment: Tiingo primary when `ENVIRONMENT=production`, Yahoo primary locally (where it works fine and costs nothing).
- **Do your own caching layer** — do not depend on `nospam`, which is broken as of #2913. Your Parquet cache already is this layer; lean on it harder and lengthen its TTL in production.
- Batch through `yf.download()` rather than per-ticker `.info` calls, and use exponential backoff.
- **Never let a Yahoo 429 fail a user-facing request** — fall through to Tiingo silently and log.
- This is also the strongest argument against DO App Platform: an ephemeral filesystem means a full cache re-download on every deploy, i.e. a burst of exactly the request pattern that gets you rate-limited.

**Tiingo and FRED are safe.** Both are token/API-key authenticated with per-key quotas (Tiingo ~2,400 req/hr on the free tier; FRED ~120 req/min), so the rate-limit bucket follows your key rather than your egress IP. No reports of datacenter-IP restrictions on either, and no such clause in their terms. Keep the Tiingo key in a platform secret, not in the image.

---

## References

**Fly.io**
- https://fly.io/docs/about/pricing/
- https://fly.io/docs/about/free-trial/
- https://fly.io/docs/about/billing/
- https://fly.io/docs/volumes/overview/
- https://fly.io/docs/launch/autostop-autostart/
- https://fly.io/docs/launch/deploy/
- https://fly.io/docs/reference/regions/
- https://fly.io/pricing/
- https://status.flyio.net/
- https://kuberns.com/blogs/is-fly-io-good-for-production/
- https://community.fly.io/t/using-sqlite-from-persistent-volume-for-django-application/16206
- https://fly.io/docs/rails/advanced-guides/sqlite3/

**Railway**
- https://railway.com/pricing
- https://docs.railway.com/reference/pricing/plans
- https://docs.railway.com/reference/volumes
- https://docs.railway.com/reference/app-sleeping
- https://docs.railway.com/reference/regions
- https://station.railway.com/feedback/regions-for-hobby-plan-users-6e6d418d

**Render**
- https://render.com/pricing
- https://render.com/docs/free
- https://render.com/docs/disks
- https://render.com/docs/new-workspace-plans
- https://render.com/docs/platform-features-by-plan
- https://render.com/docs/compute-plans
- https://render.com/docs/regions
- https://render.com/docs/faq
- https://render.com/changelog/updated-plans-for-render-workspaces
- https://render.com/blog/better-pricing-for-fast-growing-teams

**Hetzner**
- https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/
- https://northflank.com/blog/hetzner-cloud-server-price-increases
- https://www.hetzner.com/cloud/
- https://www.hetzner.com/cloud/regular-performance/
- https://www.hetzner.com/cloud/cost-optimized/
- https://docs.hetzner.com/cloud/general/locations/
- https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/
- https://costgoat.com/pricing/hetzner
- https://agentxcloud.com/news/hetzner-cloud-instance-availability-status-may-2026
- https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do
- https://webhosting.today/2026/05/29/hetzner-has-now-raised-prices-three-times-in-2026-this-one-is-different/

**DigitalOcean**
- https://www.digitalocean.com/pricing/droplets
- https://www.digitalocean.com/pricing/app-platform
- https://docs.digitalocean.com/products/app-platform/details/limits/
- https://docs.digitalocean.com/products/volumes/details/pricing/
- https://docs.digitalocean.com/platform/regional-availability/

**PythonAnywhere**
- https://www.pythonanywhere.com/pricing/
- https://blog.pythonanywhere.com/222/
- https://www.pythonanywhere.com/forums/topic/1847/
- https://www.pythonanywhere.com/forums/topic/11858/
- https://www.pythonanywhere.com/forums/topic/986/

**Newer entrants**
- https://sevalla.com/application-hosting/pricing/
- https://docs.sevalla.com/applications/storage
- https://zeabur.com/changelogs/new-subscription-plans
- https://temps.sh/blog/coolify-pricing-explained-2026

**Yahoo Finance / data sources**
- https://www.pythonanywhere.com/forums/topic/35201/
- https://discuss.streamlit.io/t/yfratelimiterror-too-many-requests-rate-limited-try-after-a-while/111207
- https://github.com/ranaroussi/yfinance/discussions/2431
- https://github.com/ranaroussi/yfinance/discussions/2581
- https://github.com/ranaroussi/yfinance/issues/2658
- https://github.com/ranaroussi/yfinance/issues/2913
- https://github.com/ranaroussi/yfinance/issues/2422
- https://github.com/ranaroussi/yfinance/issues/2496
- https://github.com/ranaroussi/yfinance/pull/2434
- https://github.com/ranaroussi/yfinance/blob/main/CHANGELOG.rst
- https://github.com/ranaroussi/yfinance/releases
- https://pypi.org/project/yfinance/
- https://scrapfly.io/blog/posts/guide-to-yahoo-finance-api
- https://deepcharts.substack.com/p/why-did-the-yfinance-python-library
- https://www.tiingo.com/documentation/
- https://fred.stlouisfed.org/docs/api/terms_of_use.html
- https://blog.pecar.me/django-sqlite-dblock/

**Coverage caveats:** Render's main `/pricing` page renders its tables client-side and could not be parsed directly; the $7 Starter / $25 Standard / $0.25-per-GB-disk figures are corroborated across Render's own docs and articles plus multiple third-party trackers, and Render's `new-workspace-plans` doc confirms *"Compute pricing is not changing at this time."* Hetzner's live pricing tables likewise render client-side; EUR figures come from Hetzner's official June-2026 price-adjustment doc cross-checked against Northflank's breakdown and the CostGoat calculator — note that the Better Stack review reflects **April 2026** pricing and is stale relative to the June increase. Reddit and Hacker News returned only SEO chaff on the Yahoo question, so there are no community-sourced provider rankings; the FRED rate-limit figure comes from the `fredr` package docs, as FRED's own terms page returns 403 to automated fetches.
