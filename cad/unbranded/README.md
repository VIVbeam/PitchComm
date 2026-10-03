# Cases

Print files for the field units. All dimensions in millimetres.

## Print list

| Unit | Sets | Files |
|---|---|---|
| Pitcher | 1 | `receiver_body`, `receiver_lid`, `receiver_deck`, `receiver_charge_cap`, `receiver_belt_carrier`, `receiver_plunger_1` |
| Catcher | 1 | `keypad_body`, `keypad_lid`, `keypad_deck`, `keypad_charge_cap`, `keypad_guard_carrier`, `keypad_plunger_call_1..4`, `keypad_plunger_back`, `keypad_label_call_1..4`, `keypad_display_bezel` |
| Shortstop | 1 | `wrist_body`, `wrist_lid`, `wrist_deck`, `wrist_charge_cap`, `wrist_plunger_1`, `wrist_display_bezel` |
| Center field | 1 | same as shortstop |
| Fit check | 1 | `exports/fit_coupon` |

The STLs are in `exports/`. Not printed: `*_color.stl` (same meshes for colour printers), `*_colored.3mf` and `*_lid_colored.3mf` (grouped print files), and the previews. Screws, webbing, wire, cells, and headphones are in the [parts list](../../docs/bom.md).

## Fielder watch

The fielder is a flat watch: 45.8 x 50.1 mm body, 12.0 mm flat, 55.1 mm lug to lug over two printed fixed bars (51.1 mm between bar axes). The bars are 4 mm and stand 2.2 mm off the case back, so a 20 mm NATO or single-pass strap threads under both; a standard 1.2 to 1.5 mm NATO fits with clearance, up to about 2.0 mm. There is no metal in the strap path. The 0.96 inch 128x64 SSD1306 module (PCB 27.3 x 27.8 mm) sits under the bezel window with its 21.74 x 10.86 mm active area centred; the recall cap is beside the display. Two M2.5 screws plus the lid lip close the watch.

## Print first

`exports/fit_coupon.stl` is a 64 x 72 x 3 mm plate with 2.2 / 2.6 / 2.8 / 3.3 mm holes and 25 / 45 mm strap slots. Check the screws, webbing, and lid fit on the coupon before printing the full set.

## Settings

- PETG; ASA for hot cars or full sun.
- 0.2 mm layers, 0.25 mm first layer, 4 perimeters, 5 top/bottom layers, 25 % gyroid.
- No supports. Bodies and carriers print as exported (floor/plate on the bed); the watch body prints with its printed bars on the bed. Lids print deck up. Charge caps print flange down. Plungers print flange up.
- If the lid plate sags between the collars, add tree supports under the plate only.

## Assemble one unit

1. Solder the switch wires and trim the switch legs.
2. Press each switch into its lid collar, then the cap onto the actuator.
3. Tape the OLED into the lid recess, screen toward the bezel window.
4. Tape the board to the lid standoffs, parts facing the cell.
5. Tape the cell into the bay. Route the pigtail and protection board away from the board antenna end.
6. Lay the deck on the ledges over the cell.
7. Fit the lid and screws: three M2.5 x 8 to 10 mm for the pitcher and catcher, two for the fielder watch. Snug only.
8. Push the charge cap into its opening.
9. Strap up: slide the carrier onto the pitcher or catcher and thread the strap through both loops. The fielder watch takes a 20 mm NATO threaded under both printed bars.

## Wear

- Pitcher: belt carrier, or a pocket. One button, either hand.
- Fielder: 20 mm NATO watch strap, either wrist. One button, bare hand.
- Catcher: 25 mm guard carrier or a torso strap. Four calls plus Back, bare throwing hand only.

## Charge

USB-C only, unit off the player. The charge cap is the only opening. Splash-resistant, not waterproof.

## Cells

The slim shells are sized for a protected 100 mAh pouch, Adafruit 1570 class, 11.5 x 31 x 3.8 mm. The older 500 mAh (29 x 36 x 4.75 mm) and 850 mAh (34.5 x 45 x 6.2 mm) cells do not fit these cases; that cell class needs the older, larger shell set.

## Check with calipers

- Board 21 x 17.8 mm, OLED 36 x 12.5 mm (catcher) or 27.3 x 27.8 mm (fielder watch), cell 11.5 x 31 x 3.8 mm, and switches.
- Fielder watch: a 20 mm strap threads under both printed bars with the watch off the wrist.
- USB-C cable mates through the wall opening.
- Screw heads fit the counterbores; webbing fits the coupon slots.
