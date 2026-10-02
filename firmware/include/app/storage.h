/*
 * PitchComm clip storage: LittleFS holds the spoken-call audio set.
 * The audio source reads and decodes clips through this module; it does not
 * know whether the files are 16 kHz PCM or compact 8 kHz mu-law.
 *
 * Clips are exposed as bounded-memory streams: open once, read small chunks,
 * close.  Nothing here allocates or buffers in proportion to clip length, so
 * a call can be assembled frame by frame on a 256 KB part.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Mount the audio filesystem. Returns 0 on success, negative errno otherwise. */
int pc_storage_mount(void);

/* True when the filesystem is mounted and the manifest is valid. */
bool pc_storage_ready(void);

/* Dictionary identity from the audio manifest, 0 when not mounted. */
uint32_t pc_storage_dictionary(void);

/* Free space of the audio filesystem in bytes, 0 when not mounted. */
size_t pc_storage_free(void);

/*
 * Open a catalog clip ("/audio/p01.wav") as a mono PCM16 stream.  The path is
 * tried exactly first, then with its extension replaced by ".ulw".  Returns 0
 * on success and stores an opaque handle in *handle; on failure *handle is
 * NULL and a negative errno is returned.  The handle owns a fixed-size
 * decoder state (independent of the clip length, plus one fs_file_t).
 */
int pc_clip_open(const char *path, void **handle);

/* Native sample rate of the open clip: 16000 (WAV) or 8000 (ULW). */
uint32_t pc_clip_rate(void *handle);

/*
 * Read up to `frames` mono int16 samples.  Returns the number of frames
 * written (0 at end of clip) or a negative errno.  Reads are sequential; the
 * caller must not seek.
 */
int pc_clip_read(void *handle, int16_t *dst, size_t frames);

/* Close a clip and release its handle.  NULL is a no-op. */
void pc_clip_close(void *handle);

#ifdef __cplusplus
}
#endif
