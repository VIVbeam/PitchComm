/*
 * HOST STUB: zephyr/bluetooth/bluetooth.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Only the host,
 * address, bond, AD-parsing and scanning surface audio_source.c uses is
 * declared.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/net_buf.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
	uint8_t type;
	uint8_t a[6];
} bt_addr_t;

typedef struct {
	uint8_t type;
	bt_addr_t a;
} bt_addr_le_t;

struct bt_data {
	uint8_t type;
	uint8_t data_len;
	const uint8_t *data;
};

bool bt_data_parse(struct net_buf_simple *ad,
		   bool (*func)(struct bt_data *data, void *user_data),
		   void *user_data);

typedef void (*bt_ready_cb_t)(int err);
int bt_enable(bt_ready_cb_t cb);

const char *bt_addr_le_str(const bt_addr_le_t *addr);

#define BT_ID_DEFAULT 0

struct bt_bond_info {
	bt_addr_le_t addr;
};

void bt_foreach_bond(uint8_t id,
		     void (*func)(const struct bt_bond_info *info,
				  void *user_data),
		     void *user_data);

struct bt_le_scan_param {
	uint8_t type;
	uint8_t options;
	uint16_t interval;
	uint16_t window;
};

typedef void (*bt_le_scan_cb_t)(const bt_addr_le_t *addr, int8_t rssi,
				uint8_t adv_type, struct net_buf_simple *buf);

int bt_le_scan_start(const struct bt_le_scan_param *param,
		     bt_le_scan_cb_t cb);
int bt_le_scan_stop(void);

#define BT_LE_SCAN_PASSIVE ((const struct bt_le_scan_param *)0)
#define BT_LE_SCAN_ACTIVE ((const struct bt_le_scan_param *)0)

#ifdef __cplusplus
}
#endif
