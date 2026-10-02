"""Enroll or unenroll roster units and regenerate the catalog (standard library only).

config/roster.json is the enrollment source of truth. This tool makes one
enrollment change without hand-editing JSON and immediately regenerates
firmware/include/pc/catalog.h and gui/catalog.json through
generate_catalog.generate(), so the generated catalog never drifts from the
roster.

Commands:

    python tools/roster.py list [--root PATH]
    python tools/roster.py enable KEY [--root PATH] [capability flags]
    python tools/roster.py disable KEY [--root PATH]

`enable` turns a roster unit on. With no capability flag it applies the unit's
standard profile exactly:

    pitcher                                          audio + pitches
    catcher                                          display + controls + pitches
    every other standard key, and every custom key   display

With capability flags (--audio/--no-audio, --display/--no-display,
--controls/--no-controls, --pitches/--no-pitches) only the named capabilities
change and the rest keep their current values. A controls unit always needs
display, the same rule tools/build_firmware.ps1 enforces.

`disable` refuses to unenroll the last unit that receives pitch calls. Neither
command touches config/team.local.json, data/audio or firmware/build.
config/team.local.json and firmware/include/app/team_config.h keep the old
enrollment until tools/provision.py is rerun, and preflight flags that drift
until then.
"""
import argparse
import inspect
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import generate_catalog

CAPABILITY_FIELDS = ('audio', 'display', 'controls', 'pitches')
DEFAULT_PROFILES = {
    'pitcher': {'audio': True, 'display': False, 'controls': False, 'pitches': True},
    'catcher': {'audio': False, 'display': True, 'controls': True, 'pitches': True},
}
FIELD_PROFILE = {'audio': False, 'display': True, 'controls': False, 'pitches': False}
HEADERS = ('UNIT', 'KEY', 'LABEL', 'SHORT', 'ENROLLED', 'CAPABILITIES', 'EUI')


class RosterParser(argparse.ArgumentParser):
    """One-line, exit-code-1 failures instead of argparse's usage dump."""

    def error(self, message):
        self.exit(1, f'roster: {message}\n')


def default_profile(key):
    """Return the standard capability profile for one roster key."""
    return dict(DEFAULT_PROFILES.get(key, FIELD_PROFILE))


def load_units(root):
    """Parse config/roster.json and validate it with the generator's own rules.

    Returns (document, units) so callers keep the parsed document for
    formatting while the generator validates every field.
    """
    path = Path(root) / 'config/roster.json'
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise ValueError('config/roster.json is missing') from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'config/roster.json is not readable JSON ({error})') from error
    if not isinstance(document, dict):
        raise ValueError('config/roster.json must be a JSON object with schema and units')
    generate_catalog.load_roster(root)
    return document, document['units']


def validate_units(units):
    """Apply the invariants the generator and the firmware build enforce."""
    for unit in units:
        if unit['controls'] and not unit['display']:
            raise ValueError(f'Unit {unit["key"]!r} has controls without display; '
                             'the catcher menu needs the OLED (CONFIG_PITCHCOMM_DISPLAY)')
    enrolled = [unit for unit in units if unit['enrolled']]
    if not enrolled:
        raise ValueError('roster must enroll at least one unit')
    if len(enrolled) > generate_catalog.ENROLLED_LIMIT:
        raise ValueError(f'roster enrolls {len(enrolled)} units; at most '
                         f'{generate_catalog.ENROLLED_LIMIT} fit the 16-bit unit mask')
    if not any(unit['pitches'] for unit in enrolled):
        raise ValueError('roster must enroll at least one unit with the pitches capability')


def format_document(document):
    """Render the roster in the committed style: one unit per 4-space line."""
    lines = ['{']
    keys = list(document)
    for position, key in enumerate(keys):
        tail = ',' if position < len(keys) - 1 else ''
        value = document[key]
        if key == 'units' and isinstance(value, list):
            lines.append(f'  {json.dumps(key)}: [')
            for index, unit in enumerate(value):
                unit_tail = ',' if index < len(value) - 1 else ''
                lines.append('    ' + json.dumps(unit, separators=(', ', ': ')) + unit_tail)
            lines.append('  ]' + tail)
        else:
            lines.append(f'  {json.dumps(key)}: {json.dumps(value, separators=(", ", ": "))}{tail}')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def write_document(root, document):
    """Write config/roster.json atomically, preserving unit field order."""
    generate_catalog.atomic_text(Path(root) / 'config/roster.json', format_document(document))


def regenerate(root):
    """Regenerate both catalog files for root through generate_catalog.generate().

    generate() reads its repository root from the generate_catalog.ROOT module
    global, so point that global at root for the duration of the call (and
    support a future generate(root) signature), then restore it.
    """
    root = Path(root)
    try:
        parameters = inspect.signature(generate_catalog.generate).parameters
    except (TypeError, ValueError):
        parameters = None
    original = generate_catalog.ROOT
    generate_catalog.ROOT = root
    try:
        if parameters:
            generate_catalog.generate(root)
        else:
            generate_catalog.generate()
    finally:
        generate_catalog.ROOT = original


def regenerate_or_explain(root):
    """Regenerate after a roster write and name the recovery command on failure."""
    try:
        regenerate(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'{error}. config/roster.json was updated; run '
                         'python tools/generate_catalog.py to finish regeneration') from error


