/*
 * PitchComm clip storage.
 *
 * LittleFS is mounted on the unused MCUboot secondary slot
 * (FIXED_PARTITION_ID(slot1_partition), 712 KB on the XIAO nRF54L15), which is
 * the only large, writable region this application owns.  The file system is
 * populated out of band (USB mass-storage image / tools), not by this
 * firmware.
 *
 * Catalog paths look like "/audio/p01.wav".  Two on-disk formats are
 * accepted:
 *
 *   - RIFF/WAVE, PCM, mono, 16 kHz, 16 bit, data chunk <= 5 s.  The same
 *     validation as v1/include/pc/wav.h is applied (unknown chunks are
 *     skipped, fmt must be PCM 1/1/16000/32000/2/16, data even and short
 *     enough).
 *   - "ULW1" + uint32 little-endian sample count + G.711 mu-law bytes at
 *     8 kHz (the compact deployment format).
 *
 * Clips are streamed: pc_clip_open() parses the header and keeps only a
 * fixed-size state; pc_clip_read() pulls small chunks straight into the
 * caller's buffer (mu-law is decoded one 256-byte chunk at a time).  Memory
 * use is independent of clip length.
 *
 * Thread notes: pc_storage_mount() is called once from the boot thread;
 * pc_clip_* are called from the audio playback thread only.  A handle must
 * not be shared between threads.
 */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/fs/fs.h>
#include <zephyr/fs/littlefs.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <app/storage.h>

LOG_MODULE_REGISTER(pc_storage, LOG_LEVEL_INF);

#define PC_STORAGE_MNT   "/audio"
#define PC_MANIFEST      "/audio/manifest.txt"
#define PC_PATH_MAX      48
#define PC_MANIFEST_MAX  32

/* Same budget as the v1 WAV reader: at most 5 s of 16 kHz mono PCM16. */
#define PC_WAV_MAX_DATA      (32000u * 5u)
#define PC_ULW_MAX_SAMPLES   (32000u * 5u)

/* Mu-law bytes decoded per fs_read() during pc_clip_read(). */
#define PC_ULAW_CHUNK        256U

static const char pc_ulw_magic[4] = { 'U', 'L', 'W', '1' };

FS_LITTLEFS_DECLARE_DEFAULT_CONFIG(pc_lfs_cfg);

static struct fs_mount_t pc_lfs_mount = {
	.type = FS_LITTLEFS,
	.fs_data = &pc_lfs_cfg,
	/* VERIFY: NCS v3.4.0 struct fs_mount_t takes the flash area id through
	 * the void *storage_dev field; there is no fa_id field on fs_littlefs.
	 * The documented pattern is the cast below.
	 */
	.storage_dev = (void *)FIXED_PARTITION_ID(slot1_partition),
	.mnt_point = PC_STORAGE_MNT,
};

static bool mounted;
static bool manifest_ok;
static uint32_t dictionary;
static int16_t mulaw_table[256];

enum pc_clip_format {
	PC_CLIP_WAV = 1,
	PC_CLIP_ULW = 2,
};

/* One open clip.  Fixed size: never scaled by the clip length. */
struct pc_clip {
	struct fs_file_t file;
	uint32_t rate;
	uint32_t remaining;   /* frames left to read */
	uint8_t format;
	uint8_t ulaw[PC_ULAW_CHUNK];
};

/* ------------------------------------------------------------------------- */
/* Mount / manifest                                                          */
/* ------------------------------------------------------------------------- */

static void pc_build_mulaw_table(void)
{
	for (unsigned i = 0; i < 256; i++) {
		const uint8_t u = (uint8_t)~i;
		int32_t t = ((u & 0x0FU) << 3) + 0x84;

		t <<= (u & 0x70U) >> 4;
		mulaw_table[i] = (u & 0x80U) ? (int16_t)(0x84 - t) : (int16_t)(t - 0x84);
	}
}

static bool pc_parse_dictionary(const char *text, uint32_t *out)
{
	uint32_t value = 0;
	unsigned digits = 0;

	while (*text == ' ' || *text == '\t' || *text == '\r' || *text == '\n') {
		text++;
	}

	while (digits < 8) {
		const char c = *text++;
		int nibble;

		if (c >= '0' && c <= '9') {
			nibble = c - '0';
		} else if (c >= 'a' && c <= 'f') {
			nibble = c - 'a' + 10;
		} else if (c >= 'A' && c <= 'F') {
			nibble = c - 'A' + 10;
		} else {
			break;
		}

		value = (value << 4) | (uint32_t)nibble;
		digits++;
	}

	if (digits == 0) {
		return false;
	}

	*out = value;
	return true;
}

