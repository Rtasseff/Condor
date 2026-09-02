# Condor Funds v2 — agent guide

Read `ARCHITECTURE.md` before changing code under `condor/` or `web/`.
It defines the layering (engine functions → domain model → facade → view),
where new features go, and the don'ts. Follow it; if a change genuinely
needs to break it, say so explicitly and update it in the same commit.

Orientation: `README.md` (run it), `BACKLOG.md` (what's next, in order),
`context/CONTEXT.md` (history, mission, UI concept), `context/legacy/`
(2023–24 code, reference only).

**If this checkout lives under `~/projects/condor-dev/`** it is a git
worktree for one branch of work: read `docs/handoffs/<dirname>.md` FIRST —
it is your brief — and never `git checkout` another branch or run `fly`
commands here. Conventions: `docs/WORKTREES.md`.

Working rules:

- New capabilities are methods on `AssetSet` / `Portfolio` / `Frontier`
  (`condor/model.py`) with their numerics in an engine module as pure
  functions. Don't extend `compute_analysis` directly; extend the objects'
  `to_dict()` / `AssetSet.analysis()`.
- Prefer established packages (PyPortfolioOpt, cvxpy, numpy, pandas,
  statsmodels) over hand-rolled algorithms.
- `python -m pytest tests/` must pass before committing. Engine changes
  need a verification-style test (closed form / hand case / legacy
  agreement); model changes need an "equals the engine" test.
- Vocabulary: *expected return*, *dispersion*, *robust* (median/MAD/CoMAD).
- Never commit `drive_export/` (credentials, personal notes, bulk data)
  or anything from `.condor_cache/`.
- Use `.venv` (`source .venv/bin/activate`); bare `python` isn't on PATH.
