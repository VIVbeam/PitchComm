/*
 * HOST STUB: zephyr/net_buf.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. NET_BUF_POOL_FIXED_
 * DEFINE declares a pool object so the address can be taken.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <zephyr/kernel.h>

struct net_buf_simple {
	uint8_t *data;
	size_t len;
	size_t size;
};

void net_buf_simple_init_with_data(struct net_buf_simple *buf, void *data,
				   size_t size);
uint8_t net_buf_simple_pull_u8(struct net_buf_simple *buf);
uint16_t net_buf_simple_pull_le16(struct net_buf_simple *buf);
uint32_t net_buf_simple_pull_le32(struct net_buf_simple *buf);

struct net_buf {
	int unused;
};

struct net_buf_pool {
	int unused;
};

#define NET_BUF_POOL_FIXED_DEFINE(name, count, size, ud_size, destroy) \
	static struct net_buf_pool name __attribute__((unused)) = { 0 }

struct net_buf *net_buf_alloc(struct net_buf_pool *pool, k_timeout_t timeout);
void net_buf_reserve(struct net_buf *buf, size_t reserve);
uint8_t *net_buf_tail(struct net_buf *buf);
void net_buf_add(struct net_buf *buf, size_t len);
void net_buf_unref(struct net_buf *buf);
