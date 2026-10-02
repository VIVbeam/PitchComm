// Local evidence of what this page observed. No raw serial text or team keys.
export class SessionReport {
  constructor(dictionary, {limit = 10000, wallNow = () => new Date().toISOString(), monoNow = () => performance.now()} = {}) {
    if (!/^[a-f0-9]{8}$/.test(dictionary) || !Number.isInteger(limit) || limit < 1) throw new Error('Invalid report settings');
    this.dictionary = dictionary; this.limit = limit; this.wallNow = wallNow; this.monoNow = monoNow;
    this.startedAt = wallNow(); this.startedMono = monoNow();
    this.events = []; this.dropped = 0; this.total = 0; this.lastState = ''; this.lastConnection = '';
  }
  add(kind, details = {}) {
    const event = {index: ++this.total, at: this.wallNow(), elapsedMs: Math.round(this.monoNow() - this.startedMono), kind,
      details: JSON.parse(JSON.stringify(details))};
    this.events.push(event);
    if (this.events.length > this.limit) { this.events.shift(); this.dropped++; }
  }
  observeState(state) {
    // Whitelist protocol fields and omit the advancing clock from comparison.
    // Repeated polls add no noise, while old pitch errors after a play survive.
    const details = Object.fromEntries(['client', 'boot', 'role', 'dictionary', 'configured', 'radio', 'busy', 'seq', 'category', 'code']
      .map(key => [key, state[key]]));
    details.links = [...state.links]; details.delivery = [...state.delivery];
    details.records = state.records.map(r => ({category: r.category, seq: r.seq, code: r.code, delivery: [...r.delivery]}));
    const signature = JSON.stringify(details);
    if (signature === this.lastState) return;
    this.lastState = signature;
    this.add('board_state', {...details, boardClock: state.clock});
  }
  observeConnection(status, blockedBy) {
    const signature = JSON.stringify([status, blockedBy]);
    if (signature === this.lastConnection) return;
    this.lastConnection = signature;
    this.add('connection_status', {status, blockedBy});
  }
  snapshot() {
    return {
      schema: 1, product: 'PitchComm coach session', usbProtocol: 4, dictionary: this.dictionary,
      startedAt: this.startedAt, exportedAt: this.wallNow(), totalEvents: this.total, omittedEvents: this.dropped,
      evidence: 'Times are as observed on this laptop. Receiver acceptance does not prove audible or visible output.',
      events: JSON.parse(JSON.stringify(this.events)),
    };
  }
}
