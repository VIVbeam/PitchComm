/*
 * PitchComm LE Audio source.
 *
 * One BAP unicast client, one sink ASE (the earbud is the unicast server /
 * sink), mono FRONT_LEFT.  The audio thread owns every Bluetooth call: the
 * public API is callable from the engine thread and only touches the request
 * queue and atomics.
 *
 * Connection sequence (all asynchronous, every wait has a timeout):
 *   passive scan for a close advertiser carrying ASCS service data
 *   -> connect -> MTU (best effort) -> SMP L2 -> discover sink ASEs/PACs
 *   -> configure one preset -> create unicast group -> QoS -> enable
 *   -> connect CIS -> wait for the server to start streaming.
 *
 * Written against NCS v3.4.0.  Note for reviewers: the Zephyr sample kept in
 * scratch (older API) uses bt_bap_stream_ops.codec_configured/qos_configured;
 * NCS v3.4.0 bap.h names those members .configured and .qos_set, so that is
 * what is used here.  The SDK-correct names were verified against
 * include/zephyr/bluetooth/audio/bap.h of sdk-zephyr ncs-v3.4.0.
 */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net_buf.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#include <zephyr/bluetooth/assigned_numbers.h>
#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gap.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/hci_types.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/audio/audio.h>
#include <zephyr/bluetooth/audio/bap.h>
#include <zephyr/bluetooth/audio/bap_lc3_preset.h>
#include <zephyr/bluetooth/iso.h>

#include <lc3.h>

#include <app/audio_source.h>
#include <app/storage.h>
#include <pc/resampler.h>

#if !defined(CONFIG_LIBLC3)
#error "PitchComm audio source requires CONFIG_LIBLC3 (roles/audio-unit.conf)"
#endif

LOG_MODULE_REGISTER(pc_audio, LOG_LEVEL_INF);

/* ------------------------------------------------------------------------- */
/* Tunables                                                                  */
/* ------------------------------------------------------------------------- */

#define PC_AUDIO_THREAD_STACK_SIZE 4096
#define PC_AUDIO_THREAD_PRIO       K_PRIO_PREEMPT(5)

#define PC_CALL_QUEUE_DEPTH        4
#define PC_CLIP_SLOTS              3
#define PC_CLIP_PATH_MAX           24
#define PC_GAP_MS                  20U

#define PC_SCAN_TIMEOUT_MS         10000
#define PC_MTU_WAIT_MS             3000
#define PC_SECURITY_WAIT_MS        15000   /* pairing may need the user */
#define PC_DISCOVER_WAIT_MS        10000
#define PC_CONFIGURE_WAIT_MS       5000
#define PC_STAGE_WAIT_MS           5000
#define PC_ISO_CONNECT_WAIT_MS     5000
#define PC_START_WAIT_MS           5000
#define PC_DISCONNECT_WAIT_MS      3000
#define PC_GROUP_DELETE_RETRIES    20
#define PC_GROUP_DELETE_POLL_MS    100
#define PC_PRESET_RETRY_MS         250

#define PC_BACKOFF_MIN_MS          1000U
#define PC_BACKOFF_MAX_MS          30000U

#define PC_MIN_RSSI                (-50)
#define PC_TX_RETRY_US             2000
#define PC_SEND_RETRIES            32

#define PC_MAX_FRAME_SAMPLES       480U    /* 48 kHz, 10 ms */
#define PC_MAX_SLEEP_US            20000

#define PC_VOLUME_MIN              PC_RESAMPLER_VOLUME_MIN
#define PC_VOLUME_MAX              PC_RESAMPLER_VOLUME_MAX
#define PC_VOLUME_DEFAULT          20U

/* VERIFY: stream context.  The runbook's sample uses UNSPECIFIED and the
 * 16_2_1 preset is mandatory, so that is the default.  If the JY300 rejects
 * the configuration with metadata errors, switch this to
 * BT_AUDIO_CONTEXT_TYPE_MEDIA.
 */
#define PC_STREAM_CONTEXT          BT_AUDIO_CONTEXT_TYPE_UNSPECIFIED
#define PC_STREAM_LOCATION         BT_AUDIO_LOCATION_FRONT_LEFT

enum pc_audio_state {
	PC_ST_NO_EARBUD = 0,
	PC_ST_PAIRING,
	PC_ST_CONNECTING,
	PC_ST_READY,
	PC_ST_PLAYING,
};

/* Preset priority: 16/10 mandatory first, then the runbook fallbacks. */
enum pc_preset_idx {
	PC_PRESET_16_2 = 0,   /* 16 kHz, 10 ms, 40 octets */
	PC_PRESET_16_1,       /* 16 kHz, 7.5 ms, 30 octets */
	PC_PRESET_24_2,       /* 24 kHz, 10 ms, 60 octets */
	PC_PRESET_32_2,       /* 32 kHz, 10 ms, 80 octets */
	PC_PRESET_48_2,       /* 48 kHz, 10 ms, 120 octets */
	PC_PRESET_48_1,       /* 48 kHz, 7.5 ms, 90 octets */
	PC_PRESET_COUNT
};

#define PC_PRESET_NONE (-1)

/* ------------------------------------------------------------------------- */
/* Request queue and shared state                                            */
/* ------------------------------------------------------------------------- */

struct pc_call_req {
	uint32_t sequence;
	char clips[PC_CLIP_SLOTS][PC_CLIP_PATH_MAX];
};

K_MSGQ_DEFINE(pc_call_q, sizeof(struct pc_call_req), PC_CALL_QUEUE_DEPTH, 4);

/* Event bits are posted from Bluetooth callbacks and consumed by the audio
 * thread with k_event_wait().  All are cleared at the start of a session.
 */
#define EV_CONNECTED      BIT(0)
#define EV_CONNECT_FAILED BIT(1)
#define EV_DISCONNECTED   BIT(2)
#define EV_MTU            BIT(3)
#define EV_SECURITY       BIT(4)
#define EV_SECURITY_FAILED BIT(5)
#define EV_DISCOVERED     BIT(6)
#define EV_CONFIGURED     BIT(7)
#define EV_CONFIG_FAILED  BIT(8)
#define EV_QOS            BIT(9)
#define EV_QOS_FAILED     BIT(10)
#define EV_ENABLED        BIT(11)
#define EV_ENABLE_FAILED  BIT(12)
#define EV_ISO_CONNECTED  BIT(13)
#define EV_STARTED        BIT(14)
#define EV_STREAM_STOPPED BIT(15)
#define EV_RELEASED       BIT(16)
#define EV_SENT           BIT(17)
#define EV_RECONNECT_REQ  BIT(18)

/* Reasons any wait should stop early. */
#define EV_ABORT_BITS (EV_DISCONNECTED | EV_RECONNECT_REQ)

K_EVENT_DEFINE(pc_audio_evt);

/* The presets are file-scope initializers: BT_BAP_LC3_PRESET is a brace
 * initializer macro in NCS v3.4.0 and cannot be used inside a function.
 */
