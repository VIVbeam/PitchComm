# PitchComm wiring reference

Five units in the base set, one Seeed XIAO nRF54L15 each (21 x 17.8 mm; Nordic nRF54L15; Bluetooth 6.0 LE Audio; 802.15.4). Extra positions wire the same as shortstop. All peripheral logic is 3.3 V. Never source peripherals from the 5V pin on battery.

## XIAO nRF54L15 pin map (silk to port)

| Silk | Port | Alt / notes |
|------|------|-------------|
| 5V   | VBUS | System supply rail, USB-derived or battery-derived; see power notes |
| GND  | GND  | Common ground |
| 3V3  | 3V3_OUT | Regulated 3.3 V out |
| D0   | P1.04 | GPIO, ADC |
| D1   | P1.05 | GPIO, ADC |
| D2   | P1.06 | GPIO, ADC |
| D3   | P1.07 | GPIO, ADC |
| D4   | P1.10 | GPIO, I2C (SDA) |
| D5   | P1.11 | GPIO, I2C (SCL) |
| D6   | P2.08 | GPIO, UART1 TX |
| D7   | P2.07 | GPIO, UART1 RX |
| D8   | P2.01 | GPIO, SPI SCK |
| D9   | P2.04 | GPIO, SPI MISO |
| D10  | P2.02 | GPIO, SPI MOSI |
| D11  | P0.03 | GPIO |
| D12  | P0.04 | GPIO |
| D13  | P2.10 | GPIO |
| D14  | P2.09 | GPIO |
| D15  | P2.06 | GPIO |
| BAT+ | -    | Battery positive pad |
| BAT- | -    | Battery negative pad |

## I2C bus (catcher, shortstop, center field)

The XIAO header I2C pins are D4 (SDA, P1.10) and D5 (SCL, P1.11). In the Zephyr devicetree this is `i2c22`; the firmware overlay attaches one SSD1306 panel at 0x3C. The catcher uses the 0.91" 128x32 module and the fielder watch uses the 0.96" 128x64 module; both are the same 4-pin SSD1306 wiring. Do not add an I/O expander.

| XIAO | OLED (both panels) |
|------|--------------------|
| 3V3  | VCC        |
| GND  | GND        |
| D4   | SDA        |
| D5   | SCL        |

The module carries 4.7k pull-ups; that is enough. 400 kHz is safe at 3.3 V. Power the OLED from 3V3 only.

## Coach

USB-C to laptop only. No external wiring.

## Catcher

OLED on D4/D5. Five buttons, all direct GPIO. Each button is wired pin to GND; the firmware enables the internal pull-ups.

| Signal | Silk | Port  | Button        |
|--------|------|-------|---------------|
| Call 1 | D0   | P1.04 | D0 -> GND     |
| Call 2 | D1   | P1.05 | D1 -> GND     |
| Call 3 | D2   | P1.06 | D2 -> GND     |
| Call 4 | D3   | P1.07 | D3 -> GND     |
| Back   | D13  | P2.10 | D13 -> GND    |
| Battery| BAT+ / BAT- | - | 100 mAh cell |

The catcher uses 7 GPIOs (2 I2C + 5 buttons). D13 (Back) is the underside pad identified as TP15 in the manufacturer PCB file; it is not on the two standard 1x7 headers. Solder an insulated lead to that pad before securing the board, including for USB bench testing of all five buttons.

## Pitcher

| Signal  | Silk | Port  | Device            |
|---------|------|-------|-------------------|
| Recall  | D1   | P1.05 | D1 -> GND         |
| Battery | BAT+ / BAT- | - | 100 mAh protected cell |

## Shortstop / center field

| Signal   | Silk | Port  | Device            |
|----------|------|-------|-------------------|
| OLED VCC | 3V3  | -     | SSD1306 0x3C      |
| OLED GND | GND  | -     |                   |
| OLED SDA | D4   | P1.10 |                   |
| OLED SCL | D5   | P1.11 |                   |
| Recall   | D1   | P1.05 | D1 -> GND         |
| Battery  | BAT+ / BAT- | - | 100 mAh protected cell |

## GPIOs to avoid

| Port      | Silk      | Reason |
|-----------|-----------|--------|
| P0.00     | USER KEY  | Onboard user button |
| P2.00     | USER_LED  | Onboard user LED |
| P2.05     | -         | RF switch port select (antenna) |
| P2.03     | -         | RF switch power |
| P1.14     | -         | AIN7 VBAT sense, internal divider |
| P1.15     | -         | VBAT divider load-switch enable |
| P1.02/P1.03 | NFC1/NFC2 | NFC pins, not on header |
| D6 / D7   | UART1 TX/RX | Header UART pins, unused by this design |
| P1.08/P1.09 | -       | Onboard debugger UART (console) |

Safe for this design: D0, D1, D2, D3, D4, D5, D13 (plus D8-D12, D14, D15 if needed).

## Power and battery

