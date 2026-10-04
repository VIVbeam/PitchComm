# Power budget and one-game cells

Estimated, not measured. The requirement is one game, taken as three hours of play with the unit worn. Bench current measurements are in `dev/test-checklist.md` phases 3 and 5; nothing here is a measurement.

## Estimated average current

| Unit build | Load | Estimate | Energy per 3 h game |
|---|---|---|---|
| Relay + OLED (catcher, fielders) | 802.15.4 receive about 4.6 mA, MCU about 1.5 mA, OLED about 12 mA | about 18 mA | about 54 mAh |
| Relay + LE Audio (pitcher) | radio and MCU plus a kept-alive LC3 stream, no display | about 15 mA | about 45 mAh |
| Sleepy + OLED (`--no-relay`) | polled sleep plus the same display load | about 13 mA | about 39 mAh |
| Sleepy, no display | polled sleep only | about 1 mA | about 3 mAh |

The OLED dominates every display unit; the radio is about a third of the load. The fielder watch uses the 128x64 panel but its strip UI stays sparse, so the same estimate stands. The only way materially below a 100 mAh cell is to blank the OLED when no call is recent, which changes first-call behavior and is not implemented.

## Recommended cells

| Use | Cell | Size | Weight | Notes |
|---|---|---|---|---|
| Standard smallest build, every field unit | Adafruit 1570, 100 mAh | 11.5 x 31 x 3.8 mm | 3 g | About 1.8 catcher games and 2.2 pitcher games by nameplate, about 1.4 to 1.8 after derating. The slim cases are sized for this cell. |
| More margin | Adafruit 1317, 150 mAh | 19.75 x 26 x 3.8 mm | 4.65 g | About 1.5x the runtime, but it does not fit the slim cases; use the older shell set. |
| Multi-game weekends | Adafruit 1578, 500 mAh, and SparkFun PRT-13854, 850 mAh | larger | | Older shell set only; roughly 25 to 50 games by estimate. |

The XIAO's onboard charger runs at about 100 mA, which is 1C for the 100 mAh cell, the top of its rating. Verify the board's actual charge current on the bench; if it is higher, charge through an external 50 to 100 mA charger or add a series resistor. If the one-game margin feels thin, blanking the OLED when no call is recent is the highest-value change: the display is about two thirds of the load.

## Size impact

| Case | Original | Shipped now (`dev/cad/dimensions.json`) | Cell |
|---|---|---|---|
| Pitcher | 42.0 x 63.5 mm, flat 14.65 mm | 30.0 x 48.6 mm, flat 13.0 mm, pre-soldered board | 100 mAh, 11.5 x 31 x 3.8 mm |
| Fielder watch | 46.0 x 56.0 mm, flat 14.3 mm, 19.9 mm max | 45.8 x 50.1 mm, flat 13.0 mm, 13.4 mm max, 55.1 mm lug to lug | 100 mAh |
| Catcher | 48.0 x 80.0 mm, flat 16.8 mm, 23.9 mm max | 37.0 x 58.2 mm, flat 14.0 mm, 14.4 mm max, worn landscape | 100 mAh |

Against the original shells that is roughly 25 to 57 percent less envelope and 40 to 60 percent less printed plastic, with the 6 mm switch class, the 100 mAh cell and the display rework doing the work. The old 500 and 850 mAh cells no longer fit any shell. The floor is now the electronics: the 21 x 17.8 mm board, the two OLED modules, the switch bodies and the antenna keepout.

## What to measure on hardware

- Average current per build: relay + OLED, relay + audio, sleepy + OLED.
- Whole-game voltage from the firmware `status` battery readout.
- The OLED blanking payoff if it is added: idle-off versus always-on.
