# Team roster, enrollment, and per-unit audio

Internal spec for enrolling any number of positions and giving any unit optional audio. This replaces the fixed five-role model (coach, catcher, pitcher, shortstop, center field) with a roster that the tools, firmware, and coach desk all read. Counts and capabilities are data; nothing is hardcoded to four field units.

## Roster file

`config/roster.json` (committed) lists every enrollable position and its capabilities:

```json
{
  "schema": 1,
  "units": [
    {"key": "pitcher", "label": "Pitcher", "short": "P", "enrolled": true, "audio": true, "display": false, "controls": false, "pitches": true},
    {"key": "catcher", "label": "Catcher", "short": "C", "enrolled": true, "audio": false, "display": true, "controls": true, "pitches": true},
    {"key": "shortstop", "label": "Shortstop", "short": "SS", "enrolled": true, "audio": false, "display": true, "controls": false, "pitches": false},
    {"key": "center", "label": "Center field", "short": "CF", "enrolled": true, "audio": false, "display": true, "controls": false, "pitches": false}
  ]
}
```

Rules:

- Standard keys available to enroll: `pitcher`, `catcher`, `first`, `second`, `third`, `shortstop`, `left`, `center`, `right`. Custom keys are allowed and are added by hand to `config/roster.json` (`tools/roster.py` toggles the units already listed); `label` is the GUI name and `short` is at most 4 characters for the catcher menu and status lines.
- `enrolled` marks the units the team actually has. Only enrolled units appear in the desk, the generated catalog, and the audio plan.
- Capabilities: `audio` (earbud), `display` (OLED), `controls` (catcher-style menu), `pitches` (receives pitch calls), `relay` (Full Thread Device: stays receive-on and forwards for the mesh; costs battery). Plays are not a capability: each play resolves its own targets.
- The committed default enrolls only the four current field units, so today's bench builds and tests behave exactly as before. Enrolling more is a config edit plus one EUI, not firmware surgery.

## Enrollment

`config/team.local.json` (gitignored) keeps the network secrets as today; its `eui64` object maps each enrolled unit key plus `coach` to an address:

```json
{
  "eui64": {
    "coach": "AA:BB:CC:DD:EE:FF:00:00",
    "pitcher": "AA:BB:CC:DD:EE:FF:00:01",
    "catcher": "AA:BB:CC:DD:EE:FF:00:02"
  }
}
```

`tools/provision.py --coach AA:BB:.. --unit pitcher=AA:BB:.. --unit catcher=..` replaces the five fixed `--catcher/--pitcher/...` flags. It reads `config/roster.json`, requires exactly the enrolled keys plus coach, and `--from-file` still regenerates `team_config.h`. Enrollment can grow one unit at a time; the network secrets persist. A team file from before the roster change has exactly the four default keys plus coach, so it still validates unchanged.

## Enrollment CLI

`tools/roster.py` edits `config/roster.json` and regenerates the catalog in one step:

- `python tools/roster.py list` prints every unit, its index when enrolled, capabilities, and whether an EUI exists.
- `python tools/roster.py enable first` enrolls with the standard profile (pitcher: audio and pitches; catcher: display, controls and pitches; any other key: display; relay is on for every profile). Capability flags such as `--audio`, `--no-pitches`, `--controls`, `--no-relay` override individual capabilities. `relay` does not enter the dictionary; it is a build choice. A unit that must sleep for a season can be built sleepy with `--no-relay`.
- `python tools/roster.py disable first` un-enrolls; it refuses to remove the last unit with `pitches`. Both commands stage the edited roster with the real calls and validate it before writing, so a change that would leave a play with no enrolled recipient (for example disabling the only outfield unit) is refused with the file untouched.

Both commands print the provisioning and build steps to run next. Disabling warns that `config/team.local.json` and `team_config.h` still hold the unit until provisioning reruns; preflight reports that drift.

## Generated catalog

`tools/generate_catalog.py` reads `config/calls.json` and the enrolled units in `config/roster.json`, then emits:

- `kUnitCount` (coach plus enrolled units, at most 16) and one constant per unit key
- `roleMask(unit)` as `uint16_t`, one bit per unit
- recipients per call: pitch calls to every enrolled unit with `pitches`; plays to the enrolled units their targets resolve to
- `kUnitLabel[]` / `kUnitShort[]` for status lines and the desk
- the dictionary hash over `config/calls.json` plus the enrolled unit keys and capabilities (not EUIs, so re-addressing does not invalidate the vocabulary)

`gui/catalog.json` carries the same unit list so the desk renders exactly the enrolled team.

## Play targets

Every play in `config/calls.json` gets a `targets` list made of group names and unit keys:

- groups: `battery` (pitcher + catcher), `infield` (first, second, third, shortstop), `outfield` (left, center, right), `all`
- or an explicit unit key such as `"shortstop"`

A play that targets a position nobody enrolled simply reaches nobody extra. The coach desk shows the resolved SEND TO list for the selected play.

## Audio sizing

- A unit plays a call only when it has `audio` and the call targets it.
- `tools/build_audio_fs.py` includes the pitch and location clips when at least one enrolled audio unit receives pitch calls, and a play clip only when that play's resolved targets include an audio unit.
- Codec stays a build choice: `compact` (8 kHz G.711 mu-law, default, smallest) or `pcm` (16 kHz PCM). The builder prints the exact bytes against the 712 KB slot and refuses to overrun, listing the ways to shrink: compact codec, fewer audio units, or fewer audio-targeted plays. That is the budget dial.
- `tools/import_demo_audio.py` converts the clips the current roster needs, so a two-earbud bench never pays for play audio.

## Firmware mapping

- Unit 0 is the coach; each field unit build selects its roster key (`-Unit pitcher`), which chooses the generated unit index and capability flags.
- `Role` becomes the generated unit index; engine arrays, loops, delivery records, and status lines size to `kUnitCount`.
- The catcher-only request path becomes the `controls` capability.
- `pc::recipients(category, code)` reads the resolved target mask from `kCalls[]`.

## Coach desk

- The receiver rail lists the enrolled units with their capabilities.
- The play panel preview shows SEND TO from the resolved targets; receipts render one row per enrolled unit.
