/*
 * PitchComm buttons for the XIAO nRF54L15 (Zephyr / NCS).
 *
 * Field button: one active-low recall button on D1 = P1.05 with an internal
 * pull-up. 30 ms debounce, 700 ms long press. Released reads raw 1;
 * pressed (pin to GND) reads raw 0.
 *
 * Catcher keypad: four numbered calls on D0..D3 = P1.04..P1.07 plus Back on
 * D13 = P2.10, all pin-to-GND with internal pull-ups. Events are filtered by
 * the shared pc::CatcherButtons model (35 ms startup/release block, chord
 * rejection, event numbers 1..4 on a numbered release, 5 on a Back short
 * release and 6 on a Back long hold).
 */

#include "board/buttons.h"

#if defined(CONFIG_PITCHCOMM_FIELD_BUTTON) || defined(CONFIG_PITCHCOMM_CATCHER_MENU)

#include <cstdint>

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
#include "pc/newcatcher_menu.h"
#endif

namespace board {
namespace {

const struct device* const gGpio1 = DEVICE_DT_GET(DT_NODELABEL(gpio1));

inline uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }

}  // namespace

#if defined(CONFIG_PITCHCOMM_FIELD_BUTTON)

namespace {

/* Pitcher / fielder recall: D1 = P1.05, pin to GND. */
constexpr uint8_t kFieldButtonPin = 5;

bool gButtonReady = false;
bool gRawDown = false;
bool gHeld = false;
bool gLongReported = false;
uint32_t gChanged = 0;
uint32_t gPressedAt = 0;

}  // namespace

void Button::begin() {
  gButtonReady = false;
  gRawDown = false;
  gHeld = false;
  gLongReported = false;
  gChanged = 0;
  gPressedAt = 0;
  if (!device_is_ready(gGpio1)) {
    return;
  }
  if (gpio_pin_configure(gGpio1, kFieldButtonPin,
                         GPIO_INPUT | GPIO_PULL_UP) != 0) {
    return;
  }
  gButtonReady = true;
}

Button::Event Button::tick(uint32_t now) {
  if (!gButtonReady) {
    return Event::None;
  }
  const bool down = gpio_pin_get_raw(gGpio1, kFieldButtonPin) == 0;
  if (down != gRawDown) {
    gRawDown = down;
    gChanged = now;
  }
  if (gRawDown != gHeld && elapsed(now, gChanged) >= 30) {
    gHeld = gRawDown;
    if (gHeld) {
      gPressedAt = now;
      gLongReported = false;
    } else if (!gLongReported) {
      return Event::Press;
    }
  }
  if (gHeld && !gLongReported && elapsed(now, gPressedAt) >= 700) {
    gLongReported = true;
    return Event::LongPress;
  }
  return Event::None;
}

#endif /* CONFIG_PITCHCOMM_FIELD_BUTTON */

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)

namespace {

const struct device* const gGpio2 = DEVICE_DT_GET(DT_NODELABEL(gpio2));

/* Catcher keypad: D0..D3 = P1.04..P1.07 (calls 1..4), D13 = P2.10 (Back). */
constexpr uint8_t kCallPins[4] = {4, 5, 6, 7};
constexpr uint8_t kBackPin = 10;

pc::CatcherButtons gFilter;
uint32_t gScanAt = 0;

}  // namespace

bool CatcherControls::begin() {
  present_ = false;
  if (!device_is_ready(gGpio1) || !device_is_ready(gGpio2)) {
    return false;
  }
  bool ok = true;
  for (uint8_t pin : kCallPins) {
    if (gpio_pin_configure(gGpio1, pin, GPIO_INPUT | GPIO_PULL_UP) != 0) {
      ok = false;
    }
  }
  if (gpio_pin_configure(gGpio2, kBackPin, GPIO_INPUT | GPIO_PULL_UP) != 0) {
    ok = false;
  }
  present_ = ok;
  return ok;
}

bool CatcherControls::available() const { return present_; }

unsigned CatcherControls::tick(uint32_t now) {
  if (!present_) {
    return 0;
  }
  if (elapsed(now, gScanAt) < 10) {
    return 0;
  }
  gScanAt = now;

  uint8_t mask = 0;
  for (uint8_t i = 0; i < 4; ++i) {
    if (gpio_pin_get_raw(gGpio1, kCallPins[i]) == 0) {
      mask |= static_cast<uint8_t>(1u << i);
    }
  }
  if (gpio_pin_get_raw(gGpio2, kBackPin) == 0) {
    mask |= 0x10;
  }
  return gFilter.tick(mask, true, now);
}

#endif /* CONFIG_PITCHCOMM_CATCHER_MENU */

} // namespace board

#endif /* CONFIG_PITCHCOMM_FIELD_BUTTON || CONFIG_PITCHCOMM_CATCHER_MENU */
