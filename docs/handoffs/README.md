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
