"""Convert the College Demo Tracks recordings into the committed clip set.

Pitch recordings become data/audio/p01.wav .. p<M>.wav (zero padded), the
row-major location recordings become data/audio/l1.wav .. l<R*C>.wav, and the
play recordings become data/audio/d01.wav .. only for the plays whose resolved
roster audience includes an enrolled audio unit. The converted set is exactly
generate_catalog.clips(); a play whose targets reach no audio unit is never
converted, and asking for it is an error rather than a silently shipped dead
clip.

Each output must be mono 16 kHz PCM16 and at most five seconds. ffmpeg applies
a short leading and trailing silence trim when the silenceremove filter yields
a usable clip; otherwise the source is converted untrimmed. A clip that still
fails the format or duration check is refused and reported, and the manifest
is refreshed only after every clip validates.

--check verifies that every source exists and converts nothing. --force
reconverts clips even when a valid output already exists (the default keeps
valid outputs so an unchanged rebuild is cheap).
"""
import argparse
import os
import subprocess
import sys
import wave
from pathlib import Path

import check_audio
from generate_catalog import ROOT, clips, load

SOURCE_DIR = 'College Demo Tracks'
AUDIO_DIR = Path('data/audio')
RATE = 16000
MAX_FRAMES = 5 * RATE
SILENCE_TRIM = ('silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB:'
                'stop_periods=1:stop_duration=0.05:stop_threshold=-50dB')


def source_table(data):
    """Map every vocabulary clip name to its College Demo Tracks recording."""
    table = {}
    for pitch in data['pitches']:
        table[f'p{pitch["key"]:02d}.wav'] = pitch['file']
    for index, location in enumerate(data['locations'], 1):
        table[f'l{index}.wav'] = location['file']
    for play in data['plays']:
        table[f'd{play["key"]:02d}.wav'] = play['file']
    return table


def outputs(data):
    """Return (clip name, source file) for every recording the roster needs.

    The names are exactly generate_catalog.clips(). A play clip is converted
    only when its resolved audience includes an enrolled audio unit; if the
    pipeline ever feeds one in without an audio audience, it is an error.
    """
    table = source_table(data)
    audio_keys = {unit['key'] for unit in data['units'] if unit['audio']}
    result = []
    for name, _ in clips(data):
        play = next((play for play in data['plays']
                     if f'd{play["key"]:02d}.wav' == name), None)
        if play is not None and not set(play['audience']) & audio_keys:
            raise ValueError(f'{name}: play targets no enrolled audio unit; it must not be converted')
        if name not in table:
            raise ValueError(f'{name}: not a pitch, location or play clip')
        result.append((name, table[name]))
    return result


def probe(path, name=None):
    """Return the frame count of a mono 16 kHz PCM16 clip, or raise ValueError."""
    name = path.name if name is None else name
    try:
        with wave.open(str(path), 'rb') as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError(f'{name}: not a readable WAV ({error})') from error
    if (channels, width, rate) != (1, 2, RATE):
        raise ValueError(f'{name}: expected mono 16 kHz PCM16, found {channels} channel(s), '
                         f'{width * 8}-bit at {rate} Hz')
    if frames < 1:
        raise ValueError(f'{name}: contains no samples')
    if frames > MAX_FRAMES:
        raise ValueError(f'{name}: {frames / RATE:.3f} s exceeds the five second limit')
    try:
        check_audio.wav_frames(path)
    except ValueError as error:
        raise ValueError(f'{name}: invalid receiver WAV; requires mono PCM 16-bit 16 kHz, '
                         'consistent headers and 1..80000 samples') from error
    return frames


def run_ffmpeg(ffmpeg, source, destination, trim):
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source)]
    if trim:
        command += ['-af', SILENCE_TRIM]
    command += ['-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_s16le', str(destination)]
    return subprocess.run(command, capture_output=True, text=True)


