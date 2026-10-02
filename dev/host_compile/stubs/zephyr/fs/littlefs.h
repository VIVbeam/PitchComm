/*
 * HOST STUB: zephyr/fs/littlefs.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. The config macro only
 * needs to declare the fs_data object storage.c points at.
 */
#pragma once

#include <zephyr/fs/fs.h>

struct fs_littlefs {
	int unused;
};

#define FS_LITTLEFS_DECLARE_DEFAULT_CONFIG(name) \
	struct fs_littlefs name = { 0 }
#define FS_LITTLEFS_DECLARE_CUSTOM_CONFIG(name, ...) \
	struct fs_littlefs name = { 0 }
