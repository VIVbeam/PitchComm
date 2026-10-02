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
| littlefs-python | Host tool to build the clip filesystem | MIT | https://github.com/jrast/littlefs-python |
| trimesh / manifold3d | Host case generator | MIT / Apache-2.0 | https://github.com/mikedh/trimesh, https://github.com/elalish/manifold |

Portions of `firmware/src/audio_source.c` are adapted from the Zephyr sample `samples/bluetooth/audio/bap_unicast_client`, Copyright (c) Nordic Semiconductor ASA, used under the Apache-2.0 license. The adapted file retains its upstream attribution. The 5x7 font in `firmware/src/display.cpp` is ported from the Adafruit GFX `glcdfont.c` (BSD license, Copyright (c) Limor Fried), with attribution in the file.

Refer to each package's license for its exact terms. Versions are pinned by NCS v3.4.0 and the Python packages named above.