def clip_names(root):
    """Return the audio clip names the current roster and vocabulary need."""
    data, _ = generate_catalog.load(root)
    return {name for name, _ in generate_catalog.clips(data)}


def local_euis(root):
    """Return the unit keys config/team.local.json records an EUI for."""
    path = Path(root) / 'config/team.local.json'
    if not path.is_file():
        return set()
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'config/team.local.json is not readable JSON ({error})') from error
    if not isinstance(document, dict) or not isinstance(document.get('eui64'), dict):
        return set()
    return set(document['eui64'])


def find_unit(units, key):
    """Return the unit with this key, or None."""
    for unit in units:
        if unit['key'] == key:
            return unit
    return None


def unknown_key_error(units, key):
    """One line naming the usable keys for an unknown enable/disable target."""
    if key == 'coach':
        return "Unit 'coach' is implicit unit 0 and cannot be enabled or disabled"
    return f'Unknown unit key {key!r}; known keys: ' + ', '.join(unit['key'] for unit in units)


def render_table(rows):
    """Left-align columns with two spaces between them."""
    widths = [len(header) for header in HEADERS]
    for row in rows:
        for position, cell in enumerate(row):
            widths[position] = max(widths[position], len(cell))

    def line(cells):
        return '  '.join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    return '\n'.join([line(HEADERS)] + [line(row) for row in rows])


def resolve_root(args):
    return Path(args.root) if args.root is not None else Path(generate_catalog.ROOT)


def command_list(args):
    root = resolve_root(args)
    _, units = load_units(root)
    euis = local_euis(root)
    rows = [('0', 'coach', 'Coach', 'CO', 'implicit', '-',
             'yes' if 'coach' in euis else 'no')]
    index = 0
    for unit in units:
        if unit['enrolled']:
            index += 1
        capabilities = ', '.join(field for field in CAPABILITY_FIELDS if unit[field]) or '-'
        rows.append((str(index if unit['enrolled'] else 0), unit['key'], unit['label'], unit['short'],
                     'yes' if unit['enrolled'] else 'no', capabilities,
                     'yes' if unit['key'] in euis else 'no'))
    print(render_table(rows))


def command_enable(args):
    root = resolve_root(args)
    document, units = load_units(root)
    unit = find_unit(units, args.key)
    if unit is None:
        raise ValueError(unknown_key_error(units, args.key))
    before = clip_names(root)
    flags = {field: getattr(args, field) for field in CAPABILITY_FIELDS
             if getattr(args, field) is not None}
    if flags:
        for field, value in flags.items():
            unit[field] = value
    else:
        profile = default_profile(unit['key'])
        for field in CAPABILITY_FIELDS:
            unit[field] = profile[field]
    unit['enrolled'] = True
    validate_units(units)
    write_document(root, document)
    regenerate_or_explain(root)
    audio_grew = bool(clip_names(root) - before)
    print(f'Enabled unit {unit["key"]!r}.')
    print('Next steps:')
    print(f'  python tools/provision.py --coach <EUI-64> --unit {unit["key"]}=<EUI-64>')
    print(f'  tools\\build_firmware.ps1 -Units {unit["key"]}')
    if audio_grew:
        print('  python tools/import_demo_audio.py')
        print('  python tools/build_audio_fs.py')


def command_disable(args):
    root = resolve_root(args)
    document, units = load_units(root)
    unit = find_unit(units, args.key)
    if unit is None:
        raise ValueError(unknown_key_error(units, args.key))
    if unit['enrolled'] and unit['pitches'] and not any(
            other is not unit and other['enrolled'] and other['pitches'] for other in units):
        raise ValueError(f'Cannot disable {unit["key"]!r}: it is the last enrolled unit with the '
                         'pitches capability; enroll another pitches unit first')
    unit['enrolled'] = False
    validate_units(units)
    write_document(root, document)
    regenerate_or_explain(root)
    print(f'Disabled unit {unit["key"]!r}.')
    print(f'Warning: config/team.local.json and firmware/include/app/team_config.h still hold '
          f'{unit["key"]!r} until provisioning is rerun; preflight will flag the drift.')


def add_capability_flags(parser):
    for field in CAPABILITY_FIELDS:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(f'--{field}', dest=field, action='store_true', default=None,
                           help=f'enable the {field} capability')
        group.add_argument(f'--no-{field}', dest=field, action='store_false',
                           help=f'disable the {field} capability')


def build_parser():
    parser = RosterParser(prog='roster.py', description=__doc__,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest='command', required=True)

    listing = subparsers.add_parser('list', help='show every roster unit and its local EUI')
    listing.add_argument('--root', type=Path, default=None,
                         help='repository root (default: the repository containing tools/)')
    listing.set_defaults(handler=command_list)

    enabling = subparsers.add_parser('enable', help='enroll one unit and regenerate the catalog')
    enabling.add_argument('key', help='roster key to enroll')
    enabling.add_argument('--root', type=Path, default=None,
                          help='repository root (default: the repository containing tools/)')
    add_capability_flags(enabling)
    enabling.set_defaults(handler=command_enable)

    disabling = subparsers.add_parser('disable', help='unenroll one unit and regenerate the catalog')
    disabling.add_argument('key', help='roster key to unenroll')
    disabling.add_argument('--root', type=Path, default=None,
                           help='repository root (default: the repository containing tools/)')
    disabling.set_defaults(handler=command_disable)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'roster: {error}\n')
    return 0


if __name__ == '__main__':
    main()
