#!/usr/bin/env bash
# Install the commit-msg and pre-push hooks into a repository, using that repository's LOCAL git config.
#   scripts/install-hooks.sh [repo_dir]      (default: the current directory)
# This sets core.hooksPath in that repo to this project's hooks/ folder. It does not touch your global config.
# If the repo already has its own hooks path, the script stops and tells you.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${1:-.}"
git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || { echo "install-hooks: not a git repo: $repo" >&2; exit 2; }
current="$(git -C "$repo" config --local --get core.hooksPath || true)"
if [ -n "$current" ] && [ "$current" != "$here/hooks" ]; then
  echo "install-hooks: $repo already uses core.hooksPath=$current. Call $here/scripts/check-authorship.sh from those hooks instead." >&2
  exit 1
fi
chmod +x "$here"/hooks/* "$here"/scripts/check-authorship.sh
git -C "$repo" config --local core.hooksPath "$here/hooks"
echo "install-hooks: $repo now runs the commit-msg and pre-push checks from $here/hooks"
