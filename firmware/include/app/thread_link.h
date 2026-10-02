/*
 * PitchComm call link: 802.15.4 over Thread, carried as UDPv6 datagrams.
 *
 * The coach is the Thread leader (FTD); field units are Sleepy End Devices.
 * This module owns the OpenThread bring-up and one non-blocking UDP socket.
 * The engine never touches the radio: pc_link_send() only enqueues.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One encoded pc::Packet, no application-layer wrapper. */
#define PC_LINK_PACKET_BYTES 56

/* Role indices match pc::Role in firmware/include/pc/protocol.h. */
#define PC_LINK_ROLE_COACH 0
#define PC_LINK_ROLE_CATCHER 1
#define PC_LINK_ROLE_PITCHER 2
#define PC_LINK_ROLE_SHORTSTOP 3
#define PC_LINK_ROLE_CENTERFIELD 4
#define PC_LINK_ROLES 5

/*
 * Receive callback, invoked on the radio thread for each decoded datagram from
 * a known role. It must copy the payload and return without blocking; the
 * engine inbox is a k_msgq.
 */
typedef void (*pc_link_rx_fn)(uint8_t source_role, const uint8_t *bytes, size_t len);

/*
 * Start OpenThread and the radio thread. role is the unit's own PC_LINK_ROLE_*.
 * Returns 0 when the stack started, negative errno otherwise. A unit without
 * provisioned team credentials starts in a not-ready state instead of failing.
 */
int pc_link_start(uint8_t role, pc_link_rx_fn rx_cb);

/* True once the interface is operational (leader for the coach, child for a SED). */
bool pc_link_ready(void);

/* Enqueue one datagram for target_role. Non-blocking; false when full. */
bool pc_link_send(uint8_t target_role, const uint8_t *bytes, size_t len);

/* State string for diagnostics: "UP", "ATTACHING", "NO CONFIG", "ERROR". */
const char *pc_link_state(void);

/* The unit's 802.15.4 extended address (8 bytes, big-endian wire order). */
void pc_link_local_eui64(uint8_t out[8]);

/* Radio-thread counters for diagnostics. */
uint32_t pc_link_tx_dropped(void);
uint32_t pc_link_rx_dropped(void);
uint32_t pc_link_tx_errors(void);

#ifdef __cplusplus
}
#endif
