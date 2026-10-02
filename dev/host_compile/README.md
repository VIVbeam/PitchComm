# PitchComm host syntax-check harness

Compiles the PitchComm firmware sources with the host `gcc`/`g++` using
`-fsyntax-only`, so syntax and preprocessor errors surface before an NCS
toolchain is available. Zephyr, OpenThread, Bluetooth and LC3 headers are
provided by declaration-only stubs under `dev/host_compile/stubs/`.

This is a fast gate for editing `firmware/src/*` and `firmware/include/**`.
It is not a substitute for a real `west build`.

## Layout

```
dev/host_compile/
  run.ps1              base pass plus optional -Provisioned, -MinSize, -RawI2c,
                       -RosterVariant, -Strict modes
  stubs/               declaration-only stand-in headers (all marked HOST STUB)
  roster-variant.json  six-unit roster fixture used by -RosterVariant
  catalog_probe.cpp    static_assert probe compiled against the variant catalog
  README.md            this file
```

## How to run

From the repository root, with `gcc` and `g++` on `PATH`:

```
powershell -NoProfile -ExecutionPolicy Bypass -File dev/host_compile\run.ps1
```

PowerShell 7+:

```
pwsh -NoProfile -File dev/host_compile/run.ps1
```

Options:

| Option | Meaning |
| --- | --- |
| `-Roles coach,catcher,...` | Check only the named roles. Default is all seven. |
| `-Provisioned` | Check the provisioned build path with a temporary `PC_TEAM_CONFIGURED 1` header. |
| `-MinSize` | Recheck every role with the `roles/min-size.conf` effects applied. |
| `-RawI2c` | Check the `display.cpp` raw I2C fallback with `CONFIG_SSD1306` undefined. |
| `-RosterVariant` | Render a catalog for `roster-variant.json`, stage a 7-unit `team_config.h`, and compile the probe plus `thread_link.c`. |
| `-Strict` | Add extra warning flags; warnings are informational, not failures. |
| `-SkipAudio` | Skip `storage.c` and `audio_source.c` for `pitcher` and `proof`, printing a SKIP note. |
| `-CompilerC path` | Override the C compiler (default: `gcc` from `PATH`). |
| `-CompilerCpp path` | Override the C++ compiler (default: `g++` from `PATH`). |

Each file is compiled with:

```
gcc   -fsyntax-only -Wall -Wextra -Werror -std=gnu11   -I firmware/include -I dev/host_compile/stubs ...
g++   -fsyntax-only -Wall -Wextra -Werror -std=gnu++17 -I firmware/include -I dev/host_compile/stubs ...
```

The script prints PASS or FAIL plus the compiler output for every file and
exits 0 only when every attempted check passed.

## Modes

Modes are additional passes layered on the default base run. They can be
combined in one invocation:

```
pwsh -NoProfile -File dev/host_compile/run.ps1 -Provisioned -MinSize -RawI2c -Strict
```

| Mode | Extra checks | What it does |
| --- | --- | --- |
| `-Provisioned` | 14 | Generates a temporary `app/team_config.h` shaped like `team_config.example.h` with `PC_TEAM_CONFIGURED 1`, unique nonzero EUIs, and lab channel, PAN ID, keys and prefix. The temp directory is added with `-I` before `firmware/include`, and `main.cpp` plus `thread_link.c` are recompiled for all seven roles, so the provisioned branch (including its `_Static_assert` on the network name) is parsed. `firmware/include/app/team_config.h` is never written to, and the temp directory is removed afterwards even when a check fails. |
| `-MinSize` | 29 | Applies the `roles/min-size.conf` effects to every role: `CONFIG_LOG` and `CONFIG_ASSERT` are omitted (`n` in Kconfig), `CONFIG_OPENTHREAD_DEBUG` is omitted, `CONFIG_OPENTHREAD_NUM_MESSAGE_BUFFERS` becomes 32, `CONFIG_OPENTHREAD_MAX_CHILDREN` becomes 4, then every role source is recompiled. |
| `-RawI2c` | 3 | Recompiles `display.cpp` for catcher, shortstop and center with `CONFIG_SSD1306` removed (and `CONFIG_I2C` still set), so the raw SSD1306 fallback branch is parsed instead of the in-tree driver branch. |
| `-RosterVariant` | 2 | Copies `config/calls.json` and `dev/host_compile/roster-variant.json` into a temporary config root, then renders two files into a temporary overlay of the real headers: the variant `catalog.h` with `tools/generate_catalog.py` and the matching `app/team_config.h` with `tools/provision.py`'s `header_text` (`PC_TEAM_UNIT_COUNT 7`, seven EUI rows in unit order). `catalog_probe.cpp` and `firmware/src/thread_link.c` (C11) are compiled against that overlay, so the catalog values and the Thread transport's `PC_TEAM_UNIT_COUNT` sizing are both checked with six enrolled units. `load()`/`render()` are read only, never `generate()`, so the committed `catalog.h`, `gui/catalog.json` and `build/validation.lock` stay untouched. |
| `-Strict` | adds notes | Adds `-Wundef -Wshadow -Wcast-qual -Wpointer-arith -Wstrict-prototypes -Wmissing-prototypes -Wmissing-declarations`, drops `-Werror`, and prints warnings as `NOTE` lines with a per-mode note count. `-Wstrict-prototypes` and `-Wmissing-prototypes` go to C files only because g++ rejects them for C++. Compile errors still fail the run. |

