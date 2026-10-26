# Scripted MCP calls with mcporter (read-only)

`mcporter` (tested with 0.7.3) runs an MCP tool from Bash, so a script can chain calls and
filter the results with `jq` before anything reaches the conversation. Use it for READ-ONLY work,
starting with chrome-devtools audits: Lighthouse and performance traces, network lists, console dumps.

## Syntax (checked with `mcporter --help` and `mcporter call --help`)

- `mcporter list chrome-devtools` shows that server's tools. Do not run a bare `mcporter list`:
  it connects to every configured server.
- `mcporter call <server>.<tool> key=value ... --output json`
- Example: `mcporter call chrome-devtools.list_network_requests --output json | jq '[.[]|select(.status>=400)]|.[:20]'`
- Optional typed client for multi-step scripts: `mcporter emit-ts chrome-devtools --mode client --out $TMPDIR/cc-scripts/chrome.ts`

## Caveats

- `chrome-devtools` comes from a Claude plugin, which mcporter does not import. If
  `mcporter list chrome-devtools` reports an unknown server, ask the user to add it once:
  `mcporter config add chrome-devtools --scope home --command npx -- -y chrome-devtools-mcp@1.11.0`.
  Never edit mcporter config yourself. Until then, an ad-hoc form works for one self-contained call:
  `mcporter call --stdio "npx -y chrome-devtools-mcp@1.11.0" --name chrome-devtools <tool> key=value`.
  Each ad-hoc call starts a fresh server and browser, so chained calls need the configured server.
- A mcporter-launched chrome-devtools is a separate server and browser from the plugin's tools in
  this session. Use it for scripted audits (open URL, trace, summarize), not to drive a page Claude
  already has open.

## Guardrails

- NEVER call a protected MCP server (any name listed in CLAUDE_LAB_MCPORTER_BLOCK) through mcporter. It would
  bypass that server's per-tool guards; the lab denies it. Use the server's native `mcp__` tools.
- Never print `mcporter config` output or environment variables: they can contain tokens.
- mcporter calls face only the Bash permission check, not the `mcp__*` allow and deny lists.
  Keep scripts read-only.
