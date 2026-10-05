# PitchComm bill of materials

Five nodes, each one Seeed XIAO nRF54L15 (21 x 17.8 mm; Nordic nRF54L15; Bluetooth 6.0 LE Audio; 802.15.4). The coach runs from USB; the four field units run from one protected Li-ion cell each. The operating plan is to swap field batteries every inning and recharge the removed cells on separate two-pin JST chargers.

## Parts

| Part | Qty | Approx. unit price | Buy link |
|---|---|---|---|
| Seeed XIAO nRF54L15, pre-soldered | 5 | $10.90 | https://www.seeedstudio.com/XIAO-nRF54L15-p-6493.html |
| 0.91" 128x32 I2C OLED, SSD1306, addr 0x3C (catcher) | 1 | $5.55 | https://www.addicore.com/products/oled-display-128x32-0-91in-monochrome |
| 0.96" 128x64 I2C OLED, SSD1306, addr 0x3C (fielder watch) | 2 | $6.50 US, about $4.50 AliExpress | https://www.addicore.com/products/oled-display-128x64-0-96in-monochrome (budget: https://www.aliexpress.com/w/wholesale-0.96-oled-128x64.html) |
| Protected Li-ion cell, 100 mAh, JST-PH (Adafruit 1570) | 4 installed + rotation spares; total TBD | $5.95 | https://www.adafruit.com/product/1570 |
| 6 x 6 x 5 mm tactile switches, TE 1825910-6 class (Addicore AD140 or Adafruit 367) | 8 | $0.10 each, or $2.50 per 20-pack | https://www.addicore.com/products/small-tact-mini-push-button-switch-6x6x5mm |
| JST-PH-compatible 2-pin cable, male header, 200 mm (Adafruit 3814) | 4 | $0.75 | https://www.adafruit.com/product/3814 |
| Single-cell Li-ion charger with matching two-pin JST-PH polarity, at 100 mA or less (Micro-Lipo Adafruit 1304 is the reference) | TBD; one independent channel per cell charged simultaneously | $5.95 reference allowance | https://www.adafruit.com/product/1304 |

The earlier electronics subtotal of about $107 covers the pre-soldered boards, three panels, four installed cells, eight switches, battery pigtails and one reference charger. It does not cover the rotation spares or multiple charging channels in the inning-swap plan. Their quantities remain to be sized from measured consumption and charging turnaround. Prices are budget allowances, excluding shipping and tax.

