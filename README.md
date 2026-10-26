# claude-lab

claude-lab runs several Claude Code sessions at the same time on one machine. Each session works on its own task, in its own copy of your repository, and finishes by opening a draft pull request. You read the draft pull requests and decide what to merge.

It is a small set of shell scripts. It uses tmux, git worktrees, and the GitHub CLI. There is no server and nothing to install beyond those tools.

## Why

One Claude Code session is slow when you have several independent tasks. Running them one after another wastes time. Running them in the same folder makes them overwrite each other. claude-lab gives each task its own folder and branch, keeps the number of sessions small enough to follow, and puts rules in place so that a session cannot merge, force-push, or push to your main branch.

## Requirements

- Linux or macOS, with `bash`
- `git` (2.5 or newer, for worktrees)
- `tmux`
- `gh`, the GitHub CLI, logged in (`gh auth login`)
- Claude Code (`claude`), logged in
- `python3` (used for one small setting change, see the safety notes)
- `flock` is optional. Without it, claude-lab uses a lock folder instead.

## Quick start

```bash
git clone <this repository> claude-lab
cd claude-lab

cp .env.example .env
# edit .env: set LAB_REPO_URL to the repository your sessions will work on

scripts/init-repo.sh                      # clones the repository into ./repo
scripts/install-hooks.sh ./repo           # optional: also check commits made by hand in ./repo

# start a session that implements a ticket and opens a draft PR
./launch.sh fix-login - prompts/implement-ticket.md \
  --set TICKET=ABC-12 --set "TICKET_TEXT=Login fails when the email has a plus sign."

bin/claude-lab list                       # see all sessions and what each one is doing
bin/claude-lab tail fix-login 40          # last 40 lines of a session
bin/claude-lab nudge fix-login "yes"      # type an answer into a session
bin/claude-lab kill fix-login             # stop a session
```

Add `bin/` to your `PATH` if you want to type `claude-lab` instead of `bin/claude-lab`.

To try it without calling Claude, add `--dry-run` to `launch.sh`. It creates the worktree and the tmux session but only prints the command it would run.

## How it works

1. **`launch.sh <name> <branch|-> <prompt-file>`** makes a git worktree at `worktrees/<name>`. The branch is `<LAB_BRANCH_PREFIX><name>` (default `lab/<name>`) unless you give a branch. It is cut from `origin/<LAB_BASE_BRANCH>` (default `origin/main`).
2. It builds the session prompt: `prompts/COMMON.md` (the rules every session follows) followed by your prompt file. Placeholders like `{{TICKET}}` are filled in from `--set KEY=VALUE`. The result is saved as `prompts/.run-<name>.md`.
3. **`bin/claude-lab start`** opens a tmux session named `rt-<name>`, starts a clean `bash` in the worktree, and runs Claude Code with the prompt as its first message.
4. The session works alone: it writes a failing test, implements, commits, pushes its own branch, and opens a **draft** pull request.
5. It writes a short report to `reports/<name>.md` and stops. You review the draft PR and the report.

### Worktrees

A git worktree is a second working folder for the same repository, on its own branch. Four sessions get four folders under `worktrees/` that all share one `repo/` clone. They cannot overwrite each other's files. Each has its own branch and its own `TMPDIR`.

### The 4-session cap

At most 4 `rt-*` sessions run at once. `LAB_MAX_SESSIONS` can lower the number, never raise it. `launch.sh` refuses early when the cap is reached, and `claude-lab start` checks again under a lock so two launches at the same moment cannot both squeeze in. The lab only looks at tmux sessions with its prefix (`rt-` by default), so your other tmux sessions are never listed, touched, or killed. You can also list names that must never be used in `LAB_PROTECTED_SESSIONS`.

### Permissions

