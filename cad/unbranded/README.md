# PitchComm field pods — print and wear guide

Three printable pods, one per field role. Each pod holds one Seeed XIAO
nRF54L15, one protected Li-ion cell, an internal deck that keeps the cell away
from the board, and a raised control deck on the lid that tilts the display and
controls toward the wearer. Everything is in millimetres; every number lives in
`profiles.json` and `generate_cases.py` rebuilds the whole set.

Nothing here has been test-fitted. Print the fit coupon and one body/lid pair
before committing a full set, and run the caliper checks at the end of this
file.

## Files

| Suffix | What it is |
| --- | --- |
| `_body.stl` | Flat tapered tray: floor, walls, wide rim, hanging screw bosses, deck ledges, cell bay rails, switch pedestals where used, USB-C opening |
| `_lid.stl` | Flat lid with inset lip, screw counterbores, and the raised control deck: sloped display head plus a button plateau/pad |
| `_deck.stl` | Cell cover with boss notches, collar notches, pull-tab pocket and charge-plug clearance |
| `_charge_cap.stl` | Friction frame plug; pries out with a fingernail |
| `_<mount>_carrier.stl` | Back plate following the case outline with two strap loops |
| `_plunger_*.stl` | Captive caps: plain (pitcher, fielder) or numbered (catcher); `_plunger_back` on the catcher |
| `_label_*.stl` | Press-in digit labels for the numbered caps |
| `_display_bezel.stl` | Pink bezel with a protective hood bar on the display head |
| `_window.stl` | Optional 1.5 mm acrylic window (vendored part, not printed) |

Each part also has a `_color.stl` copy, and each style exports
`<style>_colored.3mf` (assembled) and `<style>_lid_colored.3mf` (lid print
group). `exports/palette.json` maps the colors. STL files carry no color
information (`stl_color_support: false`).

Styles: `receiver` = pitcher, `wrist` = fielder (shortstop / center field),
`keypad` = catcher.

Previews: `preview.png` (assembled color render), `parts-preview.png`
(labelled part sheet with inch captions), `mounts-preview.png`,
`ergonomics-preview.png` (side profiles with the assumed stance angles).
`exports/<style>_plan.svg` shows the internal layout. Renders are made with a
built-in software renderer because trimesh's OpenGL preview needs pyglet,
which is not installed here.

## Fit coupon first

`exports/fit_coupon.stl` is a 64 x 72 x 3 mm plate:

- holes 2.2 / 2.6 / 2.8 / 3.3 mm for the M2.5 pilot and clearance fits,
- a 25 x 2.8 mm and a 45 x 2.8 mm strap window so the actual webbing can be
  threaded before printing a carrier.

The cases assume 2.2 mm pilots, 2.8 mm lid clearance and 2.0-2.5 mm webbing.
Retune `profiles.json` and regenerate rather than drilling printed parts.

## Sizes and colors

| Style | Case W x L | W x L x max H (in) | Flat body height | Max height | Control deck | Carriers |
| --- | --- | --- | --- | --- | --- | --- |
| Pitcher (`receiver`) | 42 x 63.5 mm | 1.65 x 2.50 x 0.58 | 14.7 mm | 14.7 mm | flat face, one button | 45 mm belt |
| Fielder (`wrist`) | 46 x 56 mm | 1.81 x 2.20 x 0.78 | 14.3 mm | 19.9 mm | 18 deg display head + button pad | 25 mm wrist + 45 mm belt |
| Catcher (`keypad`) | 48 x 80 mm | 1.89 x 3.15 x 0.94 | 16.8 mm | 23.9 mm | 18 deg display head + call plateau | 25 mm guard |

The pitcher has no display; its one recall cap sits 0.2 mm below its collar top
in a 13.6 mm well in the flat face. Both sloped heads carry the OLED in a
2.5 mm seat under a pink bezel; the catcher's four call caps sit in a column
along the pod at a 14 mm pitch with the numbered labels pressed in.

Colors follow the family palette: body, deck, charge cap and carriers cyan
`#74D7EE`; lid, bezel and side caps pink `#FFAFC8`; face plungers white
`#FFFFFF`; press-in labels cyan. The antenna end of the board keeps a 10 mm
metal-free band; the cell sits below the deck.

## Print settings

- PETG (ASA for hot cars or full sun), 0.2 mm layers, 0.25 mm first layer.
- 4 perimeters, 5 top / bottom layers, 25 % gyroid infill.
- Bodies: as exported, floor on the bed.
- Lids: as exported, deck up. The inner collars and the lip ring sit on the
  bed and the flat plate bridges between them; the wells, window and bezel all
  open upward, so the display face needs no supports. If the bridge between
  the collars sags, enable tree supports under the plate only.
- Carriers: as exported, plate on the bed, loops up. The tunnel ceilings are
  bridges; clean up any droop so the strap slides.
- Plungers and labels: as exported, cap face on the bed.
- Charge cap and fit coupon: as exported, flat.

