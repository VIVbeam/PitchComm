# PitchComm roadmap

Build order and open questions. Each field unit is one Seeed XIAO nRF54L15 (Nordic nRF54L15: LE Audio, 802.15.4 Thread/Zigbee/Matter, no Wi-Fi). Firmware is Zephyr / nRF Connect SDK.

## Size constraint

Small comes first. Each unit should be as small as possible while it still:

- runs one full game on one charge,
- is readable and reachable while worn (glove, belt, cap),
- survives being dropped and rained on.

The pitcher pod is the size test: one board, one button, one cell, no display. If it is not small enough, nothing else will be.

## Build order

1. **Prove LE Audio on the nRF54L15.** Code complete: `roles/audio-proof.conf` + `roles/audio-unit.conf` build the BAP unicast client / LC3 source in `firmware/src/audio_source.c`; the proof plays one spoken call to one JY300. Procedure and pass criteria: `dev/le-audio-proof.md`, `dev/test-checklist.md` phase 1. Awaiting hardware.

2. **Port the call engine with an 802.15.4 transport.** Done: the portable engine is in `firmware/include/pc/`, the Thread transport is `firmware/src/thread_link.c`, and the hook mapping is in `firmware/src/main.cpp`. Host tests cover protocol, handshake, call, ACK, retry, expiry, requests, clock wrap, lossy and reordered links, multi-node fairness and protocol fuzzing: 3348 checks, 0 failures. On-hardware validation is checklist phase 2.

3. **Run both links on one board.** Code integrated for catcher and pitcher (Thread SED + LE Audio + OLED/buttons on one nRF54L15). The radio coexistence question is checklist phase 3; this is the top remaining risk.

4. **Build the pitcher pod first, then catcher, then fielders.** The STLs ship in `cad/unbranded/exports/`; the generator and profiles are maintainer tools in `dev/cad/`. Pitcher sets the size bar. Print the coupon, then the pitcher shell, then the rest.

5. **Port the coach GUI.** Done: `gui/` keeps the V1 protocol (`@PC`, v4) and the coach firmware implements the same console commands. Connect over the coach's USB serial; no GUI protocol change.

6. **Field test.** Checklist phase 5: latency, range, runtime, fit, drop survival.

## State of the build

Everything short of hardware observation is written: firmware for every enrolled unit, host tests, coach GUI, provisioning and audio tooling, case CAD, and user docs. No firmware has been flashed, no range/latency/runtime numbers exist, and no phrase in any document should be read as a measurement. `dev/test-checklist.md` is the loop from here: flash, observe, record, fix.

## Open questions

Hardware-only items stay here; everything resolvable without a board is in `dev/verification.md` with its evidence.

- **Concurrent LE Audio + 802.15.4.** One 2.4 GHz transceiver. How much does the audio stream degrade call-link timing, and vice versa? Phase 3 answers it. Top remaining risk.
- **LE Audio wake-up latency and idle strategy.** The source keeps the ISO stream alive and sends silence between calls; measure battery cost vs restart latency (phase 1/3).
- **JY300 codec preset.** The proof prefers 16 kHz and falls back through advertised PAC records to 48 kHz; the stream context is one line away from `MEDIA`. Confirm on hardware (phase 1).
- **App size in the 712 KB MCUboot slot.** The build script now measures and guards the image; `-MinSize` and a no-MCUboot recipe are prepared in `dev/build.md`. Measurement needs the toolchain.
- **Smallest cell that lasts a game.** Start at 500 mAh for display units and 850 mAh for the pitcher, then shrink (phase 5).
- **SED battery vs call latency.** 200 ms poll is the starting point; measure a full game (phase 3/5).
- **Thread channel at the field.** 11-26, default 15; pick a channel clear of local Wi-Fi (phase 2).
- **One enclosure per unit type, or shared?** Decided: three (pitcher, catcher, fielder). The fielder is one pod with a wrist carrier and a belt carrier; mounting options and protection notes are in `dev/case-design.md`. The fit coupon confirms before a full set.
- **Factory EUI stability.** `eui` reads the chip id until the team file is provisioned; confirm the value is stable and unique per board on hardware (phase 2/provisioning).
