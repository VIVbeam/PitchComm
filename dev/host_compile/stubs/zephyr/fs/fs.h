/*
 * HOST STUB: zephyr/fs/fs.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. The LittleFS mount
 * struct keeps the field names storage.c initializes.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

struct fs_file_t {
	int unused;
};

typedef struct fs_file_t fs_file_t;

void fs_file_t_init(fs_file_t *file);

struct fs_dirent {
	uint64_t size;
	uint8_t type;
	char name[32];
};

struct fs_statvfs {
	unsigned long f_bsize;
	unsigned long f_frsize;
	unsigned long f_blocks;
	unsigned long f_bfree;
	unsigned long f_bavail;
	unsigned long f_files;
	unsigned long f_ffree;
};

struct fs_mount_t {
	uint8_t type;
	void *fs_data;
	void *storage_dev;
	const char *mnt_point;
	uint8_t flags;
};

#define FS_LITTLEFS 0x01
#define FS_FATFS 0x02

#define FS_O_READ 0x01
#define FS_O_WRITE 0x02
#define FS_O_CREATE 0x04
#define FS_O_APPEND 0x08

#define FS_SEEK_SET 0
#define FS_SEEK_CUR 1
#define FS_SEEK_END 2

int fs_mount(struct fs_mount_t *mp);
int fs_unmount(struct fs_mount_t *mp);
int fs_open(struct fs_file_t *zfp, const char *file_name, uint8_t flags);
int fs_close(struct fs_file_t *zfp);
ssize_t fs_read(struct fs_file_t *zfp, void *ptr, size_t size);
ssize_t fs_write(struct fs_file_t *zfp, const void *ptr, size_t size);
int fs_seek(struct fs_file_t *zfp, off_t off, int whence);
int fs_stat(const char *path, struct fs_dirent *entry);
int fs_statvfs(const char *path, struct fs_statvfs *stat);
