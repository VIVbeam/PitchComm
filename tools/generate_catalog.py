"""Generate matching firmware and laptop dictionaries (standard library only).

`config/calls.json` (schema 3) is the vocabulary source of truth and
`config/roster.json` (schema 1) is the enrollment source of truth. Counts are
data: M pitches, R rows, C columns, R*C locations in row-major order, N plays,
and the coach plus the enrolled units. Play targets are group names
(`battery`, `infield`, `outfield`, `all`) or explicit roster keys, resolved
against the enrolled units only. The dictionary hash is FNV-1a over the
canonical JSON of the vocabulary plus the enrolled unit keys and their
call-routing capabilities (EUIs and the relay build flag never enter it), so
any vocabulary or enrollment edit changes it and forces a rebuild on every unit.
"""
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 3
ROSTER_SCHEMA = 1
DISPLAY_LIMIT = 11
SHORT_LIMIT = 4
SPEECH_LIMIT = 80
ENROLLED_LIMIT = 15
STANDARD_KEYS = ('pitcher', 'catcher', 'first', 'second', 'third',
                 'shortstop', 'left', 'center', 'right')
GROUPS = {'battery': ('pitcher', 'catcher'),
          'infield': ('first', 'second', 'third', 'shortstop'),
          'outfield': ('left', 'center', 'right'),
          'all': STANDARD_KEYS}
UNIT_FIELDS = ('key', 'label', 'short', 'relay', 'audio', 'display', 'controls', 'pitches')
KEY_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def atomic_text(path,contents):
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',
                                         dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as output:
            temporary=Path(output.name)
            output.write(contents); output.flush(); os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def _text(item,field,where):
    value=item.get(field)
    if not isinstance(value,str) or not value or value!=value.strip():
        raise ValueError(f'{where}: {field} must be a nonempty string without leading or trailing spaces')
    if any(not 32<=ord(c)<=126 for c in value):
        raise ValueError(f'{where}: {field} must be printable ASCII')
    return value


def _display(item,field,where):
    value=_text(item,field,where)
    if len(value)>DISPLAY_LIMIT:
        raise ValueError(f'{where}: {field} must be at most {DISPLAY_LIMIT} characters')
    return value


def _short(item,field,where):
    value=_text(item,field,where)
    if len(value)>SHORT_LIMIT:
        raise ValueError(f'{where}: {field} must be at most {SHORT_LIMIT} characters')
    return value


def _speech(item,where):
    value=_text(item,'speech',where)
    if len(value)>SPEECH_LIMIT:
        raise ValueError(f'{where}: speech must be at most {SPEECH_LIMIT} characters')
    return value


def _file(item,where):
    name=_text(item,'file',where)
    if Path(name).name!=name:
        raise ValueError(f'{where}: file must be a plain name under College Demo Tracks')
    return name


def _bool(item,field,where):
    value=item.get(field)
    if type(value) is not bool:
        raise ValueError(f'{where}: {field} must be a boolean')
    return value


def _key(item,where):
    value=_text(item,'key',where)
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError(f'{where}: key must be a C identifier (letter or underscore, then letters, '
                         'digits or underscores)')
    return value


def _keyed(data,group):
    items=data.get(group)
    if not isinstance(items,list) or not items:
        raise ValueError(f'{group} must be a list with at least one item')
    keys=[]
    for index,item in enumerate(items):
        if not isinstance(item,dict) or type(item.get('key')) is not int:
            raise ValueError(f'{group}[{index}]: key must be an integer')
        keys.append(item['key'])
    if sorted(keys)!=list(range(1,len(items)+1)):
        raise ValueError(f'{group} must define keys 1 through {len(items)} exactly once')
    return items


def pitch_code(pitch,row,col,pitches,rows,cols):
    if not 1<=pitch<=pitches or not 1<=row<=rows or not 1<=col<=cols:
        raise ValueError('pitch call is outside the configured grid')
    return (pitch-1)*rows*cols+(row-1)*cols+col


