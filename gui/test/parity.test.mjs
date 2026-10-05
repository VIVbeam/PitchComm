// Cross-parity between the firmware call table and the GUI vocabulary.
// If the two dictionaries drift, one of these tests must fail.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../..', import.meta.url));
const header = readFileSync(path.join(root, 'firmware', 'include', 'pc', 'catalog.h'), 'utf8');
const catalog = JSON.parse(readFileSync(path.join(root, 'gui', 'catalog.json'), 'utf8'));

function parseCallEntries(source) {
  const pattern = /\{\s*Category::(Pitch|Play)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*\{([^}]*)\}\s*\}/g;
  const entries = [];
  for (const match of source.matchAll(pattern)) {
    entries.push({
      category: match[1],
      code: Number(match[2]),
      audience: Number(match[3]),
      label: match[4],
      shortstop: match[5],
      centerfield: match[6],
      audio: [...match[7].matchAll(/"([^"]*)"/g)].map(item => item[1]),
    });
  }
  return entries;
}

function constant(name, source = header) {
  const match = source.match(new RegExp(`constexpr\\s+unsigned\\s+${name}\\s*=\\s*(\\d+)`));
  assert.ok(match, `${name} must be present in catalog.h`);
  return Number(match[1]);
}

function stringTable(name, source = header) {
  const block = source.match(new RegExp(`${name}\\[\\]\\s*=\\s*\\{([\\s\\S]*?)\\};`));
  assert.ok(block, `${name} must be present in catalog.h`);
  return [...block[1].matchAll(/"([^"]*)"/g)].map(match => match[1]);
}

function boolTable(name) {
  const block = header.match(new RegExp(`${name}\\[\\]\\s*=\\s*\\{([\\s\\S]*?)\\};`));
  assert.ok(block, `${name} must be present in catalog.h`);
  return [...block[1].matchAll(/\b(true|false)\b/g)].map(match => match[1] === 'true');
}

function audienceMask(keys) {
  let mask = 0;
  for (const key of keys) {
    const index = catalog.units.findIndex(unit => unit.key === key);
    assert.ok(index >= 0, `${key} is an enrolled unit`);
    mask |= 1 << (index + 1);
  }
  return mask >>> 0;
}

const entries = parseCallEntries(header);
const pitchEntries = entries.filter(entry => entry.category === 'Pitch' && entry.code<=catalog.pitches.length*catalog.rows.length*catalog.cols.length);
const playEntries = entries.filter(entry => entry.category === 'Play');
const rowCount = catalog.rows.length;
const colCount = catalog.cols.length;
const locationCount = catalog.locations.length;
const maxPitch = catalog.pitches.length * rowCount * colCount;
const unitKeys = catalog.units.map(unit => unit.key);
const unitLabels = ['Coach', ...catalog.units.map(unit => unit.label)];
const unitShorts = ['CO', ...catalog.units.map(unit => unit.short)];
const unitAudio = [false, ...catalog.units.map(unit => unit.audio)];
const unitDisplay = [false, ...catalog.units.map(unit => unit.display)];
const unitControls = [false, ...catalog.units.map(unit => unit.controls)];
const unitPitches = [false, ...catalog.units.map(unit => unit.pitches)];
const pitchAudience = audienceMask(catalog.units.filter(unit => unit.pitches).map(unit => unit.key));
const fullAudience = audienceMask(unitKeys);

test('GUI catalog has the schema 3 shape and the pinned dictionary', () => {
  assert.equal(catalog.schema, 3);
  assert.equal(catalog.dictionary, '94b7a24a');
  assert.match(catalog.dictionary, /^[a-f0-9]{8}$/);
  assert.deepEqual(
    [catalog.pitches.length, rowCount, colCount, locationCount, catalog.plays.length],
    [9, 3, 3, 9, 21],
  );
  catalog.pitches.forEach((pitch, index) => assert.equal(pitch.key, index + 1, `pitch key ${index + 1}`));
  catalog.rows.forEach((row, index) => assert.equal(row.key, index + 1, `row key ${index + 1}`));
  catalog.cols.forEach((col, index) => assert.equal(col.key, index + 1, `col key ${index + 1}`));
  catalog.plays.forEach((play, index) => assert.equal(play.key, index + 1, `play key ${index + 1}`));
  catalog.locations.forEach((location, index) => {
    assert.equal(location.row, Math.floor(index / colCount) + 1, `location ${index + 1} row`);
    assert.equal(location.col, (index % colCount) + 1, `location ${index + 1} col`);
  });
  assert.equal(maxPitch, 81);
  assert.deepEqual(unitKeys, ['pitcher', 'catcher', 'shortstop', 'center']);
  for (const play of catalog.plays) {
    assert.ok(play.audience.length > 0, `play ${play.key} targets at least one unit`);
    assert.deepEqual(play.audience, unitKeys.filter(key => play.audience.includes(key)), `play ${play.key} audience order`);
  }
});

