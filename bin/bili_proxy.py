#!/usr/bin/env python3
"""Start, check and stop the lab-only billion-context ("bili") compression proxy.

What: bili sits between Claude Code and api.anthropic.com and folds old conversation into
summaries. Only claude-lab sessions that opt in (`claude-lab --bili`, or `claude-lab bili on`)
point ANTHROPIC_BASE_URL at it; plain `claude` and the desktop app never see it.
Why it is OFF by default: an A/B test on the author's own work (see docs/bili.md) found 0.1.204 breaks the session
at its first fold, 0.1.203 drops Claude Code's mid-conversation system messages, and on a
long task bili doubled the expensive cache writes.
How: `claude-lab bili on|off|status|start|stop`. `python3 bili_proxy.py serve` is the
supervisor the lab starts in the background; it restarts bili if it crashes.
What it changes: only files under ~/.local/share/claude-lab/bili (bili's config, sessions,
logs) and the switch file ~/.local/state/claude-lab/bili.json. Self-update and bili's
remote "forced advisory" installs are turned off so the pinned version never changes.
The OAuth token passes through bili in request headers; bili masks it in logs and stores
only a 12-hex hash prefix (checked once by the author: the token appeared in 0 bili files; re-check if you change versions).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

VERSION = '0.1.203'
PORT = 18990
UPSTREAM = 'https://api.anthropic.com'
PREFIX = Path(os.environ.get('CLAUDE_LAB_DATA_DIR') or Path.home() / '.local/share/claude-lab') / 'bili'
HOME = PREFIX / 'home'
SWITCH = Path(os.environ.get('CLAUDE_LAB_STATE_DIR') or Path.home() / '.local/state/claude-lab') / 'bili.json'
PIDFILE = HOME / 'supervisor.pid'
PACKAGE = 'billion-context'
# `claude-lab bili install` puts the pinned package under PREFIX; CLAUDE_LAB_BILI_BIN points at another copy.
BIN = Path(os.environ.get('CLAUDE_LAB_BILI_BIN') or PREFIX / 'node_modules/.bin/bili')


def install() -> bool:
    """Install the pinned bili version (npm package billion-context) into the lab prefix only. Needs npm and network."""
    PREFIX.mkdir(parents=True, exist_ok=True, mode=0o700)
    done = subprocess.run(['npm', 'install', '--prefix', str(PREFIX), '--save-exact', '--ignore-scripts', f'{PACKAGE}@{VERSION}'],
                          check=False)
    return done.returncode == 0 and BIN.exists()


def base_url() -> str:
    return f'http://127.0.0.1:{PORT}/bili/{UPSTREAM}'


def enabled() -> bool:
    """The saved default for new lab launches; OFF unless `claude-lab bili on` was run."""
    try:
        return json.loads(SWITCH.read_text()).get('enabled') is True
    except (OSError, ValueError):
        return False


def set_enabled(on: bool) -> None:
    SWITCH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    SWITCH.write_text(json.dumps({'enabled': on}) + '\n')
    SWITCH.chmod(0o600)


def health(timeout: float = 1.5) -> dict | None:
    """Return bili's health JSON when the pinned version answers on the lab port, else None."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/__bili/health', timeout=timeout) as reply:
            info = json.load(reply)
    except (OSError, ValueError):
        return None
    return info if info.get('ok') is True and info.get('version') == VERSION else None


def proxy_env() -> dict:
    """bili's own environment: every path inside the lab prefix, no updates, no body dumps."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ANTHROPIC_', 'CLAUDE_CODE_', 'BILI_', 'ACP_')) and k != 'CLAUDECODE'}
    env.update({'XDG_CONFIG_HOME': str(HOME / 'config'), 'XDG_DATA_HOME': str(HOME / 'data'),
                'XDG_STATE_HOME': str(HOME / 'state'), 'XDG_CACHE_HOME': str(HOME / 'cache'),
                'ACP_AUTO_UPDATE': '0', 'BILI_ADVISORY_CHECK': '0', 'ACP_DEBUG': '0',
                'ACP_DUMP_BODY': '0', 'BILI_DUMP_4XX': '0', 'BILI_CACHE_KEEPALIVE': '0'})
    return env


def start(wait: float = 10.0) -> bool:
    """Start the supervisor in the background (if needed) and wait until bili answers."""
    if health():
        return True
    if not BIN.exists():
        return False
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = open(HOME / 'supervisor.log', 'a')
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve'], stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, start_new_session=True, env=proxy_env())
    deadline = time.time() + wait
    while time.time() < deadline:
        if health(0.5):
            return True
        time.sleep(0.3)
    return False


def stop() -> bool:
    """Stop the supervisor and its bili child. Returns True if something was running."""
    try:
        pid = int(PIDFILE.read_text())
    except (OSError, ValueError):
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        PIDFILE.unlink(missing_ok=True)
        return False
    for _ in range(30):
        if not health(0.3):
            break
        time.sleep(0.2)
    PIDFILE.unlink(missing_ok=True)
    return True


def serve() -> int:
    """Supervisor: keep one bili running on the lab port; give up after 5 crashes in 2 minutes."""
    PIDFILE.write_text(str(os.getpid()))
    crashes: list[float] = []
    child: subprocess.Popen | None = None

    def shutdown(*_: object) -> None:
        if child and child.poll() is None:
            child.terminate()
        PIDFILE.unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while True:
        child = subprocess.Popen([str(BIN), 'start', '--port', str(PORT), '--host', '127.0.0.1', '--no-auto-update'],
                                 env=proxy_env(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # bili keeps its own rotating log
        child.wait()
        now = time.time()
        crashes = [t for t in crashes if now - t < 120] + [now]
        print(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} bili exited with {child.returncode}; restart {len(crashes)}/5', flush=True)
        if len(crashes) >= 5:
            PIDFILE.unlink(missing_ok=True)
            return 1
        time.sleep(min(2 ** len(crashes), 15))


def status() -> dict:
    info = health()
    return {'installed': BIN.exists(), 'default_for_new_launches': 'on' if enabled() else 'off', 'pinned_version': VERSION,
            'proxy': 'running' if info else 'stopped', 'port': PORT, 'base_url': base_url(),
            'state_dir': str(HOME),
            'note': 'Experimental. Off by default: see docs/bili.md.'}


if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        raise SystemExit(serve())
    print(json.dumps(status(), indent=2))