def load_roster(root=None):
    """Return the validated roster units in file order (all nine standard keys allowed, custom keys too)."""
    root = ROOT if root is None else Path(root)
    data = json.loads((root / 'config/roster.json').read_text(encoding='utf-8'))
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data.get('schema')!=ROSTER_SCHEMA:
        raise ValueError(f'config/roster.json must be a schema {ROSTER_SCHEMA} object')
    units = data.get('units')
    if not isinstance(units,list) or not units:
        raise ValueError('roster units must be a list with at least one unit')
    seen=set()
    for index,unit in enumerate(units,1):
        where=f'units[{index}]'
        if not isinstance(unit,dict):
            raise ValueError(f'{where}: must be an object')
        key=_key(unit,where)
        if key in seen:
            raise ValueError(f'{where}: duplicate unit key {key!r}')
        seen.add(key)
        # The label is the desk name, not the 11-character fielder-strip
        # display label carried by plays; `short` is the menu/status label.
        _text(unit,'label',where)
        _short(unit,'short',where)
        _bool(unit,'enrolled',where)
        for field in ('relay','audio','display','controls','pitches'):
            _bool(unit,field,where)
        # display64 selects the 128x64 fielder panel. It is a build/layout
        # choice, not a call-routing capability, so it stays out of UNIT_FIELDS,
        # gui/catalog.json, the firmware header and the dictionary hash. Old
        # rosters and fixtures without the field load with the 32-row default.
        if 'display64' in unit:
            _bool(unit,'display64',where)
        else:
            unit['display64']=False
    enrolled=[unit for unit in units if unit['enrolled']]
    if not enrolled:
        raise ValueError('roster must enroll at least one unit')
    if len(enrolled)>ENROLLED_LIMIT:
        raise ValueError(f'roster enrolls {len(enrolled)} units; at most {ENROLLED_LIMIT} fit the 16-bit unit mask')
    if not any(unit['pitches'] for unit in enrolled):
        raise ValueError('roster must enroll at least one unit with the pitches capability')
    return units


def _public_unit(unit):
    return {field:unit[field] for field in UNIT_FIELDS}


def _audience(play,units):
    """Resolve one play's targets to the enrolled unit keys, in unit order."""
    where=f'plays[{play["key"]}]'
    targets=play.get('targets')
    if not isinstance(targets,list) or not targets:
        raise ValueError(f'{where}: targets must be a nonempty list')
    keys=set()
    for target in targets:
        if not isinstance(target,str) or not target or target!=target.strip():
            raise ValueError(f'{where}: targets must be nonempty strings without leading or trailing spaces')
        if target in GROUPS:
            keys.update(GROUPS[target])
        elif any(unit['key']==target for unit in units):
            keys.add(target)
        else:
            raise ValueError(f'{where}: target {target!r} is not a group or roster key')
    audience=[unit['key'] for unit in units if unit['enrolled'] and unit['key'] in keys]
    if not audience:
        raise ValueError(f'{where}: targets reach no enrolled unit')
    return audience


def unit_index(data):
    """Map every enrolled key to its generated unit index; the coach is 0."""
    return {unit['key']:index for index,unit in enumerate(data['units'],1)}


def unit_mask(data,keys):
    """Return the uint16_t bit mask for a list of enrolled unit keys."""
    index=unit_index(data)
    value=0
    for key in keys:
        value |= 1<<index[key]
    return value