With every mode enabled the run performs 77 checks: 29 base, 29 min-size,
3 raw I2C, 14 provisioned, 1 variant catalog probe, and 1 seven-unit Thread
transport.

### Variant roster mode

`-RosterVariant` proves that the generator and the portable firmware headers
agree on a roster the repo does not ship. Relative to `config/roster.json`,
`dev/host_compile/roster-variant.json`:

* enrolls `right` (display and audio) and the custom key `bench` (display and
  pitch reception) in addition to the default pitcher, catcher, shortstop and
  center;
* switches `center` from display-only to display and audio;
* leaves the copied `config/calls.json` unchanged.

That mixture exercises the data paths a larger roster changes: enrollment
order (so `PC_UNIT_right` is 5 and the custom `PC_UNIT_bench` is 6),
`kUnitCount == 7`, one mask bit per unit, capability arrays, pitch recipients
(`pitcher`, `catcher` and `bench`, mask 70), the `all` group now reaching
`right`, the `outfield` group changing from center only to center plus right,
and the `SEE DOWN` play gaining `/audio/d18.wav` because both of its resolved
targets now have audio. A missing generated define stops the probe at compile
time and is reported as a normal FAIL check.

The same pass stages `app/team_config.h` through `tools/provision.py`'s
`header_text`, so the header carries `PC_TEAM_UNIT_COUNT 7` and seven
`team_eui64` rows in unit order (coach, pitcher, catcher, shortstop, center,
right, bench). The count line and the row count are checked before the file is
written, and the run prints
`team PC_TEAM_UNIT_COUNT 7  EUI rows 7  unit order: ...`. `thread_link.c` is
then compiled against that header with the field-unit define set, which pins
that the transport's peer address table, EUI setup loop and receive loop size
themselves from `PC_TEAM_UNIT_COUNT` instead of the default five. The
generator and provision imports keep `-B`, so `tools/__pycache__` is not
written either.

Because a quoted include such as `units.h -> "catalog.h"` resolves next to the
including header first, the variant catalog only takes effect inside a
temporary copy of `firmware/include`. The real `firmware/include`, `config/`
and `build/` trees are only read, and the temporary root is removed even when
a check fails.

## Roles and files checked

The default run performs 29 checks.

| Role | Macro set highlights | Sources |
| --- | --- | --- |
| coach | FTD leader, console, settings, no audio/display, no `PC_UNIT` (falls back to kCoach) | main.cpp, thread_link.c |
| catcher | `PC_UNIT=PC_UNIT_catcher`, OLED + catcher menu + keypad + battery, Thread SED | main.cpp, thread_link.c, display.cpp, buttons.cpp, battery.cpp |
| pitcher | `PC_UNIT=PC_UNIT_pitcher`, LE Audio + field button + battery, Thread SED | main.cpp, thread_link.c, buttons.cpp, battery.cpp, storage.c, audio_source.c |
| shortstop | `PC_UNIT=PC_UNIT_shortstop`, OLED + field button + battery, Thread SED | main.cpp, thread_link.c, display.cpp, buttons.cpp, battery.cpp |
| center | `PC_UNIT=PC_UNIT_center`, OLED + field button + battery, Thread SED | main.cpp, thread_link.c, display.cpp, buttons.cpp, battery.cpp |
| first | `PC_UNIT=PC_UNIT_first` only (not enrolled today; proves a non-default roster key compiles), Thread SED | main.cpp, thread_link.c |
| proof | LE Audio only, no Thread, no display | main.cpp, thread_link.c, storage.c, audio_source.c |

