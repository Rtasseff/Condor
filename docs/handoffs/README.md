# Branch handoff docs

One file per worktree branch, `<slug>.md`, created by
`scripts/new-worktree.sh` from [_template.md](_template.md) and committed
**on that branch**. It is the brief a fresh agent session reads first when
opened in the branch's worktree directory under `~/projects/condor-dev/`.

When a branch merges, its handoff doc lands here as a record — mark it
*Merged YYYY-MM-DD* at the top rather than deleting it.

Conventions, registry of active worktrees, review policy, and lifecycle:
[../WORKTREES.md](../WORKTREES.md).

Merged (kept as records):

- `forecast-anchors.md` — `feature/forecast-anchors`, merged 2026-09-02
  (PR #1): Forecaster rung C, expected-return anchor + posterior blend.
- `home-builder.md` — `feature/home-builder`, merged 2026-09-02:
  friendly Build home at `/`, Optimize rename, DraftPortfolio thread.
- `flow-clarity.md` — `feature/flow-clarity`, merged 2026-09-05:
  Explore/Real worlds, account bridges, gating, sources, honest labels,
  Advanced priors.
- `ledger-mirror.md` — `feature/ledger-mirror`, merged 2026-10-24:
  ledger v2 (cost basis, income/fees, currency, bills) and read-only
  mirror import (ADR 0005).
- `stats-honesty.md` — `feature/stats-honesty`, merged 2026-11-01:
  expected return = T-bill + premium, constant-correlation shrinkage,
  portfolio history, CLI meta (ADR 0006).
- `account-plans.md` — `feature/account-plans`, merged 2026-11-01:
  pay-in tracker, rule alerts, XIRR, combined total; format v1.1
  (ADR 0007).
- `assumptions-1.md` — `feature/assumptions-1`, merged 2026-11-01:
  constraints, equilibrium prior, distance from best, side-by-side view
  (ADR 0008).
- `broker-reconcile.md` — `feature/broker-reconcile`, merged 2026-11-01:
  check a mirror account against the broker, to the cent.
- `scenarios.md` — `feature/scenarios`, merged 2026-11-01: stress-period
  returns and tangency stability bands.