Sessions run with `--permission-mode acceptEdits`, which approves file edits. Shell commands must match the allow list in `config/settings.template.json`. The same file has a deny list. A command that is not on the allow list makes the session stop and wait. `claude-lab list` then shows `WAITING-PERMISSION`. Answer it with `claude-lab nudge <name> 1`, or tell the session what to do instead. The lab never uses `--dangerously-skip-permissions`.

The template is turned into `~/.config/claude-lab/settings.json` each time a session starts, with your branch prefix and lab folder filled in. Edit the template to change what sessions may do.

### Dedicated git config

`lab-env.sh` points `GIT_CONFIG_GLOBAL` at `~/.config/claude-lab/gitconfig` inside lab sessions only. That file holds the commit identity and the hook folder. Your normal global git config is not changed.

## Adding prompts

A prompt is a Markdown file in `prompts/`. It describes one task. `COMMON.md` is added in front of it automatically, so do not repeat the rules.

1. Copy one of the examples (`implement-ticket.md`, `review-pr.md`, `write-tests.md`) to `prompts/my-task.md`.
2. Write the task in plain steps: what to read, what to change, how to check it, what the draft PR should say.
3. Use placeholders for anything that changes per run: `{{TICKET}}`, `{{TARGET}}`, `{{PR}}`.
4. Launch it: `./launch.sh my-run - prompts/my-task.md --set TARGET=src/parser.py`.

Built-in placeholders, always available: `{{NAME}}`, `{{BRANCH}}`, `{{BASE}}`, `{{LAB_DIR}}`, `{{REPORT_FILE}}`, `{{TEST_CMD}}`. `launch.sh` warns when a placeholder is left unfilled.

For a read-only task, add `--kind review`. Review sessions use `LAB_MODEL_REVIEW` (default `opus`). Work sessions use `LAB_MODEL_WORK` (default `sonnet`). `--model <name>` overrides both.

Keep private details (real project names, internal ticket text) in `--set` arguments or in prompt files you do not commit, not in the shared templates.

## Configuration

All settings are in `.env.example`, with comments. The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `LAB_REPO_URL` | none | Repository the sessions work on |
| `LAB_DIR` | folder of `lab-env.sh` | Where `repo/`, `worktrees/`, `reports/`, `tmp/` live |
| `LAB_MAX_SESSIONS` | 4 | Concurrent sessions, 4 at most |
| `LAB_SESSION_PREFIX` | `rt-` | tmux session name prefix |
| `LAB_BRANCH_PREFIX` | `lab/` | Branch name prefix |
| `LAB_BASE_BRANCH` | `main` | Branch to cut from and open PRs against |
| `LAB_CLAUDE_CMD` | `claude` | Command that starts Claude Code |
| `LAB_AUTHOR_NAME`, `LAB_AUTHOR_EMAIL` | the project owner | The only identity allowed on commits |

Values already in your environment win over `.env`. `.env` is read as plain `KEY=VALUE` lines and is never executed.

### Logging in without a browser

If the machine has no browser, run `claude setup-token` on a machine where you are logged in. Save the result in `~/.config/claude-headless/token` and run `chmod 600` on it. Then set `LAB_CLAUDE_CMD=claude-headless` in `.env`. `bin/claude-headless` refuses to run unless the file mode is 600.

## Safety notes

- **Draft PRs only.** Sessions open pull requests with `gh pr create --draft`. They cannot mark a PR ready, close it, or merge it.
- **Never push the main branch.** The deny list blocks it, the prompt forbids it, and the pre-push hook refuses it in lab sessions.
- **Never force-push.** The deny list blocks `--force`, `-f`, `--force-with-lease`, and `+ref`. The pre-push hook refuses non-fast-forward pushes in lab sessions.
- **A human merges.** Nothing in the lab merges. You review each draft PR and merge it yourself.
- **Only `<LAB_BRANCH_PREFIX>*` branches can be pushed.** The allow list covers nothing else.
- **No `--no-verify`, no `git config`, no `git reset --hard`, no `git clean`, no `rm -rf`, no `sudo`.** All denied.
- **Credentials stay out of reach.** Sessions start in a clean environment (`env -i`). The deny list blocks reading `~/.ssh`, `~/.config/gh`, the token file, and any `.env` file, and blocks `gh auth` and `gh api`.
- **One file outside the lab is edited.** Unless you set `LAB_PREACCEPT_TRUST=0`, `launch.sh` marks the new worktree as trusted in `~/.claude.json`, so a fresh session does not stop at the folder-trust question. It also sets the first-run flags there.
- **This is a safety net, not a sandbox.** Read the allow list before you run the lab on a repository you care about. Run it on a machine or account where a mistake is cheap.

