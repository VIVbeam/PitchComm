"""Pack the spoken calls into the LittleFS image for the audio units.

Default output is the compact form: one /audio/<clip>.ulw file per call, where
<clip> is the catalog stem (p01..p09, h1..h3, s1..s3). A .ulw file is:

    magic  "ULW1"                     4 bytes
    count  uint32 little-endian       samples at 8 kHz
    data   G.711 mu-law               1 byte per sample

--pcm instead copies the 16 kHz mono WAV set unchanged (files keep the .wav
names the catalog uses). Both modes write /audio/manifest.txt whose first line
is the 8-hex call dictionary from tools/generate_catalog.py.

Only the littlefs image and an Intel HEX record file at the slot base are
needed here; flashing is tools/flash_audio.ps1.
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

# nRF54L15 internal flash is 1.5 MB with 4 KB pages. The MCUboot update slot
# (slot1_partition) is reused as the audio filesystem:
#   slot0 (app)  base 0x010000, size 712 KB (0xB2000) -> ends at 0x0C2000
#   slot1 (audio) base 0x0C2000 = 0x010000 + 712*1024, size 712 KB
# so the image is exactly 0x0C2000..0x174000, and the Intel HEX base address
# below must stay in step with the board's partition manager.
SLOT_BASE = 0x000C2000
SLOT_BYTES = 712 * 1024
BLOCK_SIZE = 4096
BLOCK_COUNT = SLOT_BYTES // BLOCK_SIZE  # 178 blocks, exactly 712 KB

WAV_RATE = 16000
ULW_MAGIC = b'ULW1'


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


def build_fs(pcm_mode, data, dictionary):
    """Return the formatted littlefs image bytes."""
    fs = littlefs.LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT)
    fs.makedirs('/audio', exist_ok=True)
    with fs.open('/audio/manifest.txt', 'wb') as handle:
        handle.write(f'{dictionary:08x}\n'.encode('ascii'))
    for name, _ in clips(data):
        source = ROOT / 'data/audio' / name
        if pcm_mode:
            target, payload = f'/audio/{name}', source.read_bytes()
        else:
            target, payload = f'/audio/{Path(name).stem}.ulw', to_ulw(read_wav(source))
        with fs.open(target, 'wb') as handle:
            handle.write(payload)
    image = bytes(fs.context.buffer)
    if len(image) != SLOT_BYTES:
        raise ValueError(f'LittleFS image is {len(image)} bytes; expected {SLOT_BYTES}')
    return image


def verify_image(image, pcm_mode, data, dictionary):
    """Mount the produced bytes read-only and check every entry."""
    fs = littlefs.LittleFS(context=littlefs.context.UserContext(buffer=bytearray(image)),
                           block_size=BLOCK_SIZE, block_count=BLOCK_COUNT, mount=False)
    fs.mount()
    with fs.open('/audio/manifest.txt', 'rb') as handle:
        if handle.read() != f'{dictionary:08x}\n'.encode('ascii'):
            raise ValueError('Audio manifest does not match the call dictionary')
    for name, _ in clips(data):
        target = f'/audio/{name}' if pcm_mode else f'/audio/{Path(name).stem}.ulw'
        with fs.open(target, 'rb') as handle:
            handle.read()


def pack(pcm_mode=False, output=None):
    check_audio.check(root=ROOT, quiet=True)
    data, dictionary = load(ROOT)
    image = build_fs(pcm_mode, data, dictionary)
    verify_image(image, pcm_mode, data, dictionary)
    destination = Path(output) if output else ROOT / 'firmware/build/audio/littlefs.img'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    hex_path = destination.with_suffix('.hex')
    hex_path.write_text(intel_hex(SLOT_BASE, image), encoding='ascii')
    print(f'Packed {len(clips(data))} clips ({"16 kHz PCM" if pcm_mode else "8 kHz mu-law"}), '
          f'dictionary {dictionary:08x}, {len(image)} bytes at 0x{SLOT_BASE:08X}')
    print(f'  image: {destination}')
    print(f'  hex:   {hex_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pcm', action='store_true', help='copy the 16 kHz WAVs instead of compact 8 kHz mu-law')
    parser.add_argument('--output', type=Path, help='image path (default firmware/build/audio/littlefs.img); the .hex is written beside it')
    args = parser.parse_args()
    try:
        pack(args.pcm, args.output)
    except (OSError, ValueError, KeyError, TypeError, littlefs.errors.LittleFSError) as error:
        parser.exit(1, f'Audio filesystem build failed: {error}\n')


if __name__ == '__main__':
    main()
