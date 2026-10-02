# PitchComm flash and test checklist

The working loop: this file is the owner's checklist. Nothing below has been run on hardware yet; every phase starts with a hypothesis and an observation to record. Do not treat a phase as passed until the observations are recorded here or in a copy of the log table.

## Bench minimum

Two boards are enough, but one of them must be the coach: it is the Thread leader and relay, and two field units will not form a network without it.

| Goal | Minimum hardware |
|---|---|
| Link, console, retry, range | 2x XIAO nRF54L15, 2x USB-C data cables, laptop with NCS, 2 USB ports (or a powered hub) |
| Clean pitch-call display | the above + 1x 128x32 SSD1306 OLED (3V3, GND, D4, D5) and the catcher build |
| Catcher request/menu | the above + 5x momentary switches (D0-D3 calls, D13 Back, each to GND) |
| Spoken call | the above + 1x JY300 and the pitcher build |
| Recall/volume | 1x momentary switch on D1 to GND |

No cells, cases, or external probe are needed: the boards run from USB, the onboard debugger flashes and hosts the console, and no firmware path gates on battery voltage. Provision the two real EUI-64s and use unique dummy values for the three absent units; the coach shows them offline. Without an output device the field unit ACKs `OutputError`, so calls show `ERR` rather than `OK`; that still exercises the handshake, call, retry, expiry and ACK paths.

## Phase 0: host side (no hardware)

Already verified on this machine:

- [x] `firmware/tests/run_host_tests.ps1` -> 3348 checks, 0 failures (includes 100k-buffer protocol fuzzing, lossy/reordered link scenarios, multi-node fairness, clock wrap and addressing vectors; `-Sanitize` falls back with a warning on this MSYS toolchain because libasan is absent). The same script also consumes the shared GUI protocol fixtures with the firmware parsers: 168 checks, 0 failures.
- [x] `firmware/tests/run_audio_tests.ps1` -> 146 checks, 0 failures (resampler ramps, frame boundaries, two-clip call assembly).
- [x] `gui/test/run_tests.ps1` -> 71 tests, 0 failures (core, report, firmware/GUI catalog parity, shared protocol fixtures, 21-play list, unit audiences, variable-roster validation including a custom unit).
- [x] Coach desk smoke: served locally with every asset 200 and no console errors; the receiver cards, tabs, 9 pitch buttons, 3x3 location grid, 21 play buttons, selection preview and the disabled Send state all render.
- [x] `dev/host_compile/run.ps1 -Provisioned -MinSize -RawI2c -RosterVariant` -> 76 syntax checks, all pass (stub headers, no NCS needed). The variant mode compiles the portable headers against a seven-unit roster with a custom `bench` key and an audio outfield, proving enrollment counts and audiences are data.
- [x] `python tools/generate_catalog.py` -> dictionary matches `gui/catalog.json` (`299314f6`), 21 plays, 4 enrolled units, 37 clips.
- [x] `python tools/check_audio.py` -> 37 clips, manifest matches (`299314f6`); `python tools/import_demo_audio.py` rebuilds them from `College Demo Tracks/`.
- [x] `python tools/build_audio_fs.py` -> LittleFS image and Intel HEX created (37 clips, `236550`/`729088` clip plus manifest bytes, image `729088` bytes at `0x0C2000`), verified by `tools/verify_audio_fs.py`; the PCM variant is refused over budget.
- [x] `python tools/preflight.py --audio` -> audio ready, repo audit passes.
- [x] `python tools/audit_repo.py` -> 6/6 checks pass.
- [x] `python tools/test_tools.py` -> 164 tests, 0 failures (catalog, roster variants, enrollment CLI, provisioning, preflight drift checks, audio budgets, packaging, audit).
- [x] `python dev/cad/generate_cases.py --no-preview` -> all checks passed; STLs written to `cad/unbranded/exports/`.
- [x] `powershell tools/build_print_pack.ps1` and `-Bench` -> both packs written and verified by `-Verify`.
- [x] `powershell tools/check_toolchain.ps1` -> only `west` and `nrfutil` missing on this bench, as expected.
- [x] `powershell tools/verify_all.ps1` -> all seven required host steps pass, exit 0; the informational toolchain check reports only `west`/`nrfutil` missing, and `-Quick` skips the host compile and toolchain check.

Still needs the NCS toolchain:

- [ ] `west build` for all enrolled units; record `IMAGE <unit>: bytes / 729088`.
- [ ] Build the proof and the full team once with `-StrictSize`.

## Phase 1: LE Audio proof (do this first)

Goal: one XIAO nRF54L15 streams an LC3 call to one JY300 earbud.

Setup:
1. `python tools/provision.py ...` (any dummy EUI values are fine for this phase; the proof role does not use Thread).
2. Build the proof role: `tools/build_firmware.ps1 -Units proof`.
3. Flash it: `tools/flash_firmware.ps1 -Unit proof -Erase`.
4. `python tools/build_audio_fs.py` then `tools/flash_audio.ps1`.
5. Unpair the JY300 from any phone, put it in pairing mode.
6. Open the console at 115200 (the XIAO debugger port).

Observations to record:
- [ ] Console shows the BLE scan starting and the JY300 discovered with RSSI.
- [ ] `Connected`, security level reached, sink discovered, stream configured, QoS set, stream started.
- [ ] The spoken call plays in the earbud (FOUR-SEAM FASTBALL / HIGH INSIDE).
- [ ] First-word latency from stream start (rough stopwatch) and whether the call is intelligible.
- [ ] Which LC3 preset was selected (log line).
- [ ] Power-cycle: does it reconnect to the bonded earbud without pairing mode?
- [ ] If it stalls at configuration, try forcing 48 kHz (see `dev/le-audio-proof.md`).

