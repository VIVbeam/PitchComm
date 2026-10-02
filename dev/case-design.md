# Case design notes

Internal rationale for the pod shapes. The user-facing print and assembly guide is `cad/unbranded/README.md`.

## Why the display heads are tilted

The pods sit flat against a leg, belt, or forearm, so a flat face points sideways or at the ground. The control deck is tilted 15-22 degrees so the screen still faces the wearer when the pod rides low. Placement is the user's choice; the pods and carriers are symmetric, so a pod can be flipped end for end.

## Controls

- Catcher: four numbered calls and the Back cap are operated with the bare throwing hand. The mitt hand holds the mitt and operates nothing; no control is placed where only the glove can reach it. Back is recessed 1 mm deeper than the call caps so a brush does not cancel a draft.
- Pitcher: one recall/volume cap on the flat face, sized to hit with a glove.
- Fielder: one recall cap beside the display head, pressed with the bare hand or bumped with the glove heel. The pod fits either forearm.

## Size

Actual sizes: pitcher 42 x 63.5 mm, flat 14.7 mm; fielder 46 x 56 mm, flat 14.3 mm, 19.9 mm at the deck; catcher 48 x 80 mm, flat 16.8 mm, 23.9 mm at the deck.

- The 500 mAh cell (29 x 36 x 4.75 mm) sets the fielder thickness; the board stacks above it under the deck.
- The 850 mAh cell (34.5 x 45 x 6.2 mm) plus the five switches and the OLED set the catcher; the call caps run along the long side to keep the width small.
- The pitcher is 1.5 mm over its 62 mm target because the 45 mm cell, a 12 mm switch, and the walls do not compress further.

If the owner later accepts a smaller cell, the fielder pod can shrink toward a true watch.

## Damage resistance

- Every OLED sits behind a raised bezel with a hood bar, so the glass cannot rest on a flat surface in any orientation.
- Button caps sit in collars; caps are wider than their holes, so they cannot fall in, and their faces are recessed so snags do not pull them off.
- Impact walls are 2.4 mm at the corners; the carrier wraps the back; the charge cap is recessed.
- An internal deck separates the cell from the board, and the cell gets foam allowance front and back. This is for puncture and pressure, not drop energy.
- The case is splash-resistant at best. The charge cap is the only opening.

## Family and color

- Three shapes: catcher, pitcher, fielder. The fielder has one pod with two carriers (25 mm wrist, 45 mm belt).
- Body cyan `#74D7EE`, lid and accents pink `#FFAFC8`, plungers white `#FFFFFF`; the colored 3MF files and `palette.json` name the same set as the V1 printables.
- The board end opposite the USB-C connector keeps a 10 mm metal-free band for the ceramic chip antenna.

## Checks before a full print set

1. Fit coupon: screws, strap webbing, lid lip.
2. Caliper pass on the board, OLED module, cell, and switch bodies against `dev/cad/profiles.json`.
3. One body/lid pair carried where you intend to wear it, then dropped and rained on, before printing the rest.
