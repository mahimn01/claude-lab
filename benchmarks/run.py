#!/usr/bin/env python3
"""Run one headless benchmark run and write a summary file.

    python3 benchmarks/run.py ARM TASK N          ARM = lab | plain,  TASK = a folder under benchmarks/tasks

Environment (all optional except an authenticated `claude`):
    CLAUDE_BIN        the claude executable to use for BOTH arms (default: claude on PATH)
    BENCH_OUT         where summaries and raw output go (default: benchmarks/out)
    BENCH_CONFIG_DIR  an empty CLAUDE_CONFIG_DIR, so your own ~/.claude is not used (default: BENCH_OUT/config)
    CLAUDE_LAB_STATE_DIR  where the lab keeps its run folders (default: BENCH_OUT/lab-state)

Each run starts from a fresh copy of the task's project folder. After the run, the visible tests and the hidden
test (never shown to the agent) are run against the result. Runs spend real API usage.
"""
import importlib.util, json, os, shutil, subprocess, sys, time
from pathlib import Path

arm, task, n = sys.argv[1], sys.argv[2], sys.argv[3]
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get('BENCH_OUT', HERE / 'out')); OUT.mkdir(parents=True, exist_ok=True)
TASKDIR = HERE / 'tasks' / task
name = f'{task}.{arm}.run{n}'
proj = OUT / 'work' / name
if proj.exists(): shutil.rmtree(proj)
shutil.copytree(TASKDIR / 'project', proj)
prompt = (TASKDIR / 'prompt.txt').read_text().strip()

env = dict(os.environ)
env.setdefault('DISABLE_AUTOUPDATER', '1')
env.setdefault('CLAUDE_LAB_STATE_DIR', str(OUT / 'lab-state'))
cfg_dir = Path(os.environ.get('BENCH_CONFIG_DIR', OUT / 'config')); cfg_dir.mkdir(parents=True, exist_ok=True)
env['CLAUDE_CONFIG_DIR'] = str(cfg_dir)
CLAUDE = os.environ.get('CLAUDE_BIN', 'claude')
env['CLAUDE_LAB_CLAUDE'] = CLAUDE
extra = ['--permission-mode', 'bypassPermissions', '-p', '--output-format', 'json']
if arm == 'lab':
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location('lab', HERE.parent / 'bin' / 'lab.py')
    lab = importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)
    run, cfg = lab.prepare(proj, 'balanced', 'auto', None, False)
    argv, lenv = lab.launch_command(run, prompt)
    argv = argv[:-1] + extra + [prompt]
    lenv['CLAUDE_CONFIG_DIR'] = env['CLAUDE_CONFIG_DIR']
    if 'CLAUDE_CODE_OAUTH_TOKEN' in env: lenv['CLAUDE_CODE_OAUTH_TOKEN'] = env['CLAUDE_CODE_OAUTH_TOKEN']
    cwd = cfg.get('launchCwd', cfg['project']); env = lenv
else:
    argv = [CLAUDE] + extra + [prompt]
    cwd = str(proj)
t0 = time.time()
p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=2400)
wall = time.time() - t0

def tests():
    out = {}
    shutil.copy(TASKDIR / 'hidden_test.py', proj / 'hidden_test.py')
    for label, cmd in (('visible', ['discover', '-q', '-p', 'test_*.py']), ('hidden', ['-q', 'hidden_test'])):
        r = subprocess.run([sys.executable, '-m', 'unittest'] + cmd, cwd=proj, capture_output=True, text=True)
        out[label] = r.returncode == 0
    return out
res = tests()
try: d = json.loads(p.stdout)
except ValueError: d = {}
summary = {'name': name, 'arm': arm, 'task': task, 'run': int(n), 'exit': p.returncode, 'wall_s_measured': round(wall, 1),
           'duration_ms': d.get('duration_ms'), 'duration_api_ms': d.get('duration_api_ms'), 'num_turns': d.get('num_turns'),
           'total_cost_usd': d.get('total_cost_usd'), 'is_error': d.get('is_error'), 'subagents': (d.get('subagent_stats') or {}).get('by_type'),
           'usage': d.get('usage'), 'modelUsage': d.get('modelUsage') or {},
           'visible_tests_pass': res['visible'], 'hidden_tests_pass': res['hidden']}
(OUT / f'{name}.summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps({k: summary[k] for k in ['name', 'exit', 'wall_s_measured', 'total_cost_usd', 'visible_tests_pass', 'hidden_tests_pass']}))
