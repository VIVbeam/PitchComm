# LE Audio proof on XIAO nRF54L15: runbook

Goal: build the PitchComm LE Audio source (`roles/audio-proof.conf`), flash it
to a XIAO nRF54L15 (`xiao_nrf54l15/nrf54l15/cpuapp`), and play one spoken call
to one HomeSpot JY300 earbud. This is the riskiest unknown; finish it before
any call-link work. Nothing here has been verified on hardware yet.

## Platform caveat: read first

Nordic's official LE Audio platform is nRF5340 (nRF5340 Audio DK). nRF54L has
no Audio PLL, which synchronizes two independent L/R receivers, so it cannot do
TWS (both earbuds); Nordic calls it "limited support for Audio samples".
Point-to-point mono may work. The nRF54L15 SoftDevice Controller does implement
isochronous channels (CIS/BIS).

- The Zephyr `bap_unicast_client` sample ships a simulated `nrf54l15bsim` config
  but no real nRF54L15 board config. The real-XIAO build is plausible but
  unvalidated.
- Headphones: HomeSpot JY300 neckband (LC3 / LE Audio, advertises ASCS).
- Safe order: prove the sample on an nRF5340 Audio DK first, then the XIAO. If
  unstable, change the field-unit SoC (nRF5340/nRF54H20).

## 1. Install NCS v3.4.0 LTS

VS Code + nRF Connect is recommended; command line below.

```bat
:: Windows: download nrfutil.exe, put it on PATH, then:
nrfutil install sdk-manager
nrfutil sdk-manager search             :: lists installable NCS versions
nrfutil sdk-manager install v3.4.0     :: first LTS (Jul 2026)
nrfutil sdk-manager toolchain launch --ncs-version v3.4.0 --terminal
```

Plain west workspace instead: `west init -m
https://github.com/nrfconnect/sdk-nrf --mr v3.4.0 ncs\v3.4.0`, then
`west update && west zephyr-export`.

NCS version, sample path and log text are version-dependent; re-check.

## 2. Confirm the board target

```bat
west boards | findstr xiao
:: expect: xiao_nrf54l15/nrf54l15/cpuapp
```

NCS v3.4.0 includes it at `zephyr/boards/seeed/xiao_nrf54l15/`. If missing, add
Seeed's board repo `zephyr` folder as a board root, or copy it into the tree.

## 3. Build the proof role

The proof role is the PitchComm BAP unicast client (`src/audio_source.c`)
without the Thread link. It plays `/audio/p01.wav` + `/audio/l1.wav`
(FOUR-SEAM FASTBALL / HIGH INSIDE) once an earbud stream is running.

```bat
west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/proof -- -DEXTRA_CONF_FILE="roles/audio-proof.conf;roles/audio-unit.conf"
```

`tools/build_firmware.ps1 -Units proof` wraps this. If the board config has no
nRF54L15 LE Audio config, `roles/audio-unit.conf` supplies `CONFIG_LIBLC3=y`,
`CONFIG_FPU=y`, and the BT buffer sizes. No devicetree overlay is needed for
audio; the board DTS already enables the radio and IEEE 802.15.4 nodes.

## 4. Flash the proof and the audio filesystem

```bat
powershell -NoProfile -File tools\build_audio_fs.py
powershell -NoProfile -File tools\flash_firmware.ps1 -Role proof -Erase
powershell -NoProfile -File tools\flash_audio.ps1
```

Console: XIAO USB CDC ACM port at 115200. Flashing uses OpenOCD over the XIAO
on-board SAMD11 CMSIS-DAP (`choco install openocd` if missing) or
`west flash --runner jlink` / `nrfutil device program`.

If the audio filesystem has not been written yet, the source still keeps the
ISO stream alive with LC3-encoded silence, so the link can be observed in the
logs; the spoken call itself requires the filesystem from step 4.

## 5. Pair the JY300

1. Unpair the neckband from any phone, put it in pairing mode.
2. Power the board; watch for the scan and connection lines.
3. If discovery/configuration stalls, the earbud likely rejects the preferred
   16 kHz preset. The source walks the sink's advertised PAC records and falls
   back toward 48 kHz/10 ms; if it still stalls, force the 48 kHz preset in
   `firmware/src/audio_source.c` and rebuild.
4. TWS is the case nRF54L15 cannot clock-sync; expect at best one earbud /
   mono. Configure exactly one sink stream (the firmware does).

## 6. What success looks like

ACL "Connected" is not audio; real audio needs the QoS/stream lines. Expected
sequence (message text is approximate):

```
audio: Bluetooth ready
audio: scanning
audio: Audio server found ... connecting
audio: Connected ...
audio: Sinks discovered
audio: Configured sink stream
audio: Unicast group created
audio: QoS set with CIG_ID ... CIS_ID ...
audio: Stream enabled
audio: Stream connected
audio: Stream started
audio: playing call
audio: call complete
```

Pass criteria and the record table are in `dev/test-checklist.md` phase 1.

## 7. Fallback baseline: upstream sample

If the PitchComm proof fails in a way that looks like a platform problem rather
than application code, run the stock `bap_unicast_client` sample on the same
board to separate the two. Copy it from `zephyr/samples/bluetooth/audio/
bap_unicast_client` and add a board `.conf` with `CONFIG_FPU=y`,
`CONFIG_LIBLC3=y`, `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096`, and the BT buffer
sizes. That sample sends an LC3 tone, not speech.

## 8. 802.15.4 call link (next milestone)

The call link is implemented (`firmware/src/thread_link.c`) and is validated
after the proof, checklist phase 2. The board DTS already sets
`zephyr,ieee802154 = &ieee802154;` and `&ieee802154 { status = "okay"; };`, so
no overlay is required.

## Links

- NCS install: https://github.com/nrfconnect/sdk-nrf/blob/main/doc/nrf/installation/install_ncs.rst
- XIAO nRF54L15 board doc: https://docs.zephyrproject.org/latest/boards/seeed/xiao_nrf54l15/doc/index.html
- bap_unicast_client sample: https://docs.zephyrproject.org/latest/samples/bluetooth/audio/bap_unicast_client/README.html
- nRF54L LE Audio / no Audio PLL / no TWS: https://devzone.nordicsemi.com/f/nordic-q-a/122409/case-about-nrf54l15-le-audio
- nRF54L15 LE Audio support: https://devzone.nordicsemi.com/f/nordic-q-a/117778/nrf54l15-support-le-audio
- nRF5340 Audio DK: https://www.nordicsemi.com/Products/Development-hardware/nRF5340-Audio-DK
- Seeed XIAO NCS setup: https://wiki.seeedstudio.com/xiao_nrf54l15_sense_getting_started/
