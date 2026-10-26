---
name: work-task
description: Complete substantive coding, debugging, research or mathematical tasks in Claude Lab using scoped context, bounded specialists and verified handoffs.
---

# Work a Claude Lab task

When started in the home directory, browse normally. Before editing files or reviewing code,
select the relevant work folder with mcp__harness-lab__select_project. Read that folder's project
instructions. Use absolute paths and explicit project directories in Bash commands; acceptance
checks run in the selected folder. Never use the entire home as a source-verification scope.

## Small change: work directly

A change is small when it touches at most 3 source files and about 80 changed lines in total, and
the task is not financial or security-sensitive (authentication, cryptography, secrets, concurrency,
data migrations). Do it yourself in the lead: read the code, edit, run the project's own tests, report.
Do not spawn workers or a reviewer, do not record a checkpoint, and do not call verify. The lab measures
the change when you finish; at or under the limit it does not ask for any of them. Choose this path by
default: a worker or reviewer adds fixed overhead that a small change rarely repays.

## Larger or riskier change: full handoff

Above the small-change limit, or for financial or security-sensitive work, use the specialists for
independent scopes (investigator, implementer, reasoner, reviewer). Give each its question or owned files,
relevant source paths, acceptance criteria and a compact return format. Do not fork full chat history.

Record one compact checkpoint with the lab checkpoint tool: source/context pointers, plan,
implementation decisions, unresolved issues, acceptance criteria and meaningful check commands
as argv arrays. The runtime writes brief, context, plan, implementation and verification artifacts
outside the repository. Read these for a stage handoff instead of rerunning discovery.

Run the recorded acceptance checks with the lab verify tool. It invokes the usual Bash permission
guards, then records real exit codes and a fingerprint of current source. Then use one independent
reviewer (`harness-lab:reviewer`, Sonnet). For financial or security-sensitive work use `harness-lab:opus-reviewer` (Opus) instead (the lab also upgrades `harness-lab:reviewer` to Opus on those tasks), and use it whenever the user or you explicitly want an Opus review. Fix material findings, repeat affected checks and review the final revision. Changes
through Bash also invalidate evidence when the source fingerprint changes. If a task started small and
grows past the limit, switch to this path before you finish.

## Models

The investigator, implementer and ordinary reviewer run on Sonnet. The reasoner and the opus-reviewer run
on Opus, so spawn them only when this path calls for it. Do not pass a `model` argument to override a specialist; the lab
ignores an Opus request for the investigator or implementer (to get an Opus review, spawn the opus-reviewer).

When an investigation is hard or its result is uncertain after your own attempt, escalate that specific
question to the reasoner once with collected evidence. Keep ordinary implementation on Sonnet. The lead keeps one
model for the whole task (a mid-session switch rebuilds the prompt cache); failed checks or a
rejected review call for a reasoner, not a model switch.

Multi-step data or bulk output → harness-lab:code-first-data skill; return summaries, not dumps.

Soft budget per task: at most 4 workers, one review plus at most one re-review after fixes, and stop
to ask the user once the lab status shows more than 2M tokens. The budget guides; it never blocks.
Use scoped specialists for additional work; preserve compact handoffs and avoid nested delegation,
full-history forks, subprocess agents, workflows, timers or unrequested scheduled wakeups.
User routing overrides are /lab-model; the context compacts at about 300k tokens.
Keep secrets and transcripts out of any notes or memory you write.
