# PitchComm firmware

Zephyr / nRF Connect SDK application for the XIAO nRF54L15 units in the roster.

Board target: `xiao_nrf54l15/nrf54l15/cpuapp`

## What you need

- nRF Connect SDK v3.4.0 with the ARM toolchain, `west`, and `nrfutil` on `PATH`.
- Five wired boards ([wiring](../docs/wiring.md)).
- A laptop with Python 3.10 or newer.
- One HomeSpot JY300 neckband for the pitcher. Pair it once: put it in pairing mode; the pitcher unit reconnects to it after that.

## 1. Provision

For first setup from a fresh checkout, before `team_config.h` is generated,
build the unprovisioned coach image and flash it to each board, one at a time.
It reports the chip ID without joining a team:

```powershell
powershell -NoProfile -File tools\build_firmware.ps1 -Units coach -StrictSize
powershell -NoProfile -File tools\flash_firmware.ps1 -Unit coach -Erase
```

Repeat the flash for each fresh board. Then:

1. Connect each board over USB.
2. Open its serial port at 115200 and type `eui`. Note the value and label the board with the unit key you will flash to it.
3. From the repository folder:

```powershell
python tools\provision.py --coach EUI1 --unit pitcher=EUI2 --unit catcher=EUI3 `
  --unit shortstop=EUI4 --unit center=EUI5 --channel 15
