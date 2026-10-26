---
name: work-task
description: Complete substantive coding, debugging, research or mathematical tasks in Claude Lab using scoped context, bounded specialists and verified handoffs.
---

# Work a Claude Lab task

When started in the home directory, browse normally. Before editing files or reviewing code,
select the relevant work folder with mcp__harness-lab__select_project. Read that folder's project
instructions. Use absolute paths and explicit project directories in Bash commands; acceptance
checks run in the selected folder. Never use the entire home as a source-verification scope.

For a small change, work directly. For multiple independent scopes, use the lab investigator,
implementer, reasoner and reviewer specialists. Give each its question or owned files, relevant
source paths, acceptance criteria and a compact return format. Do not fork full chat history.

Record one compact checkpoint with the lab checkpoint tool: source/context pointers, plan,
implementation decisions, unresolved issues, acceptance criteria and meaningful check commands
as argv arrays. The runtime writes brief, context, plan, implementation and verification artifacts
outside the repository. Read these for a stage handoff instead of rerunning discovery.

Run the recorded acceptance checks with the lab verify tool. It invokes the usual Bash permission
guards, then records real exit codes and a fingerprint of current source. For code edits,
use one independent reviewer after checks. Fix material findings, repeat affected checks and review
the final revision. Changes through Bash also invalidate evidence when the source fingerprint changes.

When an investigation is hard or its result is uncertain, escalate that specific question to the
reasoner once with collected evidence. Keep ordinary implementation on Sonnet. The lead keeps one
model for the whole task (a mid-session switch rebuilds the prompt cache); failed checks or a
rejected review call for a reasoner, not a model switch.

Multi-step data or bulk output → harness-lab:code-first-data skill; return summaries, not dumps.

Soft budget per task: at most 4 workers, one review plus at most one re-review after fixes, and stop
to ask the user once the lab status shows more than 2M tokens. The budget guides; it never blocks.
Use scoped specialists for additional work; preserve compact handoffs and avoid nested delegation,
full-history forks, subprocess agents, workflows, timers or unrequested scheduled wakeups.
User routing overrides are /lab-model; the context compacts at about 300k tokens.
Keep secrets and transcripts out of any notes or memory you write.