int pc_storage_mount(void)
{
	struct fs_file_t file;
	char buf[PC_MANIFEST_MAX];
	ssize_t n;
	int err;

	if (mounted) {
		return 0;
	}

	pc_build_mulaw_table();

	err = fs_mount(&pc_lfs_mount);
	if (err != 0) {
		LOG_ERR("LittleFS mount failed: %d", err);
		return err;
	}
	mounted = true;

	fs_file_t_init(&file);
	err = fs_open(&file, PC_MANIFEST, FS_O_READ);
	if (err == -ENOENT) {
		/* No audio set programmed: a normal state, not an error.  Leave
		 * the file system unmounted so nothing else touches it.
		 */
		LOG_INF("No %s; clip storage offline", PC_MANIFEST);
		(void)fs_unmount(&pc_lfs_mount);
		mounted = false;
		return 0;
	}
	if (err != 0) {
		LOG_ERR("manifest open failed: %d", err);
		(void)fs_unmount(&pc_lfs_mount);
		mounted = false;
		return err;
	}

	n = fs_read(&file, buf, sizeof(buf) - 1);
	(void)fs_close(&file);
	if (n <= 0) {
		LOG_WRN("manifest empty or unreadable (%d)", (int)n);
		(void)fs_unmount(&pc_lfs_mount);
		mounted = false;
		return (n < 0) ? (int)n : -EINVAL;
	}
	buf[n] = '\0';

	if (!pc_parse_dictionary(buf, &dictionary)) {
		LOG_WRN("manifest has no dictionary id");
		(void)fs_unmount(&pc_lfs_mount);
		mounted = false;
		return -EINVAL;
	}

	manifest_ok = true;
	LOG_INF("Clip storage ready: dictionary %08x, %zu bytes free",
		(unsigned int)dictionary, pc_storage_free());
	return 0;
}

bool pc_storage_ready(void)
{
	return mounted && manifest_ok;
}

uint32_t pc_storage_dictionary(void)
{
	return pc_storage_ready() ? dictionary : 0U;
}

size_t pc_storage_free(void)
{
	struct fs_statvfs statvfs;

	if (!mounted) {
		return 0U;
	}

	if (fs_statvfs(PC_STORAGE_MNT, &statvfs) != 0) {
		return 0U;
	}

	return (size_t)statvfs.f_bfree * (size_t)statvfs.f_bsize;
}

/* ------------------------------------------------------------------------- */
/* Path resolution                                                           */
/* ------------------------------------------------------------------------- */

/*
 * Replace the last path extension with ".ulw".  Returns false when there is
 * nothing to try (no room, or the path is already ".ulw").
 */
static bool pc_alt_ulw_path(const char *path, char *out, size_t out_size)
{
	const size_t len = strlen(path);
	const char *slash = strrchr(path, '/');
	const char *dot = strrchr(path, '.');
	size_t base;

	if (len == 0 || len >= out_size) {
		return false;
	}

	if (dot == NULL || (slash != NULL && dot < slash)) {
		/* No extension: append one. */
		if (len + 5 > out_size) {
			return false;
		}
		memcpy(out, path, len);
		memcpy(out + len, ".ulw", 4);
		out[len + 4] = '\0';
		return true;
	}

	if (strcmp(dot, ".ulw") == 0) {
		return false;
	}

	base = (size_t)(dot - path);
	if (base + 5 > out_size) {
		return false;
	}

	memcpy(out, path, base);
	memcpy(out + base, ".ulw", 4);
	out[base + 4] = '\0';
	return true;
}

/* ------------------------------------------------------------------------- */
/* Header probing                                                            */
/* ------------------------------------------------------------------------- */

static int pc_read_exact(struct fs_file_t *file, void *dst, size_t len)
{
	uint8_t *p = dst;
	size_t got = 0;

	while (got < len) {
		const ssize_t n = fs_read(file, p + got, len - got);

		if (n <= 0) {
			return (n < 0) ? (int)n : -EIO;
		}
		got += (size_t)n;
	}

	return 0;
}

