# PitchComm flash and test checklist

The working loop: this file is the owner's checklist. Nothing below has been run on hardware yet; every phase starts with a hypothesis and an observation to record. Do not treat a phase as passed until the observations are recorded here or in a copy of the log table.

## Phase 0 — host side (no hardware)

- [ ] `firmware/tests/run_host_tests.ps1` -> 127 checks, 0 failures.
- [ ] `python tools/generate_catalog.py` -> dictionary matches `gui/catalog.json`.
- [ ] `python tools/check_audio.py` -> 15 clips, manifest matches.
- [ ] `python tools/build_audio_fs.py` -> LittleFS image and Intel HEX created.
- [ ] `west build` for all five roles; record image sizes.

## Phase 1 — LE Audio proof (do this first)

Goal: one XIAO nRF54L15 streams an LC3 call to one JY300 earbud.

Setup:
1. `python tools/provision.py ...` (any dummy EUI values are fine for this phase; the proof role does not use Thread).
2. Build the proof role: `tools/build_firmware.ps1 -Roles proof`.
3. Flash it: `tools/flash_firmware.ps1 -Role proof -Erase`.
4. `python tools/build_audio_fs.py` then `tools/flash_audio.ps1`.
5. Unpair the JY300 from any phone, put it in pairing mode.
6. Open the console at 115200 (the XIAO debugger port).

Observations to record:
- [ ] Console shows the BLE scan starting and the JY300 discovered with RSSI.
- [ ] `Connected`, security level reached, sink discovered, stream configured, QoS set, stream started.
- [ ] The spoken call plays in the earbud (FASTBALL / UP / INSIDE).
- [ ] First-word latency from stream start (rough stopwatch) and whether the call is intelligible.
- [ ] Which LC3 preset was selected (log line).
- [ ] Power-cycle: does it reconnect to the bonded earbud without pairing mode?
- [ ] If it stalls at configuration, try forcing 48 kHz (see `dev/le-audio-proof.md`).

Pass: intelligible spoken call in one earbud, repeatable after power cycle.

## Phase 2 — Thread call link, one field unit

Goal: coach to one catcher, handshake, call, ACK, retry, expiry.

Setup:
1. Read both EUI-64s (`eui` command), provision, rebuild coach + catcher.
2. Flash both; power the coach on USB and the catcher on battery.
3. `status` on both consoles.

Observations:
- [ ] Coach reports `LINK=UP` for catcher and `CAT/CATCHER` peer ready; catcher reports linked.
- [ ] Batch: from the coach console, `call ... p 1 1 1 ...` -> catcher prints the call.
- [ ] Coach delivery after ACK shows `OK` (console `status`, GUI receipts).
- [ ] Pull the catcher's radio (power off) mid-call: coach shows `MISS`, does not hang.
- [ ] Request path: catcher keypad sends a pitch; coach accepts; catcher hears `COACH ACCEPTED`.
- [ ] Range baseline: walk the catcher away until the link drops; record distance (open field, body-worn orientation).

Pass: calls and ACKs reliable at arm's length and across a normal baseball field; no lockups.

## Phase 3 — both links on one board

Goal: LE Audio streaming and Thread calls share the nRF54L15 radio.

Observations:
- [ ] Start the JY300 stream, then send a burst of calls; no call is dropped.
- [ ] During audio playback, send the next call; no audio underrun or stutter.
- [ ] Record battery current or runtime during idle-stream vs call-only operation.
- [ ] Record whether the earbud drops the stream when a call burst arrives.

## Phase 4 — full team

- [ ] Provision all five EUI-64s; rebuild all roles.
- [ ] Coach + catcher + pitcher + shortstop + center field on one network.
- [ ] Pitch calls reach pitcher and catcher; plays reach shortstop and center field only.
- [ ] Coach GUI over USB: connect, send a pitch, watch receipts, defensive play, session report.
- [ ] Catcher menu end to end: pitch -> height -> location -> send; Back and long-hold volume.
- [ ] Pitcher recall tap and volume hold.
- [ ] Fielder display labels and OLD marking after 15 s.
- [ ] OLED disconnect (unplug) does not authorize a blind send.

## Phase 4b — wear usability (with the first printed shells)

- [ ] Catcher, squat: the screen is readable without lifting or unstrapping the unit.
- [ ] Catcher, one-knee-down (OKD): the screen is still readable from the normal head position.
- [ ] Catcher, bare hand: all four calls and Back reachable without looking away, with the glove on the other hand; no accidental presses while blocking or sliding; the mount does not catch on the opposite leg.
- [ ] Fielder on a wrist in the two-point ready stance: the screen is readable at a glance and the recall button falls under the thumb.
- [ ] Fielder on a belt in the two-point ready stance and standing: the screen is readable with the 20 degree tilt; the recall button works without looking.
- [ ] Pitcher: recall works through the glove; the collar does not snag; the button cannot be pressed accidentally when the unit lies on a bench.
- [ ] Screen recess and window: the glass sits below the bezel lip and a knocked-on bezel does not touch it.
- [ ] Carriers: straps slide through both loops, the case cannot pull free, and the strap does not cover the screen or buttons.
- [ ] Antenna keepout stays metal-free with the cell and wiring installed.


## Phase 5 — field test

- [ ] End-to-end latency from button press to earbud speech and OLED update, over 20 calls.
- [ ] Range at shortstop/center-field depth and with the catcher crouched.
- [ ] Runtime: one full game on one charge per unit; record start/end voltage.
- [ ] Fit: catcher leg guard, pitcher belt, fielder wrist/belt; readability in sunlight.
- [ ] Catcher screen readable in one-knee-down and two-point stances; Back not hit by accident.
- [ ] Fielder screen readable in the fielding stance (belt) and at a glance (wrist); recall reachable with the glove hand.
- [ ] Drop and rain: 1.5 m drop onto grass/dirt, light rain; inspect after.
- [ ] Impact: throw a baseball at the display face and the pitcher collar from playing distance; inspect bezel, window and switch action.
- [ ] Abuse: fielder dives/slides on the unit, catcher blocks with it on, strap is tugged hard; case, carrier and strap stay put.
- [ ] Recharge and repeat.

## Results log

Copy this table and fill it in per run.

| Date | Phase | Firmware build dir | Observation | Result | Notes |
|---|---|---|---|---|---|
| | | | | | |
