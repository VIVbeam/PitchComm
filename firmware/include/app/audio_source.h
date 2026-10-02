/*
 * PitchComm LE Audio source: one BAP unicast client streaming LC3 to one
 * earbud (mono; no TWS). The engine's present hook calls pc_audio_play(); the
 * call returns once the request is queued, not when the earbud has heard it.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Start the Bluetooth host, earbud scan/connect state machine, and playback thread. */
int pc_audio_start(void);

/* True when an earbud is connected and its sink stream is started. */
bool pc_audio_ready(void);

/* True while a call is playing or queued. */
bool pc_audio_busy(void);

/*
 * Queue a call assembled from up to three catalog clip paths (for example
 * "/audio/p01.wav", "/audio/h1.wav", "/audio/s1.wav"). Pass NULL for unused
 * slots. Returns false when audio is not ready or the queue is full.
 */
bool pc_audio_play(const char *clip_a, const char *clip_b, const char *clip_c);

/* Replay the last queued call. False when there is nothing to recall. */
bool pc_audio_recall(void);

/* Stop playback and clear the queue. */
void pc_audio_stop(void);

/* Output level 1..20 (20 = full scale). */
void pc_audio_set_volume(uint8_t volume);
uint8_t pc_audio_volume(void);

/* Drop the current earbud connection and retry the saved one. */
void pc_audio_reconnect(void);

/* Diagnostics: "READY", "CONNECTING", "PAIRING", "PLAYING", "NO EARBUD". */
const char *pc_audio_state(void);

/* Body-to-earbud latency estimate of the negotiated QoS, in microseconds. */
uint32_t pc_audio_frame_duration_us(void);

#ifdef __cplusplus
}
#endif
