import test from 'node:test';
import assert from 'node:assert/strict';
import { SessionReport } from '../report.js';

const DICTIONARY = '299314f6';

function fakeClocks() {
  let wall = 0;
  let mono = 0;
  return {
    wallNow: () => `wall-${++wall}`,
    monoNow: () => (mono += 250),
  };
}

function stateFixture(clock = 1000, overrides = {}) {
  return {
    type: 'state', v: 4, client: 'a1b2c3d4', clock, role: 0, dictionary: DICTIONARY,
    boot: '0011223344556677', configured: 1, radio: 1, busy: 0,
    seq: 5, category: 1, code: 41,
    links: [1, 0, 1, 1, 1], delivery: [0, 2, 2, 0, 0],
    records: [
      { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
      { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
    ],
    ...overrides,
  };
}

test('SessionReport validates the dictionary and limit', () => {
  assert.throws(() => new SessionReport('ABCDEF12'), /Invalid report settings/);
  assert.throws(() => new SessionReport('1234567'), /Invalid report settings/);
  assert.throws(() => new SessionReport(0x12345678), /Invalid report settings/);
  assert.throws(() => new SessionReport(undefined), /Invalid report settings/);
  assert.throws(() => new SessionReport(DICTIONARY, { limit: 0 }), /Invalid report settings/);
  assert.throws(() => new SessionReport(DICTIONARY, { limit: -3 }), /Invalid report settings/);
  assert.throws(() => new SessionReport(DICTIONARY, { limit: 2.5 }), /Invalid report settings/);
  assert.throws(() => new SessionReport(DICTIONARY, { limit: '100' }), /Invalid report settings/);
  assert.doesNotThrow(() => new SessionReport(DICTIONARY, { limit: 1 }));
});

test('SessionReport records start times and starts with empty accounting', () => {
  const { wallNow, monoNow } = fakeClocks();
  const report = new SessionReport(DICTIONARY, { limit: 10, wallNow, monoNow });
  assert.equal(report.startedAt, 'wall-1');
  assert.equal(report.events.length, 0);
  assert.equal(report.total, 0);
  assert.equal(report.dropped, 0);
  const snapshot = report.snapshot();
  assert.equal(snapshot.startedAt, 'wall-1');
  assert.equal(snapshot.exportedAt, 'wall-2');
  assert.equal(snapshot.totalEvents, 0);
  assert.equal(snapshot.omittedEvents, 0);
  assert.deepEqual(snapshot.events, []);
});

test('add stamps index, wall time, elapsed milliseconds, and kind', () => {
  const { wallNow, monoNow } = fakeClocks();
  const report = new SessionReport(DICTIONARY, { limit: 10, wallNow, monoNow });
  report.add('page_started');
  report.add('notice', { message: 'hello', error: false });
  assert.deepEqual(report.events[0], { index: 1, at: 'wall-2', elapsedMs: 250, kind: 'page_started', details: {} });
  assert.deepEqual(report.events[1], {
    index: 2, at: 'wall-3', elapsedMs: 500, kind: 'notice', details: { message: 'hello', error: false },
  });
});

test('add stores a deep copy of details', () => {
  const report = new SessionReport(DICTIONARY, { limit: 10, wallNow: () => 'w', monoNow: () => 0 });
  const details = { nested: { value: 1 }, list: [1, 2] };
  report.add('x', details);
  details.nested.value = 99;
  details.list.push(3);
  assert.deepEqual(report.events[0].details, { nested: { value: 1 }, list: [1, 2] });
});

test('add drops the oldest events past the limit and keeps counting totals', () => {
  const report = new SessionReport(DICTIONARY, { limit: 2, wallNow: () => 'w', monoNow: () => 0 });
  report.add('a');
  report.add('b');
  report.add('c');
  report.add('d');
  assert.equal(report.total, 4);
  assert.equal(report.dropped, 2);
  assert.deepEqual(report.events.map(e => e.index), [3, 4]);
  assert.deepEqual(report.events.map(e => e.kind), ['c', 'd']);
  const snapshot = report.snapshot();
  assert.equal(snapshot.totalEvents, 4);
  assert.equal(snapshot.omittedEvents, 2);
  assert.equal(snapshot.events.length, 2);
});

test('snapshot deep-copies events so callers cannot reach into the report', () => {
  const report = new SessionReport(DICTIONARY, { limit: 10, wallNow: () => 'w', monoNow: () => 0 });
  report.add('x', { payload: { n: 1 } });
  const first = report.snapshot();
  first.events[0].details.payload.n = 99;
  const second = report.snapshot();
  assert.equal(second.events[0].details.payload.n, 1);
  assert.notEqual(second.events[0], first.events[0]);
});

test('snapshot exposes the expected schema', () => {
  const report = new SessionReport(DICTIONARY, {
    limit: 10,
    wallNow: () => '2026-01-02T03:04:05.000Z',
    monoNow: () => 0,
  });
  report.add('page_started');
  const snapshot = report.snapshot();
  assert.deepEqual(Object.keys(snapshot).sort(), [
    'dictionary', 'events', 'evidence', 'exportedAt', 'omittedEvents',
    'product', 'schema', 'startedAt', 'totalEvents', 'usbProtocol',
  ]);
  assert.equal(snapshot.schema, 1);
  assert.equal(snapshot.product, 'PitchComm coach session');
  assert.equal(snapshot.usbProtocol, 4);
  assert.equal(snapshot.dictionary, DICTIONARY);
  assert.equal(snapshot.startedAt, '2026-01-02T03:04:05.000Z');
  assert.equal(snapshot.exportedAt, '2026-01-02T03:04:05.000Z');
  assert.equal(snapshot.totalEvents, 1);
  assert.equal(snapshot.omittedEvents, 0);
  assert.equal(typeof snapshot.evidence, 'string');
  assert.ok(snapshot.evidence.length > 0);
  assert.equal(snapshot.events.length, 1);
  assert.equal(snapshot.events[0].kind, 'page_started');
});

test('observeState dedupes repeated polls that only advance the board clock', () => {
  const report = new SessionReport(DICTIONARY, { limit: 100, wallNow: () => 'w', monoNow: () => 0 });
  report.observeState(stateFixture(1000));
  report.observeState(stateFixture(1001));
  report.observeState(stateFixture(999999));
  assert.equal(report.total, 1);
  assert.equal(report.events[0].kind, 'board_state');
  assert.equal(report.events[0].details.boardClock, 1000);
});

test('observeState records only whitelisted fields plus the board clock', () => {
  const report = new SessionReport(DICTIONARY, { limit: 100, wallNow: () => 'w', monoNow: () => 0 });
  report.observeState(stateFixture(4242, { secret: 'not recorded', token: 7 }));
  const { details } = report.events[0];
  assert.equal(details.boardClock, 4242);
  assert.equal(details.client, 'a1b2c3d4');
  assert.equal(details.boot, '0011223344556677');
  assert.equal(details.role, 0);
  assert.equal(details.dictionary, DICTIONARY);
  assert.equal(details.configured, 1);
  assert.equal(details.radio, 1);
  assert.equal(details.busy, 0);
  assert.equal(details.seq, 5);
  assert.equal(details.category, 1);
  assert.equal(details.code, 41);
  assert.deepEqual(details.links, [1, 0, 1, 1, 1]);
  assert.deepEqual(details.delivery, [0, 2, 2, 0, 0]);
  assert.deepEqual(details.records, [
    { category: 1, seq: 5, code: 41, delivery: [0, 2, 2, 0, 0] },
    { category: 2, seq: 3, code: 1, delivery: [0, 0, 0, 0, 0] },
  ]);
  assert.equal('secret' in details, false);
  assert.equal('token' in details, false);
  assert.equal('clock' in details, false);
});

test('observeState emits again when a whitelisted field changes and when it reverts', () => {
  const report = new SessionReport(DICTIONARY, { limit: 100, wallNow: () => 'w', monoNow: () => 0 });
  report.observeState(stateFixture(1));
  report.observeState(stateFixture(2, { busy: 1 }));
  report.observeState(stateFixture(3));
  assert.equal(report.total, 3);
  assert.deepEqual(report.events.map(e => e.details.busy), [0, 1, 0]);
  assert.deepEqual(report.events.map(e => e.details.boardClock), [1, 2, 3]);
});

test('observeState copies arrays so later mutations do not rewrite recorded evidence', () => {
  const report = new SessionReport(DICTIONARY, { limit: 100, wallNow: () => 'w', monoNow: () => 0 });
  const state = stateFixture(1);
  report.observeState(state);
  state.delivery[0] = 4;
  state.links[0] = 0;
  state.records[0].delivery[0] = 4;
  assert.deepEqual(report.events[0].details.delivery, [0, 2, 2, 0, 0]);
  assert.deepEqual(report.events[0].details.links, [1, 0, 1, 1, 1]);
  assert.deepEqual(report.events[0].details.records[0].delivery, [0, 2, 2, 0, 0]);
});

test('observeConnection dedupes consecutive identical status pairs', () => {
  const report = new SessionReport(DICTIONARY, { limit: 100, wallNow: () => 'w', monoNow: () => 0 });
  report.observeConnection('USB disconnected', 'Connect the coach radio');
  report.observeConnection('USB disconnected', 'Connect the coach radio');
  report.observeConnection('Coach USB connected', 'Connect the coach radio');
  report.observeConnection('Coach USB connected', 'Connect the coach radio');
  report.observeConnection('Coach USB connected', '');
  report.observeConnection('USB disconnected', 'Connect the coach radio');
  assert.equal(report.total, 4);
  assert.deepEqual(report.events.map(e => e.kind), [
    'connection_status', 'connection_status', 'connection_status', 'connection_status',
  ]);
  assert.deepEqual(report.events.map(e => [e.details.status, e.details.blockedBy]), [
    ['USB disconnected', 'Connect the coach radio'],
    ['Coach USB connected', 'Connect the coach radio'],
    ['Coach USB connected', ''],
    ['USB disconnected', 'Connect the coach radio'],
  ]);
});
