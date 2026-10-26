#!/usr/bin/env python3
"""Print per-task, per-arm means from a folder of *.summary.json files: python3 benchmarks/summarize.py DIR"""
import glob, json, statistics as st, sys
from collections import defaultdict
cells = defaultdict(list)
for f in sorted(glob.glob(sys.argv[1].rstrip('/') + '/*.summary.json')):
    s = json.load(open(f)); cells[(s['task'], s['arm'])].append(s)
print(f"{'task':12} {'arm':6} {'n':>2} {'cost $':>7} {'wall s':>7} {'Opus %':>6} {'visible':>7} {'hidden':>6}  subagents")
for (task, arm), v in sorted(cells.items()):
    cost = sum(x['total_cost_usd'] for x in v)
    opus = sum(u['costUSD'] for x in v for m, u in x['modelUsage'].items() if 'opus' in m)
    subs = sum(sum((x.get('subagents') or {}).values()) for x in v)
    print(f"{task:12} {arm:6} {len(v):>2} {cost/len(v):7.3f} {st.mean(x['wall_s_measured'] for x in v):7.0f} {100*opus/cost if cost else 0:6.0f} "
          f"{sum(x['visible_tests_pass'] for x in v)}/{len(v):<5} {sum(bool(x['hidden_tests_pass']) for x in v)}/{len(v):<4}  {subs}")
