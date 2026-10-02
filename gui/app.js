import { deliveryLabels, unitAt, unitIndexOf, pitchCode, describe, command, validState, validResult, blockReason, LineFramer } from './core.js';
import { SessionReport } from './report.js';

const $ = id => document.getElementById(id);
let catalog, report, connection = null, closing = null, state = null, lastState = 0, pending = null;
let category = 1, type = 0, row = 0, col = 0, play = 0;
let limits = {rows: 3, cols: 3, maxPitch: 81, maxPlay: 21, unitCount: 5};
let nextId = 1, history = [], connecting = false;
let client = '';
let seenFailures = new Set();
const encoder = new TextEncoder();

function notice(text, error = false) {
  report?.add('notice', {message: text, error});
  $('notice').textContent = text; $('notice').classList.toggle('error', error);
}
function saveReport() {
  if (!report) return;
  const data = report.snapshot();
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + '\n'], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url;
  link.download = `pitchcomm-session-${data.startedAt.replace(/[:.]/g, '-')}.json`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function pickButton(label, key, onClick, small = '') {
  const button = document.createElement('button');
  button.className = 'choice'; button.dataset.key = key; button.setAttribute('aria-pressed', 'false');
  if (small) { const hint = document.createElement('small'); hint.textContent = small; button.append(hint); }
  button.append(document.createTextNode(label)); button.addEventListener('click', onClick); return button;
}
function buildControls() {
  for (const pitch of catalog.pitches) $('pitchTypes').append(pickButton(pitch.speech, pitch.key, () => { type = pitch.key; render(); }, String(pitch.key).padStart(2, '0')));
  const columns = document.querySelector('.zone-columns');
  columns.style.gridTemplateColumns = `repeat(${catalog.cols.length}, 1fr)`;
  columns.replaceChildren(...catalog.cols.map(column => {
    const label = document.createElement('span'); label.textContent = column.label; return label;
  }));
  $('zone').style.gridTemplateColumns = `repeat(${catalog.cols.length}, 1fr)`;
  for (const zoneRow of catalog.rows) for (const zoneCol of catalog.cols) {
    const location = catalog.locations.find(candidate => candidate.row === zoneRow.key && candidate.col === zoneCol.key);
    const button = document.createElement('button'); button.className = 'zone-button';
    button.dataset.row = zoneRow.key; button.dataset.col = zoneCol.key;
    button.setAttribute('aria-label', location?.speech ?? `${zoneRow.label}, ${zoneCol.label}`); button.setAttribute('aria-pressed', 'false');
    const heading = document.createElement('strong'); heading.textContent = location?.speech ?? `${zoneRow.label} · ${zoneCol.label}`;
    button.append(heading);
    button.addEventListener('click', () => { row = zoneRow.key; col = zoneCol.key; render(); }); $('zone').append(button);
  }
  for (const p of catalog.plays) {
    $('plays').append(pickButton(p.label, p.key, () => { play = p.key; render(); }));
  }
  catalog.units.forEach((unit, index) => {
    const i = index + 1;
    const card = document.createElement('div'); card.className = 'receiver';
    const top = document.createElement('div'); top.className = 'receiver-top';
    const title = document.createElement('strong'); title.textContent = unit.label;
    const dot = document.createElement('span'); dot.className = 'dot'; dot.id = `dot${i}`; top.append(title, dot);
    const caps = [unit.audio ? 'Audio' : '', unit.controls ? 'Controls' : '', unit.pitches ? 'Pitches' : ''].filter(Boolean);
    const link = document.createElement('div'); link.id = `link${i}`; link.className = 'receiver-link'; link.textContent = 'Connection unknown';
    if (caps.length) { const capabilities = document.createElement('div'); capabilities.className = 'receiver-link'; capabilities.textContent = caps.join(' · '); card.append(top, capabilities, link); }
    else { card.append(top, link); }
    $('receivers').append(card);
    const receipt = document.createElement('div'); receipt.className = 'receipt'; receipt.id = `receipt${i}`;
    const rname = document.createElement('span'); rname.textContent = unit.label;
    const result = document.createElement('span'); result.id = `delivery${i}`; result.textContent = '--'; receipt.append(rname, result); $('receipts').append(receipt);
  });
}
function setSelected(button, chosen) { button.classList.toggle('selected', chosen); button.setAttribute('aria-pressed', String(chosen)); }
function render() {
  if (!catalog) return;
  $('saveReport').disabled = !report;
  $('reportHint').textContent = report?.dropped ? `${report.dropped} earlier report events omitted at the limit. Save before reloading.` : '';
  const fresh = state && performance.now() - lastState <= 1000;
  const compatible = fresh && state.client === client && state.role === 0 && state.dictionary === catalog.dictionary;
  $('connect').disabled = connecting || Boolean(closing);
  $('connect').firstChild.textContent = closing ? 'Closing radio… ' : connecting ? 'Connecting… ' : connection ? 'Disconnect radio ' : 'Connect coach radio ';
  $('connectionStatus').textContent = closing ? 'Closing USB connection' : connection ? fresh ? compatible ? 'Coach USB connected' : 'Check coach unit' : 'Waiting for coach' : 'USB disconnected';
  $('connectionStatus').classList.toggle('live', Boolean(compatible && state.radio && state.configured));
  $('pitchTab').setAttribute('aria-selected', String(category === 1)); $('playTab').setAttribute('aria-selected', String(category === 2));
  $('pitchPanel').hidden = category !== 1; $('playPanel').hidden = category !== 2;
  document.querySelectorAll('#pitchTypes button').forEach(b => setSelected(b, +b.dataset.key === type));
  document.querySelectorAll('#zone button').forEach(b => setSelected(b, +b.dataset.row === row && +b.dataset.col === col));
  document.querySelectorAll('#plays button').forEach(b => setSelected(b, +b.dataset.key === play));
  const selectedPlay = catalog.plays.find(p => p.key === play);
  const selectedRow = catalog.rows.find(candidate => candidate.key === row);
  const selectedCol = catalog.cols.find(candidate => candidate.key === col);
  const selectedLocation = catalog.locations.find(candidate => candidate.row === row && candidate.col === col);
  const pitchIndices = catalog.units.map((unit, index) => unit.pitches ? index + 1 : 0).filter(Boolean);
  const audienceIndices = selectedPlay ? selectedPlay.audience.map(key => unitIndexOf(catalog, key)).filter(index => index > 0) : [];
  const targetIndices = category === 1 ? pitchIndices : audienceIndices;
  $('previewCategory').textContent = category === 1 ? 'PITCH CALL' : 'PLAY CALL';
  $('previewType').textContent = category === 1 ? catalog.pitches.find(p => p.key === type)?.speech ?? 'Choose a pitch' : selectedPlay?.label ?? 'Choose a play';
  $('previewLocation').textContent = category === 1 ? selectedLocation ? selectedLocation.speech : selectedRow && selectedCol ? `${selectedRow.label} · ${selectedCol.label}` : 'Then choose a location' : selectedPlay ? selectedPlay.speech : '';
  $('previewTargets').textContent = category === 1
    ? pitchIndices.map(index => unitAt(catalog, index).label).join(' + ') || 'No enrolled receivers'
    : selectedPlay ? audienceIndices.map(index => unitAt(catalog, index).label).join(' + ') || 'No enrolled receivers' : 'Choose a play';
  const complete = category === 1 ? Boolean(pitchCode(type, row, col, limits.rows, limits.cols) && type <= catalog.pitches.length) : Boolean(play);
  const reason = blockReason(state, lastState, catalog.dictionary, pending, performance.now(), client);
  report?.observeConnection($('connectionStatus').textContent, reason);
  $('send').disabled = connecting || Boolean(closing) || !connection || !complete || Boolean(reason);
  $('send').firstChild.textContent = pending ? 'Sending… ' : category === 1 ? 'Send pitch ' : 'Send play ';
  const offline = compatible ? targetIndices.filter(i => !state.links[i]).map(i => unitAt(catalog, i).label) : [];
  $('sendHint').textContent = reason || (!complete ? 'Choose a complete call to send' : offline.length ? `${offline.join(' + ')} offline: delivery may be unconfirmed` : 'Ready to send');
  catalog.units.forEach((unit, index) => {
    const i = index + 1;
    const on = Boolean(compatible && state.radio && state.links[i]);
    $(`dot${i}`).classList.toggle('on', on); $(`link${i}`).classList.toggle('on', on);
    $(`link${i}`).textContent = compatible ? on ? '● Connected' : '○ Offline' : 'Connection unknown';
    const d = compatible && state.seq ? state.delivery[i] : 0;
    $(`delivery${i}`).textContent = deliveryLabels[d]; $(`receipt${i}`).className = `receipt ${d === 2 ? 'ok' : d >= 3 ? 'error' : ''}`;
  });
  $('lastCall').textContent = compatible && state.seq ? `#${state.seq} · ${describe(catalog, state.category, state.code)}` : 'No current call';
  const failures = [];
  if (compatible) for (const record of state.records) {
    record.delivery.forEach((d,i) => { if (d === 4 && record.seq && i > 0) failures.push(`${unitAt(catalog, i).label} output failed for call #${record.seq}`); });
  }
  $('failureStatus').hidden = !failures.length;
  const failureText = failures.length ? failures.join('. ') + '. Check with the players.' : '';
  if ($('failureStatus').textContent !== failureText) $('failureStatus').textContent = failureText;
  $('history').replaceChildren();
  if (!history.length) { const li = document.createElement('li'); li.className = 'empty'; li.textContent = 'No calls yet.'; $('history').append(li); }
  for (const item of history) {
    const li = document.createElement('li'); const title = document.createElement('strong'); title.textContent = `${item.seq ? '#' + item.seq + ' · ' : ''}${item.label}`;
    const result = document.createElement('span'); result.textContent = item.status;
    if (item.failed) result.className = 'failed';
    li.append(title, result); $('history').append(li);
  }
}
function unknownPending(message) {
  if (!pending) return;
  report?.add('call_unconfirmed', {client, id: pending.id, boot: pending.item.boot, reason: message});
  pending.item.status = 'Unconfirmed'; pending = null;
  notice(message + ' Check the latest field call before sending again.', true);
}
function updateReceipts(item) {
  if (!state || item.boot !== state.boot || !item.seq) return;
  const record = state.records.find(record => record.seq === item.seq && record.category === item.category);
  if (!record) return;
  item.status = record.delivery.map((d,i) => i === 0 ? '' : `${unitAt(catalog, i).label}: ${deliveryLabels[d]}`).filter(Boolean).join(' · ');
  item.failed = record.delivery.includes(4);
}
function receive(message) {
  if (validState(message, limits)) {
    report?.observeState(message);
    if (state && message.boot !== state.boot) unknownPending('The coach restarted; the previous send is unconfirmed.');
    state = message; lastState = performance.now();
    for (const record of state.records) {
      for (const item of history) if (item.boot === state.boot && item.seq === record.seq && item.category === record.category && item.seq) {
        item.status = record.delivery.map((d,i) => i === 0 ? '' : `${unitAt(catalog, i).label}: ${deliveryLabels[d]}`).filter(Boolean).join(' · ');
        item.failed = record.delivery.includes(4);
      }
      if (state.role === 0 && state.client === client && state.dictionary === catalog.dictionary && record.seq) {
        const failed = [];
        record.delivery.forEach((d,i) => {
          const key = `${state.boot}:${record.seq}:${i}`;
          if (d === 4 && i > 0 && !seenFailures.has(key)) { seenFailures.add(key); failed.push(unitAt(catalog, i).label); }
        });
        if (failed.length) notice(`${failed.join(' + ')} output failed for call #${record.seq} (${describe(catalog, record.category, record.code)}). Check with the players before continuing.`, true);
      }
    }
    render();
  } else if (validResult(message, limits)) {
    const matchedPending = message.client === client && pending?.id === message.id;
    const item = history.find(item => item.written && item.client === message.client &&
      item.boot === message.boot && item.id === message.id);
    report?.add('call_result', {client: message.client, boot: message.boot, id: message.id, result: message.result,
      seq: message.seq, matchedPending: Boolean(matchedPending), matchedHistory: Boolean(item)});
    if (matchedPending && message.boot !== pending.item.boot) {
      unknownPending('The coach session changed; the send is unconfirmed.'); state = null; lastState = 0; render(); return;
    }
    // Late results can resolve retained calls; duplicates must preserve receiver evidence.
    if (!item || item.result !== undefined) return;
    if (pending?.item === item) pending = null;
    item.result = message.result;
    if (message.result === 0) { item.seq = message.seq; item.status = 'Waiting for receivers'; updateReceipts(item); notice('Call sent. Watch the receiver confirmations.'); }
    else { item.status = ['Accepted', 'Busy', 'Offline', 'Rejected', 'Expired', 'Session changed'][message.result]; notice(`Coach ${item.status.toLowerCase()}. Not accepted; send again when ready.`, true); }
    render();
  }
}
function write(line, guard = null) {
  const c = connection;
  if (!c || c.closing) return Promise.reject(new Error('Coach USB disconnected'));
  c.queue = c.queue.then(() => {
    if (connection !== c || c.closing || (guard && !guard())) {
      const error = new Error('USB command cancelled before writing'); error.notSent = true; throw error;
    }
    return c.writer.write(encoder.encode(line));
  });
  return c.queue;
}
async function bounded(promise, milliseconds, message) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
async function read(c) {
  const decoder = new TextDecoder(); const framer = new LineFramer(message => { if (connection === c) receive(message); });
  try { while (!c.closing) { const {value, done} = await c.reader.read(); if (done) break; framer.push(decoder.decode(value, {stream: true})); } }
  catch (e) { if (!c.closing) notice(`USB connection lost: ${e.message}`, true); }
  finally { c.reader.releaseLock(); if (!c.closing) await disconnect(c, true); }
}
async function disconnect(c = connection, fromRead = false) {
  if (!c || c.closing) return; c.closing = true;
  report?.add('usb_disconnect', {client, fromRead});
  closing = c;
  if (connection === c) connection = null;
  unknownPending('USB disconnected; the previous send is unconfirmed.'); state = null; lastState = 0; render();
  c.closeTask = (async () => {
    if (!fromRead) { try { await c.reader.cancel(); await c.readTask; } catch { /* Continue with port cleanup. */ } }
    try { await c.queue; } catch { /* A failed write is never retried. */ }
    c.writer.releaseLock(); await c.port.close();
    report?.add('usb_closed', {client});
    // A rejected close leaves ownership uncertain. Only a confirmed close
    // permits another connection; the bounded caller gives recovery advice.
    if (closing === c) closing = null; render();
  })();
  try { await bounded(c.closeTask, 2000, 'USB port is still closing'); }
  catch { if (closing === c) notice('USB port is still closing. Unplug the coach USB cable and reload this page before reconnecting.', true); }
}
async function closeUnconnectedPort(port, openTask) {
  // An open timeout does not cancel Web Serial's underlying operation. Retain
  // ownership until that operation settles, then close a late-opened port.
  const owner = {port}; closing = owner; render();
  owner.closeTask = (async () => {
    let opened = false;
    if (openTask) {
      try { await openTask; opened = true; } catch { /* A rejected open has no usable connection. */ }
    }
    if (opened) await port.close();
    if (closing === owner) closing = null; render();
  })();
  try { await bounded(owner.closeTask, 2000, 'USB port is still closing'); }
  catch { if (closing === owner) notice('USB port is still closing. Unplug the coach USB cable and reload this page before reconnecting.', true); }
}
async function connect() {
  if (closing) return;
  if (connection) { await disconnect(); return; }
  if (!('serial' in navigator)) { notice('Open this page in Chrome for USB Web Serial.', true); return; }
  connecting = true; render(); let port, openTask, reader, writer, openedConnection;
  report?.add('usb_connect_requested');
  try {
    port = await navigator.serial.requestPort();
    notice('Opening the coach USB port…');
    openTask = port.open({baudRate: 115200});
    await bounded(openTask, 2000, 'Coach USB port did not finish opening');
    reader = port.readable.getReader(); writer = port.writable.getWriter();
    const c = {port, reader, writer, queue: Promise.resolve(), closing: false};
    openedConnection = c; connection = c; state = null; lastState = 0; seenFailures = new Set();
    const random = crypto.getRandomValues(new Uint32Array(1))[0] || 1;
    client = random.toString(16).padStart(8, '0');
    report?.add('usb_opened', {client});
    c.readTask = read(c); await bounded(write(`gui ${client}\n`), 2000, 'Coach USB write did not finish');
    if (!state?.records.some(record => record.delivery.includes(4))) notice('Connected over USB. Waiting for the coach unit’s readiness check.');
  } catch (e) {
    // A read failure may already have detached this connection and started
    // cleanup. Keep that owner's locks and close task instead of replacing it.
    if (openedConnection) await disconnect(openedConnection);
    else if (port) {
      // Acquiring the second stream can fail after the first is already locked.
      try { reader?.releaseLock(); } catch { /* No usable reader. */ }
      try { writer?.releaseLock(); } catch { /* No usable writer. */ }
      await closeUnconnectedPort(port, openTask);
    }
    if (!closing) notice(e.name === 'NotFoundError' ? 'No USB port selected. Connect when you are ready.' : `Could not connect: ${e.message}`, e.name !== 'NotFoundError');
  } finally { connecting = false; render(); }
}
async function send() {
  if ($('send').disabled) return;
  const id = nextId; nextId = nextId === 0xffffffff ? 1 : nextId + 1;
  const code = category === 1 ? pitchCode(type, row, col, limits.rows, limits.cols) : play;
  const line = command(id, category, category === 1 ? type : play, row, col, state, limits);
  const item = {id, client, category, seq: 0, boot: state.boot, label: describe(catalog, category, code), status: 'Awaiting coach'};
  report?.add('call_requested', {client, id, boot: item.boot, category, code, label: item.label});
  history.unshift(item); history = history.slice(0, 8); pending = {id, item, started: performance.now()}; render();
  try { await write(line, () => {
    const ready = pending?.id === id && state?.boot === item.boot &&
      !blockReason(state, lastState, catalog.dictionary, null, performance.now(), client);
    if (ready) { item.written = true; report?.add('call_write_started', {client, id, boot: item.boot}); }
    return ready;
  }); }
  catch (error) {
    if (error.notSent) {
      report?.add('call_not_sent', {client, id, boot: item.boot});
      item.status = 'Not sent';
      if (pending?.id === id) pending = null;
      notice('Call cancelled before it reached the radio. Reconnect and send again.', true);
    } else unknownPending('USB write failed; the send result is unconfirmed.');
    await disconnect();
  }
}
async function start() {
  try { const response = await fetch('./catalog.json', {cache: 'no-store'}); if (!response.ok) throw new Error('Vocabulary could not be loaded'); catalog = await response.json();
    const rows = catalog.rows.length, cols = catalog.cols.length;
    limits = {rows, cols, maxPitch: catalog.pitches.length * rows * cols, maxPlay: catalog.plays.length, unitCount: catalog.units.length + 1};
    report = new SessionReport(catalog.dictionary); report.add('page_started'); buildControls(); }
  catch (e) { notice(e.message + '. Start tools/serve_gui.py and reload this page.', true); return; }
  $('connect').addEventListener('click', connect); $('send').addEventListener('click', send);
  $('saveReport').addEventListener('click', saveReport);
  $('pitchTab').addEventListener('click', () => { category = 1; render(); }); $('playTab').addEventListener('click', () => { category = 2; render(); });
  $('clear').addEventListener('click', () => { type = row = col = play = 0; render(); });
  let polling = false;
  setInterval(() => {
    if (pending && performance.now() - pending.started > 2500) unknownPending('No coach response; delivery is unconfirmed.');
    if (connection && !polling) { polling = true; write(`gui ${client}\n`).catch(() => disconnect()).finally(() => { polling = false; }); }
    render();
  }, 500);
  if (!('serial' in navigator)) notice('For USB calls, use desktop Chrome and open this page through the local launcher.', true);
  render();
}
start();
