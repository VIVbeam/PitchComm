"""Generate local secrets and the firmware header from five IEEE 802.15.4 EUI-64s.

The five units share one closed Thread dataset (channel, PAN ID, extended PAN
ID, network key, mesh-local ULA prefix) and a constant UDP port. Five EUI-64
extended addresses select the role of each physical board. The per-team PSKd is
saved in config/team.local.json only; it is reserved for future joiner-based
commissioning and is not compiled into the firmware.
"""
import argparse
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('coach', 'catcher', 'pitcher', 'shortstop', 'centerfield')
UDP_PORT = 45678
PSKD_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def parse_eui64(text):
    """Validate one 8-byte IEEE 802.15.4 extended address.

    Kept byte-for-byte in the reading order the board prints it
    (AA:BB:CC:DD:EE:FF:00:11 is stored as AA first, wire order).
    """
    if not isinstance(text, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){7}[0-9a-fA-F]{2}', text):
        raise ValueError('Use an EUI-64 like AA:BB:CC:DD:EE:FF:00:11')
    value = bytes.fromhex(text.replace(':', ''))
    if value == bytes(8) or value == b'\xff' * 8:
        raise ValueError('EUI-64 must be nonzero and not all-FF')
    return text.upper()


def eui64(text):
    """argparse type wrapper around parse_eui64."""
    try:
        return parse_eui64(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def channel(text):
    try:
        value = int(text)
    except ValueError:
        value = -1
    if not 11 <= value <= 26:
        raise argparse.ArgumentTypeError('Choose an 802.15.4 channel from 11 to 26')
    return value


def hex_value(text, size, field):
    """Parse one fixed-size, nonzero, not-all-FF hex byte string."""
    if not isinstance(text, str) or not re.fullmatch(f'[0-9a-fA-F]{{{size * 2}}}', text):
        raise ValueError(f'{field} must be {size} bytes of hex')
    value = bytes.fromhex(text)
    if value == bytes(size) or value == b'\xff' * size:
        raise ValueError(f'{field} must be nonzero and not all-FF')
    return value


def normalized(data):
    if not isinstance(data, dict) or not isinstance(data.get('eui64'), dict):
        raise ValueError('Team configuration requires the five role addresses')
    if any(not isinstance(data['eui64'].get(role), str) for role in ROLES):
        raise ValueError('Supply one EUI-64 for each of the five roles')
    addresses = [parse_eui64(data['eui64'][role]) for role in ROLES]
    if len(set(addresses)) != 5:
        raise ValueError('All five units must have different EUI-64 addresses')

    channel_value = data.get('channel')
    if type(channel_value) is not int or not 11 <= channel_value <= 26:
        raise ValueError('Choose an 802.15.4 channel from 11 to 26')

    panid = data.get('panid')
    if isinstance(panid, str) and re.fullmatch(r'0[xX][0-9a-fA-F]{1,4}', panid):
        panid = int(panid, 16)
    if type(panid) is not int or not 1 <= panid <= 0xfffe:
        raise ValueError('PAN ID must be a nonzero 16-bit value other than 0xFFFF')

    name = data.get('network_name')
    if not isinstance(name, str) or not re.fullmatch(r'PitchComm-[0-9a-fA-F]{4}', name):
        raise ValueError('Network name must look like PitchComm-XXXX with four hex digits')
    name = 'PitchComm-' + name[-4:].upper()

    if data.get('udp_port') != UDP_PORT:
        raise ValueError(f'UDP port must be the constant {UDP_PORT}')

    xpanid = hex_value(data.get('xpanid'), 8, 'Extended PAN ID')
    network_key = hex_value(data.get('network_key'), 16, 'Network key')
    prefix = hex_value(data.get('mesh_local_prefix'), 8, 'Mesh-local prefix')
    if prefix[0] != 0xfd:
        raise ValueError('Mesh-local prefix must start with fd (RFC 4193 ULA)')

    pskd = data.get('pskd')
    if not isinstance(pskd, str) or not re.fullmatch(f'[{PSKD_ALPHABET}]{{8,32}}', pskd):
        raise ValueError('PSKd must be 8 to 32 upper-case letters and digits from the PSKd alphabet')

    return {
        'channel': channel_value,
        'network_name': name,
        'panid': panid,
        'udp_port': UDP_PORT,
        'xpanid': xpanid.hex().upper(),
        'network_key': network_key.hex().upper(),
        'mesh_local_prefix': prefix.hex().upper(),
        'pskd': pskd,
        'eui64': dict(zip(ROLES, addresses)),
    }


def atomic_text(path, text):
    # Write beside the destination so replacement stays on the same filesystem.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(text); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def hex_values(value):
    return ', '.join('0x%02x' % byte for byte in value)


def render(data, root=ROOT):
    """Write the firmware header; data must already be normalized."""
    root = Path(root)
    network_key = bytes.fromhex(data['network_key'])
    lines = ['// Local team secrets generated by tools/provision.py. Do not commit or share this file.',
             '#pragma once',
             '',
             '#include <stdint.h>',
             '',
             '#define PC_TEAM_CONFIGURED 1',
             '',
             f'#define PC_TEAM_NETWORK_NAME "{data["network_name"]}"',
             f'#define PC_TEAM_PANID 0x{data["panid"]:04x}',
             f'#define PC_TEAM_CHANNEL {data["channel"]}',
             f'#define PC_TEAM_UDP_PORT {UDP_PORT}',
             '',
             '#define PC_TEAM_XPANID {' + hex_values(bytes.fromhex(data['xpanid'])) + '}',
             '#define PC_TEAM_NETWORK_KEY {' + hex_values(network_key[:8]) + ', \\',
             ' ' * 29 + hex_values(network_key[8:]) + '}',
             '#define PC_TEAM_MESH_LOCAL_PREFIX {' + hex_values(bytes.fromhex(data['mesh_local_prefix'])) + '}',
             '',
             'static const uint8_t team_eui64[5][8] = {']
    for role in ROLES:
        lines.append('  {' + hex_values(bytes.fromhex(data['eui64'][role].replace(':', ''))) + '},')
    lines += ['};', '']
    (root / 'firmware/include/app').mkdir(parents=True, exist_ok=True)
    atomic_text(root / 'firmware/include/app/team_config.h', '\n'.join(lines))


def random_bytes(size):
    while True:
        value = secrets.token_bytes(size)
        if value != bytes(size) and value != b'\xff' * size:
            return value


def generate_data(args):
    prefix = b'\xfd' + random_bytes(7)
    return {
        'channel': args.channel,
        'network_name': 'PitchComm-' + secrets.token_hex(2).upper(),
        'panid': secrets.randbelow(0xfffe) + 1,
        'udp_port': UDP_PORT,
        'xpanid': random_bytes(8).hex().upper(),
        'network_key': random_bytes(16).hex().upper(),
        'mesh_local_prefix': prefix.hex().upper(),
        'pskd': ''.join(secrets.choice(PSKD_ALPHABET) for _ in range(16)),
        'eui64': {role: getattr(args, role) for role in ROLES},
    }


def save(data, root=ROOT):
    """Validate and publish one configuration while holding the setup lock."""
    root = Path(root)
    data = normalized(data)
    (root / 'build').mkdir(parents=True, exist_ok=True)
    lock = root / 'build/validation.lock'
    owner = f'PROVISIONING PID {os.getpid()} TOKEN {secrets.token_hex(16)}\n'.encode('ascii')
    try:
        handle = lock.open('xb')
    except FileExistsError as error:
        raise ValueError('Configuration is already locked. Finish or stop active validation, provisioning, '
                         'audio or catalog generation before removing build/validation.lock.') from error
    identity = os.fstat(handle.fileno())
    try:
        with handle:
            handle.write(owner)
            handle.flush()
            os.fsync(handle.fileno())
        save_locked(data, root)
    finally:
        # Never clear another operation's replacement/interrupted lock.
        try:
            current = lock.stat()
            same_creation = (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino)
            if lock.read_bytes() == owner or same_creation:
                lock.unlink()
        except FileNotFoundError:
            pass


def save_locked(data, root=ROOT):
    root = Path(root)
    data = normalized(data)
    local = root / 'config/team.local.json'
    if local.exists():
        if normalized(json.loads(local.read_text(encoding='utf-8'))) != data:
            raise ValueError('A different local team already exists. Archive the existing configuration before '
                             'deliberate rekeying or changing role addresses.')
    else:
        # Preserve the source values before changing the derived header. If the
        # header write fails, --from-file can finish with exactly these values.
        local.parent.mkdir(parents=True, exist_ok=True)
        atomic_text(local, json.dumps(data, indent=2) + '\n')
    render(data, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ROLES:
        parser.add_argument('--' + role, type=eui64, metavar='EUI64', help=f'{role} extended address')
    parser.add_argument('--channel', type=channel, default=15, help='802.15.4 channel 11..26 (default 15)')
    parser.add_argument('--from-file', type=Path, help='regenerate the header from a saved team.local.json')
    args = parser.parse_args()
    local = ROOT / 'config/team.local.json'
    try:
        if args.from_file:
            data = json.loads(args.from_file.read_text(encoding='utf-8'))
        else:
            if not all(getattr(args, role) for role in ROLES):
                parser.error('Supply all five EUI-64 addresses, or --from-file')
            if local.exists():
                parser.error('A team configuration already exists. Use --from-file config/team.local.json to reuse '
                             'it; archive the old file before deliberate rekeying.')
            data = generate_data(args)
        save(data)
    except (OSError, ValueError, KeyError, TypeError, argparse.ArgumentTypeError) as error:
        parser.exit(1, f'Provisioning failed: {error}\n'
                       'If a configuration was saved, retry with --from-file config/team.local.json.\n')
    print('Wrote config/team.local.json and firmware/include/app/team_config.h. '
          'Warning: team_config.h contains the team network key; treat it as a secret and never commit it. '
          'Secrets were not printed.')


if __name__ == '__main__':
    main()
