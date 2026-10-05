# Protocol fixtures

Shared, deterministic fixtures for the PitchComm coach USB line protocol
(protocol v4). The coach GUI tests and firmware host tests consume
the same files, so a change on one side that is not mirrored on the other fails
a test instead of reaching the field.

## Files

| File | Direction | Payload |
| --- | --- | --- |
| `gui_commands.txt` | host to coach | `gui CLIENT` handshake and `call ...` commands produced by `gui/core.js` `command()` |
| `state_frames.txt` | coach to host | `@PC {...}` JSON state and result frames accepted by `gui/core.js` `validState()` and `validResult()` |
| `calls.fixture.json` | tests only | Vocabulary source targets for variable-roster group-resolution tests; runtime uses the matched generated catalog |

## Format

- One record per line. Lines starting with `#` are comments and are ignored.
- Records use single spaces between fields; nothing follows the last field.
- `gui_commands.txt` records are the exact USB line text, each ending with `\n`.
- `state_frames.txt` records start with `@PC ` and the remainder is one JSON object, matching what `LineFramer` in `gui/core.js` parses.
- The files use LF line endings and no blank lines.

## Grammar

### Commands

    gui <client>
    call <client> <id> p <type> <row> <col> <boot> <dictionary> <deadline>
    call <client> <id> d <play> <boot> <dictionary> <deadline>

Fields:

- `client`: 8 hex digits, nonzero. The value sent in the `gui` handshake and repeated in every command.
- `id`: decimal uint32, nonzero. Increments per request.
- `p` or `d`: pitch call or defensive play.
- `type`, `row`, `col`: decimal. Pitch type 1..`kPitchCount`, row 1..`kRows`, column 1..`kCols`, from `config/calls.json`.
- `play`: decimal 1..`kPlayCount`.
- `boot`: 16 hex digits, nonzero. Coach boot id.
- `dictionary`: 8 hex digits. Must match `gui/catalog.json` and the firmware `kDictionary`.
- `deadline`: decimal uint32, computed as `(coach clock + 1500) mod 2^32`. The wrap case is covered by the last two records.

These rules mirror `firmware/include/pc/controls.h` `parseUsbCall` and
`parseGuiClient`. The firmware accepts upper and lower case hex. The GUI emits
lower case, and the fixtures stay in that canonical form.

### Frames

Field documentation lives in the comment header of `state_frames.txt`. The
frames exercise idle and active states, pitch and play categories, a receiver
unit index, sequence wraparound, delivery outcomes 0 through 4, and result
values 0 through 5. `links` and `delivery` arrays are `kUnitCount` long in unit
index order, with index 0 the coach.

## Consumers

- `gui/test/conformance.test.mjs` regenerates both files in memory, compares
  them to disk, parses every command with a mirror of `parseUsbCall` and
  `parseGuiClient`, and validates every frame with `validState` and
  `validResult`.
- `firmware/tests/test_protocol_fixtures.cpp` consumes the same files with the
  real firmware parsers through `run_host_tests.ps1`; for the frame file it
  checks the `@PC ` prefix and brace balance (the Node test validates the
  fields).

## Regenerating

From the repository root:

    node gui/test/generate_fixtures.mjs

Then run the suite:

    powershell -File gui/test/run_tests.ps1

The conformance test fails when a fixture on disk differs from the generator
output, so regenerate after any change to `gui/core.js` command formatting.
The fixed session values used by `gui_commands.txt` are defined in
`gui/test/generate_fixtures.mjs`.
