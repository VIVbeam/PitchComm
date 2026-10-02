You are building PitchComm, a DIY baseball pitch-call system: a coach console
sends pitch and defensive-play calls to small units worn by the catcher,
pitcher, shortstop, and center field, which deliver the call as audio (a
neckband headphone) or text (an OLED). The catcher both originates and receives
pitch calls.

Repo layout:
- README.md          product overview
- docs/bom.md        what to buy
- docs/wiring.md     how to wire the units
- dev/               internal build/design notes (read all of it)
- firmware/          a Zephyr / nRF Connect SDK skeleton (code starts here)
- v1/                the previous (two-board) build; git-ignored, holds the
                     reusable code

The design is decided. Do not re-derive it:

- Each field unit is a single Seeed XIAO nRF54L15 (21 x 17.8 mm; Nordic
  nRF54L15: Bluetooth 6.0 LE with LE Audio, IEEE 802.15.4, no Wi-Fi).
- Call trigger: 802.15.4 over Thread. The coach is the leader; field units are
  Sleepy End Devices. See dev/transport.md.
- Audio: LE Audio (LC3) to ONE earbud, mono only (no TWS). Headphones: HomeSpot
  JY300 neckband (LC3 / LE Audio), one for the pitcher.
- Firmware: Zephyr / nRF Connect SDK (C).
- Units:
  - Coach: board + laptop over USB.
  - Catcher: board + 128x32 OLED + four buttons + Back + cell. The catcher
    selects a pitch (type, row, column) and sends it as a request through
    the coach, then sees the delivered call on the OLED.
  - Pitcher: board + recall button + cell + JY300.
  - Shortstop / center field: board + OLED + button + cell.
- Vocabulary: 9 pitch types x 3 rows x 3 columns (81 calls) + 21 tactical plays.
  Positions are enrollable (`dev/roster.md`) and any unit can carry audio. Pitch
  calls are spoken as two clips: the pitch name and the location phrase.

Reuse V1's code, do not rewrite it. The portable C++ call engine and wire
protocol are in v1/include/pc/ (engine.h, protocol.h, catalog.h), plus the
controls, vocabulary (v1/config/calls.json), coach GUI (v1/gui/), and the
provisioning / audio-generation tooling (v1/tools/). Port all of it. Write only
the two transports (LE Audio and Thread) and the nRF54L15 board drivers new.
The engine is transport-agnostic: its send hook maps to a Thread datagram, its
present hook maps to the LE Audio source or the OLED.

Goal: bring this repo to the same completeness as V1: all firmware, case CAD,
coach GUI, provisioning, and docs written and complete, but with no hardware
in place: nothing flashed, nothing field-tested, no performance claims.

Workflow: working can only be proven on hardware, so it is a loop. Write
complete code and a "flash and test" checklist; the owner flashes a XIAO
nRF54L15 and a JY300 and reports results; you fix and repeat. Never claim
something works that has not been flashed and observed. Everything short of
that must be complete and clean.

Prove LE Audio first (flash a minimal LE Audio unicast source and get a JY300
to connect and play); see dev/le-audio-proof.md. That is the one risky unknown.

Constraints:
- User-facing docs stay minimal and product-style: plain, concise, factual, no
  filler, no "why we chose X". Only README, docs/bom.md, docs/wiring.md, and
  the firmware flashing/use guide are user-facing; keep all build/design notes
  in dev/.
- Units are as small as possible while lasting one full game and surviving a
  drop.
- Do not reference V1 or any rejected hardware in user-facing docs.

Start by reading README.md, docs/, dev/, firmware/, and v1/, then prove LE
Audio before anything else.
