#!/usr/bin/env bash
# check-authorship.sh: fail unless every commit is authored and committed by the one allowed identity,
# and no commit message carries a Co-Authored-By trailer or AI attribution.
#
#   check-authorship.sh [range]            check a range, for example origin/main..HEAD (default: origin/main..HEAD,
#                                          or main..HEAD, or every commit if neither branch exists)
#   check-authorship.sh --commit-msg FILE  hook mode: check the message in FILE and the identity git will use
#   check-authorship.sh --pre-push         hook mode: read ref lines from stdin as git passes them to pre-push
#
# Allowed identity: LAB_AUTHOR_NAME <LAB_AUTHOR_EMAIL>. Defaults to the project owner. Change them in .env
# or your environment if you fork this project.
# Exit codes: 0 all good, 1 a commit or message was rejected, 2 usage or git error.
set -uo pipefail

WANT_NAME="${LAB_AUTHOR_NAME:-Mahimn Patel}"
WANT_EMAIL="${LAB_AUTHOR_EMAIL:-mahimn.patel.k@gmail.com}"
# Case-insensitive extended regex for lines that must never appear in a commit message.
ATTR_RE='^[[:space:]]*(co-authored-by[[:space:]]*:|generated[[:space:]]+(with|by)|assisted-by[[:space:]]*:|made[[:space:]]+with[[:space:]]+claude|written[[:space:]]+(with|by)[[:space:]]+claude)|noreply@anthropic\.com|^[[:space:]]*🤖'
ZERO="0000000000000000000000000000000000000000"

bad=0
note() { echo "check-authorship: $*" >&2; }

# check_message <label> <message text on stdin>
check_message() {
  local label="$1" hits
  hits="$(grep -Ein "$ATTR_RE" || true)"
  if [ -n "$hits" ]; then
    note "REJECT $label: message has a co-author trailer or AI attribution:"
    printf '%s\n' "$hits" | sed 's/^/    /' >&2
    return 1
  fi
  return 0
}

check_range() {
  local range="$1" sha an ae cn ce flag count=0
  local shas
  # $range is split on purpose: it can be "<sha> --not --remotes".
  # shellcheck disable=SC2086
  shas="$(git rev-list --reverse $range 2>/dev/null)" || { note "bad range: $range"; return 2; }
  [ -n "$shas" ] || { echo "no commits to check ($range)"; return 0; }
  while read -r sha; do
    count=$((count + 1))
    an="$(git log -1 --format=%an "$sha")"; ae="$(git log -1 --format=%ae "$sha")"
    cn="$(git log -1 --format=%cn "$sha")"; ce="$(git log -1 --format=%ce "$sha")"
    flag=""
    if [ "$an" != "$WANT_NAME" ] || [ "$ae" != "$WANT_EMAIL" ]; then flag="$flag BAD-AUTHOR"; fi
    if [ "$cn" != "$WANT_NAME" ] || [ "$ce" != "$WANT_EMAIL" ]; then flag="$flag BAD-COMMITTER"; fi
    if ! git log -1 --format=%B "$sha" | check_message "${sha:0:10}" 2>/dev/null; then flag="$flag BAD-MESSAGE"; fi
    if [ -n "$flag" ]; then
      bad=1
      note "REJECT ${sha:0:10}:$flag (author '$an <$ae>', committer '$cn <$ce>')"
      git log -1 --format=%B "$sha" | check_message "${sha:0:10}" || true
    fi
  done <<< "$shas"
  [ "$bad" = 0 ] && echo "check-authorship: $count commit(s) OK"
  return "$bad"
}

check_ident() {
  local who ident name rest email rc=0
  for who in AUTHOR COMMITTER; do
    ident="$(git var "GIT_${who}_IDENT")" || { note "cannot read the $who identity"; return 2; }
    name="${ident%% <*}"; rest="${ident#*<}"; email="${rest%%>*}"
    if [ "$name" != "$WANT_NAME" ] || [ "$email" != "$WANT_EMAIL" ]; then
      note "REJECT: $who identity is '$name <$email>', it must be '$WANT_NAME <$WANT_EMAIL>'"
      rc=1
    fi
  done
  return "$rc"
}

case "${1:-}" in
  --commit-msg)
    f="${2:?usage: --commit-msg FILE}"
    [ -f "$f" ] || { note "message file not found: $f"; exit 2; }
    rc=0
    grep -Ev '^[[:space:]]*#' "$f" | check_message "this commit message" || rc=1
    check_ident || rc=1
    exit "$rc"
    ;;
  --pre-push)
    rc=0
    while read -r _lref lsha rref rsha; do
      [ "$lsha" = "$ZERO" ] && continue                  # deleting a ref, nothing to check
      if [ "${LAB_PROTECT_BASE:-0}" = "1" ]; then
        case "$rref" in
          refs/heads/main|refs/heads/master|"refs/heads/${LAB_BASE_BRANCH:-main}")
            note "REJECT: lab sessions never push to $rref"; rc=1; continue ;;
        esac
        if [ "$rsha" != "$ZERO" ] && ! git merge-base --is-ancestor "$rsha" "$lsha" 2>/dev/null; then
          note "REJECT: push to $rref is not a fast-forward (force-push)"; rc=1; continue
        fi
      fi
      if [ "$rsha" = "$ZERO" ]; then range="$lsha --not --remotes"; else range="$rsha..$lsha"; fi
      check_range "$range" || rc=1
    done
    exit "$rc"
    ;;
  -h|--help)
    sed -n '2,13p' "$0"; exit 0 ;;
  "")
    range=""
    for c in origin/main main; do
      git rev-parse --verify -q "$c^{commit}" >/dev/null && { range="$c..HEAD"; break; }
    done
    [ -n "$range" ] || range="HEAD"
    ;;
  *)
    range="$1" ;;
esac
check_range "$range"
