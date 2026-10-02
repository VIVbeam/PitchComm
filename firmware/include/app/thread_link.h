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

/*
 * Receive callback, invoked on the radio thread for each decoded datagram from
 * a known unit. It must copy the payload and return without blocking; the
 * engine inbox is a k_msgq.
 */
typedef void (*pc_link_rx_fn)(uint8_t source_unit, const uint8_t *bytes, size_t len);

/*
 * Start OpenThread and the radio thread. role is this unit's index from the
 * generated catalog: unit 0 is the coach and units 1..PC_TEAM_UNIT_COUNT-1 are
 * the enrolled field units (see catalog.h and the PC_UNIT_<key> selectors).
 * The count comes from PC_TEAM_UNIT_COUNT in app/team_config.h, which
 * tools/provision.py writes as coach plus the enrolled units. Returns 0 when
 * the stack started, negative errno otherwise. A unit without provisioned team
 * credentials starts in a not-ready state instead of failing.
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
