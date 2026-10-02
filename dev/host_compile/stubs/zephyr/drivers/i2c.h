/*
 * HOST STUB: zephyr/drivers/i2c.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. I2C_DT_SPEC_GET
 * resolves to the overlay's ssd1306 address 0x3C.
 */
#pragma once

#include <zephyr/device.h>

struct i2c_dt_spec {
	const struct device *bus;
	uint16_t addr;
};

/* HOST STUB devicetree resolution: only the SSD1306 at 0x3C is used. */
#define I2C_DT_SPEC_GET(node) { ((const struct device *)0), 0x3c }

int i2c_write_dt(const struct i2c_dt_spec *spec, const uint8_t *buf,
		 uint32_t num_bytes);
int i2c_read_dt(const struct i2c_dt_spec *spec, uint8_t *buf,
		uint32_t num_bytes);