static const struct bt_bap_lc3_preset pc_presets[] = {
	BT_BAP_LC3_UNICAST_PRESET_16_2_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
	BT_BAP_LC3_UNICAST_PRESET_16_1_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
	BT_BAP_LC3_UNICAST_PRESET_24_2_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
	BT_BAP_LC3_UNICAST_PRESET_32_2_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
	BT_BAP_LC3_UNICAST_PRESET_48_2_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
	BT_BAP_LC3_UNICAST_PRESET_48_1_1(PC_STREAM_LOCATION, PC_STREAM_CONTEXT),
};

struct pc_preset_info {
	uint32_t rate_hz;
	uint32_t frame_us;
	uint16_t octets;
	int cap_freq;   /* BT_AUDIO_CODEC_CAP_FREQ_* bit */
	int cap_dur;    /* BT_AUDIO_CODEC_CAP_DURATION_* bit */
};

static const struct pc_preset_info pc_preset_info[PC_PRESET_COUNT] = {
	{ 16000U, 10000U, 40U, BT_AUDIO_CODEC_CAP_FREQ_16KHZ, BT_AUDIO_CODEC_CAP_DURATION_10 },
	{ 16000U, 7500U, 30U, BT_AUDIO_CODEC_CAP_FREQ_16KHZ, BT_AUDIO_CODEC_CAP_DURATION_7_5 },
	{ 24000U, 10000U, 60U, BT_AUDIO_CODEC_CAP_FREQ_24KHZ, BT_AUDIO_CODEC_CAP_DURATION_10 },
	{ 32000U, 10000U, 80U, BT_AUDIO_CODEC_CAP_FREQ_32KHZ, BT_AUDIO_CODEC_CAP_DURATION_10 },
	{ 48000U, 10000U, 120U, BT_AUDIO_CODEC_CAP_FREQ_48KHZ, BT_AUDIO_CODEC_CAP_DURATION_10 },
	{ 48000U, 7500U, 90U, BT_AUDIO_CODEC_CAP_FREQ_48KHZ, BT_AUDIO_CODEC_CAP_DURATION_7_5 },
};

/* Bluetooth objects.  Written by the audio thread, read by callbacks. */
static struct bt_conn *default_conn;
static struct bt_bap_unicast_group *unicast_group;
static struct bt_bap_ep *sink_ep;
static struct bt_bap_stream sink_stream;

/* Working copy of the chosen preset; bt_bap_stream_config() wants a
 * non-const codec configuration.
 */
static struct bt_bap_lc3_preset codec_cfg;

static int chosen_preset = PC_PRESET_NONE;
static int forced_preset = PC_PRESET_NONE;
static bool pac_seen;
static int discover_err;

/* Negotiated stream numbers. */
static uint32_t pc_sample_rate = 16000U;
static uint32_t pc_frame_us = 10000U;
static uint16_t pc_octets = 40U;
static uint16_t pc_seq_num;

/* Engine-visible state. */
static atomic_t pc_volume = ATOMIC_INIT(PC_VOLUME_DEFAULT);
static atomic_t pc_playing = ATOMIC_INIT(0);
static atomic_t pc_stop = ATOMIC_INIT(0);
static atomic_t pc_reconnect = ATOMIC_INIT(0);
static atomic_t pc_connected = ATOMIC_INIT(0);
static atomic_t pc_streaming = ATOMIC_INIT(0);
static atomic_t pc_connect_pending = ATOMIC_INIT(0);
static atomic_t pc_play_seq = ATOMIC_INIT(0);
static atomic_t pc_state = ATOMIC_INIT(PC_ST_NO_EARBUD);

/* Last assembled call for pc_audio_recall(). */
static struct pc_call_req last_req;
static bool last_req_valid;
static K_MUTEX_DEFINE(last_req_lock);

/* LC3 encoder (set up once per session, on the audio thread). */
static struct {
	lc3_encoder_t enc;
	lc3_encoder_mem_48k_t mem;
	uint16_t samples_per_frame;
} pc_lc3;

static int16_t pc_silence[PC_MAX_FRAME_SAMPLES];
static int16_t pc_frame_buf[PC_MAX_FRAME_SAMPLES];

NET_BUF_POOL_FIXED_DEFINE(pc_tx_pool, CONFIG_BT_ISO_TX_BUF_COUNT,
			  BT_ISO_SDU_BUF_SIZE(CONFIG_BT_ISO_TX_MTU),
			  CONFIG_BT_CONN_TX_USER_DATA_SIZE, NULL);

static K_THREAD_STACK_DEFINE(pc_audio_stack, PC_AUDIO_THREAD_STACK_SIZE);
static struct k_thread pc_audio_thread_data;
static bool pc_started;
static bool pc_cb_registered;

/* ------------------------------------------------------------------------- */
/* Small helpers                                                             */
/* ------------------------------------------------------------------------- */

static void pc_set_state(enum pc_audio_state state)
{
	atomic_set(&pc_state, (atomic_val_t)state);
}

static const char *pc_preset_name(int idx)
{
	switch (idx) {
	case PC_PRESET_16_2:
		return "16 kHz/10 ms/40";
	case PC_PRESET_16_1:
		return "16 kHz/7.5 ms/30";
	case PC_PRESET_24_2:
		return "24 kHz/10 ms/60";
	case PC_PRESET_32_2:
		return "32 kHz/10 ms/80";
	case PC_PRESET_48_2:
		return "48 kHz/10 ms/120";
	case PC_PRESET_48_1:
		return "48 kHz/7.5 ms/90";
	default:
		return "unset";
	}
}

static void pc_apply_preset_numbers(int idx)
{
	pc_sample_rate = pc_preset_info[idx].rate_hz;
	pc_frame_us = pc_preset_info[idx].frame_us;
	pc_octets = pc_preset_info[idx].octets;
}

static int pc_select_preset(int idx)
{
	if (idx < 0 || idx >= PC_PRESET_COUNT) {
		return -EINVAL;
	}

	codec_cfg = pc_presets[idx];
	LOG_INF("Using LC3 preset %s", pc_preset_name(idx));
	return 0;
}

static bool pc_stream_ok(void)
{
	return atomic_get(&pc_connected) != 0 &&
	       atomic_get(&pc_streaming) != 0 &&
	       default_conn != NULL &&
	       unicast_group != NULL;
}

/* The linear-interpolation resampler, its volume gain, and the per-frame
 * assembly are in <pc/resampler.h>; the playback path streams clip chunks
 * through pc_clip_stream_next() without buffering a whole clip.
 */

/* ------------------------------------------------------------------------- */
/* Bluetooth callbacks                                                       */
/* ------------------------------------------------------------------------- */

static void pc_connected_cb(struct bt_conn *conn, uint8_t err)
{
	if (err != 0) {
		LOG_WRN("Connect to %s failed: 0x%02x %s", bt_conn_dst_str(conn), err,
			bt_hci_err_to_str(err));

		if (default_conn != NULL && default_conn == conn) {
			bt_conn_unref(default_conn);
			default_conn = NULL;
		}
		atomic_set(&pc_connect_pending, 0);
		k_event_post(&pc_audio_evt, EV_CONNECT_FAILED);
		return;
	}

	if (conn != default_conn) {
		LOG_DBG("Ignoring unexpected connection");
		return;
	}

	atomic_set(&pc_connected, 1);
	atomic_set(&pc_connect_pending, 0);
	LOG_INF("Connected: %s", bt_conn_dst_str(conn));
	k_event_post(&pc_audio_evt, EV_CONNECTED);
}

