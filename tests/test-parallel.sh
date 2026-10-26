#!/usr/bin/env bash
# Self-test for the parallel session runner. No Claude, no network: it uses --dry-run, a private tmux socket,
# and a throwaway lab directory. Skips (exit 0) when tmux is missing.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v tmux >/dev/null 2>&1 || { echo "test-parallel: tmux not installed, skipping"; exit 0; }

tmp="$(mktemp -d)"
sock="lab-test-$$"
cleanup() { tmux -L "$sock" kill-server 2>/dev/null; rm -rf "$tmp"; }
trap cleanup EXIT

export HOME="$tmp/home"; mkdir -p "$HOME"
export LAB_DIR="$tmp/lab" LAB_CFG="$tmp/cfg" LAB_TMUX_SOCKET="$sock" LAB_MAX_SESSIONS=9
mkdir -p "$LAB_DIR"
cp -R "$here/parallel/." "$LAB_DIR/"
# The parallel module finds the shared authorship hooks next to the lab directory.
mkdir -p "$tmp/hooks"; cp "$here"/hooks/* "$tmp/hooks/"
export LAB_HOOKS_DIR="$tmp/hooks"
runner="$LAB_DIR/bin/claude-lab-sessions"

pass=0; fail=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; fail=$((fail + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

printf 'dummy prompt\n' > "$tmp/prompt.md"
mkdir -p "$tmp/wt"
check "count starts at 0" '[ "$("$runner" count)" = 0 ]'
check "bad names are refused" '! "$runner" start "Bad Name" "$tmp/wt" "$tmp/prompt.md" --dry-run >/dev/null 2>&1'
check "a dry-run start works" '"$runner" start t1 "$tmp/wt" "$tmp/prompt.md" --dry-run | grep -q "started rt-t1 model=sonnet kind=work"'
check "review kind routes to opus" '"$runner" start t2 "$tmp/wt" "$tmp/prompt.md" --kind review --dry-run | grep -q "model=opus kind=review"'
check "duplicates are refused" '! "$runner" start t1 "$tmp/wt" "$tmp/prompt.md" --dry-run >/dev/null 2>&1'
check "count sees two sessions" '[ "$("$runner" count)" = 2 ]'
listing="$("$runner" list)"
check "list shows them" 'printf "%s\n" "$listing" | grep -q "rt-t1"'
check "the 4-session cap holds even when LAB_MAX_SESSIONS=9" '
  "$runner" start t3 "$tmp/wt" "$tmp/prompt.md" --dry-run >/dev/null &&
  "$runner" start t4 "$tmp/wt" "$tmp/prompt.md" --dry-run >/dev/null &&
  ! "$runner" start t5 "$tmp/wt" "$tmp/prompt.md" --dry-run >/dev/null 2>&1'
check "settings keep the safety rules" '
  grep -q "gh pr merge" "$LAB_CFG/settings.json" && grep -q "git push --force" "$LAB_CFG/settings.json" && grep -q "acceptEdits" "$LAB_CFG/settings.json"'
check "lab git config uses the shared authorship hooks" '[ "$(git config --file "$LAB_CFG/gitconfig" core.hooksPath)" = "$LAB_HOOKS_DIR" ]'
check "lab git identity is the single allowed author" '[ "$(git config --file "$LAB_CFG/gitconfig" user.email)" = "mahimn.patel.k@gmail.com" ]'
check "kill removes only the named session" '"$runner" kill t1 >/dev/null && [ "$("$runner" count)" = 3 ]'
check "sessions outside the prefix are never listed" '
  tmux -L "$sock" new-session -d -s other-session "sleep 30" && [ -z "$("$runner" list | grep other-session)" ]'

echo "test-parallel: $pass passed, $fail failed"
[ "$fail" = 0 ]
