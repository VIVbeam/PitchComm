# PitchComm firmware build notes

Internal build/design notes for the Zephyr / nRF Connect SDK (NCS) application. The user-facing flash and use guide is `firmware/README.md`.

## Toolchain

- NCS v3.4.0 LTS with the ARM toolchain, `west`, and `nrfutil` on `PATH`.
- Board target: `xiao_nrf54l15/nrf54l15/cpuapp`.
- Console: the XIAO debugger's USB serial at 115200 (board UART20, P1.8/P1.9).
- Host tests need only `g++`/`clang++`; they do not need NCS.

## Application layout

- `firmware/src/main.cpp` — role selection, hooks, engine thread, console, UI loop.
- `firmware/src/thread_link.c` — OpenThread + UDP transport.
- `firmware/src/audio_source.c`, `storage.c` — LE Audio unicast source and LittleFS clips.
- `firmware/src/display.cpp`, `buttons.cpp`, `battery.cpp` — board drivers.
- `firmware/include/pc/` — portable engine, protocol, catalog, controls, USB gate (do not edit `catalog.h` by hand).
- `firmware/include/app/` — transport/audio/storage contracts and team credentials.
- `firmware/include/board/` — driver interfaces.
- `firmware/roles/` — Kconfig fragments per role.
- `firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay` — OLED, ADC channel, display choice.

## Roles and fragments

`west build` takes a semicolon-separated `EXTRA_CONF_FILE` list. `tools/build_firmware.ps1` wraps this:

| Role | Fragments |
|---|---|
| Coach | `roles/coach.conf` |
| Catcher | `roles/catcher.conf;roles/field-common.conf;roles/audio-unit.conf` |
| Pitcher | `roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf` |
| Shortstop | `roles/shortstop.conf;roles/field-common.conf` |
| Center field | `roles/centerfield.conf;roles/field-common.conf` |
| LE Audio proof | `roles/audio-proof.conf;roles/audio-unit.conf` |

Each role conf sets `CONFIG_PITCHCOMM_ROLE_*`. The application `Kconfig` derives `CONFIG_PITCHCOMM_AUDIO`, `CONFIG_PITCHCOMM_DISPLAY`, `CONFIG_PITCHCOMM_CATCHER_MENU`, `CONFIG_PITCHCOMM_FIELD_BUTTON`, `CONFIG_PITCHCOMM_BATTERY`, and `CONFIG_PITCHCOMM_CONSOLE` from the role.

Raw equivalent for one role:

```powershell
west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/pitcher -- `
  -DEXTRA_CONF_FILE="roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf"
west flash -d firmware/build/pitcher
```

## Provisioning

```powershell
python tools\provision.py --coach EUI --catcher EUI --pitcher EUI `
  --shortstop EUI --centerfield EUI --channel 15
```

Read each board's EUI-64 with the `eui` console command (or `status`) before provisioning. This writes `config/team.local.json` and `firmware/include/app/team_config.h`. Both are git-ignored; keep the JSON. Rebuild all five roles after provisioning. `--from-file` regenerates the header from saved values.

## Audio filesystem and flash budget

- App slot (`slot0_partition`): 712 KB with MCUboot. The BT host + LE Audio + 802.15.4 stack is expected to be tight; if it overflows, see the open items below.
- Audio slot (`slot1_partition`, the unused MCUboot update slot): 712 KB, mounted as LittleFS by `storage.c`. This is not an OTA slot in PitchComm; firmware updates are done over USB.
- Storage partition: 36 KB for settings and Bluetooth bonds.
- `tools/build_audio_fs.py` packs the calls (compact 8 kHz mu-law by default, `--pcm` for 16 kHz WAV) into `firmware/build/audio/littlefs.img` and `.hex`; `tools/flash_audio.ps1` writes it once per audio unit.

The compact pack is about 0.17 MB; the PCM pack is about 0.66 MB. Prefer compact unless speech quality requires the WAV set.

Playback is streamed, not buffered: one clip is open at a time and one LC3 frame
is assembled at a time. The audio path's fixed buffers total about 3.3 KB
(512-sample source window, 480-sample LC3 frame, silence keep-alive, one clip
handle), independent of clip length and negotiated sample rate.

## Host tests

```powershell
powershell -NoProfile -File firmware\tests\run_host_tests.ps1
```

Covers protocol round-trip, handshake, call/ACK, duplicate suppression, output errors, catcher requests, expiry, USB gate/parse, catcher menu, button filtering, strip priority.

## Build checks on first toolchain contact (no hardware needed)

1. `west build` for each role; record the image size against the 712 KB slot.
2. Check that every `VERIFY:` comment in the sources is either confirmed or corrected (search `VERIFY:`).
3. Confirm the `solomon,ssd1306` binding accepts 128x32 and the overlay pinctrl matches `i2c22`.
4. Confirm OpenThread device-type and poll-period symbol names for NCS v3.4.0.
5. Confirm `BT_LL_SOFTDEVICE` vs the nRF54L15 controller selection and that BT + 802.15.4 link without a coexistence option.
6. Confirm MCUboot is built by sysbuild and `slot1` is not needed by the bootloader configuration in use.

## Firmware-wide open items

- App size vs the 712 KB MCUboot slot: trim logging, OpenThread buffers, or switch off MCUboot if it does not fit.
- Concurrent LE Audio + Thread on the shared 2.4 GHz radio is unmeasured; `dev/roadmap.md` keeps it as the top field question.
- SED poll period 200 ms trades call latency for battery; measure against a full game.
- The JY300 may require 48 kHz; `audio_source.c` prefers 16 kHz and falls back through the advertised PAC records.
