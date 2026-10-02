/*
 * PitchComm battery sense for the XIAO nRF54L15 (Zephyr / NCS).
 *
 * The board senses VBAT internally on AIN7 = P1.14 through a load-switched
 * divider enabled by P1.15 (active high). docs/wiring.md keeps the load
 * switch on, so begin() raises it and never turns it back off.
 *
 * nRF54L15 SAADC: the internal reference is 900 mV, so with gain 1/4 the
 * full-scale pin input is 3600 mV. The board halves VBAT before the pin:
 *
 *   millivolts = raw * vref / (1/4) * 2 / 4096
 *              = raw * vref * 8 / 4096
 *
 * With the expected vref = 900 mV that is exactly the V1 scale rule
 * raw * 3600 / 4096 * 2, clamped to 6000. Eight samples are summed and
 * averaged in one integer division, as the proven V1 code did.
 * VERIFY: adc_ref_internal() must report 900 on the nRF54L15 SAADC; the
 * fallback keeps the previous behaviour if a driver reports 0.
 */

#include "board/battery.h"

#if defined(CONFIG_PITCHCOMM_BATTERY)

#if !defined(CONFIG_ADC)
#error "PitchComm battery: CONFIG_ADC=y is required for the nRF SAADC driver."
#endif

#include <cstdint>

#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#if defined(CONFIG_ADC_CONFIGURABLE_INPUTS)
#include <zephyr/dt-bindings/adc/nrf-saadc.h>
#endif

namespace board {
namespace {

/* P1.15 enables the internal VBAT divider load switch (active high). */
constexpr uint8_t kDividerEnablePin = 15;

/* AIN7 = P1.14, through the internal divider (scale x2). */
const struct adc_dt_spec gVbat = ADC_DT_SPEC_GET(DT_PATH(zephyr_user));
const struct device* const gGpio1 = DEVICE_DT_GET(DT_NODELABEL(gpio1));

constexpr uint32_t kSampleIntervalMs = 500;
constexpr uint32_t kSamples = 8;
constexpr uint32_t kFallbackVrefMv = 900; /* VERIFY: nRF54L15 internal ref */
constexpr uint32_t kMaxMillivolts = 6000;

bool gAdcReady = false;
bool gDividerOn = false;

inline uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }

void enableDivider() {
  if (gDividerOn || !device_is_ready(gGpio1)) {
    return;
  }
  /* VERIFY: P1.15 is active high and is also claimed by the board's
   * vbat_pwr regulator (regulator-boot-on), so this is normally a no-op.
   * It is intentionally never disabled. */
  if (gpio_pin_configure(gGpio1, kDividerEnablePin, GPIO_OUTPUT_ACTIVE) == 0) {
    gpio_pin_set(gGpio1, kDividerEnablePin, 1);
    gDividerOn = true;
  }
}

}  // namespace

void Battery::begin() {
  enableDivider();
  if (!adc_is_ready_dt(&gVbat)) {
    return;
  }
  struct adc_channel_cfg cfg{};
  cfg.gain = ADC_GAIN_1_4;
  cfg.reference = ADC_REF_INTERNAL;
  cfg.acquisition_time = ADC_ACQ_TIME_DEFAULT;
  cfg.channel_id = gVbat.channel_id;
  cfg.differential = 0;
#if defined(CONFIG_ADC_CONFIGURABLE_INPUTS)
  /* VERIFY: the nRF SAADC driver selects ADC_CONFIGURABLE_INPUTS, so the
   * physical input must be named explicitly; AIN7 is P1.14. */
  cfg.input_positive = NRF_SAADC_AIN7;
#endif
  if (adc_channel_setup(gVbat.dev, &cfg) != 0) {
    return;
  }
  gAdcReady = true;
}

void Battery::tick(uint32_t now) {
  if (!gAdcReady) {
    return;
  }
  if (sampled_ && elapsed(now, sampledAt_) < kSampleIntervalMs) {
    return;
  }

  int32_t sum = 0;
  for (uint32_t i = 0; i < kSamples; ++i) {
    int16_t raw = 0;
    struct adc_sequence sequence{};
    sequence.channels = BIT(gVbat.channel_id);
    sequence.buffer = &raw;
    sequence.buffer_size = sizeof(raw);
    sequence.resolution = 12;
    if (adc_read_dt(&gVbat, &sequence) != 0) {
      return; /* keep the previous reading */
    }
    if (raw < 0) {
      raw = 0; /* single-ended readings cannot be negative */
    }
    sum += raw;
  }

  uint32_t vrefMv = adc_ref_internal(gVbat.dev);
  if (vrefMv == 0) {
    vrefMv = kFallbackVrefMv;
  }

  /* Per sample: raw * vref / (gain = 1/4) / 4096, then x2 for the divider.
   * Averaged over 8 samples: (sum/8) * vref * 8 / 4096 = sum * vref / 4096. */
  uint32_t millivolts = static_cast<uint32_t>(sum) * vrefMv / 4096u;
  if (millivolts > kMaxMillivolts) {
    millivolts = kMaxMillivolts;
  }
  millivolts_ = millivolts;
  sampledAt_ = now;
  sampled_ = true;
}

uint32_t Battery::millivolts() const { return millivolts_; }

/* V1 windows: a cell in this window is low but still powers the rail. */
bool Battery::low() const { return millivolts_ >= 2800 && millivolts_ < 3500; }

/* V1 window in which the LE Audio rail is trusted to stay up. */
bool Battery::audioPower() const {
  return millivolts_ >= 3100 && millivolts_ <= 4400;
}

} // namespace board

#endif /* CONFIG_PITCHCOMM_BATTERY */
