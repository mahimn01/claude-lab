---
name: code-first-data
description: Use when a task chains 3+ dependent tool calls, or touches large JSON, logs, CSV, transcripts, PDFs or screenshots. Process data in a throwaway script and return only the result.
---

# Code-first data handling

Every tool result is re-read on every later call, so bulk data in context is paid for many times.
Do the fetching, joining and filtering in code; bring back only the answer.

1. Write a throwaway script in `$TMPDIR/cc-scripts/` (Python, or Node with `jq`). Keep it read-only
   unless the task is to change something.
2. The script prints at most about 40 lines, or a short JSON summary. It writes the full output to a
   file; report that path so the user (or a later step) can open it.
3. Never `cat` a large file into context. Use `rg -n --max-count`, `head`, `wc`, or Read with
   offset/limit for the lines you need.
4. PDFs: `pdftotext -layout f.pdf - | rg -n 'term'`, or `pdftotext -layout f.pdf $TMPDIR/f.txt` and
   then `rg` the text file. Read the PDF itself only when layout or figures matter.
5. Screenshots: only when visual judgment is needed. Downscale first
   (macOS: `sips -Z 1200 in.png --out $TMPDIR/s.png`; Linux: `convert in.png -resize 1200x $TMPDIR/s.png`),
   crop to the region, then Read the small file.
6. Exception: keep raw visuals when you genuinely need to see them, such as visual UI debugging.
   Say why when you do.

For scripted MCP calls from Bash (read-only chrome-devtools audits), read `mcporter.md` in this
skill's folder first. Never call a protected MCP server through mcporter.
