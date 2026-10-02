# PitchComm firmware

Zephyr / nRF Connect SDK application for the XIAO nRF54L15 units in the roster.

Board target: `xiao_nrf54l15/nrf54l15/cpuapp`

## What you need

- nRF Connect SDK v3.4.0 with the ARM toolchain, `west`, and `nrfutil` on `PATH`.
- Five wired boards in the base set ([wiring](../docs/wiring.md)); extra positions enroll the same way.
- A laptop with Python 3.10 or newer.
- One HomeSpot JY300 neckband for the pitcher. Pair it once: put it in pairing mode; the pitcher unit reconnects to it after that.

## 1. Provision

1. Connect each board over USB.
2. Open its serial port at 115200 and type `eui`. Note the value and label the board with the unit key you will flash to it.
3. From the repository folder:

```powershell
python tools\provision.py --coach EUI1 --unit pitcher=EUI2 --unit catcher=EUI3 `
  --unit shortstop=EUI4 --unit center=EUI5 --channel 15
```

Enrolled units come from `config/roster.json`; the legacy `--catcher/--pitcher/...` flags still work for the default four.

Pick a channel (11-26) clear of local Wi-Fi. Keep `config\team.local.json` to reproduce the team; it is git-ignored.

## 2. Build

```powershell
powershell -NoProfile -File tools\build_firmware.ps1
```

`-Units coach` builds one unit; `-Roles` is kept as an alias that maps `centerfield` to `center`. `-Pristine` rebuilds clean. The script prints each image size.

## 3. Flash

```powershell
powershell -NoProfile -File tools\flash_firmware.ps1 -Unit coach -Erase
```

`-Erase` wipes the chip first; use it on the first flash of each board. Repeat per enrolled unit key; `-Role` still works as an alias for the old names.

## 4. Load the calls

Pitcher only. Flash the firmware first.

```powershell
python tools\build_audio_fs.py
powershell -NoProfile -File tools\flash_audio.ps1
```

## 5. Use

Run `selftest` on the console after the first flash. It reports each installed part as PASS, FAIL, or SKIP.

### Coach

1. Connect the coach board over USB.
2. Start the coach desk: `powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_coach_gui.ps1`.
3. In the browser, click **Connect coach radio**, choose the coach port, pick a pitch and location, then **Send pitch**. Use **Defensive play** for shortstop / center field.
4. Save a session report with **Save session report** before reloading.

### Catcher

Buttons 1-3 choose a pitch; button 4 advances the page (three pitches per page) or confirms.

| Screen | Buttons 1-3 | Button 4 |
|---|---|---|
| Pitch | Three pitches | Next page |
| Row | High, Middle, Low | Confirm |
| Column | Inside, Middle, Outside | Send |

Tap Back to step back; hold Back to cancel a draft. A delivered call shows `CALL` with the pitch on the OLED for a few seconds, then the menu returns.

### Pitcher

Tap the button to repeat the last call; hold it to change volume.

### Shortstop / center field

The display shows the play; recall wakes it. Calls mark `OLD` after fifteen seconds.

### Console commands

Connect at 115200 and end each command with a newline:

| Command | Action |
|---|---|
| `eui` | Print the unit EUI-64 and link state |
| `status` | Unit, EUI, dictionary, link, battery, audio, display, counters |
| `selftest` | Bench check: OLED, controls, battery, storage, audio, settings |
| `gui` / `gui CLIENT` | Coach status JSON for the coach desk |
| `call CLIENT ID p TYPE ROW COL BOOT DICT DEADLINE` | Coach: send a pitch |
| `call CLIENT ID d PLAY BOOT DICT DEADLINE` | Coach: send a defensive play |
| `repeat` | Audio units: repeat the last call |
| `vol 1`-`vol 20` | Audio level |
| `scan` | Scan the OLED I2C bus |
| `help` | List commands |

Default vocabulary: 9 pitch types x 3 rows x 3 columns (81 calls) plus 21 play calls. The calls are spoken pitch and location phrases recorded in `data/audio`; plays route by audience and any enrolled unit can optionally carry audio (`dev/roster.md`).

## Bench check (two boards, no cases or cells)

The radio and the engine come up with boards on USB.

1. Connect two boards. One is the coach; the other can be any field unit.
2. Read both `eui` values, provision with unique dummy EUIs for the three absent units, build both units, and flash both.
3. Open both consoles, 115200, and run `selftest` on each.
4. From the coach console or the coach desk, send a call.

The link is good when both report `LINK=UP`, calls arrive within a second,
and a powered-off field unit shows `MISS` on the coach without locking up.
A bare field board ACKs `OutputError` because it has no output; add one OLED
(catcher, shortstop, or center field) or one JY300 (pitcher) for a clean
delivery. No battery, charger, or case is needed on the bench.

## Troubleshooting

| Symptom | Check |
|---|---|
| `LINK=DOWN` on a field unit | Same team file on all units; same channel; coach powered; unit in range |
| Coach shows `MISS` | Field unit out of range or powered off |
| No speech in the earbud | Earbud charged and paired; `status` shows `AUDIO=READY`; reload the audio filesystem |
| OLED blank | Wiring on D4/D5, 3V3 power, address 0x3C; use `scan` |
| Coach desk will not connect | Desktop Chrome; use the local launcher, not the HTML file directly |
| Unit does not appear on USB | Use `-Erase` on the flash command |

Build, design, and vocabulary maintenance notes are in [`dev/`](../dev/); the flash-and-test checklist is [`dev/test-checklist.md`](../dev/test-checklist.md).
