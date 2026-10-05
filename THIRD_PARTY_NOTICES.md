# Third-party software

The MIT license does not replace dependency licenses. Dependencies are installed locally or built by the toolchain and are not bundled with this source except where noted.

| Dependency | Used for | License | Upstream |
|---|---|---|---|
| Zephyr RTOS | Firmware kernel and drivers | Apache-2.0 | https://github.com/zephyrproject-rtos/zephyr |
| nRF Connect SDK | Nordic libraries, SoftDevice Controller, OpenThread integration | LicenseRef-Nordic-5-Clause | https://github.com/nrfconnect/sdk-nrf |
| OpenThread | 802.15.4 / Thread stack | BSD-3-Clause | https://github.com/openthread/openthread |
| libLC3 | LC3 encode/decode | Apache-2.0 | https://github.com/google/liblc3 |
| Mbed TLS | Crypto for Thread/Bluetooth | Apache-2.0 | https://github.com/Mbed-TLS/mbedtls |
| LittleFS | Audio clip filesystem | BSD-3-Clause | https://github.com/littlefs-project/littlefs |

Portions of `firmware/src/audio_source.c` are adapted from the Zephyr sample
`samples/bluetooth/bap_unicast_client`, Copyright (c) 2021-2025 Nordic
Semiconductor ASA, used under [Apache-2.0](LICENSES/Apache-2.0.txt).
The adapted file carries attribution and a modification notice. The 5x7 font
in `firmware/src/display.cpp` is ported from Adafruit GFX `glcdfont.c`,
Copyright (c) 2012 Adafruit Industries, with attribution in the file and the
[BSD license text](LICENSES/Adafruit-GFX.txt) included here.

Refer to each package's license for its exact terms. The firmware SDK version
is specified in `firmware/ncs_version.txt`. Setup tools use Python's standard
library and Windows PowerShell.

The spoken recordings in the supplied audio image are included with ownership
or redistribution permission confirmed on 2026-10-04. This is separate from the
MIT license for the original software and printable cases.