static void pc_disconnected_cb(struct bt_conn *conn, uint8_t reason)
{
	if (conn != default_conn) {
		return;
	}

	LOG_INF("Disconnected: 0x%02x %s", reason, bt_hci_err_to_str(reason));

	bt_conn_unref(default_conn);
	default_conn = NULL;

	atomic_set(&pc_connected, 0);
	atomic_set(&pc_streaming, 0);
	atomic_set(&pc_connect_pending, 0);
	k_event_post(&pc_audio_evt, EV_DISCONNECTED);
}

static void pc_security_cb(struct bt_conn *conn, bt_security_t level, enum bt_security_err err)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(level);

	if (err == 0) {
		k_event_post(&pc_audio_evt, EV_SECURITY);
	} else {
		LOG_WRN("Security failed: %s (%d)", bt_security_err_to_str(err), err);
		k_event_post(&pc_audio_evt, EV_SECURITY_FAILED);
	}
}

BT_CONN_CB_DEFINE(pc_conn_callbacks) = {
	.connected = pc_connected_cb,
	.disconnected = pc_disconnected_cb,
	.security_changed = pc_security_cb,
};

static void pc_mtu_cb(struct bt_conn *conn, uint16_t tx, uint16_t rx)
{
	ARG_UNUSED(conn);
	LOG_DBG("MTU exchanged: %u/%u", tx, rx);
	k_event_post(&pc_audio_evt, EV_MTU);
}

static struct bt_gatt_cb pc_gatt_callbacks = {
	.att_mtu_updated = pc_mtu_cb,
};

static int pc_preset_from_cap(const struct bt_audio_codec_cap *codec_cap)
{
	struct bt_audio_codec_octets_per_codec_frame octets;
	const int freq = bt_audio_codec_cap_get_freq(codec_cap);
	const int dur = bt_audio_codec_cap_get_frame_dur(codec_cap);
	const int chans = bt_audio_codec_cap_get_supported_audio_chan_counts(codec_cap, true);

	if (freq < 0 || dur < 0 || chans < 0) {
		return -ENOENT;
	}
	if ((chans & BT_AUDIO_CODEC_CAP_CHAN_COUNT_1) == 0) {
		return -ENOENT;
	}
	if (bt_audio_codec_cap_get_octets_per_frame(codec_cap, &octets) != 0) {
		return -ENOENT;
	}

	for (int i = 0; i < PC_PRESET_COUNT; i++) {
		if ((freq & pc_preset_info[i].cap_freq) == 0) {
			continue;
		}
		if ((dur & pc_preset_info[i].cap_dur) == 0) {
			continue;
		}
		if (octets.min > pc_preset_info[i].octets ||
		    octets.max < pc_preset_info[i].octets) {
			continue;
		}
		return i;
	}

	return -ENOENT;
}

static void pc_pac_record_cb(struct bt_conn *conn, enum bt_audio_dir dir,
			     const struct bt_audio_codec_cap *codec_cap)
{
	int idx;

	ARG_UNUSED(conn);

	if (dir != BT_AUDIO_DIR_SINK || codec_cap == NULL ||
	    codec_cap->id != BT_HCI_CODING_FORMAT_LC3) {
		return;
	}

	idx = pc_preset_from_cap(codec_cap);
	if (idx < 0) {
		LOG_DBG("Sink PAC has no supported LC3 preset");
		return;
	}

	pac_seen = true;
	if (chosen_preset == PC_PRESET_NONE || idx < chosen_preset) {
		chosen_preset = idx;
		LOG_INF("Sink PAC advertises %s", pc_preset_name(idx));
	}
}

static void pc_endpoint_cb(struct bt_conn *conn, enum bt_audio_dir dir, struct bt_bap_ep *ep)
{
	ARG_UNUSED(conn);

	if (dir == BT_AUDIO_DIR_SINK && ep != NULL && sink_ep == NULL) {
		sink_ep = ep;
		LOG_INF("Remote sink ASE found");
	}
}

static void pc_discover_cb(struct bt_conn *conn, int err, enum bt_audio_dir dir)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(dir);

	discover_err = err;
	k_event_post(&pc_audio_evt, EV_DISCOVERED);
}

static void pc_location_cb(struct bt_conn *conn, enum bt_audio_dir dir, enum bt_audio_location loc)
{
	ARG_UNUSED(conn);
	LOG_DBG("Remote location dir %d loc 0x%08x", dir, (unsigned int)loc);
}

static void pc_supported_contexts_cb(struct bt_conn *conn, enum bt_audio_context snk_ctx,
				     enum bt_audio_context src_ctx)
{
	ARG_UNUSED(conn);
	LOG_DBG("Supported contexts snk 0x%x src 0x%x", (unsigned int)snk_ctx,
		(unsigned int)src_ctx);
}

static void pc_available_contexts_cb(struct bt_conn *conn, enum bt_audio_context snk_ctx,
				     enum bt_audio_context src_ctx)
{
	ARG_UNUSED(conn);
	LOG_DBG("Available contexts snk 0x%x src 0x%x", (unsigned int)snk_ctx,
		(unsigned int)src_ctx);
}

static void pc_config_rsp_cb(struct bt_bap_stream *stream, enum bt_bap_ascs_rsp_code rsp_code,
			     enum bt_bap_ascs_reason reason)
{
	ARG_UNUSED(stream);

	if (rsp_code != BT_BAP_ASCS_RSP_CODE_SUCCESS) {
		LOG_WRN("Configure rejected: rsp 0x%02x reason 0x%02x", rsp_code, reason);
		k_event_post(&pc_audio_evt, EV_CONFIG_FAILED);
	}
}

static void pc_qos_rsp_cb(struct bt_bap_stream *stream, enum bt_bap_ascs_rsp_code rsp_code,
			  enum bt_bap_ascs_reason reason)
{
	ARG_UNUSED(stream);

	if (rsp_code != BT_BAP_ASCS_RSP_CODE_SUCCESS) {
		LOG_WRN("QoS rejected: rsp 0x%02x reason 0x%02x", rsp_code, reason);
		k_event_post(&pc_audio_evt, EV_QOS_FAILED);
	}
}

static void pc_enable_rsp_cb(struct bt_bap_stream *stream, enum bt_bap_ascs_rsp_code rsp_code,
			     enum bt_bap_ascs_reason reason)
{
	ARG_UNUSED(stream);

	if (rsp_code != BT_BAP_ASCS_RSP_CODE_SUCCESS) {
		LOG_WRN("Enable rejected: rsp 0x%02x reason 0x%02x", rsp_code, reason);
		k_event_post(&pc_audio_evt, EV_ENABLE_FAILED);
	}
}