def _dictionary(data,units):
    """FNV-1a over the calls plus the enrolled units and their capabilities, in roster order."""
    enrolled=[unit for unit in units if unit['enrolled']]
    payload={'schema':data['schema'],'pitches':data['pitches'],'rows':data['rows'],
             'cols':data['cols'],'locations':data['locations'],
             'plays':[{field:play[field] for field in
                       ('key','label','shortstop','centerfield','speech','targets','file')}
                      for play in data['plays']],
             # Relay and display64 stay out of the dictionary: they are
             # network-layer/build-layout choices, not call-routing
             # capabilities, so the hash must not move when only a unit's relay
             # flag or panel size changes.
             'units':[{field:unit[field] for field in
                       ('key','audio','display','controls','pitches')}
                      for unit in enrolled]}
    canonical=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    value = 2166136261
    for byte in canonical:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def load(root=None):
    root = ROOT if root is None else Path(root)
    data = json.loads((root / 'config/calls.json').read_text(encoding='utf-8'))
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data.get('schema')!=SCHEMA:
        raise ValueError(f'config/calls.json must be a schema {SCHEMA} object')
    pitches = _keyed(data,'pitches')
    rows = _keyed(data,'rows')
    cols = _keyed(data,'cols')
    plays = _keyed(data,'plays')
    for pitch in pitches:
        where=f'pitches[{pitch["key"]}]'
        _display(pitch,'label',where); _short(pitch,'short',where)
        _speech(pitch,where); _file(pitch,where)
    for row in rows:
        where=f'rows[{row["key"]}]'
        _display(row,'label',where); _short(row,'short',where); _speech(row,where)
    for col in cols:
        where=f'cols[{col["key"]}]'
        _display(col,'label',where); _short(col,'short',where); _speech(col,where)
    locations = data.get('locations')
    expected = len(rows)*len(cols)
    if not isinstance(locations,list) or len(locations)!=expected:
        raise ValueError(f'locations must hold rows*cols = {expected} entries')
    for index,location in enumerate(locations,1):
        row,col=divmod(index-1,len(cols)); row+=1; col+=1
        if (not isinstance(location,dict) or type(location.get('row')) is not int
                or type(location.get('col')) is not int
                or location['row']!=row or location['col']!=col):
            raise ValueError(f'locations[{index}] must be row {row} col {col} in row-major order')
        where=f'locations[{index}]'
        _speech(location,where); _file(location,where)
    units = load_roster(root)
    for play in plays:
        where=f'plays[{play["key"]}]'
        _display(play,'label',where); _display(play,'shortstop',where)
        _display(play,'centerfield',where); _speech(play,where); _file(play,where)
        play['audience'] = _audience(play,units)
    data['units'] = [_public_unit(unit) for unit in units if unit['enrolled']]
    data['allUnits'] = [_public_unit(unit) for unit in units]
    version = _dictionary(data,units)
    return data, version


def clips(data):
    """Return every shipped clip as (file name, spoken text).

    Pitches and locations ship when at least one audio unit receives pitch
    calls; a play clip ships when the play's resolved audience includes an
    audio unit. `data` comes from load(), so the audience is already resolved.
    """
    pitch_clips = [(f'p{pitch["key"]:02d}.wav', pitch['speech'])
                   for pitch in sorted(data['pitches'], key=lambda x: x['key'])]
    location_clips = [(f'l{index}.wav', location['speech'])
                      for index, location in enumerate(data['locations'], 1)]
    audio_mask = unit_mask(data,[unit['key'] for unit in data['units'] if unit['audio']])
    result=[]
    if unit_mask(data,[unit['key'] for unit in data['units'] if unit['pitches']]) & audio_mask:
        result += pitch_clips + location_clips
    for play in sorted(data['plays'], key=lambda x: x['key']):
        if unit_mask(data,play['audience']) & audio_mask:
            result.append((f'd{play["key"]:02d}.wav', play['speech']))
    return result


