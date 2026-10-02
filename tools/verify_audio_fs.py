"""Verify the LittleFS audio image and its Intel HEX record file.

Mounts firmware/build/audio/littlefs.img with littlefs-python and checks:

  - the image is a nonempty multiple of 4096 bytes and fits the 712 KB
    MCUboot audio slot at 0x0C2000..0x174000
  - /audio/manifest.txt is the dictionary from tools/generate_catalog.py
  - every catalog clip resolves to /audio/<stem>.ulw or /audio/<name>.wav
    with a valid header, and .ulw files match their sample counts
  - the Intel HEX records start at 0xC2000, are contiguous, and cover the
    image bytes with matching payloads and valid checksums

All problems are collected and printed together; the exit code is 1 on any
mismatch. tools/build_audio_fs.py calls verify() after writing the files.
"""
import argparse
import struct
import sys
from pathlib import Path

try:
    import littlefs
except ImportError:
    littlefs = None

from generate_catalog import ROOT, clips, load

# nRF54L15 internal flash layout, kept in step with the board's partition
# manager: slot0 (app) is 0x010000 + 712 KB, so the audio slot base is
# 0x010000 + 712 * 1024 = 0x0C2000, and the slot is 712 KB.
SLOT_BASE = 0x000C2000
SLOT_BYTES = 712 * 1024
BLOCK_SIZE = 4096
BLOCK_COUNT = SLOT_BYTES // BLOCK_SIZE  # 178 blocks, exactly 712 KB
ULW_MAGIC = b'ULW1'
WAV_RATE = 16000


