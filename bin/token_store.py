"""Where the lab keeps its own OAuth tokens: macOS Keychain on a Mac, private 0600 files elsewhere.

Both stores have the same four calls: get(name), put(name, value), delete(name), describe().
Tokens never go into argv or logs. The lab only reads them to put one into a child process's environment.

File store (Linux and anything that is not macOS):
  * one file per name under the store directory (default ~/.config/claude-lab/tokens/), mode 0600, dir 0700;
  * the file's permissions are checked on every read and a loose file is refused;
  * CLAUDE_LAB_TOKEN_FILE can point the "lab" name at a token file that another tool already manages
    (for example a `claude setup-token` file). That file is read-only to the lab: put/delete refuse to
    touch it, so `claude-lab auth clear` can never remove a token that something else relies on.
Set CLAUDE_LAB_TOKEN_BACKEND=file to use the file store on a Mac as well.
"""
from __future__ import annotations

import os
import re
import stat
import sys
import tempfile
from pathlib import Path


class CredentialError(RuntimeError):
    pass


NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')


class FileStore:
    def __init__(self, directory, shared=None):
        self.directory = Path(directory).expanduser()
        self.shared = Path(shared).expanduser() if shared else None

    def describe(self):
        if self.shared:
            return f'file {self.shared} (shared, read-only for the lab)'
        return f'private files in {self.directory} (mode 0600)'

    def _path(self, name):
        if not NAME.fullmatch(name):
            raise CredentialError('Invalid token name')
        if name == 'lab' and self.shared:
            return self.shared
        return self.directory / name

    def _is_shared(self, name):
        return name == 'lab' and self.shared is not None

    def get(self, name):
        path = self._path(name)
        if not path.is_file():
            raise CredentialError(f'No stored token for {name!r}; run `claude-lab auth set` first.')
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise CredentialError(f'Refusing to read {path}: mode is {mode:o}, it must be 600.')
        value = ''.join(path.read_text().split())
        if not value:
            raise CredentialError(f'Token file {path} is empty.')
        return value

    def put(self, name, value):
        if self._is_shared(name):
            raise CredentialError('The lab token file is managed outside the lab; edit that file directly.')
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tok-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(value + '\n')
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def delete(self, name):
        if self._is_shared(name):
            return  # never remove a token file that belongs to another tool
        self._path(name).unlink(missing_ok=True)


def open_store(service, directory):
    """Pick the Keychain on macOS (unless forced to files), else the private file store."""
    shared = os.environ.get('CLAUDE_LAB_TOKEN_FILE')
    if sys.platform == 'darwin' and os.environ.get('CLAUDE_LAB_TOKEN_BACKEND') != 'file' and not shared:
        from importlib import util
        spec = util.spec_from_file_location('lab_keychain', Path(__file__).with_name('keychain_store.py'))
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        store = module.Keychain(service)
        store.describe = lambda: 'macOS Keychain'
        return store
    return FileStore(directory, shared)
