/*
 * HOST STUB: zephyr/sys/atomic.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. The host build never
 * executes these calls.
 */
#pragma once

#include <stdint.h>

typedef int32_t atomic_t;
typedef int32_t atomic_val_t;

#define ATOMIC_INIT(value) (value)

atomic_val_t atomic_get(const atomic_t *target);
void atomic_set(atomic_t *target, atomic_val_t value);
atomic_val_t atomic_inc(atomic_t *target);
atomic_val_t atomic_dec(atomic_t *target);
