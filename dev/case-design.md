# Case design notes

Internal rationale for the pod shapes. The user-facing print and assembly guide is `cad/unbranded/README.md`.

## Why the pitcher head is tilted

The pitcher pod sits flat against a belt or a pocket, so a flat face points sideways or at the ground; its control deck is tilted 18 degrees so the screen still faces the wearer when the pod rides low. The catcher and the fielder watch are flat: the catcher is worn across the front of the leg guard and read from above, and the watch sits on top of the wrist.

## Controls

- Catcher: four numbered calls in a column beside the screen and the Back cap are operated with the bare throwing hand. The mitt hand holds the mitt and operates nothing; no control is placed where only the glove can reach it. Back is recessed 1 mm deeper than the call caps so a brush does not cancel a draft. The pod is worn across the front of the leg guard; the screen reads left to right looking down the leg.
- Pitcher: one recall/volume cap on the flat face, sized to hit with a glove.
- Fielder watch: one recall cap beside the display on the flat face, pressed with the bare hand or bumped with the glove heel. The case takes any 20 mm NATO strap through the printed fixed bars; no carrier, no tools.
- Every switch is the 6 x 6 x 4.3 mm Omron B3F-1000 class under a printed captive plunger: call caps 10.5 mm, recall caps 12 mm, Back 7 mm. The small switch body is what let every collar and the catcher wall shrink.

## Size

Actual sizes with the one-game 100 mAh cell and 6 mm switches (`dev/cad/dimensions.json`): pitcher 30.0 x 48.6 mm, flat 12.0 mm; watch 45.8 x 50.1 mm, flat 12.0 mm, 12.4 mm at the deck, 55.1 mm lug to lug; catcher 37.0 x 58.2 mm, flat 13.0 mm, 13.4 mm at the hood, worn landscape across the leg.

- The pitcher shrank 55 percent by envelope; the watch 25 percent against the original shells, printing 60 percent less plastic and dropping its maximum height from 19.9 to 12.4 mm with no separate wrist or belt carrier. Both are board and cell-stack bound at 12.0 mm flat.
- The catcher turned landscape, then dropped the switch class: the display moved beside the 1-to-4 column and the 6 mm switch replaced the 12 mm part, so the pod went from 41.0 x 78.0 mm at 16.7 mm flat to 37.0 x 58.2 mm at 13.0 mm flat, a 57 percent envelope cut against the original. Width 37.0 is check-bound by the 21 mm board beside the 7.4 mm collars and the USB-C shell allowance; length by the 36 mm module over the column at a 12.2 mm pitch and the Back switch wall; flat 13.0 by the rotated module stack over the deck, with 0.2 mm to spare. The old 12 mm Back switch body no longer sets the wall.
- The 6 mm switch and the 100 mAh cell are what make the game-size build possible; the remaining floor is the 21 x 17.8 mm board, the two OLED modules, the switch bodies and the antenna keepout. The 500 and 850 mAh cells do not fit these shells; a multi-game build would need the older, larger case set.
- Fasteners: three M2.5 x 8 mm self-tapping screws each for the pitcher and catcher, two for the watch, all inserted from the attachment side into blind pilots in lid bosses. The control face has no holes, and the carrier or NATO strap comes off before the case opens. The pitcher and catcher cell bays shifted in x to clear the screw columns.

## Damage resistance

- Every OLED sits behind a raised bezel with a hood bar, so the glass cannot rest on a flat surface in any orientation.
- Button caps sit in collars; caps are wider than their holes, so they cannot fall in, and their faces are recessed so snags do not pull them off.
- Impact walls are 2.4 mm at the corners; the pitcher belt carrier wraps the back, the catcher guard takes the strap, and the watch relies on its 2 mm shell and the NATO bars; the charge cap is recessed.
- An internal deck separates the cell from the board, and the cell gets foam allowance front and back. This is for puncture and pressure, not drop energy.
- The case is splash-resistant at best. The charge cap is the only opening.

## Family and color

- Three shapes: catcher, pitcher, fielder. The fielder is a watch with integrated 20 mm NATO bars and no separate carrier; the pitcher and catcher keep their belt carrier and guard straps.
- Body cyan `#74D7EE`, lid and accents pink `#FFAFC8`, plungers white `#FFFFFF`; the colored 3MF files and `palette.json` name the same set as the V1 printables.
- The board end opposite the USB-C connector keeps a 10 mm metal-free band for the ceramic chip antenna.

## Checks before a full print set

1. Fit coupon: screws, strap webbing, lid lip.
2. Caliper pass on the board, both OLED modules (0.91 inch 128x32 and 0.96 inch 128x64), the cell, the 6 x 6 x 4.3 mm switch bodies, and the printed caps against `dev/cad/profiles.json`.
3. One body/lid pair carried where you intend to wear it, then dropped and rained on, before printing the rest.