static struct bt_bap_unicast_client_cb pc_unicast_client_cbs = {
	.location = pc_location_cb,
	.supported_contexts = pc_supported_contexts_cb,
	.available_contexts = pc_available_contexts_cb,
	.config = pc_config_rsp_cb,
	.qos = pc_qos_rsp_cb,
	.enable = pc_enable_rsp_cb,
	.pac_record = pc_pac_record_cb,
	.endpoint = pc_endpoint_cb,
	.discover = pc_discover_cb,
};

/* --- stream ops ----------------------------------------------------------- */

static void pc_stream_configured(struct bt_bap_stream *stream,
				 const struct bt_bap_qos_cfg_pref *pref)
{
	ARG_UNUSED(stream);
	ARG_UNUSED(pref);
	k_event_post(&pc_audio_evt, EV_CONFIGURED);
}

static void pc_stream_qos_set(struct bt_bap_stream *stream)
{
	if (stream != NULL && stream->qos != NULL) {
		pc_frame_us = stream->qos->interval;
	}
	k_event_post(&pc_audio_evt, EV_QOS);
}

static void pc_stream_enabled(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	k_event_post(&pc_audio_evt, EV_ENABLED);
}

static void pc_stream_started(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	LOG_INF("Sink stream started by the server");
	k_event_post(&pc_audio_evt, EV_STARTED);
}

static void pc_stream_stopped(struct bt_bap_stream *stream, uint8_t reason)
{
	ARG_UNUSED(stream);
	LOG_INF("Sink stream stopped: 0x%02x", reason);
	atomic_set(&pc_streaming, 0);
	k_event_post(&pc_audio_evt, EV_STREAM_STOPPED);
}

static void pc_stream_disabled(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	atomic_set(&pc_streaming, 0);
}

static void pc_stream_released(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	atomic_set(&pc_streaming, 0);
	k_event_post(&pc_audio_evt, EV_RELEASED);
}

static void pc_stream_metadata_updated(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
}

static void pc_stream_connected(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	k_event_post(&pc_audio_evt, EV_ISO_CONNECTED);
}

static void pc_stream_sent(struct bt_bap_stream *stream)
{
	ARG_UNUSED(stream);
	k_event_post(&pc_audio_evt, EV_SENT);
}

static struct bt_bap_stream_ops pc_stream_ops = {
	.configured = pc_stream_configured,
	.qos_set = pc_stream_qos_set,
	.enabled = pc_stream_enabled,
	.started = pc_stream_started,
	.stopped = pc_stream_stopped,
	.disabled = pc_stream_disabled,
	.released = pc_stream_released,
	.metadata_updated = pc_stream_metadata_updated,
	.connected = pc_stream_connected,
	.sent = pc_stream_sent,
};

/* ------------------------------------------------------------------------- */
/* Scanning and connecting                                                   */
/* ------------------------------------------------------------------------- */

struct pc_adv_ctx {
	const bt_addr_le_t *addr;
	int8_t rssi;
};

static void pc_device_found(const bt_addr_le_t *addr, int8_t rssi, uint8_t type,
			    struct net_buf_simple *ad);

static void pc_scan_start(void)
{
	const int err = bt_le_scan_start(BT_LE_SCAN_PASSIVE, pc_device_found);

	if (err != 0) {
		LOG_ERR("bt_le_scan_start: %d", err);
	}
}

static void pc_scan_stop(void)
{
	const int err = bt_le_scan_stop();

	if (err != 0 && err != -EALREADY) {
		LOG_DBG("bt_le_scan_stop: %d", err);
	}
}

static bool pc_check_ascs(struct bt_data *data, void *user_data)
{
	const struct pc_adv_ctx *ctx = user_data;
	struct net_buf_simple svc_data;
	uint16_t uuid_val;
	const struct bt_uuid *uuid;
	int err;

	if (data->type != BT_DATA_SVC_DATA16) {
		return true;
	}
	if (data->data_len < sizeof(uuid_val)) {
		return true;
	}

	net_buf_simple_init_with_data(&svc_data, (void *)data->data, data->data_len);
	uuid_val = net_buf_simple_pull_le16(&svc_data);
	uuid = BT_UUID_DECLARE_16(sys_le16_to_cpu(uuid_val));

	if (bt_uuid_cmp(uuid, BT_UUID_ASCS) != 0) {
		return true;
	}

	/* announcement type (1) + audio contexts (4) + meta length (1) */
	if (svc_data.len < 6U) {
		return true;
	}

	(void)net_buf_simple_pull_u8(&svc_data);
	(void)net_buf_simple_pull_le32(&svc_data);
	(void)net_buf_simple_pull_u8(&svc_data);

	if (atomic_get(&pc_connect_pending) != 0 || default_conn != NULL) {
		return false;
	}
	atomic_set(&pc_connect_pending, 1);

	pc_scan_stop();

	LOG_INF("Audio server found: %s (RSSI %d); connecting", bt_addr_le_str(ctx->addr),
		ctx->rssi);

	err = bt_conn_le_create(ctx->addr, BT_CONN_LE_CREATE_CONN, BT_BAP_CONN_PARAM_RELAXED,
				&default_conn);
	if (err != 0) {
		LOG_WRN("bt_conn_le_create: %d", err);
		atomic_set(&pc_connect_pending, 0);
		pc_scan_start();
	}

	return false;
}

static void pc_device_found(const bt_addr_le_t *addr, int8_t rssi, uint8_t type,
			    struct net_buf_simple *ad)
{
	struct pc_adv_ctx ctx = {
		.addr = addr,
		.rssi = rssi,
	};

	if (default_conn != NULL || atomic_get(&pc_connect_pending) != 0) {
		return;
	}

	/* Connectable advertisers only. */
	if (type != BT_GAP_ADV_TYPE_ADV_IND &&
	    type != BT_GAP_ADV_TYPE_ADV_DIRECT_IND &&
	    type != BT_GAP_ADV_TYPE_EXT_ADV) {
		return;
	}

	/* Audio servers are expected next to the unit. */
	if (rssi < PC_MIN_RSSI) {
		return;
	}

	(void)bt_data_parse(ad, pc_check_ascs, &ctx);
}

struct pc_bond_ctx {
	bt_addr_le_t addr;
	bool found;
};

static void pc_bond_cb(const struct bt_bond_info *info, void *user_data)
{
	struct pc_bond_ctx *ctx = user_data;

	if (!ctx->found) {
		ctx->addr = info->addr;
		ctx->found = true;
	}
}

static int pc_connect_saved_bond(void)
{
	struct pc_bond_ctx ctx = { 0 };
	int err;

	bt_foreach_bond(BT_ID_DEFAULT, pc_bond_cb, &ctx);
	if (!ctx.found) {
		LOG_INF("No bonded earbud saved");
		return -ENOENT;
	}

	LOG_INF("Trying saved earbud %s", bt_addr_le_str(&ctx.addr));
	atomic_set(&pc_connect_pending, 1);

	err = bt_conn_le_create(&ctx.addr, BT_CONN_LE_CREATE_CONN, BT_BAP_CONN_PARAM_RELAXED,
				&default_conn);
	if (err != 0) {
		LOG_WRN("bt_conn_le_create(saved): %d", err);
		atomic_set(&pc_connect_pending, 0);
	}

	return err;
}

