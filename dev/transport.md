# PitchComm transport: call engine on Zephyr + 802.15.4

How the portable call engine (`engine.h`, `protocol.h`) runs on a XIAO nRF54L15 with Zephyr / nRF Connect SDK. The engine is reusable C++; the Thread transport is new. This file now records both the design and the implemented shape.

## 1. The engine

Three header-only C++ modules, copied unchanged from the proven core:

| File | Notes |
|---|---|
| `firmware/include/pc/protocol.h` | `Packet`, `encode`/`decode`, enums, constants |
| `firmware/include/pc/catalog.h` | generated from `config/calls.json`; regenerate, do not hand-edit |
| `firmware/include/pc/engine.h` | header-only `Engine`; depends only on the two above |

The engine has no platform dependencies. Only `firmware/src/main.cpp` (`AppHooks` plus threads) is platform code. Constants stay in milliseconds:

| Constant | Value | Meaning |
|---|---|---|
| `kUnitCount` | 5 | Coach plus the enrolled roster (default pitcher, catcher, shortstop, center) |
| `kPacketBytes` | 56 | wire payload, explicit little-endian |
| `kProtocolVersion` | 1 | byte `b[2]` |
| `kCallWindow` | 1000 ms | call lifetime |
| `kLinkTimeout` | 3500 ms | peer considered gone |
| `kOldCall` | 15000 ms | output considered stale |

- `elapsed()`/`newer()` are `uint32_t` wrap math, valid only for milliseconds (wrap ~49.7 days). Never feed microseconds.
- `Engine` API (`submit`, `tick`, `receive`, `outputFailed`, accessors) is unchanged.
- The core is verified on the host by `firmware/tests/test_core.cpp` (3348 checks, 0 failures) including handshake, call/ACK, duplicate suppression, requests, expiry, USB gate, catcher menu, button filtering, clock-wrap behavior, lossy and reordered links, multi-node fairness, and 100k-buffer protocol fuzzing.

## 2. Transport: Thread, not Zigbee

Both sit on IEEE 802.15.4. The link is a closed star: the coach is the only talker, the field units are listeners; a field unit sends only heartbeats, ACKs, and pitch requests back. We need a low-latency unicast datagram pipe, not a mesh and not an application layer.

| Criterion | Thread (OpenThread) | Zigbee |
|---|---|---|
| Support on nRF54L15 in NCS | Native; Thread 1.4 in current releases | Zigbee R23 is an add-on for nRF54L |
| Zephyr integration | First-class; OpenThread in-tree, Zephyr sockets + L2 | First-class, but heavier app layer (ZCL, APS, BDB) |
| Fit to our app | IPv6/UDP datagrams; we keep our own protocol | Its ZCL/APS layer would go unused |
| Sleepy nodes | Sleepy End Device (SED) is a core role | End device, also works |
| Latency, 5 nodes, small payload | Under 50 ms typical; one frame, no fragmentation | Similar |

**Pick Thread.** Our 56-byte packet fits a single 802.15.4 frame (max PSDU 127 B), so no 6LoWPAN fragmentation. Only UDPv6 is used; Thread's leader election and mesh routing are overhead we do not need at this size but come for free.

No border router and no phone are needed. The coach is the leader (`CONFIG_OPENTHREAD_FTD`); each field unit is a Sleepy End Device (`CONFIG_OPENTHREAD_MTD` + `CONFIG_OPENTHREAD_MTD_SED`, 200 ms poll period). Sockets use the Zephyr BSD API (`zsock_socket(AF_INET6, SOCK_DGRAM, IPPROTO_UDP)`).

### Provisioning: pre-shared dataset

`tools/provision.py` generates one closed Thread dataset per team and writes it into `firmware/include/app/team_config.h`:

- one EUI-64 extended address per unit (coach plus the enrolled roster),
- active dataset: channel (11-26, default 15), PAN ID, extended PAN ID, network key, mesh-local ULA prefix, network name `PitchComm-XXXX`,
- UDP port 45678 (constant).

Every unit is built with the same dataset and calls `otDatasetSetActive()` + `otThreadSetEnabled()` at boot (`CONFIG_OPENTHREAD_MANUAL_START=y`). The coach comes up first and becomes leader; the field units attach as children. No commissioner or PSKd exchange is needed at the field: the network key is already in every image. A per-device PSKd is stored in `config/team.local.json` only for future joiner-based commissioning.

### Addressing

- Each unit sets its 802.15.4 extended address to its provisioned EUI-64 (`otLinkSetExtendedAddress`) before enabling Thread.
- Link-local IPv6 addresses are therefore deterministic: `fe80::/64` plus the EUI-64 with the universal/local bit flipped. The coach computes every enrolled unit's address, and every unit can compute the coach's.
- Outgoing datagrams set `sin6_scope_id` from the default network interface; incoming datagrams are matched against the unit link-local addresses to identify the source unit.
- The engine's `authenticatedSource` argument is meaningful because Thread binds a node's link-local address to its EUI-64 and encrypts/authenticates at the MAC layer with the network key.

