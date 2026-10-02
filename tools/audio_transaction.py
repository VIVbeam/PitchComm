"""Stage and validate Windows speech recordings before replacing the live set."""
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import check_audio
import preflight
from generate_catalog import ROOT


def snapshot(root):
    """Detect vocabulary or asset edits while the speech engine is running."""
    paths=[root/'config/calls.json', root/'firmware/include/pc/catalog.h', root/'gui/catalog.json']
    if (root/'data').is_symlink():
        raise ValueError('Audio generation requires an ordinary project data directory')
    if (root/'data').exists():
        paths.extend(sorted((root/'data').rglob('*')))
    result={}
    for path in paths:
        if path.is_symlink():
            raise ValueError(f'Audio generation requires ordinary files: {path}')
        relative=path.relative_to(root).as_posix()
        result[relative]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


def synthesize(stage, voice, powershell):
    command=[powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             str(Path(__file__).with_name('synthesize_audio.ps1')),
             '-CatalogPath', str(stage/'config/calls.json'), '-AudioPath', str(stage/'data/audio')]
    if voice:
        command.extend(['-Voice', voice])
    subprocess.run(command, check=True)


def install(root, stage, backup):
    """Keep the original outside temporary cleanup, including if rollback fails."""
    live=root/'data/audio'
    live.parent.mkdir(exist_ok=True)
    had_live=live.exists()
    if had_live:
        live.rename(backup)
    try:
        (stage/'data/audio').rename(live)
    except BaseException as error:
        if had_live:
            try:
                backup.rename(live)
            except OSError as restore_error:
                raise RuntimeError(f'Audio replacement failed ({error}); restoration also failed '
                                   f'({restore_error}). Original recordings are preserved at {backup}. '
                                   'Restore that folder to data/audio before building or uploading.') from error
        raise
    return backup if had_live else None


def generate(root=ROOT, voice='', powershell='powershell'):
    root=Path(root).resolve()
    build=root/'build'
    build.mkdir(exist_ok=True)
    if build.resolve().parent!=root:
        raise ValueError('Audio staging must remain inside the project build directory')
    lock=build/'validation.lock'
    try:
        handle=lock.open('x', encoding='ascii')
    except FileExistsError as error:
        raise ValueError('Configuration is already locked. Check for active audio generation, '
                         'validation or provisioning before removing build/validation.lock.') from error
    try:
        with handle:
            handle.write(f'AUDIO GENERATION PID {os.getpid()}\n')
        try:
            preflight.check(root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f'Preflight failed: {error}') from error
        original=snapshot(root)
        # TemporaryDirectory owns only its newly created, project-local folder.
        with tempfile.TemporaryDirectory(prefix='audio-stage-', dir=build) as directory:
            stage=Path(directory)
            (stage/'config').mkdir()
            shutil.copyfile(root/'config/calls.json', stage/'config/calls.json')
            if (root/'data').exists():
                shutil.copytree(root/'data', stage/'data')
            (stage/'data/audio').mkdir(parents=True, exist_ok=True)
            if snapshot(root)!=original:
                raise ValueError('Vocabulary or assets changed while copying; existing recordings were preserved')
            print('Generating recordings in a separate folder...', flush=True)
            synthesize(stage, voice, powershell)
            check_audio.check(write_manifest=True, root=stage)
            if snapshot(root)!=original:
                raise ValueError('Vocabulary or assets changed during generation; new recordings were not installed')
            preflight.check(root)
            backup=build/stage.name.replace('audio-stage-', 'audio-backup-', 1)
            saved=install(root, stage, backup)
        print('Audio set installed.'+(f' Previous recordings: {saved}' if saved else ''), flush=True)
        return saved
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default='')
    parser.add_argument('--powershell', default='powershell')
    args=parser.parse_args()
    try:
        generate(voice=args.voice, powershell=args.powershell)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Audio generation failed: {error}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Audio generation interrupted; check data/audio and any build/audio-backup-* folder.\n')


if __name__=='__main__':
    main()
