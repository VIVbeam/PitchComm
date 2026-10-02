/*
 * HOST STUB: zephyr/net/net_if.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

struct net_if;
struct net_l2;

struct net_if *net_if_get_default(void);
struct net_if *net_if_get_first_by_type(const struct net_l2 *l2);
int net_if_get_by_iface(const struct net_if *iface);
