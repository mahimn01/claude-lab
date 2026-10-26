# Benchmarks

A small, synthetic comparison harness: plain `claude -p` against the lab launcher on the same task text. It runs real model
calls, so it spends real API usage. Nothing here runs unless you invoke `run.py`.

- `tasks/`: five tasks. Each has a `project/` folder (copied fresh for every run), a `prompt.txt`, and a `hidden_test.py` that
  is only used to grade the result after the run. t1 to t3 are small (a few lines to change); l1 and l2 are larger (about 70 and
  110 added source lines across several files). `l1-ledger/hidden_test.original.py` is the first version of l1's hidden test; see
  the results notes in the main README for why it was changed.
- `run.py ARM TASK N`: one run (ARM is `lab` or `plain`), writes `NAME.summary.json` (cost, wall time, token and per-model usage
  from `modelUsage`, subagent counts, visible and hidden test results).
- `summarize.py DIR`: per-task, per-arm means for a folder of summaries.
- `results/`: the summary files behind the numbers in the main README (no transcripts).
  `pre-fix` and `opus-reviewer` are the same harness run on earlier lab commits; `sonnet-reviewer` is the current one.

Reproduce (needs an authenticated `claude`; use an isolated config folder so your own settings are not touched):

    export CLAUDE_BIN=$(command -v claude) BENCH_OUT=/tmp/lab-bench
    for n in 1 2 3; do for task in l1-ledger l2-tpl; do
      for arm in plain lab; do python3 benchmarks/run.py $arm $task $n; done; done; done
    python3 benchmarks/summarize.py /tmp/lab-bench

Recompute the published tables from the shipped summaries without any model call:

    python3 benchmarks/summarize.py benchmarks/results/sonnet-reviewer
    python3 benchmarks/summarize.py benchmarks/results/opus-reviewer
