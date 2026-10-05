import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { coachUnit, unitAt, unitIndexOf, deliveryLabels, pitchCode, decodePitch, keyAction, formatClock, formatLatency, describe, command, validState, validResult, blockReason, LineFramer } from '../core.js';

const catalog = JSON.parse(readFileSync(new URL('../catalog.json', import.meta.url), 'utf8'));
const DICTIONARY = '94b7a24a';
const ROWS = catalog.rows.length;
const COLS = catalog.cols.length;
const MAX_PITCH = catalog.pitches.length * ROWS * COLS;
const UNIT_COUNT = catalog.units.length + 1;
const LIMITS = {rows: ROWS, cols: COLS, maxPitch: MAX_PITCH, maxPlay: catalog.plays.length, unitCount: UNIT_COUNT};
const SESSION = Object.freeze({client: 'a1b2c3d4', boot: '0011223344556677', dictionary: DICTIONARY, clock: 0x1000});

function stateFixture(overrides = {}) {
  return {
    type: 'state', v: 4, client: 'a1b2c3d4', clock: 0x01020304, role: 0,
    dictionary: DICTIONARY, boot: '0011223344556677',
    configured: 1, radio: 1, busy: 0,
    seq: 5, category: 1, code: 41,
    links: [1, 0, 1, 1, 1], delivery: [0, 2, 2, 0, 0],
    records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ],
    ...overrides,
  };
}

function resultFixture(overrides = {}) {
  return {
    type: 'result', v: 4, client: 'a1b2c3d4', boot: '0011223344556677',
    id: 7, result: 0, seq: 3,
    ...overrides,
  };
}

test('the loaded catalog is the schema 3 vocabulary', () => {
  assert.equal(catalog.schema, 3);
  assert.equal(catalog.dictionary, DICTIONARY);
  assert.deepEqual([catalog.pitches.length, ROWS, COLS, catalog.locations.length, catalog.plays.length], [9, 3, 3, 9, 21]);
  assert.equal(MAX_PITCH, 81);
  assert.deepEqual(LIMITS, {rows: 3, cols: 3, maxPitch: 81, maxPlay: 21, unitCount: 5});
});

test('catalog units are the enrolled roster in unit index order', () => {
  assert.deepEqual(catalog.units.map(unit => unit.key), ['pitcher', 'catcher', 'shortstop', 'center']);
  assert.deepEqual(catalog.units.map(unit => unit.label), ['Pitcher', 'Catcher', 'Shortstop', 'Center field']);
  assert.deepEqual(catalog.units.map(unit => unit.short), ['P', 'C', 'SS', 'CF']);
  assert.deepEqual(catalog.units.map(unit => [unit.audio, unit.display, unit.controls, unit.pitches]), [
    [true, false, false, true],
    [false, true, true, true],
    [false, true, false, false],
    [false, true, false, false],
  ]);
  assert.deepEqual(coachUnit, {key: 'coach', label: 'Coach', short: 'CO'});
});

test('unitAt maps the coach at index 0 and roster units above it', () => {
  assert.equal(unitAt(catalog, 0), coachUnit);
  catalog.units.forEach((unit, index) => assert.equal(unitAt(catalog, index + 1), unit));
  assert.equal(unitAt(catalog, UNIT_COUNT), null);
  assert.equal(unitAt(catalog, -1), null);
  assert.equal(unitAt(catalog, 1.5), null);
  assert.equal(unitAt(catalog, '1'), null);
  assert.equal(unitAt(undefined, 1), null);
  assert.equal(unitIndexOf(catalog, 'pitcher'), 1);
  assert.equal(unitIndexOf(catalog, 'catcher'), 2);
  assert.equal(unitIndexOf(catalog, 'shortstop'), 3);
  assert.equal(unitIndexOf(catalog, 'center'), 4);
  assert.equal(unitIndexOf(catalog, 'coach'), -1);
  assert.equal(unitIndexOf(catalog, 'none'), -1);
  assert.equal(unitIndexOf(undefined, 'pitcher'), -1);
});

test('play audiences resolve to enrolled unit keys in unit order', () => {
  const keys = catalog.units.map(unit => unit.key);
  for (const play of catalog.plays) {
    assert.ok(play.audience.length > 0, `play ${play.key} targets at least one unit`);
    assert.deepEqual(play.audience, keys.filter(key => play.audience.includes(key)), `play ${play.key} audience order`);
  }
  assert.equal(catalog.plays[20].key, 21);
  assert.deepEqual(catalog.plays[20].audience, ['pitcher', 'catcher']);
  const audienceLabels = keysOf => keysOf.map(key => unitAt(catalog, unitIndexOf(catalog, key)).label).join(' + ');
  assert.equal(audienceLabels(catalog.plays[20].audience), 'Pitcher + Catcher');
  assert.deepEqual(catalog.plays[17].audience, ['center']);
  assert.equal(audienceLabels(catalog.plays[17].audience), 'Center field');
  assert.ok(catalog.plays.some(play => play.audience.length < catalog.units.length), 'a reduced audience exists');
});

test('pitchCode maps every type, row, and col to a unique code from 1 to 81', () => {
  const seen = new Set();
  for (let type = 1; type <= 9; type++) {
    for (let row = 1; row <= 3; row++) {
      for (let col = 1; col <= 3; col++) {
        const code = pitchCode(type, row, col, 3, 3);
        assert.equal(code, (type - 1) * 9 + (row - 1) * 3 + col);
        assert.ok(code >= 1 && code <= 81);
        assert.equal(seen.has(code), false, `duplicate code ${code}`);
        seen.add(code);
      }
    }
  }
  assert.equal(seen.size, 81);
  assert.equal(pitchCode(1, 1, 1, 3, 3), 1);
  assert.equal(pitchCode(1, 2, 1, 3, 3), 4);
  assert.equal(pitchCode(2, 1, 1, 3, 3), 10);
  assert.equal(pitchCode(9, 3, 3, 3, 3), 81);
});

