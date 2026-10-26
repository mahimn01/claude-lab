#!/usr/bin/env python3
"""Claude Lab status line: context size, prompt-cache age, compactions, plan usage, and plain-word warnings.

What: Claude Code runs this after each update and pipes its status JSON on stdin; the first
printed line is the status bar, a second line appears only when there is something to act on.
Why: the expensive moments are a cache miss (the whole context is re-sent at full price) and a
bloated or repeatedly compacted context. The bar says when to start fresh instead of paying them.
No keep-warm pings: a ping is an unattended model call (against the no-watchers rule), and it is
wasted whenever you start fresh, which is what these warnings recommend.
How: lab sessions get it automatically through the generated lab settings (statusLine).
Read-only except for a small scan cache (statusline.json) in the lab run directory, so long
transcripts are read incrementally.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

TTL_SECONDS = {'1h': 3600, '5m': 300}


def parse_ts(text: str) -> float | None:
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def scan(transcript: Path, cache_file: Path | None) -> dict:
    """Read only the new part of the transcript: last main reply time, its cache tier, compactions."""
    state = {'path': str(transcript), 'offset': 0, 'last_reply': None, 'ttl': None, 'compactions': 0}
    if cache_file and cache_file.exists():
        try:
            saved = json.loads(cache_file.read_text())
            if saved.get('path') == state['path'] and saved.get('offset', 0) <= transcript.stat().st_size:
                state = saved
        except (OSError, ValueError):
            pass
    with transcript.open('rb') as fh:
        fh.seek(state['offset'])
        for raw in fh:
            if not raw.endswith(b'\n'):
                break  # A line still being written; read it next time.
            state['offset'] += len(raw)
            if b'"isSidechain":true' in raw:
                continue
            if b'"compact_boundary"' in raw:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get('type') == 'system' and event.get('subtype') == 'compact_boundary':
                    state['compactions'] += 1
            elif b'"type":"assistant"' in raw and b'"usage"' in raw:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                state['last_reply'] = parse_ts(event.get('timestamp', '')) or state['last_reply']
                tiers = (event.get('message', {}).get('usage') or {}).get('cache_creation') or {}
                if tiers.get('ephemeral_1h_input_tokens'):
                    state['ttl'] = '1h'
                elif tiers.get('ephemeral_5m_input_tokens'):
                    state['ttl'] = '5m'
    if cache_file:
        try:
            cache_file.write_text(json.dumps(state))
        except OSError:
            pass
    return state


def window_tokens(text: str | None) -> int:
    """Read a compaction window such as 300000, 300k or 1m; fall back to the lab's 300k."""
    text = (text or '').strip().lower()
    scale = {'k': 1_000, 'm': 1_000_000}.get(text[-1:], 1)
    try:
        return int(float(text[:-1] if scale > 1 else text) * scale)
    except ValueError:
        return 300_000


def k(tokens: float) -> str:
    return f'{tokens / 1000:.0f}k'


def clock(epoch: float | None) -> str:
    return time.strftime('%H:%M', time.localtime(epoch)) if epoch else '?'


def render(data: dict, env: dict, now: float, cache_file: Path | None = None) -> list[str]:
    window = data.get('context_window') or {}
    used = window.get('total_input_tokens') or 0
    bili = env.get('CLAUDE_LAB_BILI') == 'on'
    # Native compaction point (lab default 300k); with bili, bili folds against its own 200k budget.
    limit = 200_000 if bili else window_tokens(env.get('CLAUDE_LAB_COMPACT_AT'))
    share = round(100 * used / limit) if limit else 0
    model = (data.get('model') or {}).get('display_name') or 'model ?'
    parts = [f'Lab {model}', f'ctx {k(used)}/{k(limit)} ({share}%)']
    warnings = []

    transcript = Path(data.get('transcript_path') or '')
    info = scan(transcript, cache_file) if transcript.is_file() else {'last_reply': None, 'ttl': None, 'compactions': 0}
    ttl = info['ttl'] or '1h'  # Lab leads write 1-hour cache; bili hides the tier but keeps it.
    if info['last_reply']:
        left = TTL_SECONDS[ttl] - (now - info['last_reply'])
        if left > 0:
            parts.append(f'cache {ttl}, {int(left // 60)}m left')
            if used >= 30_000 and left < (300 if ttl == '1h' else 60):
                warnings.append(f'Cache expires in {max(1, int(left // 60))} min; after that the next message re-sends {k(used)} tokens at full price.')
        else:
            parts.append(f'cache {ttl}, expired')
            if used >= 30_000:
                warnings.append(f'Cache expired: your next message re-sends {k(used)} tokens at full price. '
                                'New topic? Run /lab-new and /clear first.')
    else:
        parts.append(f'cache {ttl}, not started')
    parts.append(f'compactions {info["compactions"]}')

    limits = data.get('rate_limits') or {}
    for key, label in [('five_hour', '5h'), ('seven_day', 'week')]:
        window_info = limits.get(key)
        if not window_info or window_info.get('used_percentage') is None:
            continue
        pct = round(window_info['used_percentage'])
        parts.append(f'{label} {pct}%')
        if pct >= 80:
            name = '5-hour' if key == 'five_hour' else 'Weekly'
            warnings.append(f'{name} limit {pct}% used (resets {clock(window_info.get("resets_at"))}). Keep tasks small or wait.')
    parts.append('bili on' if bili else 'bili off')

    if share >= 85:
        warnings.insert(0, 'Context nearly full: it compacts soon and loses detail. Finish this step, then /lab-new and /clear.')
    elif share >= 60:
        warnings.insert(0, f'Context is large: every message re-reads {k(used)} tokens. Start fresh (/lab-new, /clear) when this task ends.')
    if info['compactions'] >= 2:
        warnings.insert(0, f'Compacted {info["compactions"]} times: early details are fuzzy now. Start a fresh session for new work.')
    lines = [' · '.join(parts)]
    if warnings:
        lines.append('⚠ ' + warnings[0])
    return lines


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or '{}')
        run = os.environ.get('CLAUDE_LAB_RUN_DIR')
        cache_file = Path(run) / 'statusline.json' if run and Path(run).is_dir() else None
        print('\n'.join(render(data, dict(os.environ), time.time(), cache_file)))
    except Exception as error:  # A status bar must never break the session; show why it is blank.
        print(f'Lab status unavailable ({type(error).__name__})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
