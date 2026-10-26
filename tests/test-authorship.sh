#!/usr/bin/env bash
# Self-test for scripts/check-authorship.sh and the hooks. Uses a throwaway repo in a temp folder.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chk="$here/scripts/check-authorship.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export LAB_AUTHOR_NAME="Mahimn Patel" LAB_AUTHOR_EMAIL="mahimn.patel.k@gmail.com"
fail=0
expect() {  # expect <want_rc> <description> <command...>
  local want="$1" desc="$2"; shift 2
  "$@" >/dev/null 2>&1
  local got=$?
  if [ "$got" = "$want" ]; then echo "ok   $desc"; else echo "FAIL $desc (exit $got, wanted $want)"; fail=1; fi
}
cd "$tmp" && git init -q -b main repo && cd repo || exit 1
git config user.name "$LAB_AUTHOR_NAME"; git config user.email "$LAB_AUTHOR_EMAIL"
git commit -q --allow-empty -m "base"
base="$(git rev-parse HEAD)"

git commit -q --allow-empty -m "good commit"
expect 0 "good commit passes" "$chk" "$base..HEAD"

git commit -q --allow-empty -m "bad trailer" -m "Co-Authored-By: Someone <x@example.com>"
expect 1 "co-author trailer is rejected" "$chk" "HEAD~1..HEAD"
git reset -q --hard HEAD~1

git commit -q --allow-empty -m "ai footer" -m "Generated with a tool"
expect 1 "AI attribution is rejected" "$chk" "HEAD~1..HEAD"
git reset -q --hard HEAD~1

git -c user.name="Someone Else" -c user.email="else@example.com" commit -q --allow-empty -m "wrong author"
expect 1 "wrong author is rejected" "$chk" "HEAD~1..HEAD"
git reset -q --hard HEAD~1

GIT_COMMITTER_NAME="Someone Else" GIT_COMMITTER_EMAIL="else@example.com" git commit -q --allow-empty -m "wrong committer"
expect 1 "wrong committer is rejected" "$chk" "HEAD~1..HEAD"
git reset -q --hard HEAD~1

printf 'fine message\n' > msg.txt
expect 0 "commit-msg hook accepts a clean message" "$chk" --commit-msg msg.txt
printf 'subject\n\nCo-authored-by: A <a@example.com>\n' > msg.txt
expect 1 "commit-msg hook rejects a trailer (any case)" "$chk" --commit-msg msg.txt
printf 'subject\n\n# Co-Authored-By: only in a comment\n' > msg.txt
expect 0 "commit-msg hook ignores comment lines" "$chk" --commit-msg msg.txt
expect 1 "commit-msg hook rejects the wrong identity" env GIT_AUTHOR_NAME="Someone Else" "$chk" --commit-msg msg.txt

git config core.hooksPath "$here/hooks"
expect 0 "installed hook lets a clean commit through" git commit --allow-empty -m "hooked ok"
expect 1 "installed hook blocks a bad commit" git commit --allow-empty -m "x" -m "Co-Authored-By: A <a@example.com>"

# pre-push: simulate git's stdin lines "<local ref> <local sha> <remote ref> <remote sha>"
zero=0000000000000000000000000000000000000000
head="$(git rev-parse HEAD)"
expect 0 "pre-push accepts a clean range" bash -c "echo 'refs/heads/f $head refs/heads/f $base' | '$chk' --pre-push"
expect 1 "pre-push in a lab session refuses main" bash -c "echo 'refs/heads/f $head refs/heads/main $base' | LAB_PROTECT_BASE=1 '$chk' --pre-push"
expect 1 "pre-push in a lab session refuses a force-push" bash -c "echo 'refs/heads/f $base refs/heads/f $head' | LAB_PROTECT_BASE=1 '$chk' --pre-push"
expect 0 "pre-push in a lab session accepts a new feature branch" bash -c "echo 'refs/heads/f $head refs/heads/f $zero' | LAB_PROTECT_BASE=1 '$chk' --pre-push"
exit "$fail"
