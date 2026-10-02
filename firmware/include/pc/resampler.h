/*
 * PitchComm streaming PCM resampler.
 *
 * Integer-only linear interpolation from a clip's native sample rate (8000 or
 * 16000 Hz) to the negotiated LC3 rate (16000/24000/32000/48000 Hz), the
 * per-sample volume gain, and the per-frame assembly used by the audio
 * playback path.
 *
 * The source is consumed in bounded chunks through a caller-supplied read
 * callback, so nothing here allocates and the whole state fits in one
 * fixed-size struct.  There is no floating point and no RTOS dependency:
 * this header is portable C and is covered by firmware/tests/test_audio.cpp.
 *
 * Callers start every clip with pc_resampler_init(), which resets the
 * window, position, and EOF latch along with the rates, so each stream
 * begins at its first source frame.
 */
#pragma once

#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PC_RESAMPLER_WINDOW_FRAMES     512U /* source window, in frames */
#define PC_RESAMPLER_VOLUME_MIN        1U
#define PC_RESAMPLER_VOLUME_MAX        20U
#define PC_RESAMPLER_HEADROOM_PERMILLE 950  /* 95 %, guard against clipping */

/* Read up to `frames` mono int16 source samples into `dst`.  Returns the
 * number written, 0 at the end of the clip, or a negative errno on error.
 */
typedef int (*pc_resampler_read_fn)(void *ctx, int16_t *dst, size_t frames);

/* Pull one output sample.  Returns 1 when *out is valid, 0 when the call is
 * finished.
 */
typedef int (*pc_resampler_pull_fn)(void *ctx, int16_t *out);

struct pc_resampler {
	int16_t win[PC_RESAMPLER_WINDOW_FRAMES]; /* source window */
	uint64_t base;     /* absolute source index of win[0] */
	size_t len;        /* valid frames in win */
	uint64_t pos_q16;  /* absolute source position, Q16 */
	uint32_t src_rate; /* native clip rate */
	uint32_t dst_rate; /* negotiated output rate */
	bool eof;
};

/* Source frames advanced per output frame, Q16.  0 when a rate is unset or
 * the step would underflow.
 */
static inline uint32_t pc_resampler_step_q16(uint32_t src_rate, uint32_t dst_rate)
{
	if (src_rate == 0U || dst_rate == 0U) {
		return 0U;
	}

	return (uint32_t)(((uint64_t)src_rate << 16) / dst_rate);
}

/* 1..20 maps linearly to 5 %..100 %; the headroom guard trims another 5 %.
 * Returned as a Q10 multiplier so the per-sample path has no division.
 */
static inline int32_t pc_resampler_gain_q10(uint8_t volume)
{
	int32_t gain_milli;

	if (volume < PC_RESAMPLER_VOLUME_MIN) {
		volume = PC_RESAMPLER_VOLUME_MIN;
	} else if (volume > PC_RESAMPLER_VOLUME_MAX) {
		volume = PC_RESAMPLER_VOLUME_MAX;
	}

	gain_milli = 50 + ((int32_t)volume - 1) * 50;

	return (int32_t)(((int64_t)gain_milli * PC_RESAMPLER_HEADROOM_PERMILLE * 1024) / 1000000);
}

static inline int16_t pc_resampler_apply_gain(int32_t sample, int32_t gain_q10)
{
	int32_t v = (sample * gain_q10) >> 10;

	if (v > INT16_MAX) {
		v = INT16_MAX;
	} else if (v < INT16_MIN) {
		v = INT16_MIN;
	}

	return (int16_t)v;
}

/* Reset the stream and set both conversion rates. */
static inline void pc_resampler_init(struct pc_resampler *rs, uint32_t src_rate, uint32_t dst_rate)
{
	memset(rs, 0, sizeof(*rs));
	rs->src_rate = src_rate;
	rs->dst_rate = dst_rate;
}

/* Advance the window so absolute source index `need` becomes available, then
 * read more frames from the source.
 */
static inline int pc_resampler_fill(struct pc_resampler *rs, pc_resampler_read_fn read,
				    void *ctx, uint64_t need)
{
	size_t keep = 0U;
	int n;

	if (need > rs->base) {
		const uint64_t k = need - rs->base;

		keep = (k > rs->len) ? rs->len : (size_t)k;
	}

	if (keep > 0U) {
		memmove(rs->win, rs->win + keep, (rs->len - keep) * sizeof(rs->win[0]));
		rs->base += keep;
		rs->len -= keep;
	}

	if (rs->len >= PC_RESAMPLER_WINDOW_FRAMES) {
		return 0;
	}

	n = read(ctx, rs->win + rs->len, PC_RESAMPLER_WINDOW_FRAMES - rs->len);
	if (n < 0) {
		return n;
	}
	if (n == 0) {
		rs->eof = true;
		return 0;
	}

	rs->len += (size_t)n;
	return 0;
}

/* Produce one resampled, volume-adjusted output sample.
 * Returns 1 on success, 0 at the end of the clip, negative errno on error.
 */
static inline int pc_resampler_next(struct pc_resampler *rs, pc_resampler_read_fn read,
				    void *ctx, int32_t gain_q10, int16_t *out)
{
	uint32_t step;

	if (rs->src_rate == 0U || rs->dst_rate == 0U) {
		return -EINVAL;
	}

	step = pc_resampler_step_q16(rs->src_rate, rs->dst_rate);
	if (step == 0U) {
		return -EINVAL;
	}

	for (;;) {
		const uint64_t idx = rs->pos_q16 >> 16;
		size_t i;

		while (!rs->eof && rs->base + rs->len <= idx + 1U) {
			const int err = pc_resampler_fill(rs, read, ctx, idx);

			if (err < 0) {
				return err;
			}
		}

		if (idx < rs->base) {
			return -EIO;
		}

		i = (size_t)(idx - rs->base);
		if (i >= rs->len) {
			return 0; /* all source samples consumed */
		}

		{
			const int32_t s0 = rs->win[i];
			const int32_t s1 = (i + 1U < rs->len) ? rs->win[i + 1U] : s0;
			const uint32_t frac = (uint32_t)(rs->pos_q16 & 0xFFFFU);
			const int32_t v =
				s0 + (int32_t)(((int64_t)(s1 - s0) * (int32_t)frac) >> 16);

			*out = pc_resampler_apply_gain(v, gain_q10);
		}

		rs->pos_q16 += step;
		return 1;
	}
}

/* Fill exactly one output frame by pulling samples; once the pull callback
 * reports the end (0), the rest of the frame is zero-padded and the function
 * returns false.
 */
static inline bool pc_resampler_fill_frame(pc_resampler_pull_fn pull, void *ctx,
					   int16_t *dst, uint32_t frames)
{
	bool alive = true;

	for (uint32_t i = 0; i < frames; i++) {
		int16_t sample = 0;

		if (alive && pull(ctx, &sample) > 0) {
			dst[i] = sample;
		} else {
			alive = false;
			dst[i] = 0;
		}
	}

	return alive;
}

#ifdef __cplusplus
}
#endif