def render(data, version):
    """Return the generated firmware header and GUI catalog for one dictionary."""
    for derived in ('units','allUnits'):
        if derived not in data:
            raise ValueError(f'render() needs data from load(): missing {derived}')
    pitches = sorted(data['pitches'], key=lambda x: x['key'])
    rows = sorted(data['rows'], key=lambda x: x['key'])
    cols = sorted(data['cols'], key=lambda x: x['key'])
    locations = data['locations']
    plays = sorted(data['plays'], key=lambda x: x['key'])
    units = data['units']
    index = unit_index(data)
    row_count, col_count = len(rows), len(cols)
    audio_mask = unit_mask(data,[unit['key'] for unit in units if unit['audio']])
    pitch_mask = unit_mask(data,[unit['key'] for unit in units if unit['pitches']])

    lines = ['// Generated by tools/generate_catalog.py; edit config/calls.json and config/roster.json instead.',
             '#pragma once', '#include "protocol.h"', '',
             '// Unit selectors for -DPC_UNIT=<key>; unit 0 is the coach, and keys that are not enrolled map to 0.']
    lines += [f'#define PC_UNIT_{unit["key"]} {index.get(unit["key"],0)}' for unit in data['allUnits']]
    lines += ['', 'namespace pc {',
              f'constexpr uint32_t kDictionary = 0x{version:08x}u;',
              f'constexpr unsigned kPitchCount = {len(pitches)};',
              f'constexpr unsigned kRows = {row_count};',
              f'constexpr unsigned kCols = {col_count};',
              f'constexpr unsigned kLocationCount = {len(locations)};',
              f'constexpr unsigned kPlayCount = {len(plays)};',
              f'constexpr unsigned kUnitCount = {len(units)+1};',
              'constexpr uint16_t pitchCode(unsigned type, unsigned row, unsigned col) {',
              '  return type>=1 && type<=kPitchCount && row>=1 && row<=kRows && col>=1 && col<=kCols ? uint16_t((type-1)*kRows*kCols+(row-1)*kCols+col) : 0;',
              '}',
              'constexpr uint16_t kUnitMask(unsigned unit) { return uint16_t(1u << unit); }',
              'inline constexpr const char* kUnitLabel[] = {']
    lines += [f'  {json.dumps(label)},' for label in ['Coach']+[unit['label'] for unit in units]]
    lines += ['};', 'inline constexpr const char* kUnitShort[] = {']
    lines += [f'  {json.dumps(short)},' for short in ['CO']+[unit['short'] for unit in units]]
    lines += ['};', 'inline constexpr bool kUnitAudio[] = {']
    lines += [f'  {str(bool(flag)).lower()},' for flag in [False]+[unit['audio'] for unit in units]]
    lines += ['};', 'inline constexpr bool kUnitDisplay[] = {']
    lines += [f'  {str(bool(flag)).lower()},' for flag in [False]+[unit['display'] for unit in units]]
    lines += ['};', 'inline constexpr bool kUnitControls[] = {']
    lines += [f'  {str(bool(flag)).lower()},' for flag in [False]+[unit['controls'] for unit in units]]
    lines += ['};', 'inline constexpr bool kUnitPitches[] = {']
    lines += [f'  {str(bool(flag)).lower()},' for flag in [False]+[unit['pitches'] for unit in units]]
    lines += ['};',
              'struct Call { Category category; uint16_t code; uint16_t audience; const char* label; const char* ss; const char* cf; const char* audio[3]; };',
              'inline constexpr const char* kPitchShort[] = {']
    lines += [f'  {json.dumps(pitch["short"])},' for pitch in pitches]
    lines += ['};', 'inline constexpr const char* kRowShort[] = {']
    lines += [f'  {json.dumps(row["short"])},' for row in rows]
    lines += ['};', 'inline constexpr const char* kColShort[] = {']
    lines += [f'  {json.dumps(col["short"])},' for col in cols]
    lines += ['};', 'inline constexpr Call kCalls[] = {']
    for pitch in pitches:
        for row in rows:
            for col in cols:
                label = f'{pitch["label"]} {row["label"]} {col["label"]}'
                fields = ', '.join(json.dumps(label) for _ in range(3))
                location = (row["key"] - 1) * col_count + col["key"]
                audio = ', '.join(json.dumps(path) for path in
                                  (f'/audio/p{pitch["key"]:02d}.wav', f'/audio/l{location}.wav', ''))
                code = pitch_code(pitch["key"], row["key"], col["key"], len(pitches), row_count, col_count)
                lines.append(f'  {{Category::Pitch, {code}, {pitch_mask}, {fields}, {{{audio}}}}},')
    for play in plays:
        fields = ', '.join(json.dumps(play[field]) for field in ('label', 'shortstop', 'centerfield'))
        if unit_mask(data,play['audience']) & audio_mask:
            audio = ', '.join(json.dumps(path) for path in (f'/audio/d{play["key"]:02d}.wav', '', ''))
        else:
            audio = ', '.join(json.dumps(path) for path in ('', '', ''))
        lines.append(f'  {{Category::Play, {play["key"]}, {unit_mask(data,play["audience"])}, {fields}, {{{audio}}}}},')
    lines += ['};',
              'constexpr const Call* findCall(Category cat, uint16_t code) {',
              '  for (const auto& c:kCalls) if (c.category==cat && c.code==code) return &c;',
              '  return nullptr;', '}',
              'constexpr uint16_t recipients(Category category, uint16_t code) {',
              '  for (const auto& c:kCalls) if (c.category==category && c.code==code) return c.audience;',
              '  return 0;', '}',
              '} // namespace pc', '']

    catalog = {'dictionary': f'{version:08x}', 'schema': data['schema'],
               'units': [_public_unit(unit) for unit in units],
               'pitches': [{'key': p['key'], 'label': p['label'], 'short': p['short'],
                            'speech': p['speech']} for p in pitches],
               'rows': [{'key': r['key'], 'label': r['label'], 'short': r['short'],
                         'speech': r['speech']} for r in rows],
               'cols': [{'key': c['key'], 'label': c['label'], 'short': c['short'],
                         'speech': c['speech']} for c in cols],
               'locations': [{'row': l['row'], 'col': l['col'], 'speech': l['speech']}
                             for l in locations],
               'plays': [{'key': p['key'], 'label': p['label'], 'shortstop': p['shortstop'],
                          'centerfield': p['centerfield'], 'speech': p['speech'],
                          'audience': list(p['audience'])} for p in plays]}
    return {'firmware/include/pc/catalog.h': '\n'.join(lines),
            'gui/catalog.json': json.dumps(catalog, indent=2) + '\n'}


