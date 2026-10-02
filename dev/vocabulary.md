# Vocabulary and audio database

Internal spec for `config/calls.json` schema 3, the generated catalog, and the audio assets. The source recordings live in `College Demo Tracks/` (untracked). This replaces the old fixed 9 x 3 x 3 + 9 model: counts are data, not constants.

## Schema

```json
{
  "schema": 3,
  "pitches":  [{"key": 1, "label": "FOUR-SEAM", "short": "4S", "speech": "Four-Seam Fastball", "file": "A1 Four-Seam Fastball.mp3"}],
  "rows":     [{"key": 1, "label": "HIGH", "short": "HI", "speech": "High"}],
  "cols":     [{"key": 1, "label": "INSIDE", "short": "IN", "speech": "Inside"}],
  "locations":[{"row": 1, "col": 1, "speech": "High Inside", "file": "B1 High Inside.mp3"}],
  "plays":    [{"key": 1, "label": "BUNT DEF", "shortstop": "BUNT DEF", "centerfield": "BUNT DEF", "speech": "Regular Bunt Defense", "targets": ["battery", "infield", "outfield"], "file": "I4 Regular Bunt Defense.mp3"}]
}
```

Rules:

- `pitches` length M, `rows` length R, `cols` length C, `locations` length R x C in row-major order, `plays` length N. All are 1 or more; keys are contiguous from 1.
- Pitch call code = `(type - 1) * R * C + (row - 1) * C + col`, exactly the existing three-number pitch fields on the wire (`p TYPE ROW COL`).
- A pitch call carries two audio clips: the pitch `file` and the location `file`. The generated `Call.audio[2]` is empty.
- Play call code = `plays[].key`. A play reaches the enrolled units its `targets` resolve to: group names (`battery`, `infield`, `outfield`, `all`) or explicit roster keys. A play whose resolved targets include an audio unit ships its spoken clip; otherwise it stays display-only. See `dev/roster.md`.
- Display labels: pitch and play `label` and fielder `shortstop`/`centerfield` fields must be at most 11 characters so the fielder strip can render them. `short` (pitch, row, col) is at most 4 characters for the catcher menu.
- The dictionary hash is FNV-1a over the canonical JSON of `{schema, pitches, rows, cols, locations, plays}` with sorted keys, so any edit changes it.

## Generated constants

`tools/generate_catalog.py` emits into `firmware/include/pc/catalog.h`:

- `kDictionary`, `kPitchCount`, `kRows`, `kCols`, `kLocationCount`, `kPlayCount`
- `pitchCode(type, row, col)`
- `kPitchShort[]`, `kRowShort[]`, `kColShort[]` for the catcher menu
- `kCalls[]` with the pitch labels and two clip paths, and the play labels with empty audio

and into `gui/catalog.json` the same data as JSON for the coach desk.

## Clip files

Converted assets live in `data/audio/` and keep stable names:

- pitches: `/audio/p01.wav` .. `/audio/p<M>.wav`
- locations: `/audio/l1.wav` .. `/audio/l<R*C>.wav`
- all 16 kHz mono 16-bit PCM, under 5 seconds each

`tools/import_demo_audio.py` converts the selected `College Demo Tracks/*.mp3` with ffmpeg (`-ac 1 -ar 16000 -c:a pcm_s16le`), trims to the duration limit, and refuses to run when an output would exceed it. The source MP3s stay untracked; only the WAVs are committed.

## Current content (schema 3)

Pitches: A1 Four-Seam Fastball, A2 Curveball, A3 Slider, A4 Changeup, A5 Sinker, A6 Two-Seam Fastball, G7 Cutter, J6 Sweeper, J8 Splitter.

Rows: High, Middle, Low. Cols: Inside, Middle, Outside.

Locations: B1 .. B9 (High Inside, High Middle, High Outside, Middle Inside, Middle Center, Middle Outside, Low Inside, Low Middle, Low Outside).

Plays: the tactical subset only: pickoffs and picks (A7-A9, I1-I3, I8, I9, Q1-Q8), bunt defense and wheel (I4-I7, Q6), outfield depth (C7, C8), and pitcher tactics (Pitch Around, Ignore Runner). Hitting signals, squeezes, steals, mechanics cues, and motivation tracks are dropped. Every play carries a `targets` list resolved against the enrolled roster.

## Workflow after an edit

1. Edit `config/calls.json`.
2. `python tools/import_demo_audio.py` (only when the file list changed).
3. `python tools/generate_catalog.py`.
4. `python tools/check_audio.py`.
5. `python tools/build_audio_fs.py` (self-verifies the image and HEX).
6. Rebuild the firmware and reload the audio filesystem on the pitcher.