test('pitchCode follows the configured grid counts instead of fixed dimensions', () => {
  assert.equal(pitchCode(2, 3, 2, 4, 5), 32);
  assert.equal(pitchCode(1, 4, 5, 4, 5), 20);
  assert.equal(pitchCode(3, 1, 1, 2, 2), 9);
  // The code formula extends across any number of types; command() is what
  // caps the total with the maxPitch supplied by the caller.
  assert.equal(pitchCode(10, 1, 1, 3, 3), 82);
});

test('pitchCode returns 0 outside the row and col bounds and for non-integer inputs', () => {
  const cases = [
    [0, 1, 1, 3, 3], [1, 0, 1, 3, 3], [1, 4, 1, 3, 3], [1, 1, 0, 3, 3], [1, 1, 4, 3, 3],
    [-1, 1, 1, 3, 3], [1, -1, 1, 3, 3], [1, 1, -1, 3, 3],
    [1, 1, 1, 0, 3], [1, 1, 1, 3, 0],
    [1.5, 1, 1, 3, 3], [1, 1.5, 1, 3, 3], [1, 1, 1.5, 3, 3], [NaN, 1, 1, 3, 3], [Infinity, 1, 1, 3, 3],
    ['1', 1, 1, 3, 3], [null, 1, 1, 3, 3], [true, 1, 1, 3, 3], [undefined, 1, 1, 3, 3],
    [1, 1, 1, '3', 3], [1, 1, 1, 3, '3'],
  ];
  for (const bad of cases) assert.equal(pitchCode(...bad), 0, JSON.stringify(bad));
  assert.equal(pitchCode(), 0);
  assert.equal(pitchCode(1), 0);
  assert.equal(pitchCode(1, 2), 0);
  assert.equal(pitchCode(1, 2, 3), 0);
  assert.equal(pitchCode(1, 2, 3, 3), 0);
});

test('describe builds every pitch label from pitch speech and location speech', () => {
  assert.equal(describe(catalog, 1, 1), 'Four-Seam Fastball \u00b7 High Inside');
  assert.equal(describe(catalog, 1, 41), 'Sinker \u00b7 Middle Center');
  assert.equal(describe(catalog, 1, 81), 'Splitter \u00b7 Low Outside');
  for (let code = 1; code <= MAX_PITCH; code++) {
    const type = Math.floor((code - 1) / (ROWS * COLS)) + 1;
    const row = Math.floor(((code - 1) % (ROWS * COLS)) / COLS) + 1;
    const col = (code - 1) % COLS + 1;
    const pitch = catalog.pitches.find(p => p.key === type);
    const location = catalog.locations[(row - 1) * COLS + (col - 1)];
    assert.equal(describe(catalog, 1, code), `${pitch.speech} \u00b7 ${location.speech}`);
  }
});

test('describe returns play labels and safe fallbacks', () => {
  assert.equal(catalog.plays.length, 21);
  for (const play of catalog.plays) assert.equal(describe(catalog, 2, play.key), play.label);
  assert.equal(describe(catalog, 2, 10), catalog.plays[9].label);
  assert.equal(describe(catalog, 2, 21), 'IGNORE RUN');
  assert.equal(describe(catalog, 2, 0), 'Unknown play');
  assert.equal(describe(catalog, 2, 22), 'Unknown play');
  assert.equal(describe(catalog, 2, '1'), 'Unknown play');
  assert.equal(describe(catalog, 1, 0), 'Waiting for the first call');
  assert.equal(describe(catalog, 0, 0), 'Waiting for the first call');
  assert.equal(describe(catalog, 1, catalog.pitchFlow.maxCode+1), 'Waiting for the first call');
  assert.equal(describe(catalog, 2, 1.5), 'Unknown play');
});

test('command accepts high-numbered plays and count-aware pitch calls', () => {
  const suffix = `0011223344556677 ${DICTIONARY} 5596\n`;
  assert.equal(command(7, 2, 21, 0, 0, SESSION, LIMITS), `call a1b2c3d4 7 d 21 ${suffix}`);
  assert.equal(command(8, 2, 21, 0, 0, SESSION), `call a1b2c3d4 8 d 21 ${suffix}`);
  assert.equal(command(9, 1, 9, 3, 3, SESSION, LIMITS), `call a1b2c3d4 9 p 9 3 3 ${suffix}`);
  const small = {rows: 4, cols: 5, maxPitch: 40, maxPlay: 2};
  assert.equal(command(10, 1, 2, 4, 5, SESSION, small), `call a1b2c3d4 10 p 2 4 5 ${suffix}`);
  assert.equal(command(11, 2, 2, 0, 0, SESSION, small), `call a1b2c3d4 11 d 2 ${suffix}`);
});

test('command rejects calls outside the configured counts and session', () => {
  assert.throws(() => command(1, 2, 22, 0, 0, SESSION, LIMITS), /Complete the call before sending/);
  assert.throws(() => command(1, 2, 22, 0, 0, SESSION), /Complete the call before sending/);
  assert.throws(() => command(1, 2, 10, 0, 0, SESSION, {maxPlay: 9}), /Complete the call before sending/);
  assert.throws(() => command(1, 1, 10, 1, 1, SESSION, LIMITS), /Complete the call before sending/);
  assert.throws(() => command(1, 1, 1, 4, 1, SESSION, LIMITS), /Complete the call before sending/);
  assert.throws(() => command(1, 1, 1, 1, 4, SESSION, LIMITS), /Complete the call before sending/);
  assert.throws(() => command(1, 1, 3, 1, 1, SESSION, {rows: 4, cols: 5, maxPitch: 40, maxPlay: 2}), /Complete the call before sending/);
  assert.throws(() => command(0, 1, 1, 1, 1, SESSION, LIMITS), /Invalid request ID/);
  assert.throws(() => command(1, 1, 1, 1, 1, {...SESSION, client: '00000000'}, LIMITS), /fresh coach session/);
  assert.throws(() => command(1, 1, 1, 1, 1, {...SESSION, clock: -1}, LIMITS), /fresh coach session/);
});

test('validState accepts a consistent coach state', () => {
  assert.equal(validState(stateFixture(), LIMITS), true);
});

