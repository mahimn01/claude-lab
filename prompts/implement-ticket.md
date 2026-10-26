# Task: implement a ticket as a draft pull request

Ticket: {{TICKET}}

Details:
{{TICKET_TEXT}}

## Steps
1. Read the ticket and the code it touches. List the files you expect to change in your report.
2. Write a failing test that describes the behavior the ticket asks for. Run it and confirm it fails for the right reason.
3. Implement the smallest change that makes the test pass. Run the full test command.
4. Review your own diff once as if you were the reviewer: correctness, edge cases, unclear names, leftover debug code.
5. Commit in small steps. Put the ticket id in each commit subject, for example `{{TICKET}}: add input check`.
6. Push `{{BRANCH}}` and open a draft PR against `{{BASE}}`. Title: `{{TICKET}}: <what changed>`. Body: what changed, tests run, known gaps.
7. Write the report and stop. Do not mark the PR ready and do not merge it.
