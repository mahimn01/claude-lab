# Security

## Reporting a problem

Please report security issues privately by email to mahimn.patel.k@gmail.com rather than in a public issue.
Include what you ran, what you expected, and what happened. Do not include real tokens or transcripts. This is a
small side project, so there is no fixed response time, but I will reply.

## What is in scope

- Anything that makes `claude-lab` read, change, copy or print your saved Claude login or an optional
  lab-only token, or store one with loose file permissions.
- Anything that lets the parallel runner break its stated rules (draft-only pull requests, no push to the
  main branch, no force-push).
- Secrets or personal paths committed to the repository.

The parallel runner's allow and deny list is a strong default, not a security boundary; see the README
section "Parallel session runner" and "Limitations".

## Supported versions

Only the latest release and the `main` branch.
