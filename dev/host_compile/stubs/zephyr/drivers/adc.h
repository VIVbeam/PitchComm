/*
 * HOST STUB: zephyr/drivers/adc.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. ADC_DT_SPEC_GET
 * resolves to the overlay's AIN7 (channel 7) in zephyr,user.
 */
#pragma once

#include <zephyr/device.h>

struct adc_dt_spec {
	const struct device *dev;
	uint8_t channel_id;
};

/* HOST STUB devicetree resolution: only io-channels = <&adc 7> is used. */
#define ADC_DT_SPEC_GET(node) { ((const struct device *)0), 7 }
#define ADC_DT_SPEC_GET_BY_IDX(node, idx) { ((const struct device *)0), 7 }
#define ADC_DT_SPEC_GET_BY_NAME(node, name) { ((const struct device *)0), 7 }

struct adc_channel_cfg {
	uint16_t gain;
	uint16_t reference;
	uint32_t acquisition_time;
	uint8_t channel_id;
	uint8_t differential;
	uint8_t input_positive;
};

struct adc_sequence {
	uint16_t channels;
	void *buffer;
	size_t buffer_size;
	uint8_t resolution;
	uint8_t oversampling;
};

#define ADC_GAIN_1_4 0x02
#define ADC_REF_INTERNAL 0x00
#define ADC_ACQ_TIME_DEFAULT 0x00

bool adc_is_ready_dt(const struct adc_dt_spec *spec);
int adc_channel_setup(const struct device *dev,
		      const struct adc_channel_cfg *channel_cfg);
int adc_read_dt(const struct adc_dt_spec *spec,
		const struct adc_sequence *sequence);
uint16_t adc_ref_internal(const struct device *dev);
