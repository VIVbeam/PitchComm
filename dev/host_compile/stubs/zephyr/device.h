/*
 * HOST STUB: zephyr/device.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Devicetree macros
 * resolve to fixed host values matching the XIAO nRF54L15 overlay.
 */
#pragma once

#include <zephyr/sys/util.h>

struct device {
	int unused;
};

int device_is_ready(const struct device *dev);

/* HOST STUB devicetree resolution: labels and paths are opaque tokens. */
#define DT_NODELABEL(label) label
#define DT_PATH(path) path
#define DT_REG_ADDR(node) 0x3c /* only ssd1306 is queried */
/* Geometry matching the base 128x32 overlay; display64 changes the real
 * devicetree only. display.cpp reads exactly width and height. */
#define DT_PROP(node, prop) DT_PROP_STUB_##prop
#define DT_PROP_STUB_width 128
#define DT_PROP_STUB_height 32
#define DEVICE_DT_GET(node) ((const struct device *)0)
#define DEVICE_DT_GET_ANY(compat) ((const struct device *)0)
#define DEVICE_DT_GET_ONE(compat) ((const struct device *)0)