test('firmware kDictionary and counts match the GUI vocabulary', () => {
  const match = header.match(/constexpr\s+uint32_t\s+kDictionary\s*=\s*(0x[0-9a-fA-F]+)u?/);
  assert.ok(match, 'kDictionary must be present in catalog.h');
  assert.equal(Number(match[1]) >>> 0, parseInt(catalog.dictionary, 16));
  assert.equal(constant('kPitchCount'), catalog.pitches.length);
  assert.equal(constant('kRows'), rowCount);
  assert.equal(constant('kCols'), colCount);
  assert.equal(constant('kLocationCount'), locationCount);
  assert.equal(constant('kPlayCount'), catalog.plays.length);
  assert.equal(constant('kUnitCount'), catalog.units.length + 1);
});

test('firmware unit tables match the GUI roster in unit index order', () => {
  assert.deepEqual(stringTable('kUnitLabel'), unitLabels);
  assert.deepEqual(stringTable('kUnitShort'), unitShorts);
  assert.deepEqual(boolTable('kUnitAudio'), unitAudio);
  assert.deepEqual(boolTable('kUnitDisplay'), unitDisplay);
  assert.deepEqual(boolTable('kUnitControls'), unitControls);
  assert.deepEqual(boolTable('kUnitPitches'), unitPitches);
  for (const [index, unit] of catalog.units.entries()) {
    const define = header.match(new RegExp(`#define\\s+PC_UNIT_${unit.key}\\s+(\\d+)`));
    assert.ok(define, `PC_UNIT_${unit.key} must be present`);
    assert.equal(Number(define[1]), index + 1, `PC_UNIT_${unit.key} selects unit index ${index + 1}`);
  }
});

test('firmware has 81 pitch entries with codes 1 through 81 that match the GUI grid', () => {
  assert.equal(pitchEntries.length, maxPitch);
  assert.deepEqual(pitchEntries.map(entry => entry.code), Array.from({ length: maxPitch }, (_, index) => index + 1));
  for (const entry of pitchEntries) {
    const type = Math.floor((entry.code - 1) / (rowCount * colCount)) + 1;
    const row = Math.floor(((entry.code - 1) % (rowCount * colCount)) / colCount) + 1;
    const col = (entry.code - 1) % colCount + 1;
    const pitch = catalog.pitches.find(candidate => candidate.key === type);
    const rowItem = catalog.rows.find(candidate => candidate.key === row);
    const colItem = catalog.cols.find(candidate => candidate.key === col);
    assert.ok(pitch && rowItem && colItem, `grid item exists for pitch code ${entry.code}`);
    const expected = `${pitch.label} ${rowItem.label} ${colItem.label}`;
    assert.equal(entry.label, expected, `pitch code ${entry.code} label`);
    assert.equal(entry.shortstop, expected, `pitch code ${entry.code} shortstop label`);
    assert.equal(entry.centerfield, expected, `pitch code ${entry.code} centerfield label`);
    assert.equal(entry.audience, pitchAudience, `pitch code ${entry.code} audience mask`);
    assert.deepEqual(entry.audio, [
      `/audio/p${String(type).padStart(2, '0')}.wav`,
      `/audio/l${(entry.code - 1) % (rowCount * colCount) + 1}.wav`,
      '',
    ], `pitch code ${entry.code} audio`);
  }
});

