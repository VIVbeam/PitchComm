# Developer notes

Internal notes for maintainers. The user-facing docs are the root `README.md`, `docs/bom.md`, `docs/wiring.md`, `cad/unbranded/README.md`, and `firmware/README.md`.

Conventions: no generated SVG assets. Diagrams are hand-made or omitted; use tables and text in docs. Do not use em-dashes (U+2014).

| File | Contents |
|---|---|
| `architecture.md` | single-chip layout, both radio links, flash map |
| `build.md` | NCS toolchain, roles, image size, no-bootloader fallback, CAD regeneration |
| `case-design.md` | why the pods are shaped the way they are |
| `le-audio-proof.md` | JY300 bring-up runbook and platform caveats |
| `roadmap.md` | build order and hardware-only open items |
| `test-checklist.md` | bench minimum and the phase-by-phase bench log |
| `transport.md` | engine mapping, Thread transport, request timing |
| `verification.md` | every `VERIFY` item and what proves it |
| `vocabulary.md` | calls.json schema 3, generated catalog, demo audio import |
| `roster.md` | enrollable positions, per-unit audio, targets, budget sizing |
| `host_compile/` | host syntax-check harness with Zephyr stub headers |
