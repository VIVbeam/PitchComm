/*
 * HOST STUB: zephyr/bluetooth/audio/audio.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Only the audio
 * codec capability surface audio_source.c uses is declared.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/bluetooth/assigned_numbers.h>

#ifdef __cplusplus
extern "C" {
#endif

enum bt_audio_dir {
	BT_AUDIO_DIR_SINK = 0,
	BT_AUDIO_DIR_SOURCE,
};

enum bt_audio_context {
	BT_AUDIO_CONTEXT_TYPE_UNSPECIFIED = 0,
	BT_AUDIO_CONTEXT_TYPE_CONVERSATIONAL = (1U << 0),
	BT_AUDIO_CONTEXT_TYPE_MEDIA = (1U << 1),
	BT_AUDIO_CONTEXT_TYPE_GAME = (1U << 2),
	BT_AUDIO_CONTEXT_TYPE_NOTIFICATION = (1U << 3),
};

enum bt_audio_location {
	BT_AUDIO_LOCATION_FRONT_LEFT = (1U << 0),
	BT_AUDIO_LOCATION_FRONT_RIGHT = (1U << 1),
	BT_AUDIO_LOCATION_FRONT_CENTER = (1U << 2),
	BT_AUDIO_LOCATION_MONO_AUDIO = (1U << 31),
};

struct bt_audio_codec_cap {
	uint8_t id;
};

struct bt_audio_codec_cfg {
	uint8_t id;
	uint8_t meta[16];
	size_t meta_len;
};

struct bt_audio_codec_octets_per_codec_frame {
	uint16_t min;
	uint16_t max;
};

int bt_audio_codec_cap_get_freq(const struct bt_audio_codec_cap *codec_cap);
int bt_audio_codec_cap_get_frame_dur(const struct bt_audio_codec_cap *codec_cap);
int bt_audio_codec_cap_get_supported_audio_chan_counts(
	const struct bt_audio_codec_cap *codec_cap, bool is_unicast);
int bt_audio_codec_cap_get_octets_per_frame(
	const struct bt_audio_codec_cap *codec_cap,
	struct bt_audio_codec_octets_per_codec_frame *octets);

#ifdef __cplusplus
}
#endif