class AudioFsMismatch(ValueError):
    """One message per failed check, in self.problems."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__('; '.join(self.problems))


def _read_regular(fs, path):
    """Return the bytes of one regular file, or None when it is missing."""
    try:
        info = fs.stat(path)
    except littlefs.errors.LittleFSError:
        return None
    if info.type != littlefs.lfs.LFSStat.TYPE_REG:
        return None
    with fs.open(path, 'rb') as handle:
        return handle.read()


def wav_frames(data, name):
    """Return the sample count of a mono 16-bit 16 kHz PCM WAV payload.

    Mirrors tools/check_audio.py so the verifier accepts exactly the WAV set
    the builder accepts. Raises ValueError with the clip name on any problem.
    """
    def invalid():
        raise ValueError(f'{name}: invalid WAV; requires mono PCM 16-bit 16 kHz, '
                         'consistent headers and 1..80000 samples')

    size = len(data)
    if size < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        invalid()
    end = 8 + int.from_bytes(data[4:8], 'little')
    if not 44 <= end <= size:
        invalid()
    position = 12
    seen_format = False
    samples = None
    while position + 8 <= end:
        chunk = data[position:position + 8]
        if len(chunk) != 8:
            invalid()
        length = int.from_bytes(chunk[4:], 'little')
        start = position + 8
        if start + length > end:
            invalid()
        if chunk[:4] == b'fmt ':
            if seen_format or length < 16:
                invalid()
            fmt = data[start:start + 16]
            if len(fmt) != 16 or struct.unpack('<HHIIHH', fmt) != (1, 1, WAV_RATE, WAV_RATE * 2, 2, 16):
                invalid()
            seen_format = True
        elif chunk[:4] == b'data':
            if samples is not None or not length or length % 2 or length > 160000:
                invalid()
            samples = length // 2
        position = start + length + (length % 2)
        if position > end:
            invalid()
    if not seen_format or samples is None or position != end:
        invalid()
    return samples


def parse_intel_hex(text):
    """Return the data records of Intel HEX text as [(address, bytes)]."""
    records = []
    upper = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(':'):
            raise ValueError(f'line {number}: missing ":" start code')
        try:
            payload = bytes.fromhex(line[1:])
        except ValueError as error:
            raise ValueError(f'line {number}: not hexadecimal') from error
        if len(payload) < 5:
            raise ValueError(f'line {number}: record is too short')
        count = payload[0]
        if len(payload) != count + 5:
            raise ValueError(f'line {number}: byte count does not match the record length')
        address = (payload[1] << 8) | payload[2]
        kind = payload[3]
        body = payload[4:4 + count]
        if (sum(payload[:4 + count]) + payload[4 + count]) & 0xff:
            raise ValueError(f'line {number}: checksum mismatch')
        if kind == 0x00:
            records.append((upper + address, body))
        elif kind == 0x01:
            break
        elif kind in (0x02, 0x04):
            if len(body) != 2:
                raise ValueError(f'line {number}: record type 0x{kind:02X} needs exactly two payload bytes')
            upper = int.from_bytes(body, 'big') << (4 if kind == 0x02 else 16)
        elif kind in (0x03, 0x05):
            continue
        else:
            raise ValueError(f'line {number}: unsupported record type 0x{kind:02X}')
    return records


def check_hex(records, image):
    """Return the problems found in the parsed Intel HEX data records."""
    if not records:
        return ['Intel HEX has no data records']
    ordered = sorted(records, key=lambda item: item[0])
    problems = []
    start = ordered[0][0]
    if start != SLOT_BASE:
        problems.append(f'Intel HEX starts at 0x{start:X}; expected 0x{SLOT_BASE:X}')
    position = start
    for address, body in ordered:
        if address != position:
            problems.append(f'Intel HEX is not contiguous at 0x{address:X}; expected 0x{position:X}')
            return problems
        position += len(body)
    total = position - start
    if total != len(image):
        problems.append(f'Intel HEX covers {total} bytes; image is {len(image)} bytes')
        return problems
    flat = b''.join(body for _, body in ordered)
    if flat != image:
        for index, (left, right) in enumerate(zip(flat, image)):
            if left != right:
                problems.append(f'Intel HEX differs from the image at 0x{SLOT_BASE + index:X}')
                break
        else:
            problems.append('Intel HEX differs from the image')
    return problems


def verify(image_path=None, hex_path=None, root=ROOT, quiet=False):
    """Run every check against the image and HEX files.

    Raises AudioFsMismatch with one problem per failed check. Returns a small
    summary dictionary on success.
    """
    if littlefs is None:
        raise ValueError('littlefs-python is required; run python -m pip install -r tools/requirements.txt')
    root = Path(root)
    image_path = Path(image_path) if image_path else root / 'firmware/build/audio/littlefs.img'
    hex_path = Path(hex_path) if hex_path else image_path.with_suffix('.hex')
    data, dictionary = load(root)
    expected_manifest = f'{dictionary:08x}\n'.encode('ascii')
    clip_list = list(clips(data))
    problems = []
    image = b''
    clips_seen = 0

    if not image_path.is_file():
        problems.append(f'image not found: {image_path}')
    else:
        image = image_path.read_bytes()
        if not image:
            problems.append(f'image is empty: {image_path}')
        elif len(image) % BLOCK_SIZE:
            problems.append(f'image is {len(image)} bytes, not a multiple of {BLOCK_SIZE}')
        elif len(image) > SLOT_BYTES:
            problems.append(f'image is {len(image)} bytes, over the {SLOT_BYTES}-byte (712 KB) slot')
        else:
            fs = littlefs.LittleFS(context=littlefs.context.UserContext(buffer=bytearray(image)),
                                   block_size=BLOCK_SIZE, block_count=len(image) // BLOCK_SIZE, mount=False)
            try:
                fs.mount()
            except littlefs.errors.LittleFSError as error:
                problems.append(f'cannot mount the LittleFS image: {error}')
            else:
                manifest = _read_regular(fs, '/audio/manifest.txt')
                if manifest is None:
                    problems.append('missing /audio/manifest.txt')
                elif manifest != expected_manifest:
                    problems.append(f'/audio/manifest.txt is {manifest!r}; expected {expected_manifest!r} '
                                    f'for dictionary {dictionary:08x}')
                for name, _ in clip_list:
                    stem = Path(name).stem
                    ulw = _read_regular(fs, f'/audio/{stem}.ulw')
                    wav = None if ulw is not None else _read_regular(fs, f'/audio/{name}')
                    if ulw is None and wav is None:
                        problems.append(f'missing clip {name}: neither /audio/{stem}.ulw nor /audio/{name}')
                        continue
                    clips_seen += 1
                    if ulw is not None:
                        if len(ulw) < 8 or ulw[:4] != ULW_MAGIC:
                            problems.append(f'/audio/{stem}.ulw: bad magic, expected {ULW_MAGIC.decode("ascii")}')
                            continue
                        count = struct.unpack('<I', ulw[4:8])[0]
                        if count == 0 or len(ulw) != 8 + count:
                            problems.append(f'/audio/{stem}.ulw: {len(ulw)} bytes does not match '
                                            f'its sample count {count}')
                    else:
                        try:
                            wav_frames(wav, name)
                        except ValueError as error:
                            problems.append(str(error))

    if not hex_path.is_file():
        problems.append(f'Intel HEX not found: {hex_path}')
    else:
        try:
            records = parse_intel_hex(hex_path.read_text(encoding='ascii'))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            problems.append(f'{hex_path.name}: {error}')
        else:
            problems.extend(check_hex(records, image) if image else [])

    if problems:
        raise AudioFsMismatch(problems)
    if not quiet:
        print(f'Audio filesystem verified: {clips_seen} clips, dictionary {dictionary:08x}, '
              f'image {len(image)}/{SLOT_BYTES} bytes, Intel HEX at 0x{SLOT_BASE:X}')
    return {'clips': clips_seen, 'dictionary': dictionary, 'image_bytes': len(image)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true',
                        help='verify the image and Intel HEX (the default action)')
    parser.add_argument('--image', type=Path, help='image path (default firmware/build/audio/littlefs.img)')
    parser.add_argument('--hex', type=Path, help='Intel HEX path (default beside the image)')
    parser.add_argument('--root', type=Path, default=ROOT, help='repository root')
    parser.add_argument('--quiet', action='store_true', help='only print on failure')
    args = parser.parse_args()
    if littlefs is None:
        parser.exit(1, 'verify_audio_fs.py needs the littlefs-python package; see tools/requirements.txt\n')
    try:
        verify(args.image, args.hex, args.root, args.quiet)
    except AudioFsMismatch as error:
        print(f'Audio filesystem verification failed ({len(error.problems)} mismatch(es)):', file=sys.stderr)
        for problem in error.problems:
            print(f'  - {problem}', file=sys.stderr)
        parser.exit(1)
    except (OSError, ValueError, KeyError, TypeError, littlefs.errors.LittleFSError) as error:
        parser.exit(1, f'Audio filesystem verification failed: {error}\n')


if __name__ == '__main__':
    main()
