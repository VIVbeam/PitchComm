# Case design notes

Internal rationale for the pod shapes. The user-facing print and assembly guide is `cad/unbranded/README.md`.

## Why the pitcher head is tilted

The pitcher pod sits flat against a belt or a pocket, so a flat face points sideways or at the ground; its control deck is tilted 18 degrees so the screen still faces the wearer when the pod rides low. The catcher and the fielder watch are flat: the catcher is worn across the front of the leg guard and read from above, and the watch sits on top of the wrist.

## Controls

- Catcher: four numbered calls in a column beside the screen and the Back cap are operated with the bare throwing hand. The mitt hand holds the mitt and operates nothing; no control is placed where only the glove can reach it. Back is recessed 1 mm deeper than the call caps so a brush does not cancel a draft. The pod is worn across the front of the leg guard; the screen reads left to right looking down the leg.
- Pitcher: one recall/volume cap on the flat face, sized to hit with a glove.
- Fielder watch: one recall cap beside the display on the flat face, pressed with the bare hand or bumped with the glove heel. The case takes any 20 mm NATO strap through the printed fixed bars; no carrier, no tools.

## Size

Actual sizes with the one-game 100 mAh cell (`dev/cad/dimensions.json`): pitcher 30.0 x 48.6 mm, flat 12.0 mm; watch 45.8 x 50.1 mm, flat 12.0 mm, 12.4 mm at the deck, 55.1 mm lug to lug; catcher 43.0 x 64.9 mm, flat 16.7 mm, 17.1 mm at the hood, worn landscape across the leg.

- The pitcher shrank 55 percent by envelope. Its width is set by the board and the recall collar between the screw bosses, and its length by the recall collar, the 31 mm cell and the 45 mm belt loop channel.
- The watch grew 5 percent in envelope against the smallest fielder because the 0.96 inch module reserves a 27.3 x 27.8 mm box against the old strip's 36 x 12.5, but it prints with half the plastic, drops the maximum height from 17.6 to 12.4 mm, and needs no separate wrist or belt carrier.
- The catcher turned landscape: the display moved from the end of the pod to beside the 1-to-4 button column, cutting the length from 78.0 to 64.9 mm and the maximum height from 23.8 to 17.1 mm, at a 12.7 percent envelope cut. Width 43.0 is check-bound: the 21 mm board must sit beside the 13.4 mm button collars because putting it under them collides with the switch pedestals and crosses the antenna keepout; length is bound by the four collars, the front screw boss and the Back switch wall. Flat 16.7 is the 12 mm Back switch body between the floor and the lid lip. A 2x2 button cluster could reach about 41 x 44 mm, but the owner chose the column layout.
- Electronics are the floor everywhere now: the 21 x 17.8 mm board, the OLED module, the switch bodies and the antenna keepout. The 500 and 850 mAh cells do not fit these shells; a multi-game build would need the older, larger case set.

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
2. Caliper pass on the board, both OLED modules (0.91 inch 128x32 and 0.96 inch 128x64), the cell, and the switch bodies against `dev/cad/profiles.json`.
3. One body/lid pair carried where you intend to wear it, then dropped and rained on, before printing the rest.
