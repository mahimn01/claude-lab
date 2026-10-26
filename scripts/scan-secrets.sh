#!/usr/bin/env bash
# Rough scan of the tracked files for things that should not be published: tokens, private keys,
# foreign email addresses, phone numbers, and IP addresses. Run it before every push.
#   scripts/scan-secrets.sh            scan files tracked by git (or all files if this is not a repo)
# Exit 0 when nothing is found, 1 when there are hits to look at. It is a safety net, not a guarantee.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
ALLOWED_EMAIL="${LAB_AUTHOR_EMAIL:-mahimn.patel.k@gmail.com}"
self="scripts/scan-secrets.sh"
if git rev-parse --git-dir >/dev/null 2>&1 && [ -n "$(git ls-files)" ]; then
  mapfile -t files < <(git ls-files | grep -vxF "$self")
else
  mapfile -t files < <(find . -type f -not -path './.git/*' | sed 's|^\./||' | grep -vxF "$self")
fi
rc=0
scan() {  # scan <label> <regex> [ignore-regex: lines matching it are known false positives]
  local out
  out="$(grep -InEi -e "$2" -- "${files[@]}" 2>/dev/null || true)"
  if [ -n "$out" ] && [ -n "${3:-}" ]; then out="$(printf '%s\n' "$out" | grep -vE -e "$3" || true)"; fi
  if [ -n "$out" ]; then echo "== $1"; echo "$out"; rc=1; fi
}
scan "token prefixes"  '(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})'
scan "private keys"    '-----BEGIN [A-Z ]*PRIVATE KEY-----'
scan "bearer tokens"   'bearer[[:space:]]+[A-Za-z0-9._~+/=-]{16,}'
scan "assigned credentials" '(password|passwd|secret|api[_-]?key)[[:space:]]*[:=][[:space:]]*["'\'']?[^[:space:]"'\'']{6,}' \
  '^bin/lab\.py:[0-9]+:SECRET = re\.compile\('
scan "phone numbers"   '(\+?[0-9]{1,2}[ .-])?\(?[0-9]{3}\)?[ .-][0-9]{3}[ .-][0-9]{4}'
scan "IPv4 addresses"  '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' '(^|[^0-9.])127\.0\.0\.1([^0-9]|$)'  # the loopback address is not a secret
out="$(grep -InEoi -e '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- "${files[@]}" 2>/dev/null | grep -viF "$ALLOWED_EMAIL" | grep -viE '@example\.(com|org)$' || true)"
if [ -n "$out" ]; then echo "== email addresses other than $ALLOWED_EMAIL"; echo "$out"; rc=1; fi
[ "$rc" = 0 ] && echo "scan-secrets: no hits in ${#files[@]} files"
exit "$rc"
