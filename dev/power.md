# Power budget and one-game cells

Estimated, not measured. The requirement is one game, taken as three hours of play with the unit worn. Bench current measurements are in `dev/test-checklist.md` phases 3 and 5; nothing here is a measurement.

## Estimated average current

| Unit build | Load | Estimate | Energy per 3 h game |
|---|---|---|---|
| Relay + OLED (catcher, fielders) | 802.15.4 receive about 4.6 mA, MCU about 1.5 mA, OLED about 12 mA | about 18 mA | about 54 mAh |
| Relay + LE Audio (pitcher) | radio and MCU plus a kept-alive LC3 stream, no display | about 15 mA | about 45 mAh |
| Sleepy + OLED (`--no-relay`) | polled sleep plus the same display load | about 13 mA | about 39 mAh |
| Sleepy, no display | polled sleep only | about 1 mA | about 3 mAh |

The OLED dominates every display unit; the radio is about a third of the load. The only way materially below a 100 mAh cell is to blank the OLED when no call is recent, which changes first-call behavior and is not implemented.

## Recommended cells

| Use | Cell | Size | Weight | Notes |
|---|---|---|---|---|
| Standard one-game build, every field unit | Adafruit 1317, 150 mAh | 19.75 x 26.02 x 3.8 mm | 4.65 g | About 2.8 games for a catcher, 3.3 for the pitcher by estimate, before cold and aging derating |
| Floor, pitcher or a build with display blanking | Adafruit 1570, 100 mAh | 11.5 x 31 x 3.8 mm | 3 g | Charge at 100 mA or less |
| Multi-game weekends | Adafruit 1578, 500 mAh, and SparkFun PRT-13854, 850 mAh | current cells | | Roughly 25 to 50 games by estimate; the current cases are designed around these |

The XIAO's onboard charger runs at about 100 mA, which suits the 150 mAh cell (0.67C) and is at the limit for the 100 mAh cell. Keep an external charger only as a spare.

## Size impact

| Case | Today (from `dev/cad/dimensions.json`) | Cell space today | Rough slim target with a 150 mAh cell |
|---|---|---|---|
| Receiver (pitcher) | 42 x 63.5 x 14.65 mm | 34.5 x 45 x 6.2 mm | about 36 x 50 x 13 mm |
| Wrist (fielder) | 46 x 56 x 14.3 mm, 19.9 tilted | 29 x 36 x 4.75 mm | about 42 x 46 x 13.5 mm |
| Keypad (catcher) | 48 x 80 x 16.8 mm, 23.9 tilted | 34.5 x 45 x 6.2 mm | about 42 x 62 x 14 mm |

That is roughly 35 to 50 percent less case volume, and about 12 g less carried weight on the pitcher and catcher. The floor is now the electronics: the 21 x 17.8 mm board, the 30 x 12 mm OLED module, the five catcher buttons and the antenna keepout. The current cases still fit the smaller cell with foam or a printed spacer.

Slim cases require regenerating the STL and 3MF exports. That is on hold until the owner approves changing the CAD files; nothing in `cad/unbranded/exports/` changes for a small-cell build.

## What to measure on hardware

- Average current per build: relay + OLED, relay + audio, sleepy + OLED.
- Whole-game voltage from the firmware `status` battery readout.
- The OLED blanking payoff if it is added: idle-off versus always-on.
