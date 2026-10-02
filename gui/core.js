export const deliveryLabels = ['--', 'Waiting', 'Output accepted', 'Unconfirmed', 'Output error'];

// Unit 0 is the coach. catalog.units lists the enrolled field units in roster
// order, so a field unit index maps to catalog.units[index - 1].
export const coachUnit = Object.freeze({key: 'coach', label: 'Coach', short: 'CO'});
export function unitAt(catalog, unitIndex) {
  if (unitIndex === 0) return coachUnit;
  if (!Number.isInteger(unitIndex) || unitIndex < 0) return null;
  return catalog?.units?.[unitIndex - 1] ?? null;
}
export function unitIndexOf(catalog, key) {
  const index = Array.isArray(catalog?.units) ? catalog.units.findIndex(unit => unit.key === key) : -1;
  return index < 0 ? -1 : index + 1;
}

// Counts are data: row and col bounds come from the loaded catalog, and a
// caller that knows the pitch count caps the computed code with maxPitch.
export function pitchCode(type, row, col, rows, cols) {
  if (![type, row, col, rows, cols].every(Number.isInteger) || rows < 1 || cols < 1 ||
      type < 1 || row < 1 || row > rows || col < 1 || col > cols) return 0;
  return (type - 1) * rows * cols + (row - 1) * cols + col;
}
export function decodePitch(code, rows, cols) {
  if (!Number.isInteger(code) || code < 1 || !Number.isInteger(rows) || rows < 1 || !Number.isInteger(cols) || cols < 1) return null;
  const size = rows * cols;
  return {
    type: Math.floor((code - 1) / size) + 1,
    row: Math.floor(((code - 1) % size) / cols) + 1,
    col: (code - 1) % cols + 1,
  };
}
// Keyboard flow. The zone letters follow the visual 3x3 layout; each letter is
// only live when the loaded catalog actually has that row and column.
const ZONE_ROWS = ['qwe', 'asd', 'zxc'];
export function keyAction(key, category, {rows = 0, cols = 0, pitchTypes = 0, maxPlay = 0} = {}) {
  if (typeof key !== 'string') return null;
  if (key === 'Enter') return {kind: 'send'};
  if (key === 'Escape') return {kind: 'clear'};
  if (key === 'r' || key === 'R') return {kind: 'resend'};
  if (category === 1 && /^[1-9]$/.test(key)) {
    const value = Number(key);
    return value <= pitchTypes ? {kind: 'type', value} : null;
  }
  if (category === 2 && /^[1-9]$/.test(key)) {
    const value = Number(key);
    return value <= maxPlay ? {kind: 'play', value} : null;
  }
  if (category === 1) {
    const lower = key.toLowerCase();
    if (lower.length === 1) {
      for (let index = 0; index < ZONE_ROWS.length; index++) {
        const col = ZONE_ROWS[index].indexOf(lower);
        if (col >= 0) return index + 1 <= rows && col + 1 <= cols ? {kind: 'zone', row: index + 1, col: col + 1} : null;
      }
    }
  }
  return null;
}
export function formatClock(atMs) {
  if (!Number.isFinite(atMs)) return '';
  const at = new Date(atMs);
  const pad = value => String(value).padStart(2, '0');
  return `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}
export function formatLatency(ms) {
  if (!Number.isFinite(ms)) return '';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
export function describe(catalog, category, code) {
  if (category === 1) {
    const rows = catalog?.rows?.length ?? 0;
    const cols = catalog?.cols?.length ?? 0;
    if (Number.isInteger(code) && code >= 1 && rows > 0 && cols > 0 && code <= catalog.pitches.length * rows * cols) {
      const type = Math.floor((code - 1) / (rows * cols)) + 1;
      const row = Math.floor(((code - 1) % (rows * cols)) / cols) + 1;
      const col = (code - 1) % cols + 1;
      const pitch = catalog.pitches.find(candidate => candidate.key === type);
      const location = catalog.locations[(row - 1) * cols + (col - 1)];
      return pitch && location ? `${pitch.speech} · ${location.speech}` : 'Unknown pitch';
    }
    return 'Waiting for the first call';
  }
  return category === 2 ? catalog.plays.find(candidate => candidate.key === code)?.label ?? 'Unknown play' : 'Waiting for the first call';
}
export function command(id, category, type, row, col, session, counts = {}) {
  const {rows = 3, cols = 3, maxPitch = 81, maxPlay = 21} = counts;
  if (!Number.isInteger(id) || id < 1 || id > 0xffffffff) throw new Error('Invalid request ID');
  if (!/^[a-f0-9]{8}$/.test(session?.client) || session.client === '00000000' || !/^[a-f0-9]{16}$/.test(session?.boot) ||
      !/^[a-f0-9]{8}$/.test(session?.dictionary) || !Number.isInteger(session?.clock) || session.clock < 0 || session.clock > 0xffffffff)
    throw new Error('A fresh coach session is required');
  const suffix = `${session.boot} ${session.dictionary} ${(session.clock + 1500) >>> 0}\n`;
  if (category === 1) {
    const code = pitchCode(type, row, col, rows, cols);
    if (code && code <= maxPitch) return `call ${session.client} ${id} p ${type} ${row} ${col} ${suffix}`;
  }
  if (category === 2 && Number.isInteger(type) && type >= 1 && type <= maxPlay) return `call ${session.client} ${id} d ${type} ${suffix}`;
  throw new Error('Complete the call before sending');
}
export function validState(s, limits = {}) {
  const {maxPitch = 81, maxPlay = 21, unitCount = 5} = limits;
  const uint = n => Number.isInteger(n) && n >= 0 && n <= 0xffffffff;
  const outcome = n => Number.isInteger(n) && n >= 0 && n <= 4;
  return s?.type === 'state' && s.v === 4 && /^[a-f0-9]{8}$/.test(s.client) && uint(s.clock) && uint(s.role) && s.role < unitCount && /^[a-f0-9]{8}$/.test(s.dictionary) &&
    /^[a-f0-9]{16}$/.test(s.boot) && [s.configured, s.radio, s.busy].every(n => n === 0 || n === 1) &&
    uint(s.seq) && [0, 1, 2].includes(s.category) && uint(s.code) &&
    (s.seq === 0 ? s.code === 0 : s.category === 1 ? s.code >= 1 && s.code <= maxPitch : s.category === 2 && s.code >= 1 && s.code <= maxPlay) &&
    Array.isArray(s.links) && s.links.length === unitCount && s.links.every(n => n === 0 || n === 1) &&
    Array.isArray(s.delivery) && s.delivery.length === unitCount && s.delivery.every(outcome) && s.delivery[0] === 0 &&
    Array.isArray(s.records) && s.records.length === 2 && s.records.every((r, i) =>
      r?.category === i + 1 && uint(r.seq) && uint(r.code) &&
      (r.seq === 0 ? r.code === 0 : r.code >= 1 && r.code <= (i === 0 ? maxPitch : maxPlay)) &&
      Array.isArray(r.delivery) && r.delivery.length === unitCount && r.delivery.every(outcome) && r.delivery[0] === 0 &&
      (r.seq !== 0 || r.delivery.every(n => n === 0)) &&
      (s.role !== 0 || !r.seq || (s.seq !== 0 && ((s.seq - r.seq) >>> 0) < 0x80000000)) &&
      (s.role !== 0 || s.category !== r.category || !s.seq ||
        (r.seq === s.seq && r.code === s.code && r.delivery.every((d, j) => d === s.delivery[j]))));
}
// Result frames carry no call codes. The limits are accepted so the app and
// the tests can use one counts object for every validator.
export function validResult(s, _limits = {}) {
  return s?.type === 'result' && s.v === 4 && /^[a-f0-9]{8}$/.test(s.client) && /^[a-f0-9]{16}$/.test(s.boot) && Number.isInteger(s.id) && s.id >= 1 && s.id <= 0xffffffff &&
    Number.isInteger(s.result) && s.result >= 0 && s.result <= 5 && Number.isInteger(s.seq) && s.seq >= 0 && s.seq <= 0xffffffff &&
    (s.result === 0 ? s.seq > 0 : s.seq === 0);
}
export function blockReason(state, lastState, dictionary, pending, now = performance.now(), client = null) {
  if (!state || now - lastState > 1000) return 'Connect the coach radio';
  if (client && state.client !== client) return 'Waiting for this USB session';
  if (state.role !== 0) return 'Connect the coach unit';
  if (state.dictionary !== dictionary) return 'Vocabulary mismatch: rebuild and reload';
  if (!state.configured) return 'Provision the units first';
  if (!state.radio) return 'Coach radio unavailable';
  if (pending || state.busy) return 'Waiting for the current call';
  return '';
}
// USB chunks can contain partial JSON, several lines, and ordinary diagnostic logs.
export class LineFramer {
  constructor(onMessage) { this.onMessage = onMessage; this.line = ''; this.overflow = false; }
  push(text) {
    for (const ch of text) {
      if (ch === '\n') {
        if (!this.overflow && this.line.startsWith('@PC ')) {
          try { this.onMessage(JSON.parse(this.line.slice(4))); } catch { /* Ignore malformed frames. */ }
        }
        this.line = ''; this.overflow = false;
      } else if (ch !== '\r' && !this.overflow) {
        if (this.line.length >= 4096) { this.line = ''; this.overflow = true; }
        else this.line += ch;
      }
    }
  }
}
