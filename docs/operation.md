# Using PitchComm

The current software uses dictionary `94b7a24a`. Every enrolled unit, the coach console and the pitcher audio image must come from this same package. Rebuild and reload them together when updating older files. The software has passed host and simulated browser checks; hardware operation and a real Nordic SDK build still need validation.

## Call a pitch

1. Choose the pitch and announce its name. The pitcher hears, for example, “Four-Seam Fastball.”
2. Watch the pitcher. Confirm the nod yourself: **Pitcher nodded → placement** on the coach desk, or button **4 / NOD** on the catcher.
3. Choose the height and side, then send placement. The second message speaks only that location.

On the catcher, hold it horizontally with the screen above buttons **1, 2, 3, 4**. Four display columns match those buttons. Buttons 1–3 choose among the displayed pitches; 4 changes the page. After the nod, 1–3 select height and 4 confirms, then 1–3 select side and 4 sends.

**Back** lets you revise the location or height, return to the nod step, or return to pitch selection. Hold the catcher Back button to cancel a draft. On the coach desk, changing pitch requires a fresh announcement. Back cannot retract a message already transmitted; tell the player verbally if a transmitted call must be disregarded.

The console waits for matching output receipts before offering the nod step. The catcher offers NOD after the coordinator accepts its request; the caller must still observe the player's nod. Placement is rejected if matching announcement receipts are missing. **Output accepted** means output started, not proof that the player heard it. Nods are never detected automatically.

A new play or pitch call, receiver reconnect, output failure or the two-minute decision limit can invalidate the announcement. Announce again before sending placement. Do not use **Send again** blindly after an unconfirmed result; check the latest call with the player first.

## Swap batteries between innings

The operating plan is to exchange cells every inning and charge the removed cells separately. Disconnect the specified field cell before connecting the board to USB; see the [power instructions](wiring.md#power-and-battery).

The [sliding-panel case prototype](../cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt) provides side access while leaving the main lid, electronics and mount fitted. Its optional pull sling is a geometric fit study. Printed latch force, real wire clearance, sling adhesion and repeated use have not been tested.

Open the panel, unplug by the connector housings, and exchange the cell without pulling its wires or prying the pouch. Reconnect and close the panel, then wait for network and output readiness before resuming calls. Actual swap, reboot and reconnect times have not been measured.
