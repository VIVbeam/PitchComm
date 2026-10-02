/*
 * HOST STUB: zephyr/net/net_l2.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. NET_L2_GET_NAME
 * yields a dereferenceable designator so that &NET_L2_GET_NAME(X) still has
 * the const struct net_l2 * type.
 */
#pragma once

struct net_l2 {
	int unused;
};

#define NET_L2_GET_NAME(instance) (*((const struct net_l2 *)0))
