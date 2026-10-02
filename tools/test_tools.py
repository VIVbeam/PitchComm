"""Regression tests for the PitchComm Python tooling (stdlib only).

Run either of:

    python tools/test_tools.py
    python -m unittest tools.test_tools

Every test works on a disposable temporary directory and passes explicit roots
to the tools, so the repository is only ever read. Where a function resolves
its repository root from a module global (generate_catalog.load/rendered and
check_audio.check), the globals are patched as well. Tests that need the real
repository read config/calls.json, config/roster.json, data/audio,
firmware/include/pc/catalog.h, gui/catalog.json, and
firmware/build/audio/littlefs.img without writing them.
"""
import argparse
import contextlib
import copy
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import audio_transaction
import audit_repo
import check_audio
import generate_catalog
import import_demo_audio
import preflight
import provision
import roster
import verify_audio_fs

try:
    import build_audio_fs
except SystemExit:  # littlefs-python is not installed
    build_audio_fs = None

REAL_ROOT = Path(__file__).resolve().parents[1]
REAL_CALLS = REAL_ROOT / 'config/calls.json'
REAL_ROSTER = REAL_ROOT / 'config/roster.json'
REAL_AUDIO = REAL_ROOT / 'data/audio'
REAL_IMAGE = REAL_ROOT / 'firmware/build/audio/littlefs.img'
REAL_HEX = REAL_IMAGE.with_suffix('.hex')
GIT = shutil.which('git')


AUDIT_RULE_NAMES = [
    'CONFIG_PITCHCOMM_* references',
    'U+2014 em-dash in tracked text files',
    'firmware/src sources in firmware/CMakeLists.txt',
    'generated catalog files',
    'firmware/ncs_version.txt',
    'empty source/tool/gui files',
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def remove_tree(path):
    """Remove a tree even when git left read-only object files on Windows."""
    def force(function, target, _error):
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except OSError:
            pass
    shutil.rmtree(str(path), onerror=force)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args],
                          capture_output=True, text=True, check=True)


def git_init(root):
    git(root, '-c', 'init.defaultBranch=main', 'init', '-q')
    git(root, 'add', '-A')


def real_roster_units():
    """The committed roster units as fresh dictionaries."""
    return copy.deepcopy(json.loads(REAL_ROSTER.read_text(encoding='utf-8'))['units'])


def roster_unit(key, enrolled=True, audio=False, display=True, controls=False, pitches=False,
                short=None, label=None):
    """One complete roster unit; capabilities default to a display-only field unit."""
    if short is None:
        short = key[:4].upper()
    if label is None:
        label = key.replace('_', ' ').title()
    return {'key': key, 'label': label, 'short': short, 'enrolled': enrolled,
            'audio': audio, 'display': display, 'controls': controls, 'pitches': pitches}


def write_roster(root, units, schema=1):
    """Write a roster document under root/config/roster.json."""
    (root / 'config').mkdir(parents=True, exist_ok=True)
    document = {'schema': schema, 'units': units}
    (root / 'config/roster.json').write_text(json.dumps(document), encoding='utf-8')


def config_with(eui64):
    """A valid provision config whose eui64 maps the given unit keys."""
    data = good_config()
    data['eui64'] = dict(eui64)
    return data


def expected_clip_names():
    """The schema 3 + roster clip set for the committed vocabulary."""
    return ([f'p{i:02d}.wav' for i in range(1, 10)] +
            [f'l{i}.wav' for i in range(1, 10)] +
            [f'd{i:02d}.wav' for i in range(1, 18)] +
            ['d20.wav', 'd21.wav'])


def small_calls(targets=('battery',)):
    """A tiny valid vocabulary whose one play resolves against a tiny roster."""
    return {
        'schema': 3,
        'pitches': [
            {'key': 1, 'label': 'FOUR-SEAM', 'short': '4S', 'speech': 'Four-Seam', 'file': 'a.mp3'},
            {'key': 2, 'label': 'CURVEBALL', 'short': 'CB', 'speech': 'Curveball', 'file': 'b.mp3'},
        ],
        'rows': [
            {'key': 1, 'label': 'HIGH', 'short': 'HI', 'speech': 'High'},
            {'key': 2, 'label': 'LOW', 'short': 'LO', 'speech': 'Low'},
        ],
        'cols': [
            {'key': 1, 'label': 'INSIDE', 'short': 'IN', 'speech': 'Inside'},
            {'key': 2, 'label': 'OUTSIDE', 'short': 'OUT', 'speech': 'Outside'},
        ],
        'locations': [{'row': row, 'col': col, 'speech': f'R{row}C{col}',
                       'file': f'r{row}c{col}.mp3'}
                      for row in (1, 2) for col in (1, 2)],
        'plays': [{'key': 1, 'label': 'PLAY', 'shortstop': 'PLAY', 'centerfield': 'PLAY',
                   'speech': 'Play', 'targets': list(targets), 'file': 'p.mp3'}],
    }


def good_config():
    """One fully valid provision.py input, deliberately in mixed case."""
    return {
        'channel': 15,
        'network_name': 'PitchComm-1a2b',
        'panid': 0x1234,
        'udp_port': provision.UDP_PORT,
        'xpanid': '0102030405060708',
        'network_key': '00010203040506070809101112131415',
        'mesh_local_prefix': 'fd00112233445566',
        'pskd': 'ABCDEFGH',
        'eui64': {
            'coach': 'aa:bb:cc:dd:ee:ff:00:01',
            'catcher': 'aa:bb:cc:dd:ee:ff:00:02',
            'pitcher': 'aa:bb:cc:dd:ee:ff:00:03',
            'shortstop': 'aa:bb:cc:dd:ee:ff:00:04',
            'centerfield': 'aa:bb:cc:dd:ee:ff:00:05',
        },
    }


def wav_bytes(frames=100, rate=16000, channels=1, width=2):
    """A valid mono/stereo 16 kHz PCM WAV with silent frames."""
    data = b'\x00' * (frames * channels * width)
    block = channels * width
    return (b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate,
                                    rate * block, block, width * 8)
            + b'data' + struct.pack('<I', len(data)) + data)


def framed_wav(data_length, payload):
    """A WAV whose data chunk declares data_length regardless of payload."""
    fmt = b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16)
    body = fmt + b'data' + struct.pack('<I', data_length) + payload
    return b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WAVE' + body


def hex_record(address, kind, payload):
    body = bytes((len(payload) & 0xff, (address >> 8) & 0xff, address & 0xff, kind)) + payload
    return ':' + body.hex().upper() + f'{(-sum(body)) & 0xff:02X}'


def intel_hex(base, data, width=32):
    """Classic Intel HEX text for data loaded at base (same as build_audio_fs)."""
    lines = []
    upper = None
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        address = base + offset
        high = address >> 16
        if high != upper:
            upper = high
            lines.append(hex_record(0, 0x04, bytes(((high >> 8) & 0xff, high & 0xff))))
        lines.append(hex_record(address & 0xffff, 0x00, chunk))
    lines.append(':00000001FF')
    return '\n'.join(lines) + '\n'


def write_rendered(root):
    """Write the two catalog files rendered() predicts for this root."""
    version, files = generate_catalog.rendered(root)
    for name, contents in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding='utf-8', newline='\n')
    return version


def add_catalog(root, roster=None):
    """Put calls.json, a roster and matching catalog files under root.

    roster=None copies the committed roster; pass a list of unit dictionaries
    for a fixture roster.
    """
    (root / 'config').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_CALLS, root / 'config/calls.json')
    if roster is None:
        shutil.copyfile(REAL_ROSTER, root / 'config/roster.json')
    else:
        write_roster(root, list(roster))
    return write_rendered(root)


def add_synthetic_audio(root, frames=100):
    """Write one tiny but valid WAV per catalog clip under root."""
    data, dictionary = generate_catalog.load(root)
    audio = root / 'data/audio'
    audio.mkdir(parents=True, exist_ok=True)
    for name, _ in generate_catalog.clips(data):
        (audio / name).write_bytes(wav_bytes(frames))
    return data, dictionary


def make_repo_fixture(root, with_git=True):
    """A minimal, clean repository for audit_repo and preflight."""
    version = add_catalog(root)
    (root / 'firmware/src').mkdir(parents=True, exist_ok=True)
    (root / 'firmware/roles').mkdir(parents=True, exist_ok=True)
    (root / 'firmware/Kconfig').write_text(
        'config PITCHCOMM_UNIT\n\tbool "unit"\n\nconfig PITCHCOMM_EXTRA\n\tbool "extra"\n',
        encoding='ascii', newline='\n')
    (root / 'firmware/roles/unit.conf').write_text(
        'CONFIG_PITCHCOMM_UNIT=y\n# CONFIG_PITCHCOMM_EXTRA is not set\n',
        encoding='ascii', newline='\n')
    (root / 'firmware/src/main.c').write_text(
        'int main_source;\n'
        'int unit_uses = CONFIG_PITCHCOMM_UNIT;\n'
        'int extra_uses = CONFIG_PITCHCOMM_EXTRA;\n',
        encoding='ascii', newline='\n')
    (root / 'firmware/CMakeLists.txt').write_text(
        'target_sources(app PRIVATE src/main.c)\n', encoding='ascii', newline='\n')
    (root / 'firmware/ncs_version.txt').write_text('v3.4.0\n', encoding='ascii', newline='\n')
    if with_git:
        git_init(root)
    return version