/* WAV: RIFF/WAVE, fmt PCM 1/1/16000/32000/2/16, one even data chunk <= 5 s. */
static int pc_wav_probe(struct pc_clip *clip, const char *path)
{
	struct fs_dirent entry;
	uint8_t hdr[16];
	uint32_t file_size;
	uint32_t riff_end;
	uint32_t pos;
	uint32_t data_off = 0U;
	uint32_t data_len = 0U;
	bool have_fmt = false;
	bool have_data = false;
	int err;

	err = fs_stat(path, &entry);
	if (err != 0) {
		return err;
	}
	if (entry.size < 44U) {
		return -EINVAL;
	}
	file_size = (uint32_t)entry.size;

	err = fs_seek(&clip->file, 0, FS_SEEK_SET);
	if (err != 0) {
		return err;
	}
	err = pc_read_exact(&clip->file, hdr, 12U);
	if (err != 0) {
		return err;
	}
	if (memcmp(hdr, "RIFF", 4) != 0 || memcmp(hdr + 8, "WAVE", 4) != 0) {
		return -EINVAL;
	}
	riff_end = 8U + sys_get_le32(hdr + 4);
	if (riff_end > file_size || riff_end < 44U) {
		return -EINVAL;
	}

	pos = 12U;
	while (pos + 8U <= riff_end) {
		uint32_t len;
		uint32_t start;
		uint64_t next;

		err = fs_seek(&clip->file, (off_t)pos, FS_SEEK_SET);
		if (err != 0) {
			return err;
		}
		err = pc_read_exact(&clip->file, hdr, 8U);
		if (err != 0) {
			return err;
		}

		len = sys_get_le32(hdr + 4);
		start = pos + 8U;
		if ((uint64_t)start + len > riff_end) {
			return -EINVAL;
		}

		if (memcmp(hdr, "fmt ", 4) == 0) {
			if (have_fmt || len < 16U) {
				return -EINVAL;
			}
			err = pc_read_exact(&clip->file, hdr, 16U);
			if (err != 0) {
				return err;
			}
			if (sys_get_le16(hdr) != 1U ||          /* PCM */
			    sys_get_le16(hdr + 2) != 1U ||      /* mono */
			    sys_get_le32(hdr + 4) != 16000U ||  /* sample rate */
			    sys_get_le32(hdr + 8) != 32000U ||  /* byte rate */
			    sys_get_le16(hdr + 12) != 2U ||     /* block align */
			    sys_get_le16(hdr + 14) != 16U) {    /* bits */
				return -EINVAL;
			}
			have_fmt = true;
		} else if (memcmp(hdr, "data", 4) == 0) {
			if (have_data || len == 0U || (len & 1U) != 0U ||
			    len > PC_WAV_MAX_DATA) {
				return -EINVAL;
			}
			data_off = start;
			data_len = len;
			have_data = true;
		}

		next = (uint64_t)start + len + (len & 1U);
		if (next > riff_end) {
			return -EINVAL;
		}
		pos = (uint32_t)next;
	}

	/* v1 reader required the chunks to tile the RIFF area exactly. */
	if (!have_fmt || !have_data || pos != riff_end) {
		return -EINVAL;
	}

	/* Position the file at the first PCM sample. */
	err = fs_seek(&clip->file, (off_t)data_off, FS_SEEK_SET);
	if (err != 0) {
		return err;
	}

	clip->rate = 16000U;
	clip->remaining = data_len / 2U;
	clip->format = PC_CLIP_WAV;
	return 0;
}

/* Compact format: "ULW1" + uint32 count + G.711 mu-law bytes at 8 kHz. */
static int pc_ulw_probe(struct pc_clip *clip, const char *path)
{
	struct fs_dirent entry;
	uint8_t hdr[8];
	uint32_t count;
	int err;

	err = fs_stat(path, &entry);
	if (err != 0) {
		return err;
	}

	err = fs_seek(&clip->file, 0, FS_SEEK_SET);
	if (err != 0) {
		return err;
	}
	err = pc_read_exact(&clip->file, hdr, sizeof(hdr));
	if (err != 0) {
		return err;
	}
	if (memcmp(hdr, pc_ulw_magic, 4) != 0) {
		return -EINVAL;
	}

	count = sys_get_le32(hdr + 4);
	if (count == 0U || count > PC_ULW_MAX_SAMPLES) {
		return -EINVAL;
	}
	if ((uint64_t)entry.size < (uint64_t)count + sizeof(hdr)) {
		return -EINVAL; /* truncated file */
	}

	/* File position is already at the first mu-law byte. */
	clip->rate = 8000U;
	clip->remaining = count;
	clip->format = PC_CLIP_ULW;
	return 0;
}

