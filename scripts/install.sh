#!/usr/bin/env bash
# Put `claude-lab` (and, if you want the parallel runner, `claude-lab-sessions`) on your PATH with symlinks.
#   scripts/install.sh [--prefix DIR] [--force]       default prefix: ~/.local/bin
# Nothing outside the prefix is changed. It never edits your Claude settings.
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
prefix="$HOME/.local/bin"; force=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="${2:?--prefix needs a directory}"; shift ;;
    --force) force=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "install: unknown option $1" >&2; exit 64 ;;
  esac
  shift
done

for tool in python3 git; do
  command -v "$tool" >/dev/null 2>&1 || { echo "install: $tool is required" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "install: Python 3.10 or newer is required" >&2; exit 1; }
command -v claude >/dev/null 2>&1 || echo "install: note: 'claude' (Claude Code) is not on PATH yet; install it before launching" >&2
command -v node >/dev/null 2>&1 || echo "install: note: node is not installed; the plugin hooks and 'claude-lab route' need it" >&2

mkdir -p "$prefix"
chmod +x "$here"/bin/claude-lab "$here"/bin/lab-usage-scan "$here"/parallel/bin/* "$here"/parallel/launch.sh "$here"/parallel/scripts/*.sh
link() {
  local target="$1" name="$2" dest="$prefix/$2"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ "$(readlink -f "$dest")" = "$(readlink -f "$target")" ]; then echo "install: $dest already points here"; return; fi
    [ "$force" = 1 ] || { echo "install: $dest exists; not replacing it (use --force)" >&2; return; }
  fi
  ln -sfn "$target" "$dest.tmp.$$" && mv -T "$dest.tmp.$$" "$dest"
  echo "install: $dest -> $target"
}
link "$here/bin/claude-lab" claude-lab
link "$here/bin/lab-usage-scan" lab-usage-scan
link "$here/parallel/bin/claude-lab-sessions" claude-lab-sessions
case ":$PATH:" in *":$prefix:"*) ;; *) echo "install: add $prefix to your PATH" ;; esac
echo "install: done. Next: claude-lab doctor && claude-lab --dry-run"