class TempRepoTestCase(unittest.TestCase):
    """Base class giving every test a self-cleaning temporary directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pitchcomm-test-'))
        self.addCleanup(remove_tree, self.tmp)


# ---------------------------------------------------------------------------
# provision.py: normalized()
# ---------------------------------------------------------------------------

class ProvisionRosterTests(TempRepoTestCase):
    """load_roster, enrolled_keys, unit_keys, assignment parsing and resolution."""

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        self.coach = 'AA:BB:CC:DD:EE:FF:00:01'
        self.addresses = {
            'pitcher': 'AA:BB:CC:DD:EE:FF:00:02',
            'catcher': 'AA:BB:CC:DD:EE:FF:00:03',
            'shortstop': 'AA:BB:CC:DD:EE:FF:00:04',
            'center': 'AA:BB:CC:DD:EE:FF:00:05',
        }
        self.default_units = [roster_unit('pitcher', audio=True, pitches=True),
                              roster_unit('catcher', pitches=True),
                              roster_unit('shortstop'),
                              roster_unit('center')]

    def args(self, **overrides):
        values = {'coach': self.coach, 'unit': [],
                  'catcher': None, 'pitcher': None, 'shortstop': None, 'centerfield': None}
        values.update(overrides)
        return types.SimpleNamespace(**values)

    def assignments(self, **overrides):
        return provision.unit_assignments(self.args(**overrides), self.tmp)

    def full_units(self):
        return [('pitcher', self.addresses['pitcher']),
                ('catcher', self.addresses['catcher']),
                ('shortstop', self.addresses['shortstop']),
                ('center', self.addresses['center'])]

    def test_load_roster_returns_file_order(self):
        write_roster(self.tmp, [
            roster_unit('first', enrolled=False),
            roster_unit('pitcher', audio=True, pitches=True),
            roster_unit('catcher', pitches=True),
        ])
        units = provision.load_roster(self.tmp)
        self.assertEqual([unit['key'] for unit in units], ['first', 'pitcher', 'catcher'])
        self.assertEqual(provision.enrolled_keys(self.tmp), ['pitcher', 'catcher'])
        self.assertEqual(provision.unit_keys(self.tmp), ['coach', 'pitcher', 'catcher'])

    def test_load_roster_rejections(self):
        cases = (
            ({'schema': 2, 'units': [roster_unit('pitcher')]},
             'config/roster.json must be a schema 1 object'),
            ({'schema': 1}, 'roster units must be a list with at least one unit'),
            ({'schema': 1, 'units': []}, 'roster units must be a list with at least one unit'),
            ({'schema': 1, 'units': ['pitcher']}, 'units[1]: must be an object'),
            ({'schema': 1, 'units': [roster_unit('')]}, 'units[1]: key must be text'),
            ({'schema': 1, 'units': [roster_unit('pitcher'), roster_unit('pitcher')]},
             "units[2]: duplicate unit key 'pitcher'"),
            ({'schema': 1, 'units': [roster_unit('pitcher', enrolled='yes')]},
             'units[1]: enrolled must be true or false'),
            ({'schema': 1, 'units': [roster_unit('pitcher', enrolled=False)]},
             'roster must enroll at least one unit'),
        )
        for document, message in cases:
            with self.subTest(message=message):
                (self.tmp / 'config/roster.json').write_text(json.dumps(document), encoding='utf-8')
                with self.assertRaises(ValueError) as ctx:
                    provision.load_roster(self.tmp)
                self.assertIn(message, str(ctx.exception))

    def test_parse_unit_assignment(self):
        key, address = provision.parse_unit_assignment('pitcher=aa:bb:cc:dd:ee:ff:00:02')
        self.assertEqual(key, 'pitcher')
        self.assertEqual(address, 'AA:BB:CC:DD:EE:FF:00:02')
        for text in ('pitcher', '=AA:BB:CC:DD:EE:FF:00:02', 'pitcher=not-an-eui',
                     'pitcher=00:00:00:00:00:00:00:00'):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError):
                    provision.parse_unit_assignment(text)

    def test_unit_assignments_accepts_coach_units_and_legacy_flags(self):
        write_roster(self.tmp, self.default_units)
        addresses = self.assignments(unit=[('pitcher', self.addresses['pitcher']),
                                           ('catcher', self.addresses['catcher'])],
                                     shortstop=self.addresses['shortstop'],
                                     centerfield=self.addresses['center'])
        self.assertEqual(list(addresses), ['coach', 'pitcher', 'catcher', 'shortstop', 'center'])
        self.assertEqual(addresses['coach'], self.coach)
        self.assertEqual(addresses['center'], self.addresses['center'])

    def test_unit_assignments_accepts_an_extra_enrolled_unit(self):
        write_roster(self.tmp, self.default_units[:2] +
                     [roster_unit('first', pitches=True)] + self.default_units[2:])
        addresses = self.assignments(unit=[('pitcher', self.addresses['pitcher']),
                                           ('catcher', self.addresses['catcher']),
                                           ('first', 'AA:BB:CC:DD:EE:FF:00:06'),
                                           ('shortstop', self.addresses['shortstop']),
                                           ('center', self.addresses['center'])])
        self.assertEqual(list(addresses),
                         ['coach', 'pitcher', 'catcher', 'first', 'shortstop', 'center'])

    def test_unit_assignments_rejections(self):
        write_roster(self.tmp, self.default_units + [roster_unit('first', enrolled=False)])
        full = self.full_units()
        cases = (
            (dict(coach=None, unit=full), "Missing EUI-64 for unit 'coach'"),
            (dict(unit=full[:3]), "Missing EUI-64 for unit 'center'"),
            (dict(unit=full + [('nope', self.addresses['pitcher'])]), "Unknown unit key 'nope'"),
            (dict(unit=full + [('first', self.addresses['pitcher'])]),
             "Unit 'first' is not enrolled in config/roster.json"),
            (dict(unit=full + [('pitcher', self.addresses['pitcher'])]),
             "Unit 'pitcher' was supplied more than once with --unit"),
            (dict(unit=full + [('coach', self.addresses['pitcher'])]),
             "Use --coach for unit 'coach', not --unit"),
            (dict(unit=full, pitcher=self.addresses['pitcher']),
             "Unit 'pitcher' was supplied by both --pitcher and --unit"),
            (dict(unit=[('pitcher', self.addresses['pitcher']),
                        ('shortstop', self.addresses['shortstop']),
                        ('center', self.addresses['center'])],
                  catcher=self.coach),
             "Unit 'catcher' reuses the EUI-64 of unit 'coach'"),
            (dict(unit=[('pitcher', 'not-an-eui')]),
             'Use an EUI-64 like AA:BB:CC:DD:EE:FF:00:11'),
        )
        for overrides, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as ctx:
                    self.assignments(**overrides)
                self.assertIn(message, str(ctx.exception))

    def test_legacy_flag_for_an_unenrolled_key_is_rejected(self):
        write_roster(self.tmp, [roster_unit('pitcher', pitches=True), roster_unit('center')])
        with self.assertRaises(ValueError) as ctx:
            self.assignments(unit=[('pitcher', self.addresses['pitcher']),
                                   ('center', self.addresses['center'])],
                             catcher=self.addresses['catcher'])
        self.assertIn("Unit 'catcher' from --catcher is not enrolled in config/roster.json",
                      str(ctx.exception))


class ProvisionNormalizedTests(unittest.TestCase):
    """normalized() against the committed roster (reads only)."""

    def setUp(self):
        self.good = good_config()

    def mutated(self):
        return copy.deepcopy(self.good)

    def assert_rejected(self, mutate, message):
        data = self.mutated()
        mutate(data)
        with self.assertRaises(ValueError) as ctx:
            provision.normalized(data)
        self.assertIn(message, str(ctx.exception))

    def test_accepts_and_normalizes_good_config(self):
        result = provision.normalized(self.good)
        self.assertEqual(result['channel'], 15)
        self.assertEqual(result['udp_port'], provision.UDP_PORT)
        self.assertEqual(result['panid'], 0x1234)
        self.assertEqual(result['network_name'], 'PitchComm-1A2B')
        self.assertEqual(result['xpanid'], '0102030405060708')
        self.assertEqual(result['network_key'], '00010203040506070809101112131415')
        self.assertEqual(result['mesh_local_prefix'], 'FD00112233445566')
        self.assertEqual(result['pskd'], 'ABCDEFGH')
        self.assertEqual(list(result['eui64']), ['coach', 'pitcher', 'catcher', 'shortstop', 'center'])
        self.assertEqual(result['eui64']['coach'], 'AA:BB:CC:DD:EE:FF:00:01')
        self.assertEqual(result['eui64']['center'], 'AA:BB:CC:DD:EE:FF:00:05')
        # normalized() returns a new dictionary and leaves the input alone.
        self.assertEqual(self.good['network_name'], 'PitchComm-1a2b')

    def test_legacy_five_key_file_still_validates(self):
        legacy = self.mutated()
        self.assertEqual(set(legacy['eui64']),
                         {'coach', 'catcher', 'pitcher', 'shortstop', 'centerfield'})
        result = provision.normalized(legacy)
        self.assertEqual(result['eui64']['center'], 'AA:BB:CC:DD:EE:FF:00:05')
        self.assertNotIn('centerfield', result['eui64'])

    def test_rejects_malformed_eui64(self):
        for text in ('', 'AA:BB:CC:DD:EE:FF:00', 'AA:BB:CC:DD:EE:FF:00:01:02',
                     'AA:BB:CC:DD:EE:FF:00:0', 'AABBCCDDEEFF0001',
                     'AA-BB-CC-DD-EE-FF-00-01', 'GG:BB:CC:DD:EE:FF:00:01',
                     'AA:BB:CC:DD:EE:FF:00:GG', 'AA:BB:CC:DD:EE:FF:00: 1'):
            with self.subTest(text=text):
                self.assert_rejected(lambda data, t=text: data['eui64'].__setitem__('coach', t),
                                     'Use an EUI-64 like AA:BB:CC:DD:EE:FF:00:11')

    def test_rejects_all_zero_and_all_ff_eui64(self):
        for text in ('00:00:00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff:ff:ff'):
            with self.subTest(text=text):
                self.assert_rejected(lambda data, t=text: data['eui64'].__setitem__('pitcher', t),
                                     'EUI-64 must be nonzero and not all-FF')

    def test_rejects_duplicate_eui64_addresses(self):
        self.assert_rejected(lambda data: data['eui64'].__setitem__(
            'catcher', data['eui64']['coach']),
            "Unit 'catcher' reuses the EUI-64 of unit 'coach'")
        self.assert_rejected(lambda data: data['eui64'].__setitem__(
            'pitcher', 'aa:bb:cc:dd:ee:ff:00:01'),
            'all units must have different EUI-64 addresses')

    def test_rejects_missing_or_non_string_units(self):
        self.assert_rejected(lambda data: data.__setitem__('eui64', []),
                             'Team configuration requires the eui64 addresses of the coach '
                             'and enrolled units')
        self.assert_rejected(lambda data: data['eui64'].__setitem__('coach', None),
                             "Supply one EUI-64 for unit 'coach'")
        self.assert_rejected(lambda data: data['eui64'].pop('coach'),
                             "Missing EUI-64 for unit 'coach'")
        self.assert_rejected(lambda data: data['eui64'].pop('pitcher'),
                             "Missing EUI-64 for unit 'pitcher'")

    def test_rejects_extra_unenrolled_or_unknown_keys(self):
        self.assert_rejected(lambda data: data['eui64'].__setitem__(
            'first', 'AA:BB:CC:DD:EE:FF:00:06'),
            "Unit 'first' is not enrolled in config/roster.json")
        self.assert_rejected(lambda data: data['eui64'].__setitem__(
            'nope', 'AA:BB:CC:DD:EE:FF:00:06'),
            "Unknown unit key 'nope'")

    def test_rejects_channel_outside_11_to_26(self):
        for value in (0, 10, 27, 99, '15', 15.0, None, True):
            with self.subTest(value=value):
                self.assert_rejected(lambda data, v=value: data.__setitem__('channel', v),
                                     'Choose an 802.15.4 channel from 11 to 26')

    def test_rejects_panid_zero_and_ffff(self):
        for value in (0, 0xFFFF, '0x0000', '0xFFFF', '0x10000', '', True):
            with self.subTest(value=value):
                self.assert_rejected(lambda data, v=value: data.__setitem__('panid', v),
                                     'PAN ID must be a nonzero 16-bit value other than 0xFFFF')

    def test_panid_accepts_hex_string(self):
        data = self.mutated()
        data['panid'] = '0x00a5'
        self.assertEqual(provision.normalized(data)['panid'], 0xA5)

    def test_rejects_bad_network_name(self):
        for value in ('PitchComm-123', 'PitchComm-12345', 'PitchComm-GHIJ',
                      'pitchcomm-1a2b', 'PitchComm-1A2B ', 'PitchComm-',
                      'PitchComm-1A2BEXTRA', '', None):
            with self.subTest(value=value):
                self.assert_rejected(lambda data, v=value: data.__setitem__('network_name', v),
                                     'Network name must look like PitchComm-XXXX with four hex digits')

    def test_rejects_wrong_udp_port(self):
        for value in (0, 45677, 45679, '45678', None):
            with self.subTest(value=value):
                self.assert_rejected(lambda data, v=value: data.__setitem__('udp_port', v),
                                     f'UDP port must be the constant {provision.UDP_PORT}')

    def test_rejects_zero_and_all_ff_keys(self):
        cases = (
            ('xpanid', '00' * 8, 'Extended PAN ID must be nonzero and not all-FF'),
            ('xpanid', 'FF' * 8, 'Extended PAN ID must be nonzero and not all-FF'),
            ('xpanid', '0102', 'Extended PAN ID must be 8 bytes of hex'),
            ('network_key', '00' * 16, 'Network key must be nonzero and not all-FF'),
            ('network_key', 'ff' * 16, 'Network key must be nonzero and not all-FF'),
            ('network_key', '0102', 'Network key must be 16 bytes of hex'),
            ('mesh_local_prefix', '00' * 8, 'Mesh-local prefix must be nonzero and not all-FF'),
            ('mesh_local_prefix', 'FF' * 8, 'Mesh-local prefix must be nonzero and not all-FF'),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                self.assert_rejected(lambda data, f=field, v=value: data.__setitem__(f, v), message)

    def test_rejects_mesh_local_prefix_outside_ula(self):
        self.assert_rejected(lambda data: data.__setitem__('mesh_local_prefix', '0102030405060708'),
                             'Mesh-local prefix must start with fd (RFC 4193 ULA)')

    def test_rejects_bad_pskd(self):
        for value in ('abcdefgh', '1234567', '00000000', 'ABCDEFGHI0', '', None,
                      'ABCDEFGH' * 5):
            with self.subTest(value=value):
                self.assert_rejected(lambda data, v=value: data.__setitem__('pskd', v),
                                     'PSKd must be 8 to 32 upper-case letters and digits '
                                     'from the PSKd alphabet')


# ---------------------------------------------------------------------------
# provision.py: render(), save_locked(), save()
# ---------------------------------------------------------------------------

class ProvisionRenderTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')

    def header_path(self):
        return self.tmp / 'firmware/include/app/team_config.h'

    def normalized(self, data=None):
        return provision.normalized(good_config() if data is None else data, self.tmp)

    def parsed_eui64(self, header):
        marker = 'static const uint8_t team_eui64[PC_TEAM_UNIT_COUNT][8] = {'
        self.assertIn(marker, header)
        block = header.split(marker, 1)[1].split('};', 1)[0]
        rows = re.findall(r'\{([^}]*)\},', block)
        return [':'.join(re.findall(r'0x([0-9a-f]{2})', row)).upper() for row in rows]

    def test_render_writes_unit_count_and_coach_then_enrolled_order(self):
        data = self.normalized()
        provision.render(data, root=self.tmp)
        header = self.header_path().read_text(encoding='utf-8')
        self.assertIn('#pragma once', header)
        self.assertIn('#define PC_TEAM_CONFIGURED 1', header)
        self.assertIn('#define PC_TEAM_NETWORK_NAME "PitchComm-1A2B"', header)
        self.assertIn('#define PC_TEAM_PANID 0x1234', header)
        self.assertIn('#define PC_TEAM_CHANNEL 15', header)
        self.assertIn(f'#define PC_TEAM_UDP_PORT {provision.UDP_PORT}', header)
        self.assertIn('#define PC_TEAM_UNIT_COUNT 5', header)

        xpanid = ', '.join(f'0x{b:02x}' for b in bytes.fromhex(data['xpanid']))
        self.assertIn('#define PC_TEAM_XPANID {' + xpanid + '}', header)
        prefix = ', '.join(f'0x{b:02x}' for b in bytes.fromhex(data['mesh_local_prefix']))
        self.assertIn('#define PC_TEAM_MESH_LOCAL_PREFIX {' + prefix + '}', header)

        key = [f'0x{b:02x}' for b in bytes.fromhex(data['network_key'])]
        self.assertIn('#define PC_TEAM_NETWORK_KEY {' + ', '.join(key[:8]) + ', \\', header)
        self.assertIn('\n' + ' ' * 29 + ', '.join(key[8:]) + '}', header)

        order = ['coach', 'pitcher', 'catcher', 'shortstop', 'center']
        parsed = self.parsed_eui64(header)
        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed, [data['eui64'][unit] for unit in order])
        for address in parsed:
            self.assertEqual(len(address.split(':')), 8)

    def test_render_extra_enrolled_unit(self):
        units = real_roster_units()
        for unit in units:
            if unit['key'] == 'first':
                unit['enrolled'] = True
        write_roster(self.tmp, units)
        data = self.normalized(config_with({
            'coach': 'AA:BB:CC:DD:EE:FF:00:01',
            'pitcher': 'AA:BB:CC:DD:EE:FF:00:02',
            'catcher': 'AA:BB:CC:DD:EE:FF:00:03',
            'first': 'AA:BB:CC:DD:EE:FF:00:06',
            'shortstop': 'AA:BB:CC:DD:EE:FF:00:04',
            'centerfield': 'AA:BB:CC:DD:EE:FF:00:05',
        }))
        provision.render(data, root=self.tmp)
        header = self.header_path().read_text(encoding='utf-8')
        self.assertIn('#define PC_TEAM_UNIT_COUNT 6', header)
        order = ['coach', 'pitcher', 'catcher', 'first', 'shortstop', 'center']
        self.assertEqual(self.parsed_eui64(header), [data['eui64'][unit] for unit in order])

    def test_render_is_deterministic_and_leaves_no_temp_files(self):
        data = self.normalized()
        provision.render(data, root=self.tmp)
        first = self.header_path().read_text(encoding='utf-8')
        provision.render(data, root=self.tmp)
        self.assertEqual(self.header_path().read_text(encoding='utf-8'), first)
        self.assertEqual(list((self.tmp / 'firmware/include/app').glob('.*.tmp')), [])

    def test_header_text_matches_render_bytes_and_is_stable(self):
        data = self.normalized()
        first = provision.header_text(data, self.tmp)
        self.assertEqual(first, provision.header_text(data, self.tmp))
        self.assertIn('#define PC_TEAM_UNIT_COUNT 5', first)
        provision.render(data, root=self.tmp)
        self.assertEqual(self.header_path().read_bytes(), first.encode('utf-8'))

    def test_save_locked_round_trip_and_from_file_reload(self):
        data = self.normalized()
        provision.save_locked(data, root=self.tmp)
        local = self.tmp / 'config/team.local.json'
        self.assertTrue(local.is_file())
        header = self.header_path().read_text(encoding='utf-8')

        # --from-file style reload: read the JSON back, re-normalize and render.
        reloaded = json.loads(local.read_text(encoding='utf-8'))
        self.assertEqual(provision.normalized(reloaded, self.tmp), data)
        provision.save_locked(reloaded, root=self.tmp)
        self.assertEqual(self.header_path().read_text(encoding='utf-8'), header)

    def test_generate_data_save_locked_round_trip(self):
        args = types.SimpleNamespace(
            channel=15,
            coach='aa:bb:cc:dd:ee:ff:00:01',
            unit=[('pitcher', 'aa:bb:cc:dd:ee:ff:00:02'),
                  ('catcher', 'aa:bb:cc:dd:ee:ff:00:03'),
                  ('shortstop', 'aa:bb:cc:dd:ee:ff:00:04'),
                  ('center', 'aa:bb:cc:dd:ee:ff:00:05')],
            catcher=None, pitcher=None, shortstop=None, centerfield=None)
        data = provision.generate_data(args, self.tmp)
        provision.save_locked(data, self.tmp)
        local = json.loads((self.tmp / 'config/team.local.json').read_text(encoding='utf-8'))
        self.assertEqual(provision.normalized(local, self.tmp),
                         provision.normalized(data, self.tmp))
        self.assertTrue(self.header_path().is_file())

    def test_save_locked_rejects_a_different_local_config(self):
        provision.save_locked(self.normalized(), root=self.tmp)
        other = good_config()
        other['channel'] = 16
        with self.assertRaises(ValueError) as ctx:
            provision.save_locked(other, root=self.tmp)
        self.assertIn('different local team', str(ctx.exception))

    def test_save_creates_and_releases_the_validation_lock(self):
        provision.save(good_config(), root=self.tmp)
        self.assertTrue((self.tmp / 'config/team.local.json').is_file())
        self.assertTrue(self.header_path().is_file())
        self.assertFalse((self.tmp / 'build/validation.lock').exists())

    def test_save_refuses_when_lock_is_held(self):
        lock = self.tmp / 'build/validation.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text('VAULT GENERATION PID 1 TOKEN deadbeef\n', encoding='ascii')
        with self.assertRaises(ValueError) as ctx:
            provision.save(good_config(), root=self.tmp)
        self.assertIn('already locked', str(ctx.exception))
        self.assertTrue(lock.exists())
        self.assertFalse((self.tmp / 'config/team.local.json').exists())


# ---------------------------------------------------------------------------
# generate_catalog.py
# ---------------------------------------------------------------------------

class GenerateCatalogTests(unittest.TestCase):

    def load(self):
        return generate_catalog.load(REAL_ROOT)

    def rendered(self):
        return generate_catalog.rendered(REAL_ROOT)

    def c_array(self, header, name, values, boolean=False):
        if boolean:
            body = ''.join(f'  {str(bool(value)).lower()},\n' for value in values)
            expected = f'inline constexpr bool {name}[] = {{\n{body}}}'
        else:
            body = ''.join(f'  {json.dumps(value)},\n' for value in values)
            expected = f'inline constexpr const char* {name}[] = {{\n{body}}}'
        self.assertIn(expected, header)

    def test_load_is_deterministic_and_carries_schema_3_and_units(self):
        first, first_hash = generate_catalog.load(REAL_ROOT)
        second, second_hash = generate_catalog.load(REAL_ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)
        self.assertIsInstance(first_hash, int)
        self.assertEqual(first_hash, 0x299314f6)
        self.assertEqual(first['schema'], 3)
        self.assertEqual([p['key'] for p in first['pitches']], list(range(1, 10)))
        self.assertEqual([r['key'] for r in first['rows']], [1, 2, 3])
        self.assertEqual([c['key'] for c in first['cols']], [1, 2, 3])
        self.assertEqual([p['key'] for p in first['plays']], list(range(1, 22)))
        self.assertEqual(len(first['locations']), len(first['rows']) * len(first['cols']))
        self.assertEqual([(l['row'], l['col']) for l in first['locations']],
                         [(row, col) for row in (1, 2, 3) for col in (1, 2, 3)])
        self.assertEqual(generate_catalog.SCHEMA, 3)
        self.assertEqual(generate_catalog.DISPLAY_LIMIT, 11)
        self.assertEqual(generate_catalog.SHORT_LIMIT, 4)
        self.assertEqual(generate_catalog.ENROLLED_LIMIT, 15)

    def test_load_units_are_enrolled_only_and_all_units_is_the_roster(self):
        data, _ = self.load()
        roster = real_roster_units()
        roster_keys = [unit['key'] for unit in roster]
        enrolled_keys = [unit['key'] for unit in roster if unit['enrolled']]
        self.assertEqual([unit['key'] for unit in data['units']], enrolled_keys)
        self.assertEqual([unit['key'] for unit in data['allUnits']], roster_keys)
        for unit in data['units']:
            self.assertTrue(unit['display'] or unit['audio'] or unit['controls'])

    def test_play_audiences_resolve_groups_against_enrolled_units(self):
        data, _ = self.load()
        by_key = {play['key']: play['audience'] for play in data['plays']}
        enrolled = [unit['key'] for unit in data['units']]
        for play in data['plays']:
            self.assertTrue(play['audience'])
            self.assertEqual(play['audience'], [key for key in enrolled if key in play['audience']])
        self.assertEqual(by_key[1], ['pitcher', 'catcher', 'shortstop'])  # battery + infield
        self.assertEqual(by_key[2], ['pitcher', 'catcher'])               # battery
        self.assertEqual(by_key[13], ['pitcher', 'catcher', 'shortstop', 'center'])  # all
        self.assertEqual(by_key[18], ['center'])                          # outfield
        self.assertEqual(generate_catalog.unit_mask(data, by_key[1]), 2 | 4 | 8)
        self.assertEqual(generate_catalog.unit_mask(data, by_key[13]), 2 | 4 | 8 | 16)
        self.assertEqual(generate_catalog.unit_mask(data, by_key[18]), 16)

    def test_clips_are_pitches_locations_and_audible_plays(self):
        data, _ = self.load()
        clips = generate_catalog.clips(data)
        self.assertEqual([name for name, _ in clips], expected_clip_names())
        self.assertEqual(len(clips), 37)
        self.assertNotIn('d18.wav', [name for name, _ in clips])
        self.assertNotIn('d19.wav', [name for name, _ in clips])
        self.assertEqual(dict(clips)['d20.wav'], 'Pitch Around')
        self.assertEqual(dict(clips)['p01.wav'], 'Four-Seam Fastball')
        self.assertEqual(dict(clips)['l1.wav'], 'High Inside')
        pitch_mask = generate_catalog.unit_mask(
            data, [unit['key'] for unit in data['units'] if unit['pitches']])
        self.assertEqual(pitch_mask, 0x0006)

    def test_rendered_is_deterministic(self):
        version_a, files_a = self.rendered()
        version_b, files_b = self.rendered()
        self.assertEqual(version_a, version_b)
        self.assertEqual(files_a, files_b)
        self.assertEqual(sorted(files_a), ['firmware/include/pc/catalog.h', 'gui/catalog.json'])

    def test_dictionary_is_299314f6_in_generated_and_checked_in_files(self):
        version, files = self.rendered()
        self.assertEqual(version, 0x299314f6)
        self.assertIn('constexpr uint32_t kDictionary = 0x299314f6u;',
                      files['firmware/include/pc/catalog.h'])
        checked_in = (REAL_ROOT / 'firmware/include/pc/catalog.h').read_text(encoding='utf-8')
        self.assertIn('constexpr uint32_t kDictionary = 0x299314f6u;', checked_in)
        catalog = json.loads((REAL_ROOT / 'gui/catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(catalog['dictionary'], '299314f6')
        self.assertEqual(catalog['schema'], 3)

    def test_generated_files_match_checked_in_catalog(self):
        version, files = self.rendered()
        for name, expected in files.items():
            actual = (REAL_ROOT / name).read_text(encoding='utf-8')
            self.assertEqual(actual.replace('\r\n', '\n'), expected, f'{name} drifted from rendered()')
        header = files['firmware/include/pc/catalog.h']
        self.assertEqual(header.count('{Category::Pitch,'), 81)
        self.assertEqual(header.count('{Category::Play,'), 21)

    def test_pitch_entries_have_audience_mask_and_two_clips(self):
        data, _ = self.load()
        _, files = self.rendered()
        header = files['firmware/include/pc/catalog.h']
        pitch_lines = [line for line in header.splitlines()
                       if line.strip().startswith('{Category::Pitch,')]
        self.assertEqual(len(pitch_lines), 81)
        pitches = sorted(data['pitches'], key=lambda x: x['key'])
        rows = sorted(data['rows'], key=lambda x: x['key'])
        cols = sorted(data['cols'], key=lambda x: x['key'])
        per_pitch = len(rows) * len(cols)
        for index, line in enumerate(pitch_lines):
            pitch = pitches[index // per_pitch]
            row = rows[(index % per_pitch) // len(cols)]
            col = cols[index % len(cols)]
            label = f'{pitch["label"]} {row["label"]} {col["label"]}'
            location = (row['key'] - 1) * len(cols) + col['key']
            self.assertIn(f'{{Category::Pitch, {index + 1}, 6, ', line)
            self.assertEqual(line.count(json.dumps(label)), 3, line)
            self.assertIn(f'{{"/audio/p{pitch["key"]:02d}.wav", '
                          f'"/audio/l{location}.wav", ""}}}}', line)

    def test_play_entries_have_audience_masks_and_clip_presence(self):
        data, _ = self.load()
        _, files = self.rendered()
        header = files['firmware/include/pc/catalog.h']
        play_lines = [line for line in header.splitlines()
                      if line.strip().startswith('{Category::Play,')]
        self.assertEqual(len(play_lines), 21)
        audio_mask = generate_catalog.unit_mask(
            data, [unit['key'] for unit in data['units'] if unit['audio']])
        plays = sorted(data['plays'], key=lambda x: x['key'])
        for play, line in zip(plays, play_lines):
            mask = generate_catalog.unit_mask(data, play['audience'])
            fields = ', '.join(json.dumps(play[field])
                               for field in ('label', 'shortstop', 'centerfield'))
            if mask & audio_mask:
                audio = f'{{"/audio/d{play["key"]:02d}.wav", "", ""}}'
            else:
                audio = '{"", "", ""}'
            self.assertIn(f'{{Category::Play, {play["key"]}, {mask}, {fields}, {audio}}},', line)
        self.assertIn(', 18, 16, "SEE DOWN"', header)
        self.assertIn(', 18, 16, "SEE DOWN", "SEE DOWN", "SEE DOWN", {"", "", ""}},', header)

    def test_catalog_defines_unit_tables_and_selectors(self):
        data, _ = self.load()
        _, files = self.rendered()
        header = files['firmware/include/pc/catalog.h']
        self.assertIn('constexpr unsigned kUnitCount = 5;', header)
        self.assertIn('constexpr unsigned kPitchCount = 9;', header)
        self.assertIn('constexpr unsigned kPlayCount = 21;', header)
        self.assertIn('constexpr uint16_t kUnitMask(unsigned unit)', header)
        self.assertIn('uint16_t audience;', header)
        self.assertIn('constexpr const Call* findCall(Category cat, uint16_t code)', header)
        self.assertIn('constexpr uint16_t recipients(Category category, uint16_t code)', header)
        self.assertNotIn('labelFor', header)
        self.assertNotIn('uint8_t recipients(Category', header)

        index = generate_catalog.unit_index(data)
        for unit in data['allUnits']:
            expected = index.get(unit['key'], 0)
            self.assertIn(f'#define PC_UNIT_{unit["key"]} {expected}', header)
        self.assertIn('#define PC_UNIT_pitcher 1', header)
        self.assertIn('#define PC_UNIT_catcher 2', header)
        self.assertIn('#define PC_UNIT_shortstop 3', header)
        self.assertIn('#define PC_UNIT_center 4', header)
        for key in ('first', 'second', 'third', 'left', 'right'):
            self.assertIn(f'#define PC_UNIT_{key} 0', header)

        units = data['units']
        self.c_array(header, 'kUnitLabel', ['Coach'] + [unit['label'] for unit in units])
        self.c_array(header, 'kUnitShort', ['CO'] + [unit['short'] for unit in units])
        self.c_array(header, 'kUnitAudio', [False] + [unit['audio'] for unit in units], boolean=True)
        self.c_array(header, 'kUnitDisplay', [False] + [unit['display'] for unit in units], boolean=True)
        self.c_array(header, 'kUnitControls', [False] + [unit['controls'] for unit in units], boolean=True)
        self.c_array(header, 'kUnitPitches', [False] + [unit['pitches'] for unit in units], boolean=True)

    def test_gui_catalog_carries_units_and_play_audiences(self):
        data, _ = self.load()
        catalog = json.loads((REAL_ROOT / 'gui/catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(catalog['dictionary'], '299314f6')
        self.assertEqual(catalog['schema'], 3)
        self.assertEqual(catalog['units'],
                         [{field: unit[field] for field in generate_catalog.UNIT_FIELDS}
                          for unit in data['units']])
        self.assertEqual(len(catalog['units']), 4)
        self.assertEqual(catalog['pitches'],
                         [{'key': p['key'], 'label': p['label'], 'short': p['short'],
                           'speech': p['speech']} for p in data['pitches']])
        self.assertEqual(catalog['rows'],
                         [{'key': r['key'], 'label': r['label'], 'short': r['short'],
                           'speech': r['speech']} for r in data['rows']])
        self.assertEqual(catalog['cols'],
                         [{'key': c['key'], 'label': c['label'], 'short': c['short'],
                           'speech': c['speech']} for c in data['cols']])
        self.assertEqual(catalog['locations'],
                         [{'row': l['row'], 'col': l['col'], 'speech': l['speech']}
                          for l in data['locations']])
        self.assertEqual(len(catalog['plays']), 21)
        for gui_play, source in zip(catalog['plays'], data['plays']):
            self.assertEqual(gui_play['key'], source['key'])
            self.assertEqual(gui_play['audience'], source['audience'])
            self.assertEqual(gui_play['label'], source['label'])

    def test_rendered_lists_every_audio_clip(self):
        data, _ = self.load()
        version, files = self.rendered()
        header = files['firmware/include/pc/catalog.h']
        clip_names = [name for name, _ in generate_catalog.clips(data)]
        self.assertEqual(len(clip_names), 37)
        for name in clip_names:
            self.assertIn(f'"/audio/{name}"', header)


class GenerateCatalogVariableCountTests(TempRepoTestCase):
    """Schema 3 counts and the roster are data: a small fixture renders its own grid."""

    def test_variable_counts_load_and_render(self):
        calls = small_calls(targets=['battery'])
        (self.tmp / 'config').mkdir(parents=True)
        (self.tmp / 'config/calls.json').write_text(json.dumps(calls), encoding='utf-8')
        write_roster(self.tmp, [roster_unit('pitcher', audio=True, pitches=True),
                                roster_unit('catcher', pitches=True)])

        data, version = generate_catalog.load(self.tmp)
        self.assertEqual(len(data['locations']), 6 - 2)
        self.assertEqual([unit['key'] for unit in data['units']], ['pitcher', 'catcher'])
        self.assertEqual(data['plays'][0]['audience'], ['pitcher', 'catcher'])
        files = generate_catalog.render(data, version)
        header = files['firmware/include/pc/catalog.h']
        self.assertIn('constexpr unsigned kPitchCount = 2;', header)
        self.assertIn('constexpr unsigned kRows = 2;', header)
        self.assertIn('constexpr unsigned kCols = 2;', header)
        self.assertIn('constexpr unsigned kLocationCount = 4;', header)
        self.assertIn('constexpr unsigned kPlayCount = 1;', header)
        self.assertIn('constexpr unsigned kUnitCount = 3;', header)
        self.assertEqual(header.count('{Category::Pitch,'), 8)
        self.assertEqual(header.count('{Category::Play,'), 1)
        # pitch 2, row 2, col 2 -> (2-1)*2*2 + (2-1)*2 + 2 = 8, audience pitcher+catcher = 6
        self.assertIn('{Category::Pitch, 8, 6, "CURVEBALL LOW OUTSIDE"', header)
        self.assertEqual([name for name, _ in generate_catalog.clips(data)],
                         ['p01.wav', 'p02.wav', 'l1.wav', 'l2.wav', 'l3.wav', 'l4.wav', 'd01.wav'])
        with self.assertRaises(ValueError):
            generate_catalog.pitch_code(3, 1, 1, 2, 2, 2)


class GenerateCatalogRosterTests(TempRepoTestCase):
    """Malformed rosters and targets, plus enrollment-dependent unit mapping."""

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)

    def write(self, units=None, calls=None, schema=1):
        if calls is None:
            shutil.copyfile(REAL_CALLS, self.tmp / 'config/calls.json')
        else:
            (self.tmp / 'config/calls.json').write_text(json.dumps(calls), encoding='utf-8')
        if units is not None:
            write_roster(self.tmp, units, schema=schema)

    def assert_load_error(self, message, units=None, calls=None, schema=1):
        self.write(units, calls, schema)
        with self.assertRaises(ValueError) as ctx:
            generate_catalog.load(self.tmp)
        self.assertIn(message, str(ctx.exception))

    def test_malformed_roster(self):
        sixteen = [roster_unit(f'u{index:02d}', audio=True, pitches=True) for index in range(1, 17)]
        cases = (
            ('config/roster.json must be a schema 1 object', real_roster_units(), None, 2),
            ('config/roster.json must be a schema 1 object', real_roster_units(), None, 1.0),
            ('roster units must be a list with at least one unit', [], None, 1),
            ('units[1]: must be an object', ['pitcher'], None, 1),
            ('units[1]: key must be a C identifier '
             '(letter or underscore, then letters, digits or underscores)',
             [roster_unit('1st')], None, 1),
            ("units[2]: duplicate unit key 'pitcher'",
             [roster_unit('pitcher', pitches=True), roster_unit('pitcher')], None, 1),
            ('units[1]: short must be at most 4 characters',
             [roster_unit('pitcher', pitches=True, short='ABCDE')], None, 1),
            ('units[1]: audio must be a boolean',
             [dict(roster_unit('pitcher', pitches=True), audio='yes')], None, 1),
            ('roster must enroll at least one unit',
             [roster_unit('pitcher', enrolled=False)], None, 1),
            ('roster must enroll at least one unit with the pitches capability',
             [roster_unit('pitcher', pitches=False)], None, 1),
            ('roster enrolls 16 units; at most 15 fit the 16-bit unit mask', sixteen, None, 1),
        )
        for message, units, calls, schema in cases:
            with self.subTest(message=message):
                self.assert_load_error(message, units=units, calls=calls, schema=schema)

    def test_malformed_play_targets(self):
        cases = (
            (lambda play: play.pop('targets'), 'plays[1]: targets must be a nonempty list'),
            (lambda play: play.__setitem__('targets', []), 'plays[1]: targets must be a nonempty list'),
            (lambda play: play.__setitem__('targets', 'battery'), 'plays[1]: targets must be a nonempty list'),
            (lambda play: play.__setitem__('targets', [1]),
             'plays[1]: targets must be nonempty strings without leading or trailing spaces'),
            (lambda play: play.__setitem__('targets', [' pitcher']),
             'plays[1]: targets must be nonempty strings without leading or trailing spaces'),
            (lambda play: play.__setitem__('targets', ['bullpen']),
             "plays[1]: target 'bullpen' is not a group or roster key"),
            (lambda play: play.__setitem__('targets', ['nope']),
             "plays[1]: target 'nope' is not a group or roster key"),
            (lambda play: play.__setitem__('targets', ['first']),
             'plays[1]: targets reach no enrolled unit'),
        )
        for mutate, message in cases:
            with self.subTest(message=message):
                calls = json.loads(REAL_CALLS.read_text(encoding='utf-8'))
                mutate(calls['plays'][0])
                self.assert_load_error(message, units=real_roster_units(), calls=calls)

    def test_groups_resolve_against_the_enrolled_roster(self):
        self.write(real_roster_units())
        data, _ = generate_catalog.load(self.tmp)
        by_key = {play['key']: play['audience'] for play in data['plays']}
        self.assertEqual(by_key[2], ['pitcher', 'catcher'])  # battery
        self.assertEqual(by_key[13], ['pitcher', 'catcher', 'shortstop', 'center'])  # all
        self.assertEqual(by_key[18], ['center'])  # outfield, only center enrolled
        self.assertEqual(generate_catalog.unit_mask(data, by_key[13]), 2 | 4 | 8 | 16)

    def test_extra_enrolled_unit_changes_indices_masks_and_macros(self):
        units = real_roster_units()
        for unit in units:
            if unit['key'] == 'first':
                unit['enrolled'] = True
        self.write(units)
        data, version = generate_catalog.load(self.tmp)
        self.assertNotEqual(version, 0x299314f6)
        self.assertEqual([unit['key'] for unit in data['units']],
                         ['pitcher', 'catcher', 'first', 'shortstop', 'center'])
        index = generate_catalog.unit_index(data)
        self.assertEqual(index['first'], 3)
        self.assertEqual(index['shortstop'], 4)
        self.assertEqual(index['center'], 5)
        _, files = generate_catalog.rendered(self.tmp)
        header = files['firmware/include/pc/catalog.h']
        self.assertIn('constexpr unsigned kUnitCount = 6;', header)
        self.assertIn('#define PC_UNIT_first 3', header)
        self.assertIn('#define PC_UNIT_shortstop 4', header)
        self.assertIn('#define PC_UNIT_center 5', header)
        by_key = {play['key']: play['audience'] for play in data['plays']}
        self.assertEqual(by_key[1], ['pitcher', 'catcher', 'first', 'shortstop'])
        self.assertEqual(by_key[13], ['pitcher', 'catcher', 'first', 'shortstop', 'center'])
        self.assertEqual(generate_catalog.unit_mask(data, by_key[1]), 2 | 4 | 8 | 16)
        self.assertEqual(generate_catalog.unit_mask(data, by_key[13]), 2 | 4 | 8 | 16 | 32)
        self.assertEqual([name for name, _ in generate_catalog.clips(data)],
                         expected_clip_names())

    def test_audience_order_follows_roster_order_not_target_order(self):
        units = [roster_unit('catcher', pitches=True, controls=True),
                 roster_unit('pitcher', audio=True, pitches=True)]
        self.write(units, calls=small_calls(targets=['pitcher', 'catcher']))
        data, _ = generate_catalog.load(self.tmp)
        self.assertEqual(data['plays'][0]['audience'], ['catcher', 'pitcher'])
        self.assertEqual(generate_catalog.unit_mask(data, data['plays'][0]['audience']), 0b110)
        self.assertEqual(generate_catalog.unit_index(data), {'catcher': 1, 'pitcher': 2})

    def test_dictionary_changes_with_enrollment(self):
        self.write(real_roster_units())
        _, real_version = generate_catalog.load(self.tmp)
        self.assertEqual(real_version, 0x299314f6)
        units = real_roster_units()
        for unit in units:
            if unit['key'] == 'center':
                unit['audio'] = True
        self.write(units)
        _, changed_version = generate_catalog.load(self.tmp)
        self.assertNotEqual(changed_version, real_version)
        self.assertEqual(changed_version, generate_catalog.load(self.tmp)[1])


class GenerateCatalogInvalidTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')
        self.path = self.tmp / 'config/calls.json'
        self.good = json.loads(REAL_CALLS.read_text(encoding='utf-8'))

    def calls(self):
        return copy.deepcopy(self.good)

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def assert_load_rejected(self, data, message):
        self.write(data)
        with self.assertRaises(ValueError) as ctx:
            generate_catalog.load(self.tmp)
        self.assertIn(message, str(ctx.exception))

    def test_requires_schema_3(self):
        calls = self.calls()
        calls['schema'] = 2
        self.assert_load_rejected(calls, 'config/calls.json must be a schema 3 object')
        calls = self.calls()
        del calls['schema']
        self.assert_load_rejected(calls, 'config/calls.json must be a schema 3 object')
        calls = self.calls()
        calls['schema'] = 3.0
        self.assert_load_rejected(calls, 'config/calls.json must be a schema 3 object')
        calls = self.calls()
        calls['schema'] = '3'
        self.assert_load_rejected(calls, 'config/calls.json must be a schema 3 object')

    def test_missing_rows(self):
        calls = self.calls()
        del calls['rows'][1]  # leaves keys 1 and 3, no longer contiguous
        self.assert_load_rejected(calls, 'rows must define keys 1 through 2 exactly once')
        calls = self.calls()
        calls['rows'] = []
        self.assert_load_rejected(calls, 'rows must be a list with at least one item')

    def test_non_contiguous_keys(self):
        for group in ('pitches', 'rows', 'cols', 'plays'):
            with self.subTest(group=group):
                calls = self.calls()
                del calls[group][1]
                remaining = len(self.good[group]) - 1
                self.assert_load_rejected(
                    calls, f'{group} must define keys 1 through {remaining} exactly once')

    def test_duplicate_keys(self):
        calls = self.calls()
        calls['pitches'][1]['key'] = calls['pitches'][0]['key']
        self.assert_load_rejected(calls, 'pitches must define keys 1 through 9 exactly once')
        calls = self.calls()
        calls['rows'][2]['key'] = 1
        self.assert_load_rejected(calls, 'rows must define keys 1 through 3 exactly once')

    def test_mismatched_location_count(self):
        calls = self.calls()
        calls['locations'] = calls['locations'][:8]
        self.assert_load_rejected(calls, 'locations must hold rows*cols = 9 entries')
        calls = self.calls()
        calls['locations'].append(calls['locations'][0].copy())
        self.assert_load_rejected(calls, 'locations must hold rows*cols = 9 entries')
        calls = self.calls()
        calls['cols'] = calls['cols'][:2]  # 3 rows x 2 cols still needs 6 locations
        self.assert_load_rejected(calls, 'locations must hold rows*cols = 6 entries')

    def test_out_of_range_row_col(self):
        calls = self.calls()
        calls['locations'][0]['row'] = 2
        self.assert_load_rejected(calls, 'locations[1] must be row 1 col 1 in row-major order')
        calls = self.calls()
        calls['locations'][7]['col'] = 3
        self.assert_load_rejected(calls, 'locations[8] must be row 3 col 2 in row-major order')
        calls = self.calls()
        calls['locations'][4]['row'] = '2'
        self.assert_load_rejected(calls, 'locations[5] must be row 2 col 2 in row-major order')

    def test_overlong_label_and_short(self):
        calls = self.calls()
        calls['pitches'][0]['label'] = 'SUPERFASTBALL'
        self.assert_load_rejected(calls, 'pitches[1]: label must be at most 11 characters')
        calls = self.calls()
        calls['pitches'][0]['short'] = 'ABCDE'
        self.assert_load_rejected(calls, 'pitches[1]: short must be at most 4 characters')
        calls = self.calls()
        calls['rows'][0]['label'] = 'HIGH ENOUGHY'
        self.assert_load_rejected(calls, 'rows[1]: label must be at most 11 characters')
        calls = self.calls()
        calls['cols'][0]['label'] = 'OUTSIDE PLUS'
        self.assert_load_rejected(calls, 'cols[1]: label must be at most 11 characters')
        calls = self.calls()
        calls['plays'][0]['label'] = 'TAKE THE BASE'
        self.assert_load_rejected(calls, 'plays[1]: label must be at most 11 characters')
        calls = self.calls()
        calls['plays'][0]['shortstop'] = 'TAKE THE BASE'
        self.assert_load_rejected(calls, 'plays[1]: shortstop must be at most 11 characters')
        calls = self.calls()
        calls['plays'][0]['centerfield'] = 'TAKE THE BASE'
        self.assert_load_rejected(calls, 'plays[1]: centerfield must be at most 11 characters')

    def test_labels_and_shorts_accept_the_limits(self):
        calls = self.calls()
        calls['pitches'][0]['label'] = 'ELEVEN CHRS'  # exactly 11 characters
        calls['pitches'][0]['short'] = 'ABCD'  # exactly 4 characters
        calls['plays'][0]['label'] = 'TAKE BASE 2'  # exactly 11 characters
        self.write(calls)
        data, _ = generate_catalog.load(self.tmp)
        self.assertEqual(data['pitches'][0]['label'], 'ELEVEN CHRS')
        self.assertEqual(data['pitches'][0]['short'], 'ABCD')
        self.assertEqual(data['plays'][0]['label'], 'TAKE BASE 2')

    def test_overlong_speech(self):
        calls = self.calls()
        calls['pitches'][0]['speech'] = 'A' * 81
        self.assert_load_rejected(calls, 'pitches[1]: speech must be at most 80 characters')

    def test_non_printable_or_padded_text(self):
        calls = self.calls()
        calls['pitches'][0]['label'] = ' FASTBALL'
        self.assert_load_rejected(
            calls, 'pitches[1]: label must be a nonempty string without leading or trailing spaces')
        calls = self.calls()
        calls['pitches'][0]['label'] = 'FASTB\u00c4LL'
        self.assert_load_rejected(calls, 'pitches[1]: label must be printable ASCII')

    def test_file_must_be_a_plain_name(self):
        calls = self.calls()
        calls['pitches'][0]['file'] = 'sub/dir/pitch.mp3'
        self.assert_load_rejected(
            calls, 'pitches[1]: file must be a plain name under College Demo Tracks')

    def test_empty_group_is_rejected(self):
        for group in ('pitches', 'rows', 'cols', 'plays'):
            with self.subTest(group=group):
                calls = self.calls()
                calls[group] = []
                self.assert_load_rejected(calls, f'{group} must be a list with at least one item')

    def test_rendered_propagates_validation_failure(self):
        calls = self.calls()
        calls['schema'] = 2
        self.write(calls)
        with self.assertRaises(ValueError):
            generate_catalog.rendered(self.tmp)


# ---------------------------------------------------------------------------
# roster.py (enrollment CLI)
# ---------------------------------------------------------------------------

class RosterCliTests(TempRepoTestCase):
    """roster.py list/enable/disable run in-process against a staged root."""

    def setUp(self):
        super().setUp()
        add_catalog(self.tmp)
        self.roster_path = self.tmp / 'config/roster.json'
        self.original_roster = self.roster_path.read_bytes()

    def run_roster(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = roster.main([*arguments, '--root', str(self.tmp)])
        return code, stdout.getvalue(), stderr.getvalue()

    def run_roster_error(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                roster.main([*arguments, '--root', str(self.tmp)])
        self.assertEqual(ctx.exception.code, 1)
        return stdout.getvalue(), stderr.getvalue()

    def assert_roster_error(self, arguments, message):
        before = self.roster_path.read_bytes()
        _, stderr = self.run_roster_error(*arguments)
        self.assertTrue(stderr.startswith('roster: '), stderr)
        self.assertEqual(stderr.count('\n'), 1, stderr)
        self.assertIn(message, stderr)
        self.assertEqual(self.roster_path.read_bytes(), before)
        self.assert_no_side_outputs()

    def assert_no_side_outputs(self):
        self.assertFalse((self.tmp / 'config/team.local.json').exists())
        self.assertFalse((self.tmp / 'data/audio').exists())
        self.assertFalse((self.tmp / 'firmware/build').exists())

    def unit_by_key(self, key):
        document = json.loads(self.roster_path.read_text(encoding='utf-8'))
        return next(unit for unit in document['units'] if unit['key'] == key)

    def test_list_shows_coach_and_every_unit_in_order(self):
        code, out, err = self.run_roster('list')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), list(roster.HEADERS))
        rows = lines[1:]
        self.assertEqual([row.split()[1] for row in rows],
                         ['coach'] + [unit['key'] for unit in real_roster_units()])
        expected_numbers = {'coach': 0}
        index = 0
        for unit in real_roster_units():
            if unit['enrolled']:
                index += 1
            expected_numbers[unit['key']] = index if unit['enrolled'] else 0
        self.assertEqual({row.split()[1]: int(row.split()[0]) for row in rows}, expected_numbers)
        self.assertEqual(rows[0].split()[5], '-')
        self.assertTrue(all(row.split()[-1] == 'no' for row in rows))
        self.assertEqual(self.roster_path.read_bytes(), self.original_roster)
        self.assert_no_side_outputs()

    def test_enable_first_regenerates_catalog_and_disable_restores(self):
        code, out, err = self.run_roster('enable', 'first')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        first = self.unit_by_key('first')
        self.assertTrue(first['enrolled'])
        self.assertEqual({field: first[field] for field in roster.CAPABILITY_FIELDS},
                         {'audio': False, 'display': True, 'controls': False, 'pitches': False})
        data, version = generate_catalog.load(self.tmp)
        self.assertNotEqual(version, 0x299314f6)
        by_key = {play['key']: play['audience'] for play in data['plays']}
        self.assertIn('first', by_key[1])
        self.assertIn('first', by_key[13])
        self.assertEqual(by_key[18], ['center'])
        catalog = (self.tmp / 'firmware/include/pc/catalog.h').read_text(encoding='utf-8')
        self.assertIn('constexpr unsigned kUnitCount = 6;', catalog)
        self.assertIn('#define PC_UNIT_first 3', catalog)
        self.assertIn("Enabled unit 'first'.", out)
        self.assertIn('python tools/provision.py --coach <EUI-64> --unit first=<EUI-64>', out)
        self.assertIn('tools\\build_firmware.ps1 -Units first', out)
        self.assertNotIn('python tools/import_demo_audio.py', out)
        self.assertNotIn('python tools/build_audio_fs.py', out)
        self.assert_no_side_outputs()

        code, out, err = self.run_roster('disable', 'first')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        self.assertEqual(self.roster_path.read_bytes(), self.original_roster)
        restored, restored_version = generate_catalog.load(self.tmp)
        self.assertEqual(restored_version, 0x299314f6)
        catalog = (self.tmp / 'firmware/include/pc/catalog.h').read_text(encoding='utf-8')
        self.assertIn('constexpr unsigned kUnitCount = 5;', catalog)
        self.assertIn('#define PC_UNIT_first 0', catalog)
        self.assertIn("Disabled unit 'first'.", out)
        self.assertIn('preflight will flag the drift', out)
        self.assert_no_side_outputs()

    def test_enable_left_audio_adds_outfield_play_clips_and_audio_steps(self):
        before = {name for name, _ in generate_catalog.clips(generate_catalog.load(self.tmp)[0])}
        self.assertNotIn('d18.wav', before)
        code, out, err = self.run_roster('enable', 'left', '--audio')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        data, _ = generate_catalog.load(self.tmp)
        after = {name for name, _ in generate_catalog.clips(data)}
        self.assertEqual(after - before, {'d18.wav', 'd19.wav'})
        self.assertTrue(self.unit_by_key('left')['audio'])
        self.assertEqual({play['key']: play['audience'] for play in data['plays']}[18],
                         ['left', 'center'])
        self.assertIn('python tools/import_demo_audio.py', out)
        self.assertIn('python tools/build_audio_fs.py', out)
        self.assert_no_side_outputs()

    def test_display_only_enable_does_not_print_audio_steps(self):
        before = {name for name, _ in generate_catalog.clips(generate_catalog.load(self.tmp)[0])}
        code, out, err = self.run_roster('enable', 'right')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        after = {name for name, _ in generate_catalog.clips(generate_catalog.load(self.tmp)[0])}
        self.assertEqual(after, before)
        self.assertNotIn('python tools/import_demo_audio.py', out)
        self.assertNotIn('python tools/build_audio_fs.py', out)
        self.assert_no_side_outputs()

    def test_unknown_key_fails_one_line_and_leaves_roster(self):
        self.assert_roster_error(['enable', 'nope'],
                                 "Unknown unit key 'nope'; known keys: pitcher, catcher, first")

    def test_controls_without_display_fails_one_line_and_leaves_roster(self):
        self.assert_roster_error(['enable', 'first', '--no-display', '--controls'],
                                 "Unit 'first' has controls without display")

    def test_disabling_the_last_pitches_unit_fails_one_line_and_leaves_roster(self):
        code, out, err = self.run_roster('disable', 'catcher')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        self.assert_roster_error(['disable', 'pitcher'],
                                 "Cannot disable 'pitcher': it is the last enrolled unit "
                                 'with the pitches capability')

    def test_repeated_enable_is_byte_idempotent(self):
        code, _, err = self.run_roster('enable', 'first')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        first_bytes = self.roster_path.read_bytes()
        first_header = (self.tmp / 'firmware/include/pc/catalog.h').read_bytes()
        code, _, err = self.run_roster('enable', 'first')
        self.assertEqual(code, 0)
        self.assertEqual(err, '')
        self.assertEqual(self.roster_path.read_bytes(), first_bytes)
        self.assertEqual((self.tmp / 'firmware/include/pc/catalog.h').read_bytes(), first_header)
        self.assert_no_side_outputs()


# ---------------------------------------------------------------------------
# check_audio.py
# ---------------------------------------------------------------------------

class WavFramesTests(TempRepoTestCase):

    def write_wav(self, name, payload):
        path = self.tmp / name
        path.write_bytes(payload)
        return path

    def assert_invalid(self, path):
        with self.assertRaises(ValueError) as ctx:
            check_audio.wav_frames(path)
        self.assertIn('invalid receiver WAV', str(ctx.exception))
        self.assertIn(path.name, str(ctx.exception))

    def test_accepts_real_clips(self):
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')
        data, _ = generate_catalog.load(REAL_ROOT)
        real_clips = generate_catalog.clips(data)
        self.assertEqual(len(real_clips), 37)
        self.assertEqual([name for name, _ in real_clips], expected_clip_names())
        for name, _ in real_clips:
            path = REAL_AUDIO / name
            self.assertTrue(path.is_file(), f'missing real clip {path}')
            frames = check_audio.wav_frames(path)
            self.assertGreater(frames, 0, name)
            self.assertLessEqual(frames, 80000, name)

    def test_manifest_matches_the_new_dictionary_and_clip_list(self):
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')
        data, dictionary = generate_catalog.load(REAL_ROOT)
        manifest = (REAL_AUDIO / 'manifest.txt').read_text(encoding='ascii')
        self.assertEqual(manifest, check_audio.manifest_text(dictionary, data))
        self.assertEqual(manifest.splitlines()[0], '299314f6')
        self.assertEqual(manifest.splitlines()[1:], expected_clip_names())

    def test_old_three_clip_files_are_gone(self):
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')
        for name in ('h1.wav', 'h2.wav', 'h3.wav', 's1.wav', 's2.wav', 's3.wav'):
            self.assertFalse((REAL_AUDIO / name).exists(), name)

    def test_real_audio_set_passes_full_check(self):
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')
        check_audio.check(root=REAL_ROOT, quiet=True)

    def test_verify_wav_frames_agrees_with_check_audio(self):
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')
        data, _ = generate_catalog.load(REAL_ROOT)
        for name, _ in generate_catalog.clips(data):
            path = REAL_AUDIO / name
            self.assertTrue(path.is_file(), f'missing real clip {path}')
            self.assertEqual(check_audio.wav_frames(path),
                             verify_audio_fs.wav_frames(path.read_bytes(), name), name)

    def test_rejects_truncated_header(self):
        for payload in (b'', b'RIFF', wav_bytes(0)[:12], wav_bytes(0)[:43]):
            with self.subTest(length=len(payload)):
                self.assert_invalid(self.write_wav('short.wav', payload))

    def test_rejects_wrong_sample_rate(self):
        self.assert_invalid(self.write_wav('rate.wav', wav_bytes(100, rate=8000)))

    def test_rejects_stereo(self):
        self.assert_invalid(self.write_wav('stereo.wav', wav_bytes(100, channels=2)))

    def test_rejects_odd_data_length(self):
        self.assert_invalid(self.write_wav('odd.wav', framed_wav(3, b'\x01\x02\x03\x00')))

    def test_rejects_oversize_data(self):
        self.assert_invalid(self.write_wav('big.wav', framed_wav(160002, b'\x00' * 160002)))

    def test_rejects_riff_size_beyond_file(self):
        payload = bytearray(wav_bytes(100))
        payload[4:8] = struct.pack('<I', 0xFFFFFF)
        self.assert_invalid(self.write_wav('longriff.wav', bytes(payload)))

    def test_rejects_zero_sample_data(self):
        self.assert_invalid(self.write_wav('empty.wav', wav_bytes(0)))


class CheckAudioTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_CALLS, self.tmp / 'config/calls.json')
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')
        self.data, self.dictionary = add_synthetic_audio(self.tmp)

    def manifest(self):
        return self.tmp / 'data/audio/manifest.txt'

    def expected_manifest(self):
        return check_audio.manifest_text(self.dictionary, self.data)

    def test_write_manifest_then_validate(self):
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        self.assertEqual(self.manifest().read_text(encoding='ascii'), self.expected_manifest())
        check_audio.check(root=self.tmp, quiet=True)

    def test_wrong_dictionary_manifest_rejected(self):
        self.manifest().write_text('deadbeef\n', encoding='ascii')
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(root=self.tmp, quiet=True)
        self.assertIn('Manifest does not match the call dictionary or clip list',
                      str(ctx.exception))

    def test_missing_manifest_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(root=self.tmp, quiet=True)
        self.assertIn('Manifest does not match the call dictionary or clip list',
                      str(ctx.exception))

    def test_global_roots_can_be_patched(self):
        with mock.patch.object(check_audio, 'ROOT', self.tmp), \
                mock.patch.object(generate_catalog, 'ROOT', self.tmp):
            check_audio.check(write_manifest=True, quiet=True)
        self.assertEqual(self.manifest().read_text(encoding='ascii'), self.expected_manifest())

    def test_broken_clip_is_named(self):
        (self.tmp / 'data/audio/p02.wav').write_bytes(b'RIFF')
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(root=self.tmp, quiet=True)
        self.assertIn('p02.wav', str(ctx.exception))

    def test_pitch_plus_location_over_five_seconds_rejected(self):
        (self.tmp / 'data/audio/p01.wav').write_bytes(wav_bytes(40000))
        (self.tmp / 'data/audio/l1.wav').write_bytes(wav_bytes(40001))
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        self.assertIn('Pitch p01.wav plus location l1.wav exceeds five seconds',
                      str(ctx.exception))

    def test_clip_set_is_pitches_locations_and_play_clips(self):
        names = sorted(path.name for path in (self.tmp / 'data/audio').iterdir() if path.is_file())
        self.assertEqual(names, sorted(expected_clip_names()))
        self.assertEqual(len(names), 37)
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        self.assertEqual(self.manifest().read_text(encoding='ascii'), self.expected_manifest())

    def test_extra_wav_is_rejected(self):
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        (self.tmp / 'data/audio/stray.wav').write_bytes(wav_bytes(10))
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(root=self.tmp, quiet=True)
        self.assertIn('holds WAV files outside the current clip set', str(ctx.exception))
        self.assertIn('stray.wav', str(ctx.exception))

    def test_real_set_compact_estimate_is_236837_bytes(self):
        data, dictionary = generate_catalog.load(REAL_ROOT)
        lengths = check_audio.check(root=REAL_ROOT, quiet=True)
        estimate = sum(check_audio.ulw_bytes(frames) for frames in lengths.values())
        estimate += len(check_audio.manifest_text(dictionary, data).encode('ascii'))
        self.assertEqual(estimate, 236837)
        self.assertLess(estimate, verify_audio_fs.SLOT_BYTES)

    def test_compact_budget_over_slot_rejected(self):
        for name in expected_clip_names():
            if name.startswith('d'):
                (self.tmp / 'data/audio' / name).write_bytes(wav_bytes(80000))
        with self.assertRaises(ValueError) as ctx:
            check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        message = str(ctx.exception)
        self.assertIn('Compact audio filesystem needs', message)
        self.assertIn('unenroll audio units in config/roster.json', message)
        self.assertIn('drop audio-targeted plays', message)
        self.assertTrue(self.manifest().is_file())


# ---------------------------------------------------------------------------
# import_demo_audio.py
# ---------------------------------------------------------------------------

class ImportDemoAudioTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_CALLS, self.tmp / 'config/calls.json')
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')
        self.data, self.dictionary = generate_catalog.load(self.tmp)

    def test_source_table_maps_pitch_location_and_play_recordings(self):
        table = import_demo_audio.source_table(self.data)
        self.assertEqual(table['p01.wav'], 'A1 Four-Seam Fastball.mp3')
        self.assertEqual(table['p09.wav'], 'J8 Splitter.mp3')
        self.assertEqual(table['l1.wav'], 'B1 High Inside.mp3')
        self.assertEqual(table['l9.wav'], 'B9 Low Outside.mp3')
        self.assertEqual(table['d01.wav'], 'A7 Pickoff.mp3')
        self.assertEqual(table['d18.wav'], 'C7 See Down.mp3')  # mapped even though not needed
        self.assertEqual(table['d21.wav'], 'E9 Ignore Runner.mp3')
        self.assertEqual(len(table),
                         len(self.data['pitches']) + len(self.data['locations']) + len(self.data['plays']))

    def test_outputs_are_exactly_the_needed_clips(self):
        pairs = import_demo_audio.outputs(self.data)
        self.assertEqual([name for name, _ in pairs], expected_clip_names())
        table = dict(pairs)
        self.assertEqual(table['d20.wav'], 'E8 Pitch Around.mp3')
        self.assertEqual(table['d02.wav'], 'A8 Hold and Step Off.mp3')
        self.assertNotIn('d18.wav', table)
        self.assertNotIn('d19.wav', table)

    def test_outputs_rejects_a_play_clip_without_an_audio_audience(self):
        with mock.patch.object(import_demo_audio, 'clips',
                               lambda data: [('d18.wav', 'See Down')]):
            with self.assertRaises(ValueError) as ctx:
                import_demo_audio.outputs(self.data)
        self.assertIn('d18.wav: play targets no enrolled audio unit', str(ctx.exception))

    def test_probe_accepts_valid_and_rejects_bad_clips(self):
        good = self.tmp / 'good.wav'
        good.write_bytes(wav_bytes(400))
        self.assertEqual(import_demo_audio.probe(good), 400)

        stereo = self.tmp / 'stereo.wav'
        stereo.write_bytes(wav_bytes(100, channels=2))
        with self.assertRaises(ValueError) as ctx:
            import_demo_audio.probe(stereo)
        self.assertIn('expected mono 16 kHz PCM16', str(ctx.exception))

        long_clip = self.tmp / 'long.wav'
        long_clip.write_bytes(wav_bytes(80001))
        with self.assertRaises(ValueError) as ctx:
            import_demo_audio.probe(long_clip)
        self.assertIn('exceeds the five second limit', str(ctx.exception))

        empty = self.tmp / 'empty.wav'
        empty.write_bytes(wav_bytes(0))
        with self.assertRaises(ValueError) as ctx:
            import_demo_audio.probe(empty)
        self.assertIn('contains no samples', str(ctx.exception))

        garbage = self.tmp / 'garbage.wav'
        garbage.write_bytes(b'RIFF')
        with self.assertRaises(ValueError) as ctx:
            import_demo_audio.probe(garbage)
        self.assertIn('not a readable WAV', str(ctx.exception))

    def test_stale_files_lists_wavs_outside_the_set(self):
        pairs = import_demo_audio.outputs(self.data)
        audio = self.tmp / 'data/audio'
        audio.mkdir(parents=True)
        (audio / 'p01.wav').write_bytes(wav_bytes(10))
        (audio / 'h1.wav').write_bytes(wav_bytes(10))
        (audio / '.gitkeep').write_text('', encoding='ascii')
        self.assertEqual(import_demo_audio.stale_files(self.tmp, pairs), ['h1.wav'])


# ---------------------------------------------------------------------------
# audio_transaction.py
# ---------------------------------------------------------------------------

class AudioTransactionTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_CALLS, self.tmp / 'config/calls.json')
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')
        self.data, self.dictionary = generate_catalog.load(self.tmp)

    def test_snapshot_includes_roster_and_detects_changes(self):
        before = audio_transaction.snapshot(self.tmp)
        self.assertIn('config/roster.json', before)
        self.assertIn('config/calls.json', before)
        self.assertIn('firmware/include/pc/catalog.h', before)
        self.assertIn('gui/catalog.json', before)

        units = real_roster_units()
        units[0]['audio'] = not units[0]['audio']
        write_roster(self.tmp, units)
        after = audio_transaction.snapshot(self.tmp)
        self.assertNotEqual(before['config/roster.json'], after['config/roster.json'])
        self.assertEqual(before['config/calls.json'], after['config/calls.json'])

    def test_prune_deletes_out_of_set_staged_wavs(self):
        stage = self.tmp / 'stage'
        (stage / 'config').mkdir(parents=True)
        shutil.copyfile(REAL_CALLS, stage / 'config/calls.json')
        shutil.copyfile(REAL_ROSTER, stage / 'config/roster.json')
        audio = stage / 'data/audio'
        audio.mkdir(parents=True)
        (audio / 'p01.wav').write_bytes(wav_bytes(10))
        (audio / 'h1.wav').write_bytes(wav_bytes(10))
        (audio / 'stray.wav').write_bytes(wav_bytes(10))
        (audio / '.gitkeep').write_text('', encoding='ascii')

        audio_transaction.prune(stage)

        self.assertEqual(sorted(path.name for path in audio.iterdir()),
                         ['.gitkeep', 'p01.wav'])

    def test_generate_stages_roster_prunes_and_installs(self):
        audio = self.tmp / 'data/audio'
        audio.mkdir(parents=True)
        (audio / 'p01.wav').write_bytes(wav_bytes(10))
        (audio / 'p99.wav').write_bytes(wav_bytes(10))
        seen = {}

        def fake_synthesize(stage, voice, powershell):
            seen['roster'] = (stage / 'config/roster.json').read_text(encoding='utf-8')
            staged, _ = generate_catalog.load(stage)
            for name, _ in generate_catalog.clips(staged):
                (stage / 'data/audio' / name).write_bytes(wav_bytes(300))

        with mock.patch.object(audio_transaction, 'synthesize', side_effect=fake_synthesize), \
                mock.patch.object(audio_transaction.preflight, 'check',
                                  return_value=self.dictionary):
            with contextlib.redirect_stdout(io.StringIO()):
                backup = audio_transaction.generate(root=self.tmp)

        self.assertEqual(seen['roster'],
                         (self.tmp / 'config/roster.json').read_text(encoding='utf-8'))
        self.assertTrue(backup.is_dir())
        self.assertTrue((backup / 'p01.wav').is_file())
        self.assertTrue((backup / 'p99.wav').is_file())
        remaining = sorted(path.name for path in (self.tmp / 'data/audio').iterdir()
                           if path.is_file())
        self.assertEqual(remaining, sorted(expected_clip_names() + ['manifest.txt']))
        self.assertFalse((self.tmp / 'build/validation.lock').exists())


# ---------------------------------------------------------------------------
# audit_repo.py
# ---------------------------------------------------------------------------

class AuditRepoRuleTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        if GIT is None:
            self.skipTest('git is required for the audit fixture (em-dash rule uses git ls-files)')
        self.version = make_repo_fixture(self.tmp, with_git=True)

    def append_main(self, text):
        path = self.tmp / 'firmware/src/main.c'
        path.write_text(path.read_text(encoding='ascii') + text,
                        encoding='ascii', newline='\n')

    def run_audit_main(self, root):
        argv = ['audit_repo.py', '--root', str(root)]
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as ctx:
                audit_repo.main()
        return ctx.exception.code, output.getvalue()

    def test_clean_fixture_passes_audit(self):
        report = audit_repo.audit(self.tmp)
        self.assertTrue(report['ok'], report['summary'])
        self.assertEqual([check['name'] for check in report['checks']], AUDIT_RULE_NAMES)
        for check in report['checks']:
            self.assertTrue(check['ok'], check)
        self.assertEqual(report['errors'], [])
        self.assertIn('audit_repo: PASS (6 of 6 checks passed, 0 error(s))', report['summary'])

    def test_audit_reports_exactly_one_rule_failure(self):
        self.append_main('int missing_uses = CONFIG_PITCHCOMM_MISSING;\n')
        report = audit_repo.audit(self.tmp)
        self.assertFalse(report['ok'])
        failed = [check['name'] for check in report['checks'] if not check['ok']]
        self.assertEqual(failed, ['CONFIG_PITCHCOMM_* references'])
        self.assertEqual(len(report['errors']), 1)
        self.assertIn('CONFIG_PITCHCOMM_MISSING is not defined in firmware/Kconfig or a conf file',
                      report['errors'][0])
        self.assertIn('audit_repo: FAIL (5 of 6 checks passed, 1 error(s))', report['summary'])

    def test_audit_main_exit_codes(self):
        code, output = self.run_audit_main(self.tmp)
        self.assertEqual(code, 0)
        self.assertIn('audit_repo: PASS', output)

        version = self.tmp / 'firmware/ncs_version.txt'
        version.write_text('v3.4\n', encoding='ascii', newline='\n')
        code, output = self.run_audit_main(self.tmp)
        self.assertEqual(code, 1)
        self.assertIn('audit_repo: FAIL', output)

    def test_config_symbols_undefined_reference(self):
        self.append_main('int missing_uses = CONFIG_PITCHCOMM_MISSING;\n')
        check = audit_repo.check_config_symbols(self.tmp)
        self.assertEqual(check['name'], AUDIT_RULE_NAMES[0])
        self.assertFalse(check['ok'])
        self.assertEqual(len(check['errors']), 1)
        self.assertRegex(check['errors'][0],
                         r'firmware/src/main\.c:\d+: CONFIG_PITCHCOMM_MISSING is not defined '
                         r'in firmware/Kconfig or a conf file')

    def test_config_symbols_wildcard_needs_a_matching_prefix(self):
        self.append_main('// needs CONFIG_PITCHCOMM_UNIT_EXTRA* later\n')
        check = audit_repo.check_config_symbols(self.tmp)
        self.assertFalse(check['ok'])
        self.assertTrue(any('CONFIG_PITCHCOMM_UNIT_EXTRA* matches no defined symbol' in error
                            for error in check['errors']), check['errors'])

        kconfig = self.tmp / 'firmware/Kconfig'
        kconfig.write_text(kconfig.read_text(encoding='ascii') + 'config PITCHCOMM_UNIT_EXTRA\n\tbool "x"\n',
                           encoding='ascii', newline='\n')
        self.assertTrue(audit_repo.check_config_symbols(self.tmp)['ok'])

    def test_config_symbols_conf_file_definitions(self):
        self.append_main('int conf_uses = CONFIG_PITCHCOMM_FROM_CONF;\n')
        self.assertFalse(audit_repo.check_config_symbols(self.tmp)['ok'])
        conf = self.tmp / 'firmware/roles/unit.conf'
        conf.write_text(conf.read_text(encoding='ascii') + 'CONFIG_PITCHCOMM_FROM_CONF=y\n',
                        encoding='ascii', newline='\n')
        self.assertTrue(audit_repo.check_config_symbols(self.tmp)['ok'])

    def test_em_dash_in_tracked_file(self):
        dash = self.tmp / 'firmware/src/dash.c'
        dash.write_text('// ' + '\u2014' + '\n', encoding='utf-8', newline='\n')
        git(self.tmp, 'add', '-A')
        check = audit_repo.check_em_dash(self.tmp)
        self.assertEqual(check['name'], AUDIT_RULE_NAMES[1])
        self.assertFalse(check['ok'])
        self.assertIn('firmware/src/dash.c:1: contains U+2014 em-dash', check['errors'])

        dash.unlink()
        git(self.tmp, 'add', '-A')
        self.assertTrue(audit_repo.check_em_dash(self.tmp)['ok'])

    def test_em_dash_rule_falls_back_to_a_filesystem_walk(self):
        other = Path(tempfile.mkdtemp(prefix='pitchcomm-nogit-'))
        self.addCleanup(remove_tree, other)
        make_repo_fixture(other, with_git=False)
        check = audit_repo.check_em_dash(other)
        self.assertTrue(check['ok'], check['errors'])
        self.assertIn('filesystem walk', check['detail'])
        self.assertRegex(check['detail'], r'^[1-9]\d* files scanned')

        (other / 'notes.txt').write_text('before ' + '\u2014' + ' after\n',
                                         encoding='utf-8', newline='\n')
        check = audit_repo.check_em_dash(other)
        self.assertFalse(check['ok'])
        self.assertIn('notes.txt:1: contains U+2014 em-dash', check['errors'])

    def test_em_dash_check_on_a_repo_subdirectory_uses_root_relative_paths(self):
        repo = Path(tempfile.mkdtemp(prefix='pitchcomm-subrepo-'))
        self.addCleanup(remove_tree, repo)
        git(repo, '-c', 'init.defaultBranch=main', 'init', '-q')
        (repo / 'outside.txt').write_text('outside ' + '\u2014' + '\n',
                                          encoding='utf-8', newline='\n')
        sub = repo / 'sub'
        sub.mkdir()
        (sub / 'inside.c').write_text('inside ' + '\u2014' + '\n',
                                      encoding='utf-8', newline='\n')
        git(repo, 'add', '-A')

        check = audit_repo.check_em_dash(sub)
        self.assertFalse(check['ok'])
        self.assertIn('inside.c:1: contains U+2014 em-dash', check['errors'])
        self.assertNotIn('outside.txt', ' '.join(check['errors']))

        (sub / 'inside.c').write_text('inside clean\n', encoding='ascii', newline='\n')
        check = audit_repo.check_em_dash(sub)
        self.assertTrue(check['ok'], check['errors'])
        self.assertRegex(check['detail'], r'^1 files scanned')

    def test_em_dash_zero_scan_with_files_present_is_not_a_pass(self):
        repo = Path(tempfile.mkdtemp(prefix='pitchcomm-zeroscan-'))
        self.addCleanup(remove_tree, repo)
        git(repo, '-c', 'init.defaultBranch=main', 'init', '-q')
        (repo / 'tracked.txt').write_text('clean\n', encoding='ascii', newline='\n')
        git(repo, 'add', '-A')
        sub = repo / 'sub'
        sub.mkdir()
        (sub / 'blob.bin').write_bytes(b'\x00\x01\x02')
        check = audit_repo.check_em_dash(sub)
        self.assertFalse(check['ok'])
        self.assertTrue(any('inspected nothing' in error for error in check['errors']),
                        check['errors'])

    def test_cmake_missing_source(self):
        extra = self.tmp / 'firmware/src/extra.c'
        extra.write_text('int extra_source;\n', encoding='ascii', newline='\n')
        check = audit_repo.check_cmake_sources(self.tmp)
        self.assertEqual(check['name'], AUDIT_RULE_NAMES[2])
        self.assertFalse(check['ok'])
        self.assertIn('firmware/src/extra.c is not listed in firmware/CMakeLists.txt', check['errors'])

        cmake = self.tmp / 'firmware/CMakeLists.txt'
        cmake.write_text(cmake.read_text(encoding='ascii') + 'target_sources(app PRIVATE src/extra.c)\n',
                         encoding='ascii', newline='\n')
        check = audit_repo.check_cmake_sources(self.tmp)
        self.assertTrue(check['ok'])
        self.assertEqual(check['detail'], '2 source files checked')

    def test_cmake_missing_cmakelists(self):
        (self.tmp / 'firmware/CMakeLists.txt').unlink()
        check = audit_repo.check_cmake_sources(self.tmp)
        self.assertFalse(check['ok'])
        self.assertIn('firmware/CMakeLists.txt is missing or unreadable', check['errors'])

    def test_cmake_source_only_in_a_comment_is_not_listed(self):
        (self.tmp / 'firmware/src/extra.c').write_text('int extra_source;\n',
                                                       encoding='ascii', newline='\n')
        cmake = self.tmp / 'firmware/CMakeLists.txt'
        cmake.write_text('target_sources(app PRIVATE src/main.c)\n'
                         '# src/extra.c was removed from the build\n',
                         encoding='ascii', newline='\n')
        check = audit_repo.check_cmake_sources(self.tmp)
        self.assertFalse(check['ok'])
        self.assertIn('firmware/src/extra.c is not listed in firmware/CMakeLists.txt', check['errors'])

        cmake.write_text(cmake.read_text(encoding='ascii') + 'target_sources(app PRIVATE src/extra.c)\n',
                         encoding='ascii', newline='\n')
        self.assertTrue(audit_repo.check_cmake_sources(self.tmp)['ok'])

    def test_catalog_drift_and_missing_files(self):
        header = self.tmp / 'firmware/include/pc/catalog.h'
        header.write_text(header.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        check = audit_repo.check_catalog(self.tmp)
        self.assertEqual(check['name'], AUDIT_RULE_NAMES[3])
        self.assertFalse(check['ok'])
        self.assertTrue(any('firmware/include/pc/catalog.h does not match rendered()' in error
                            for error in check['errors']), check['errors'])

        write_rendered(self.tmp)
        self.assertTrue(audit_repo.check_catalog(self.tmp)['ok'])

        (self.tmp / 'gui/catalog.json').unlink()
        check = audit_repo.check_catalog(self.tmp)
        self.assertFalse(check['ok'])
        self.assertTrue(any('gui/catalog.json is missing or not UTF-8 text' in error
                            for error in check['errors']), check['errors'])

    def test_catalog_render_failure_is_reported(self):
        calls = self.tmp / 'config/calls.json'
        data = json.loads(calls.read_text(encoding='utf-8'))
        data['schema'] = 2  # schema 3 counts are variable, so drop the schema instead
        calls.write_text(json.dumps(data), encoding='utf-8')
        check = audit_repo.check_catalog(self.tmp)
        self.assertFalse(check['ok'])
        self.assertEqual(check['detail'], 'cannot render the catalog')
        self.assertIn('catalog render failed', check['errors'][0])

    def test_ncs_version_accept_and_reject(self):
        path = self.tmp / 'firmware/ncs_version.txt'
        self.assertTrue(audit_repo.check_ncs_version(self.tmp)['ok'])
        for text in ('v3.4\n', '3.4.0\n', 'v3.4.0\nv3.4.1\n', 'release v3.4.0\n', '\n'):
            with self.subTest(text=text):
                path.write_text(text, encoding='ascii', newline='\n')
                check = audit_repo.check_ncs_version(self.tmp)
                self.assertFalse(check['ok'])
                self.assertIn('must be one line like v3.4.0', check['errors'][0])
        path.write_text('v3.4.0\n', encoding='ascii', newline='\n')
        self.assertTrue(audit_repo.check_ncs_version(self.tmp)['ok'])

    def test_ncs_version_missing_and_non_ascii(self):
        path = self.tmp / 'firmware/ncs_version.txt'
        path.unlink()
        check = audit_repo.check_ncs_version(self.tmp)
        self.assertFalse(check['ok'])
        self.assertIn('is missing; restore the pinned NCS version', check['errors'][0])

        path.write_bytes(b'v3.4.\xff\n')
        check = audit_repo.check_ncs_version(self.tmp)
        self.assertFalse(check['ok'])
        self.assertIn('is not readable as ASCII', check['errors'][0])

    def test_empty_files(self):
        check = audit_repo.check_empty_files(self.tmp)
        self.assertEqual(check['name'], AUDIT_RULE_NAMES[5])
        self.assertTrue(check['ok'])

        (self.tmp / 'firmware/boards').mkdir(parents=True, exist_ok=True)
        (self.tmp / 'firmware/src/empty.c').write_bytes(b'')
        (self.tmp / 'firmware/roles/empty.conf').write_bytes(b'')
        (self.tmp / 'firmware/boards/empty.overlay').write_bytes(b'')
        (self.tmp / 'gui/empty.js').write_bytes(b'')
        check = audit_repo.check_empty_files(self.tmp)
        self.assertFalse(check['ok'])
        self.assertIn('firmware/src/empty.c: zero bytes', check['errors'])
        self.assertIn('firmware/roles/empty.conf: zero bytes', check['errors'])
        self.assertIn('firmware/boards/empty.overlay: zero bytes', check['errors'])
        self.assertIn('gui/empty.js: zero bytes', check['errors'])

        for name in ('firmware/src/empty.c', 'firmware/roles/empty.conf',
                     'firmware/boards/empty.overlay', 'gui/empty.js'):
            (self.tmp / name).unlink()
        self.assertTrue(audit_repo.check_empty_files(self.tmp)['ok'])

    def test_audit_can_skip_only_the_version_rule(self):
        version = self.tmp / 'firmware/ncs_version.txt'
        version.write_text('gone\n', encoding='ascii', newline='\n')
        report = audit_repo.audit(self.tmp)
        self.assertFalse(report['ok'])
        failed = [check['name'] for check in report['checks'] if not check['ok']]
        self.assertEqual(failed, ['firmware/ncs_version.txt'])

        report = audit_repo.audit(self.tmp, check_version=False)
        self.assertTrue(report['ok'], report['summary'])
        names = [check['name'] for check in report['checks']]
        self.assertNotIn('firmware/ncs_version.txt', names)
        self.assertEqual(len(names), 5)
        self.assertIn('audit_repo: PASS (5 of 5 checks passed, 0 error(s))', report['summary'])

        # Catalog drift is still caught when only the version rule is dropped.
        header = self.tmp / 'firmware/include/pc/catalog.h'
        header.write_text(header.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        report = audit_repo.audit(self.tmp, check_version=False)
        self.assertFalse(report['ok'])
        self.assertTrue(any(error.startswith('generated catalog files:') for error in report['errors']),
                        report['errors'])

    def test_read_text_missing_and_binary(self):
        blob = self.tmp / 'blob.bin'
        blob.write_bytes(b'\x00\x01\x02')
        self.assertIsNone(audit_repo.read_text(blob))
        self.assertIsNone(audit_repo.read_text(self.tmp / 'absent.txt'))
        self.assertEqual(audit_repo.read_text(self.tmp / 'firmware/ncs_version.txt'), 'v3.4.0\n')


# ---------------------------------------------------------------------------
# preflight.py
# ---------------------------------------------------------------------------

class PreflightTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        if GIT is None:
            self.skipTest('git is required for the preflight fixture (audit uses git ls-files)')
        self.version = make_repo_fixture(self.tmp, with_git=True)

    def test_accepts_valid_version_pin(self):
        self.assertEqual(preflight.check(root=self.tmp, skip_audit=True), self.version)

    def test_rejects_bad_version_pins(self):
        path = self.tmp / 'firmware/ncs_version.txt'
        for text in ('3.4.0\n', 'v3.4\n', 'v3.4.0.1\n', 'v3.4.0\nv3.4.1\n',
                     'release v3.4.0\n', '', 'not-a-version\n'):
            with self.subTest(text=text):
                path.write_text(text, encoding='ascii', newline='\n')
                with self.assertRaises(ValueError) as ctx:
                    preflight.check(root=self.tmp, skip_audit=True)
                self.assertIn('Stale or missing NCS version pin', str(ctx.exception))

    def test_missing_version_pin(self):
        (self.tmp / 'firmware/ncs_version.txt').unlink()
        with self.assertRaises(ValueError) as ctx:
            preflight.check(root=self.tmp, skip_audit=True)
        self.assertIn('Stale or missing NCS version pin', str(ctx.exception))

    def test_stale_catalog_reported_before_the_audit(self):
        header = self.tmp / 'firmware/include/pc/catalog.h'
        header.write_text(header.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError) as ctx:
            preflight.check(root=self.tmp, skip_audit=True)
        self.assertIn('Stale or missing call files', str(ctx.exception))

    def test_audit_failure_reported_unless_skipped(self):
        main = self.tmp / 'firmware/src/main.c'
        main.write_text(main.read_text(encoding='ascii') + 'int missing = CONFIG_PITCHCOMM_MISSING;\n',
                        encoding='ascii', newline='\n')
        self.assertEqual(preflight.check(root=self.tmp, skip_audit=True), self.version)
        with self.assertRaises(ValueError) as ctx:
            preflight.check(root=self.tmp, skip_audit=False)
        self.assertIn('Repository audit failed (1 error(s))', str(ctx.exception))
        self.assertIn('CONFIG_PITCHCOMM_MISSING', str(ctx.exception))

    def test_audio_check_bypasses_version_pin_and_needs_clips(self):
        add_synthetic_audio(self.tmp)
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        self.assertEqual(preflight.check(root=self.tmp, audio=True, skip_audit=True), self.version)

        (self.tmp / 'firmware/ncs_version.txt').write_text('not-a-pin\n', encoding='ascii')
        self.assertEqual(preflight.check(root=self.tmp, audio=True, skip_audit=True), self.version)

        (self.tmp / 'data/audio/manifest.txt').write_text('deadbeef\n', encoding='ascii')
        with self.assertRaises(ValueError) as ctx:
            preflight.check(root=self.tmp, audio=True, skip_audit=True)
        self.assertIn('Receiver audio is not ready', str(ctx.exception))

    def test_audio_check_skips_only_the_version_rule(self):
        add_synthetic_audio(self.tmp)
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        (self.tmp / 'firmware/ncs_version.txt').write_text('not-a-pin\n', encoding='ascii')

        # Default audit runs, but it must drop only the version rule.
        self.assertEqual(preflight.check(root=self.tmp, audio=True), self.version)

        # The other audit rules are still active: catalog drift must fail.
        header = self.tmp / 'firmware/include/pc/catalog.h'
        header.write_text(header.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError) as ctx:
            preflight.check(root=self.tmp, audio=True)
        self.assertIn('Stale or missing call files', str(ctx.exception))


class PreflightCheckRosterTests(unittest.TestCase):
    """preflight.check_roster inspects the generated catalog text directly."""

    def setUp(self):
        self.catalog = (REAL_ROOT / 'firmware/include/pc/catalog.h').read_text(encoding='utf-8')

    def with_unit_count(self, count):
        return re.sub(r'constexpr unsigned kUnitCount = \d+;',
                      f'constexpr unsigned kUnitCount = {count};', self.catalog)

    def test_accepts_the_real_generated_catalog(self):
        self.assertIsNone(preflight.check_roster(self.catalog))

    def test_rejects_a_unit_count_out_of_range(self):
        for count in (0, 1, 17, 20):
            with self.subTest(count=count):
                with self.assertRaises(ValueError) as ctx:
                    preflight.check_roster(self.with_unit_count(count))
                message = str(ctx.exception)
                self.assertIn(f'Generated catalog covers {count - 1} enrolled unit(s)', message)
                self.assertIn('1 to 15 units', message)
                self.assertIn('python tools/generate_catalog.py', message)
        # 16 units (coach plus 15 enrolled) is exactly the mask limit.
        self.assertIsNone(preflight.check_roster(self.with_unit_count(16)))

    def test_rejects_a_missing_unit_count(self):
        text = re.sub(r'constexpr unsigned kUnitCount = \d+;\n', '', self.catalog)
        with self.assertRaises(ValueError) as ctx:
            preflight.check_roster(text)
        self.assertIn('has no kUnitCount', str(ctx.exception))

    def test_rejects_a_catalog_with_no_pitches_unit(self):
        text = re.sub(r'inline constexpr bool kUnitPitches\[\] = \{.*?\};',
                      'inline constexpr bool kUnitPitches[] = {\n  false,\n  false,\n};',
                      self.catalog, flags=re.DOTALL)
        with self.assertRaises(ValueError) as ctx:
            preflight.check_roster(text)
        message = str(ctx.exception)
        self.assertIn('enrolls no unit with the pitches capability', message)
        self.assertIn('python tools/generate_catalog.py', message)

    def test_rejects_a_missing_pitches_array(self):
        text = re.sub(r'inline constexpr bool kUnitPitches\[\] = \{.*?\};\n', '',
                      self.catalog, flags=re.DOTALL)
        with self.assertRaises(ValueError) as ctx:
            preflight.check_roster(text)
        self.assertIn('has no kUnitPitches[]', str(ctx.exception))


class PreflightCheckTeamTests(TempRepoTestCase):
    """preflight.check_team compares the local team file and generated header."""

    def setUp(self):
        super().setUp()
        (self.tmp / 'config').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REAL_ROSTER, self.tmp / 'config/roster.json')
        provision.save_locked(good_config(), root=self.tmp)
        self.local = self.tmp / 'config/team.local.json'
        self.header = self.tmp / 'firmware/include/app/team_config.h'

    def test_matching_team_file_and_header_pass(self):
        self.assertIsNone(preflight.check_team(self.tmp))

    def test_stale_header_is_reported_with_the_regenerate_command(self):
        self.header.write_text(self.header.read_text(encoding='utf-8') + '// stale\n',
                               encoding='utf-8', newline='\n')
        with self.assertRaises(ValueError) as ctx:
            preflight.check_team(self.tmp)
        message = str(ctx.exception)
        self.assertIn('does not match config/team.local.json', message)
        self.assertIn('python tools/provision.py --from-file config/team.local.json', message)

    def test_missing_header_is_reported_with_the_regenerate_command(self):
        self.header.unlink()
        with self.assertRaises(ValueError) as ctx:
            preflight.check_team(self.tmp)
        message = str(ctx.exception)
        self.assertIn('team_config.h is missing', message)
        self.assertIn('python tools/provision.py --from-file config/team.local.json', message)

    def test_extra_key_in_the_team_file_is_reported(self):
        data = json.loads(self.local.read_text(encoding='utf-8'))
        data['eui64']['first'] = 'AA:BB:CC:DD:EE:FF:00:06'
        self.local.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            preflight.check_team(self.tmp)
        message = str(ctx.exception)
        self.assertIn('config/team.local.json is not a valid team configuration', message)
        self.assertIn("Unit 'first' is not enrolled in config/roster.json", message)
        self.assertIn('python tools/provision.py --from-file config/team.local.json', message)

    def test_missing_key_in_the_team_file_is_reported(self):
        data = json.loads(self.local.read_text(encoding='utf-8'))
        del data['eui64']['pitcher']
        self.local.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            preflight.check_team(self.tmp)
        message = str(ctx.exception)
        self.assertIn("Missing EUI-64 for unit 'pitcher'", message)
        self.assertIn('python tools/provision.py --from-file config/team.local.json', message)

    def test_header_without_a_team_file_is_reported(self):
        self.local.unlink()
        with self.assertRaises(ValueError) as ctx:
            preflight.check_team(self.tmp)
        message = str(ctx.exception)
        self.assertIn('exists but config/team.local.json is missing', message)
        self.assertIn('python tools/provision.py --from-file config/team.local.json', message)

    def test_no_team_file_and_no_header_passes(self):
        self.local.unlink()
        self.header.unlink()
        self.assertIsNone(preflight.check_team(self.tmp))


class PreflightCheckAudioSetTests(TempRepoTestCase):
    """preflight.check_audio_set reuses the check_audio helpers read-only."""

    def setUp(self):
        super().setUp()
        add_catalog(self.tmp)
        self.data, self.dictionary = add_synthetic_audio(self.tmp)
        check_audio.check(write_manifest=True, root=self.tmp, quiet=True)
        self.audio = self.tmp / 'data/audio'

    def test_correct_staged_set_passes(self):
        self.assertIsNone(preflight.check_audio_set(self.tmp, self.dictionary))

    def test_missing_clip_is_reported(self):
        (self.audio / 'p01.wav').unlink()
        with self.assertRaises(ValueError) as ctx:
            preflight.check_audio_set(self.tmp, self.dictionary)
        message = str(ctx.exception)
        self.assertIn('missing clips for the current roster and dictionary: p01.wav', message)
        self.assertIn('python tools/import_demo_audio.py', message)
        self.assertIn('check_audio.py --write-manifest', message)

    def test_extra_wav_is_reported(self):
        (self.audio / 'stray.wav').write_bytes(wav_bytes(10))
        with self.assertRaises(ValueError) as ctx:
            preflight.check_audio_set(self.tmp, self.dictionary)
        self.assertIn('holds WAV files outside the current clip set (stray.wav)',
                      str(ctx.exception))

    def test_stale_manifest_is_reported(self):
        (self.audio / 'manifest.txt').write_text('deadbeef\n', encoding='ascii')
        with self.assertRaises(ValueError) as ctx:
            preflight.check_audio_set(self.tmp, self.dictionary)
        message = str(ctx.exception)
        self.assertIn('manifest.txt does not match the current dictionary and clip list', message)
        self.assertIn('check_audio.py --write-manifest', message)

    def test_no_wavs_is_skipped_not_failed(self):
        shutil.rmtree(self.audio)
        self.assertIsNone(preflight.check_audio_set(self.tmp, self.dictionary))
        self.audio.mkdir()
        self.assertIsNone(preflight.check_audio_set(self.tmp, self.dictionary))

    def test_empty_root_is_skipped(self):
        bare = Path(tempfile.mkdtemp(prefix='pitchcomm-bare-'))
        self.addCleanup(remove_tree, bare)
        self.assertIsNone(preflight.check_audio_set(bare, self.dictionary))


# ---------------------------------------------------------------------------
# verify_audio_fs.py
# ---------------------------------------------------------------------------

class IntelHexTests(unittest.TestCase):

    def test_check_hex_accepts_matching_records(self):
        image = bytes(range(256)) * 16
        records = verify_audio_fs.parse_intel_hex(intel_hex(verify_audio_fs.SLOT_BASE, image))
        self.assertEqual(verify_audio_fs.check_hex(records, image), [])

    def test_check_hex_reports_wrong_base(self):
        image = b'\x00' * 64
        base = verify_audio_fs.SLOT_BASE + 0x1000
        records = verify_audio_fs.parse_intel_hex(intel_hex(base, image))
        problems = verify_audio_fs.check_hex(records, image)
        self.assertEqual(problems, [f'Intel HEX starts at 0x{base:X}; '
                                    f'expected 0x{verify_audio_fs.SLOT_BASE:X}'])

    def test_check_hex_reports_gap(self):
        records = [(verify_audio_fs.SLOT_BASE, b'\x00' * 32),
                   (verify_audio_fs.SLOT_BASE + 64, b'\x00' * 32)]
        problems = verify_audio_fs.check_hex(records, b'\x00' * 64)
        self.assertEqual(len(problems), 1)
        self.assertIn('not contiguous at 0x', problems[0])

    def test_check_hex_reports_length_mismatch(self):
        records = [(verify_audio_fs.SLOT_BASE, b'\x00' * 64)]
        problems = verify_audio_fs.check_hex(records, b'\x00' * 63)
        self.assertEqual(problems, ['Intel HEX covers 64 bytes; image is 63 bytes'])

    def test_check_hex_reports_byte_difference(self):
        records = [(verify_audio_fs.SLOT_BASE, b'\x01' + b'\x00' * 63)]
        problems = verify_audio_fs.check_hex(records, b'\x00' * 64)
        self.assertEqual(problems,
                         [f'Intel HEX differs from the image at 0x{verify_audio_fs.SLOT_BASE:X}'])

    def test_check_hex_reports_no_records(self):
        self.assertEqual(verify_audio_fs.check_hex([], b''), ['Intel HEX has no data records'])

    def test_parse_rejects_checksum_mismatch(self):
        lines = intel_hex(verify_audio_fs.SLOT_BASE, b'\x00' * 32).splitlines()
        lines[1] = lines[1][:-1] + ('1' if lines[1][-1] != '1' else '2')
        with self.assertRaises(ValueError) as ctx:
            verify_audio_fs.parse_intel_hex('\n'.join(lines))
        self.assertIn('checksum mismatch', str(ctx.exception))

    def test_parse_rejects_missing_start_code(self):
        with self.assertRaises(ValueError) as ctx:
            verify_audio_fs.parse_intel_hex('00000001FF\n')
        self.assertIn('missing ":" start code', str(ctx.exception))

    def test_parse_rejects_wrong_size_upper_records(self):
        cases = [(0x02, b''), (0x02, b'\x01'), (0x02, b'\x01\x02\x03'),
                 (0x04, b''), (0x04, b'\x01'), (0x04, b'\x01\x02\x03')]
        for kind, body in cases:
            with self.subTest(kind=kind, length=len(body)):
                text = hex_record(0, kind, body) + '\n:00000001FF\n'
                with self.assertRaises(ValueError) as ctx:
                    verify_audio_fs.parse_intel_hex(text)
                self.assertIn(f'record type 0x{kind:02X} needs exactly two payload bytes',
                              str(ctx.exception))

        valid = hex_record(0, 0x04, b'\x00\x0c') + '\n' + hex_record(0x2000, 0x00, b'\x00' * 4)
        self.assertEqual(verify_audio_fs.parse_intel_hex(valid), [(0xC2000, b'\x00' * 4)])


class VerifyAudioFsTests(TempRepoTestCase):

    def setUp(self):
        super().setUp()
        if verify_audio_fs.littlefs is None:
            self.skipTest('littlefs-python is not installed; '
                          'run python -m pip install -r tools/requirements.txt')
        if not REAL_IMAGE.is_file():
            self.skipTest(f'real audio filesystem image is absent: {REAL_IMAGE}')
        self.image = REAL_IMAGE.read_bytes()

    def write_image_and_hex(self, image_bytes, hex_base=None):
        image_path = self.tmp / 'littlefs.img'
        image_path.write_bytes(image_bytes)
        hex_path = self.tmp / 'littlefs.hex'
        hex_path.write_text(intel_hex(verify_audio_fs.SLOT_BASE if hex_base is None else hex_base,
                                      self.image),
                            encoding='ascii')
        return image_path, hex_path

    def test_real_image_and_hex_verify(self):
        result = verify_audio_fs.verify(image_path=REAL_IMAGE, hex_path=REAL_HEX,
                                        root=REAL_ROOT, quiet=True)
        data, dictionary = generate_catalog.load(REAL_ROOT)
        self.assertEqual(len(generate_catalog.clips(data)), 37)
        self.assertEqual(result['clips'], 37)
        self.assertEqual(result['dictionary'], 0x299314f6)
        self.assertEqual(result['dictionary'], dictionary)
        self.assertEqual(result['image_bytes'], len(self.image))
        self.assertEqual(len(self.image) % verify_audio_fs.BLOCK_SIZE, 0)
        self.assertLessEqual(len(self.image), verify_audio_fs.SLOT_BYTES)

    def test_wrong_hex_base_is_reported(self):
        base = verify_audio_fs.SLOT_BASE + 0x1000
        image_path, hex_path = self.write_image_and_hex(self.image, hex_base=base)
        with self.assertRaises(verify_audio_fs.AudioFsMismatch) as ctx:
            verify_audio_fs.verify(image_path=image_path, hex_path=hex_path,
                                   root=REAL_ROOT, quiet=True)
        self.assertEqual(ctx.exception.problems,
                         [f'Intel HEX starts at 0x{base:X}; '
                          f'expected 0x{verify_audio_fs.SLOT_BASE:X}'])

    def test_truncated_image_is_reported(self):
        truncated = self.image[:1000]
        image_path, hex_path = self.write_image_and_hex(truncated)
        with self.assertRaises(verify_audio_fs.AudioFsMismatch) as ctx:
            verify_audio_fs.verify(image_path=image_path, hex_path=hex_path,
                                   root=REAL_ROOT, quiet=True)
        self.assertEqual(ctx.exception.problems,
                         [f'image is {len(truncated)} bytes, not a multiple of '
                          f'{verify_audio_fs.BLOCK_SIZE}',
                          f'Intel HEX covers {len(self.image)} bytes; '
                          f'image is {len(truncated)} bytes'])

    def test_missing_image_and_hex_are_reported(self):
        missing = self.tmp / 'absent.img'
        with self.assertRaises(verify_audio_fs.AudioFsMismatch) as ctx:
            verify_audio_fs.verify(image_path=missing, root=REAL_ROOT, quiet=True)
        self.assertEqual(ctx.exception.problems,
                         [f'image not found: {missing}',
                          f'Intel HEX not found: {missing.with_suffix(".hex")}'])


class BuildAudioFsRoundTripTests(TempRepoTestCase):
    """The compact image built from the real clips verifies; PCM refuses."""

    def setUp(self):
        super().setUp()
        if build_audio_fs is None or verify_audio_fs.littlefs is None:
            self.skipTest('littlefs-python is not installed; '
                          'run python -m pip install -r tools/requirements.txt')
        if not REAL_AUDIO.is_dir():
            self.skipTest(f'real audio directory is absent: {REAL_AUDIO}')

    def check_image(self):
        data, dictionary = generate_catalog.load(build_audio_fs.ROOT)
        self.assertEqual(f'{dictionary:08x}', '299314f6')
        image = build_audio_fs.build_fs(False, data, dictionary)
        image_path = self.tmp / 'littlefs.img'
        image_path.write_bytes(image)
        hex_path = image_path.with_suffix('.hex')
        hex_path.write_text(intel_hex(build_audio_fs.SLOT_BASE, image), encoding='ascii')
        result = verify_audio_fs.verify(image_path=image_path, hex_path=hex_path,
                                        root=build_audio_fs.ROOT, quiet=True)
        self.assertEqual(result['clips'], 37)
        self.assertEqual(result['clips'], len(generate_catalog.clips(data)))
        self.assertEqual(result['dictionary'], 0x299314f6)
        self.assertEqual(result['dictionary'], dictionary)
        self.assertEqual(result['image_bytes'], len(image))

    def pcm_payload_bytes(self, data, dictionary):
        payload = len(f'{dictionary:08x}\n'.encode('ascii'))
        payload += sum((REAL_AUDIO / name).stat().st_size
                       for name, _ in generate_catalog.clips(data))
        return payload

    def test_compact_ulw_image_verifies(self):
        self.check_image()

    def test_pcm_build_refuses_with_the_shrink_options(self):
        data, dictionary = generate_catalog.load(REAL_ROOT)
        payload = self.pcm_payload_bytes(data, dictionary)
        with self.assertRaises(ValueError) as ctx:
            build_audio_fs.build_fs(True, data, dictionary)
        message = str(ctx.exception)
        self.assertIn('16 kHz PCM', message)
        self.assertIn(f'{payload} bytes of clips plus manifest', message)
        self.assertIn('use the compact 8 kHz mu-law codec', message)
        self.assertIn('unenroll audio units in config/roster.json', message)
        self.assertIn('drop audio-targeted plays', message)

        output = self.tmp / 'pcm/littlefs.img'
        with self.assertRaises(ValueError):
            build_audio_fs.pack(pcm_mode=True, output=output, root=REAL_ROOT)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix('.hex').exists())

    def test_pack_uses_a_staging_root(self):
        staging = self.tmp / 'staging'
        add_catalog(staging)
        _, dictionary = add_synthetic_audio(staging, frames=200)
        check_audio.check(write_manifest=True, root=staging, quiet=True)

        with contextlib.redirect_stdout(io.StringIO()):
            build_audio_fs.pack(root=staging)

        destination = staging / 'firmware/build/audio/littlefs.img'
        self.assertTrue(destination.is_file())
        self.assertTrue(destination.with_suffix('.hex').is_file())
        result = verify_audio_fs.verify(image_path=destination,
                                        hex_path=destination.with_suffix('.hex'),
                                        root=staging, quiet=True)
        self.assertEqual(result['dictionary'], dictionary)
        self.assertEqual(f"{result['dictionary']:08x}", '299314f6')
        self.assertEqual(result['clips'], 37)

    def test_build_fs_reads_clips_from_the_given_root(self):
        staging = self.tmp / 'staging'
        add_catalog(staging)
        add_synthetic_audio(staging, frames=200)
        data, dictionary = generate_catalog.load(staging)
        image = build_audio_fs.build_fs(pcm_mode=False, data=data,
                                        dictionary=dictionary, root=staging)
        self.assertEqual(len(image), build_audio_fs.SLOT_BYTES)

    def test_wrong_dictionary_image_is_reported(self):
        data, dictionary = generate_catalog.load(REAL_ROOT)
        image = build_audio_fs.build_fs(pcm_mode=False, data=data,
                                        dictionary=(dictionary + 1) & 0xffffffff)
        image_path = self.tmp / 'wrong.img'
        image_path.write_bytes(image)
        hex_path = image_path.with_suffix('.hex')
        hex_path.write_text(intel_hex(verify_audio_fs.SLOT_BASE, image), encoding='ascii')
        with self.assertRaises(verify_audio_fs.AudioFsMismatch) as ctx:
            verify_audio_fs.verify(image_path=image_path, hex_path=hex_path,
                                   root=REAL_ROOT, quiet=True)
        self.assertTrue(any('/audio/manifest.txt is' in problem
                            for problem in ctx.exception.problems), ctx.exception.problems)


if __name__ == '__main__':
    unittest.main(verbosity=2)
