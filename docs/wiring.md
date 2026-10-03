# PitchComm wiring reference

Five units in the base set, one Seeed XIAO nRF54L15 each (21 x 17.8 mm; Nordic nRF54L15; Bluetooth 6.0 LE Audio; 802.15.4). Extra positions wire the same as shortstop. All peripheral logic is 3.3 V. Never source peripherals from the 5V pin on battery.

## XIAO nRF54L15 pin map (silk to port)

| Silk | Port | Alt / notes |
|------|------|-------------|
| 5V   | VBUS | USB 5 V in/out; dead on battery |
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

The catcher uses 7 GPIOs (2 I2C + 5 buttons).

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

- Cell: single protected 3.7 V Li-ion or LiPo, 1S only. Watch polarity at the BAT pads.
- The XIAO has an onboard charger and charge LED. Charge over USB-C only, and only off-body: remove the unit from the player before charging.
- Do not charge and operate a hot cell. Charge in a fire-safe area on a non-flammable surface.
- Battery sense is internal: P1.14 (AIN7) reads the cell through the load switch enabled by P1.15. Do not add an external divider. The firmware enables the switch, reads ADC channel 7, and scales by 2.
- On battery the 5V pin has no voltage. Power the OLED from 3V3 only.
- Deep sleep: the Global RTC can wake the part; the RF switch stays powered to keep the ceramic antenna selected (about 60 uA). The field units poll the Thread parent every 200 ms while awake; sleep between pitches to extend runtime.

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
