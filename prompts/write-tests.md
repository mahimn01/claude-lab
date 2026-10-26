# Task: add tests for existing code

Target: {{TARGET}}

Add tests for the code named above without changing its behavior.

## Steps
1. Read the target code and any existing tests. Note what is already covered.
2. List the behaviors that matter: normal use, edge inputs (empty, large, wrong type), error paths, and anything with state or timing.
3. Write the tests in the project's existing test style and folder. One test per behavior, with a name that says what it checks.
4. Run {{TEST_CMD}}. Every new test must pass. If a test exposes a real bug, mark it clearly (for example an expected-failure marker with a comment), do not fix the production code, and list the bug in your report.
5. Make sure tests do not use the network, real credentials, or files outside a temp directory.
6. Commit with clear subjects, push `{{BRANCH}}`, and open a draft PR against `{{BASE}}` titled `Add tests for {{TARGET}}`. The body lists the behaviors covered and the bugs found.
7. Write the report and stop.