## Authorship rule

Every commit is authored and committed by one person: the identity in `LAB_AUTHOR_NAME` and `LAB_AUTHOR_EMAIL` (the project owner, Mahimn Patel, by default). No `Co-Authored-By` lines, no "Generated with" footers, no AI attribution of any kind. If you fork this project, change those two variables to your own identity.

Three layers enforce it:

1. The Claude settings turn off Claude Code's own commit and PR attribution.
2. The prompt rules tell each session not to add any.
3. `scripts/check-authorship.sh` fails when a commit has a different author or committer, a co-author trailer, or AI attribution in its message.

### Installing the hooks

In a repository, run:

```bash
scripts/install-hooks.sh /path/to/repo
```

This sets `core.hooksPath` in that repository's local git config to this project's `hooks/` folder. It does not touch your global config, and it stops if the repository already uses another hooks path. In that case, call `scripts/check-authorship.sh --commit-msg "$1"` from your `commit-msg` hook and `scripts/check-authorship.sh --pre-push` from your `pre-push` hook.

- `commit-msg` rejects a commit whose message has a trailer or AI attribution, or whose author or committer is not the allowed identity.
- `pre-push` checks every commit being pushed. In lab sessions it also refuses pushes to `main` and force-pushes.

Lab sessions use these hooks automatically through the dedicated git config. You can also check a range by hand:

```bash
scripts/check-authorship.sh origin/main..HEAD
```

It exits 0 when everything is fine and 1 when a commit is rejected. Run `tests/test-authorship.sh` to test the checker itself.

## Before you publish your own version

Run `scripts/scan-secrets.sh`. It looks through tracked files for token prefixes, private keys, bearer tokens, assigned credentials, phone numbers, IP addresses, and email addresses other than the allowed one. It is a safety net, so read your diff as well. `.gitignore` already excludes `.env`, `repo/`, `worktrees/`, `reports/`, and `tmp/`.

## Architecture

- `launch.sh`: creates the worktree, builds the prompt, starts the session.
- `lab-env.sh`: loads `.env`, sets defaults, the git identity, `PATH`, and a per-session `TMPDIR`. Sourced by everything else.
- `bin/claude-lab`: starts, lists, tails, nudges, and kills `rt-*` tmux sessions, and enforces the cap and the model choice.
- `bin/claude-headless`: optional wrapper to log in with a token file.
- `config/settings.template.json`: Claude Code allow and deny lists, rendered at session start.
- `prompts/`: `COMMON.md` (rules for every session) and task templates.
- `hooks/` and `scripts/check-authorship.sh`: commit-msg and pre-push checks.
- `scripts/init-repo.sh`, `install-hooks.sh`, `scan-secrets.sh`: setup and checks.
- `tests/test-authorship.sh`: self-test for the authorship checker.
- Created at run time and ignored by git: `repo/` (the clone), `worktrees/`, `reports/`, `tmp/`, `prompts/.run-*.md`.

## Limits

- A session waits for you when it needs a command that is not on the allow list. Check `claude-lab list` now and then.
- The `WAITING-PERMISSION` and rate-limit detection reads the tmux screen and can miss new wording from Claude Code.
- A repository that sets its own `core.hooksPath` bypasses the lab hooks. Always run `scripts/check-authorship.sh` before you push by hand.

## License

MIT. See `LICENSE`.
