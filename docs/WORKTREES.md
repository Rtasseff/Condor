# Worktrees & handoffs — running parallel agent sessions

> **Development document.** Worktrees are a laptop-side device; production is
> the Fly.io machine, which only ever runs what `main` contained at the last
> `fly deploy` from the main checkout. No worktree ever deploys.

How we organise parallel work on this repo (pattern imported from
ReDIB-Portal): one **handoff session** sits on `main` in the primary
checkout and coordinates — design, briefs, review, merge, deploy. Each
large bucket of work gets its own branch **and its own directory** via
`git worktree`, with a dedicated agent session working in it. The human
relays between sessions.

## Layout

```
~/projects/condor_v2/            ← main checkout, handoff session lives here
~/projects/condor-dev/           ← one sub-dir per active branch
    <slug>/                      ← feature/<slug>, created by scripts/new-worktree.sh
```

Siblings under one dedicated parent, not nested inside the repo: nesting a
second checkout under `condor_v2/` makes grep, IDE indexing and Docker
build context double-hit; loose siblings clutter `~/projects`.

## What a worktree does and doesn't share

Shared (one `.git` object store): commits, branches, remotes, stashes.
**Not shared** (gitignored, per-checkout): `.venv/`, `web/db.sqlite3`,
`.condor_cache/`, `staticfiles/`, `.claude/`. `scripts/new-worktree.sh`
copies or creates these so a fresh worktree is runnable immediately.

**`drive_export/` is never copied and never needed in a worktree** — it
holds credentials and personal data; branch work has no business touching
it (same rule as CLAUDE.md: never commit it).

Rules that follow from the sharing model:

- A branch can be checked out in **only one** worktree at a time. Never
  `git checkout <other-branch>` inside a worktree dir — that dir *is* that
  branch. Switch dirs instead.
- `git worktree list` from any checkout shows every active worktree.
- Each worktree gets its own **runserver port** when running concurrently:
  `main` = 8000, then 8001, 8002, … in creation order (registry below).
- Claude Code auto-memory is keyed by directory, so a session started in a
  worktree begins with **no** project memory. The handoff doc is the
  intended context carrier — write it so a fresh session needs nothing
  else beyond `CLAUDE.md`, `ARCHITECTURE.md` and `docs/`.

## When to use a worktree at all

Not every task needs one. The handoff/worktree cycle costs a brief, a
bootstrap, and a review; it pays off when the implementation is a real
chunk of work that a fresh, cheaper session can run with.

- **Inline on `main`, in the handoff session:** backlog edits, docs/copy
  tweaks, one- or two-file fixes, anything under ~an hour.
- **Worktree bucket:** multi-file features, anything with a migration,
  anything that will take a session hours, or work you want to hand to a
  different model. One bucket = one coherent deliverable (it can have
  phases inside).

## Model split (why the briefs are as detailed as they are)

Design and the handoff brief happen on the top-tier model (Fable) in the
handoff session; **branch sessions run on a cheaper model** — Sonnet
first, Opus if it struggles — switch with `/model` after opening the
session in the worktree. The brief is what makes that safe: it fixes the
decisions so the implementer never has to re-derive them. If a cheaper
implementer struggles, tighten the brief before reaching for a bigger
model.

## Review policy (proportionate — never pay twice)

The branch agent already ran the suites and kept its handoff Status
current; the human usually did a click-through. The handoff-session review
adds **one** layer matched to risk, not two:

| Change | Review |
|---|---|
| Docs, copy, small UI | Read the diff; run the suites. No automated review. |
| Ordinary features | Run the suites; targeted read of the risky files. |
| Engine numerics (anything that computes money, returns, bands, or plans), auth/permission changes, migrations touching account/ledger tables, deploy config (`Dockerfile`, `fly.toml`, `web/config/settings.py`) | **One** `/code-review` at *medium*, ideally run **by the branch session on its own branch before opening the PR** so findings and fixes land in the PR. The handoff session then reads only what was flagged plus the money-math paths. |

Always, before merge (the branch records these as its baseline before
starting and must not make them worse):

