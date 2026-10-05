"""Check the installed PitchComm package and local team configuration."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import provision
from catalog import ROOT, load

SLOT_BASE = 0xC2000
SLOT_BYTES = 712 * 1024


def check_hex(text):
    """Require a complete, contiguous data image inside the audio partition."""
    upper = 0
    next_address = SLOT_BASE
    ended = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if ended:
            raise ValueError('Audio image has records after its end-of-file marker.')
        if not re.fullmatch(r':(?:[0-9a-fA-F]{2}){5,}', line):
            raise ValueError(f'Audio image line {number}: invalid HEX record.')
        record = bytes.fromhex(line[1:])
        count = record[0]
        if len(record) != count + 5:
            raise ValueError(f'Audio image line {number}: invalid record length.')
        if sum(record) & 0xff:
            raise ValueError(f'Audio image line {number}: record checksum failed.')
        address = int.from_bytes(record[1:3], 'big')
        kind = record[3]
        body = record[4:-1]
        if kind == 0:
            absolute = upper + address
            if (not count or address + count > 0x10000 or absolute != next_address
                    or absolute + count > SLOT_BASE + SLOT_BYTES):
                raise ValueError(f'Audio image line {number}: data must cover the audio slot contiguously.')
            next_address += count
        elif kind == 1:
            if count or address:
                raise ValueError('Audio image has an invalid end-of-file record.')
            ended = True
        elif kind in (2, 4):
            if count != 2 or address:
                raise ValueError(f'Audio image line {number}: invalid address record.')
            upper = int.from_bytes(body, 'big') << (4 if kind == 2 else 16)
        else:
            raise ValueError(f'Audio image line {number}: unsupported record type.')
    if not ended:
        raise ValueError('Audio image is missing its end-of-file record.')
    if next_address != SLOT_BASE + SLOT_BYTES:
        raise ValueError('Audio image does not fill the complete audio slot.')


def check_audio(image, dictionary):
    image = Path(image)
    package = json.loads((image.parent / 'package.json').read_text(encoding='utf-8'))
    if (not isinstance(package, dict) or package.get('dictionary') != f'{dictionary:08x}'
            or type(package.get('slot_base')) is not int or package['slot_base'] != SLOT_BASE
            or type(package.get('slot_bytes')) is not int or package['slot_bytes'] != SLOT_BYTES):
        raise ValueError('Audio package does not match the firmware catalog or flash layout.')
    content = image.read_bytes()
    if hashlib.sha256(content).hexdigest() != package.get('sha256'):
        raise ValueError('Audio image checksum failed; restore data/audio from the complete package.')
    check_hex(content.decode('ascii'))


def check(root=ROOT, audio_image=None):
    root = Path(root)
    _data, dictionary = load(root)
    local = root / 'config/team.local.json'
    header = root / 'firmware/include/app/team_config.h'
    if local.is_file():
        team = provision.normalized(json.loads(local.read_text(encoding='utf-8')), root)
        if not header.is_file() or header.read_text(encoding='utf-8') != provision.header_text(team, root):
            raise ValueError('Team configuration is incomplete. Run tools/provision.py --from-file config/team.local.json.')
    elif header.is_file():
        raise ValueError('Team header has no saved configuration; restore config/team.local.json.')
    version = (root / 'firmware/ncs_version.txt').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid SDK version in the package.')
    check_audio(root / 'data/audio/littlefs.hex' if audio_image is None else audio_image, dictionary)
    return dictionary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--audio-image', type=Path, help='check a selected audio image and its adjacent package.json')
    args = parser.parse_args()
    try:
        dictionary = check(args.root, args.audio_image)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Setup check failed: {error}\n')
    print(f'Package ready: dictionary {dictionary:08x}.')


if __name__ == '__main__':
    main()
