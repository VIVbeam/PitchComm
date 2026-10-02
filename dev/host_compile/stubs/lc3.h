/*
 * HOST STUB: lc3.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Mirrors the liblc3
 * encoder surface audio_source.c uses.
 */
#pragma once

#include <stdint.h>

typedef struct lc3_encoder *lc3_encoder_t;

typedef struct {
	uint8_t bytes[16384];
} lc3_encoder_mem_48k_t;

enum lc3_pcm_format {
	LC3_PCM_FORMAT_S16 = 0,
};

lc3_encoder_t lc3_setup_encoder(int dt_us, int sr_hz, int sr_out_hz,
				lc3_encoder_mem_48k_t *mem);
int lc3_encode(lc3_encoder_t encoder, enum lc3_pcm_format fmt,
	       const void *pcm, int channels, int nbytes, void *out);