/* ------------------------------------------------------------------------- */
/* State machine                                                             */
/* ------------------------------------------------------------------------- */

static int pc_wait_stage(uint32_t want, uint32_t fail, int timeout_ms)
{
	const uint32_t got = k_event_wait(&pc_audio_evt, want | fail | EV_ABORT_BITS, false,
					  K_MSEC(timeout_ms));

	if ((got & EV_ABORT_BITS) != 0U) {
		return -ECONNRESET;
	}
	if ((got & want) != 0U) {
		return 0;
	}
	if (fail != 0U && (got & fail) != 0U) {
		return -EIO;
	}

	return -ETIMEDOUT;
}

static void pc_reset_session(void)
{
	atomic_set(&pc_connected, 0);
	atomic_set(&pc_streaming, 0);
	atomic_set(&pc_connect_pending, 0);
	atomic_set(&pc_playing, 0);
	atomic_set(&pc_stop, 0);
	atomic_set(&pc_reconnect, 0);

	pc_seq_num = 0U;
	sink_ep = NULL;
	chosen_preset = PC_PRESET_NONE;
	pac_seen = false;
	discover_err = 0;

	k_event_clear(&pc_audio_evt, 0xFFFFFFFFU);
}

static int pc_connect_stage(void)
{
	int err;

	if (default_conn != NULL) {
		/* A previous disconnect is still settling. */
		(void)k_event_wait(&pc_audio_evt, EV_DISCONNECTED, true, K_MSEC(PC_DISCONNECT_WAIT_MS));
		if (default_conn != NULL) {
			return -EBUSY;
		}
	}

	pc_scan_start();
	err = pc_wait_stage(EV_CONNECTED, EV_CONNECT_FAILED, PC_SCAN_TIMEOUT_MS);
	pc_scan_stop();

	if (err == 0) {
		return 0;
	}

	if (err == -ETIMEDOUT) {
		LOG_INF("No close ASCS advertiser in %d ms; trying saved bond",
			PC_SCAN_TIMEOUT_MS);
		if (pc_connect_saved_bond() == 0) {
			err = pc_wait_stage(EV_CONNECTED, EV_CONNECT_FAILED, PC_SCAN_TIMEOUT_MS);
			if (err == 0) {
				return 0;
			}
		}
	}

	atomic_set(&pc_connect_pending, 0);
	return err;
}

static int pc_security_stage(void)
{
	int err;

	/* The MTU exchange is best effort; ASCS discovery needs it but it may
	 * already have happened by the time we get here.
	 */
	(void)pc_wait_stage(EV_MTU, 0U, PC_MTU_WAIT_MS);

	if (default_conn == NULL) {
		return -ECONNRESET;
	}

	err = bt_conn_set_security(default_conn, BT_SECURITY_L2);
	if (err != 0) {
		LOG_WRN("bt_conn_set_security: %d", err);
		return err;
	}

	return pc_wait_stage(EV_SECURITY, EV_SECURITY_FAILED, PC_SECURITY_WAIT_MS);
}

static int pc_discover_stage(void)
{
	int err;

	k_event_clear(&pc_audio_evt, EV_DISCOVERED);
	sink_ep = NULL;
	chosen_preset = PC_PRESET_NONE;
	pac_seen = false;
	discover_err = 0;

	err = bt_bap_unicast_client_discover(default_conn, BT_AUDIO_DIR_SINK);
	if (err != 0) {
		LOG_WRN("bt_bap_unicast_client_discover: %d", err);
		return err;
	}

	err = pc_wait_stage(EV_DISCOVERED, 0U, PC_DISCOVER_WAIT_MS);
	if (err != 0) {
		return err;
	}
	if (discover_err != 0 && discover_err != BT_ATT_ERR_ATTRIBUTE_NOT_FOUND) {
		return -EIO;
	}
	if (sink_ep == NULL) {
		LOG_WRN("No sink ASE discovered");
		return -ENODEV;
	}

	if (pac_seen) {
		LOG_INF("Sink PAC selected preset %s", pc_preset_name(chosen_preset));
	} else {
		LOG_WRN("No usable sink PAC; will try the mandatory preset first");
	}

	return 0;
}

static int pc_configure_stage(void)
{
	int idx;
	int err;

	if (pac_seen && chosen_preset != PC_PRESET_NONE) {
		idx = chosen_preset;
	} else if (forced_preset != PC_PRESET_NONE) {
		idx = forced_preset;
	} else {
		idx = PC_PRESET_16_2;
	}

	err = pc_select_preset(idx);
	if (err != 0) {
		return err;
	}

	k_event_clear(&pc_audio_evt, EV_CONFIGURED | EV_CONFIG_FAILED | EV_RELEASED);
	err = bt_bap_stream_config(default_conn, &sink_stream, sink_ep, &codec_cfg.codec_cfg);
	if (err == 0) {
		err = pc_wait_stage(EV_CONFIGURED, EV_CONFIG_FAILED | EV_RELEASED,
				    PC_CONFIGURE_WAIT_MS);
	}

	if (err == 0) {
		pc_apply_preset_numbers(idx);
		LOG_INF("Sink configured with %s", pc_preset_name(idx));
		/* Remember a PAC-less choice for the next reconnect; always
		 * re-evaluate when the sink actually advertises PACs.
		 */
		forced_preset = pac_seen ? PC_PRESET_NONE : idx;
		return 0;
	}

	/* NCS v3.4.0 cannot reconfigure a stream that is already attached to an
	 * endpoint (bt_bap_stream_config returns -EALREADY), so the fallback
	 * preset needs a fresh connection.
	 */
	if (!pac_seen && forced_preset == PC_PRESET_NONE) {
		LOG_WRN("%s rejected (%d); reconnecting to try %s", pc_preset_name(idx), err,
			pc_preset_name(PC_PRESET_48_2));
		forced_preset = PC_PRESET_48_2;
		return -EAGAIN;
	}

	return err;
}

