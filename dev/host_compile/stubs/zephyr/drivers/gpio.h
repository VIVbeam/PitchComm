/*
 * HOST STUB: zephyr/drivers/gpio.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <zephyr/device.h>

typedef uint32_t gpio_pin_t;
typedef uint32_t gpio_flags_t;

#define GPIO_INPUT 0x00000001u
#define GPIO_OUTPUT 0x00000002u
#define GPIO_OUTPUT_ACTIVE 0x00000004u
#define GPIO_PULL_UP 0x00000010u
#define GPIO_PULL_DOWN 0x00000020u

int gpio_pin_configure(const struct device *port, gpio_pin_t pin,
		       gpio_flags_t flags);
int gpio_pin_get_raw(const struct device *port, gpio_pin_t pin);
int gpio_pin_set(const struct device *port, gpio_pin_t pin, int value);
