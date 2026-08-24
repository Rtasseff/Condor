# Where things stand — RT's review guide

*Written 2026-08-23 at `main` ≈ `ae363bb`+deploy-prep. Read this when
you're back; it is the map of what shipped while you were remote, what
to click through, which of my calls you should ratify or overturn, and
what happens next. Everything below is pushed, tested (198 core + 41
Django), and was verified live in Chrome before each push.*

## 1. What shipped, in one table

| Area | What it does now | Commit(s) |
|---|---|---|
| Chart UX (your review round 1) | Key/legend instead of chasing labels; "Your portfolio" rename; teal "Considering" ring; point card directly under the chart; click-anywhere snapping | `527e80e` |
| Capital allocation line | Clickable two-fund mixes (T-bills + tangency); borrowing region flagged with a warning; `Frontier.cal_mix()` engine | `527e80e` |
| Accounts & login | Django auth; styled /login; per-user Saved lists; share links readable team-wide, owner-only edits; /admin for user management | `7c8a7d7` |
| Forecaster rung A | Closed-form "steady rates" fan; two band sets (market randomness vs + estimate error); μ error bar printed as a sentence | `89255c9` |
| Account view (ADR 0004) | Ledger (deposits/trades/forces) → value at last close, TWR (deposits ≠ return), drift vs setpoint, whole-share rebalancing plans, "Use as account setpoint" from any frontier/CAL point | `dacb430` |
| DCA contributions | Schedule (amount + cadence), due dot on the nav + login banner, buys-only whole-share contribution routing, confirm advances the schedule from the due date | `43b151e` |
| Whole-account forecast | Complete portfolio: holdings + cash share at the live T-bill rate, in dollars from current value | `43b151e` |
| Forecaster rung B | "Resampled history" (stationary 21-day block bootstrap), guard-railed to never show narrower bands than model 1 — and the guard fires on real 2016-26 data | `ae363bb` |
| Deploy prep | Env-driven settings (CONDOR_*), whitenoise, gunicorn, Dockerfile (built + smoke-tested both arches 2026-08-24), UTC pinned, security headers; see docs/DEPLOY.md | `e0c9dae`+ |
| Research | 3 forecasting reports + 7-page summary PDF + hosting report in `docs/research/`; ADRs 0001–0004 in `docs/decisions/` | several |

## 2. Getting running after you pull

```bash
git pull
source .venv/bin/activate
python web/manage.py migrate           # new tables: auth, accounts, DCA
python web/manage.py createsuperuser   # once — the app now requires login
python web/manage.py runserver
```

Add teammates later at `/admin` → Users → Add. No new pip installs are
required for local dev (whitenoise/gunicorn are in requirements.txt but
only matter in production).

## 3. Suggested walkthrough (15 minutes, in order)

1. **Login** — sign in; note your name + Log out in the topbar, and the
   nav is real now (Build / My account).
2. **Build page** — hit Analyze. Check the key above the chart (no
   labels chase markers). Click *anywhere* near the frontier: nearest
   point lights up with the teal ring; details land directly under the
   chart. Click the dashed CAL line low (T-bills mix), then past the
   tangent (borrowing warning). Click the T-bills dot itself.
3. **Adopt & save** — "Make this my portfolio" on a frontier point;
   Save it; open the share link.
4. **Send a draft to the account** — select a CAL point ~60% risky →
   "Use as account setpoint →". You land on the transition report:
   whole shares at last close, editable, cash share preserved. Confirm.
5. **My account** — tiles (value / contributions / gain / TWR), value
   chart, drift columns. Add a deposit in the Ledger; watch value move
   but Return stay put — that's the whole ADR-0004 point.
6. **Rebalancing plan** — drift will be small day 1; still click it to
   see the mechanics.
7. **DCA** — set a schedule with a past due date; see the nav dot +
   banner; "Where should it go?"; confirm; watch next-due advance.
8. **Forecasts** — on Build and on My account: model 1 vs model 2,
   the badge, the μ ± sentence, and (model 2, most mixes) the guard
   note about widened bands.
9. **CLI sanity** — `python -m condor analyze MSFT NEE CVX` still
   works with zero web stack.

## 4. Calls I made that you should ratify (or overturn)

Each is reversible; none is load-bearing beyond its feature.

- **Draft targets are COPIED, not linked** — adopting a draft/CAL point
  copies weights into the account setpoint; later edits to the saved
  portfolio don't silently move your account (ADR 0004).
- **Share pages require login** — `/p/<uuid>` is readable by any
  logged-in teammate, not the public internet. The 5-user release has
  accounts, so link-only access felt wrong to keep.
- **Buys require ledger cash** — recording a buy without the cash is
  rejected ("record a deposit first"), keeping contributions honest;
  `set_shares` / `set_cash` are the escape hatches for forcing reality.
- **One account per user in the UI** — the schema allows many; a
  selector is cheap when you want play + real side by side.
- **DCA plan may deploy idle cash** — a contribution plan spends the
  new money *plus* any cash above the setpoint's reserve. Arguably it
  should touch only the new money; easy to flip.
- **Rebalance rounding** — nearest whole share, then trim the cheapest
  buys until cash ≥ 0 (minimizes idle cash). DCA variant: buys only,
  largest dollar deficit first, never buy unless more than half a
  share short.
- **Bootstrap block = 21 days, fixed** — auto-selection degenerates on
  return series (research); disclosed in the UI badge instead.
- **Guard-rail semantics** — model 2's bands are always floored at
  model 1's, and the UI says so only when the narrowing was material
  (>5% of final log-width).
- **Weekend/after-close ledger events** value against the last known
  close (fixed live; regression-tested).

## 5. Known gaps & quirks (deliberate, not forgotten)

- No dividends/splits at the *account* level — ledger kinds for Later
  (price statistics already use adjusted closes; ADR 0004 "reopens if").
- No password-reset email — admin resets passwords at /admin (fine for
  5 friends; noted in DEPLOY.md).
- All-cash accounts can't forecast (trivially rf growth; the API says
  so rather than drawing a flat cone).
- Contribution due-check compares dates in UTC — a user in Asia may see
  the reminder a few hours "early". Harmless at this scale.
- Ticker autocomplete list is a static bundled file; quick-add row is
  hardcoded.
- The forecast backtest view (project-from-2-years-ago) and the
  offline coverage notebook are still queued (rung C item).

## 6. What's next, in order

1. **Your review** — walk §3, add notes to BACKLOG (round 1 items all
   landed same-day; keep them coming).
2. **Forecaster rung C** — *green-lit by you 2026-08-23* ("completely
   on board"): the expected-return anchor control (Historical /
   long-run anchor / custom), Black-Litterman underneath, CAPE/
   Damodaran ERP as anchor sources. I can build this next session.
3. **Branding pass** — token values + two SVGs, per docs/BRANDING.md.
4. **Deploy the 5-user test** — decision + runbook in docs/DEPLOY.md
   (hosting research included). Code prep is already merged; the main
   thing only you can do is pick the host, buy the Tiingo key (free
   tier), and rotate the old exposed Polygon key before anything
   becomes more public.

## 7. Where everything is written down

- `ARCHITECTURE.md` — layering; engines now include forecast + accounting
- `docs/decisions/0001–0004` — seam check, flat files, no build step,
  account-as-ledger
- `docs/research/` — forecasting ladder / validation / data sources +
  the 7-page summary PDF you read + hosting report
- `docs/CLI.md`, `docs/BRANDING.md`, `docs/DEPLOY.md`
- `BACKLOG.md` — Now / Next / Later / Done, all current
