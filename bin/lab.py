#!/usr/bin/env python3
"""Run the opt-in Claude Code lab without changing the ordinary Claude setup.

Use `claude-lab doctor`, `claude-lab --dry-run`, or `claude-lab "your task"`.
Only the lab's own state is written. Verification runs explicit argument lists
inside the chosen project and records real exit codes, without a shell.
"""
from __future__ import annotations

import argparse
import hashlib
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import uuid

ROOT = Path(__file__).resolve().parents[1]
USER = Path.home()


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _env_list(name: str, sep: str = ',') -> list[str]:
    return [item.strip() for item in os.environ.get(name, '').split(sep) if item.strip()]


# Everything below can be moved with an environment variable; the defaults follow the XDG-style layout.
STATE = _env_path('CLAUDE_LAB_STATE_DIR', USER / '.local/state/claude-lab') / 'runs'
CONFIG = _env_path('CLAUDE_LAB_CONFIG_DIR', USER / '.config/claude-lab')
CLAUDE = _env_path('CLAUDE_LAB_CLAUDE', Path(shutil.which('claude') or USER / '.local/bin/claude'))
SOURCE = _env_path('CLAUDE_LAB_SOURCE_SETTINGS', USER / '.claude/settings.json')
PYTHON = sys.executable or shutil.which('python3') or '/usr/bin/python3'
AUTH = STATE.parent / 'auth.json'
TOKEN_SERVICE = 'local.claude-lab.oauth.v1'
ACCOUNT_REGISTRY = _env_path('CLAUDE_LAB_ACCOUNTS', STATE.parent / 'accounts.json')
# Files the lab promises never to change; `doctor` reports whether they still hash the same.
PROTECTED = [SOURCE, SOURCE.with_name('settings.local.json'), SOURCE.with_name('remote-settings.json'),
             SOURCE.with_name('CLAUDE.md'), USER / '.claude.json',
             SOURCE.with_name('plugins') / 'installed_plugins.json'] + [Path(p).expanduser() for p in _env_list('CLAUDE_LAB_PROTECT')]
MODES = ('balanced', 'deep')
COMPACT_WINDOW = '300k'
# Model ids are pinned so the prompt cache stays warm; override them if your Claude Code knows other ids.
SONNET = os.environ.get('CLAUDE_LAB_SONNET', 'claude-sonnet-5-5')
OPUS = os.environ.get('CLAUDE_LAB_OPUS', 'claude-opus-5-5')


def disabled_plugins() -> list[str]:
    """Plugins to leave out of lab sessions (comma list in CLAUDE_LAB_DISABLE_PLUGINS, names with or without @marketplace)."""
    return _env_list('CLAUDE_LAB_DISABLE_PLUGINS')


def mcporter_deny() -> list[str]:
    """mcporter runs MCP tools from Bash, outside per-tool hooks: block named servers and any mcporter config edits.

    Name the servers to wall off in CLAUDE_LAB_MCPORTER_BLOCK (comma list)."""
    rules = []
    for name in _env_list('CLAUDE_LAB_MCPORTER_BLOCK'):
        rules += [f'Bash(mcporter*{name}*)', f'Bash(npx mcporter*{name}*)', f'Bash(bunx mcporter*{name}*)', f'Bash(*mcporter*{name}*)']
    return rules + ['Bash(mcporter config*)']


MCPORTER_ALLOW = ['Bash(mcporter list chrome-devtools*)'] + [
    f'Bash(mcporter call chrome-devtools.{tool}*)' for tool in
    ['list_pages', 'list_network_requests', 'get_network_request', 'list_console_messages',
     'get_console_message', 'performance_analyze_insight', 'lighthouse_audit']]
# Built-in tools that the author's own lab sessions never used in a month of logs. They are hidden from the
# model to cut startup tokens (Artifact alone is ~10k per interactive request); the cron/wakeup/trigger tools
# also enforce the no-watchers rule. Plain `claude` keeps all of them; `--full-tools` restores them for one session.
HIDDEN_TOOLS = ['Artifact', 'ArtifactComments', 'ArtifactData', 'ScheduleWakeup', 'ReportFindings', 'ListAgents',
                'CronCreate', 'CronDelete', 'CronList', 'RemoteTrigger', 'PushNotification', 'DesignSync',
                'EnterWorktree', 'ExitWorktree', 'NotebookEdit']
# Skills that lab sessions rarely need: left out of the model's skill list but still typable as /name.
QUIET_SKILLS = ['dataviz', 'design', 'design-sync', 'batch', 'fewer-permission-prompts', 'doctor', 'loop', 'schedule',
                'run', 'run-skill-generator', 'plugin-authoring', 'update-config', 'code-review', 'artifact-design',
                'artifact-capabilities', 'artifact-diagramming'] + [
    'chrome-devtools-mcp:' + name for name in ['a11y-debugging', 'chrome-devtools', 'chrome-devtools-cli', 'cookie-debugging',
                                               'debug-optimize-lcp', 'memory-leak-debugging', 'troubleshooting']]
