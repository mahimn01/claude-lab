"""The Linux/file token store: private files, strict permissions, and a read-only shared token file."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('token_store', ROOT / 'bin/token_store.py')
token_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(token_store)


class FileStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name) / 'tokens'
        self.store = token_store.FileStore(self.dir)

    def tearDown(self):
        self.temp.cleanup()

    def test_put_get_delete_with_private_modes(self):
        self.store.put('lab', 'dummy-value-1')
        self.assertEqual(self.store.get('lab'), 'dummy-value-1')
        self.assertEqual(stat.S_IMODE((self.dir / 'lab').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
        self.store.put('lab', 'dummy-value-2')
        self.assertEqual(self.store.get('lab'), 'dummy-value-2')
        self.store.delete('lab')
        with self.assertRaises(token_store.CredentialError):
            self.store.get('lab')
        self.store.delete('lab')  # deleting twice is fine

    def test_a_loose_file_is_refused(self):
        self.store.put('lab', 'dummy')
        (self.dir / 'lab').chmod(0o644)
        with self.assertRaisesRegex(token_store.CredentialError, 'must be 600'):
            self.store.get('lab')

    def test_names_cannot_escape_the_directory(self):
        for name in ['../x', 'a/b', '', '.hidden', 'x' * 65]:
            with self.assertRaises(token_store.CredentialError):
                self.store.put(name, 'dummy')

    def test_shared_token_file_is_read_only_for_the_lab(self):
        shared = Path(self.temp.name) / 'shared-token'
        shared.write_text('dummy-shared\n')
        shared.chmod(0o600)
        store = token_store.FileStore(self.dir, shared)
        self.assertEqual(store.get('lab'), 'dummy-shared')
        with self.assertRaises(token_store.CredentialError):
            store.put('lab', 'other')
        store.delete('lab')
        self.assertTrue(shared.exists(), 'a shared token file must never be deleted by the lab')
        self.assertIn('read-only', store.describe())

    def test_open_store_uses_files_off_macos_and_honors_the_shared_file(self):
        with patch.dict(os.environ, {'CLAUDE_LAB_TOKEN_FILE': ''}, clear=False):
            os.environ.pop('CLAUDE_LAB_TOKEN_FILE')
            store = token_store.open_store('svc', self.dir)
            self.assertIsInstance(store, token_store.FileStore)
        with patch.dict(os.environ, {'CLAUDE_LAB_TOKEN_FILE': str(Path(self.temp.name) / 't')}):
            self.assertIn('shared', token_store.open_store('svc', self.dir).describe())


if __name__ == '__main__':
    unittest.main()
