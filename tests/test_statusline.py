"""Lab status line and bili switch on synthetic inputs; no model, no real transcripts, no proxy."""
import importlib.util
import json
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = load('lab_statusline', ROOT / 'bin/lab_statusline.py')
NOW = 1_800_000_000.0


def iso(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z')


def reply(epoch, tier='ephemeral_1h_input_tokens', sidechain=False):
    usage = {'input_tokens': 2, 'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 9000,
             'output_tokens': 5, 'cache_creation': {tier: 100}}
    return {'type': 'assistant', 'isSidechain': sidechain, 'timestamp': iso(epoch), 'message': {'usage': usage}}


def compaction(epoch):
    return {'type': 'system', 'subtype': 'compact_boundary', 'isSidechain': False, 'timestamp': iso(epoch)}


class StatusLineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.transcript = self.dir / 'session.jsonl'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, records, mode='w'):
        with self.transcript.open(mode) as fh:
            fh.write(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in records))

    def data(self, used=50_000, limits=None):
        return {'model': {'display_name': 'Sonnet 5.5'}, 'transcript_path': str(self.transcript),
                'context_window': {'total_input_tokens': used, 'context_window_size': 1_000_000},
                **({'rate_limits': limits} if limits else {})}

    def test_warm_cache_shows_time_left_and_no_warning(self):
        self.write([reply(NOW - 600)])
        lines = status.render(self.data(), {}, NOW)
        self.assertEqual(len(lines), 1)
        self.assertIn('ctx 50k/300k (17%)', lines[0])
        self.assertIn('cache 1h, 50m left', lines[0])
        self.assertIn('compactions 0', lines[0])
        self.assertIn('bili off', lines[0])

    def test_expired_cache_tells_the_user_to_start_fresh_for_a_new_topic(self):
        self.write([reply(NOW - 4000)])
        lines = status.render(self.data(120_000), {}, NOW)
        self.assertIn('cache 1h, expired', lines[0])
        self.assertIn('Cache expired: your next message re-sends 120k tokens at full price', lines[1])

    def test_five_minute_tier_is_detected_and_warned_before_expiry(self):
        self.write([reply(NOW - 250, 'ephemeral_5m_input_tokens')])
        lines = status.render(self.data(), {}, NOW)
        self.assertIn('cache 5m, 0m left', lines[0])
        self.assertIn('Cache expires in 1 min', lines[1])

    def test_subagent_replies_do_not_reset_the_lead_cache_clock(self):
        self.write([reply(NOW - 4000), reply(NOW - 10, sidechain=True)])
        self.assertIn('expired', status.render(self.data(), {}, NOW)[0])

    def test_compactions_are_counted_incrementally_and_two_trigger_start_fresh(self):
        cache = self.dir / 'statusline.json'
        self.write([reply(NOW - 100), compaction(NOW - 90)])
        self.assertIn('compactions 1', status.render(self.data(), {}, NOW, cache)[0])
        self.write([compaction(NOW - 50), reply(NOW - 40)], mode='a')
        lines = status.render(self.data(), {}, NOW, cache)
        self.assertIn('compactions 2', lines[0])
        self.assertIn('Compacted 2 times', lines[1])
        self.assertGreater(json.loads(cache.read_text())['offset'], 0)

    def test_large_context_and_plan_limits_are_reported_in_plain_words(self):
        self.write([reply(NOW - 60)])
        limits = {'five_hour': {'used_percentage': 85.4, 'resets_at': NOW + 3600},
                  'seven_day': {'used_percentage': 20, 'resets_at': NOW + 86400}}
        lines = status.render(self.data(270_000, limits), {}, NOW)
        self.assertIn('5h 85%', lines[0])
        self.assertIn('week 20%', lines[0])
        self.assertIn('Context nearly full', lines[1])
        lines = status.render(self.data(40_000, limits), {}, NOW)
        self.assertIn('5-hour limit 85% used', lines[1])

    def test_bili_sessions_measure_against_its_200k_budget_and_custom_windows_parse(self):
        self.write([reply(NOW - 60)])
        self.assertIn('ctx 100k/200k (50%) ', status.render(self.data(100_000), {'CLAUDE_LAB_BILI': 'on'}, NOW)[0] + ' ')
        self.assertIn('/500k', status.render(self.data(), {'CLAUDE_LAB_COMPACT_AT': '500k'}, NOW)[0])
        self.assertIn('/400k', status.render(self.data(), {'CLAUDE_LAB_COMPACT_AT': '400000'}, NOW)[0])

    def test_script_never_fails_on_bad_input(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/lab_statusline.py')], input='not json',
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Lab status unavailable', result.stdout)


class BiliSwitchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = load('lab_for_bili', ROOT / 'bin/lab.py')
        self.lab.STATE = Path(self.temp.name) / 'runs'
        self.run, cfg = self.lab.prepare(ROOT / 'demo-project', 'balanced', 'auto', self.lab.STATE / 'run')
        cfg['biliRequested'] = True
        self.lab.dump(self.run / 'runtime.json', cfg)
        self.real = self.lab.bili()

    def tearDown(self):
        self.temp.cleanup()

    def proxy(self, up):
        real = self.real

        class Fake:
            HOME = real.HOME
            base_url = staticmethod(real.base_url)
            start = staticmethod(lambda: up)
            health = staticmethod(lambda: {'ok': True} if up else None)
        return Fake()

    def test_default_is_off_and_settings_carry_the_status_line(self):
        settings = json.loads((self.run / 'settings.json').read_text())
        self.assertIn('lab_statusline.py', settings['statusLine']['command'])
        self.assertEqual(self.lab.bili().VERSION, '0.1.203')

    def test_a_down_proxy_falls_back_to_direct_with_native_compaction(self):
        self.lab.bili = lambda: self.proxy(False)
        argv, env = self.lab.launch_command(self.run, 'x', load_auth=False)
        self.assertEqual(env['CLAUDE_LAB_BILI'], 'off')
        self.assertIn('--autocompact', argv)
        self.assertNotIn('DISABLE_AUTO_COMPACT', env)
        self.assertNotIn('/bili/', env.get('ANTHROPIC_BASE_URL', ''))

    def test_a_healthy_proxy_routes_only_the_lab_child(self):
        self.lab.bili = lambda: self.proxy(True)
        argv, env = self.lab.launch_command(self.run, 'x', load_auth=False)
        self.assertEqual(env['CLAUDE_LAB_BILI'], 'on')
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:18990/bili/https://api.anthropic.com')
        self.assertEqual(env['DISABLE_AUTO_COMPACT'], '1')
        self.assertNotIn('--autocompact', argv)
        self.assertNotIn('/bili/', __import__('os').environ.get('ANTHROPIC_BASE_URL', ''))  # parent shell untouched


if __name__ == '__main__':
    unittest.main()
