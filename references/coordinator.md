# Claude Lab task workflow

Use the harness-lab:work-task skill for substantive implementation, debugging, research, or mathematics.
The lead runs on Sonnet 5.5 and keeps one model for the whole task, because switching models mid-session
rebuilds the prompt cache. Escalate a hard question by spawning harness-lab:reasoner once with the evidence;
harness-lab:reviewer and harness-lab:reasoner run on Opus, other workers on Sonnet.
Soft budget per task: at most 4 workers, one independent review plus at most one re-review after fixes,
and stop to ask the user once the lab status shows more than 2M tokens on the task. The budget guides;
it never blocks work.
Work directly on small tasks. For larger tasks, give specialists disjoint questions or file ownership,
required source paths, success criteria, and a compact result format. Use harness-lab:investigator,
harness-lab:implementer, harness-lab:reviewer, and harness-lab:reasoner as appropriate.
Multi-step data or bulk output → harness-lab:code-first-data skill; return summaries, not dumps.
Use mcp__harness-lab__checkpoint to record a compact plan, context/source pointers, decisions,
changed paths, acceptance criteria, explicit check argv arrays, and unresolved issues. This updates
the task artifacts outside the project. Use mcp__harness-lab__verify to run recorded acceptance checks
through Bash with the usual permission guards. After code changes, obtain one independent
review from harness-lab:reviewer. Read artifacts for a handoff instead of copying the conversation.
The reviewer returns JSON with approved and findings. Fix material findings and rerun the affected checks.
Do not claim verification passed before the checker and reviewer evidence exists for the latest revision.
Continue until the task is complete or genuinely blocked. If evidence is incomplete, report the exact
remaining work. Keep delegation scoped; do not spawn nested agents, fork full chat history, or launch a Workflow.
The user can use /lab-new to start an independent task and /lab-model to choose auto, sonnet, or opus.
Keep structured handoffs below 6000 characters. Do not write raw transcripts or secrets into notes or memory.
For any financial or broker task, read the scoped financial policy supplied by the lab before analysis,
and obtain one harness-lab:reviewer review of the analysis or change before finishing.
Existing project instructions, permissions, and authorization requirements remain applicable.
In a home-directory session, browse and research normally. Before file edits or code review,
select the specific work folder with mcp__harness-lab__select_project. Read its project instructions.
Use absolute paths and explicit project directories in Bash commands. Checks run in that selected
folder; the whole home is never a source-verification scope. The native launch directory stays fixed.
Refer to files by path rather than @-mentions, and read only the line ranges you need.

## Compact instructions

The context compacts at about 300k tokens. When compacting, keep: failing test names and their errors,
file paths touched or inspected, decisions and their reasons, acceptance checks, and open TODOs.
At a task boundary, write the handoff with mcp__harness-lab__checkpoint (it fills context.md, plan.md
and implementation.md in the task artifacts), then suggest /lab-new and /clear; the next task starts by
reading those files instead of the old conversation.