SECRET = re.compile(r'AIza[\w-]{25,}|sk-(?:ant|proj)-[\w-]{15,}|(?i:Bearer)\s+[\w.-]{20,}')
CODE_SUFFIXES = {'.py','.ts','.tsx','.js','.jsx','.mjs','.cjs','.json','.toml','.yaml','.yml','.rs','.go','.c','.cpp','.h','.ipynb'}


def fingerprint(project: Path) -> dict:
    """Hash source state, including changes made through Bash, without saving contents."""
    project = project.resolve()
    result = subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],
                            cwd=project,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=False)
    if result.returncode == 0:
        paths = [project / p.decode('utf-8',errors='surrogateescape') for p in result.stdout.split(b'\0') if p]
    else:
        skip = {'.git','node_modules','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dist','build'}
        paths = []
        for base, dirs, files in os.walk(project):
            dirs[:] = [d for d in dirs if d not in skip and not Path(base,d).is_symlink()]
            paths.extend(Path(base,f) for f in files)
    paths = sorted(set(p for p in paths if p.suffix in CODE_SUFFIXES and not p.is_symlink()))
    if len(paths) > 20000:
        raise ValueError('Project scope is too broad; launch the lab inside the actual repository')
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(project)).encode('utf-8',errors='surrogateescape'))
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b'deleted')
    return {'sha256':digest.hexdigest(),'sourceFiles':len(paths)}


def run_fingerprint(run: Path) -> dict:
    """Home sessions browse freely; hash only an explicitly selected code scope."""
    cfg = json.loads((run / 'runtime.json').read_text())
    project = cfg.get('verificationProject', cfg['project'])
    if project is None:
        return {'sha256': None, 'sourceFiles': 0, 'scopeRequired': True, 'project': None}
    return {**fingerprint(Path(project)), 'scopeRequired': False, 'project': project}


def select_project(run: Path, project: Path) -> dict:
    """Change lab verification scope without changing the native launch directory."""
    cfg = json.loads((run / 'runtime.json').read_text())
    if cfg.get('schema') != 1 or cfg.get('root') != str(ROOT):
        raise ValueError('Scope path is not a run owned by this lab installation')
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError('Project directory does not exist')
    if project == USER.resolve() or project in USER.resolve().parents:
        raise ValueError('Choose a specific work folder for code verification, rather than the entire home or computer')
    if run.resolve() == project or project in run.resolve().parents:
        raise ValueError('The verification folder cannot contain the lab run files')
    result = fingerprint(project)
    cfg['verificationProject'] = str(project)
    dump(run / 'runtime.json', cfg)
    return {**result, 'scopeRequired': False, 'project': str(project)}


def scrub(text: str) -> str:
    return SECRET.sub('[REDACTED]', text)


