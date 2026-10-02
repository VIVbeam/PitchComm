/*
 * HOST STUB: zephyr/bluetooth/audio/bap.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Member names follow
 * NCS v3.4.0 bap.h as used by audio_source.c. The host build never calls
 * these functions.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <zephyr/bluetooth/audio/audio.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/net_buf.h>

#ifdef __cplusplus
extern "C" {
#endif

struct bt_bap_ep;
struct bt_bap_unicast_group;
struct bt_bap_stream;

struct bt_bap_qos_cfg {
	uint32_t interval;
	uint16_t framing;
	uint8_t phy;
	uint8_t rtn;
};

struct bt_bap_qos_cfg_pref {
	uint32_t interval;
};

struct bt_bap_stream_ops {
	void (*configured)(struct bt_bap_stream *stream,
			   const struct bt_bap_qos_cfg_pref *pref);
	void (*qos_set)(struct bt_bap_stream *stream);
	void (*enabled)(struct bt_bap_stream *stream);
	void (*started)(struct bt_bap_stream *stream);
	void (*metadata_updated)(struct bt_bap_stream *stream);
	void (*disabled)(struct bt_bap_stream *stream);
	void (*stopped)(struct bt_bap_stream *stream, uint8_t reason);
	void (*released)(struct bt_bap_stream *stream);
	void (*sent)(struct bt_bap_stream *stream);
	void (*connected)(struct bt_bap_stream *stream);
	void (*disconnected)(struct bt_bap_stream *stream, uint8_t reason);
};

struct bt_bap_stream {
	struct bt_bap_stream_ops *ops;
	struct bt_bap_qos_cfg *qos;
};

struct bt_bap_lc3_preset {
	struct bt_audio_codec_cfg codec_cfg;
	struct bt_bap_qos_cfg qos;
};

enum bt_bap_ascs_rsp_code {
	BT_BAP_ASCS_RSP_CODE_SUCCESS = 0x00,
	BT_BAP_ASCS_RSP_CODE_NOT_SUPPORTED = 0x01,
	BT_BAP_ASCS_RSP_CODE_INVALID_CODEC = 0x08,
};

enum bt_bap_ascs_reason {
	BT_BAP_ASCS_REASON_NONE = 0x00,
	BT_BAP_ASCS_REASON_CODEC_NOT_SUPPORTED = 0x01,
	BT_BAP_ASCS_REASON_CODEC_SIZE_NOT_SUPPORTED = 0x03,
};

struct bt_bap_unicast_client_cb {
	void (*location)(struct bt_conn *conn, enum bt_audio_dir dir,
			 enum bt_audio_location loc);
	void (*supported_contexts)(struct bt_conn *conn,
				   enum bt_audio_context snk_context,
				   enum bt_audio_context src_context);
	void (*available_contexts)(struct bt_conn *conn,
				   enum bt_audio_context snk_context,
				   enum bt_audio_context src_context);
	void (*config)(struct bt_bap_stream *stream,
		       enum bt_bap_ascs_rsp_code rsp_code,
		       enum bt_bap_ascs_reason reason);
	void (*qos)(struct bt_bap_stream *stream,
		    enum bt_bap_ascs_rsp_code rsp_code,
		    enum bt_bap_ascs_reason reason);
	void (*enable)(struct bt_bap_stream *stream,
		       enum bt_bap_ascs_rsp_code rsp_code,
		       enum bt_bap_ascs_reason reason);
	void (*pac_record)(struct bt_conn *conn, enum bt_audio_dir dir,
			   const struct bt_audio_codec_cap *codec_cap);
	void (*endpoint)(struct bt_conn *conn, enum bt_audio_dir dir,
			 struct bt_bap_ep *ep);
	void (*discover)(struct bt_conn *conn, int err, enum bt_audio_dir dir);
};

struct bt_bap_unicast_group_stream_param {
	struct bt_bap_stream *stream;
	struct bt_bap_qos_cfg *qos;
};

struct bt_bap_unicast_group_stream_pair_param {
	struct bt_bap_unicast_group_stream_param *tx_param;
	struct bt_bap_unicast_group_stream_param *rx_param;
};

struct bt_bap_unicast_group_param {
	size_t params_count;
	struct bt_bap_unicast_group_stream_pair_param *params;
	int packing;
};

#define BT_BAP_CONN_PARAM_RELAXED ((const struct bt_le_conn_param *)0)

int bt_bap_unicast_client_register_cb(struct bt_bap_unicast_client_cb *cb);
int bt_bap_unicast_client_discover(struct bt_conn *conn, enum bt_audio_dir dir);
int bt_bap_stream_config(struct bt_conn *conn, struct bt_bap_stream *stream,
			 struct bt_bap_ep *ep,
			 struct bt_audio_codec_cfg *codec_cfg);
int bt_bap_stream_qos(struct bt_conn *conn,
		      struct bt_bap_unicast_group *group);
int bt_bap_stream_enable(struct bt_bap_stream *stream, const uint8_t *meta,
			 size_t meta_len);
int bt_bap_stream_connect(struct bt_bap_stream *stream);
int bt_bap_stream_send(struct bt_bap_stream *stream, struct net_buf *buf,
		       uint16_t seq_num);
int bt_bap_unicast_group_create(struct bt_bap_unicast_group_param *param,
				struct bt_bap_unicast_group **unicast_group);
int bt_bap_unicast_group_delete(struct bt_bap_unicast_group *unicast_group);

#ifdef __cplusplus
}
#endif
