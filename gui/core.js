export const roles = ['Catcher', 'Pitcher', 'Shortstop', 'Center field'];
export const deliveryLabels = ['—', 'Waiting', 'Output accepted', 'Unconfirmed', 'Output error'];

export function pitchCode(type, height, side) {
  if (![type, height, side].every(Number.isInteger) || type < 1 || type > 9 || height < 1 || height > 3 || side < 1 || side > 3) return 0;
  return (type - 1) * 9 + (height - 1) * 3 + side;
}
export function describe(catalog, category, code) {
  if (category === 1 && Number.isInteger(code) && code >= 1 && code <= 81) {
    const type = Math.floor((code - 1) / 9) + 1;
    const height = Math.floor(((code - 1) % 9) / 3) + 1;
    const side = (code - 1) % 3 + 1;
    const pitch = catalog.pitches.find(p => p.key === type);
    return pitch ? `${pitch.speech} · ${catalog.heights[height - 1]} · ${catalog.sides[side - 1]}` : 'Unknown pitch';
  }
  return category === 2 ? catalog.plays.find(p => p.key === code)?.label ?? 'Unknown play' : 'Waiting for the first call';
}
export function command(id, category, type, height, side, session) {
  if (!Number.isInteger(id) || id < 1 || id > 0xffffffff) throw new Error('Invalid request ID');
  if (!/^[a-f0-9]{8}$/.test(session?.client) || session.client === '00000000' || !/^[a-f0-9]{16}$/.test(session?.boot) ||
      !/^[a-f0-9]{8}$/.test(session?.dictionary) || !Number.isInteger(session?.clock) || session.clock < 0 || session.clock > 0xffffffff)
    throw new Error('A fresh coach session is required');
  const suffix = `${session.boot} ${session.dictionary} ${(session.clock + 1500) >>> 0}\n`;
  if (category === 1 && pitchCode(type, height, side)) return `call ${session.client} ${id} p ${type} ${height} ${side} ${suffix}`;
  if (category === 2 && Number.isInteger(type) && type >= 1 && type <= 9) return `call ${session.client} ${id} d ${type} ${suffix}`;
  throw new Error('Complete the call before sending');
}
export function validState(s) {
  const uint = n => Number.isInteger(n) && n >= 0 && n <= 0xffffffff;
  return s?.type === 'state' && s.v === 4 && /^[a-f0-9]{8}$/.test(s.client) && uint(s.clock) && uint(s.role) && s.role <= 4 && /^[a-f0-9]{8}$/.test(s.dictionary) &&
    /^[a-f0-9]{16}$/.test(s.boot) && [s.configured, s.radio, s.busy].every(n => n === 0 || n === 1) &&
    uint(s.seq) && [0, 1, 2].includes(s.category) && uint(s.code) &&
    (s.seq === 0 ? s.code === 0 : s.category === 1 ? s.code >= 1 && s.code <= 81 : s.category === 2 && s.code >= 1 && s.code <= 9) &&
    Array.isArray(s.links) && s.links.length === 4 && s.links.every(n => n === 0 || n === 1) &&
    Array.isArray(s.delivery) && s.delivery.length === 4 && s.delivery.every(n => Number.isInteger(n) && n >= 0 && n <= 4) &&
    Array.isArray(s.records) && s.records.length === 2 && s.records.every((r, i) =>
      r?.category === i + 1 && uint(r.seq) && uint(r.code) &&
      (r.seq === 0 ? r.code === 0 : r.code >= 1 && r.code <= (i === 0 ? 81 : 9)) &&
      Array.isArray(r.delivery) && r.delivery.length === 2 && r.delivery.every(n => Number.isInteger(n) && n >= 0 && n <= 4) &&
      (r.seq !== 0 || r.delivery.every(n => n === 0)) &&
      (s.role !== 0 || !r.seq || (s.seq !== 0 && ((s.seq - r.seq) >>> 0) < 0x80000000)) &&
      (s.role !== 0 || s.category !== r.category || !s.seq ||
        (r.seq === s.seq && r.code === s.code && r.delivery.every((d,j) => d === s.delivery[i * 2 + j]))));
}
export function validResult(s) {
  return s?.type === 'result' && s.v === 4 && /^[a-f0-9]{8}$/.test(s.client) && /^[a-f0-9]{16}$/.test(s.boot) && Number.isInteger(s.id) && s.id >= 1 && s.id <= 0xffffffff &&
    Number.isInteger(s.result) && s.result >= 0 && s.result <= 5 && Number.isInteger(s.seq) && s.seq >= 0 && s.seq <= 0xffffffff &&
    (s.result === 0 ? s.seq > 0 : s.seq === 0);
}
export function blockReason(state, lastState, dictionary, pending, now = performance.now(), client = null) {
  if (!state || now - lastState > 1000) return 'Connect the coach radio';
  if (client && state.client !== client) return 'Waiting for this USB session';
  if (state.role !== 0) return 'Connect the coach unit';
  if (state.dictionary !== dictionary) return 'Vocabulary mismatch — rebuild and reload';
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