The `-D` flags mirror `firmware/prj.conf`, `firmware/Kconfig` defaults,
`firmware/roles/*.conf` (`coach.conf` or `<role>.conf` plus
`field-common.conf` where the role includes it, plus `audio-unit.conf` for
`pitcher` and `proof`), the generated catalog's `-DPC_UNIT=PC_UNIT_<key>` for
field roles, and
`firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.conf`. Kconfig booleans that
a role disables are omitted, matching `autoconf.h`, where a disabled bool is
not defined.

The overlay
`firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay` is devicetree only.
Its two effects are pinned in the stubs: the SSD1306 I2C spec is at address
0x3C and `ADC_DT_SPEC_GET(DT_PATH(zephyr_user))` resolves to AIN7.

## What is stubbed

Every stub carries a `HOST STUB:` banner and the real header path. Functions
are declared but not defined; `-fsyntax-only` never needs a linker.

| Stub | Contents used by the sources |
| --- | --- |
| `zephyr/kernel.h` | k_thread, k_msgq, k_mutex, k_event, stack macros, sleep and uptime calls |
| `zephyr/sys/atomic.h`, `sys/util.h`, `sys/byteorder.h`, `sys/printk.h` | atomic_t, IS_ENABLED, ARG_UNUSED, MIN/MAX, BIT, ARRAY_SIZE, endian helpers |
| `zephyr/random/random.h` | sys_rand32_get |
| `zephyr/device.h` | struct device, device_is_ready, DEVICE_DT_GET, DT_NODELABEL, DT_REG_ADDR |
| `zephyr/drivers/gpio.h`, `drivers/adc.h`, `drivers/i2c.h`, `drivers/display.h`, `drivers/hwinfo.h` | the driver calls buttons.cpp, battery.cpp, display.cpp, thread_link.c and main.cpp use |
| `zephyr/dt-bindings/adc/nrf-saadc.h` | NRF_SAADC_AIN7 |
| `zephyr/console/console.h`, `settings/settings.h` | console_getline, settings_subsys_init/load/save |
| `zephyr/fs/fs.h`, `fs/littlefs.h`, `storage/flash_map.h` | fs_mount/read/stat, FS_LITTLEFS_DECLARE_DEFAULT_CONFIG, FIXED_PARTITION_ID |
| `zephyr/logging/log.h` | LOG_* forwarded to a variadic host function with printf format checking |
| `zephyr/net_buf.h` | net_buf/net_buf_simple and NET_BUF_POOL_FIXED_DEFINE |
| `zephyr/net/net_if.h`, `net/net_l2.h`, `net/openthread.h`, `net/socket.h` | the OpenThread bring-up and zsock_* calls in thread_link.c |
| `openthread/*.h` | instance, dataset, link, thread, ip6, netdata types and calls |
| `zephyr/bluetooth/**` | bluetooth, conn, gap, gatt, att, hci_types, uuid, iso, assigned_numbers, audio/audio.h, audio/bap.h, audio/bap_lc3_preset.h |
| `lc3.h` | lc3_setup_encoder, lc3_encode, LC3_PCM_FORMAT_S16 |

## Known gaps

* Stubs are hand-written declarations. They do not prove that an API name or
  signature exists in NCS v3.4.0, only that the source is internally
  consistent and the call shapes are plausible.
* No devicetree processing. Overlay errors (addresses, compatible strings,
  chosen nodes) are invisible here.
* `-fsyntax-only` performs no linking and no code generation, so missing
  definitions, section placement, stack sizes and runtime behavior are out of
  scope.
* The `-Provisioned` mode covers the `PC_TEAM_CONFIGURED` branch of
  `thread_link.c` with generated lab credentials in a temporary header. It
  does not test a real team file; the repo still ships only
  `team_config.example.h` with `PC_TEAM_CONFIGURED 0`, and
  `firmware/include/app/team_config.h` stays untouched.
