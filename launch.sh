#!/usr/bin/env bash
# launch.sh <name> <branch|-> <prompt_file> [--set KEY=VALUE]... [--kind work|review] [--model M] [--dry-run]
#
# 1. Makes a git worktree at $LAB_DIR/worktrees/<name> on a new branch (<LAB_BRANCH_PREFIX><name> unless
#    you pass a branch), cut from origin/$LAB_BASE_BRANCH. Set LAUNCH_BASE=<ref> to stack on another branch.
# 2. Builds the session prompt: prompts/COMMON.md + your prompt file, with {{KEY}} placeholders filled in.
# 3. Starts the tmux session <LAB_SESSION_PREFIX><name> through bin/claude-lab.
#
# Built-in placeholders: {{NAME}} {{BRANCH}} {{BASE}} {{LAB_DIR}} {{REPORT_FILE}} {{TEST_CMD}}.
# Add your own with --set KEY=VALUE (for example --set TICKET=123).
set -euo pipefail

LAB_DIR="${LAB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
export LAB_DIR
# shellcheck source=lab-env.sh
source "$LAB_DIR/lab-env.sh"

usage() { echo "usage: launch.sh <name> <branch|-> <prompt_file> [--set KEY=VALUE]... [claude-lab start flags]" >&2; }
[ $# -ge 3 ] || { usage; exit 64; }
name="$1"; branch="$2"; pf="$3"
shift 3

[[ "$name" =~ ^[a-z0-9][a-z0-9_-]{0,30}$ ]] || { echo "launch: bad name '$name' (use a-z, 0-9, _ and -)" >&2; exit 64; }
if [ -z "$branch" ] || [ "$branch" = "-" ]; then branch="${LAB_BRANCH_PREFIX}${name}"; fi
[ -f "$pf" ] || { echo "launch: prompt file not found: $pf" >&2; exit 1; }

declare -a keys=() vals=() passthrough=()
while [ $# -gt 0 ]; do
  case "$1" in
    --set)
      kv="${2:?--set needs KEY=VALUE}"
      [[ "$kv" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || { echo "launch: bad --set '$kv' (want KEY=VALUE)" >&2; exit 64; }
      keys+=("${kv%%=*}"); vals+=("${kv#*=}"); shift 2 ;;
    *) passthrough+=("$1"); shift ;;
  esac
done

REPO="$LAB_REPO_DIR"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 \
  || { echo "launch: $REPO is not a git repo. Run scripts/init-repo.sh first (needs LAB_REPO_URL)." >&2; exit 1; }

# Refuse early when at the cap. bin/claude-lab checks again under a lock.
cap="$LAB_MAX_SESSIONS"; case "$cap" in ''|*[!0-9]*) cap=4 ;; esac; [ "$cap" -gt 4 ] && cap=4
[ "$("$LAB_DIR/bin/claude-lab" count)" -lt "$cap" ] || { echo "launch: at the cap ($cap sessions)" >&2; exit 1; }

wt="$LAB_DIR/worktrees/$name"
base="$LAB_BASE_BRANCH"
if [ ! -d "$wt" ]; then
  git -C "$REPO" fetch origin "$LAB_BASE_BRANCH" --quiet 2>/dev/null || true
  git -C "$REPO" rev-parse --verify -q "origin/$LAB_BASE_BRANCH" >/dev/null && base="origin/$LAB_BASE_BRANCH"
  if [ -n "${LAUNCH_BASE:-}" ]; then
    git -C "$REPO" fetch origin --quiet 2>/dev/null || true
    git -C "$REPO" rev-parse --verify -q "$LAUNCH_BASE" >/dev/null || { echo "launch: LAUNCH_BASE $LAUNCH_BASE not found" >&2; exit 1; }
    base="$LAUNCH_BASE"
  fi
  mkdir -p "$LAB_DIR/worktrees"
  git -C "$REPO" worktree add --no-track -b "$branch" "$wt" "$base"
fi

# A fresh Claude Code session stops at its first-run and folder-trust prompts. Pre-accept them for this
# worktree only. This edits ~/.claude.json. Set LAB_PREACCEPT_TRUST=0 to skip it and accept by hand.
if [ "$LAB_PREACCEPT_TRUST" = "1" ]; then
  python3 - "$wt" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude.json")
d = json.load(open(p)) if os.path.exists(p) else {}
d["hasCompletedOnboarding"] = True
d.setdefault("theme", "dark")
e = d.setdefault("projects", {}).setdefault(sys.argv[1], {})
e["hasTrustDialogAccepted"] = True
e["hasCompletedProjectOnboarding"] = True
json.dump(d, open(p, "w"), indent=2)
os.chmod(p, 0o600)
PY
fi

mkdir -p "$LAB_DIR/reports"
text="$(cat "$LAB_DIR/prompts/COMMON.md"; printf '\n\n---\n\n'; cat "$pf")"
subst() { text="${text//"{{$1}}"/"$2"}"; }
subst NAME "$name"
subst BRANCH "$branch"
subst BASE "${base#origin/}"
subst LAB_DIR "$LAB_DIR"
subst REPORT_FILE "$LAB_DIR/reports/$name.md"
subst TEST_CMD "$LAB_TEST_CMD"
for i in "${!keys[@]}"; do subst "${keys[$i]}" "${vals[$i]}"; done

combined="$LAB_DIR/prompts/.run-$name.md"
printf '%s\n' "$text" > "$combined"
if grep -Eq '\{\{[A-Za-z_]+\}\}' "$combined"; then
  echo "launch: warning: unfilled placeholders in the prompt: $(grep -Eo '\{\{[A-Za-z_]+\}\}' "$combined" | sort -u | tr '\n' ' ')" >&2
  echo "launch: pass them with --set KEY=VALUE" >&2
fi
exec "$LAB_DIR/bin/claude-lab" start "$name" "$wt" "$combined" "${passthrough[@]+"${passthrough[@]}"}"