test('validState accepts an idle state with zeroed records', () => {
  assert.equal(validState(stateFixture({
    seq: 0, category: 0, code: 0, delivery: [0, 0, 0, 0, 0],
    records: [
      { category: 1, seq: 0, code: 0, delivery: [0, 0, 0, 0, 0] },
      { category: 2, seq: 0, code: 0, delivery: [0, 0, 0, 0, 0] },
    ],
  }), LIMITS), true);
});

test('validState accepts a play state whose current record matches the call', () => {
  assert.equal(validState(stateFixture({
    seq: 21, category: 2, code: 21, delivery: [0, 2, 3, 0, 0],
    records: [
      { category: 1, seq: 20, code: 81, delivery: [0, 4, 2, 0, 0] },
      { category: 2, seq: 21, code: 21, delivery: [0, 2, 3, 0, 0] },
    ],
  }), LIMITS), true);
});

test('validState skips record consistency rules for non-coach roles', () => {
  for (let role = 1; role < UNIT_COUNT; role++) {
    assert.equal(validState(stateFixture({
      role,
      records: [
        { category: 1, seq: 99, code: 81, delivery: [0, 4, 4, 0, 0] },
        { category: 2, seq: 7, code: 21, delivery: [0, 3, 3, 0, 0] },
      ],
    }), LIMITS), true, `role ${role}`);
  }
});

test('validState accepts an older record sequence across the uint32 wrap', () => {
  assert.equal(validState(stateFixture({
    records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 0xfffffffe, code: 21, delivery: [0, 0, 0, 0, 0] },
    ],
  }), LIMITS), true);
});

test('validState enforces the catalog counts at the top of each range', () => {
  assert.equal(validState(stateFixture({
    seq: 81, category: 1, code: 81, delivery: [0, 2, 2, 0, 0],
    records: [
      { category: 1, seq: 81, code: 81, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 80, code: 21, delivery: [0, 0, 0, 0, 0] },
    ],
  }), LIMITS), true);
  assert.equal(validState(stateFixture({
    seq: 21, category: 2, code: 21, delivery: [0, 2, 2, 0, 0],
    records: [
      { category: 1, seq: 20, code: 81, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 21, code: 21, delivery: [0, 2, 2, 0, 0] },
    ],
  }), LIMITS), true);
  assert.equal(validState(stateFixture({ seq: 82, category: 1, code: 82 }), LIMITS), false);
  const highPlay = stateFixture({ seq: 10, category: 2, code: 10, records: [
    { category: 1, seq: 8, code: 81, delivery: [0, 2, 2, 0, 0] },
    { category: 2, seq: 10, code: 10, delivery: [0, 2, 2, 0, 0] },
  ] });
  assert.equal(validState(highPlay, {maxPitch: 81, maxPlay: 9, unitCount: 5}), false, 'compatibility limits keep the old nine-play ceiling');
  assert.equal(validState(highPlay, LIMITS), true, 'the real counts accept play 10');
  assert.equal(validState(stateFixture({ seq: 22, category: 2, code: 22, records: [
    { category: 1, seq: 20, code: 81, delivery: [0, 2, 2, 0, 0] },
    { category: 2, seq: 22, code: 22, delivery: [0, 2, 2, 0, 0] },
  ] }), LIMITS), false);
  assert.equal(validState(stateFixture({ role: 4 }), LIMITS), true, 'the last enrolled unit index is valid');
  assert.equal(validState(stateFixture({ role: UNIT_COUNT }), LIMITS), false);
});

test('validState sizes links, delivery, and record arrays to the unit count', () => {
  const four = {rows: ROWS, cols: COLS, maxPitch: MAX_PITCH, maxPlay: catalog.plays.length, unitCount: 4};
  const fourUnit = stateFixture({
    links: [1, 0, 1, 1],
    delivery: [0, 2, 2, 0],
    records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0] },
    ],
  });
  assert.equal(validState(fourUnit, four), true);
  assert.equal(validState(fourUnit, LIMITS), false, 'four-entry arrays fail the five-unit roster');
  assert.equal(validState(stateFixture(), four), false, 'five-entry arrays fail a four-unit roster');
});

