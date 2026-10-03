# Verification register

Every `VERIFY:` marker in the sources, where it was resolved, and what still needs a compiler or hardware. "Source" means the name/behavior was checked against NCS v3.4.0 or Zephyr sources; no toolchain was available to compile.

Status key: **closed** (no further action), **build** (first toolchain contact), **bench** (first hardware contact), **field** (game conditions).

## Firmware API and Kconfig

| Item | Where | Status | Proof / next check |
|---|---|---|---|
| OpenThread instance accessor | `thread_link.c` | closed | NCS v3.4.0 uses `openthread_get_default_instance()` via `<zephyr/net/openthread.h>`; `otGetInstance()` does not exist. |
| Security policy is a bitfield struct | `thread_link.c` | closed | `otSecurityPolicy` has no `mFlags`; default flags (obtain/native/router/external/ToBLE, routers enabled) are set so the coach can lead. |
| Dataset component flags | `thread_link.c` | closed | `mComponents.mIs*Present` set; without them the dataset would save empty. |
| Socket types without `CONFIG_POSIX_API` | `thread_link.c` | closed | `net_sockaddr_in6`, `NET_AF_INET6`, `NET_SOCK_DGRAM`, `ZSOCK_MSG_DONTWAIT` used. |
| `CONFIG_NET_SOCKETS_POSIX_NAMES` removed | role confs | closed | Not set; firmware calls `zsock_*` directly. |
| `CONFIG_SETTINGS_ZMS` depends on ZMS + FLASH_MAP | role confs | closed | `CONFIG_ZMS=y`, `CONFIG_FLASH_MAP=y` set beside it. |
| `CONFIG_CONSOLE_GETLINE` for `console_getline()` | `prj.conf` | closed | Optional choice set; `console_getline_init()` called in `main()`. |
| `settings_load_one()` exists and returns a length | `main.cpp` | closed | Zephyr settings header declares it and returns `ssize_t`; code checks `== sizeof(value)`. |
| Missing `otGetInstance()` fallback (factory EUI) | `thread_link.c` | build + bench | `CONFIG_HWINFO=y`; `HWINFO_NRF` defaults y because `NRF_SOC_SECURE_SUPPORTED` is true on the non-TF-M cpuapp build. Bench: `eui` prints a stable, unique, nonzero 16-hex value on a fresh board. |
| `BT_LL_SOFTDEVICE` is the nRF54L controller | `audio-unit.conf` | closed | Default y for the nRF54L series; set explicitly. |
| `fs_mount_t.storage_dev` holds the partition id | `storage.c` | closed | Zephyr `fs_mount_t` has `void *storage_dev`; `FIXED_PARTITION_ID(slot1_partition)` is the documented cast. |
| liblc3 encoder API | `audio_source.c` | closed | `lc3_setup_encoder`, `lc3_encode`, `LC3_PCM_FORMAT_S16`, and `lc3_encoder_mem_48k_t` confirmed in the upstream header. |
| Stream context `UNSPECIFIED` vs `MEDIA` | `audio_source.c` | bench | One-line switch documented at `PC_STREAM_CONTEXT`; change if the JY300 rejects metadata. |
| Startup vref is 900 mV | `battery.cpp` | bench | Compare `status` battery against a meter; fallback 900 is coded. |
| `ADC_CONFIGURABLE_INPUTS` and AIN7 | `battery.cpp` | build | `ADC_NRFX_SAADC` selects it; `NRF_SAADC_AIN7` used. |
| P1.15 divider enable | `battery.cpp` | bench | Board DTS `vbat_pwr` is active high and boot-on; code leaves it on. |
| SSD1306 binding properties and 128x32 | overlay | closed (source), bench | Upstream binding marks width/height/segment-remap/com-invdir/com-sequential/prechargep required; all set. Bench: panel probes at 0x3C and refreshes. |
| C++ standard selection | `Kconfig`/`CMakeLists.txt` | closed | `CONFIG_STD_CPP17=y` owns the standard; the redundant CMake override was removed. |
| `CONFIG_PITCHCOMM_*` symbol coverage | all sources | closed | Static audit: every `CONFIG_PITCHCOMM_*` reference is defined in `Kconfig` or a role conf; no zero-length array declarations. |

## Toolchain and image

