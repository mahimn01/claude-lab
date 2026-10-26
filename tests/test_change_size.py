"""The small-change fast path rests on measuring how much source a task changed, and on the helper model pins."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab', ROOT / 'bin/lab.py')
lab = importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)


def frontmatter(name):
    text = (ROOT / 'plugin/agents' / (name + '.md')).read_text()
    return dict(re.findall(r'^([A-Za-z]+): (.+)$', text.split('---')[1], re.M))


class ChangeSizeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / 'project'
        self.project.mkdir()
        (self.project / 'a.py').write_text('x = 1\ny = 2\n')
        (self.project / 'b.py').write_text('print("b")\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_unchanged_source_measures_zero_and_missing_baseline_is_unknown(self):
        baseline = lab.file_hashes(self.project)
        self.assertEqual(lab.change_size(self.project, baseline), {'files': 0, 'lines': 0})
        self.assertIsNone(lab.change_size(self.project, None))

    def test_edits_new_files_and_deletions_are_counted_without_git(self):
        baseline = lab.file_hashes(self.project)
        (self.project / 'a.py').write_text('x = 1\ny = 3\nz = 4\n')
        (self.project / 'c.py').write_text('print("c")\n')
        (self.project / 'b.py').unlink()
        size = lab.change_size(self.project, baseline)
        self.assertEqual(size['files'], 3)
        # Without git the whole length of each changed file counts, so the size only ever over-counts.
        self.assertGreaterEqual(size['lines'], 4)

    def test_git_numstat_gives_the_exact_changed_lines(self):
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        for argv in (['git', 'init', '-q'], ['git', 'add', '.'], ['git', 'commit', '-q', '-m', 'init']):
            subprocess.run(argv, cwd=self.project, env=env, check=True, stdout=subprocess.DEVNULL)
        baseline = lab.file_hashes(self.project)
        (self.project / 'a.py').write_text('x = 1\ny = 3\n')
        self.assertEqual(lab.change_size(self.project, baseline), {'files': 1, 'lines': 2})

    def test_many_changed_files_report_unknown_lines(self):
        baseline = lab.file_hashes(self.project)
        for i in range(30):
            (self.project / f'n{i}.py').write_text('pass\n')
        self.assertIsNone(lab.change_size(self.project, baseline)['lines'])

    def test_run_fingerprint_reports_size_from_the_run_baseline(self):
        run = Path(self.temp.name) / 'run'; run.mkdir()
        (run / 'runtime.json').write_text(json.dumps({'project': str(self.project)}))
        self.assertIsNone(lab.run_fingerprint(run)['size'])
        lab.reset_baseline(run)
        self.assertEqual(lab.run_fingerprint(run)['size'], {'files': 0, 'lines': 0})
        (self.project / 'a.py').write_text('x = 2\n')
        self.assertEqual(lab.run_fingerprint(run)['size']['files'], 1)
        lab.reset_baseline(run)
        self.assertEqual(lab.run_fingerprint(run)['size']['files'], 0)

    def test_fast_path_limits_come_from_the_environment(self):
        with patch.dict(os.environ, {'CLAUDE_LAB_SMALL_FILES': '5', 'CLAUDE_LAB_SMALL_LINES': 'oops'}):
            self.assertEqual(lab._env_int('CLAUDE_LAB_SMALL_FILES', 3), 5)
            self.assertEqual(lab._env_int('CLAUDE_LAB_SMALL_LINES', 80), 80)


class HelperModelPinTest(unittest.TestCase):
    def test_agent_files_pin_their_own_model(self):
        # The pin must not depend on CLAUDE_CODE_SUBAGENT_MODEL: since Claude Code 2.1.251 that variable is only a
        # default, and an agent without a model line inherits the lead's model.
        self.assertEqual(frontmatter('implementer')['model'], 'sonnet')
        self.assertEqual(frontmatter('investigator')['model'], 'sonnet')
        self.assertEqual(frontmatter('reasoner')['model'], 'opus')
        self.assertEqual(frontmatter('reviewer')['model'], 'opus')

    def test_no_advisor_model_unless_opted_in(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(lab, 'SOURCE', Path(tmp) / 'none.json'):
            with patch.dict(os.environ, {'CLAUDE_LAB_ADVISOR_MODEL': ''}):
                self.assertNotIn('advisorModel', lab.settings(Path(tmp)))
            with patch.dict(os.environ, {'CLAUDE_LAB_ADVISOR_MODEL': 'opus'}):
                self.assertEqual(lab.settings(Path(tmp))['advisorModel'], 'opus')


if __name__ == '__main__':
    unittest.main()
