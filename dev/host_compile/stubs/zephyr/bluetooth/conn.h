/*
 * HOST STUB: zephyr/bluetooth/conn.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stdint.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/hci_types.h>

#ifdef __cplusplus
extern "C" {
#endif

struct bt_conn;

typedef enum {
	BT_SECURITY_L0 = 0,
	BT_SECURITY_L1,
	BT_SECURITY_L2,
	BT_SECURITY_L3,
	BT_SECURITY_L4,
} bt_security_t;

enum bt_security_err {
	BT_SECURITY_ERR_SUCCESS = 0,
	BT_SECURITY_ERR_PIN_OR_KEY_MISSING,
	BT_SECURITY_ERR_OOB_NOT_AVAILABLE,
	BT_SECURITY_ERR_AUTH_REQUIREMENT,
	BT_SECURITY_ERR_PAIR_NOT_SUPPORTED,
	BT_SECURITY_ERR_PAIR_NOT_ALLOWED,
};

const char *bt_security_err_to_str(enum bt_security_err err);
const char *bt_conn_dst_str(const struct bt_conn *conn);

int bt_conn_set_security(struct bt_conn *conn, bt_security_t sec);
int bt_conn_disconnect(struct bt_conn *conn, uint8_t reason);
void bt_conn_unref(struct bt_conn *conn);

struct bt_le_conn_param {
	uint16_t interval_min;
	uint16_t interval_max;
	uint16_t latency;
	uint16_t timeout;
};

struct bt_conn_le_create_param {
	int options;
};

#define BT_CONN_LE_CREATE_CONN ((const struct bt_conn_le_create_param *)0)

int bt_conn_le_create(const bt_addr_le_t *peer,
		      const struct bt_conn_le_create_param *create_param,
		      const struct bt_le_conn_param *conn_param,
		      struct bt_conn **conn);

struct bt_conn_cb {
	void (*connected)(struct bt_conn *conn, uint8_t err);
	void (*disconnected)(struct bt_conn *conn, uint8_t reason);
	void (*security_changed)(struct bt_conn *conn, bt_security_t level,
				 enum bt_security_err err);
};

#define BT_CONN_CB_DEFINE(name) \
	static struct bt_conn_cb name __attribute__((unused))

#ifdef __cplusplus
}
#endif