static int pc_group_stage(void)
{
	struct bt_bap_unicast_group_stream_param stream_param;
	struct bt_bap_unicast_group_stream_pair_param pair_param;
	struct bt_bap_unicast_group_param group_param;
	int err;

	stream_param.stream = &sink_stream;
	stream_param.qos = &codec_cfg.qos;

	pair_param.tx_param = &stream_param;
	pair_param.rx_param = NULL;

	group_param.params_count = 1U;
	group_param.params = &pair_param;
	group_param.packing = BT_ISO_PACKING_SEQUENTIAL;

	err = bt_bap_unicast_group_create(&group_param, &unicast_group);
	if (err != 0) {
		LOG_WRN("bt_bap_unicast_group_create: %d", err);
		return err;
	}

	k_event_clear(&pc_audio_evt, EV_QOS | EV_QOS_FAILED);
	err = bt_bap_stream_qos(default_conn, unicast_group);
	if (err == 0) {
		err = pc_wait_stage(EV_QOS, EV_QOS_FAILED, PC_STAGE_WAIT_MS);
	}
	if (err != 0) {
		return err;
	}

	k_event_clear(&pc_audio_evt, EV_ENABLED | EV_ENABLE_FAILED);
	err = bt_bap_stream_enable(&sink_stream, codec_cfg.codec_cfg.meta,
				   codec_cfg.codec_cfg.meta_len);
	if (err == 0) {
		err = pc_wait_stage(EV_ENABLED, EV_ENABLE_FAILED, PC_STAGE_WAIT_MS);
	}
	if (err != 0) {
		return err;
	}

	k_event_clear(&pc_audio_evt, EV_ISO_CONNECTED);
	err = bt_bap_stream_connect(&sink_stream);
	if (err == -EALREADY) {
		err = 0;
	} else if (err == 0) {
		err = pc_wait_stage(EV_ISO_CONNECTED, 0U, PC_ISO_CONNECT_WAIT_MS);
	}
	if (err != 0) {
		return err;
	}

	/* The earbud is the sink ASE: per BAP the server moves it to streaming
	 * once the CIS is up.  Do not call bt_bap_stream_start() here; wait for
	 * the started callback instead.
	 */
	err = pc_wait_stage(EV_STARTED, EV_RELEASED | EV_STREAM_STOPPED, PC_START_WAIT_MS);
	if (err != 0) {
		return err;
	}

	return 0;
}

static int pc_encoder_setup(void)
{
	const uint32_t spf = (pc_sample_rate * pc_frame_us) / 1000000U;

	if (spf == 0U || spf > PC_MAX_FRAME_SAMPLES) {
		LOG_ERR("Unsupported frame geometry: %u Hz, %u us", pc_sample_rate, pc_frame_us);
		return -EINVAL;
	}

	pc_lc3.samples_per_frame = (uint16_t)spf;
	pc_lc3.enc = lc3_setup_encoder((int)pc_frame_us, (int)pc_sample_rate, 0, &pc_lc3.mem);
	if (pc_lc3.enc == NULL) {
		LOG_ERR("lc3_setup_encoder failed");
		return -ENOEXEC;
	}

	LOG_INF("LC3 encoder ready: %u Hz, %u us, %u samples/frame, %u octets",
		pc_sample_rate, pc_frame_us, spf, pc_octets);
	return 0;
}

/* ------------------------------------------------------------------------- */
/* Playback                                                                  */
/* ------------------------------------------------------------------------- */

static void pc_wait_tx_slot(void)
{
	/* Drop a sent bit left over from an earlier frame so this retry waits
	 * either for a fresh TX-complete callback or the full 2 ms.
	 */
	k_event_clear(&pc_audio_evt, EV_SENT);
	(void)k_event_wait(&pc_audio_evt, EV_SENT | EV_ABORT_BITS, true,
			   K_USEC(PC_TX_RETRY_US));
}

static int pc_send_frame(const int16_t *pcm, uint32_t samples)
{
	(void)samples;

	for (int retry = 0; retry < PC_SEND_RETRIES; retry++) {
		struct net_buf *buf;
		int err;

		if (!pc_stream_ok() || atomic_get(&pc_reconnect) != 0) {
			return -ECANCELED;
		}

		buf = net_buf_alloc(&pc_tx_pool, K_NO_WAIT);
		if (buf == NULL) {
			pc_wait_tx_slot();
			continue;
		}

		net_buf_reserve(buf, BT_ISO_CHAN_SEND_RESERVE);

		if (lc3_encode(pc_lc3.enc, LC3_PCM_FORMAT_S16, pcm, 1, (int)pc_octets,
			       net_buf_tail(buf)) < 0) {
			net_buf_unref(buf);
			LOG_ERR("lc3_encode failed (samples %u)", samples);
			return -EIO;
		}
		net_buf_add(buf, pc_octets);

		err = bt_bap_stream_send(&sink_stream, buf, pc_seq_num);
		if (err >= 0) {
			pc_seq_num++;
			return 0;
		}

		net_buf_unref(buf);

		if (err != -ENOMEM && err != -EAGAIN) {
			LOG_WRN("bt_bap_stream_send: %d", err);
			return err;
		}

		pc_wait_tx_slot();
	}

	/* Never drop cadence silently. */
	LOG_WRN("Dropped one LC3 frame after %d retries", PC_SEND_RETRIES);
	return -EAGAIN;
}

static void pc_sleep_until(int64_t *next_us)
{
	int64_t now_us = k_uptime_get() * 1000;
	int64_t delay = *next_us - now_us;

	if (delay > PC_MAX_SLEEP_US) {
		delay = PC_MAX_SLEEP_US;
	}
	if (delay > 0) {
		k_usleep((int32_t)delay);
	}

	*next_us += pc_frame_us;

	/* If a send stalled for longer than a frame, resynchronise instead of
	 * trying to catch up in a burst.
	 */
	now_us = k_uptime_get() * 1000;
	if (*next_us < now_us) {
		*next_us = now_us;
	}
}

/* --- streaming clip resampler --------------------------------------------- */

/* The clip stream owns the storage handle; the interpolation state and math
 * live in struct pc_resampler (<pc/resampler.h>).
 */
struct pc_clip_stream {
	void *handle;
	struct pc_resampler rs;
};

enum pc_call_phase {
	PC_CALL_DONE = 0,
	PC_CALL_PLAY,   /* pulling from the open clip */
	PC_CALL_OPEN,   /* need to open the next clip */
	PC_CALL_GAP,    /* emitting the inter-clip silence */
};

struct pc_call_state {
	struct pc_clip_stream stream;
	const char *paths[PC_CLIP_SLOTS];
	uint8_t next_clip;
	bool played_any;
	enum pc_call_phase phase;
	uint32_t gap_frames;
	uint32_t gap_total;
	int32_t gain_q10;
};

/* One call at a time; audio thread only. */
static struct pc_call_state pc_call;

/* Produce one resampled, volume-adjusted output sample.
 * Returns 1 on success, 0 at the end of the clip, negative errno on error.
 */
static int pc_clip_stream_next(struct pc_clip_stream *st, int16_t *out, int32_t gain_q10)
{
	return pc_resampler_next(&st->rs, pc_clip_read, st->handle, gain_q10, out);
}

static void pc_call_close(struct pc_call_state *cs)
{
	pc_clip_close(cs->stream.handle);
	cs->stream.handle = NULL;
	cs->phase = PC_CALL_DONE;
}

static void pc_call_reset(struct pc_call_state *cs, const struct pc_call_req *req)
{
	cs->stream.handle = NULL;
	pc_resampler_init(&cs->stream.rs, 0U, pc_sample_rate);

	for (int i = 0; i < PC_CLIP_SLOTS; i++) {
		cs->paths[i] = req->clips[i];
	}

	cs->next_clip = 0U;
	cs->played_any = false;
	cs->phase = PC_CALL_OPEN;
	cs->gap_frames = 0U;
	cs->gap_total = (pc_sample_rate / 1000U) * PC_GAP_MS;
	cs->gain_q10 = pc_resampler_gain_q10((uint8_t)atomic_get(&pc_volume));
}

