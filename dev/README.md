# Maintainer checks

The portable checks run without boards or the Nordic SDK. From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_repo.ps1
```

This runs package validation, all portable firmware and GUI suites, and build
plans for all five units in the standard and minimum-size/no-bootloader layouts.
It uses only files in this repository. To run a suite individually:

```powershell
firmware/tests/run_host_tests.ps1
firmware/tests/run_audio_tests.ps1
firmware/tests/run_application_tests.ps1
gui/test/run_tests.ps1
python tools/check_setup.py
```

The firmware scripts need `g++` on PATH (`clang++` also works for the core/audio suites); `-Compiler` selects another compiler path. Each runner temporarily puts that compiler's directory first on PATH for its runtime libraries and restores PATH afterward. The combined command prefers PowerShell 7 for compiler tests when available. The GUI suite needs Node.js. Setup uses Python 3.

The current suites check 4,623 core assertions, 340 shared protocol assertions, 146 audio assertions, 40 application assertions and 82 GUI tests. Core tests include pitch receiver timeout, late readiness, both inbound/timer processing orders, clock rollover and recovery through a fresh announcement. A fielder outage alone preserves the pitch decision.

The application suite exercises the actual firmware application with host mutex, queue and panel models. It checks consistent coach snapshots during concurrent receiver traffic, bounded console ownership, processing while a display transfer is stalled, exact-message completion receipts, failed/expired transfers and the catcher's four-second call display. Its support headers are test-only; they do not replace Zephyr or establish real scheduling or I2C behavior.

These are host checks. They do not establish Nordic SDK build size, board flashing, audible output, radio performance, battery life or printed fit. The matched bundle's `verification/` folder records separate simulated browser and CAD checks.

## First SDK build

Use the SDK pinned in `firmware/ncs_version.txt` (currently v3.4.0) and the
board target `xiao_nrf54l15/nrf54l15/cpuapp`. Open its toolchain shell and run
from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_repo.ps1
powershell -NoProfile -File tools\build_firmware.ps1 -Units coach -Pristine -StrictSize
```

The first coach build supports reading chip IDs before provisioning. Follow
the [firmware guide](../firmware/README.md) to enroll boards, then build all
units with `-Pristine -StrictSize`. Record the SDK/toolchain version, commands,
flash/RAM usage and build results for every unit. Host checks and dry-run plans
do not confirm SDK APIs, Kconfig, linking or flash layout.

Build outputs belong in ignored `firmware/build/`. The local team file and
generated team header stay ignored. Generated distribution ZIPs and crash
reports also stay local; the field-fit ZIP is a packaged checkpoint and is not
automatically refreshed when source files change.

## Current completion and backlog — October 5, 2026

Dictionary `94b7a24a` includes two-step pitch calling, invalidation after a
pitch receiver loses contact, protected engine snapshots, bounded console
ownership and completed display receipts. Portable checks pass at the counts
above. The current fit prototype is
[v8 sliding-panel battery access](../cad/prototypes/side-slider-v8/PRINT_AND_ASSEMBLY.txt);
`cad/unbranded` and `cad/autocad` retain the earlier v20 layout.

Remaining work:

1. Build all units with the real pinned Nordic SDK and measure flash/RAM size.
2. Flash and validate provisioning, earbud speech, displays/buttons and concurrent Thread/LE Audio.
3. Qualify actual cells, connectors, full leads/slack, strain relief, mounted swaps and slider/sling durability.
4. Measure radio range/latency, current/runtime and field durability.
5. Review audio/transport callback readiness and error reporting against the copied UI view; these are review targets, not confirmed defects.

Older maintainer tools were intentionally archived outside the shipped product.
The verification command above does not require that archive. Superseded local
CAD copies are preserved under ignored `.tools/cleanup-sdk-20261005/archive/`;
current v8 and v20 files and the v18/v19 comparison drawings remain in place.
The complete historical handoff is in `.tools/WORK_STATUS.txt`; its latest
checkpoint supersedes older summaries.