def rendered(root=None):
    """Return the generated dictionary value and both files without changing the project."""
    data, version = load(root)
    return version, render(data, version)


def generate():
    # Vocabulary belongs to the same setup transaction as firmware keys and
    # recordings. Hold exclusion across rendering and both generated writes,
    # so an upload cannot observe a dictionary changed halfway through a build.
    build=ROOT/'build'
    build.mkdir(exist_ok=True)
    lock=build/'validation.lock'
    owner=f'CATALOG GENERATION PID {os.getpid()} TOKEN {secrets.token_hex(16)}\n'.encode('ascii')
    try:
        handle=lock.open('xb')
    except FileExistsError as error:
        raise ValueError('Configuration is already locked. Finish active upload, validation, provisioning '
                         'or audio/catalog generation before regenerating vocabulary. After an '
                         'interruption, verify the owning process stopped before clearing '
                         'build/validation.lock; then rerun generation and preflight.') from error
    identity=os.fstat(handle.fileno())
    published=False
    try:
        with handle:
            handle.write(owner)
            handle.flush()
            os.fsync(handle.fileno())
        published=True
        data, version = load()
        files = render(data, version)
        for name, contents in files.items():
            target = ROOT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_text(target,contents)
        print(f'Dictionary {version:08x}: {len(data["pitches"])} pitches x '
              f'{len(data["rows"])} rows x {len(data["cols"])} cols = {len(data["locations"])} locations, '
              f'{len(data["plays"])} plays, {len(data["units"])} enrolled units, {len(clips(data))} audio clips')
    finally:
        # Never clear another operation's replacement/interrupted lock.
        try:
            current=lock.stat()
            same_creation=(current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino)
            if lock.read_bytes()==owner or (not published and same_creation):
                lock.unlink()
        except FileNotFoundError:
            pass

if __name__ == '__main__':
    generate()
