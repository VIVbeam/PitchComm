"""Read and validate the call catalog included in this package."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(root=ROOT):
    root = Path(root)
    data = json.loads((root / 'gui/catalog.json').read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema') != 3
            or not isinstance(data.get('dictionary'), str)
            or not re.fullmatch(r'[0-9a-f]{8}', data['dictionary'])):
        raise ValueError('Invalid call catalog; restore the complete product package.')
    units = data.get('units', [])
    fields = ('key', 'label', 'short', 'audio', 'display', 'controls', 'pitches')
    if (not isinstance(units, list)
            or any(not isinstance(unit, dict) or not all(field in unit for field in fields)
                   or not isinstance(unit['key'], str) for unit in units)
            or any(not isinstance(data.get(name), list)
                   for name in ('pitches', 'rows', 'cols', 'locations', 'plays'))):
        raise ValueError('Invalid call catalog; restore the complete product package.')
    flow=data.get('pitchFlow')
    size=len(data.get('pitches',[]))*len(data.get('rows',[]))*len(data.get('cols',[]))
    expected={'kind':'announce-nod-placement-v1','typeBase':size,
              'placementBase':size+len(data.get('pitches',[])),
              'maxCode':2*size+len(data.get('pitches',[]))}
    if flow!=expected:
        raise ValueError('Invalid two-segment pitch catalog; restore matching package files.')
    keys = [unit['key'] for unit in units]
    if not 1 <= len(keys) <= 15 or len(set(keys)) != len(keys):
        raise ValueError('The package must contain 1 to 15 distinct field units.')
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in keys):
        raise ValueError('Invalid unit key in the call catalog.')
    roster = json.loads((root / 'config/roster.json').read_text(encoding='utf-8'))
    if (not isinstance(roster, dict) or not isinstance(roster.get('units'), list)
            or any(not isinstance(unit, dict) or type(unit.get('enrolled')) is not bool
                   or not all(field in unit for field in fields) for unit in roster['units'])):
        raise ValueError('Invalid roster; restore the complete product package.')
    enrolled = [unit for unit in roster['units'] if unit['enrolled']]
    expected = [{field: unit[field] for field in fields} for unit in units]
    actual = [{field: unit[field] for field in fields} for unit in enrolled]
    if roster.get('schema') != 1 or actual != expected:
        raise ValueError('Roster and catalog belong to different packages; restore matching package files.')
    if not any(unit['pitches'] for unit in units):
        raise ValueError('The package has no pitch receiver.')
    header = (root / 'firmware/include/pc/catalog.h').read_text(encoding='utf-8')
    dictionary = int(data['dictionary'], 16)
    match = re.search(r'constexpr uint32_t kDictionary = 0x([0-9a-fA-F]+)u;', header)
    if not match or int(match.group(1), 16) != dictionary:
        raise ValueError('Firmware and coach catalogs differ; restore matching package files.')
    counts = {'UnitCount': len(units) + 1, 'PitchCount': len(data['pitches']),
              'Rows': len(data['rows']), 'Cols': len(data['cols']),
              'LocationCount': len(data['locations']), 'PlayCount': len(data['plays'])}
    if counts['LocationCount'] != counts['Rows'] * counts['Cols']:
        raise ValueError('The call catalog has an incomplete location grid.')
    for name, count in counts.items():
        match = re.search(r'constexpr unsigned k' + name + r' = (\d+);', header)
        if not match or int(match.group(1)) != count:
            raise ValueError(f'Firmware and coach catalog {name} differ.')
    for index, key in enumerate(keys, 1):
        match = re.search(r'^#define PC_UNIT_' + re.escape(key) + r' (\d+)$', header, re.MULTILINE)
        if not match or int(match.group(1)) != index:
            raise ValueError(f'Firmware and roster disagree on unit {key}.')
    return data, dictionary