- Operating routine: swap batteries every inning and charge removed cells separately through their two-pin JST connectors. Use charged spares rather than charging a cell connected to a worn unit. After reconnecting a spare, confirm the unit rejoins the network and the pitcher's audio is ready before sending calls. Swap time, reconnection time and charging turnaround remain unmeasured.
- Cell: single protected 3.7 V Li-ion or LiPo, 1S only. Watch polarity at the BAT pads.
- The specified [Adafruit 1570 cell](https://www.adafruit.com/product/1570) permits at most 100 mA charging. The [XIAO power schematic](https://files.seeedstudio.com/wiki/XIAO_nRF54L15/Getting_Start/nRF54L15_Schematic.pdf), sheet 4, uses U1 SGM40567 and R4=120 kOhm for 200 mA charging. Its IREF net connects only U1 and R4 in the reviewed PCB; firmware cannot reduce this setting.
- **Disconnect the cell before any USB connection to its board**, including flashing, diagnostics and USB bench operation. USB supplies the onboard charger even when the application is not running.
- Charge off-body: unplug the cell from the board pigtail, then connect it alone to the [Micro-Lipo 1304](https://www.adafruit.com/product/1304) at its 100 mA setting. Do not select 500 mA for these cells. Remove the cell from the charger before reconnecting it to a board with USB unplugged. The [sliding-panel fit prototype](../cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt) opens at the battery side while leaving the lid, deck and mount fitted. For the preserved v20 screw-fastened cases, support the deck and attached wires during opening.
- Do not charge and operate a hot cell. Charge in a fire-safe area on a non-flammable surface.
- Battery sense is internal: P1.14 (AIN7) reads the cell through the load switch enabled by P1.15. Do not add an external divider. The firmware enables the switch, reads ADC channel 7, and scales by 2.
- The header labeled **5V** is the system supply rail `VBUS`, not the raw USB rail `TYPE-C_5V`. In the reviewed manufacturer circuit, Q1 connects the battery to `VBUS` when USB is absent; D4 supplies `VBUS` from USB when connected. Expect battery-derived voltage at the 5V header on battery, not regulated 5 V. It is **not a USB-presence signal**. This follows the schematic/PCB source; actual voltage has not been measured. Power the OLED from **3V3 only**.
- The current roster marks every field unit as a relay. Their builds use Full Thread Device mode and keep the receiver available for forwarding; they do not use the 200 ms sleepy-device poll setting. The build tool applies that setting only to units explicitly configured with `relay: false`. Do not assume deep sleep between pitches or use chip sleep-current figures to estimate this system's runtime.
- The pitcher keeps its LE Audio stream running between calls, transmitting encoded silence. Linked display units blank the OLED after 30 seconds without interaction; new calls and button activity wake it. Whole-unit battery current and runtime remain unmeasured; see the [battery planning assumptions](bom.md#parts).

## Wiring inside the current cases

Use the [v8 sliding-panel guide](../cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt) for the current horizontal catcher and battery-access prototype. Keep its complete matched parts together. Its connector envelope and battery extraction path are calculated; full wiring, soldered fit and actual housings remain unverified. Field USB openings are closed; service access requires opening the main lid, with the cell disconnected.

The dimensions and routing studies below describe the preserved v20 cases. They are not a wiring-clearance certification for the v8 prototype.

The manufacturer PCB identifies battery positive as TP9 (VBAT), battery negative as TP10 (GND), and the catcher Back input as TP15 (D13/P2.10), all on the underside. These are file reference names, not assumed silkscreen labels. Use the board markings and manufacturer pinout to identify the physical pads. Attach these leads while the underside is accessible, before retaining the PCB on its deck posts.

| Unit | PCB underside to deck top | Existing solder reservation |
|---|---|---|
| Pitcher | 2.05 mm | 0.5 mm high, 0.2 mm XY allowance |
| Fielder watch | 2.05 mm | 0.5 mm high, 0.2 mm XY allowance |
| Catcher | 2.4 mm | 0.5 mm high, 0.2 mm XY allowance |

These are calculated CAD spaces and assumed solder reservations. AWG describes the conductor, not the finished insulation diameter. The v19 cases have continuously checked spatial corridors for assumed 0.6, 1.0 and 1.4 mm insulated wire envelopes with 0.05 mm per-side allowance, stopping just outside the PCB. Other pad reservations, retained posts and the antenna band stay clear. These geometric paths do not establish a finished solder joint, bend radius, full wiring route or connector fit. Check the actual wire and joint against one printed set; do not use a PCB shim to gain space, since it changes charging-port alignment.

Keep the PCB resting directly on all four posts, with removable retention adhesive beside the bearing tops. Keep adhesive away from pads and test points. Use the Adafruit 3814 male mating pigtail on the board, retaining the cell's existing connector; Adafruit 261 is the same connector half as the cell. Check physical polarity before connecting. The full mated housing, strain relief and protected-cell dimensions are not verified in the current assembly. Keep all wiring and metal out of the reserved antenna band; deck-lightening windows do not make that band a wiring route. The [v20 print guide](../cad/unbranded/README.md) gives the earlier release's matching parts and assembly order.

## Radio

- Call link: 802.15.4 Thread, channel 11-26 (default 15), one closed network per team.
- Audio link: Bluetooth LE Audio, one earpiece, mono.
- Keep the ceramic chip antenna clear of the cell and metal; the antenna end of the board faces the outside of the case with at least 10 mm of metal-free space.

## Firmware pin constants

Toolchain is nRF Connect SDK (Zephyr). Silk Dn maps to devicetree connector `xiao_d` index n, and the io-channels/OLED nodes live in `firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay`.

```c
#include <nrf_gpio.h>
#define PIN_BTN_CALL1 NRF_GPIO_PIN_MAP(1, 4)   // D0, P1.04, catcher
#define PIN_BTN_CALL2 NRF_GPIO_PIN_MAP(1, 5)   // D1, P1.05, catcher
#define PIN_BTN_CALL3 NRF_GPIO_PIN_MAP(1, 6)   // D2, P1.06, catcher
#define PIN_BTN_CALL4 NRF_GPIO_PIN_MAP(1, 7)   // D3, P1.07, catcher
#define PIN_BTN_BACK  NRF_GPIO_PIN_MAP(2, 10)  // D13, P2.10, catcher
#define PIN_BTN_THROW NRF_GPIO_PIN_MAP(1, 5)   // D1, P1.05, pitcher / SS / CF
#define OLED_ADDR     0x3C
```