## Assembly

1. Trim the tactile switch legs flush and solder wires to the outer pins.
2. OLED: nest the module into the display seat from inside the lid, screen
   against the window, and tape the rim down with foam tape. Keep the
   connector toward the low edge of the head.
3. Cell: tape it into the bay between the rails, plug the JST into the board,
   and route the pigtail and protection board away from the antenna end.
4. Board: sit the PCB on the deck standoffs and press it up until the lid pads
   touch, then tape the pads. Parts face the lid.
5. Switches: pitcher and fielder, drop each switch into its lid collar and let
   it rest on the printed pedestal. Catcher, the four call switches rest on
   the cell's own tape; add a 0.2 mm shim if the cell sits low. Catcher Back
   slides into the end-wall counterbore.
6. Press each plunger onto its switch actuator from outside. Numbered caps take
   the press-in label; a dab of gel CA locks a cap if wanted.
7. Deck: lay it on the ledges over the cell, notches over the bosses and
   collar tubes.
8. Slide the lid on (the lip enters the cavity), fit the M2.5 screws (8-10 mm),
   and stop when snug. The catcher uses three screws; its fourth (low-left)
   corner is over the board's USB end and stays open. Check each button before
   the final turn.
9. Push the charge cap into its side or end opening; it is friction-held.
10. Slide the carrier onto the back and thread the strap through both loops.
    The strap is what clamps the carrier to the case; the case is symmetric so
    the pod can be flipped end for end.

## How each pod is worn

- **Pitcher** — belt pod, worn vertically. One recall cap in the flat face,
  recessed in its well. Operated with **either hand**; the cap and well are
  sized for a glove.
- **Fielder** — 25 mm wrist carrier or 45 mm belt carrier. The display head
  tilts toward the elbow, so the pod works on either forearm; the recall cap
  sits on the low pad beside the head. Operated with the **bare throwing hand**
  (bumpable with the glove heel).
- **Catcher** — 25 mm guard carrier, worn on the outside of the **throwing-side
  knee guard** (right knee for a right-handed catcher) with the long axis
  along the shin, about 48 mm across the shin. The four numbered calls run in
  a column along the shin end, the OLED sits on the sloped head beyond them,
  and the recessed Back cap is in the end wall nearest the bare hand, so a
  bare-hand sweep covers the calls and Back is a separate deliberate press.
  Operated with the **bare throwing hand only** — the mitt hand holds the
  mitt. A left-handed catcher flips the pod to the left knee; the carrier and
  pod are symmetric.

Sight lines (design intent, wear-test before trusting): the catcher's assumed
crouch puts the eyes about 0.95 m up, the pod about 0.45 m up and 0.45 m
outboard, so the eye line is 45-50 deg above horizontal and the 18 deg head
sits within about 25 deg of it. The fielding stance (bent forward, looking
down and forward) and the bent-arm wrist case are on the ergonomics sheet.

## Charging

The XIAO charges over USB-C only, with the unit off the player. Remove the
charge cap, plug in, refit the cap. Never charge a warm or damaged cell, and
charge on a non-flammable surface. The pods are splash-resistant at best; keep
them out of standing water and do not open them in the field.

## Protection expectations (design intent)

- Every screen is recessed below a proud pink bezel with a hood bar over the
  high edge, so a face-down pod rests on the bezel/hood, not the glass.
- Every button cap sits 0.2 mm below its collar top; the catcher's Back cap
  sits 0.2 mm inside its counterbore.
- The lid/body seam is on the rim; the charge opening is in a side wall
  (pitcher, fielder) or the shin-side end wall (catcher); the back is flat
  against the carrier.
- All outside edges are rounded (6 mm corners, 2 mm floor chamfer, 1 mm+ edges).

## Caliper check list before a full print set

1. XIAO: 21 x 17.8 mm outline, PCB 1.6 mm, component stack (assumed 2.0 mm)
   and the USB shell (assumed 3.2 mm tall with its centre 1.6 mm above the
   PCB's top face).
2. OLED module: 36 x 12.5 mm, thickness including connector, active area
   offset from the module centre.
3. Cells: length/width/thickness and where the pigtail exits.
4. Tactile switches: 12 x 12 x 5 mm body, actuator diameter and height, leg
   spacing; the collar bore is 12.4 mm and the lid hole is 3.8 mm.
5. Screws: M2.5 head diameter and length; the pilots are 2.2 mm.
6. Webbing: actual width and thickness against the coupon slots.
7. USB-C cable: can it fully mate through the wall opening and the shell
   pocket?
8. Wear test: strap position, the head tilt for each stance, and glove reach.

## Regenerate

```
python cad/unbranded/generate_cases.py            # all parts + coupon + previews
python cad/unbranded/generate_cases.py --only keypad
python cad/unbranded/generate_cases.py --no-preview
```

The script prints a pass/fail summary and writes it to
`exports/dimensions.json` (`validation`, plus per-style `checks`,
`ergonomics` and reserved component spaces).