```

Unit keys come from `config/roster.json`. Use the supplied roster, firmware catalog, coach catalog, and audio together.

Pick a channel (11-26) clear of local Wi-Fi. Keep `config\team.local.json` to reproduce the team; it is git-ignored.

## 2. Build

```powershell
powershell -NoProfile -File tools\build_firmware.ps1
```

`-Units coach` builds one unit. `-Pristine` rebuilds clean. Use `-StrictSize` to require a measured image that fits the application slot. Field units are Thread relays by default; `relay: false` selects a sleepy build.

If an image exceeds the 712 KB application slot, try `-MinSize`. The
`-NoBootloader -BuildSuffix nb` option uses the larger 776 KB application
layout; flash that build with `-BuildDir firmware/build/<unit>-nb -Erase`.
This layout must be validated on hardware before use.

## 3. Flash

```powershell
powershell -NoProfile -File tools\flash_firmware.ps1 -Unit coach -Erase
```

`-Erase` wipes the chip first; use it on the first flash of each board. Repeat per enrolled unit key; `-Role` still works as an alias for the old names.

## 4. Load the calls

Load every unit whose roster has audio enabled (pitcher in the default team).
Flash the firmware first, then connect one audio board at a time:

```powershell
powershell -NoProfile -File tools\flash_audio.ps1
```

Reload the calls after any chip erase. Erasing also clears saved earbud bonds;
pair the earbud again afterward.

The supplied `data/audio/littlefs.hex` is ready to flash. The tool checks its
checksum, catalog version, and complete audio-slot layout before programming it.

## 5. Use

Run `selftest` on the console after the first flash. It reports each installed part as PASS, FAIL, or SKIP.

### Coach

1. Connect the coach board over USB.
2. Start the coach desk: `powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_coach_gui.ps1`.
3. In the browser, click **Connect coach radio**, choose the coach port, select a pitch, then **Announce pitch**. After the pitch recipients accept the output and you observe the pitcher's nod, click **Pitcher nodded → placement**, choose the location, then **Send placement**. This second message speaks the location only. **Back** revises the draft; changing pitch sends a fresh announcement. Use **Play call** for the defensive and pitching calls; the desk shows who receives each one. Keys: `1-9` pitch type, `Q W E / A S D / Z X C` location, `Enter` the current action, `R` send again, `Esc` Back/clear.
4. Save a session report with **Save session report** before reloading.

### Catcher

Use the catcher horizontally, screen above buttons 1–4 from left to right; Back sits on the lower edge. The display's four columns correspond to those numbered buttons. Buttons 1–3 select and immediately request the pitch-name announcement; button 4 pages through the pitches or confirms the current step.

| Screen | Buttons 1-3 | Button 4 |
|---|---|---|
| Pitch | Select and announce one of three pitches | Next page |
| Sending | Wait for coach response | Wait |
| Nod | No action | Confirm a nod you observed |
| Row | High, Middle, Low | Confirm |
| Column | Inside, Middle, Outside | Send placement |

Tap Back to step back; from Nod or Sending it returns to pitch selection. Hold Back to cancel a draft. Coach acceptance means the request was queued; wait for the pitcher's actual nod before choosing placement. The coordinator rejects placement if the announcement lacks matching successful output receipts, its context expired, or a recipient restarted. A received call briefly appears on the OLED. Nobody detects nods automatically, and output acceptance does not prove a player heard the call.

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
| `call CLIENT ID t TYPE BOOT DICT DEADLINE` | Coach: announce a pitch name |
| `call CLIENT ID l TYPE ROW COL BOOT DICT DEADLINE` | Coach: send placement for the announced pitch |
| `call CLIENT ID p TYPE ROW COL BOOT DICT DEADLINE` | Coach: send a complete pitch through the retained console command |
| `call CLIENT ID d PLAY BOOT DICT DEADLINE` | Coach: send a defensive play |
| `repeat` | Audio units: repeat the last call |
| `vol 1`-`vol 20` | Audio level |
| `scan` | Scan the OLED I2C bus |
| `help` | List commands |

Vocabulary: 9 pitch types x 3 rows x 3 columns (81 calls) plus 21 play calls. The supplied audio contains the spoken calls for the pitcher; play audiences are included in the coach catalog.

The two-step interface uses announcement codes 82–90 and placement codes 91–171 under dictionary `94b7a24a`. Placement carries the pitch identity while playing only the location clip. Its announcement context expires after two minutes; a different call, recipient reconnect or output failure may require reannouncement sooner. Update all enrolled firmware, coach files and audio together. Host checks and simulated browser operation pass; Nordic SDK compilation, image sizes and physical operation remain unverified.

The application protects engine state with a short mutex and gives the UI copied snapshots. The main UI loop owns screen updates, controls and console commands; the console reader copies commands into a bounded queue. OLED transfers run outside the engine mutex, so they do not hold up receiver processing. Display receivers send a success receipt only after the current call's transfer succeeds within its delivery window. A superseded, failed or expired transfer cannot acknowledge another call. Catcher calls remain on screen for four seconds before the selection menu returns, unless an active selection owns the screen.

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

If a field board already has a cell, disconnect it before connecting USB for flashing, console diagnostics or bench operation. The stock XIAO charger supplies 200 mA, above the specified 100 mAh cell's 100 mA limit; firmware does not control that current. Charge the cell separately at 100 mA as described in the [wiring reference](../docs/wiring.md#power-and-battery).

The current roster builds every field unit as a Full Thread Device relay, with receive-on operation for forwarding. The 200 ms sleepy-device poll setting applies only when a unit's roster entry has `relay: false`; no between-pitch deep-sleep mode is implemented for the current relay set. The pitcher maintains its LE Audio stream with encoded silence between calls. Linked display units blank the OLED after 30 seconds without interaction, and calls/buttons wake it. These behaviors do not establish battery current or runtime. The [battery planning assumptions](../docs/bom.md#parts) require measurement on finished hardware.

## Troubleshooting

| Symptom | Check |
|---|---|
| `LINK=DOWN` on a field unit | Same team file on all units; same channel; coach powered; unit in range |
| Coach shows `MISS` | Field unit out of range or powered off |
| No speech in the earbud | Earbud charged and paired; `status` shows `AUDIO=READY`; reload the audio filesystem |
| OLED blank | Wiring on D4/D5, 3V3 power, address 0x3C; use `scan` |
| Coach desk will not connect | Desktop Chrome; use the local launcher, not the HTML file directly |
| Unit does not appear on USB | Use `-Erase` on the flash command |

Run `python tools/check_setup.py` to check package consistency and the saved
team configuration. Hardware validation is pending; the checks above are
acceptance criteria, not measured performance.
