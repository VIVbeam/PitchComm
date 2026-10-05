# PitchComm

Baseball pitch-call system for a coach, pitcher, catcher, shortstop, and center fielder. A coach console sends pitch and play calls to worn units. The pitcher hears the call in a JY300 earpiece; the catcher and fielders see it on an OLED. After provisioning, the system runs as a closed network with no router, phone, or internet connection.

## Get started

Firmware, coach software, ready-to-flash audio, and printable cases are included.
Hardware validation is pending: no board has been flashed, and range,
latency, runtime, and enclosure durability have not been measured.

The repository includes firmware source, console, audio image and the v8 sliding-panel prototype. `PitchComm-current-field-fit-bundle.zip`, when supplied separately, is a generated local checkpoint; start with its `START_HERE.txt`. It is excluded from Git and does not automatically follow source edits. Firmware binaries still require a Nordic SDK build; the included print geometry remains a fit prototype.

Disconnect the specified 100 mAh field cell before any USB connection to its board. The stock board charger is set to 200 mA, above the cell's 100 mA limit. Charge the disconnected cell separately with the external charger at 100 mA; see the [power and battery instructions](docs/wiring.md#power-and-battery).

The field operating plan is to swap batteries every inning and charge removed cells on separate two-pin JST chargers. Spare-cell and charging-channel quantities are still to be sized. Easy battery access is a case-design requirement; the current screw-fastened cases have not been qualified for repeated inning swaps.

A [complete sliding-panel battery-access fit prototype](cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt) is available with matching controls, arranged print plates and an editable AutoCAD assembly. Its battery panel stays captive while the lid and mount remain fitted. An optional thin pull sling has a checked removal path; the watch gains an anchor land within its existing outside dimensions. Geometry checks pass; actual sling adhesion, connector wiring, printed fit and repeated-use durability still need qualification. [Download the prototype package](cad/prototypes/PitchComm-side-slider-v8-battery-access-fit.zip).

1. **Download** this repository.
2. **Buy the parts**: [parts list](docs/bom.md).
3. **Make a fit prototype**: [sliding-panel print guide](cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt). One pitcher set, one catcher set, two fielder sets. This matched set includes the horizontal four-button catcher layout. Validate an unpowered fit print before installing cells or electronics. The preserved [v20 case files](cad/unbranded/README.md) and `tools/build_print_pack.ps1` use the earlier case layout.
4. **Wire the units**: [wiring reference](docs/wiring.md).
5. **Build, flash, and provision**: [firmware guide](firmware/README.md).
6. **Open the coach desk**: `powershell tools\start_coach_gui.ps1` and connect the coach board over USB.

## Units

| Unit | Carries | Output |
|---|---|---|
| Coach | one XIAO nRF54L15, laptop over USB | coach console |
| Catcher | XIAO nRF54L15, 128x32 OLED, five buttons, 100 mAh cell | OLED |
| Pitcher | XIAO nRF54L15, recall button, 100 mAh cell | JY300 earbud |
| Shortstop / center field / other fielders | XIAO nRF54L15, 128x64 OLED watch, recall button, NATO strap, 100 mAh cell | OLED |

## Vocabulary

Nine pitch types x three heights x three sides (81 pitch calls) plus 21 play calls (including nine defensive plays). Firmware, coach catalog, roster, and audio are supplied as one matched set.

Pitch calls use two steps: announce the pitch name, confirm the pitcher's observed nod, then send placement. Back lets the caller revise before placement. The catcher uses four menu columns aligned with buttons 1–4 beneath the screen. See the [operating guide](docs/operation.md).

The current dictionary is `94b7a24a`. Updating from an older package requires rebuilding every enrolled unit and reloading the pitcher audio image together with the coach console. Software checks and simulated browser tests pass; a real Nordic SDK build and hardware operation remain unverified.

Portable regression suites and shared fixtures are included; see the [maintainer checks and SDK-build preparation](dev/README.md). Run `powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_repo.ps1` before the first SDK build.

## Files

| Location | Contents |
|---|---|
| `firmware/` | Zephyr / nRF Connect SDK application |
| `gui/` | Offline coach console (browser + Web Serial) |
| `config/roster.json` | Unit keys and capabilities for this package |
| `data/audio/` | Ready-to-flash calls and checksum |
| `tools/` | Build, flash, provisioning, and audio tools |
| `cad/unbranded/` | Printable STLs, 3MFs, and print guide |
| `cad/autocad/` | Native DWG working assembly, component references and verification |

## License

Original software and printable case files are under the [MIT license](LICENSE). Dependencies keep their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