Pass: intelligible spoken call in one earbud, repeatable after power cycle.

## Phase 2: Thread call link, one field unit

Goal: coach to one catcher, handshake, call, ACK, retry, expiry.

Setup:
1. Read both EUI-64s (`eui` command), provision, rebuild coach + catcher.
2. Flash both; power the coach on USB and the catcher on battery.
3. `status` on both consoles; then run `selftest` on each board.

Observations:
- [ ] `selftest` prints only PASS or SKIP for the installed subsystems (coach: no OLED should be SKIP, not FAIL; catcher: OLED/CONTROLS/BATTERY should PASS, STORAGE/AUDIO should SKIP).
- [ ] Coach reports `LINK=UP` for catcher and `CAT/CATCHER` peer ready; catcher reports linked.
- [ ] Batch: from the coach console, `call ... p 1 1 1 ...` -> catcher shows the call on the OLED for a few seconds, then returns to the menu.
- [ ] Coach delivery after ACK shows `OK` (console `status`, GUI receipts).
- [ ] Pull the catcher's radio (power off) mid-call: coach shows `MISS`, does not hang.
- [ ] Request path: catcher keypad sends a pitch; the coach module accepts it (no human step); catcher shows `COACH ACCEPTED` and the call.
- [ ] Range baseline: walk the catcher away until the link drops; record distance (open field, body-worn orientation).

Pass: calls and ACKs reliable at arm's length and across a normal baseball field; no lockups.

## Phase 3: both links on one board

Goal: LE Audio streaming and Thread calls share the nRF54L15 radio.

Observations:
- [ ] Start the JY300 stream, then send a burst of calls; no call is dropped.
- [ ] During audio playback, send the next call; no audio underrun or stutter.
- [ ] Record battery current or runtime during idle-stream vs call-only operation.
- [ ] Record whether the earbud drops the stream when a call burst arrives.

## Phase 4: full team

- [ ] Provision the enrolled EUI-64s; rebuild every enrolled unit.
- [ ] `selftest` on all enrolled units; each reports only PASS/SKIP for its installed parts, no FAIL.
- [ ] Coach plus every enrolled unit on one network.
- [ ] Pitch calls reach pitcher and catcher; plays reach exactly their audience (PICKOFF: pitcher, catcher, shortstop; BUNT DEF: the whole team; SEE UP: center field).
- [ ] Audio budget: `python tools/check_audio.py` reports the compact bytes against the slot, and `python tools/build_audio_fs.py --pcm` refuses over budget with the shrink options.
- [ ] Enrollment growth: set `enrolled: true` for one extra position, provision a dummy EUI, rebuild that unit, and confirm the desk lists it and the plays whose audience now includes it.
- [ ] Coach GUI over USB: connect, send a pitch, watch receipts, defensive play, session report.
- [ ] Catcher menu end to end: pitch -> row -> column -> send; Back and long-hold volume.
- [ ] Pitcher recall tap and volume hold.
- [ ] Fielder display labels and OLD marking after 15 s.
- [ ] OLED disconnect (unplug) does not authorize a blind send.

## Phase 4b: wear check (with the first printed shells)

- [ ] Catcher, in a crouch and standing: the screen is readable without lifting or unstrapping the unit.
- [ ] Catcher, bare hand: all four calls and Back reachable without looking away, with the glove on the other hand; no accidental presses while blocking or sliding; the mount does not catch on the opposite leg.
- [ ] Fielder on a wrist: the screen reads at a glance and the recall button falls under the thumb.
- [ ] Fielder on a belt, standing and bent forward: the screen reads without unclipping the unit; the recall button works without looking.
- [ ] Pitcher: recall works through the glove; the collar does not snag; the button cannot be pressed accidentally when the unit lies on a bench.
- [ ] Screen recess and window: the glass sits below the bezel lip and a knocked-on bezel does not touch it.
- [ ] Carriers: straps slide through both loops, the case cannot pull free, and the strap does not cover the screen or buttons.
- [ ] Antenna keepout stays metal-free with the cell and wiring installed.


## Phase 5: field test

- [ ] End-to-end latency from button press to earbud speech and OLED update, over 20 calls.
- [ ] Range at shortstop/center-field depth and with the catcher crouched.
- [ ] Runtime: one full game on one charge per unit; record start/end voltage.
- [ ] Fit: catcher leg guard, pitcher belt, fielder wrist/belt; readability in sunlight.
- [ ] Catcher screen readable in a crouch and standing; Back not hit by accident.
- [ ] Fielder screen readable on the belt while bent forward and on the wrist at a glance; recall reachable with the bare hand.
- [ ] Drop and rain: 1.5 m drop onto grass/dirt, light rain; inspect after.
- [ ] Impact: throw a baseball at the display face and the pitcher collar from playing distance; inspect bezel, window and switch action.
- [ ] Abuse: fielder dives/slides on the unit, catcher blocks with it on, strap is tugged hard; case, carrier and strap stay put.
- [ ] Recharge and repeat.

## Results log

Copy this table and fill it in per run.

| Date | Phase | Firmware build dir | Observation | Result | Notes |
|---|---|---|---|---|---|
| | | | | | |
