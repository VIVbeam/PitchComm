// Conformance checks for the shared fixtures in dev/protocol/.
// The command grammar mirrors the count-aware firmware/include/pc/controls.h
// parseUsbCall and parseGuiClient. The frame checks mirror gui/core.js
// validState and validResult.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { command, describe, pitchCode, validState, validResult } from '../core.js';
import {
  COUNTS,
  FIXED_SESSION,
  buildGuiCommandsText,
  buildStateFramesText,
  commandRecords,
  pitchSamples,
  resultSamples,
  stateSamples,
} from './generate_fixtures.mjs';

const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const fixtureDir = path.join(repoRoot, 'dev', 'protocol');
const catalog = JSON.parse(readFileSync(path.join(repoRoot, 'gui', 'catalog.json'), 'utf8'));
const LIMITS = {rows: COUNTS.rows, cols: COUNTS.cols, maxPitch: COUNTS.maxPitch, maxPlay: COUNTS.maxPlay, unitCount: COUNTS.unitCount};

const DECIMAL = /^\d+$/;
const HEX8 = /^[0-9a-fA-F]{8}$/;
const HEX16 = /^[0-9a-fA-F]{16}$/;

function readFixture(name) {
  return readFileSync(path.join(fixtureDir, name), 'utf8').replace(/\r\n/g, '\n');
}

function stripNewline(line) {
  return line.endsWith('\n') ? line.slice(0, -1) : line;
}

// Mirrors controls.h parseHex: exactly `digits` hex digits, then the cursor must be at the token end.
function hexValue(token, digits) {
  if (token.length !== digits || !/^[0-9a-fA-F]+$/.test(token)) return null;
  return BigInt('0x' + token);
}

// Mirrors controls.h number(): digits only, no sign, no overflow past UINT32_MAX.
function decimalUint32(token) {
  if (!DECIMAL.test(token)) return null;
  const value = Number(token);
  return Number.isSafeInteger(value) && value <= 0xffffffff ? value : null;
}

// Mirrors controls.h parseGuiClient.
function parseGuiLine(line) {
  const match = /^gui ([0-9a-fA-F]{8})$/.exec(line);
  if (!match) return null;
  const client = Number.parseInt(match[1], 16);
  return client === 0 ? null : { kind: 'gui', client };
}

// Mirrors controls.h parseUsbCall, including single spaces and end-of-line.
// Pitch codes and play codes use the counts from the loaded catalog.
function parseCallLine(line) {
  const tokens = line.split(' ');
  if (tokens[0] !== 'call' || tokens.some(token => token === '')) return null;
  if (tokens.length !== 10 && tokens.length !== 8) return null;
  const clientHex = tokens[1];
  if (!HEX8.test(clientHex) || /^0{8}$/.test(clientHex)) return null;
  const client = Number.parseInt(clientHex, 16);
  const id = decimalUint32(tokens[2]);
  if (id === null || id === 0) return null;
  const boot = hexValue(tokens[tokens.length - 3], 16);
  const dictionary = hexValue(tokens[tokens.length - 2], 8);
  const deadline = decimalUint32(tokens[tokens.length - 1]);
  if (boot === null || boot === 0n || dictionary === null || deadline === null) return null;
  if (tokens[3] === 't') {
    if(tokens.length!==8)return null;
    const type=decimalUint32(tokens[4]);
    if(type===null || type<1 || type>catalog.pitches.length)return null;
    return {kind:'call',client,id,category:1,type,code:catalog.pitchFlow.typeBase+type,boot,dictionary,deadline};
  }
  if (tokens[3] === 'p' || tokens[3] === 'l') {
    if (tokens.length !== 10) return null;
    const type = decimalUint32(tokens[4]);
    const row = decimalUint32(tokens[5]);
    const col = decimalUint32(tokens[6]);
    if (type === null || row === null || col === null) return null;
    const code = pitchCode(type, row, col, COUNTS.rows, COUNTS.cols);
    if (!code || type>catalog.pitches.length) return null;
    const transmitted=tokens[3]==='l'?catalog.pitchFlow.placementBase+code:code;
    return { kind: 'call', client, id, category: 1, type, row, col, code:transmitted, boot, dictionary, deadline };
  }
  if (tokens[3] === 'd') {
    if (tokens.length !== 8) return null;
    const play = decimalUint32(tokens[4]);
    if (play === null || play < 1 || play > COUNTS.maxPlay) return null;
    return { kind: 'call', client, id, category: 2, type: play, code: play, boot, dictionary, deadline };
  }
  return null;
}

function fixtureFrames() {
  return readFixture('state_frames.txt')
    .split('\n')
    .filter(line => line !== '' && !line.startsWith('#'))
    .map(line => {
      assert.ok(line.startsWith('@PC '), `frame marker present: ${line}`);
      return JSON.parse(line.slice(4));
    });
}