| Item | Status | Next check |
|---|---|---|
| NCS version pin | closed | `firmware/ncs_version.txt` = `v3.4.0`; `preflight.py` validates the shape and `build_firmware.ps1` compares `-NcsVersion`. |
| Bench self-test | closed (code) | `selftest` console command prints PASS/FAIL/SKIP for OLED, controls, battery, storage, audio, settings; run after each flash (checklist phases 2 and 4). |
| App image fits the 712 KB MCUboot slot | build | `build_firmware.ps1` reports `IMAGE <unit>: bytes / 729088`; `-StrictSize` fails an overflow; `-MinSize` applies `roles/min-size.conf`. Fallback recipe in `dev/build.md`. |
| No-MCUboot full-flash fallback | build | `boards/no_bootloader.overlay` + `boards/no_bootloader.conf` + `-DSB_CONFIG_BOOTLOADER_MCUBOOT=n`; the image links at `0x0` with a 794624-byte limit, `slot1` stays the audio filesystem at `0xC2000`, and `storage` stays settings. Verify the overlay merges, `.config` has `CONFIG_USE_DT_CODE_PARTITION=y`, and the map ends before `0xC2000`. |
| MCUboot sysbuild and `slot1` use | build | Confirm sysbuild builds MCUboot and that mounting LittleFS on `slot1` is safe with the chosen swap algorithm. |

## Audio behavior

| Item | Status | Next check |
|---|---|---|
| Streaming playback memory bound | closed | ~3.3 KB fixed buffers, independent of clip length; no per-call large allocation. |
| Multi-clip call assembly | closed | Opening each clip resets the resampler position and EOF, so the pitch type and location clips both play; covered by the 146-check audio suite. |
| Per-unit audio routing and budget | closed (tools), bench | `config/roster.json` decides which units get clips; the default 37-clip compact set is 236,550 of 729,088 bytes and PCM over-budget is refused with shrink guidance. Bench: earbud playback per audio unit, checklist phases 1 and 3. |
| LC3 preset accepted by the JY300 | bench | Proof phase 1: logged preset; fall back to 48 kHz if configuration stalls. |
| One earbud, mono, no TWS | bench | Confirm one sink ASE streams on the JY300 and no TWS pairing is attempted. |
| Idle stream vs restart | bench | Compare battery and first-word latency with the silence keep-alive. |

## Call link

| Item | Status | Next check |
|---|---|---|
| Handshake, call, ACK, retry, expiry | bench | Checklist phase 2; host simulation already passes (3348 checks, 0 failures, including lossy and reordered links). |
| Per-play audiences | closed (host), bench | Plays route to the enrolled audience their targets resolve to; generator, engine deliveries and the desk SEND TO are covered by host, fixture and GUI tests. Bench: phase 4 sends a play and checks exactly the audience reacts. |
| Mesh relay coverage | closed (source), bench | Units build as Full Thread Device relays by default; `relay: false` builds a Sleepy End Device. The dry run and build-plan checks pin both fragments. Bench: phase 2 compares a sleepy unit against the relay baseline, phase 3 repeats it with pitcher audio. |
| Concurrent LE Audio + 802.15.4 | field | Checklist phase 3; top remaining risk. |
| SED poll period vs runtime | field | Checklist phase 3/5; 200 ms starting point. |
| Channel choice at the field | field | Provision a channel clear of local Wi-Fi; 11-26, default 15. |

## Case and tooling

| Item | Status | Next check |
|---|---|---|
| Case geometry, fit, wear angles | bench | Fit coupon, calipers, one body/lid wear test; rationale in `dev/case-design.md`. |
| Drop and rain survival | field | Checklist phase 5. |
| Catalog, audio, provisioning, LittleFS image | closed | All runnable tools pass on this machine (dictionary 299314f6, 37 clips, valid Intel HEX). |
| Roster enrollment and variable counts | closed (tools), bench | Roster-driven generator, provisioning, audio plan and a host compile against a variant roster; bench: enroll one extra unit and observe the desk and audiences follow. |
| One-game power budget | estimate, bench | About 18 mA worst unit (relay plus OLED), about 54 mAh per three-hour game; 150 mAh cells estimate 2.8x margin before derating (`dev/power.md`). Bench: average current per build in phases 3 and 5. |
