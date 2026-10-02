# PitchComm field-unit firmware.
# nRF Connect SDK (Zephyr) application for the Seeed XIAO nRF54L15.
#
# Build one role at a time; tools/build_firmware.ps1 wraps these calls:
#   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware \
#     -d firmware/build/coach -- \
#     -DEXTRA_CONF_FILE=roles/coach.conf
#   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware \
#     -d firmware/build/pitcher -- \
#     -DEXTRA_CONF_FILE="roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf"

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(pitchcomm)

target_include_directories(app PRIVATE include)

target_sources(app PRIVATE
  src/main.cpp
  src/thread_link.c
)

zephyr_sources_ifdef(CONFIG_PITCHCOMM_AUDIO
  src/audio_source.c
  src/storage.c
)

zephyr_sources_ifdef(CONFIG_PITCHCOMM_DISPLAY
  src/display.cpp
)

zephyr_sources_ifdef(CONFIG_PITCHCOMM_FIELD_BUTTON
  src/buttons.cpp
)

zephyr_sources_ifdef(CONFIG_PITCHCOMM_CATCHER_MENU
  src/buttons.cpp
)

zephyr_sources_ifdef(CONFIG_PITCHCOMM_BATTERY
  src/battery.cpp
)