test('gui_commands.txt matches the generated fixture text', () => {
  assert.equal(readFixture('gui_commands.txt'), buildGuiCommandsText());
});

test('state_frames.txt matches the generated fixture text', () => {
  assert.equal(readFixture('state_frames.txt'), buildStateFramesText());
});

test('every command line satisfies the firmware token grammar', () => {
  const records = commandRecords();
  const handshake = records.filter(record => record.kind === 'gui');
  assert.equal(handshake.length, 1);
  const gui = parseGuiLine(stripNewline(handshake[0].line));
  assert.ok(gui, 'gui handshake parses');
  assert.equal(gui.client, Number.parseInt(FIXED_SESSION.client, 16));

  const calls = records.filter(record => record.kind !== 'gui');
  assert.equal(calls.length, 13+catalog.pitches.length*2);
  for (const record of calls) {
    const line = stripNewline(record.line);
    const parsed = parseCallLine(line);
    assert.ok(parsed, `firmware grammar accepts: ${line}`);
    assert.equal(parsed.client, Number.parseInt(FIXED_SESSION.client, 16));
    assert.equal(parsed.id, record.id);
    assert.equal(parsed.boot, BigInt('0x' + FIXED_SESSION.boot));
    assert.equal(parsed.dictionary, BigInt('0x' + FIXED_SESSION.dictionary));
    assert.equal(parsed.deadline, (record.clock + 1500) >>> 0);
    if (record.kind === 'play') {
      assert.equal(parsed.category, 2);
      assert.equal(parsed.code, record.play);
    } else if(record.kind==='type') {
      assert.equal(parsed.category,1);
      assert.equal(parsed.code,catalog.pitchFlow.typeBase+record.type);
    } else {
      assert.equal(parsed.category, 1);
      assert.equal(parsed.code,(record.kind==='placement'?catalog.pitchFlow.placementBase:0)+pitchCode(record.type, record.row, record.col, COUNTS.rows, COUNTS.cols));
    }
    const tokens = line.split(' ');
    assert.match(tokens[1], /^[0-9a-f]{8}$/, 'client is lowercase hex');
    assert.equal(tokens[2], String(parsed.id), 'id is canonical decimal');
    assert.match(tokens[tokens.length - 3], /^[0-9a-f]{16}$/, 'boot is lowercase hex');
    assert.match(tokens[tokens.length - 2], /^[0-9a-f]{8}$/, 'dictionary is lowercase hex');
    assert.equal(tokens[tokens.length - 1], String(parsed.deadline), 'deadline is canonical decimal');
  }
});

test('command fixtures cover all pitch types, plays 1 and 21, handshake, and deadline wrap', () => {
  const records = commandRecords();
  const calls = records.filter(record => record.kind !== 'gui').map(record => parseCallLine(stripNewline(record.line)));
  const pitchTypes = [...new Set(calls.filter(call => call.category === 1).map(call => call.type))].sort((a, b) => a - b);
  assert.deepEqual(pitchTypes, catalog.pitches.map(pitch => pitch.key));
  const plays = [...new Set(calls.filter(call => call.category === 2).map(call => call.code))].sort((a, b) => a - b);
  assert.deepEqual(plays, [1, COUNTS.maxPlay]);
  assert.ok(COUNTS.maxPlay > 9, 'the fixture includes a play beyond the old nine-play ceiling');
  assert.equal(records.filter(record => record.kind === 'gui').length, 1);
  const wrap = records.filter(record => record.kind === 'pitch-wrap');
  assert.deepEqual(wrap.map(record => record.clock), [0xfffffa24, 0xffffffff]);
  assert.deepEqual(wrap.map(record => parseCallLine(stripNewline(record.line)).deadline), [0, 1499]);
});

test('the command mirror rejects the first play above the catalog count', () => {
  const line = `call ${FIXED_SESSION.client} 99 d ${COUNTS.maxPlay + 1} ${FIXED_SESSION.boot} ${FIXED_SESSION.dictionary} 5596`;
  assert.equal(parseCallLine(line), null);
});

