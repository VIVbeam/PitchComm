/*
 * HOST STUB: zephyr/sys/byteorder.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Signatures mirror the
 * Zephyr helpers the sources call.
 */
#pragma once

#include <stdint.h>

uint16_t sys_cpu_to_be16(uint16_t val);
uint32_t sys_cpu_to_be32(uint32_t val);
uint16_t sys_le16_to_cpu(uint16_t val);
uint32_t sys_le32_to_cpu(uint32_t val);
uint16_t sys_get_le16(const uint8_t *src);
uint32_t sys_get_le32(const uint8_t *src);
