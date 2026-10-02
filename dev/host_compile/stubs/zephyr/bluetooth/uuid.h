/*
 * HOST STUB: zephyr/bluetooth/uuid.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. BT_UUID_DECLARE_16
 * builds a pointer to a compound literal, as the color/assigned number
 * macros do in Zephyr.
 */
#pragma once

#include <stdint.h>

#define BT_UUID_TYPE_16 0x02

struct bt_uuid {
	uint8_t type;
};

struct bt_uuid_16 {
	struct bt_uuid uuid;
	uint16_t val;
};

#define BT_UUID_DECLARE_16(value) \
	((const struct bt_uuid *)&(const struct bt_uuid_16){ \
		.uuid = { .type = BT_UUID_TYPE_16 }, \
		.val = (value), \
	})

#define BT_UUID_ASCS BT_UUID_DECLARE_16(0x184e)

int bt_uuid_cmp(const struct bt_uuid *u1, const struct bt_uuid *u2);
