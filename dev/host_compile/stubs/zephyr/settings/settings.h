/*
 * HOST STUB: zephyr/settings/settings.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

int settings_subsys_init(void);
int settings_load(void);
ssize_t settings_load_one(const char *name, void *value, size_t val_len);
int settings_save_one(const char *name, const void *value, size_t val_len);
int settings_delete(const char *name);