test('every state frame passes validState with codes inside the catalog ranges', () => {
  const frames = fixtureFrames();
  const states = frames.filter(frame => frame.type === 'state');
  assert.equal(states.length, stateSamples().length);
  for (const state of states) {
    assert.equal(validState(state, LIMITS), true, `validState rejects ${JSON.stringify(state)}`);
    if (state.seq === 0) {
      assert.equal(state.code, 0);
    } else if (state.category === 1) {
      assert.ok(state.code >= 1 && state.code <= LIMITS.maxPitch, `pitch code ${state.code}`);
    } else {
      assert.equal(state.category, 2);
      assert.ok(state.code >= 1 && state.code <= LIMITS.maxPlay, `play code ${state.code}`);
    }
    state.records.forEach((record, index) => {
      if (record.seq === 0) {
        assert.equal(record.code, 0);
      } else if (index === 0) {
        assert.ok(record.code >= 1 && record.code <= LIMITS.maxPitch, `record pitch code ${record.code}`);
      } else {
        assert.ok(record.code >= 1 && record.code <= LIMITS.maxPlay, `record play code ${record.code}`);
      }
    });
  }
  assert.ok(states.some(state => state.category === 1 && state.code > 9), 'a pitch code above 9 is present');
  assert.ok(states.some(state => state.category === 2 && state.code > 9), 'a play code above 9 is present');
  const deliveryValues = new Set(states.flatMap(state => [
    ...state.delivery,
    ...state.records.flatMap(record => record.delivery),
  ]));
  assert.deepEqual([...deliveryValues].sort((a, b) => a - b), [0, 1, 2, 3, 4]);
});

test('state frames carry one entry per unit with the coach index always zero', () => {
  const states = fixtureFrames().filter(frame => frame.type === 'state');
  for (const state of states) {
    assert.ok(state.role < COUNTS.unitCount, `role ${state.role} is below kUnitCount`);
    assert.equal(state.links.length, COUNTS.unitCount, 'links length');
    assert.equal(state.delivery.length, COUNTS.unitCount, 'delivery length');
    assert.equal(state.delivery[0], 0, 'coach delivery');
    for (const record of state.records) {
      assert.equal(record.delivery.length, COUNTS.unitCount, 'record delivery length');
      assert.equal(record.delivery[0], 0, 'record coach delivery');
    }
  }
  assert.equal(COUNTS.unitCount, catalog.units.length + 1);
  assert.ok(states.some(state => state.role > 0), 'a non-coach role frame is present');
});

test('every result frame passes validResult and covers all result values', () => {
  const frames = fixtureFrames();
  const results = frames.filter(frame => frame.type === 'result');
  assert.equal(results.length, resultSamples().length);
  for (const result of results) {
    assert.equal(validResult(result, LIMITS), true, `validResult rejects ${JSON.stringify(result)}`);
    if (result.result === 0) {
      assert.ok(result.seq > 0);
    } else {
      assert.equal(result.seq, 0);
    }
  }
  const values = [...new Set(results.map(result => result.result))].sort((a, b) => a - b);
  assert.deepEqual(values, [0, 1, 2, 3, 4, 5]);
});

test('pitch command output matches pitchCode and the describe round trip', () => {
  const pitchRecords = commandRecords().filter(record => record.kind === 'pitch');
  assert.equal(pitchRecords.length, pitchSamples().length);
  const codes = [];
  for (const record of pitchRecords) {
    const line = record.line;
    assert.equal(line, command(record.id, 1, record.type, record.row, record.col, {
      ...FIXED_SESSION,
      clock: record.clock,
    }, COUNTS), 'command() regenerates the fixture line');
    const parsed = parseCallLine(stripNewline(line));
    assert.ok(parsed);
    assert.equal(parsed.code, pitchCode(record.type, record.row, record.col, COUNTS.rows, COUNTS.cols));
    codes.push(parsed.code);
    const type = Math.floor((parsed.code - 1) / (COUNTS.rows * COUNTS.cols)) + 1;
    const row = Math.floor(((parsed.code - 1) % (COUNTS.rows * COUNTS.cols)) / COUNTS.cols) + 1;
    const col = (parsed.code - 1) % COUNTS.cols + 1;
    assert.deepEqual({ type, row, col }, { type: record.type, row: record.row, col: record.col });
    const pitch = catalog.pitches.find(candidate => candidate.key === type);
    const location = catalog.locations[(row - 1) * COUNTS.cols + (col - 1)];
    assert.equal(describe(catalog, 1, parsed.code), `${pitch.speech} \u00b7 ${location.speech}`);
  }
  assert.equal(new Set(codes).size, catalog.pitches.length);
  assert.ok(codes.every(code => code >= 1 && code <= COUNTS.maxPitch));
});

test('play command output covers the high play and regenerates from command()', () => {
  const playRecords = commandRecords().filter(record => record.kind === 'play');
  assert.deepEqual(playRecords.map(record => record.play), [1, COUNTS.maxPlay]);
  for (const record of playRecords) {
    assert.equal(record.line, command(record.id, 2, record.play, 0, 0, {
      ...FIXED_SESSION,
      clock: record.clock,
    }, COUNTS), 'command() regenerates the fixture line');
    const parsed = parseCallLine(stripNewline(record.line));
    assert.ok(parsed);
    assert.equal(parsed.category, 2);
    assert.equal(parsed.code, record.play);
    assert.equal(describe(catalog, 2, parsed.code), catalog.plays.find(play => play.key === record.play).label);
  }
});
