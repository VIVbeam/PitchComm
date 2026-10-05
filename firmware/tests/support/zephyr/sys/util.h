/*
 * HOST STUB: zephyr/sys/util.h
 *
 * Declaration-only stand-in used by dev/host_compile/run.ps1 with
 * -fsyntax-only. It is NOT a Zephyr header and must never be used in a
 * firmware build. Only the macros the PitchComm sources use are provided.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define MIN(a, b) (((a) < (b)) ? (a) : (b))
#define MAX(a, b) (((a) > (b)) ? (a) : (b))
#define BIT(n) (1UL << (n))
#define BIT64(n) (1ULL << (n))
#define ARG_UNUSED(x) (void)(x)

/*
 * Same preprocessor expansion strategy as Zephyr's util_macro.h so that
 * IS_ENABLED(CONFIG_X) is 1 when CONFIG_X is defined to 1 and 0 otherwise
 * (including when CONFIG_X is not defined at all).
 */
#define IS_ENABLED(config_macro) Z_IS_ENABLED1(config_macro)
#define Z_IS_ENABLED1(config_macro) Z_IS_ENABLED2(_XXXX##config_macro)
#define _XXXX1 _YYYY,
#define Z_IS_ENABLED2(one_or_two_args) Z_IS_ENABLED3(one_or_two_args 1, 0)
#define Z_IS_ENABLED3(ignore_this, val, ...) val
