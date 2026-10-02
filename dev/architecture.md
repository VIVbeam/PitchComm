# PitchComm architecture

Each field unit is a single Seeed XIAO nRF54L15. One chip runs the call link and the audio link.

## Single-chip design

Each field unit is one nRF54L15 (21 x 17.8 mm). The chip has a 2.4 GHz radio that runs Bluetooth 6.0 LE with LE Audio and IEEE 802.15.4. Two protocol stacks share that radio: 802.15.4 for calls and control, LE Audio for the spoken call. The board does four jobs:

- 802.15.4 peer and call engine.
- LE Audio source to the player's earbud (pitcher, catcher).
- OLED and button UI (catcher, shortstop, center field).
- Battery sense and USB diagnostics.

The coach is the exception: an nRF54L15 on the laptop's USB, with no battery and no audio.

## The two radio links

There is one RF front-end. Two stacks use it, and they do not share application code.

| Link | Protocol | Carries | Endpoints | Timing |
|---|---|---|---|---|
| Call link | 802.15.4 (Thread) | 56-byte packets: call trigger, ACK, sync, heartbeat | Coach to/from field units | A few ms target |
| Audio link | LE Audio (LC3) | LC3-encoded spoken call | Field unit to earbud | Isochronous, bounded |

The call link is the portable call engine, running on a closed Thread network. The coach is the leader; field units are Sleepy End Devices. The catcher can also originate a pitch request, which the coach relays. The 56-byte format carries kind, source, target, category, code, sequence, session, boot, clock, deadline, and TTL.

The audio link reads the call clips, decodes them to PCM, encodes LC3, and streams over an isochronous channel to one earbud. Headphones are the HomeSpot JY300 neckband (LC3 / LE Audio).

## Per-unit hardware

| Unit | Board | Controls | Display | Audio out | Power |
|---|---|---|---|---|---|
| Coach | XIAO nRF54L15 | Laptop over USB | Laptop | None | USB |
| Catcher | XIAO nRF54L15 | Four numbered buttons, Back | 128 x 32 OLED | LE Audio earbud | 850 mAh cell |
| Pitcher | XIAO nRF54L15 | Recall / volume button | None | LE Audio earbud | 850 mAh cell |
| Shortstop / center field | XIAO nRF54L15 | Recall button | 128 x 32 OLED | None | 500 mAh cell |

The vocabulary is 9 pitch types x 3 heights x 3 sides, so 81 pitch calls, plus 9 defensive plays. Firmware joins three clips per pitch call.

## Firmware framework

Firmware is Zephyr on the nRF Connect SDK (C, with the portable engine in C++). Each unit is a per-role build from shared modules.

| Layer | Choice |
|---|---|
| Call link | 802.15.4 radio, OpenThread, Zephyr UDP sockets |
| Audio link | Zephyr LE Audio: BAP unicast source, LC3 encoder, PACS/ASCS |
| BLE host | Zephyr Bluetooth host |
| Radio coexistence | nRF54L15 radio scheduler (unmeasured) |
| Runtime | Zephyr threads: engine, radio, console, UI/main, audio |
| Storage | LittleFS on the unused MCUboot update slot for clips; settings partition for bonds/volume |

The call engine is portable C++ with a `Hooks` interface. `send` maps to the 802.15.4 stack; `present` maps to the LE Audio source or the OLED. The build selects the hook per role, so the same engine runs on every unit.

## Flash and memory (target hardware)

The nRF54L15 has 1.5 MB of RRAM and 188 KB of usable RAM on this board. With the MCUboot layout the board ships:

| Area | Size | Use |
|---|---|---|
| `boot_partition` | 62 KB | MCUboot |
| `slot0_partition` | 712 KB | application image |
| `slot1_partition` | 712 KB | unused update slot; mounted as the audio filesystem |
| `storage_partition` | 36 KB | Zephyr settings (volume, Bluetooth bonds) |

The compact audio pack is about 0.17 MB (8 kHz G.711 mu-law, 15 clips); the 16 kHz PCM pack is about 0.66 MB. Tight app size is a tracked risk; see `dev/build.md`.

## Code map

- `firmware/src/main.cpp` — role app, hooks, engine thread, console, UI loop.
- `firmware/src/thread_link.c` — OpenThread + UDP.
- `firmware/src/audio_source.c` — BAP unicast client and LC3 encode/playback.
- `firmware/src/storage.c` — LittleFS clip reader.
- `firmware/src/display.cpp`, `buttons.cpp`, `battery.cpp` — board drivers.
- `firmware/include/pc/` — portable engine/protocol/catalog/controls.
- `firmware/include/app/` — transport, audio, storage contracts; team credentials.
- `firmware/include/board/` — driver interfaces.
- `firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay` — OLED, ADC, display choice.
- `firmware/roles/` — per-role Kconfig fragments.
- `firmware/tests/` — host tests for the portable core.
