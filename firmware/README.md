# PitchComm firmware

Zephyr / nRF Connect SDK application for all five PitchComm units on a Seeed XIAO nRF54L15.

Board target: `xiao_nrf54l15/nrf54l15/cpuapp`

## What you need

- nRF Connect SDK v3.4.0 with the ARM toolchain, `west`, and `nrfutil` on `PATH`.
- Five wired XIAO nRF54L15 boards ([wiring](../docs/wiring.md)).
- A laptop with Python 3.10 or newer for provisioning and audio tools.
- Two HomeSpot JY300 neckbands (one for the pitcher, one for the catcher).

## 1. Provision the team

Every unit is built with the same closed-network team file, so read each board's EUI-64 first:

1. Connect one board over USB.
2. Open the debugger serial port at 115200 (any terminal).
3. Type `eui` and press Enter. Copy the value.
4. Repeat for all five boards, noting which role each is.

Then on the laptop, from the repository folder:

```powershell
python tools\provision.py --coach EUI1 --catcher EUI2 --pitcher EUI3 `
  --shortstop EUI4 --centerfield EUI5 --channel 15
```

Pick a channel (11-26) clear of local Wi-Fi. This writes `config/team.local.json` and the firmware team header. Keep the JSON to reproduce the team; both files are git-ignored.

## 2. Build

```powershell
powershell -NoProfile -File tools\build_firmware.ps1
```

One role at a time: `-Roles coach`, `-Roles catcher`, etc. Adds `-Pristine` for a clean rebuild.

## 3. Flash firmware

```powershell
powershell -NoProfile -File tools\flash_firmware.ps1 -Role coach -Erase
```

`-Erase` wipes the chip first; use it on every first flash of a fresh board. Repeat for `catcher`, `pitcher`, `shortstop`, `centerfield`.

## 4. Load the spoken calls

The pitcher and catcher store the call recordings on their own flash.

```powershell
python tools\build_audio_fs.py
powershell -NoProfile -File tools\flash_audio.ps1
```

`flash_audio.ps1` asks for the unit to be in its normal (already firmware-flashed) state and writes the audio filesystem over USB.

To change the words or the voice:

```powershell
:: edit config\calls.json first
python tools\generate_catalog.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools\generate_audio.ps1
python tools\check_audio.py
:: rebuild all roles and reload the audio filesystem
```

The speech tool uses an installed Windows voice; pass `-Voice "VOICE NAME"` to pick one.

## 5. Use

### Coach

1. Connect the coach board to the laptop over USB.
2. Start the coach desk: `powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_coach_gui.ps1`.
3. In the browser, click **Connect coach radio**, choose the coach port, pick a pitch and location, then **Send pitch**. Use **Defensive play** for shortstop / center field.
4. Save a session report with **Save session report** before reloading the page.

### Catcher

Buttons 1-3 choose a pitch; button 4 advances the page (three pitches per page) or confirms.

| Screen | Buttons 1-3 | Button 4 |
|---|---|---|
| Pitch | Three pitches | Next page |
| Height | Up, Middle, Down | Confirm |
| Location | In, Middle, Away | Send |

Tap Back to step back; hold Back to cancel a draft or change volume. The catcher hears the delivered call in the JY300.

### Pitcher

Tap the button to repeat the last call; hold it to change volume.

### Shortstop / center field

The display shows the play; recall wakes it. Calls mark `OLD` after fifteen seconds.

### Console commands

Connect at 115200 and end each command with a newline:

| Command | Action |
|---|---|
| `eui` | Print the unit EUI-64 and link state |
| `status` | Role, EUI, dictionary, link, battery, audio, display, counters |
| `gui` / `gui CLIENT` | Coach status JSON for the coach desk |
| `call CLIENT ID p TYPE HEIGHT SIDE BOOT DICT DEADLINE` | Coach: send a pitch |
| `call CLIENT ID d PLAY BOOT DICT DEADLINE` | Coach: send a defensive play |
| `repeat` | Audio roles: repeat the last call |
| `vol 1`-`vol 20` | Audio level |
| `scan` | Scan the OLED I2C bus |
| `help` | List commands |

## 6. Theory of operation

- Calls travel over 802.15.4 (Thread). The coach is the network leader; field units are Sleepy End Devices on the same team channel.
- The catcher can also send a pitch request; the coach approves it and delivers it to the pitcher and catcher.
- Speech travels over Bluetooth LE Audio (LC3) to one earbud per audio unit. The first time, put the JY300 in pairing mode; after that the unit reconnects to it automatically.
- Calls expire after one second; a received call is acknowledged so the coach console shows delivery.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| `LINK=DOWN` on a field unit | Same team file built into all units; same channel; coach powered; field unit in range |
| Coach shows `MISS` | Field unit out of range or powered off; the call may or may not have played |
| No speech in the earbud | Earbud charged and paired; `status` shows `AUDIO=READY`; reload the audio filesystem |
| OLED blank | Wiring on D4/D5, 3V3 power, address 0x3C; use `scan` |
| Coach desk will not connect | Desktop Chrome; use the local launcher, not the HTML file directly |
| Unit does not appear on USB | Hold the XIAO boot/reset sequence or use `-Erase` on the flash command |

## 8. Files

| File | Purpose |
|---|---|
| `src/main.cpp` | Role app, hooks, engine thread, console, UI |
| `src/thread_link.c` | Thread bring-up and UDP call link |
| `src/audio_source.c` | LE Audio source and LC3 playback |
| `src/storage.c` | Audio filesystem reader |
| `src/display.cpp`, `buttons.cpp`, `battery.cpp` | Board drivers |
| `include/pc/` | Portable call engine, protocol, catalog |
| `include/app/team_config.example.h` | Team file shape; the real file is generated |
| `roles/` | Per-role build fragments |
| `boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay` | OLED, ADC, display choice |
| `tests/` | Host tests for the portable core |

Build and design notes are in [`dev/`](../dev/); the flash-and-test checklist is [`dev/test-checklist.md`](../dev/test-checklist.md).
