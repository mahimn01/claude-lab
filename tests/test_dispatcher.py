"""bin/claude-lab: session subcommands go to the parallel runner, everything else to lab.py. No model is run."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / 'bin/claude-lab'


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fake = Path(self.temp.name) / 'fake-sessions'
        self.fake.write_text('#!/bin/sh\necho "sessions-runner: $*"\n')
        self.fake.chmod(0o755)
        self.env = {**os.environ, 'CLAUDE_LAB_SESSIONS_CMD': str(self.fake),
                    'CLAUDE_LAB_STATE_DIR': str(Path(self.temp.name) / 'state'),
                    'CLAUDE_LAB_CONFIG_DIR': str(Path(self.temp.name) / 'cfg'),
                    'CLAUDE_LAB_ENV_FILE': str(Path(self.temp.name) / 'none'),
                    'TMPDIR': self.temp.name}

    def tearDown(self):
        self.temp.cleanup()

    def run_lab(self, *args):
        return subprocess.run([str(DISPATCHER), *args], env=self.env, text=True, capture_output=True, timeout=60)

    def test_session_subcommands_reach_the_runner_unchanged(self):
        for command in ['start', 'list', 'ls', 'count', 'status', 'nudge', 'tail', 'kill', 'protected']:
            result = self.run_lab(command, 'a', 'b')
            self.assertEqual(result.stdout.strip(), f'sessions-runner: {command} a b', command)

    def test_sessions_prefix_is_accepted(self):
        self.assertEqual(self.run_lab('sessions', 'list').stdout.strip(), 'sessions-runner: list')

    def test_everything_else_goes_to_the_launcher(self):
        result = self.run_lab('--dry-run', '--project', str(ROOT / 'demo-project'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No Claude session or model request was started', result.stdout)
        self.assertNotIn('sessions-runner', result.stdout)

    def test_doctor_runs_without_a_model(self):
        result = self.run_lab('doctor')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('token_store', result.stdout)

    def test_env_file_supplies_defaults(self):
        env_file = Path(self.temp.name) / 'env'
        env_file.write_text('CLAUDE_LAB_SONNET=custom-sonnet-id\n')
        self.env['CLAUDE_LAB_ENV_FILE'] = str(env_file)
        result = self.run_lab('--dry-run', '--project', str(ROOT / 'demo-project'))
        self.assertIn('custom-sonnet-id', result.stdout)

    def test_missing_runner_is_reported_clearly(self):
        env = {k: v for k, v in self.env.items() if k != 'CLAUDE_LAB_SESSIONS_CMD'}
        env['PATH'] = '/usr/bin:/bin'
        copy = Path(self.temp.name) / 'copy'
        (copy / 'bin').mkdir(parents=True)
        (copy / 'bin/claude-lab').write_bytes(DISPATCHER.read_bytes())
        (copy / 'bin/claude-lab').chmod(0o755)
        result = subprocess.run([str(copy / 'bin/claude-lab'), 'list'], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not installed', result.stderr)


if __name__ == '__main__':
    unittest.main()