test('firmware location table follows the GUI rows, cols, and row-major locations', () => {
  const used = pitchEntries.map(entry => entry.audio[1]);
  assert.equal(new Set(used).size, locationCount, 'every location clip is referenced');
  for (const [index, location] of catalog.locations.entries()) {
    const entry = pitchEntries.find(candidate => candidate.code === index + 1);
    assert.ok(entry, `pitch entry ${index + 1} carries location ${index + 1}`);
    assert.equal(entry.audio[1], `/audio/l${index + 1}.wav`, `location ${index + 1} clip`);
    const rowItem = catalog.rows.find(candidate => candidate.key === location.row);
    const colItem = catalog.cols.find(candidate => candidate.key === location.col);
    assert.ok(rowItem && colItem, `location ${index + 1} maps to a row and col`);
    assert.equal(entry.code, (location.row - 1) * colCount + location.col, `location ${index + 1} code`);
    assert.equal(entry.label, `${catalog.pitches[0].label} ${rowItem.label} ${colItem.label}`, `location ${index + 1} label`);
  }
  for (let index = 1; index <= locationCount; index++) {
    assert.equal(used.filter(audio => audio === `/audio/l${index}.wav`).length, catalog.pitches.length, `location ${index} used once per pitch`);
  }
});

test('firmware has 21 play entries with codes 1 through 21 and the resolved audiences', () => {
  assert.equal(playEntries.length, catalog.plays.length);
  assert.deepEqual(playEntries.map(entry => entry.code), Array.from({ length: catalog.plays.length }, (_, index) => index + 1));
  for (const entry of playEntries) {
    const play = catalog.plays.find(candidate => candidate.key === entry.code);
    assert.ok(play, `GUI play ${entry.code} exists`);
    assert.equal(entry.label, play.label, `play code ${entry.code} label`);
    assert.equal(entry.shortstop, play.shortstop, `play code ${entry.code} shortstop`);
    assert.equal(entry.centerfield, play.centerfield, `play code ${entry.code} centerfield`);
    assert.equal(entry.audience, audienceMask(play.audience), `play code ${entry.code} audience mask`);
    const audible = play.audience.some(key => catalog.units.find(unit => unit.key === key).audio);
    assert.deepEqual(entry.audio, [audible ? `/audio/d${String(entry.code).padStart(2, '0')}.wav` : '', '', ''], `play code ${entry.code} audio`);
  }
  assert.equal(playEntries[20].code, 21, 'play 21 is present');
  assert.deepEqual(catalog.plays[20].audience, ['pitcher', 'catcher']);
  assert.ok(playEntries.some(entry => entry.audience !== fullAudience), 'a play with a reduced audience is present');
});

test('firmware short label tables match the GUI short labels', () => {
  assert.deepEqual(stringTable('kPitchShort'), catalog.pitches.map(pitch => pitch.short));
  assert.deepEqual(stringTable('kRowShort'), catalog.rows.map(row => row.short));
  assert.deepEqual(stringTable('kColShort'), catalog.cols.map(col => col.short));
  assert.deepEqual(stringTable('kUnitShort'), unitShorts);
});

test('negative drift checks fail when a label, unit, audience, or the dictionary changes', () => {
  const driftedLabel = header.replace('"FOUR-SEAM HIGH INSIDE"', '"FOUR-SEAM HIGH MIDDLE"');
  assert.notEqual(driftedLabel, header, 'the header text actually changed');
  assert.notEqual(parseCallEntries(driftedLabel)[0].label, pitchEntries[0].label, 'a changed label no longer matches');
  const driftedUnit = header.replace('"Center field",', '"Centre field",');
  assert.notEqual(driftedUnit, header, 'the unit label actually changed');
  assert.notDeepEqual(stringTable('kUnitLabel', driftedUnit), unitLabels, 'a changed unit label no longer matches');
  const driftedShort = header.replace('"CO",', '"Coach",');
  assert.notEqual(driftedShort, header, 'the unit short actually changed');
  assert.notDeepEqual(stringTable('kUnitShort', driftedShort), unitShorts, 'a changed unit short no longer matches');
  const driftedAudience = header.replace('{Category::Play, 21, 6,', '{Category::Play, 21, 4,');
  assert.notEqual(driftedAudience, header, 'the play audience actually changed');
  const driftedPlay = parseCallEntries(driftedAudience).find(entry => entry.category === 'Play' && entry.code === 21);
  assert.notEqual(driftedPlay.audience, audienceMask(catalog.plays[20].audience), 'a changed audience no longer matches');
  const dictionary = Number(header.match(/constexpr\s+uint32_t\s+kDictionary\s*=\s*(0x[0-9a-fA-F]+)u?/)[1]) >>> 0;
  assert.equal(dictionary, parseInt(catalog.dictionary, 16), 'the firmware dictionary matches the pinned vocabulary');
  assert.notEqual(dictionary, parseInt('00000000', 16), 'a changed dictionary no longer matches');
});
