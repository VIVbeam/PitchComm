/*
 * HOST STUB: zephyr/bluetooth/assigned_numbers.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Values match the
 * Bluetooth assigned numbers the source compares against; the host build
 * never uses them at run time.
 */
#pragma once

/* HCI coding formats */
#define BT_HCI_CODING_FORMAT_LC3 0x06

/* Audio codec capability frequency bits (BT_AUDIO_CODEC_CAP_FREQ_*) */
#define BT_AUDIO_CODEC_CAP_FREQ_8KHZ (1U << 0)
#define BT_AUDIO_CODEC_CAP_FREQ_11KHZ (1U << 1)
#define BT_AUDIO_CODEC_CAP_FREQ_16KHZ (1U << 3)
#define BT_AUDIO_CODEC_CAP_FREQ_22KHZ (1U << 4)
#define BT_AUDIO_CODEC_CAP_FREQ_24KHZ (1U << 5)
#define BT_AUDIO_CODEC_CAP_FREQ_32KHZ (1U << 6)
#define BT_AUDIO_CODEC_CAP_FREQ_44KHZ (1U << 7)
#define BT_AUDIO_CODEC_CAP_FREQ_48KHZ (1U << 8)
#define BT_AUDIO_CODEC_CAP_FREQ_88KHZ (1U << 9)
#define BT_AUDIO_CODEC_CAP_FREQ_96KHZ (1U << 10)
#define BT_AUDIO_CODEC_CAP_FREQ_176KHZ (1U << 11)
#define BT_AUDIO_CODEC_CAP_FREQ_192KHZ (1U << 12)
#define BT_AUDIO_CODEC_CAP_FREQ_384KHZ (1U << 13)

/* Audio codec capability frame duration bits */
#define BT_AUDIO_CODEC_CAP_DURATION_7_5 (1U << 0)
#define BT_AUDIO_CODEC_CAP_DURATION_10 (1U << 1)
#define BT_AUDIO_CODEC_CAP_DURATION_20 (1U << 2)
#define BT_AUDIO_CODEC_CAP_DURATION_30 (1U << 3)
#define BT_AUDIO_CODEC_CAP_DURATION_40 (1U << 4)
#define BT_AUDIO_CODEC_CAP_DURATION_60 (1U << 5)
#define BT_AUDIO_CODEC_CAP_DURATION_80 (1U << 6)
#define BT_AUDIO_CODEC_CAP_DURATION_100 (1U << 7)

/* Audio codec capability channel count bits */
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_1 (1U << 0)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_2 (1U << 1)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_3 (1U << 2)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_4 (1U << 3)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_5 (1U << 4)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_6 (1U << 5)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_7 (1U << 6)
#define BT_AUDIO_CODEC_CAP_CHAN_COUNT_8 (1U << 7)
