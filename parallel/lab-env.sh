#!/usr/bin/env bash
# Environment for the parallel session runner (claude-lab-sessions). Source this file; do not execute it.
# It is sourced by launch.sh, by bin/claude-lab-sessions, and inside every session.
#
# Settings come from the environment first, then from $LAB_DIR/.env, then from the defaults below.
# .env is read as plain KEY=VALUE lines. It is never executed.

if [ -z "${LAB_DIR:-}" ]; then
  LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
export LAB_DIR

_lab_load_env() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" =~ ^[A-Z_][A-Z0-9_]*= ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    # Values already in the environment win over .env.
    if [ -z "${!key+x}" ]; then
      export "$key=$val"
    fi
  done < "$file"
}
_lab_load_env "$LAB_DIR/.env"
unset -f _lab_load_env

# The authorship hooks live at the top of this repository (../hooks); worktrees use them via the lab git config.
export LAB_HOOKS_DIR="${LAB_HOOKS_DIR:-$(cd "$LAB_DIR/.." && pwd)/hooks}"
export LAB_REPO_URL="${LAB_REPO_URL:-}"
export LAB_REPO_DIR="${LAB_REPO_DIR:-$LAB_DIR/repo}"
export LAB_MAX_SESSIONS="${LAB_MAX_SESSIONS:-4}"
export LAB_SESSION_PREFIX="${LAB_SESSION_PREFIX:-rt-}"
export LAB_BRANCH_PREFIX="${LAB_BRANCH_PREFIX:-lab/}"
export LAB_BASE_BRANCH="${LAB_BASE_BRANCH:-main}"
export LAB_MODEL_WORK="${LAB_MODEL_WORK:-sonnet}"
export LAB_MODEL_REVIEW="${LAB_MODEL_REVIEW:-opus}"
export LAB_CLAUDE_CMD="${LAB_CLAUDE_CMD:-claude}"
export LAB_TEST_CMD="${LAB_TEST_CMD:-run the documented test command of this project}"
export LAB_PROTECTED_SESSIONS="${LAB_PROTECTED_SESSIONS:-}"
export LAB_AUTHOR_NAME="${LAB_AUTHOR_NAME:-Mahimn Patel}"
export LAB_AUTHOR_EMAIL="${LAB_AUTHOR_EMAIL:-mahimn.patel.k@gmail.com}"
export LAB_PREACCEPT_TRUST="${LAB_PREACCEPT_TRUST:-1}"
export LAB_CFG="${LAB_CFG:-$HOME/.config/claude-lab}"

# One git identity for everything the lab does. A dedicated git config is used for lab sessions only,
# so your normal global git config is not changed.
mkdir -p "$LAB_CFG"
export GIT_CONFIG_GLOBAL="$LAB_CFG/gitconfig"
export GIT_AUTHOR_NAME="$LAB_AUTHOR_NAME" GIT_AUTHOR_EMAIL="$LAB_AUTHOR_EMAIL"
export GIT_COMMITTER_NAME="$LAB_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$LAB_AUTHOR_EMAIL"
# The pre-push hook uses this to refuse pushes to the base branch and non-fast-forward pushes.
export LAB_PROTECT_BASE=1

export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

case ":$PATH:" in
  *":$LAB_DIR/bin:"*) ;;
  *) export PATH="$LAB_DIR/bin:$HOME/.local/bin:$PATH" ;;
esac

# Per-session temp dir. Concurrent test runs can collide in a shared /tmp.
_lab_sess="$(tmux display-message -p '#S' 2>/dev/null || echo shared)"
export TMPDIR="$LAB_DIR/tmp/$_lab_sess"
mkdir -p "$TMPDIR"
unset _lab_sess
