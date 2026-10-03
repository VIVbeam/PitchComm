# PitchComm bill of materials

Five nodes, each one Seeed XIAO nRF54L15 (21 x 17.8 mm; Nordic nRF54L15; Bluetooth 6.0 LE Audio; 802.15.4). The coach runs from USB; the four field units run from one protected Li-ion cell each. The roster supports one unit per position and more: enroll only the positions you buy, and audio is optional per unit (`dev/roster.md`).

## Parts

| Part | Qty | Approx. unit price | Buy link |
|---|---|---|---|
| Seeed XIAO nRF54L15 | 5 | $9.90 | https://www.seeedstudio.com/XIAO-nRF54L15-p-6493.html |
| 0.91" 128x32 I2C OLED, SSD1306, addr 0x3C (catcher) | 1 | $5.55 | https://www.addicore.com/products/oled-display-128x32-0-91in-monochrome |
| 0.96" 128x64 I2C OLED, SSD1306, addr 0x3C (fielder watch) | 2 | about $4.50 | https://www.aliexpress.com/w/wholesale-0.96-oled-128x64.html |
| Protected Li-ion cell, 100 mAh, JST-PH (Adafruit 1570) | 4 | $5.95 | https://www.adafruit.com/product/1570 |
| 6 x 6 x 4.3 mm tactile switches, Omron B3F-1000 class | 8 | about $0.35 | https://www.digikey.com/en/products/detail/omron-electronics-inc-emc-div/B3F-1000/78996 |
| Single-cell Li-ion charger, Micro-Lipo (Adafruit 1304) | 1 | $5.95 | https://www.adafruit.com/product/1304 |

Electronics subtotal: about $96 before the headset and straps.

One game needs about 54 mAh on a catcher or fielder and about 45 mAh on the pitcher (`dev/power.md`), so a 100 mAh pouch covers every field unit with margin to spare for a single game. The cases are sized around this cell; the larger 150, 500 and 850 mAh cells do not fit the slim shells. A multi-game weekend build would need the older, larger case set from the repository history.

Cheaper sources: XIAO nRF54L15 $7.90 at 10+ on Seeed; generic 0.91" 128x32 and 0.96" 128x64 SSD1306 OLEDs about $3 to $5 on AliExpress (https://www.aliexpress.com/w/wholesale-0.91-oled-ssd1306.html, https://www.aliexpress.com/w/wholesale-0.96-oled-128x64.html); generic protected 100 mAh cells about $2 on AliExpress. Adafruit STEMMA QT OLED (https://www.adafruit.com/product/4440, $12.50) if a Qwiic cable is preferred; the 4-pin module matches the wiring doc.

## Quantity mapping

| Unit | Board | OLED | Buttons | Cell |
|---|---|---|---|---|
| Coach | 1 | 0 | 0 | USB |
| Catcher | 1 | 1 | 5 | 100 mAh |
| Pitcher | 1 | 0 | 1 | 100 mAh |
| Shortstop | 1 | 1 | 1 | 100 mAh |
| Center field | 1 | 1 | 1 | 100 mAh |

Every XIAO nRF54L15 has an onboard Li-ion charger; the external charger is a bench/spare charger for the field cells. No I/O expander is needed: the catcher uses 2 I2C pins and 5 button pins out of the 16 exposed GPIOs. Optional positions (first, second, third, left, right) use the same board, OLED, one button and cell as shortstop; enroll only what you buy.

## Antenna

The XIAO nRF54L15 has an onboard 2.4 GHz ceramic chip antenna, selected by default at boot. It also has an RF switch and a U.FL/IPEX connector for an optional external antenna (2.4 GHz FPC, $0.90: https://www.seeedstudio.com/2-4GHz-FPC-Antenna-1-86dBi-for-XIAO-nRF54L15-p-6578.html). Keep the ceramic antenna on the field units. Holding an RF switch selection costs about 60 uA.

## Audio

HomeSpot JY300 neckband headset, 1 unit, for the pitcher. Supports LC3 (LE Audio). https://the-homespot.com/gaming

Audio is a per-unit option: add one JY300 per position you want hearing calls. The audio image grows with each audio unit and the builder refuses to overrun the 712 KB slot (compact default, PCM refused with shrink guidance).

## Loose parts

- Hookup wire, 26 to 30 AWG silicone, stranded.
- JST-PH battery pigtails (2-pin) and matching connectors.
- Heat shrink tubing, small.
- 3D printer filament or enclosures, PETG or ASA for the outdoor field units.
- M2.5 x 8 mm self-tapping screws (about 10 for a full team).
- Elastic straps for the pitcher belt and catcher guard.
- 20 mm NATO watch straps for the fielder watches, about $10 each.
- Solder and solder wick.
- Optional: USB-C cable for the coach, USB charger for the Micro-Lipo.

## Bench-only order

To bring the system up on a bench before buying the full set, you do not need cells, cases, or the charger. Both field units run from USB.

| Part | Qty |
|---|---|
| Seeed XIAO nRF54L15 | 3 |
| 0.91" 128x32 SSD1306 OLED (catcher) | 1 |
| 6 x 6 mm tactile switches | 8 |
| HomeSpot JY300 neckband | 1 |
| USB-C data cables | 3 |

The full parts list above is still the right order for a finished team.

## Cost summary

- Electronics: about $96.
- Loose parts and fielder straps: about $40 to $60.
- Headset: about $40 for one JY300.
- Total: about $180 to $200.
