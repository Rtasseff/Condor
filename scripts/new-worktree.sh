#!/bin/bash
# ============================================================================
# Condor Funds v2 - Create a git worktree for a new bucket of work
# ============================================================================
# Usage (from the main checkout, clean tree):
#   scripts/new-worktree.sh <slug> [branch-name] [base-ref]
#
#   slug         directory name under $WT_ROOT and the handoff doc name
#                (docs/handoffs/<slug>.md). Lowercase, hyphens.
#   branch-name  default: feature/<slug>. If the branch already exists it is
#                checked out as-is (base-ref ignored); otherwise it is created
#                from base-ref.
#   base-ref     default: main.
#
# What it does:
#   1. git worktree add  $WT_ROOT/<slug>  <branch>
#   2. copies web/db.sqlite3 and .condor_cache/ from this checkout
#      (per-worktree, gitignored). NEVER copies drive_export/.
#   3. python3 -m venv .venv + pip install -r requirements.txt
#   4. seeds docs/handoffs/<slug>.md from docs/handoffs/_template.md
#      if the branch doesn't already have one
#   5. web/manage.py check
#
# Full conventions: docs/WORKTREES.md
# ============================================================================
set -euo pipefail

SLUG="${1:-}"
BRANCH="${2:-}"
BASE_REF="${3:-main}"
WT_ROOT="${WT_ROOT:-$HOME/projects/condor-dev}"

usage() { sed -n '2,26p' "$0"; exit 1; }
[[ -z "$SLUG" ]] && usage
[[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "ERROR: slug must be lowercase letters/digits/hyphens: '$SLUG'"; exit 1; }
[[ -z "$BRANCH" ]] && BRANCH="feature/$SLUG"

MAIN_DIR="$(git rev-parse --show-toplevel)"
DEST="$WT_ROOT/$SLUG"
TEMPLATE="$MAIN_DIR/docs/handoffs/_template.md"

cd "$MAIN_DIR"
[[ -e "$DEST" ]] && { echo "ERROR: $DEST already exists"; exit 1; }
[[ -f "$TEMPLATE" ]] || { echo "ERROR: missing $TEMPLATE"; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
  echo "WARNING: main checkout has uncommitted changes; the new branch is cut from '$BASE_REF', not the working tree."
fi

echo "==> Fetching origin"
git fetch origin --prune --quiet || echo "WARNING: fetch failed (offline?); continuing with local refs"

mkdir -p "$WT_ROOT"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "==> Branch $BRANCH exists; adding worktree at $DEST"
  git worktree add "$DEST" "$BRANCH"
elif git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  echo "==> Branch $BRANCH exists on origin; tracking it at $DEST"
  git worktree add --track -b "$BRANCH" "$DEST" "origin/$BRANCH"
else
  echo "==> Creating $BRANCH from $BASE_REF at $DEST"
  git worktree add -b "$BRANCH" "$DEST" "$BASE_REF"
fi
BASE_SHA="$(git -C "$DEST" rev-parse --short HEAD)"

echo "==> Copying per-worktree files (web/db.sqlite3, .condor_cache/) — never drive_export/"
[[ -f web/db.sqlite3 ]]  && cp web/db.sqlite3 "$DEST/web/db.sqlite3"  || echo "    (no web/db.sqlite3 to copy — run migrate + createsuperuser in the worktree)"
[[ -d .condor_cache ]]   && cp -r .condor_cache "$DEST/.condor_cache" || echo "    (no .condor_cache/ to copy — first analyze will download prices)"

echo "==> Creating .venv and installing requirements (this takes a minute)"
PY3="$(command -v python3 || true)"
[[ -z "$PY3" && -x "$MAIN_DIR/.venv/bin/python" ]] && PY3="$MAIN_DIR/.venv/bin/python"
[[ -z "$PY3" ]] && { echo "ERROR: no python3 found"; exit 1; }
"$PY3" -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --quiet --upgrade pip
"$DEST/.venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

# Port: 8000 is main; give each additional worktree the next number.
N_WT="$(git worktree list --porcelain | grep -c '^worktree ')"   # includes main + this one
PORT=$((8000 + N_WT - 1))

HANDOFF="$DEST/docs/handoffs/$SLUG.md"
if [[ -f "$HANDOFF" ]]; then
  echo "==> Handoff doc already on branch: docs/handoffs/$SLUG.md (left untouched)"
else
  echo "==> Seeding docs/handoffs/$SLUG.md from template"
  mkdir -p "$DEST/docs/handoffs"
  sed -e "s|{{SLUG}}|$SLUG|g" \
      -e "s|{{BRANCH}}|$BRANCH|g" \
      -e "s|{{DIR}}|$DEST|g" \
      -e "s|{{BASE_REF}}|$BASE_REF|g" \
      -e "s|{{BASE_SHA}}|$BASE_SHA|g" \
      -e "s|{{DATE}}|$(date +%Y-%m-%d)|g" \
      -e "s|{{PORT}}|$PORT|g" \
      "$TEMPLATE" > "$HANDOFF"
fi

echo "==> manage.py check"
( cd "$DEST" && ./.venv/bin/python web/manage.py check )

cat <<DONE

Done.
  Worktree : $DEST
  Branch   : $BRANCH  (base $BASE_REF @ $BASE_SHA)
  Port     : $PORT
  Handoff  : $HANDOFF

Next (handoff session):
  1. Fill in the handoff doc, then commit it ON THE BRANCH:
       cd $DEST && git add docs/handoffs/$SLUG.md && git commit -m "Handoff: $SLUG"
  2. Add a row to the registry in docs/WORKTREES.md and commit on main.
  3. Open a new agent session in $DEST and /model down (Sonnet first).
DONE