static int pc_clip_probe(struct pc_clip *clip, const char *path)
{
	uint8_t magic[4];
	ssize_t n;
	int err;

	err = fs_seek(&clip->file, 0, FS_SEEK_SET);
	if (err != 0) {
		return err;
	}

	n = fs_read(&clip->file, magic, sizeof(magic));
	if (n != (ssize_t)sizeof(magic)) {
		return (n < 0) ? (int)n : -EINVAL;
	}

	if (memcmp(magic, pc_ulw_magic, 4) == 0) {
		return pc_ulw_probe(clip, path);
	}

	return pc_wav_probe(clip, path);
}

/* ------------------------------------------------------------------------- */
/* Streaming clip API                                                        */
/* ------------------------------------------------------------------------- */

static int pc_clip_open_file(const char *path, void **handle)
{
	struct pc_clip *clip;
	int err;

	clip = k_malloc(sizeof(*clip));
	if (clip == NULL) {
		return -ENOMEM;
	}
	memset(clip, 0, sizeof(*clip));

	fs_file_t_init(&clip->file);
	err = fs_open(&clip->file, path, FS_O_READ);
	if (err != 0) {
		k_free(clip);
		return err;
	}

	err = pc_clip_probe(clip, path);
	if (err != 0) {
		(void)fs_close(&clip->file);
		k_free(clip);
		return err;
	}

	*handle = clip;
	return 0;
}

int pc_clip_open(const char *path, void **handle)
{
	char alt[PC_PATH_MAX];
	int err;

	if (handle == NULL) {
		return -EINVAL;
	}
	*handle = NULL;

	if (!pc_storage_ready()) {
		return -ENODEV;
	}
	if (path == NULL || path[0] == '\0') {
		return -ENOENT;
	}

	err = pc_clip_open_file(path, handle);
	if (err == -ENOENT && pc_alt_ulw_path(path, alt, sizeof(alt))) {
		err = pc_clip_open_file(alt, handle);
	}

	return err;
}

uint32_t pc_clip_rate(void *handle)
{
	const struct pc_clip *clip = handle;

	return (clip != NULL) ? clip->rate : 0U;
}

static int pc_read_wav(struct pc_clip *clip, int16_t *dst, size_t frames)
{
	const size_t want_bytes = frames * sizeof(int16_t);
	size_t got_bytes = 0U;

	while (got_bytes < want_bytes) {
		const ssize_t n = fs_read(&clip->file, (uint8_t *)dst + got_bytes,
					  want_bytes - got_bytes);

		if (n < 0) {
			return (got_bytes > 0U) ? (int)(got_bytes / 2U) : (int)n;
		}
		if (n == 0) {
			break;
		}
		got_bytes += (size_t)n;
	}

	if ((got_bytes & 1U) != 0U) {
		return -EIO; /* truncated mid-sample */
	}

	return (int)(got_bytes / 2U);
}

static int pc_read_ulaw(struct pc_clip *clip, int16_t *dst, size_t frames)
{
	size_t done = 0U;

	while (done < frames) {
		const size_t want = MIN(frames - done, sizeof(clip->ulaw));
		const ssize_t n = fs_read(&clip->file, clip->ulaw, want);

		if (n < 0) {
			return (done > 0U) ? (int)done : (int)n;
		}
		if (n == 0) {
			/* Truncated despite the size check at open. */
			return (done > 0U) ? (int)done : -EIO;
		}

		for (ssize_t i = 0; i < n; i++) {
			dst[done + (size_t)i] = mulaw_table[clip->ulaw[i]];
		}
		done += (size_t)n;
	}

	return (int)done;
}

int pc_clip_read(void *handle, int16_t *dst, size_t frames)
{
	struct pc_clip *clip = handle;
	int got;

	if (clip == NULL || dst == NULL) {
		return -EINVAL;
	}
	if (frames == 0U || clip->remaining == 0U) {
		return 0;
	}
	if (frames > clip->remaining) {
		frames = clip->remaining;
	}

	if (clip->format == PC_CLIP_ULW) {
		got = pc_read_ulaw(clip, dst, frames);
	} else {
		got = pc_read_wav(clip, dst, frames);
	}

	if (got > 0) {
		clip->remaining -= (uint32_t)got;
	}

	return got;
}

void pc_clip_close(void *handle)
{
	struct pc_clip *clip = handle;

	if (clip == NULL) {
		return;
	}

	(void)fs_close(&clip->file);
	k_free(clip);
}
