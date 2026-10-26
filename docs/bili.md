# bili: optional, experimental compression proxy

**Status: off by default. Experimental. Read the risks first.**

bili (npm package `billion-context`, binary `bili`) is a local proxy. It sits between Claude Code and
`api.anthropic.com` and folds old parts of a long conversation into summaries, so later requests carry less.
claude-lab can route one session through it. Nothing else on your machine is affected: plain `claude` and
the desktop app never see it.

## Why it is off

The author tried it on real work and kept it off, for these reasons:

- Version 0.1.204 broke the session at its first fold.
- Version 0.1.203 (the pinned version) drops the mid-conversation system messages Claude Code sends.
- On one long task it doubled the expensive prompt-cache writes, so the session cost more, not less.

Folding changes the text of earlier turns, so the prompt cache can no longer be re-read. That trade only
pays off in some workloads. Measure before you rely on it. These are the author's observations on their own
work, not a benchmark you should expect to reproduce.

## How to use it

```
claude-lab bili install      # npm install of the pinned version into the lab's own folder (needs npm and network)
claude-lab bili status
claude-lab --bili "task"     # this launch only
claude-lab bili on           # make it the default for new launches
claude-lab bili off
```

What it does when a launch uses it:

- starts a small supervisor that runs bili on `127.0.0.1:18990` and restarts it if it crashes;
- points only that Claude process at `http://127.0.0.1:18990/bili/https://api.anthropic.com`;
- turns Claude's own auto-compact off for that session (bili owns compaction then);
- if bili is not installed or will not start, the session runs direct with normal auto-compact and says so.

## Safety notes

- Install uses `npm install --ignore-scripts`: the package has no install scripts, and none are run.
- bili's self-update and remote-install features are turned off so the pinned version never changes.
- Your OAuth token passes through bili in request headers. bili masks it in logs and keeps only a hash
  prefix; the author checked this once for the pinned version. Re-check if you change versions.
- All bili files live under `~/.local/share/claude-lab/bili` (override with `CLAUDE_LAB_DATA_DIR`);
  the on/off switch is `~/.local/state/claude-lab/bili.json` (override with `CLAUDE_LAB_STATE_DIR`).
- Use at your own risk. If anything looks wrong, run `claude-lab bili off` and `claude-lab --no-bili`.
