"""Pack the spoken calls into the LittleFS image for the audio units.

Default output is the compact form: one /audio/<clip>.ulw file per needed
clip from generate_catalog.clips() (p01..p09, l1..l9 and the dNN play clips
whose roster audience includes an audio unit). A .ulw file is:

    magic  "ULW1"                     4 bytes
    count  uint32 little-endian       samples at 8 kHz
    data   G.711 mu-law               1 byte per sample

--pcm instead copies the 16 kHz mono WAV set unchanged (files keep the .wav
names the catalog uses). Both modes write /audio/manifest.txt whose first line
is the 8-hex call dictionary from tools/generate_catalog.py.

Only the littlefs image and an Intel HEX record file at the slot base are
needed here; flashing is tools/flash_audio.ps1. After writing, the files are
verified by tools/verify_audio_fs.py unless --no-verify is passed.

The chosen codec must fit the 712 KB audio slot in full. When the clips and
manifest cannot fit, the build refuses with the exact byte counts and the ways
to shrink (compact codec, unenroll audio units in config/roster.json, or drop
audio-targeted plays); a clip is never truncated.

--root packs a staging tree (config/calls.json, config/roster.json and
data/audio) instead of the repository containing this script; the default
output follows that root.
"""
import argparse
import struct
import sys
import wave
from pathlib import Path

try:
    import littlefs
except ImportError:
    sys.exit('build_audio_fs.py needs the littlefs-python package; see tools/requirements.txt')

import check_audio
from generate_catalog import ROOT, clips, load

# Shared with verify_audio_fs.py so the build and the check cannot drift.
# nRF54L15 internal flash is 1.5 MB with 4 KB pages. The MCUboot update slot
# (slot1_partition) is reused as the audio filesystem:
#   slot0 (app)  base 0x010000, size 712 KB (0xB2000) -> ends at 0x0C2000
#   slot1 (audio) base 0x0C2000 = 0x010000 + 712*1024, size 712 KB
# so the image is exactly 0x0C2000..0x174000, and the Intel HEX base address
# must stay in step with the board's partition manager.
from verify_audio_fs import (BLOCK_COUNT, BLOCK_SIZE, SLOT_BASE, SLOT_BYTES, ULW_MAGIC,
                             AudioFsMismatch, verify)

WAV_RATE = 16000


def mulaw_encode(sample):
    """Standard G.711 mu-law encoding of one signed 16-bit sample."""
    bias = 0x84
    clip = 32635
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    if sample > clip:
        sample = clip
    sample += bias
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0f
    return ~(sign | (exponent << 4) | mantissa) & 0xff


def read_wav(path):
    """Return the raw 16-bit mono 16 kHz frames of one validated clip."""
    with wave.open(str(path), 'rb') as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != WAV_RATE:
            raise ValueError(f'{path.name}: expected mono 16-bit 16 kHz PCM')
        return source.readframes(source.getnframes())


