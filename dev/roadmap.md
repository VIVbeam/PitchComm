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

2. **Port the call engine with an 802.15.4 transport.** Done: the portable engine is in `firmware/include/pc/`, the Thread transport is `firmware/src/thread_link.c`, and the hook mapping is in `firmware/src/main.cpp`. Host tests cover protocol, handshake, call, ACK, retry, expiry, and requests: `127 checks, 0 failures`. On-hardware validation is checklist phase 2.

3. **Run both links on one board.** Code integrated for catcher and pitcher (Thread SED + LE Audio + OLED/buttons on one nRF54L15). The radio coexistence question is checklist phase 3; this is the top remaining risk.

4. **Build the pitcher pod first, then catcher, then fielders.** V2 case sources are under `cad/unbranded/` with a parametric generator and a fit coupon. Pitcher sets the size bar. Print the coupon, then the pitcher shell, then the rest.

5. **Port the coach GUI.** Done: `gui/` keeps the V1 protocol (`@PC`, v4) and the coach firmware implements the same console commands. Connect over the coach's USB serial; no GUI protocol change.

6. **Field test.** Checklist phase 5: latency, range, runtime, fit, drop survival.

## State of the build

Everything short of hardware observation is written: firmware for all five roles, host tests, coach GUI, provisioning and audio tooling, case CAD, and user docs. No firmware has been flashed, no range/latency/runtime numbers exist, and no phrase in any document should be read as a measurement. `dev/test-checklist.md` is the loop from here: flash, observe, record, fix.

## Open questions

- **Concurrent LE Audio + 802.15.4.** One 2.4 GHz transceiver. How much does the audio stream degrade call-link timing, and vice versa? Phase 3 answers it.
- **LE Audio wake-up latency and idle strategy.** The source keeps the ISO stream alive and sends silence between calls; measure battery cost vs restart latency.
- **JY300 codec preset.** The proof prefers 16 kHz and falls back through advertised PAC records to 48 kHz. Confirm which preset the JY300 accepts and whether one earbud of the pair can be targeted without TWS clock sync.
- **App size in the 712 KB MCUboot slot.** BT host + LC3 + 802.15.4 + app may be tight; trim logging/buffers or build without MCUboot if it overflows.
- **Smallest cell that lasts a game.** Start at 500 mAh for display units and 850 mAh for audio units, then shrink.
- **SED battery vs call latency.** 200 ms poll is the starting point; measure a full game.
- **Thread channel at the field.** 11-26, default 15; pick a channel clear of local Wi-Fi.
- **One enclosure per unit type, or shared?** Decided: three (pitcher, catcher, fielder). The fielder is one pod with a wrist carrier and a belt carrier; rationale and sight lines are in `dev/case-design.md`. The fit coupon confirms before a full set.