def dump(path: Path, data: dict) -> None:
    """Replace lab state atomically and keep its permissions private."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def bili():
    """Lab-only billion-context proxy controls (bin/bili_proxy.py)."""
    spec = importlib.util.spec_from_file_location('lab_bili', ROOT / 'bin/bili_proxy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def token_store():
    """macOS Keychain on a Mac, a private 0600 file store elsewhere (see bin/token_store.py)."""
    spec = importlib.util.spec_from_file_location('lab_token_store', ROOT / 'bin/token_store.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.open_store(TOKEN_SERVICE, CONFIG / 'tokens')


def set_token(token: str) -> None:
    if not re.fullmatch(r'sk-ant-oat01-[A-Za-z0-9_-]{40,}', token):
        raise ValueError('Expected the exact Claude OAuth token; do not include spaces or punctuation from a sentence')
    token_store().put('lab', token)
    dump(AUTH, {'schema': 1, 'source': 'keychain', 'service': TOKEN_SERVICE, 'account': 'lab'})  # 'keychain' = the token store


def auth_policy() -> str:
    if not AUTH.exists(): return 'primary'
    selector = json.loads(AUTH.read_text())
    base = {'schema': 1, 'source': 'keychain', 'service': TOKEN_SERVICE, 'account': 'lab'}
    if {k:v for k,v in selector.items() if k != 'policy'} != base:
        raise ValueError('Invalid lab authentication selector; use claude-lab auth clear to return to your saved login')
    policy = selector.get('policy','token')
    if policy not in {'primary','token','fallback'}: raise ValueError('Invalid lab authentication policy')
    return policy


def auth_environment(env: dict, source: str | None = None) -> dict:
    """Select a lab-only token in memory; never change the saved native login."""
    env = dict(env)
    if source is None and not AUTH.exists():
        return env
    policy = auth_policy()
    source = source or ('primary' if policy == 'fallback' else policy)
    for name in ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                 'CLAUDE_CODE_OAUTH_TOKEN_FD', 'ANTHROPIC_PROFILE', 'ANTHROPIC_BASE_URL',
                 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
                 'ANTHROPIC_FEDERATION_RULE_ID', 'ANTHROPIC_ORGANIZATION_ID']:
        env.pop(name, None)
    spec=importlib.util.spec_from_file_location('selected_accounts',ROOT/'bin/accounts.py')
    accounts=importlib.util.module_from_spec(spec);spec.loader.exec_module(accounts)
    account=accounts.keychain_account(accounts.load(ACCOUNT_REGISTRY),source)
    if account is not None:env['CLAUDE_CODE_OAUTH_TOKEN']=token_store().get(account)
    return env


def auth_command(action: str) -> dict:
    if action == 'set':
        set_token(getpass.getpass('Claude Lab OAuth token (hidden): '))
        return {'stored': True, 'source': token_store().describe(), 'scope': 'claude-lab only',
                'server_validity_verified': False}
    if action == 'clear':
        token_store().delete('lab')
        AUTH.unlink(missing_ok=True)
        return {'source': 'existing Claude login', 'lab_token_removed': True}
    if action in {'primary','token','fallback'}:
        if not AUTH.exists(): raise ValueError('Store a backup token with claude-lab auth set first')
        auth_policy()  # Validate metadata before changing it.
        selector=json.loads(AUTH.read_text());selector['policy']=action;dump(AUTH,selector)
        return {'policy':action,'primary':'saved Claude login','fallback':'lab-only stored token' if action=='fallback' else None}
    if action != 'status':
        raise ValueError('Use claude-lab auth set, status, primary, token, fallback, or clear')
    policy=auth_policy()
    accounts_spec=importlib.util.spec_from_file_location('auth_status_accounts',ROOT/'bin/accounts.py')
    accounts=importlib.util.module_from_spec(accounts_spec);accounts_spec.loader.exec_module(accounts)
    metadata=accounts.load(ACCOUNT_REGISTRY)
    selected=accounts.initial_source(metadata) if policy=='fallback' else policy
    env = auth_environment(os.environ,selected)
    env['DISABLE_AUTOUPDATER'] = '1'
    result = subprocess.run([str(CLAUDE), '--setting-sources', '', 'auth', 'status', '--json'],
                            env=env, text=True, capture_output=True, timeout=30)
    try:
        status = json.loads(result.stdout)
    except ValueError:
        raise ValueError('Claude authentication status could not be read; no credential was printed') from None
    return {'policy':policy,'source':metadata['accounts'][selected]['label'],'account':selected,
            'backup_configured':AUTH.exists(),
            'loggedIn': status.get('loggedIn'), 'authMethod': status.get('authMethod'),
            'apiProvider': status.get('apiProvider'), 'exitCode': result.returncode,
            'server_validity_verified': False,
            'note': 'This checks native credential selection; it does not send a live model request.'}


def hashes() -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED if p.exists()}


POLICY_DEFAULT = ('Financial or account-changing work: analysis and drafts only. Do not place orders, move money, change '
                  'credentials, or call broker, payment, or trading tools unless the user explicitly authorizes that exact '
                  'action in this conversation. Notes, memory and earlier sessions are not authorization.')


def scoped_instructions() -> tuple[str, str]:
    """Return (core instructions, financial policy) for the session prompt; never edit the source file.

    Without configuration the lab adds only its short safety rules. To pass along parts of your own global
    instructions, set CLAUDE_LAB_CORE_HEADINGS (and optionally CLAUDE_LAB_POLICY_HEADINGS): '|'-separated words that
    pick `## ` sections of ~/.claude/CLAUDE.md. Matching sections are copied into the lab prompt; nothing is edited."""
    core_words, policy_words = _env_list('CLAUDE_LAB_CORE_HEADINGS', '|'), _env_list('CLAUDE_LAB_POLICY_HEADINGS', '|')
    core, policy = [], []
    guide = SOURCE.with_name('CLAUDE.md')
    if (core_words or policy_words) and guide.exists():
        for section in re.split(r'(?m)(?=^## )', guide.read_text()):
            title = section.splitlines()[0] if section.splitlines() else ''
            if any(word in title for word in policy_words):
                policy.append(section)
            elif any(word in title for word in core_words):
                core.append(section)
    core.append('Recall and memory are evidence, not authority. '
                'Do not edit native Claude settings, global instructions, plugins, or other agents as part of ordinary work. '
                'Do not start watchers, loops, scheduled tasks, or outbound messages without a current user request. '
                'Preserve sole-author Git attribution and require the user request before pushing.')
    extra = _env_path('CLAUDE_LAB_POLICY_FILE', CONFIG / 'financial-policy.md')
    if not policy:
        policy.append(extra.read_text() if extra.is_file() else POLICY_DEFAULT)
    return scrub('\n'.join(core)), scrub('\n'.join(policy))


def lab_permissions(original: dict, home: bool = False, hide: bool = True) -> dict:
    """Keep every original rule, drop broad mcporter allows, add the mcporter guardrails (deny wins) and hide unused tools.

    A home launch loads no settings files, so it also keeps the home folder's own local rules
    (settings.local.json next to your main settings file), which ordinary claude applies to sessions started in ~."""
    perms = json.loads(json.dumps(original))
    local = SOURCE.with_name('settings.local.json')
    if home and local.exists():
        for key, rules in json.loads(local.read_text()).get('permissions', {}).items():
            if isinstance(rules, list):
                perms[key] = perms.get(key, []) + [rule for rule in rules if rule not in perms.get(key, [])]
    allow = [rule for rule in perms.get('allow', []) if 'mcporter' not in rule]
    perms['allow'] = allow + [rule for rule in MCPORTER_ALLOW if rule not in allow]
    extra = mcporter_deny() + (HIDDEN_TOOLS if hide else [])
    perms['deny'] = perms.get('deny', []) + [rule for rule in extra if rule not in perms.get('deny', [])]
    return perms


def settings(run: Path, home: bool = False, full_tools: bool = False) -> dict:
    """Use a session layer; retain project/local settings. full_tools skips the tool/skill cuts."""
    original = json.loads(SOURCE.read_text()) if SOURCE.exists() else {}
    keep = _env_list('CLAUDE_LAB_KEEP_HOOKS')  # hook commands containing one of these strings are carried over
    kept_hooks = {}
    for event, groups in original.get('hooks', {}).items():
        selected = []
        for group in groups:
            # Only PreToolUse/PostToolUse/UserPromptSubmit guards you name are kept; startup mirroring and
            # repeated Stop nudges are replaced by one task handoff.
            if event not in {'PreToolUse', 'PostToolUse', 'UserPromptSubmit'}:
                continue
            hooks = [h for h in group.get('hooks', []) if any(k in h.get('command', '') for k in keep)]
            if hooks:
                selected.append({**group, 'hooks': hooks})
        if selected:
            kept_hooks[event] = selected
    quote = __import__('shlex').quote
    kept_hooks.setdefault('UserPromptSubmit', []).insert(0, {'hooks':[{'type':'command',
        'command': quote(PYTHON) + ' ' + quote(str(ROOT/'bin/ready_guard.py')), 'timeout':5}]})
    out = {k: original[k] for k in ['permissions', 'autoMode', 'theme', 'tui'] if k in original}
    out['permissions'] = lab_permissions(original.get('permissions', {}), home, hide=not full_tools)
    # Flag settings outrank project settings, so named plugins are left out rather than set false.
    off = disabled_plugins()
    plugins = {k: v for k, v in original.get('enabledPlugins', {}).items() if k.split('@')[0] not in off and k not in off}
    # Effort comes from modelSettings only (no top-level effortLevel); xhigh needs /lab-model opus or /effort.
    # The per-agent cacheTtl (implementer 1h, investigator 5m) applies only while subagentPromptCacheTtl is unset.
    out.update({'model': SONNET, 'advisorModel': 'opus',
                'modelSettings': {SONNET: {'effortLevel': 'medium'},
                                  OPUS: {'effortLevel': 'high'}},
                'ultracode': False, 'disableWorkflows': True,
                'workflowSizeGuideline': 'small', 'bashOutputMaxChars': 15000, 'crossSessionInbound': 'hold',
                'autoMemoryEnabled': False, 'promptSuggestionEnabled': False,
                'enabledPlugins': {**plugins, **{name: False for name in off if '@' in name}},
                'skillOverrides': {} if full_tools else {name: 'user-invocable-only' for name in QUIET_SKILLS},
                'statusLine': {'type': 'command', 'padding': 0,
                               'command': quote(PYTHON) + ' ' + quote(str(ROOT / 'bin/lab_statusline.py'))},
                'hooks': kept_hooks,
                'env': {'CLAUDE_LAB_ROOT': str(ROOT), 'CLAUDE_LAB_RUN_DIR': str(run),
                        'CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH': '1',
                        'CLAUDE_CODE_FORK_SUBAGENT': '0', 'DISABLE_AUTOUPDATER': '1',
                        'CLAUDE_CODE_SUBAGENT_MODEL': SONNET,
                        'CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL': SONNET,
                        'CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS': '4',
                        'MAX_MCP_OUTPUT_TOKENS': '8000', 'CLAUDE_CODE_GOAL_CHECKIN_MINUTES': '0'}})
    if _env_list('CLAUDE_LAB_CORE_HEADINGS', '|') or _env_list('CLAUDE_LAB_POLICY_HEADINGS', '|'):
        out['claudeMdExcludes'] = [str(SOURCE.with_name('CLAUDE.md'))]  # the scoped copy replaces the full file
    return out


def prepare(project: Path, mode: str, model: str, run: Path | None = None, full_tools: bool = False) -> tuple[Path, dict]:
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError('Project directory does not exist')
    run = run or STATE / str(uuid.uuid4())
    run = run.resolve()
    protected_dirs = [SOURCE.parent] + [Path(p).expanduser() for p in _env_list('CLAUDE_LAB_PROTECT_DIRS')]
    if any(run == p or p in run.parents for p in protected_dirs):
        raise ValueError('Lab state cannot be placed in the original Claude configuration or other protected folders')
    home_workspace = project == USER.resolve()
    if project == run or (project in run.parents and not home_workspace):
        raise ValueError('Lab state must be outside the project folder')
    if run.exists() and any(run.iterdir()):
        raise ValueError('Run directory already contains files; use --resume instead of overwriting it')
    run.mkdir(parents=True, exist_ok=True, mode=0o700)
    core, policy = scoped_instructions()
    for name, text in [('core-instructions.md', core), ('financial-policy.md', policy)]:
        (run / name).write_text(text)
        (run / name).chmod(0o600)
    try:
        session_id = str(uuid.UUID(run.name))
    except ValueError:
        session_id = str(uuid.uuid4())
    config = {'schema': 1, 'runId': session_id, 'project': str(project), 'root': str(ROOT),
              'launchCwd': str(project), 'homeWorkspace': home_workspace,
              'verificationProject': None if home_workspace else str(project),
              'mode': mode, 'modelOverride': model, 'limits': None, 'budgetPolicy': 'soft',
              'compactionPolicy': COMPACT_WINDOW, 'fullTools': full_tools,
              'financialTerms': _env_list('CLAUDE_LAB_FINANCIAL_TERMS'), 'mcporterBlock': _env_list('CLAUDE_LAB_MCPORTER_BLOCK'),
              'sonnetModel': SONNET, 'opusModel': OPUS,
              'createdAt': datetime.now(timezone.utc).isoformat()}
    dump(run / 'runtime.json', config)
    dump(run / 'settings.json', settings(run, home_workspace, full_tools))
    dump(run / 'source-hashes.json', hashes())
    for name in ['brief.md', 'context.md', 'plan.md', 'implementation.md', 'verification.md']:
        (run / name).write_text(f'# {name[:-3].capitalize()}\n\nNot recorded yet.\n')
    dump(run / 'acceptance.json', {'checks': [], 'criteria': []})
    dump(run / 'metrics.json', {'schema': 1, 'workers': 0, 'steps': 0, 'mainSteps': 0,
                               'agents': {}, 'models': {}, 'revision': 0, 'codeEdited': False,
                               'verification': None, 'review': None, 'route': None,
                               'stopNudged': False, 'checkpoint': False, 'lastUsage': None,
                               'workspaceFingerprint': run_fingerprint(run)['sha256'],
                               'scopeRequired': home_workspace, 'verificationProject': config['verificationProject'],
                               'taskSerial':0,'runtimeReady':False})
    return run, config


def upgrade_run(run: Path, full_tools: bool = False) -> dict:
    """Apply the current soft-budget and compaction policy while preserving conversation and task evidence."""
    cfg = json.loads((run / 'runtime.json').read_text())
    if cfg.get('schema') != 1 or cfg.get('root') != str(ROOT):
        raise ValueError('Resume path is not a run owned by this lab installation')
    cfg.update({'limits': None, 'budgetPolicy': 'soft', 'compactionPolicy': COMPACT_WINDOW,
                'fullTools': full_tools or bool(cfg.get('fullTools'))})
    dump(run / 'runtime.json', cfg)
    dump(run / 'settings.json', settings(run, bool(cfg.get('homeWorkspace')), cfg['fullTools']))
    return cfg


def latest_run() -> Path:
    runs = [p for p in STATE.iterdir() if (p / 'runtime.json').is_file() and (p / 'metrics.json').is_file()]
    if not runs:
        raise ValueError('No lab session is available to resume')
    return max(runs, key=lambda p: (p / 'metrics.json').stat().st_mtime)


def launch_command(run: Path, prompt: str = '', resume: bool = False, load_auth: bool = True, auth_source: str | None = None, start_proxy: bool = True) -> tuple[list[str], dict]:
    cfg = json.loads((run / 'runtime.json').read_text())
    core = (run / 'core-instructions.md').read_text()
    task_instructions = (ROOT / 'references/coordinator.md').read_text()
    if cfg.get('homeWorkspace'):
        task_instructions += ('\nThis session starts in the user home directory. Browse and handle general tasks normally. '
                              'Before coding or running code acceptance checks, use mcp__harness-lab__select_project '
                              'to select the specific work folder. Never treat the whole home as one source tree. '
                              'Use absolute file paths and explicit project directories in Bash commands. '
                              'The user can also select the folder with /lab-project /absolute/path.')
    env = auth_environment(os.environ,auth_source) if load_auth else dict(os.environ)
    # Cap the context at 300k so each call re-reads less; a window the user set in the shell wins.
    compact = [] if env.get('CLAUDE_CODE_AUTO_COMPACT_WINDOW') else ['--autocompact', COMPACT_WINDOW]
    # Opt-in bili: route only this child through the lab proxy and let bili own compaction.
    # A proxy that is down or won't start means a normal direct session with native auto-compact.
    env['CLAUDE_LAB_BILI'] = 'off'
    env['CLAUDE_LAB_COMPACT_AT'] = env.get('CLAUDE_CODE_AUTO_COMPACT_WINDOW') or '300000'  # read by the status line
    if cfg.get('biliRequested'):
        proxy = bili()
        if proxy.start() if start_proxy else proxy.health():
            env.update({'ANTHROPIC_BASE_URL': proxy.base_url(), 'DISABLE_AUTO_COMPACT': '1', 'CLAUDE_LAB_BILI': 'on'})
            compact = []
        elif start_proxy:
            print('Claude Lab: bili proxy unavailable; this session runs direct with native auto-compact.', file=sys.stderr)
    # In ~ the "project" settings file IS ~/.claude/settings.json, which would bring back every plugin and hook
    # the lab drops (measured +10.6k tokens); home launches therefore load no settings files besides the lab's.
    sources = '' if cfg.get('homeWorkspace') else 'project,local'
    argv = [str(CLAUDE), '--setting-sources', sources, '--settings', str(run / 'settings.json'),
            '--plugin-dir', str(ROOT / 'plugin'), '--model', SONNET, *compact,
            '--append-system-prompt', core + '\n\n' + task_instructions + '\nTask artifacts: ' + str(run),
            '--name', 'Claude Lab ' + cfg['mode']]
    if resume:
        argv.extend(['--resume', cfg['runId']])
    else:
        argv.extend(['--session-id', cfg['runId']])
    env.update({'CLAUDE_LAB_ROOT': str(ROOT), 'CLAUDE_LAB_RUN_DIR': str(run), 'DISABLE_AUTOUPDATER': '1'})
    if load_auth:
        policy=auth_policy()
        env.update({'CLAUDE_LAB_AUTH_SOURCE':auth_source or ('token' if policy=='token' else 'primary'),
                    'CLAUDE_LAB_AUTH_FALLBACK':'1' if policy=='fallback' else '0'})
    lsp = _env_path('CLAUDE_LAB_DATA_DIR', USER / '.local/share/claude-lab') / 'lsp/node_modules/.bin'
    if lsp.exists():
        env['PATH'] = str(lsp) + os.pathsep + env.get('PATH', '')
    if prompt:
        argv.append(prompt)
    return argv, env


def verify(run: Path) -> dict:
    cfg = json.loads((run / 'runtime.json').read_text())
    metrics = json.loads((run / 'metrics.json').read_text())
    acceptance = json.loads((run / 'acceptance.json').read_text())
    project = cfg.get('verificationProject', cfg['project'])
    if project is None:
        raise ValueError('Select the code folder with /lab-project /absolute/path before verification')
    checks = acceptance.get('checks', [])
    if not checks or len(checks) > 6:
        raise ValueError('Record 1–6 meaningful acceptance checks before verification')
    results = []
    initial = fingerprint(Path(project))['sha256']
    allowed = {'python', 'python3', 'pytest', 'ruff', 'mypy', 'npm', 'pnpm', 'yarn', 'bun',
               'node', 'npx', 'uv', 'cargo', 'go', 'make', 'tsc'}
    for index, check in enumerate(checks):
        argv = check.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ValueError('Each check needs an argv array, with no shell interpolation')
        if Path(argv[0]).name not in allowed:
            raise ValueError('Unsupported check program: ' + Path(argv[0]).name)
        timeout = min(60, max(1, int(check.get('timeoutSeconds', 60))))
        try:
            result = subprocess.run(argv, cwd=project, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
            code, output = result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            code = 124
            output = str(error.stdout or '') + '\nCheck timed out.'
        except OSError as error:
            code, output = 127, str(error)
        clean = scrub(output)
        log = run / f'check-{index}.log'
        log.write_text(clean)
        log.chmod(0o600)
        results.append({'argv': argv, 'exitCode': code, 'log': str(log), 'tail': clean[-1800:]})
    final = fingerprint(Path(project))['sha256']
    report = {'revision': metrics['revision'], 'taskSerial':metrics.get('taskSerial',0),
              'workspaceFingerprint':final, 'project': project,
              'passed': all(r['exitCode'] == 0 for r in results) and initial == final,
              'checks': results, 'checkedAt': datetime.now(timezone.utc).isoformat()}
    # This distinct file is the checker-owned evidence. The mod reads it; it does
    # not replace verification evidence with an agent's assertion of success.
    dump(run / 'verified-checks.json', report)
    (run / 'verification.md').write_text('# Verification\n\n' + json.dumps(report, indent=2) + '\n')
    return report


def doctor(save: bool = False) -> dict:
    """Report the Claude version and whether the files the lab promises not to touch still hash the same."""
    baseline = ROOT / 'installation-baseline.json'
    if save:
        dump(baseline, hashes())
    before = json.loads(baseline.read_text()) if baseline.exists() else {}
    current = hashes()
    data_dir = _env_path('CLAUDE_LAB_DATA_DIR', USER / '.local/share/claude-lab')
    return {'claude': subprocess.check_output([str(CLAUDE), '--version'], text=True).strip(),
            'original_files_unchanged': {p: current.get(p) == value for p, value in before.items()},
            'baseline': 'saved now' if save else ('found' if before else 'none yet: run `claude-lab doctor save`'),
            'lab_plugin': str(ROOT / 'plugin'), 'runtime_root': str(STATE),
            'launcher': shutil.which('claude-lab'),
            'token_store': token_store().describe(),
            'lsp': {p: (data_dir / 'lsp/node_modules/.bin' / p).exists()
                    for p in ['typescript-language-server', 'pyright-langserver']},
            'note': 'Ordinary Claude runtime metadata may change when you use Claude. No original configuration is rewritten by the lab.'}


def main() -> int:
    args = sys.argv[1:]
    commands = {'launch', 'auth', 'doctor', 'route', 'report', 'verify', 'demo', 'prepare', 'fingerprint', 'scope', 'benchmark', 'rate', 'bili'}
    if not args or args[0] not in commands:
        args.insert(0, 'launch')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=sorted(commands))
    parser.add_argument('text', nargs='?', default='')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--mode', choices=MODES, default='balanced')
    parser.add_argument('--model', choices=['auto', 'sonnet', 'opus'], default='auto')
    parser.add_argument('--run', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--quality',type=int,choices=range(6))
    parser.add_argument('--corrections',type=int,default=0)
    parser.add_argument('--bili', action='store_true', help='route this launch through the lab bili proxy (experimental)')
    parser.add_argument('--no-bili', action='store_true', help='run this launch direct even if `claude-lab bili on` is set')
    parser.add_argument('--full-tools', action='store_true', help='keep every built-in tool and skill (undo the tool/skill cuts for this session)')
    opt = parser.parse_intermixed_args(args)
    if opt.command == 'bili':
        proxy, action = bili(), opt.text or 'status'
        if action not in {'on', 'off', 'status', 'start', 'stop', 'install'}:
            parser.error('Use claude-lab bili install, on, off, status, start or stop')
        if action == 'install' and not proxy.install(): print('Claude Lab: bili install failed (needs npm and network).', file=sys.stderr)
        if action in {'on', 'off'}: proxy.set_enabled(action == 'on')
        if action in {'off', 'stop'}: proxy.stop()
        if action == 'start' and not proxy.start(): print('Claude Lab: bili did not start; see ' + str(proxy.HOME / 'supervisor.log'), file=sys.stderr)
        print(json.dumps(proxy.status(), indent=2)); return 0
    use_bili = opt.bili or (bili().enabled() and not opt.no_bili)
    if opt.command == 'auth':
        print(json.dumps(auth_command(opt.text or 'status'), indent=2)); return 0
    if opt.command == 'fingerprint':
        print(json.dumps(run_fingerprint(opt.run) if opt.run else fingerprint(opt.project))); return 0
    if opt.command == 'scope':
        if not opt.run: parser.error('scope requires --run')
        print(json.dumps(select_project(opt.run, opt.project))); return 0
    if opt.command == 'doctor':
        print(json.dumps(doctor(opt.text == 'save'), indent=2)); return 0
    if opt.command == 'benchmark':
        base=STATE.parent/'benchmarks'/str(uuid.uuid4());base.mkdir(parents=True,mode=0o700)
        for label in ['baseline','lab']:shutil.copytree(ROOT/'demo-project',base/label)
        print(json.dumps({'directory':str(base),'task':'Fix the negative-value bug in totals.py. Preserve the public API and verify all test_totals.py cases.',
                          'baseline_project':str(base/'baseline'),'baseline_command':'claude',
                          'lab_project':str(base/'lab'),'lab_command':'claude-lab',
                          'note':'Both copies start identical. No model was run. Use the same task, then compare correctness, correction time and actual /usage bars.'},indent=2));return 0
    if opt.command == 'route':
        conf = json.dumps({'financialTerms': _env_list('CLAUDE_LAB_FINANCIAL_TERMS'), 'sonnetModel': SONNET, 'opusModel': OPUS})
        js = ('import {route, configure} from ' + json.dumps((ROOT / 'plugin/hooks/register.js').as_uri())
              + '; configure(' + conf + '); console.log(JSON.stringify(route(process.argv[1])))')
        subprocess.run(['node', '--input-type=module', '-e', js, opt.text], check=True); return 0
    if opt.command == 'report':
        run = opt.run or (Path(opt.text) if opt.text else max(STATE.iterdir(), key=lambda p: p.stat().st_mtime))
        metrics=json.loads((run/'metrics.json').read_text())
        rates={SONNET:(2,10,.1,4),OPUS:(4,20,.2,8)}
        costs={model:round(sum(values.get(k,0)*p/1e6 for k,p in zip(
            ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens'],rates[model])),4)
               for model,values in metrics.get('models',{}).items() if model in rates}
        print(json.dumps({'run': str(run), 'runtime': json.loads((run/'runtime.json').read_text()),'metrics':metrics,
                          'api_equivalent_usd':costs,'pricing_note':'Published 2026-10-13 rates; assumes 1h cache writes. This is an estimate, not your bill or Max allowance. Unknown served models are omitted.'},indent=2)); return 0
    if opt.command == 'rate':
        if not opt.run or opt.quality is None:parser.error('rate requires --run and --quality 0–5')
        dump(opt.run/'feedback.json',{'quality':opt.quality,'manualCorrections':opt.corrections,'notes':scrub(opt.text)[:2000]})
        print('Feedback recorded without a model request.');return 0
    if opt.command == 'verify':
        if not opt.run:
            parser.error('verify requires --run')
        result = verify(opt.run); print(json.dumps(result, indent=2)); return 0 if result['passed'] else 1
    if opt.command == 'demo':
        project = STATE.parent / 'demo-projects' / str(uuid.uuid4())
        shutil.copytree(ROOT / 'demo-project', project)
        opt.project = project
        opt.text = 'Fix the negative-value bug in totals.py. Preserve the public API and verify all test_totals.py cases. Use the lab handoff and acceptance checks.'
    if opt.resume:
        run = latest_run() if str(opt.resume) == 'latest' else opt.resume.expanduser().resolve()
        cfg = json.loads((run / 'runtime.json').read_text())
        if cfg.get('schema') != 1 or cfg.get('root') != str(ROOT):
            raise ValueError('Resume path is not a run owned by this lab installation')
        if not opt.dry_run:
            cfg = upgrade_run(run, opt.full_tools)
            state = json.loads((run / 'metrics.json').read_text()); state['runtimeReady'] = False
            dump(run / 'metrics.json',state)
        os.chdir(cfg.get('launchCwd', cfg['project']))
    elif opt.dry_run:
        run, cfg = prepare(opt.project, opt.mode, opt.model, Path(tempfile.mkdtemp(prefix='claude-lab-preview-')), opt.full_tools)
    else:
        run, cfg = prepare(opt.project, opt.mode, opt.model, opt.run, opt.full_tools)
        os.chdir(cfg.get('launchCwd', cfg['project']))
    preview = opt.dry_run or opt.command == 'prepare'
    if not (opt.resume and preview):
        # Recorded in the run so account-fallback relaunches and resumes keep the same choice.
        cfg['biliRequested'] = use_bili
        dump(run / 'runtime.json', cfg)
    argv, env = launch_command(run, opt.text, bool(opt.resume), load_auth=not preview, start_proxy=not preview)
    if preview:
        print(json.dumps({'run': str(run), 'project': cfg['project'], 'verificationProject':cfg.get('verificationProject',cfg['project']), 'limits': cfg['limits'],
                          'bili': {'requested': bool(cfg.get('biliRequested')), 'active': env['CLAUDE_LAB_BILI'] == 'on'},
                          'argv': [x if x != argv[argv.index('--append-system-prompt')+1] else '[scoped instructions and lab workflow]' for x in argv],
                          'note': 'No Claude session or model request was started.'}, indent=2)); return 0
    print(f'Claude Lab · {cfg["mode"]} · artifacts: {run}', flush=True)
    if auth_policy() == 'fallback':
        module_spec=importlib.util.spec_from_file_location('lab_fallback',ROOT/'bin/fallback.py')
        module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
        def resume_account(session_id,source,continue_turn):
            state=json.loads((run/'metrics.json').read_text());state['runtimeReady']=False
            dump(run/'metrics.json',state)
            resumed_argv,resumed_env=launch_command(run,module.CONTINUE_PROMPT if continue_turn else None,True,auth_source=source)
            resumed_argv[resumed_argv.index('--resume')+1]=session_id
            return resumed_argv,resumed_env
        accounts_spec=importlib.util.spec_from_file_location('lab_accounts',ROOT/'bin/accounts.py')
        accounts=importlib.util.module_from_spec(accounts_spec);accounts_spec.loader.exec_module(accounts)
        policy=accounts.load();selected=accounts.initial_source(policy)
        if selected!=env.get('CLAUDE_LAB_AUTH_SOURCE'):
            argv,env=launch_command(run,opt.text,bool(opt.resume),auth_source=selected)
        config_dir=Path(env.get('CLAUDE_CONFIG_DIR',str(SOURCE.parent)))
        return module.supervise(argv,env,run,config_dir,lambda sid:resume_account(sid,'token',True),
            primary_command=lambda sid,continue_turn:resume_account(sid,'primary',continue_turn),account_policy=policy,
            account_command=resume_account,policy_loader=accounts.load)
    os.execve(str(CLAUDE), argv, env)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Claude Lab: ' + scrub(str(error)), file=sys.stderr)
        raise SystemExit(1)