```bash
source .venv/bin/activate
python -m pytest tests/                      # core engine suite
python web/manage.py test explorer           # Django suite
python web/manage.py check
python web/manage.py makemigrations --check --dry-run
```

Condor's standing verification culture applies on branches exactly as on
`main` (CLAUDE.md): engine changes need a verification-style test
(closed form / hand case / legacy agreement); model changes need an
"equals the engine" test.

Never run a manual full-diff read **and** an automated review on the same
PR — pick one. A completed human click-through counts as evidence; lean
lighter, not heavier, when it has been done.

### Cost control when fanning out subagents

Subagents start with a fresh, narrow context, which often makes a focused
subagent *cheaper* than the same read inline. What costs is the
combination: top-tier model × high effort × unbounded scope × several at
once. Set the knobs deliberately:

- **Model and effort explicit, not inherited** — Sonnet/Haiku at
  low/medium handles "check X in file Y".
- **One narrow question per agent, naming the files.**
- **Bounded count and scope** — a handful of targeted agents, not a dozen
  open-ended ones.
- **Not stacked on top of a full manual read** — one layer, per the table.

## Creating a bucket

From the `main` checkout, on a clean tree:

```bash
scripts/new-worktree.sh <slug> [branch-name] [base-ref]
#   slug        dir name under ~/projects/condor-dev/ (also the handoff doc name)
#   branch-name default feature/<slug>; an existing branch is checked out as-is
#   base-ref    default main; used only when the branch doesn't exist yet
```

The script: creates the worktree (and branch), copies `web/db.sqlite3`
and `.condor_cache/` (never `drive_export/`), builds `.venv` from that
branch's `requirements.txt`, seeds `docs/handoffs/<slug>.md` from
[handoffs/_template.md](handoffs/_template.md) if the branch doesn't
already have one, and runs `manage.py check`.

Then the handoff session:

1. Fills in the handoff doc (goal, scope, acceptance, watch-outs) and
   commits it **on the new branch** (`cd` into the worktree to commit).
2. Adds a row to the registry table below and commits that on `main`.
3. Tells the human the dir path; they open a new agent session there and
   `/model` down.

## Handoff doc convention

Every worktree branch carries `docs/handoffs/<slug>.md`, committed on
that branch. It is the first thing an agent in that dir should read
(`CLAUDE.md` says so). Sections are in the template; the important ones:

- **Goal / scope in / scope out** — the deliverable, precisely.
- **Status** — checklist the branch agent keeps current as it works.
- **Questions for the handoff session** — anything that needs the human
  or `main`; the branch agent should not guess on these.
- **Conflict watchlist** — files also moving on `main`; rebase early.
- **Return protocol** — push, open a PR against `main`, summarise in the
  handoff doc's Status.

After merge the doc lands on `main` under `docs/handoffs/` as a record;
mark it *Merged YYYY-MM-DD* at the top rather than deleting it.

## Merging and deploying (handoff session only)

After the proportionate review: merge the PR, then from the **main
checkout**:

```bash
git pull
python -m pytest tests/ && python web/manage.py test explorer
fly deploy          # ~10-30s downtime; migrations run on boot
```

A worktree session must never run `fly` commands at all — deploy authority
stays with the handoff session, always from `main`.

## Finishing / removing a worktree

```bash
# from the main checkout, after the branch is merged (or abandoned)
git worktree remove ~/projects/condor-dev/<slug>    # add --force if dirty
git branch -d feature/<slug>                         # -D if abandoning
git worktree prune
```

Mark the registry row merged (or remove it) in the same commit.

## Registry — active worktrees

| Dir (`~/projects/condor-dev/`) | Branch | Port | Since | Status |
|---|---|---|---|---|

| `flow-clarity/` | `feature/flow-clarity` | 8001 | 2026-09-04 | Active (brief v2, not yet started). User-testing rounds 1+2: Explore/Real worlds, account starter bridge, hypothetical forecast, gating, sources, honest labels, Advanced priors. Brief: `docs/handoffs/flow-clarity.md` on the branch. |