def convert(ffmpeg, source, destination, force):
    """Convert one source and return (action, frames); action is kept or converted."""
    temporary = destination.with_name(f'.{destination.name}.tmp.wav')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not force and destination.is_file():
        try:
            return 'kept', probe(destination)
        except (OSError, ValueError, wave.Error):
            pass
    try:
        result = run_ffmpeg(ffmpeg, source, temporary, trim=True)
        frames = None
        if result.returncode == 0:
            try:
                frames = probe(temporary, destination.name)
            except (OSError, ValueError, wave.Error):
                frames = None
        if frames is None:
            # The trim filter is treated as unreliable when it errors or leaves
            # an empty clip, so retry the source untrimmed.
            temporary.unlink(missing_ok=True)
            result = run_ffmpeg(ffmpeg, source, temporary, trim=False)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or '').strip().splitlines()
                raise ValueError(f'{source.name}: ffmpeg conversion failed'
                                 + (f' ({detail[-1]})' if detail else ''))
            frames = probe(temporary, destination.name)
        os.replace(temporary, destination)
        return 'converted', frames
    finally:
        temporary.unlink(missing_ok=True)


def stale_files(root, pairs):
    """Return WAV names in data/audio that are not part of this clip set."""
    expected = {name for name, _ in pairs}
    return sorted(path.name for path in (root / AUDIO_DIR).glob('*.wav')
                  if path.name not in expected)


def import_audio(root=ROOT, ffmpeg='ffmpeg', check_only=False, force=False, quiet=False):
    root = Path(root)
    data, dictionary = load(root)
    pairs = outputs(data)
    missing = [source for _, source in pairs if not (root / SOURCE_DIR / source).is_file()]
    if missing:
        for source in missing:
            print(f'missing source: {root / SOURCE_DIR / source}', file=sys.stderr)
        raise ValueError(f'{len(missing)} of {len(pairs)} source recordings are missing '
                         f'under {SOURCE_DIR}. The text-to-speech fallback generates the same '
                         'clip set: powershell tools/generate_audio.ps1')
    stale = stale_files(root, pairs)
    if check_only:
        print(f'All {len(pairs)} source recordings are present under {SOURCE_DIR}; nothing converted')
        if stale:
            print('WAV files not in this clip set (remove once the new set validates): '
                  + ', '.join(stale))
        return
    failures = []
    converted = kept = frames_total = 0
    for index, (name, source) in enumerate(pairs, 1):
        destination = root / AUDIO_DIR / name
        try:
            action, frames = convert(ffmpeg, root / SOURCE_DIR / source, destination, force)
        except (OSError, ValueError, subprocess.SubprocessError, wave.Error) as error:
            failures.append(str(error))
            print(f'[{index}/{len(pairs)}] {name}: FAILED: {error}', file=sys.stderr)
            continue
        frames_total += frames
        converted += action == 'converted'
        kept += action == 'kept'
        if not quiet:
            print(f'[{index}/{len(pairs)}] {name}: {action} {frames / RATE:.3f} s from {source}')
    if failures:
        raise ValueError(f'{len(failures)} clip(s) failed conversion; fix the sources and rerun')
    check_audio.check(write_manifest=True, root=root, quiet=True)
    if not quiet:
        print(f'Imported {converted} clip(s), kept {kept} existing clip(s), {frames_total} frames, '
              f'dictionary {dictionary:08x}')
        if stale:
            print('WAV files not in this clip set (remove once the new set validates): '
                  + ', '.join(stale))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify that every source recording exists and convert nothing')
    parser.add_argument('--force', action='store_true',
                        help='reconvert clips even when a valid output already exists')
    parser.add_argument('--ffmpeg', default='ffmpeg', help='ffmpeg executable (default: ffmpeg on PATH)')
    parser.add_argument('--root', type=Path, default=ROOT,
                        help='repository root holding config/calls.json and College Demo Tracks '
                             '(default: the repo containing tools/)')
    args = parser.parse_args()
    try:
        import_audio(args.root, args.ffmpeg, args.check, args.force)
    except (OSError, ValueError, subprocess.SubprocessError, wave.Error) as error:
        parser.exit(1, f'Audio import failed: {error}\n')


if __name__ == '__main__':
    main()
