# Task: review a pull request (read only)

Pull request: {{PR}}

Run this as a `review` session. You do not push and you do not edit files in the repository.

## Steps
1. Read the PR description and the diff: `gh pr view {{PR}}` and `gh pr diff {{PR}}`.
2. Read the surrounding code for every changed file, not only the changed lines.
3. Check, in this order: does it do what the description says, are there bugs or missed edge cases, are the tests meaningful and do they cover the change, is anything risky (security, data loss, concurrency, breaking an API), is the code clear.
4. Run the tests if that is cheap: {{TEST_CMD}}.
5. Write the review to `{{REPORT_FILE}}`:
   - A one-paragraph summary and a verdict: approve, approve with nits, or changes needed.
   - Blocking issues first, each with file, line, why it matters, and a suggested fix.
   - Then non-blocking suggestions.
6. Do not comment on the PR, approve it, or request changes on GitHub. A human reads your report and decides.
