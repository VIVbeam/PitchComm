"""Validate the PCM asset set and write the dictionary manifest (stdlib only).

The clip set is exactly generate_catalog.clips(data): the pitches, the
row-major locations, and the play clips whose resolved roster audience
includes an enrolled audio unit. Every source clip must be mono 16 kHz PCM16
with 1..80000 samples (under five seconds), and each pitch clip plus each
location clip must stay under five seconds together because the firmware
plays the pair back to back.

data/audio/manifest.txt records the dictionary on the first line and one clip
name per line, so a manifest from another dictionary or clip set is rejected.
The check also reports the compact (8 kHz mu-law) filesystem footprint against
the 712 KB audio slot; the compact form is the smallest deployment, so it must
fit even when the 16 kHz PCM sources do not.
"""
import argparse
import struct
from pathlib import Path

from generate_catalog import ROOT, clips, load
from verify_audio_fs import SLOT_BYTES

MAX_FRAMES = 80000  # five seconds at 16 kHz
PAIR_LIMIT = 80000  # one pitch plus one location, also five seconds


def ulw_bytes(frames):
    """Size of the compact 8 kHz mu-law payload build_audio_fs.py writes."""
    return 8 + frames // 2


def manifest_text(dictionary, data):
    """Return the canonical manifest: dictionary line, then one clip per line."""
    lines = [f'{dictionary:08x}']
    lines.extend(name for name, _ in clips(data))
    return '\n'.join(lines) + '\n'


def wav_frames(path):
    """Match include/pc/wav.h so ready on this laptop means parsable on a unit."""
    def invalid():
        raise ValueError(f'{path.name}: invalid receiver WAV; requires mono PCM 16-bit 16 kHz, consistent headers and 1..80000 samples')
    with path.open('rb') as source:
        size=path.stat().st_size
        header=source.read(12)
        if size<44 or len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE': invalid()
        end=8+int.from_bytes(header[4:8],'little')
        if not 44<=end<=size: invalid()
        position=12; seen_format=False; samples=None
        while position+8<=end:
            source.seek(position); chunk=source.read(8)
            if len(chunk)!=8: invalid()
            length=int.from_bytes(chunk[4:],'little'); start=position+8
            if start+length>end: invalid()
            if chunk[:4]==b'fmt ':
                if seen_format or length<16: invalid()
                format_bytes=source.read(16)
                if len(format_bytes)!=16 or struct.unpack('<HHIIHH',format_bytes)!=(1,1,16000,32000,2,16): invalid()
                seen_format=True
            elif chunk[:4]==b'data':
                if samples is not None or not length or length%2 or length>160000: invalid()
                samples=length//2
            position=start+length+(length%2)
            if position>end: invalid()
        if not seen_format or samples is None or position!=end: invalid()
        return samples


def check(write_manifest=False, root=None, quiet=False):
    """Validate the exact clips() set, pair limit, manifest and slot budget.

    Returns the per-clip frame counts. Raises ValueError naming the first
    problem. With write_manifest, data/audio/manifest.txt is rewritten before
    the budget is judged, so a failed run still reports the dictionary.
    """
    root=ROOT if root is None else Path(root)
    data, dictionary=load(root)
    audio_dir=root/'data/audio'
    lengths={}
    source_bytes=0
    compact_bytes=0
    for name, _ in clips(data):
        path=audio_dir/name
        try:
            frames=wav_frames(path)
        except FileNotFoundError as error:
            raise ValueError(f'{name}: missing from data/audio') from error
        lengths[name]=frames
        source_bytes+=path.stat().st_size
        compact_bytes+=ulw_bytes(frames)
    for pitch in data['pitches']:
        pitch_name=f'p{pitch["key"]:02d}.wav'
        if pitch_name not in lengths:
            continue
        for index in range(1,len(data['locations'])+1):
            location_name=f'l{index}.wav'
            if lengths[pitch_name]+lengths[location_name]>PAIR_LIMIT:
                raise ValueError(f'Pitch {pitch_name} plus location {location_name} exceeds five seconds')
    manifest=audio_dir/'manifest.txt'
    expected=manifest_text(dictionary,data)
    if write_manifest:
        with manifest.open('w',encoding='ascii',newline='\n') as handle:
            handle.write(expected)
    # The manifest is part of the deployed set, so the budget always sees it.
    filesystem_bytes=len(expected.encode('ascii'))+compact_bytes
    if filesystem_bytes>SLOT_BYTES:
        raise ValueError(f'Compact audio filesystem needs {filesystem_bytes} bytes; the audio slot holds '
                         f'{SLOT_BYTES} bytes (712 KB). Shrink the set: unenroll audio units in '
                         'config/roster.json or drop audio-targeted plays. Clips are never truncated.')
    if not write_manifest and (not manifest.exists() or manifest.read_text(encoding='ascii')!=expected):
        raise ValueError('Manifest does not match the call dictionary or clip list; regenerate the audio set')
    extra=sorted(path.name for path in audio_dir.glob('*.wav') if path.name not in lengths)
    if extra:
        raise ValueError('data/audio holds WAV files outside the current clip set ('
                         + ', '.join(extra) + '); remove them so the roster set stays exact')
    if not quiet:
        print(f'Validated {len(lengths)} clips, dictionary {dictionary:08x}, '
              f'{source_bytes} WAV bytes, {filesystem_bytes}/{SLOT_BYTES} filesystem bytes '
              '(712 KB slot, compact 8 kHz mu-law estimate)')
    return lengths


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest',action='store_true')
    check(parser.parse_args().write_manifest)
