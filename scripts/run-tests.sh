#!/usr/bin/env bash
# Run every test that needs no model and no network. Exit code is non-zero if anything fails.
#   scripts/run-tests.sh
# Python tests use pytest when it is installed, otherwise unittest. The plugin tests run with
# `claude plugin test` and are skipped (with a notice) when your Claude Code has no such command.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"
status=0
step() { echo; echo "== $1"; }

step "python tests"
if python3 -c 'import pytest' 2>/dev/null; then python3 -m pytest -q tests || status=1
else python3 -m unittest discover -s tests -p 'test_*.py' || status=1; fi

step "authorship checks and hooks"
bash tests/test-authorship.sh || status=1

step "parallel runner (dry-run, private tmux socket)"
bash tests/test-parallel.sh || status=1

step "plugin tests (no model calls)"
if command -v claude >/dev/null 2>&1 && claude plugin test --help >/dev/null 2>&1; then
  claude plugin test plugin || status=1
else
  echo "skipped: this Claude Code has no 'plugin test' command (try a newer version)"
fi

step "secret scan"
bash scripts/scan-secrets.sh || status=1

echo; [ "$status" = 0 ] && echo "all checks passed" || echo "SOME CHECKS FAILED"
exit "$status"