test('validState rejects malformed scalar fields', () => {
  const cases = [
    ['missing state', undefined],
    ['null state', null],
    ['wrong type', stateFixture({ type: 'result' })],
    ['wrong version', stateFixture({ v: 3 })],
    ['bad client length', stateFixture({ client: 'a1b2c3d' })],
    ['bad client case', stateFixture({ client: 'A1B2C3D4' })],
    ['bad client characters', stateFixture({ client: 'a1b2c3dz' })],
    ['numeric client too short', stateFixture({ client: 1234 })],
    ['negative clock', stateFixture({ clock: -1 })],
    ['fractional clock', stateFixture({ clock: 1.5 })],
    ['oversized clock', stateFixture({ clock: 0x100000000 })],
    ['missing clock', stateFixture({ clock: undefined })],
    ['role too large', stateFixture({ role: UNIT_COUNT })],
    ['negative role', stateFixture({ role: -1 })],
    ['fractional role', stateFixture({ role: 1.5 })],
    ['bad dictionary case', stateFixture({ dictionary: '299314F6' })],
    ['bad dictionary length', stateFixture({ dictionary: '299314f' })],
    ['bad dictionary type', stateFixture({ dictionary: 1234 })],
    ['bad boot length', stateFixture({ boot: '001122334455667' })],
    ['bad boot case', stateFixture({ boot: '001122334455667F' })],
    ['configured out of range', stateFixture({ configured: 2 })],
    ['radio out of range', stateFixture({ radio: -1 })],
    ['busy boolean', stateFixture({ busy: true })],
    ['negative seq', stateFixture({ seq: -1 })],
    ['fractional seq', stateFixture({ seq: 1.5 })],
    ['oversized seq', stateFixture({ seq: 0x100000000 })],
    ['bad category', stateFixture({ category: 3 })],
    ['negative category', stateFixture({ category: -1 })],
    ['pitch code 0 with a call', stateFixture({ code: 0 })],
    ['pitch code over 81', stateFixture({ code: 82 })],
    ['pitch code below 1', stateFixture({ code: -1 })],
    ['idle state with a nonzero code', stateFixture({ seq: 0, code: 5 })],
    ['play code over 21', stateFixture({ seq: 9, category: 2, code: 22, records: [
      { category: 1, seq: 7, code: 81, delivery: [0, 4, 2, 0, 0] },
      { category: 2, seq: 9, code: 22, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['nonzero seq with category 0', stateFixture({ category: 0 })],
  ];
  for (const [name, value] of cases) assert.equal(validState(value, LIMITS), false, name);
});

test('validState rejects malformed link and delivery arrays', () => {
  const cases = [
    ['links not an array', stateFixture({ links: '10111' })],
    ['links too short', stateFixture({ links: [1, 0, 1, 1] })],
    ['links too long', stateFixture({ links: [1, 0, 1, 1, 1, 0] })],
    ['link value out of range', stateFixture({ links: [1, 0, 2, 1, 1] })],
    ['link value negative', stateFixture({ links: [1, 0, -1, 1, 1] })],
    ['delivery not an array', stateFixture({ delivery: '02200' })],
    ['delivery too short', stateFixture({ delivery: [0, 2, 2, 0] })],
    ['delivery too long', stateFixture({ delivery: [0, 2, 2, 0, 0, 0] })],
    ['coach delivery nonzero', stateFixture({ delivery: [1, 2, 2, 0, 0] })],
    ['delivery value over 4', stateFixture({ delivery: [0, 2, 2, 0, 5] })],
    ['delivery value negative', stateFixture({ delivery: [0, 2, 2, 0, -1] })],
    ['delivery value fractional', stateFixture({ delivery: [0, 2, 2, 0, 0.5] })],
  ];
  for (const [name, value] of cases) assert.equal(validState(value, LIMITS), false, name);
});

test('validState rejects malformed record entries', () => {
  const cases = [
    ['records not an array', stateFixture({ records: 'x' })],
    ['records too short', stateFixture({ records: [stateFixture().records[0]] })],
    ['records too long', stateFixture({ records: [...stateFixture().records, stateFixture().records[0]] })],
    ['null record', stateFixture({ records: [null, stateFixture().records[1]] })],
    ['record category mismatch', stateFixture({ records: [
      { category: 2, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record code 0 with a sequence', stateFixture({ records: [
      { category: 1, seq: 5, code: 0, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record code over 81', stateFixture({ records: [
      { category: 1, seq: 5, code: 82, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record play code over 21', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 22, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['idle record with nonzero delivery', stateFixture({ records: [
      { category: 1, seq: 0, code: 0, delivery: [0, 1, 0, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record delivery too short', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record delivery too long', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record coach delivery nonzero', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [1, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record delivery value over 4', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 5, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['negative record seq', stateFixture({ records: [
      { category: 1, seq: -1, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
  ];
  for (const [name, value] of cases) assert.equal(validState(value, LIMITS), false, name);
});

test('validState enforces record consistency against the current coach call', () => {
  const cases = [
    ['record newer than state', stateFixture({ records: [
      { category: 1, seq: 6, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['record sequence ambiguous at half the uint32 range', stateFixture({ seq: 0x40000000, records: [
      { category: 1, seq: 0x40000000, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 0xc0000000, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['idle state with a live record', stateFixture({ seq: 0, category: 0, code: 0, delivery: [0, 0, 0, 0, 0] })],
    ['older record in the current category', stateFixture({ records: [
      { category: 1, seq: 4, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['zero record in the current category during a call', stateFixture({ records: [
      { category: 1, seq: 0, code: 0, delivery: [0, 0, 0, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['current record code mismatch', stateFixture({ records: [
      { category: 1, seq: 5, code: 42, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
    ['current record delivery mismatch', stateFixture({ records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 3, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ] })],
  ];
  for (const [name, value] of cases) assert.equal(validState(value, LIMITS), false, name);
});

test('validResult accepts result 0 with a sequence and other results with seq 0', () => {
  assert.equal(validResult(resultFixture({ result: 0, seq: 3 }), LIMITS), true);
  for (let result = 1; result <= 5; result++) {
    assert.equal(validResult(resultFixture({ result, seq: 0 }), LIMITS), true, `result ${result}`);
  }
});

test('validResult rejects result and sequence combinations that cannot happen', () => {
  assert.equal(validResult(resultFixture({ result: 0, seq: 0 }), LIMITS), false);
  for (let result = 0; result <= 5; result++) {
    if (result === 0) continue;
    assert.equal(validResult(resultFixture({ result, seq: 4 }), LIMITS), false, `result ${result}`);
  }
});

test('validResult rejects malformed fields', () => {
  const cases = [
    ['missing result', undefined],
    ['wrong type', resultFixture({ type: 'state' })],
    ['wrong version', resultFixture({ v: 3 })],
    ['bad client', resultFixture({ client: 'A1B2C3D4' })],
    ['bad boot', resultFixture({ boot: '001122334455667' })],
    ['id 0', resultFixture({ id: 0 })],
    ['id over range', resultFixture({ id: 0x100000000 })],
    ['fractional id', resultFixture({ id: 1.5 })],
    ['negative result', resultFixture({ result: -1 })],
    ['result over 5', resultFixture({ result: 6 })],
    ['fractional result', resultFixture({ result: 1.5 })],
    ['negative seq', resultFixture({ result: 0, seq: -1 })],
    ['fractional seq', resultFixture({ result: 0, seq: 1.5 })],
    ['oversized seq', resultFixture({ result: 0, seq: 0x100000000 })],
  ];
  for (const [name, value] of cases) assert.equal(validResult(value, LIMITS), false, name);
});

test('blockReason reports each unmet requirement', () => {
  const ready = stateFixture();
  assert.equal(blockReason(ready, 100, DICTIONARY, null, 1100), '');
  assert.equal(blockReason(undefined, 0, DICTIONARY, null, 0), 'Connect the coach radio');
  assert.equal(blockReason(null, 0, DICTIONARY, null, 0), 'Connect the coach radio');
  assert.equal(blockReason(ready, 100, DICTIONARY, null, 1101), 'Connect the coach radio');
  assert.equal(blockReason(ready, 100, DICTIONARY, null, 1100, 'ffffffff'), 'Waiting for this USB session');
  assert.equal(blockReason(ready, 100, DICTIONARY, null, 1100, ready.client), '');
  assert.equal(blockReason(stateFixture({ role: 1 }), 100, DICTIONARY, null, 1100), 'Connect the coach unit');
  assert.equal(blockReason(stateFixture({ dictionary: '00000000' }), 100, DICTIONARY, null, 1100), 'Vocabulary mismatch: rebuild and reload');
  assert.equal(blockReason(stateFixture({ configured: 0 }), 100, DICTIONARY, null, 1100), 'Provision the units first');
  assert.equal(blockReason(stateFixture({ radio: 0 }), 100, DICTIONARY, null, 1100), 'Coach radio unavailable');
  assert.equal(blockReason(ready, 100, DICTIONARY, { id: 3 }, 1100), 'Waiting for the current call');
  assert.equal(blockReason(stateFixture({ busy: 1 }), 100, DICTIONARY, null, 1100), 'Waiting for the current call');
});

test('blockReason follows priority order when several requirements fail', () => {
  const stale = stateFixture({ role: 1, dictionary: '00000000', configured: 0, radio: 0, busy: 1 });
  assert.equal(blockReason(stale, 100, '11111111', { id: 3 }, 1101, 'ffffffff'), 'Connect the coach radio');
  assert.equal(blockReason(stale, 100, '11111111', { id: 3 }, 1100, 'ffffffff'), 'Waiting for this USB session');
  assert.equal(blockReason(stale, 100, '11111111', { id: 3 }, 1100), 'Connect the coach unit');
  assert.equal(blockReason(stateFixture({ dictionary: '00000000', configured: 0, radio: 0, busy: 1 }), 100, DICTIONARY, { id: 3 }, 1100), 'Vocabulary mismatch: rebuild and reload');
  assert.equal(blockReason(stateFixture({ configured: 0, radio: 0, busy: 1 }), 100, DICTIONARY, { id: 3 }, 1100), 'Provision the units first');
  assert.equal(blockReason(stateFixture({ radio: 0, busy: 1 }), 100, DICTIONARY, { id: 3 }, 1100), 'Coach radio unavailable');
  assert.equal(blockReason(stateFixture({ busy: 1 }), 100, DICTIONARY, { id: 3 }, 1100), 'Waiting for the current call');
});

test('LineFramer reassembles messages split across chunks and multiple lines per chunk', () => {
  const messages = [];
  const framer = new LineFramer(message => messages.push(message));
  framer.push('@PC {"a":');
  framer.push('1}\n');
  assert.deepEqual(messages, [{ a: 1 }]);

  framer.push('@PC {"b":2}\n');
  framer.push('@P');
  framer.push('C {"c":3}\n@PC {"d":4}\n');
  assert.deepEqual(messages, [{ a: 1 }, { b: 2 }, { c: 3 }, { d: 4 }]);
});

test('LineFramer holds a trailing partial line until its newline arrives', () => {
  const messages = [];
  const framer = new LineFramer(message => messages.push(message));
  framer.push('@PC {"a":1}');
  assert.deepEqual(messages, []);
  framer.push('\n');
  assert.deepEqual(messages, [{ a: 1 }]);
});

test('LineFramer drops overlong lines without parsing them', () => {
  const messages = [];
  const framer = new LineFramer(message => messages.push(message));
  framer.push('@PC ' + JSON.stringify({ ok: true, pad: 'x'.repeat(5000) }) + '\n');
  assert.deepEqual(messages, []);
  framer.push('@PC {"ok":true}\n');
  assert.deepEqual(messages, [{ ok: true }]);
});

test('LineFramer ignores non-marker lines and malformed JSON, then recovers', () => {
  const messages = [];
  const framer = new LineFramer(message => messages.push(message));
  framer.push('boot diagnostics\n');
  framer.push('@PCX {"n":2}\n');
  framer.push('@PC {not json}\n');
  framer.push('@PC \n');
  framer.push('@PC {"ok":1}\n');
  assert.deepEqual(messages, [{ ok: 1 }]);
});

test('LineFramer treats CR as padding and CRLF as a line break', () => {
  const messages = [];
  const framer = new LineFramer(message => messages.push(message));
  framer.push('@PC {"a":1}\r\n');
  framer.push('plain log\r\n');
  framer.push('@PC {"b":\r2}\r\n');
  framer.push('@PC {"c":3}\r\n@PC {"d":4}\r\n');
  assert.deepEqual(messages, [{ a: 1 }, { b: 2 }, { c: 3 }, { d: 4 }]);
});

test('delivery labels stay aligned with the five outcomes', () => {
  assert.deepEqual(deliveryLabels, ['--', 'Waiting', 'Output accepted', 'Unconfirmed', 'Output error']);
});

// Variable-roster coverage. The committed roster has four enrolled units; the
// variant below appends a standard "right" and a custom "bench" key in memory
// only, so these tests never depend on the committed roster staying at four.
const sourceCalls = JSON.parse(readFileSync(new URL('../../dev/protocol/calls.fixture.json', import.meta.url), 'utf8'));

// Group resolution mirrors dev/roster.md and tools/generate_catalog.py GROUPS.
// "all" lists the nine standard keys, so a custom key only receives a play
// when the play's targets name that key explicitly.
const STANDARD_UNIT_KEYS = ['pitcher', 'catcher', 'first', 'second', 'third', 'shortstop', 'left', 'center', 'right'];
const UNIT_GROUPS = {
  battery: ['pitcher', 'catcher'],
  infield: ['first', 'second', 'third', 'shortstop'],
  outfield: ['left', 'center', 'right'],
  all: STANDARD_UNIT_KEYS,
};

function buildVariantCatalog() {
  const variant = JSON.parse(JSON.stringify(catalog));
  variant.units.push(
    {key: 'right', label: 'Right field', short: 'RF', audio: false, display: true, controls: false, pitches: false},
    {key: 'bench', label: 'Bench', short: 'BN', audio: true, display: true, controls: false, pitches: true},
  );
  const targets = new Map(sourceCalls.plays.map(play => [play.key, [...play.targets]]));
  // No group resolves to a custom key, so the team names bench explicitly on one play.
  targets.set(1, [...targets.get(1), 'bench']);
  for (const play of variant.plays) {
    assert.ok(targets.has(play.key), `source targets exist for play ${play.key}`);
    const keys = new Set();
    for (const target of targets.get(play.key)) for (const key of UNIT_GROUPS[target] ?? [target]) keys.add(key);
    play.audience = variant.units.map(unit => unit.key).filter(key => keys.has(key));
  }
  return variant;
}

const variant = buildVariantCatalog();
const variantKeys = variant.units.map(unit => unit.key);
// unitCount counts unit index 0 (the coach), the same formula app.js uses
// (catalog.units.length + 1), so six enrolled units need unitCount 7.
const VARIANT_UNIT_COUNT = variant.units.length + 1;
const VARIANT_LIMITS = {
  rows: variant.rows.length, cols: variant.cols.length,
  maxPitch: variant.pitches.length * variant.rows.length * variant.cols.length,
  maxPlay: variant.plays.length, unitCount: VARIANT_UNIT_COUNT,
};

function variantState(overrides = {}) {
  const delivery = [0, 2, 2, 0, 0, 0, 0];
  return {
    type: 'state', v: 4, client: 'a1b2c3d4', clock: 0x01020304, role: 0,
    dictionary: DICTIONARY, boot: '0011223344556677',
    configured: 1, radio: 1, busy: 0,
    seq: 5, category: 1, code: 41,
    links: [1, 0, 1, 1, 0, 1, 0],
    delivery,
    records: [
      { category: 1, seq: 5, code: 41, delivery: [...delivery] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0, 0, 0] },
    ],
    ...overrides,
  };
}

test('variant catalog enrolls a standard and a custom unit beyond the committed roster', () => {
  assert.equal(variant.units.length, catalog.units.length + 2, 'the variant appends right and bench to the deep copy');
  assert.equal(variant.units.length, 6, 'six enrolled field units');
  assert.deepEqual(variantKeys, ['pitcher', 'catcher', 'shortstop', 'center', 'right', 'bench']);
  assert.equal(VARIANT_UNIT_COUNT, 7, 'unitCount includes the coach at index 0');
  assert.deepEqual(VARIANT_LIMITS, {rows: 3, cols: 3, maxPitch: 81, maxPlay: 21, unitCount: 7});
  assert.deepEqual(unitAt(variant, 5), {key: 'right', label: 'Right field', short: 'RF', audio: false, display: true, controls: false, pitches: false});
  assert.deepEqual(unitAt(variant, 6), {key: 'bench', label: 'Bench', short: 'BN', audio: true, display: true, controls: false, pitches: true});
  assert.equal(unitIndexOf(catalog, 'bench'), -1, 'the committed catalog does not know the custom key');
});

test('variant catalog pitchCode and describe keep resolving pitch calls', () => {
  assert.equal(pitchCode(1, 1, 1, variant.rows.length, variant.cols.length), 1);
  assert.equal(pitchCode(9, 3, 3, variant.rows.length, variant.cols.length), 81);
  assert.equal(pitchCode(10, 1, 1, variant.rows.length, variant.cols.length), 82, 'the formula ignores the roster count');
  assert.equal(describe(variant, 1, 1), 'Four-Seam Fastball \u00b7 High Inside');
  assert.equal(describe(variant, 1, 41), 'Sinker \u00b7 Middle Center');
  assert.equal(describe(variant, 1, 81), 'Splitter \u00b7 Low Outside');
  for (let code = 1; code <= VARIANT_LIMITS.maxPitch; code++) {
    assert.equal(describe(variant, 1, code), describe(catalog, 1, code), `pitch ${code} does not depend on the roster`);
  }
  for (const play of variant.plays) assert.equal(describe(variant, 2, play.key), play.label);
});

test('variant limits accept a state sized to six enrolled units plus the coach', () => {
  assert.equal(variant.units.length, 6, 'six enrolled field units');
  assert.equal(VARIANT_LIMITS.unitCount, 7, 'plus unit 0, the coach');
  assert.equal(validState(variantState(), VARIANT_LIMITS), true);
  for (let role = 1; role < VARIANT_UNIT_COUNT; role++) {
    assert.equal(validState(variantState({role}), VARIANT_LIMITS), true, `role ${role} is an enrolled unit index`);
  }
  assert.equal(validState(variantState({role: VARIANT_UNIT_COUNT}), VARIANT_LIMITS), false, 'role 7 is past the roster');
  assert.equal(validResult(resultFixture(), VARIANT_LIMITS), true);
});

test('variant limits reject links and delivery arrays that do not match the unit count', () => {
  assert.equal(validState(variantState({links: [1, 0, 1, 1, 0, 1]}), VARIANT_LIMITS), false, 'six links leave out the last unit');
  assert.equal(validState(variantState({links: [1, 0, 1, 1, 0, 1, 0, 0]}), VARIANT_LIMITS), false, 'eight links overshoot the roster');
  assert.equal(validState(variantState({links: [1, 0, 1, 1, 1]}), VARIANT_LIMITS), false, 'the committed five-index links do not fit the variant');
  assert.equal(validState(variantState({delivery: [0, 2, 2, 0, 0, 0]}), VARIANT_LIMITS), false, 'six outcomes leave out the last unit');
  assert.equal(validState(variantState({delivery: [0, 2, 2, 0, 0, 0, 0, 0]}), VARIANT_LIMITS), false, 'eight outcomes overshoot the roster');
  assert.equal(validState(variantState({records: [
    {category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0, 0]},
    {category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0, 0, 0]},
  ]}), VARIANT_LIMITS), false, 'record outcomes follow the unit count');
  assert.equal(validState(variantState(), LIMITS), false, 'the committed five-index limits reject the variant state');
  assert.equal(validState(variantState(), {rows: 3, cols: 3, maxPitch: 81, maxPlay: 21, unitCount: 6}), false, 'six total indices cannot carry the coach plus six units');
});

test('variant unitAt and unitIndexOf handle the custom bench key', () => {
  assert.equal(unitIndexOf(variant, 'right'), 5);
  assert.equal(unitIndexOf(variant, 'bench'), 6);
  assert.equal(unitIndexOf(variant, 'coach'), -1);
  assert.equal(unitIndexOf(variant, 'none'), -1);
  assert.equal(unitAt(variant, unitIndexOf(variant, 'bench')), variant.units[5]);
  assert.equal(unitAt(variant, 0), coachUnit);
  assert.equal(unitAt(variant, 5), variant.units[4]);
  assert.equal(unitAt(variant, 6), variant.units[5]);
  assert.equal(unitAt(variant, 7), null);
  assert.equal(unitAt(catalog, 6), null);
});

test('variant play audiences route to right and bench in unit order', () => {
  assert.ok(variant.plays.every(play => play.audience.length > 0), 'every play keeps a nonempty audience');
  for (const play of variant.plays) {
    assert.deepEqual(play.audience, variantKeys.filter(key => play.audience.includes(key)), `play ${play.key} audience order`);
  }
  assert.deepEqual(variant.plays[0].audience, ['pitcher', 'catcher', 'shortstop', 'bench'], 'PICKOFF adds the explicitly targeted bench');
  assert.deepEqual(variant.plays.find(play => play.key === 18).audience, ['center', 'right'], 'SEE DOWN resolves the outfield group');
  assert.deepEqual(variant.plays.find(play => play.key === 13).audience, ['pitcher', 'catcher', 'shortstop', 'center', 'right'], 'the all group is the standard keys, not custom keys');
  assert.ok(variant.plays.some(play => play.audience.includes('right')), 'at least one play routes to right');
  assert.ok(variant.plays.some(play => play.audience.includes('bench')), 'at least one play routes to bench');
});

test('variant audience labels join in unit order through the desk helpers', () => {
  // gui/app.js has no exported audience-label helper; it joins unitAt labels
  // inline. Mirror that expression at the data level.
  const audienceLabels = play => play.audience
    .map(key => unitAt(variant, unitIndexOf(variant, key)).label)
    .join(' + ');
  assert.equal(audienceLabels(variant.plays[0]), 'Pitcher + Catcher + Shortstop + Bench');
  assert.equal(audienceLabels(variant.plays.find(play => play.key === 18)), 'Center field + Right field');
  assert.equal(audienceLabels(variant.plays.find(play => play.key === 13)), 'Pitcher + Catcher + Shortstop + Center field + Right field');
});

test('variant custom unit capabilities and short labels render through the desk helpers', () => {
  assert.deepEqual(variant.units.map(unit => unit.short), ['P', 'C', 'SS', 'CF', 'RF', 'BN']);
  assert.deepEqual(variant.units.map(unit => unit.label), ['Pitcher', 'Catcher', 'Shortstop', 'Center field', 'Right field', 'Bench']);
  const bench = unitAt(variant, unitIndexOf(variant, 'bench'));
  assert.equal(bench.short, 'BN');
  assert.ok(bench.short.length <= 4, 'the custom short label fits the catcher menu limit');
  // gui/app.js renders capabilities from the unit flags with this expression.
  const capabilities = unit => [unit.audio ? 'Audio' : '', unit.controls ? 'Controls' : '', unit.pitches ? 'Pitches' : ''].filter(Boolean).join(' \u00b7 ');
  assert.equal(capabilities(bench), 'Audio \u00b7 Pitches');
  const right = unitAt(variant, unitIndexOf(variant, 'right'));
  assert.equal(capabilities(right), '', 'a display-only unit adds no capability line');
  const pitchIndices = variant.units.map((unit, index) => unit.pitches ? index + 1 : 0).filter(Boolean);
  assert.deepEqual(pitchIndices, [1, 2, 6]);
  assert.equal(pitchIndices.map(index => unitAt(variant, index).label).join(' + '), 'Pitcher + Catcher + Bench');
  const audioIndices = variant.units.map((unit, index) => unit.audio ? index + 1 : 0).filter(Boolean);
  assert.deepEqual(audioIndices, [1, 6], 'the custom bench unit is the added audio receiver');
});

test('decodePitch inverts pitchCode across configured grids', () => {
  for (let code = 1; code <= MAX_PITCH; code++) {
    const decoded = decodePitch(code, ROWS, COLS);
    assert.deepEqual(decoded, {
      type: Math.floor((code - 1) / (ROWS * COLS)) + 1,
      row: Math.floor(((code - 1) % (ROWS * COLS)) / COLS) + 1,
      col: (code - 1) % COLS + 1,
    }, `code ${code}`);
    assert.equal(pitchCode(decoded.type, decoded.row, decoded.col, ROWS, COLS), code);
  }
  assert.deepEqual(decodePitch(1, 3, 3), {type: 1, row: 1, col: 1});
  assert.deepEqual(decodePitch(81, 3, 3), {type: 9, row: 3, col: 3});
  assert.deepEqual(decodePitch(32, 4, 5), {type: 2, row: 3, col: 2});
  assert.deepEqual(decodePitch(20, 4, 5), {type: 1, row: 4, col: 5});
  assert.deepEqual(decodePitch(9, 2, 2), {type: 3, row: 1, col: 1});
});

test('decodePitch returns null outside the valid range', () => {
  const cases = [
    [0, 3, 3], [-1, 3, 3], [1.5, 3, 3], ['1', 3, 3], [NaN, 3, 3], [Infinity, 3, 3], [undefined, 3, 3], [null, 3, 3],
    [1, 0, 3], [1, 3, 0], [1, -1, 3], [1, 3, -1], [1, 1.5, 3], [1, 3, 1.5], [1, '3', 3], [1, 3, '3'], [1, null, 3],
  ];
  for (const bad of cases) assert.equal(decodePitch(...bad), null, JSON.stringify(bad));
  assert.equal(decodePitch(), null);
  assert.equal(decodePitch(1), null);
  assert.equal(decodePitch(1, 3), null);
});

test('keyAction maps digits to types on the pitch tab and plays on the play tab', () => {
  const arity = {rows: 3, cols: 3, pitchTypes: 9, maxPlay: 21};
  for (let value = 1; value <= 9; value++) {
    assert.deepEqual(keyAction(String(value), 1, arity), {kind: 'type', value});
    assert.deepEqual(keyAction(String(value), 2, arity), {kind: 'play', value});
  }
  assert.equal(keyAction('0', 1, arity), null);
  assert.equal(keyAction('0', 2, arity), null);
  assert.equal(keyAction('10', 1, arity), null);
  assert.equal(keyAction('10', 2, arity), null);
  assert.deepEqual(keyAction('4', 1, {rows: 3, cols: 3, pitchTypes: 4, maxPlay: 21}), {kind: 'type', value: 4});
  assert.equal(keyAction('5', 1, {rows: 3, cols: 3, pitchTypes: 4, maxPlay: 21}), null, 'past the pitch count');
  assert.deepEqual(keyAction('9', 2, {rows: 3, cols: 3, pitchTypes: 9, maxPlay: 9}), {kind: 'play', value: 9});
  assert.equal(keyAction('9', 2, {rows: 3, cols: 3, pitchTypes: 9, maxPlay: 8}), null, 'past the play count');
  assert.equal(keyAction('1', 0, arity), null, 'no category');
  assert.equal(keyAction('1', 3, arity), null, 'unknown category');
});

test('keyAction maps the 3x3 zone letters in visual order and case-insensitively', () => {
  const arity = {rows: 3, cols: 3, pitchTypes: 9, maxPlay: 21};
  const zones = {q: [1, 1], w: [1, 2], e: [1, 3], a: [2, 1], s: [2, 2], d: [2, 3], z: [3, 1], x: [3, 2], c: [3, 3]};
  for (const [key, [row, col]] of Object.entries(zones)) {
    assert.deepEqual(keyAction(key, 1, arity), {kind: 'zone', row, col});
    assert.deepEqual(keyAction(key.toUpperCase(), 1, arity), {kind: 'zone', row, col});
    assert.equal(keyAction(key, 2, arity), null, `${key} is pitch tab only`);
  }
});

test('keyAction drops zone letters the current catalog does not have', () => {
  const twoByTwo = {rows: 2, cols: 2, pitchTypes: 9, maxPlay: 21};
  assert.deepEqual(keyAction('q', 1, twoByTwo), {kind: 'zone', row: 1, col: 1});
  assert.deepEqual(keyAction('w', 1, twoByTwo), {kind: 'zone', row: 1, col: 2});
  assert.deepEqual(keyAction('a', 1, twoByTwo), {kind: 'zone', row: 2, col: 1});
  assert.deepEqual(keyAction('s', 1, twoByTwo), {kind: 'zone', row: 2, col: 2});
  for (const key of ['e', 'd', 'z', 'x', 'c']) assert.equal(keyAction(key, 1, twoByTwo), null, `${key} needs a third row or column`);
  const oneByOne = {rows: 1, cols: 1, pitchTypes: 9, maxPlay: 21};
  assert.deepEqual(keyAction('q', 1, oneByOne), {kind: 'zone', row: 1, col: 1});
  for (const key of ['w', 'a']) assert.equal(keyAction(key, 1, oneByOne), null);
  const wide = {rows: 4, cols: 5, pitchTypes: 9, maxPlay: 21};
  assert.deepEqual(keyAction('z', 1, wide), {kind: 'zone', row: 3, col: 1});
  assert.deepEqual(keyAction('c', 1, wide), {kind: 'zone', row: 3, col: 3});
  assert.equal(keyAction('q', 1, {rows: 0, cols: 0, pitchTypes: 9, maxPlay: 21}), null, 'no zone without a grid');
});

test('keyAction handles Enter, Escape, and resend and ignores everything else', () => {
  const arity = {rows: 3, cols: 3, pitchTypes: 9, maxPlay: 21};
  for (const category of [0, 1, 2]) {
    assert.deepEqual(keyAction('Enter', category, arity), {kind: 'send'});
    assert.deepEqual(keyAction('Escape', category, arity), {kind: 'clear'});
    assert.deepEqual(keyAction('r', category, arity), {kind: 'resend'});
    assert.deepEqual(keyAction('R', category, arity), {kind: 'resend'});
  }
  for (const key of ['k', 'm', ' ', '', 'Shift', 'Tab', 'F1', 'ArrowUp', '#', 'enter', 'Enter ']) {
    assert.equal(keyAction(key, 1, arity), null, JSON.stringify(key));
  }
  assert.equal(keyAction(undefined, 1, arity), null);
  assert.equal(keyAction(null, 1, arity), null);
  assert.equal(keyAction(1, 1, arity), null);
  assert.equal(keyAction({key: 'q'}, 1, arity), null);
  assert.deepEqual(keyAction('Enter'), {kind: 'send'});
  assert.equal(keyAction('1', 1), null, 'no pitch count means no digit action');
  assert.equal(keyAction('q', 1), null, 'no grid means no zone action');
});

test('formatClock renders local wall time as HH:MM:SS', () => {
  assert.equal(formatClock(new Date(2026, 0, 2, 3, 4, 5).getTime()), '03:04:05');
  assert.equal(formatClock(new Date(2026, 0, 2, 23, 59, 7).getTime()), '23:59:07');
  assert.equal(formatClock(new Date(2026, 0, 2, 0, 0, 0).getTime()), '00:00:00');
  assert.equal(formatClock(new Date(2026, 0, 2, 12, 30, 40).getTime()), '12:30:40');
  assert.equal(formatClock(NaN), '');
  assert.equal(formatClock('later'), '');
});

test('formatLatency uses milliseconds under a second and one decimal second above', () => {
  assert.equal(formatLatency(0), '0 ms');
  assert.equal(formatLatency(240), '240 ms');
  assert.equal(formatLatency(999), '999 ms');
  assert.equal(formatLatency(240.4), '240 ms');
  assert.equal(formatLatency(240.6), '241 ms');
  assert.equal(formatLatency(1000), '1.0 s');
  assert.equal(formatLatency(1200), '1.2 s');
  assert.equal(formatLatency(1250), '1.3 s');
  assert.equal(formatLatency(12345), '12.3 s');
  assert.equal(formatLatency(NaN), '');
  assert.equal(formatLatency('slow'), '');
});
