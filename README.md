# PitchComm

Baseball pitch-call system. A coach console sends pitch and play calls to worn units; the default team is four (pitcher, catcher, shortstop, center field) and more positions can be enrolled. The pitcher hears the call in a JY300 earpiece; the catcher and fielders see it on an OLED. Audio is optional per unit. After provisioning, the system runs as a closed network with no router, phone, or internet connection.

## Get started

1. Download this repository.
2. Buy the parts: [parts list](docs/bom.md).
3. Print the cases: [print list](cad/unbranded/README.md). One pitcher set, one catcher set, two fielder sets; extra positions add fielder sets. `tools/build_print_pack.ps1` writes the same STLs, 3MFs, quantities, and settings to `PitchComm-cases-print-pack.zip`.
4. Wire the units: [wiring reference](docs/wiring.md).
5. Build, flash, and provision: [firmware guide](firmware/README.md).
6. Open the coach desk: `powershell tools\start_coach_gui.ps1` and connect the coach board over USB.

## Units

| Unit | Carries | Output |
|---|---|---|
| Coach | one XIAO nRF54L15, laptop over USB | coach console |
| Catcher | XIAO nRF54L15, OLED, five buttons, 850 mAh cell | OLED |
| Pitcher | XIAO nRF54L15, recall button, 850 mAh cell | JY300 earpiece |
| Shortstop / center field / other fielders | XIAO nRF54L15, OLED, recall button, 500 mAh cell | OLED |

Vocabulary: 81 pitch calls (9 pitch types x 3 rows x 3 columns) plus 21 play calls. Any number of positions can be enrolled and audio is optional per unit; see `dev/roster.md`.

## License

Original software and printable case files are under the [MIT license](LICENSE). Dependencies keep their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
