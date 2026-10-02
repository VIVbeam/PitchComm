"""Read-only checks for the NCS version pin, matching firmware, GUI and optional receiver audio."""
import argparse
import atexit
import json
import os
import re
import secrets
import wave
from pathlib import Path

import audit_repo
import check_audio
import provision
from generate_catalog import ROOT, clips, load, rendered

NCS_VERSION = re.compile(r'^v[0-9]+\.[0-9]+\.[0-9]+$')
CATALOG_UNIT_COUNT = re.compile(r'constexpr unsigned kUnitCount = (\d+);')
CATALOG_UNIT_PITCHES = re.compile(r'inline constexpr bool kUnitPitches\[\] = \{(.*?)\};', re.DOTALL)


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


def check_roster(catalog_text):
    """Roster sanity as the generated catalog reports it: 1..15 enrolled units with pitches.

    The generator already refuses duplicate, over-limit or pitchless rosters,
    so this asserts what the catalog says; the repository audit covers drift
    between the roster and the generated files.
    """
    match=CATALOG_UNIT_COUNT.search(catalog_text)
    if match is None:
        raise ValueError('Generated catalog has no kUnitCount; run python tools/generate_catalog.py.')
    enrolled=int(match.group(1))-1  # unit 0 is the coach
    if not 1<=enrolled<=15:
        raise ValueError(f'Generated catalog covers {enrolled} enrolled unit(s); config/roster.json must enroll '
                         '1 to 15 units. Fix the roster, then run python tools/generate_catalog.py.')
    match=CATALOG_UNIT_PITCHES.search(catalog_text)
    if match is None:
        raise ValueError('Generated catalog has no kUnitPitches[]; run python tools/generate_catalog.py.')
    if not re.search(r'\btrue\b',match.group(1)):
        raise ValueError('Generated catalog enrolls no unit with the pitches capability; enroll at least one '
                         'pitches unit in config/roster.json, then run python tools/generate_catalog.py.')


def check_team(root):
    """config/team.local.json and its generated header must match the enrolled roster."""
    local=root/'config/team.local.json'
    header=root/'firmware/include/app/team_config.h'
    if not local.is_file():
        if header.is_file():
            raise ValueError('firmware/include/app/team_config.h exists but config/team.local.json is missing, '
                             'so the header cannot be reproduced; restore config/team.local.json and run '
                             'python tools/provision.py --from-file config/team.local.json (or remove the header '
                             'when this checkout has no team configured).')
        return
    try:
        raw=json.loads(local.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'config/team.local.json is not readable JSON ({error}); restore it and run '
                         'python tools/provision.py --from-file config/team.local.json.') from error
    try:
        data=provision.normalized(raw, root)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError('config/team.local.json is not a valid team configuration: '+str(error)+
                         '. Its eui64 keys must be coach plus exactly the enrolled roster keys; fix it and run '
                         'python tools/provision.py --from-file config/team.local.json.') from error
    if not header.is_file():
        raise ValueError('config/team.local.json exists but firmware/include/app/team_config.h is missing; '
                         'run python tools/provision.py --from-file config/team.local.json to regenerate it.')
    if header.read_bytes()!=provision.header_text(data,root).encode('utf-8'):
        raise ValueError('firmware/include/app/team_config.h does not match config/team.local.json; '
                         'run python tools/provision.py --from-file config/team.local.json to regenerate it.')