/* Open the next non-empty path.  Returns true when a clip is streaming. */
static bool pc_call_open_next(struct pc_call_state *cs)
{
	while (cs->next_clip < PC_CLIP_SLOTS) {
		const char *path = cs->paths[cs->next_clip];
		void *handle = NULL;
		int err;

		cs->next_clip++;
		if (path[0] == '\0') {
			continue;
		}

		err = pc_clip_open(path, &handle);
		if (err != 0) {
			/* Report and skip: the rest of the call still plays. */
			LOG_ERR("Clip %s open failed: %d", path, err);
			continue;
		}

		cs->stream.handle = handle;
		/* Reset the stream so this clip starts at its own sample 0. */
		pc_resampler_init(&cs->stream.rs, pc_clip_rate(handle), pc_sample_rate);
		return true;
	}

	return false;
}

/* Pull one sample of the call: clip audio, inter-clip silence, or end.
 * Returns 1 when *out is valid, 0 when the call is finished.
 */
static int pc_call_pull_sample(struct pc_call_state *cs, int16_t *out)
{
	for (;;) {
		switch (cs->phase) {
		case PC_CALL_PLAY: {
			const int r = pc_clip_stream_next(&cs->stream, out, cs->gain_q10);

			if (r > 0) {
				return 1;
			}
			if (r < 0) {
				LOG_ERR("Clip read failed: %d", r);
			}

			pc_clip_close(cs->stream.handle);
			cs->stream.handle = NULL;
			cs->phase = PC_CALL_OPEN;
			continue;
		}
		case PC_CALL_OPEN:
			if (!pc_call_open_next(cs)) {
				cs->phase = PC_CALL_DONE;
				return 0;
			}
			if (cs->played_any) {
				cs->gap_frames = cs->gap_total;
				cs->phase = PC_CALL_GAP;
			} else {
				cs->played_any = true;
				cs->phase = PC_CALL_PLAY;
			}
			continue;
		case PC_CALL_GAP:
			if (cs->gap_frames > 0U) {
				cs->gap_frames--;
				*out = 0;
				return 1;
			}
			cs->phase = PC_CALL_PLAY;
			continue;
		case PC_CALL_DONE:
		default:
			return 0;
		}
	}
}

static int pc_call_pull_cb(void *ctx, int16_t *out)
{
	return pc_call_pull_sample((struct pc_call_state *)ctx, out);
}

/* Fill exactly one LC3 frame; the tail is zero-padded when the call ends.
 * Returns false once the call is over (the frame then holds silence).
 */
static bool pc_call_fill_frame(struct pc_call_state *cs, int16_t *dst, uint32_t frames)
{
	return pc_resampler_fill_frame(pc_call_pull_cb, cs, dst, frames);
}

static void pc_play_call(const struct pc_call_req *req, int64_t *next_us)
{
	struct pc_call_state *cs = &pc_call;
	const uint32_t spf = pc_lc3.samples_per_frame;

	if (spf == 0U || spf > PC_MAX_FRAME_SAMPLES || pc_sample_rate == 0U) {
		return;
	}

	pc_call_reset(cs, req);

	while (pc_stream_ok() && atomic_get(&pc_reconnect) == 0) {
		bool alive;

		/* Stop after the frame already in flight, never mid-frame. */
		if (atomic_get(&pc_stop) != 0) {
			break;
		}

		alive = pc_call_fill_frame(cs, pc_frame_buf, spf);

		if (pc_send_frame(pc_frame_buf, spf) != 0) {
			break;
		}

		pc_sleep_until(next_us);

		if (!alive) {
			break;
		}
	}

	pc_call_close(cs);
}

static void pc_playback_loop(void)
{
	int64_t next_us = k_uptime_get() * 1000;

	if (pc_lc3.enc == NULL || pc_lc3.samples_per_frame == 0U) {
		return;
	}

	while (pc_stream_ok() && atomic_get(&pc_reconnect) == 0) {
		struct pc_call_req req;

		if (k_msgq_get(&pc_call_q, &req, K_NO_WAIT) == 0) {
			atomic_set(&pc_playing, 1);
			pc_set_state(PC_ST_PLAYING);
			LOG_INF("Playing call %u: %s | %s | %s", req.sequence, req.clips[0],
				req.clips[1], req.clips[2]);

			/* A stop queued before this call was taken must not
			 * cancel it; a stop during it aborts inside the loop.
			 */
			atomic_set(&pc_stop, 0);

			pc_play_call(&req, &next_us);

			atomic_set(&pc_playing, 0);
			atomic_set(&pc_stop, 0);

			if (!pc_stream_ok()) {
				break;
			}

			pc_set_state(PC_ST_READY);
			next_us = k_uptime_get() * 1000;
			continue;
		}

		/* Keep the ISO stream alive with LC3-encoded silence. */
		if (pc_send_frame(pc_silence, pc_lc3.samples_per_frame) != 0) {
			break;
		}

		pc_sleep_until(&next_us);
	}
}

/* ------------------------------------------------------------------------- */
/* Session teardown                                                          */
/* ------------------------------------------------------------------------- */

static void pc_teardown_session(void)
{
	atomic_set(&pc_streaming, 0);
	atomic_set(&pc_connected, 0);
	atomic_set(&pc_playing, 0);

	if (default_conn != NULL) {
		const int err = bt_conn_disconnect(default_conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);

		if (err == 0) {
			/* The disconnected callback owns the connection reference. */
			(void)k_event_wait(&pc_audio_evt, EV_DISCONNECTED, true,
					   K_MSEC(PC_DISCONNECT_WAIT_MS));
		} else if (err != -ENOTCONN && err != -EALREADY) {
			LOG_DBG("bt_conn_disconnect: %d", err);
		}
	}

	if (unicast_group != NULL) {
		for (int i = 0; i < PC_GROUP_DELETE_RETRIES; i++) {
			const int err = bt_bap_unicast_group_delete(unicast_group);

			if (err == 0) {
				unicast_group = NULL;
				break;
			}
			k_msleep(PC_GROUP_DELETE_POLL_MS);
		}

		if (unicast_group != NULL) {
			LOG_WRN("Unicast group busy; retrying next session");
		}
	}

	atomic_set(&pc_reconnect, 0);
}

static void pc_wait_backoff(uint32_t *backoff_ms)
{
	LOG_INF("Retrying in %u ms", (unsigned int)*backoff_ms);

	/* Make pc_audio_reconnect() shorten a long backoff instead of waiting
	 * it out.
	 */
	const uint32_t got = k_event_wait(&pc_audio_evt, EV_RECONNECT_REQ, true,
					  K_MSEC(*backoff_ms));

	if ((got & EV_RECONNECT_REQ) != 0U) {
		atomic_set(&pc_reconnect, 0);
	}

	*backoff_ms = MIN(*backoff_ms * 2U, PC_BACKOFF_MAX_MS);
}

/* ------------------------------------------------------------------------- */
/* Audio thread                                                              */
/* ------------------------------------------------------------------------- */

