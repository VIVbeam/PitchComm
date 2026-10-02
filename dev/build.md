# PitchComm firmware build notes

Internal build/design notes for the Zephyr / nRF Connect SDK (NCS) application. The user-facing flash and use guide is `firmware/README.md`.

## Toolchain

- NCS v3.4.0 LTS with the ARM toolchain, `west`, and `nrfutil` on `PATH`.
- Board target: `xiao_nrf54l15/nrf54l15/cpuapp`.
- Console: the XIAO debugger's USB serial at 115200 (board UART20, P1.8/P1.9).
- Host tests need only `g++`/`clang++`; they do not need NCS.
- `firmware/ncs_version.txt` pins `v3.4.0`. `tools/build_firmware.ps1 -NcsVersion v3.4.0` launches that toolchain through `nrfutil sdk-manager`; the value must match the pin unless `-AllowVersionMismatch` is passed.
- First contact: `python tools/preflight.py`, then one `west build` below. Nothing in this tree has been through a compiler.

## Application layout

- `firmware/src/main.cpp`: role selection, hooks, engine thread, console, UI loop.
- `firmware/src/thread_link.c`: OpenThread + UDP transport.
- `firmware/src/audio_source.c`, `storage.c`: LE Audio unicast source and LittleFS clips.
- `firmware/src/display.cpp`, `buttons.cpp`, `battery.cpp`: board drivers.
- `firmware/include/pc/`: portable engine, protocol, catalog, controls, USB gate (do not edit `catalog.h` by hand).
- `firmware/include/app/`: transport/audio/storage contracts and team credentials.
- `firmware/include/board/`: driver interfaces.
- `firmware/roles/`: Kconfig fragments per role.
- `firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay`: OLED, ADC channel, display choice.
- `firmware/boards/no_bootloader.overlay`, `firmware/boards/no_bootloader.conf`: untested no-MCUboot layout; see "No-MCUboot fallback (VERIFY)".

## Roles and fragments

`west build` takes a semicolon-separated `EXTRA_CONF_FILE` list. `tools/build_firmware.ps1` wraps this:

| Role | Fragments |
|---|---|
| Coach | `roles/coach.conf` |
| Catcher | `roles/catcher.conf;roles/field-common.conf` |
| Pitcher | `roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf` |
| Shortstop | `roles/shortstop.conf;roles/field-common.conf` |
| Center field | `roles/centerfield.conf;roles/field-common.conf` |
| LE Audio proof | `roles/audio-proof.conf;roles/audio-unit.conf` |

Each role conf sets `CONFIG_PITCHCOMM_ROLE_*`. The application `Kconfig` derives `CONFIG_PITCHCOMM_AUDIO`, `CONFIG_PITCHCOMM_DISPLAY`, `CONFIG_PITCHCOMM_CATCHER_MENU`, `CONFIG_PITCHCOMM_FIELD_BUTTON`, and `CONFIG_PITCHCOMM_BATTERY` from the role; `CONFIG_PITCHCOMM_CONSOLE` defaults to y for every role. Only the pitcher and the proof pass `roles/audio-unit.conf`; the catcher sets `CONFIG_PITCHCOMM_AUDIO=n` and passes no audio fragment.

Raw equivalent for one role:

```powershell
west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/pitcher -- `
  -DEXTRA_CONF_FILE="roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf"
west flash -d firmware/build/pitcher
```

The proof role is not in the script's default list; build it with `tools\build_firmware.ps1 -Units proof` or the raw form with `roles/audio-proof.conf;roles/audio-unit.conf`.

## Provisioning

```powershell
python tools\provision.py --coach EUI1 --unit pitcher=EUI2 --unit catcher=EUI3 `
  --unit shortstop=EUI4 --unit center=EUI5 --channel 15
```

Enrolled units come from `config/roster.json`; add a position there and provision its EUI to grow the team.

Read each board's EUI-64 with the `eui` console command (or `status`) before provisioning. This writes `config/team.local.json` and `firmware/include/app/team_config.h`. Both are git-ignored; keep the JSON. Rebuild all enrolled units after provisioning. `--from-file` regenerates the header from saved values.

## Audio filesystem and flash budget

- App slot (`slot0_partition`): 712 KB with MCUboot. `tools/build_firmware.ps1` prints the measured `text+data` size after each build and warns over the limit; `-StrictSize` makes that fatal. If the image overflows, see "No-MCUboot fallback (VERIFY)".
- Audio slot (`slot1_partition`, the unused MCUboot update slot): 712 KB at offset `0x0C2000`, mounted as LittleFS by `storage.c`. This is not an OTA slot in PitchComm; firmware updates are done over USB.
- Storage partition: 36 KB at offset `0x174000` for settings and Bluetooth bonds.
- The no-MCUboot fallback below keeps both offsets; only the application area changes.
- `tools/build_audio_fs.py` packs the calls (compact 8 kHz mu-law by default, `--pcm` for 16 kHz WAV) into `firmware/build/audio/littlefs.img` and `.hex`; `tools/flash_audio.ps1` writes it once to the pitcher.

The compact pack is about 0.17 MB; the PCM pack is about 0.66 MB. Prefer compact unless speech quality requires the WAV set.

Playback is streamed, not buffered: one clip is open at a time and one LC3 frame is assembled at a time. The audio path's fixed buffers total about 3.3 KB (512-sample source window, 480-sample LC3 frame, silence keep-alive, one clip handle), independent of clip length and negotiated sample rate.

