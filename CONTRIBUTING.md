# Contributing

Thanks for looking. Small, focused changes are the easiest to review.

## Run the tests

None of the tests call a model or the network.

```
scripts/run-tests.sh          # everything below, in one go
pytest -q                     # just the Python tests (unittest also works)
bash scripts/scan-secrets.sh  # token, key and personal-path scan of tracked files
```

`demo-project/` has a deliberate bug and its tests fail on purpose; `pytest.ini` keeps pytest out of it.
The plugin tests run only if your Claude Code has the `claude plugin test` command; otherwise they are skipped
with a notice. Please run the suite before you open a pull request, and add a test with any behavior change.

## Authorship rule

Every commit in this repo must be authored and committed by the repository owner, and commit messages must
not carry `Co-Authored-By` trailers or "Generated with" style AI footers. `hooks/commit-msg` and
`hooks/pre-push` enforce this through `scripts/check-authorship.sh`.

For outside contributions: open a pull request from your fork. A maintainer will land it so that the commit
follows this rule (your change and credit are kept in the pull request and its discussion). If you fork
this project for your own use, set `LAB_AUTHOR_NAME` and `LAB_AUTHOR_EMAIL` to your own identity.

To install the hooks in a clone: `scripts/install-hooks.sh .`

## Guidelines

- Keep the README honest: no benchmark numbers unless you can show how to reproduce them.
- Do not add anything that reads, copies or logs a user's Claude login or tokens.
- Keep dependencies minimal: Python standard library, bash and the bundled Node plugin code.
