# PitchComm

Baseball pitch-call system: a coach console sends pitch and defensive-play calls to small units worn by the catcher, pitcher, shortstop, and center field. Calls arrive as speech in a neckband earpiece (pitcher and catcher) or as text on a 128 x 32 OLED (catcher, shortstop, center field). The catcher can also call a pitch through the coach.

## Get started

1. **Download** this repository.
2. **Buy the parts** [parts list](docs/bom.md).
3. **Print the cases**  [print guide](cad/unbranded/README.md).
4. **Wire the units**  [wiring reference](docs/wiring.md).
5. **Build, flash, and provision**  [firmware guide](firmware/README.md).

## Units

| Unit | Carries | Output |
|---|---|---|
| Coach | one XIAO nRF54L15, laptop over USB | coach console |
| Catcher | XIAO nRF54L15, OLED, five buttons, 850 mAh cell | JY300 earpiece + OLED |
| Pitcher | XIAO nRF54L15, recall button, 850 mAh cell | JY300 earpiece |
| Shortstop / center field | XIAO nRF54L15, OLED, recall button, 500 mAh cell | OLED |

## Vocabulary

Nine pitch types x three heights x three sides (81 pitch calls) plus nine defensive plays. The default dictionary is in `config/calls.json`; regenerate the firmware and coach files after editing it.

## Files

| Location | Contents |
|---|---|
| `firmware/` | Zephyr / nRF Connect SDK application |
| `gui/` | Offline coach console (browser + Web Serial) |
| `config/calls.json` | Pitch and defensive-play dictionary |
| `tools/` | Build, flash, provisioning, and audio tools |
| `cad/unbranded/` | Printable case sources and STLs |

## License

Original software and printable case files are under the [MIT license](LICENSE). Dependencies keep their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
