/*
 * HOST STUB: zephyr/random/random.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

uint32_t sys_rand32_get(void);
int sys_csrand_get(void *dst, size_t len);
