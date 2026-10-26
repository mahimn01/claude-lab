#!/usr/bin/env bash
# Clone the target repository into $LAB_DIR/repo (or $LAB_REPO_DIR). Needs LAB_REPO_URL.
set -euo pipefail
LAB_DIR="${LAB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export LAB_DIR
# shellcheck source=../lab-env.sh
source "$LAB_DIR/lab-env.sh"
[ -n "$LAB_REPO_URL" ] || { echo "init-repo: set LAB_REPO_URL in .env first" >&2; exit 1; }
if git -C "$LAB_REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "init-repo: $LAB_REPO_DIR is already a git repo, nothing to do"
  exit 0
fi
git clone "$LAB_REPO_URL" "$LAB_REPO_DIR"
echo "init-repo: cloned into $LAB_REPO_DIR"
