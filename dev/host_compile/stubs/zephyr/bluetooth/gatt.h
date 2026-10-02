/*
 * HOST STUB: zephyr/bluetooth/gatt.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stdint.h>

#include <zephyr/bluetooth/conn.h>

#ifdef __cplusplus
extern "C" {
#endif

struct bt_gatt_cb {
	void (*att_mtu_updated)(struct bt_conn *conn, uint16_t tx, uint16_t rx);
};

void bt_gatt_cb_register(struct bt_gatt_cb *cb);

#ifdef __cplusplus
}
#endif
