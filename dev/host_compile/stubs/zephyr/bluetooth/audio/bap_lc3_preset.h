/*
 * HOST STUB: zephyr/bluetooth/audio/bap_lc3_preset.h
 *
 * Stand-in preset macros for -fsyntax-only checks. Only the fields
 * audio_source.c reads (codec_cfg, codec_cfg.meta/meta_len, qos.interval)
 * carry values; the rest are zero-initialized.
 */
#pragma once

#include <zephyr/bluetooth/audio/bap.h>

#define BT_BAP_LC3_UNICAST_PRESET_16_2_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 10000U } }
#define BT_BAP_LC3_UNICAST_PRESET_16_1_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 7500U } }
#define BT_BAP_LC3_UNICAST_PRESET_24_2_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 10000U } }
#define BT_BAP_LC3_UNICAST_PRESET_32_2_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 10000U } }
#define BT_BAP_LC3_UNICAST_PRESET_48_2_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 10000U } }
#define BT_BAP_LC3_UNICAST_PRESET_48_1_1(loc, ctx) \
	{ .codec_cfg = { .id = BT_HCI_CODING_FORMAT_LC3 }, \
	  .qos = { .interval = 7500U } }