static void pc_audio_thread(void *p1, void *p2, void *p3)
{
	uint32_t backoff_ms = PC_BACKOFF_MIN_MS;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	LOG_INF("Audio thread started");

	for (;;) {
		int err;

		pc_reset_session();
		pc_set_state(PC_ST_PAIRING);

		err = pc_connect_stage();
		if (err != 0) {
			goto failed;
		}

		pc_set_state(PC_ST_CONNECTING);

		err = pc_security_stage();
		if (err != 0) {
			goto failed;
		}

		err = pc_discover_stage();
		if (err != 0) {
			goto failed;
		}

		err = pc_configure_stage();
		if (err == -EAGAIN) {
			/* Immediate retry after a preset fallback; this keeps
			 * the user-visible backoff for real failures only.
			 */
			pc_teardown_session();
			k_msleep(PC_PRESET_RETRY_MS);
			continue;
		}
		if (err != 0) {
			goto failed;
		}

		err = pc_group_stage();
		if (err != 0) {
			goto failed;
		}

		err = pc_encoder_setup();
		if (err != 0) {
			goto failed;
		}

		/* The server may have stopped the stream between the started
		 * callback and the encoder setup above.
		 */
		if (k_event_test(&pc_audio_evt, EV_STREAM_STOPPED | EV_RELEASED | EV_ABORT_BITS) != 0U) {
			err = -ECONNRESET;
			goto failed;
		}

		atomic_set(&pc_streaming, 1);
		backoff_ms = PC_BACKOFF_MIN_MS;
		pc_set_state(PC_ST_READY);

		pc_playback_loop();

		pc_teardown_session();
		pc_set_state(PC_ST_NO_EARBUD);
		pc_wait_backoff(&backoff_ms);
		continue;

failed:
		LOG_WRN("Audio session failed: %d", err);
		pc_teardown_session();
		pc_set_state(PC_ST_NO_EARBUD);
		pc_wait_backoff(&backoff_ms);
	}
}

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

int pc_audio_start(void)
{
	int err;

	if (pc_started) {
		return 0;
	}

	/* Registering before bt_enable() is safe: the client callback list is
	 * independent of the host being enabled.  Keep it once-only so a
	 * failed bt_enable() can be retried.
	 */
	if (!pc_cb_registered) {
		err = bt_bap_unicast_client_register_cb(&pc_unicast_client_cbs);
		if (err != 0) {
			LOG_ERR("bt_bap_unicast_client_register_cb: %d", err);
			return err;
		}
		pc_cb_registered = true;
	}

	sink_stream.ops = &pc_stream_ops;

	err = bt_enable(NULL);
	if (err != 0) {
		LOG_ERR("bt_enable: %d", err);
		return err;
	}

#if defined(CONFIG_SETTINGS)
	/* bt_enable() has called settings_subsys_init(); loading here restores
	 * the persisted bonds (and the local identity) before the state
	 * machine starts scanning.  Without it bt_foreach_bond() sees no
	 * saved earbud after a reboot.
	 */
	err = settings_load();
	if (err != 0) {
		LOG_WRN("settings_load: %d", err);
	}
#endif

	bt_gatt_cb_register(&pc_gatt_callbacks);

	/* Mount the clip storage unless main already did (idempotent).  A
	 * failure is logged but does not stop the audio link; playback then
	 * reports -ENODEV for every clip.
	 */
	err = pc_storage_mount();
	if (err != 0) {
		LOG_WRN("pc_storage_mount: %d", err);
	}

	k_thread_create(&pc_audio_thread_data, pc_audio_stack,
			K_THREAD_STACK_SIZEOF(pc_audio_stack), pc_audio_thread, NULL, NULL, NULL,
			PC_AUDIO_THREAD_PRIO, 0, K_NO_WAIT);
	(void)k_thread_name_set(&pc_audio_thread_data, "pc_audio");

	pc_started = true;
	pc_set_state(PC_ST_PAIRING);
	return 0;
}

bool pc_audio_ready(void)
{
	return atomic_get(&pc_connected) != 0 && atomic_get(&pc_streaming) != 0;
}

bool pc_audio_busy(void)
{
	return atomic_get(&pc_playing) != 0 || k_msgq_num_used_get(&pc_call_q) > 0U;
}

static void pc_copy_clip(char *dst, const char *src)
{
	if (src == NULL) {
		dst[0] = '\0';
		return;
	}

	size_t len = strlen(src);

	if (len > PC_CLIP_PATH_MAX - 1U) {
		len = PC_CLIP_PATH_MAX - 1U;
	}
	memcpy(dst, src, len);
	dst[len] = '\0';
}

bool pc_audio_play(const char *clip_a, const char *clip_b, const char *clip_c)
{
	struct pc_call_req req = { 0 };

	if (!pc_audio_ready()) {
		return false;
	}

	pc_copy_clip(req.clips[0], clip_a);
	pc_copy_clip(req.clips[1], clip_b);
	pc_copy_clip(req.clips[2], clip_c);

	if (req.clips[0][0] == '\0' && req.clips[1][0] == '\0' && req.clips[2][0] == '\0') {
		return false;
	}

	req.sequence = (uint32_t)atomic_inc(&pc_play_seq);

	if (k_msgq_put(&pc_call_q, &req, K_NO_WAIT) != 0) {
		return false;
	}

	k_mutex_lock(&last_req_lock, K_FOREVER);
	last_req = req;
	last_req_valid = true;
	k_mutex_unlock(&last_req_lock);

	return true;
}

bool pc_audio_recall(void)
{
	struct pc_call_req req;

	k_mutex_lock(&last_req_lock, K_FOREVER);
	if (!last_req_valid) {
		k_mutex_unlock(&last_req_lock);
		return false;
	}
	req = last_req;
	k_mutex_unlock(&last_req_lock);

	req.sequence = (uint32_t)atomic_inc(&pc_play_seq);

	/* Recall is allowed while reconnecting: the call waits in the queue
	 * and plays as soon as the stream is ready.
	 */
	return k_msgq_put(&pc_call_q, &req, K_NO_WAIT) == 0;
}

void pc_audio_stop(void)
{
	k_msgq_purge(&pc_call_q);
	atomic_set(&pc_stop, 1);
	atomic_set(&pc_playing, 0);
}

void pc_audio_reconnect(void)
{
	atomic_set(&pc_reconnect, 1);
	k_event_post(&pc_audio_evt, EV_RECONNECT_REQ);
}

void pc_audio_set_volume(uint8_t volume)
{
	if (volume < PC_VOLUME_MIN) {
		volume = PC_VOLUME_MIN;
	} else if (volume > PC_VOLUME_MAX) {
		volume = PC_VOLUME_MAX;
	}

	atomic_set(&pc_volume, (atomic_val_t)volume);
}

uint8_t pc_audio_volume(void)
{
	return (uint8_t)atomic_get(&pc_volume);
}

const char *pc_audio_state(void)
{
	switch ((enum pc_audio_state)atomic_get(&pc_state)) {
	case PC_ST_PLAYING:
		return "PLAYING";
	case PC_ST_READY:
		return "READY";
	case PC_ST_CONNECTING:
		return "CONNECTING";
	case PC_ST_PAIRING:
		return "PAIRING";
	default:
		return "NO EARBUD";
	}
}

uint32_t pc_audio_frame_duration_us(void)
{
	return pc_frame_us;
}