No application HMAC is added: the 56-byte payload stays 56 bytes, and a node cannot spoof another's source address without the network key. Revisit only if a threat model appears.

## 3. Hook mapping

The engine calls these on its own thread. None may block on the radio or audio: enqueue and return.

| Hook | V2 implementation |
|---|---|
| `send(p)` | `pc::encode` to 56 bytes, `pc_link_send(target, bytes, 56)` pushes to the radio TX `k_msgq`; false on a full queue, which the engine treats as a failed transmit and retries |
| `present(out)` | audio units: `pc_audio_play()` (queues, does not block); display units: `board::Display` frame/strip; controls units also drive the OLED menu |
| `clearOutput()` | `pc_audio_stop()` and wake the display |

On-air framing: the app payload is the 56-byte `encode()` output sent as one UDPv6 datagram. Thread handles addressing and MAC retries.

## 4. Task and clock model

| Concern | Zephyr |
|---|---|
| entry | `main()` creates threads, then returns |
| engine cadence | engine `k_thread`; `k_msleep(1)` |
| clock | `k_uptime_get_32()` (ms), direct |
| inbox | `k_msgq`, depth 12, filled by the radio callback |
| TX queue | `k_msgq`, depth 8, drained by the radio thread |
| radio thread | `zsock_poll` 2 ms + TX drain; RX callback enqueues only |
| console | `console_getline()` thread |
| UI / audio | main thread (UI) plus one audio thread on audio units |

`CONFIG_SYS_CLOCK_TICKS_PER_SEC=1000` so `k_msleep(1)` is truly 1 ms.

Thread layout:

- **engine thread** (priority 6): drain inbox, `receive(src, pkt, now, now - receivedAt)`, then `tick(now)`, 1 ms cadence.
- **radio thread** (`thread_link.c`, priority 4): owns the UDP socket, drains the TX queue, polls RX, resolves the source unit from the link-local address, calls the inbox callback.
- **main thread** (priority 7, lowest application thread): UI drawing, buttons, battery, catcher menu, serial console parse loop. A full OLED frame is a multi-millisecond I2C transfer and must not delay radio or audio.
- **console thread** (priority 7): blocks on `console_getline()`.
- **audio thread** (priority 5, pitcher/proof): BAP unicast client, LC3 encode, LittleFS clips.

Radio callbacks and audio callbacks never call the engine directly except through the bounded inbox.

## 4.1 Request, shake-off, and timing

Workflow constants: `kCallWindow` 1000 ms, request retry 100 ms, ACK resend 80 ms, SED poll period 200 ms, radio thread 2 ms, engine cadence 1 ms.

One catcher pitch request, measured from the Send button release on the catcher:

| Step | Time |
|---|---|
| Button filter stable release | 35 ms |
| Engine tick + radio queue | <= 3 ms |
| Thread uplink to the coach | 10-40 ms typical |
| Coach engine accept and queue the response | <= 2 ms |
| Downlink to the Sleepy End Device | 0-200 ms (poll phase; budget the worst case) |
| Response handling and OLED write | <= 15 ms |

Expected about 130 ms, worst case about 260 ms from release to the catcher seeing the call. The pitcher hears the same call on the same schedule, and the coach marks it delivered or missing within the 1000 ms call window.

Shake-off: there is no in-system shake-off message. The pitcher shakes his head, and the catcher selects the next pitch. Re-selecting the three axes usually takes longer than the call window, so the coach module is free; if a request does arrive inside the window, the coach answers Busy. The catcher menu re-arms the last selection on Busy or expiry (`CatcherMenu::restore`), so the retry is one press. No person accepts anything: the coach module is the relay, and the human coach only originates calls from the laptop.

A four-pitch sequence with three shake-offs is dominated by human selection time (roughly 8-15 s); the radio link contributes well under 1 s across all four calls.

## 5. File layout (V2)

- `firmware/src/main.cpp`: unit app, `AppHooks`, engine thread, console, UI loop.
- `firmware/src/thread_link.c`: OpenThread bring-up and UDP transport.
- `firmware/include/app/thread_link.h`: transport contract.
- `firmware/include/app/team_config.example.h`: committed placeholder; `team_config.h` is generated.
- `firmware/src/audio_source.c`, `firmware/src/storage.c`: LE Audio source and clip storage.
- `firmware/src/display.cpp`, `buttons.cpp`, `battery.cpp`: board drivers.
- `firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay`: OLED, ADC channel, display choice.
- `firmware/roles/*.conf`: per-unit Kconfig fragments.
- `firmware/tests/`: host tests for the portable core.
- `tools/provision.py`, `tools/build_firmware.ps1`, `tools/flash_firmware.ps1`.

Unchanged input: `config/calls.json` to `firmware/include/pc/catalog.h`.

## 6. Risk

The engine is a proven quantity; the new bugs are all in the transport. Keep the radio thread thin. First hardware checks are in `dev/test-checklist.md`: handshake, call/ACK, retry and expiry on one field unit before adding audio; then both links on one board.
