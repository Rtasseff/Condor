# Branch handoff docs

One file per worktree branch, `<slug>.md`, created by
`scripts/new-worktree.sh` from [_template.md](_template.md) and committed
**on that branch**. It is the brief a fresh agent session reads first when
opened in the branch's worktree directory under `~/projects/condor-dev/`.

When a branch merges, its handoff doc lands here as a record — mark it
*Merged YYYY-MM-DD* at the top rather than deleting it.

Conventions, registry of active worktrees, review policy, and lifecycle:
[../WORKTREES.md](../WORKTREES.md).

Currently on branches (not yet on `main`):

- `forecast-anchors.md` — `feature/forecast-anchors`, created 2026-09-02.
  Forecaster rung C: expected-return anchor control + posterior blend.
- `home-builder.md` — `feature/home-builder`, created 2026-09-02.
  Friendly Build home page, Optimize rename, draft portfolio thread.
