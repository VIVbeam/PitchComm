/*
 * HOST STUB: zephyr/drivers/display.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <zephyr/device.h>

struct display_capabilities {
	uint16_t x_resolution;
	uint16_t y_resolution;
	uint8_t supported_pixel_formats;
	uint8_t screen_info;
	uint8_t current_pixel_format;
	uint8_t current_orientation;
};

struct display_buffer_descriptor {
	uint32_t buf_size;
	uint16_t width;
	uint16_t height;
	uint16_t pitch;
	bool frame_incomplete;
};

int display_blanking_off(const struct device *dev);
int display_blanking_on(const struct device *dev);
void display_get_capabilities(const struct device *dev,
			      struct display_capabilities *capabilities);
int display_write(const struct device *dev, uint16_t x, uint16_t y,
		  const struct display_buffer_descriptor *desc,
		  const void *buf);
