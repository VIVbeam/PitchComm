"""Read-only checks for matching firmware, GUI and optional receiver audio."""
import argparse
import atexit
import os
import secrets
import wave
from pathlib import Path

import check_audio
from generate_catalog import ROOT, rendered


_flash_locks={}


class FlashLock:
    """Own setup exclusion until normal process exit; never remove another owner."""
    def __init__(self, path):
        self.path=path
        self.owner=f'UPLOAD PID {os.getpid()} TOKEN {secrets.token_hex(16)}\n'.encode('ascii')
        try:
            handle=path.open('xb')
        except FileExistsError as error:
            raise ValueError('Upload blocked: build/validation.lock is owned by validation, provisioning, '
                             'audio generation or another upload. Finish that operation first. '
                             'After an interrupted upload, verify its PID has stopped before removing '
                             'this lock; never remove an active lock or flash validation fixtures.') from error
        identity=os.fstat(handle.fileno())
        try:
            with handle:
                handle.write(self.owner)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # The payload may be partial after a disk/write failure. Compare
            # the exclusively created file identity instead of its contents.
            # A replacement file belongs to somebody else and must survive.
            try:
                current=path.stat()
                if (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass
            raise

    def release(self):
        try:
            if self.path.read_bytes()==self.owner:
                self.path.unlink()
        except FileNotFoundError:
            pass
        if _flash_locks.get(self.path) is self:
            del _flash_locks[self.path]


def acquire_flash_lock(root):
    """Reuse one lease across environments evaluated by the same SCons process."""
    path=(Path(root)/'build/validation.lock').resolve()
    existing=_flash_locks.get(path)
    if existing is not None:
        if path.read_bytes()!=existing.owner:
            raise ValueError('Upload lock ownership changed; preserved the replacement lock.')
        return existing
    path.parent.mkdir(parents=True,exist_ok=True)
    lease=FlashLock(path)
    _flash_locks[path]=lease
    atexit.register(lease.release)
    return lease


def check(root=ROOT, audio=False):
    root=Path(root)
    dictionary, files=rendered(root)
    stale=[]
    for name, expected in files.items():
        path=root/name
        if not path.is_file() or path.read_text(encoding='utf-8') != expected:
            stale.append(name)
    if stale:
        raise ValueError('Stale or missing call files: '+', '.join(stale)+
                         '. Run tools/generate_catalog.py, then rebuild all units and reload the GUI.')
    if audio:
        lock=root/'build/validation.lock'
        try:
            owner=lock.read_text(encoding='ascii')
        except FileNotFoundError:
            owner=''
        if owner.startswith('AUDIO GENERATION '):
            raise ValueError('Audio generation is active or was interrupted. Finish generation or restore '
                             'data/audio from its build/audio-backup-* folder before clearing the lock.')
        try:
            check_audio.check(root=root, quiet=True)
        except (OSError, ValueError, EOFError, wave.Error) as error:
            raise ValueError(f'Receiver audio is not ready: {error}. '
                             'Prepare the recordings and validate them with tools/check_audio.py.') from error
    return dictionary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', action='store_true', help='Also require the complete matching audio filesystem')
    args=parser.parse_args()
    try:
        dictionary=check(audio=args.audio)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Preflight failed: {error}\n')
    print(f'Preflight passed: dictionary {dictionary:08x}'+', audio ready' * args.audio)


if __name__=='__main__': main()