def check_audio_set(root, dictionary):
    """The local WAV set must match the current clips, manifest and compact budget.

    Runs read-only whenever data/audio holds WAVs. check_audio owns the strict
    format, pair-limit and manifest rules (--audio); this reuses its helpers so
    the normal build path still catches enrollment drift.
    """
    audio_dir=root/'data/audio'
    wavs=sorted(path.name for path in audio_dir.glob('*.wav')) if audio_dir.is_dir() else []
    if not wavs:
        return
    data, _=load(root)
    expected=[name for name, _ in clips(data)]
    missing=sorted(set(expected)-set(wavs))
    if missing:
        raise ValueError('data/audio is missing clips for the current roster and dictionary: '+', '.join(missing)+
                         '. Run python tools/import_demo_audio.py, then python tools/check_audio.py '
                         '--write-manifest (or restore the clip from a build/audio-backup-* folder).')
    extra=sorted(set(wavs)-set(expected))
    if extra:
        raise ValueError('data/audio holds WAV files outside the current clip set ('+', '.join(extra)+
                         '); remove them so the roster set stays exact.')
    manifest=audio_dir/'manifest.txt'
    expected_manifest=check_audio.manifest_text(dictionary,data)
    try:
        manifest_text=manifest.read_text(encoding='ascii')
    except (OSError, UnicodeDecodeError):
        manifest_text=None
    if manifest_text!=expected_manifest:
        raise ValueError('data/audio/manifest.txt does not match the current dictionary and clip list; '
                         'run python tools/check_audio.py --write-manifest to regenerate it.')
    # check_audio imports SLOT_BYTES from verify_audio_fs, the same 712 KB
    # constant build_audio_fs.py packs the compact image against.
    filesystem_bytes=len(expected_manifest.encode('ascii'))
    for name in expected:
        try:
            frames=check_audio.wav_frames(audio_dir/name)
        except (OSError, ValueError) as error:
            raise ValueError(f'data/audio is not a valid clip set: {error}. '
                             'Replace the recording and validate it with python tools/check_audio.py.') from error
        filesystem_bytes+=check_audio.ulw_bytes(frames)
    if filesystem_bytes>check_audio.SLOT_BYTES:
        raise ValueError(f'Compact 8 kHz audio filesystem needs {filesystem_bytes} bytes; the audio slot holds '
                         f'{check_audio.SLOT_BYTES} bytes (712 KB). Shrink the set: unenroll audio units in '
                         'config/roster.json or drop audio-targeted plays.')


def check(root=ROOT, audio=False, skip_audit=False):
    root=Path(root)
    dictionary, files=rendered(root)
    check_roster(files['firmware/include/pc/catalog.h'])
    stale=[]
    for name, expected in files.items():
        path=root/name
        if not path.is_file() or path.read_text(encoding='utf-8') != expected:
            stale.append(name)
    if stale:
        raise ValueError('Stale or missing call files: '+', '.join(stale)+
                         '. Run tools/generate_catalog.py, then rebuild all units and reload the GUI.')
    check_team(root)
    # The NCS version pin gates every firmware build. Audio-only validation
    # (--audio) never touches the toolchain, so it does not require the pin.
    if not audio:
        version_path=root/'firmware/ncs_version.txt'
        try:
            version=version_path.read_text(encoding='ascii').strip()
        except FileNotFoundError:
            version=''
        if not NCS_VERSION.fullmatch(version):
            raise ValueError('Stale or missing NCS version pin: firmware/ncs_version.txt must contain one '
                             'line like v3.4.0. Restore the pinned NCS version before building; see dev/build.md.')
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
    # Enrollment and audio drift run read-only on the normal path too; the
    # --audio block above already applied the stricter format and pair rules.
    check_audio_set(root, dictionary)
    # The audit is read-only and catches the maintainer checks that do not fit
    # the build path: config symbol coverage, em-dashes, CMake source lists,
    # empty files, plus a second look at the catalog. Audio-only validation
    # asks it to drop the version rule too, so --audio never touches the pin.
    if not skip_audit:
        report=audit_repo.audit(root, check_version=not audio)
        if not report['ok']:
            first=report['errors'][0] if report['errors'] else 'unknown failure'
            raise ValueError(f'Repository audit failed ({len(report["errors"])} error(s)); first: {first}. '
                             'Run python tools/audit_repo.py, or pass --skip-audit for a focused check.')
    return dictionary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', action='store_true', help='Also require the complete matching audio filesystem (does not require the NCS version pin)')
    parser.add_argument('--skip-audit', action='store_true', help='Skip the read-only repository audit (tools/audit_repo.py)')
    args=parser.parse_args()
    try:
        dictionary=check(audio=args.audio, skip_audit=args.skip_audit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Preflight failed: {error}\n')
    print(f'Preflight passed: dictionary {dictionary:08x}'+', audio ready' * args.audio)


if __name__=='__main__': main()
