# Handoff — `{{BRANCH}}`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/{{SLUG}}.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `{{BRANCH}}` |
| Worktree dir | `{{DIR}}` |
| Base | `{{BASE_REF}}` @ `{{BASE_SHA}}` |
| Created | {{DATE}} |
| Runserver port | {{PORT}} |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

<!-- One paragraph: what this branch delivers and why now. -->

## Scope

**In:**
-

**Out** (do not do here — belongs on `main` or another bucket):
-

## Acceptance

<!-- How we know it's done. Tests to pass, pages to render, commands to run. -->
-

## Context & decisions already made

<!-- Links into docs/, BACKLOG items, prior decisions the branch agent must not re-open. -->
-

## Conflict watchlist

<!-- Files also changing on main; rebase early if you touch them. -->
-

## Status

<!-- Branch agent keeps this current. Checklist + short dated notes. -->
- [ ]

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
3. If this bucket touches engine numerics, auth/permissions, migrations on
   account/ledger tables, or deploy config: run **one** `/code-review` at
   *medium* on this branch before opening the PR, and land the fixes here.
4. Push the branch and open a PR against `main`. PR body = the review
   packet: what changed and why, deviations from this brief, the test
   counts vs baseline, anything user-facing quoted for review, and any
   pre-existing bug you noticed but did not fix.
5. The handoff session reviews proportionately to risk
   (`docs/WORKTREES.md` § Review policy), merges, deploys from `main`,
   and updates the registry.

## Running locally (this worktree)

```bash
cd {{DIR}}
source .venv/bin/activate
python web/manage.py runserver {{PORT}}
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
