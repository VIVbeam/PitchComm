# Case design: wearing, sight lines, and protection

Internal rationale for the V2 enclosures. User-facing print/assembly instructions are in `cad/unbranded/README.md`; this file records why the control faces are where they are and what has to be checked on a body.

## Stances and sight lines

The two display units are read while the player is looking down and forward, not while standing upright. The control faces are therefore sloped instead of flat.

- **Catcher, one-knee-down (OKD) and two-point stances.** The pod rides on the outside of the throwing-side (bare-hand) knee guard — the right knee for a right-handed catcher — because the mitt hand can reach nothing. Eyes sit roughly 0.9 to 1.1 m above the ground; the pod sits roughly 0.45 to 0.55 m up the leg, about 0.35 to 0.5 m forward of the eyes. The look-down line is roughly 35 to 60 degrees below horizontal. The control face is tilted about 18 degrees from the pod back so its normal stays within about 35 degrees of that line in both stances. The carrier is symmetric, so a left-handed catcher flips the pod to the left knee and the Back button stays on the hand end.
- **Fielder, fielding stance (belt mount).** Bent forward, eyes roughly 1.1 to 1.4 m and the belt pod roughly 1.0 to 1.2 m, looking down and forward. The display face is tilted about 22 degrees so it faces up toward the eyes instead of the ground.
- **Fielder, wrist mount.** Arm bent, pod on the forearm with the display tilted about 22 degrees toward the elbow-to-eye line. This is a sports-watch posture: the pod is read at a glance, not stared at.
- Nothing here is measured on a body yet. The angles are design intent; the first printed pod is checked in each stance before the carrier is committed.

## Reach and controls

- Catcher: four 12 mm buttons in a row under the screen, operated with the bare throwing hand; the mitt hand never has to touch a control, and no control is placed where only the glove can reach it. Back is a separate recessed button at the bare-hand end, 1 mm deeper than the call buttons so it is not cancelled by a gloved brush. Buttons never transmit on press alone; the menu confirms.
- Pitcher: one 12 mm recall/volume button on a sloped top face, large enough to hit with a glove. It is the only control.
- Fielder: one 12 mm recall button on the display face below the screen, pressed with the bare hand (or bumped with the glove heel); the screen is the primary output and recall only wakes it. The pod can be worn on either forearm because the display tilts toward the elbow, so it faces the eyes when the arm is bent. Default is the throwing-side (bare) forearm, where the same hand can reach the recall button without crossing the body; the glove-side forearm remains an option for players who prefer the glove-side sight line.

## Size decisions

- The pod body stays a thin V1-style tray; only a raised, sloped control deck (the dashboard) is tilted. This keeps the flat stack near the cell thickness instead of making the whole case a wedge.
- Actual sizes: pitcher 42 x 63.5 mm, flat 14.7 mm; fielder 46 x 56 mm, flat 14.3 mm, 19.9 mm at the dashboard; catcher 48 x 80 mm, flat 16.8 mm, 23.9 mm at the dashboard. The pitcher is 1.5 mm over its 62 mm target because the 850 mAh cell (45 mm) plus a 12 mm switch plus walls do not compress further; the other targets are met.
- The 500 mAh cell (29 x 36 x 4.75 mm) is the wrist-size limiter, not the board: the fielder's 46 x 56 mm footprint is sports-watch scale, with the cell and board stacked under the dashboard.
- The 850 mAh cell (34.5 x 45 x 6.2 mm) plus the catcher's five switches and the 128x32 OLED set the catcher pod, with the four call buttons in a column along the pod length so the width across the shin stays at 48 mm.
- If the owner later accepts a smaller cell, the fielder pod can shrink toward a true watch.

## Damage resistance

- Every OLED sits behind a raised bezel with a hood lip, so the glass cannot rest on a flat surface in any orientation.
- Button caps sit in collars; caps are wider than their holes, so they cannot fall in, and their faces are recessed so snags do not pull them off.
- Impact walls are 2.4 mm at the corners; the carrier wraps the back; the charge cap is recessed.
- An internal deck separates the cell from the board, and the cell gets foam allowance front and back. This is for puncture and pressure, not drop energy.
- The case is splash-resistant at best. The charge cap is the only opening.

## Family and color

- Three shapes: catcher, pitcher, fielder. The fielder has one pod with two carriers (25 mm wrist, 45 mm belt).
- Body cyan `#74D7EE`, lid and accents pink `#FFAFC8`, plungers white `#FFFFFF`; the colored 3MF files and `palette.json` name the same set as the V1 printables.
- Board end opposite the USB-C connector keeps a 10 mm metal-free band for the ceramic chip antenna.

## Checks before a full print set

1. Fit coupon: screws, strap webbing, lid lip.
2. Caliper pass on the board, OLED module, cell, and switch bodies against `cad/unbranded/profiles.json`.
3. Sight line in each stance with a taped-together pod.
4. One body/lid pair dropped and rained on before printing the rest.