## Host tests

```powershell
powershell -NoProfile -File firmware\tests\run_host_tests.ps1
```

Covers protocol round-trip, handshake, call/ACK, duplicate suppression, output errors, catcher requests, expiry, USB gate/parse, catcher menu, button filtering, strip priority.

Run the whole host suite in one pass with `powershell -NoProfile -File tools\verify_all.ps1` (preflight --audio, host and audio suites, GUI tests, tool tests, the full host compile, repo audit); `-Quick` skips the host compile and toolchain check, and the toolchain check is informational when it runs.

## Cases (maintainer)

The product tree `cad/unbranded/` holds the printable STLs, color files, 3MFs, previews, and the fit coupon. The parametric sources are internal:

```powershell
python dev/cad/generate_cases.py            # rebuild STLs, previews, dev/cad/dimensions.json
python dev/cad/generate_cases.py --only keypad
python dev/cad/generate_cases.py --no-preview
```

`dev/cad/profiles.json` is the dimension source; edit it, not the generated STLs. The 3MF files and `palette.json` name the family colors.

## Build checks on first toolchain contact (no hardware needed)

The full item-by-item register is `dev/verification.md`. The short list:

1. `west build` for each role; the build script reports `IMAGE <role>: bytes / 729088`.
2. Check that every remaining `VERIFY:` comment is either confirmed or corrected (search `VERIFY:`); most API/Kconfig items are already source-verified.
3. Confirm the `solomon,ssd1306` binding accepts 128x32 and the overlay pinctrl matches `i2c22`.
4. Confirm `BT_LL_SOFTDEVICE` vs the nRF54L15 controller selection and that BT + 802.15.4 link without a coexistence option.
5. Confirm MCUboot is built by sysbuild and `slot1` is not needed by the bootloader configuration in use.
6. Check the no-MCUboot fallback below once the normal build passes.

## No-MCUboot fallback (VERIFY)

Untested; nothing here has been through a compiler. Use it when an image overflows the 712 KB MCUboot slot and `roles/min-size.conf` is not enough. It removes MCUboot and gives the application the 62 KB boot area plus the 712 KB slot0.

- `firmware/boards/no_bootloader.overlay` deletes `boot_partition` and `slot0_partition` and defines one `slot0_partition` at `0x0`, 776 KB. `slot1_partition` (LittleFS, 712 KB) and `storage_partition` (36 KB) keep their MCUboot offsets, so an already written audio image and saved bonds stay valid.
- `firmware/boards/no_bootloader.conf` sets `CONFIG_USE_DT_CODE_PARTITION=y`. MCUboot selects that symbol; without it the application would link from `0x0` over the whole 1524 KB RRAM and overlap its own LittleFS and settings areas.

Build and flash (pitcher shown):

```powershell
west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/pitcher-nb -- `
  -DSB_CONFIG_BOOTLOADER_MCUBOOT=n `
  -DEXTRA_DTC_OVERLAY_FILE=boards/no_bootloader.overlay `
  -DEXTRA_CONF_FILE="roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf;boards/no_bootloader.conf"
west flash -d firmware/build/pitcher-nb --erase
```

| Region | Offset | Size | Use |
|---|---|---|---|
| `slot0_partition` | `0x000000` | 776 KB | application (limit 794624 bytes) |
| `slot1_partition` | `0x0C2000` | 712 KB | LittleFS audio clips |
| `storage_partition` | `0x174000` | 36 KB | settings + Bluetooth bonds |

`--erase` wipes the audio filesystem and the saved bonds; rerun `tools\flash_audio.ps1` for the pitcher. Going back to the normal MCUboot build also needs `--erase`.

Caveats:

- `tools/build_firmware.ps1` has no fallback flag and always measures against the 729088-byte MCUboot slot; use the raw west command and check the map against 794624 bytes.
- `tools/flash_firmware.ps1` only accepts `firmware/build/<role>` paths, so flash this build with `west flash -d firmware/build/pitcher-nb` or name the build directory after the role.
- There is no bootloader and no revert: a bad image has to be recovered over the XIAO debugger, and the normal USB update path does not apply.

VERIFY (all of it): the overlay merges without a DTC error; `.config` shows `CONFIG_USE_DT_CODE_PARTITION=y` and `CONFIG_FLASH_USES_MAPPED_PARTITION=y`; the map starts at `0x0`, is at most 794624 bytes, and has no section past `0x0C2000`; LittleFS mounts `slot1`; settings mount `storage`; the erased board boots and enumerates on USB.

## If the app does not fit

1. Rebuild with `tools\build_firmware.ps1 -MinSize`; `roles/min-size.conf` disables logs/asserts, drops OpenThread debug, and cuts message buffers to 32.
2. Drop map-consuming options in the role confs: `CONFIG_OPENTHREAD_DEBUG=n`, smaller `CONFIG_BT_RX_STACK_SIZE`, `CONFIG_LOG=n`.
3. If it still does not fit, use the no-MCUboot fallback above (VERIFY).
4. If only the audio filesystem is over, rebuild it with `tools\build_audio_fs.py` (compact mu-law) and keep the app image lean.

Nothing here has been measured; the first `west build` is the measurement.

## Firmware-wide open items

The remaining hardware-dependent questions and their test phases are tracked in `dev/verification.md` and `dev/test-checklist.md`; the top one is concurrent LE Audio + Thread on the shared 2.4 GHz radio.
