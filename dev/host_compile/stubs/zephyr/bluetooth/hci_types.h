/*
 * HOST STUB: zephyr/bluetooth/hci_types.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stdint.h>

#define BT_HCI_ERR_SUCCESS 0x00
#define BT_HCI_ERR_UNKNOWN_CONN_ID 0x02
#define BT_HCI_ERR_REMOTE_USER_TERM_CONN 0x13
#define BT_HCI_ERR_LOCALHOST_TERM_CONN 0x16

const char *bt_hci_err_to_str(uint8_t hci_err);