The specified [100 mAh cell](https://www.adafruit.com/product/1570) requires charging at 100 mA or less. The [XIAO power schematic](https://files.seeedstudio.com/wiki/XIAO_nRF54L15/Getting_Start/nRF54L15_Schematic.pdf), sheet 4, sets its onboard charger to 200 mA through R4 (120 kOhm). **Disconnect the cell before any USB connection to a field board**, including flashing, diagnostics and bench operation. Remove the unit from the player, unplug the cell from the board pigtail, and charge it separately with the Micro-Lipo at 100 mA. Leave its 500 mA setting unused for these cells. One charger serves one disconnected cell at a time. Firmware does not control the charge-current resistor.

For inning swaps, use a charged spare while the removed cell charges off the unit. A two-pin JST connector alone does not establish charger compatibility: match the JST-PH housing, polarity and a single-cell Li-ion/LiPo CC/CV charger, with a charge-current setting of 100 mA or less. Do not assume a removed cell will be ready by the next inning; charging turnaround and the needed spare pool remain unmeasured. Battery removal powers the unit down, so confirm reconnection and the pitcher's audio readiness after each swap.

Adafruit 3814 is the mating cable for the cell's connector; the previous Adafruit 261 entry was the same connector half as the cell. The 3814 uses a compatible clone housing, not a genuine JST part. Verify physical polarity before connecting, and trim leads only after checking the complete route. Its mated housing and insulated wire diameter remain unverified in the slim cases; conductor gauge alone does not establish clearance.

Board note: pre-soldered boards are the standard. The cases reserve 2.5 mm above the PCB for the header strips and 0.5 mm below it for trimmed solder fillets. Run the USB bench setup with the header pins intact, then trim their underside ends flush before the cased build; trimmed boards cannot plug into breadboards again. Both bare and pre-soldered boards rest directly on the four current deck posts. Do not add a shim or tape beneath their bearing surfaces: that raises the PCB and changes USB alignment. The battery pads need solder either way. The catcher Back signal, D13, is an underside pad rather than a pin on either 1x7 header; solder its lead while the board is accessible, including for the full catcher USB bench setup.

Battery life remains unmeasured. The earlier three-hour budgets of 54 mAh for screen units and 45 mAh for the pitcher assume average battery currents of 18 mA and 15 mA respectively; these are **unverified planning assumptions**, not measured role-specific consumption. With an assumed 80 mAh usable budget to leave reserve, those inputs calculate about 4.4 and 5.3 hours. At 20 mA the same budget lasts 4 hours; at 30 mA it lasts only 2.7 hours. A full-game runtime is not established until a finished unit is tested, and the pitcher is not proven to last longer than a screen unit.

The current roster makes every field unit a radio relay. The pitcher keeps its LE Audio stream running between calls; linked display units blank their OLED after 30 seconds without activity. These settings, display content, actual cell capacity and temperature affect consumption. The earbud has its own separate battery. The cases are sized around a 100 mAh pouch. Larger 150, 500 and 850 mAh cells do not fit these shells.

Cheaper sources: XIAO nRF54L15 $7.90 at 10+ on Seeed; generic 0.91" 128x32 and 0.96" 128x64 SSD1306 OLEDs about $3 to $5 on AliExpress (https://www.aliexpress.com/w/wholesale-0.91-oled-ssd1306.html, https://www.aliexpress.com/w/wholesale-0.96-oled-128x64.html); generic protected 100 mAh cells about $2 on AliExpress. Adafruit STEMMA QT OLED (https://www.adafruit.com/product/4440, $12.50) if a Qwiic cable is preferred; the 4-pin module matches the wiring doc.

## Quantity mapping

| Unit | Board | OLED | Buttons | Cell |
|---|---|---|---|---|
| Coach | 1 | 0 | 0 | USB |
| Catcher | 1 | 1 | 5 | 100 mAh |
| Pitcher | 1 | 0 | 1 | 100 mAh |
| Shortstop | 1 | 1 | 1 | 100 mAh |
| Center field | 1 | 1 | 1 | 100 mAh |

The external 100 mA charger is required for the specified field cells. Use USB on field boards with the cells disconnected. No I/O expander is needed: the catcher uses 2 I2C pins and 5 button pins out of the 16 exposed GPIOs. Optional positions (first, second, third, left, right) use the same board, OLED, one button and cell as shortstop; enroll only what you buy.

## Antenna

The XIAO nRF54L15 has an onboard 2.4 GHz ceramic chip antenna, selected by default at boot. It also has an RF switch and a U.FL/IPEX connector for an optional external antenna (2.4 GHz FPC, $0.90: https://www.seeedstudio.com/2-4GHz-FPC-Antenna-1-86dBi-for-XIAO-nRF54L15-p-6578.html). Keep the ceramic antenna on the field units. Holding an RF switch selection costs about 60 uA.

## Audio

HomeSpot JY300 neckband headset, 1 unit, for the pitcher. Supports LC3 (LE Audio). https://the-homespot.com/gaming

Audio is a per-unit option: add one JY300 per position you want hearing calls. The audio image grows with each audio unit and the builder refuses to overrun the 712 KB slot (compact default, PCM refused with shrink guidance).

## Loose parts

- Hookup wire, 26 to 30 AWG silicone, stranded. Choose by measured insulated outside diameter and finished solder-joint height, not AWG alone. The v19 pitcher/watch PCB-to-deck gap is 2.05 mm; the catcher gap is 2.4 mm. The current cases do not establish a fit for arbitrary wire insulation or the JST connector body.
- Filament-compatible adhesive for the separate printed button heads, captive stems and flush numeral inlays. Check adhesion and free button travel on one printed unit; joint and inlay retention are unmeasured.
- Four Adafruit 3814 mating battery pigtails, included in the electronics table; retain the cells' existing connectors for disconnection and external charging.
- Heat shrink tubing, small.
- 3D printer filament or enclosures, PETG or ASA for the outdoor field units.
- M2.5 self-tapping screws: six x 10 mm for the pitcher/catcher carriers and four x 8 mm for the two fielder watches. For a pitcher or catcher without a carrier, use three x 8 mm instead. Heads must fit the modeled 5.6 mm diameter x 1.0 mm deep recesses; check actual head dimensions before ordering.
- Elastic straps for the pitcher belt and catcher guard.
- 20 mm NATO watch straps for the fielder watches, about $10 each.
- Temperature-controlled soldering iron with a fine tip (Pinecil V2 class, USB-C PD), 63/37 solder 0.6 to 0.8 mm, flux pen, brass wool, and a basic multimeter for continuity. Header-connected USB bench signals can use jumper leads, but the catcher Back input needs a soldered underside D13 lead. Soldering is also required for the finished battery pigtail, switches and OLED wiring.
- USB-C data cable for the coach and field-board setup; a 5 V USB source for the Micro-Lipo. Disconnect each field cell before connecting its board to USB.

## Bench-only order

To bring the system up on a bench before buying the full set, you do not need cells, cases, or the charger. Both field units run from USB with no cell connected.

| Part | Qty |
|---|---|
| Seeed XIAO nRF54L15 | 3 |
| 0.91" 128x32 SSD1306 OLED (catcher) | 1 |
| 6 x 6 mm tactile switches | 8 |
| HomeSpot JY300 neckband | 1 |
| USB-C data cables | 3 |

Include a short insulated lead and soldering access for the catcher D13 underside pad when testing Back. The full parts list above is still the right order for a finished team.

## Cost summary

Full team parts at list prices:

- Five pre-soldered XIAO boards: $54.50.
- One 0.91 inch catcher panel and two 0.96 inch watch panels: $18.55.
- Four 100 mAh cells: $23.80.
- Eight 6 mm switches: $0.80.
- Four JST-PH battery pigtails: $3.00.
- One shared 100 mA Micro-Lipo charger: $5.95.
- Case screws (8 and 10 mm), existing budget allowance: $7.64.
- One JY300: $37.99.
- Full team parts: **about $152**, using these budget allowances.

Shipping and tax depend on the current checkout and are excluded above. Two NATO straps and the filament are assumed owned; allow about $35 more if needed.

Bench minimum: three boards, one 128x32 panel, eight switches, one JY300 and the jumper wires, about $77 plus shipping, no cells or cases. Tools are separate: the soldering setup runs about $85 and a multimeter, flush cutters, USB-C data cables, straps and filament are assumed owned.