def to_ulw(pcm):
    """Downsample 16 kHz PCM to 8 kHz and mu-law encode it."""
    samples = struct.unpack(f'<{len(pcm) // 2}h', pcm)
    count = len(samples) // 2
    out = bytearray(count)
    for index in range(count):
        out[index] = mulaw_encode((samples[2 * index] + samples[2 * index + 1]) // 2)
    return ULW_MAGIC + struct.pack('<I', count) + bytes(out)


def budget_error(pcm_mode, payload_bytes, note=None):
    """Return the over-budget error naming the bytes and the ways to shrink."""
    codec = '16 kHz PCM' if pcm_mode else 'compact 8 kHz mu-law'
    detail = note or f'over the {SLOT_BYTES}-byte (712 KB) audio slot'
    return ValueError(
        f'The {codec} audio set needs {payload_bytes} bytes of clips plus manifest, '
        f'{detail}. Shrink the set: use the compact '
        '8 kHz mu-law codec, unenroll audio units in config/roster.json, or drop '
        'audio-targeted plays. Clips are never truncated.')


def payloads(pcm_mode, data, root):
    """Return [(littlefs target, payload bytes)] for the needed clip set."""
    root = Path(root)
    result = []
    for name, _ in clips(data):
        source = root / 'data/audio' / name
        if pcm_mode:
            result.append((f'/audio/{name}', source.read_bytes()))
        else:
            result.append((f'/audio/{Path(name).stem}.ulw', to_ulw(read_wav(source))))
    return result


def intel_hex(base, data, width=32):
    """Classic Intel HEX text for data loaded at base, stdlib only."""
    def record(address, kind, payload):
        body = bytes((len(payload) & 0xff, (address >> 8) & 0xff, address & 0xff, kind)) + payload
        return ':' + body.hex().upper() + f'{(-sum(body)) & 0xff:02X}'

    lines = []
    upper = None
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        address = base + offset
        high = address >> 16
        if high != upper:
            upper = high
            lines.append(record(0x0000, 0x04, bytes(((high >> 8) & 0xff, high & 0xff))))
        lines.append(record(address & 0xffff, 0x00, chunk))
    lines.append(':00000001FF')
    return '\n'.join(lines) + '\n'


def build_fs(pcm_mode, data, dictionary, root=ROOT, stats=None):
    """Return the formatted littlefs image bytes for the needed clips under root.

    Refuses before writing when the clips plus manifest cannot fit the slot,
    and converts a LittleFS out-of-space error into the same clear message
    instead of leaving a half-written image behind.
    """
    root = Path(root)
    files = [('/audio/manifest.txt', f'{dictionary:08x}\n'.encode('ascii'))]
    files += payloads(pcm_mode, data, root)
    payload_bytes = sum(len(payload) for _, payload in files)
    if payload_bytes > SLOT_BYTES:
        raise budget_error(pcm_mode, payload_bytes)
    fs = littlefs.LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT)
    fs.makedirs('/audio', exist_ok=True)
    for target, payload in files:
        try:
            with fs.open(target, 'wb') as handle:
                handle.write(payload)
        except littlefs.errors.LittleFSError as error:
            # The fixed image filled up before the set fit.
            if getattr(error, 'code', None) == littlefs.errors.LittleFSError.Error.LFS_ERR_NOSPC:
                raise budget_error(
                    pcm_mode, payload_bytes,
                    f'and the filesystem metadata pushed the {SLOT_BYTES}-byte (712 KB) image over its limit') from error
            raise
    image = bytes(fs.context.buffer)
    if len(image) != SLOT_BYTES:
        raise ValueError(f'LittleFS image is {len(image)} bytes; expected {SLOT_BYTES}')
    if stats is not None:
        stats['clips'] = len(files) - 1
        stats['payload_bytes'] = payload_bytes
        stats['blocks'] = fs.used_block_count
    return image


def pack(pcm_mode=False, output=None, verify_after=True, root=ROOT):
    root = Path(root)
    check_audio.check(root=root, quiet=True)
    data, dictionary = load(root)
    stats = {}
    image = build_fs(pcm_mode, data, dictionary, root=root, stats=stats)
    destination = Path(output) if output else root / 'firmware/build/audio/littlefs.img'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    hex_path = destination.with_suffix('.hex')
    hex_path.write_text(intel_hex(SLOT_BASE, image), encoding='ascii')
    print(f'Packed {stats["clips"]} clips ({"16 kHz PCM" if pcm_mode else "8 kHz mu-law"}), '
          f'dictionary {dictionary:08x}, {stats["payload_bytes"]}/{SLOT_BYTES} clip+manifest bytes, '
          f'{stats["blocks"]}/{BLOCK_COUNT} blocks used')
    print(f'  image: {destination}')
    print(f'  hex:   {hex_path}')
    if verify_after:
        try:
            verify(destination, hex_path, root=root, quiet=True)
        except AudioFsMismatch as error:
            for problem in error.problems:
                print(f'  verify: {problem}', file=sys.stderr)
            raise ValueError(f'verification failed after writing {destination} '
                             f'({len(error.problems)} mismatch(es); the files on disk are not trusted)') from error
        print(f'  verified: manifest, {stats["clips"]} clips, slot size, Intel HEX coverage')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pcm', action='store_true', help='copy the 16 kHz WAVs instead of compact 8 kHz mu-law')
    parser.add_argument('--output', type=Path, help='image path (default firmware/build/audio/littlefs.img); the .hex is written beside it')
    parser.add_argument('--verify', action=argparse.BooleanOptionalAction, default=True,
                        help='verify the written image and Intel HEX with verify_audio_fs.py (default); --no-verify skips it')
    parser.add_argument('--root', type=Path, default=ROOT,
                        help='repository or staging root holding config/calls.json, config/roster.json '
                             'and data/audio (default: the repo containing tools/)')
    args = parser.parse_args()
    try:
        pack(args.pcm, args.output, args.verify, args.root)
    except (OSError, ValueError, KeyError, TypeError, littlefs.errors.LittleFSError) as error:
        parser.exit(1, f'Audio filesystem build failed: {error}\n')


if __name__ == '__main__':
    main()