* The `-RawI2c` mode parses the raw fallback in `display.cpp`, but every real
  role conf still selects the in-tree SSD1306 driver, so the fallback is not
  part of a normal role build.
* `roles/min-size.conf` is mirrored by `-MinSize`. No source in
  `firmware/src` currently branches on `CONFIG_LOG` or `CONFIG_ASSERT`, so
  the mode mainly guards future edits.
* `-RosterVariant` compiles the catalog probe and `thread_link.c` against the
  variant roster, but not `main.cpp` or a full role image, and it stays
  `-fsyntax-only`. It proves the generator, the provisioned header shape and
  the Thread transport sizing agree on seven units; it does not prove the
  radio or the engine runtime.
* The 16-unit ceiling in `thread_link.c` is a `_Static_assert`, not a
  permanent host check. It was verified once by hand: a temp root with a
  17-unit roster through `provision.header_text` yields
  `#define PC_TEAM_UNIT_COUNT 17` and fails to compile with
  `static assertion failed: "team unit count must fit the wire unit index"`
  at `thread_link.c:67`. The harness only stages the valid 7-unit header.
* `CONFIG_BT_ISO_TX_MTU` and `CONFIG_BT_CONN_TX_USER_DATA_SIZE` are Kconfig
  ints without explicit values in `roles/audio-unit.conf`. Representative
  values (251 and 4) are pinned in `run.ps1`.
* The base flag set is `-Wall -Wextra -Werror`. It is stricter than a default
  Zephyr build about warnings in `firmware/src`, and weaker than a real build
  for checks Zephyr enables elsewhere (for example `-Wconversion`,
  `-Wdouble-promotion`). Runtime assertions such as `__ASSERT()` are not
  expanded because `zephyr/sys/__assert.h` is not stubbed; the sources do not
  call `__ASSERT` directly.
* One known warning is deliberately not part of the base gate:
  `audio_source.c` line 693 casts `data->data` (a `const uint8_t *`) to
  `void *` for `net_buf_simple_init_with_data()`, which `-Wcast-qual` flags.
  `-Strict` reports it as a NOTE and the base set passes. Zephyr's function
  takes `void *`, so upstream callers cast the same way.

## Current status

Run on 2026-10-02 with MSYS2 gcc/g++ 16.2.0.

Every mode with the base error gate
(`run.ps1 -Provisioned -MinSize -RawI2c -RosterVariant`):

| Mode | Pass | Fail | Skip |
| --- | --- | --- | --- |
| base | 29 | 0 | 0 |
| minsize | 29 | 0 | 0 |
| rawi2c | 3 | 0 | 0 |
| provisioned | 14 | 0 | 0 |
| rostervariant | 1 | 0 | 0 |
| roster7transport | 1 | 0 | 0 |

All 77 checks pass with exit code 0, and the plain default run
(`run.ps1`) passes its 29 checks with exit code 0. Every mode was also run
with `-Strict` (`run.ps1 -Provisioned -MinSize -RawI2c -RosterVariant -Strict`):
the same 77 checks pass, exit code 0, and the only notes are the known
`audio_source.c:693` const-cast warning, reported twice in the base pass
(pitcher and proof) and twice in the min-size pass. Neither strict variant
check adds notes. No files were skipped and no fixes were required in
`firmware/src`.

The variant pass staged `team PC_TEAM_UNIT_COUNT 7  EUI rows 7  unit order:
coach, pitcher, catcher, shortstop, center, right, bench`, and
`thread_link.c` compiled against it as `roster7`. The one-off 17-unit check
described under Known gaps failed at `thread_link.c:67` as expected and is not
part of the run.

The variant rendered on that run was dictionary `0x22583391`: `kUnitCount 7`,
`PC_UNIT_right 5`, `PC_UNIT_bench 6`, `kUnitMask(bench) 64`, pitch audience
`70`, audio mask `50`, `BUNT DEF` audience `62` with `right` newly included,
`SEE DOWN` audience `48` with center and right both listening, and the
`SEE DOWN` clip `/audio/d18.wav` now present where the committed roster has no
audio unit in the outfield.
