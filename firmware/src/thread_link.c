/*
 * PitchComm call link: 802.15.4 over Thread, carried as UDPv6 datagrams.
 *
 * The coach is the Thread leader (FTD); field units are Sleepy End Devices.
 * This module owns the OpenThread bring-up and one non-blocking UDP socket.
 * The engine never touches the radio: pc_link_send() only enqueues.
 *
 * Build (coach, Thread leader):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/coach -- \
 *     -DEXTRA_CONF_FILE=roles/coach.conf
 * Build (shortstop, Thread sleepy end device):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/shortstop -- \
 *     -DEXTRA_CONF_FILE="roles/shortstop.conf;roles/field-common.conf"
 */

#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>

#if defined(CONFIG_OPENTHREAD)
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_l2.h>
#include <zephyr/net/openthread.h>
#include <zephyr/net/socket.h>

#include <openthread/dataset.h>
#include <openthread/instance.h>
#include <openthread/ip6.h>
#include <openthread/link.h>
#include <openthread/netdata.h>
#include <openthread/thread.h>
#endif /* CONFIG_OPENTHREAD */

#include "app/thread_link.h"

#if defined(__has_include)
#if __has_include("app/team_config.h")
#include "app/team_config.h"
#else
#include "app/team_config.example.h"
#endif
#else
#include "app/team_config.example.h"
#endif

#if !PC_TEAM_CONFIGURED
#include <zephyr/drivers/hwinfo.h>
#endif

#if PC_TEAM_CONFIGURED
_Static_assert(sizeof(PC_TEAM_NETWORK_NAME) <= 17, "PC_TEAM_NETWORK_NAME is longer than 16 bytes");
#endif

/* Drain/attach cadence of the radio thread, and its stack size. */
#define PC_LINK_POLL_MS 2
#define PC_LINK_RADIO_STACK 2048

/* One encoded pc::Packet plus its destination, queued by pc_link_send(). */
struct pc_link_frame {
	uint8_t target;
	uint8_t len;
	uint8_t bytes[PC_LINK_PACKET_BYTES];
};

#if defined(CONFIG_OPENTHREAD)
#define PC_LINK_TX_QUEUE_ENABLED 1
K_MSGQ_DEFINE(pc_tx_queue, sizeof(struct pc_link_frame), 8, 4);
#endif

static uint8_t local_role;
static pc_link_rx_fn rx_handler;
static bool link_started;
static bool link_error;
static uint8_t local_eui[8];
static atomic_t tx_dropped = ATOMIC_INIT(0);
static atomic_t rx_dropped = ATOMIC_INIT(0);
static atomic_t tx_errors = ATOMIC_INIT(0);

#if defined(CONFIG_OPENTHREAD)
static otInstance *ot_instance;
static int sock_fd = -1;
static int scope_id;
static uint8_t peer_address[PC_LINK_ROLES][16];
static K_THREAD_STACK_DEFINE(radio_stack, PC_LINK_RADIO_STACK);
static struct k_thread radio_thread_data;

/*
 * Link-local IPv6 address of an 802.15.4 EUI-64: fe80::/64 plus the EUI-64
 * with the universal/local bit of its first byte flipped. This is exactly how
 * OpenThread derives the link-local address from an extended address
 * (otIp6AddressFromExtAddr), so it also matches peers provisioned by EUI-64.
 */
static void link_local_from_eui(const uint8_t eui[8], uint8_t out[16])
{
	memset(out, 0, 16);
	out[0] = 0xfe;
	out[1] = 0x80;
	out[8] = (uint8_t)(eui[0] ^ 0x02u);
	memcpy(out + 9, eui + 1, 7);
}

/*
 * Provisioned bring-up. Runs on the caller's thread (main), before the radio
 * thread exists. OpenThread API calls are serialized with the module mutex
 * (openthread_mutex_lock), as required by the Zephyr port.
 */
static int link_bring_up(void)
{
	static const uint8_t network_key[16] = PC_TEAM_NETWORK_KEY;
	static const uint8_t extended_pan_id[8] = PC_TEAM_XPANID;
	static const uint8_t mesh_local_prefix[8] = PC_TEAM_MESH_LOCAL_PREFIX;
	static const char network_name[] = PC_TEAM_NETWORK_NAME;

	/*
	 * VERIFY(instance): the task brief wrote otGetInstance()/otInstanceGet().
	 * NCS v3.4.0 does not have those symbols; the module header
	 * modules/openthread/include/openthread.h declares
	 * openthread_get_default_instance(), reached through
	 * <zephyr/net/openthread.h>. That is the accessor used here.
	 */
	ot_instance = openthread_get_default_instance();
	if (ot_instance == NULL) {
		return -ENODEV;
	}

	for (unsigned i = 0; i < PC_LINK_ROLES; ++i) {
		link_local_from_eui(team_eui64[i], peer_address[i]);
	}

	otExtAddress extended;
	memcpy(extended.m8, team_eui64[local_role], sizeof(extended.m8));

	/*
	 * VERIFY(security policy): OpenThread API 580 (NCS v3.4.0) no longer has
	 * the .mFlags field the brief named; otSecurityPolicy is a bitfield struct
	 * and mRotationTime is in hours. The flags below are exactly
	 * SecurityPolicy::SetToDefaultFlags(): obtain/native/router/external
	 * commissioning and ToBLE on, everything else off. A zeroed flag byte
	 * (as the brief's .mFlags = 0 would have produced) clears
	 * mRoutersEnabled and can make the coach ineligible to lead.
	 */
	otOperationalDataset dataset;
	memset(&dataset, 0, sizeof(dataset));
	dataset.mChannel = PC_TEAM_CHANNEL;
	dataset.mPanId = PC_TEAM_PANID;
	memcpy(dataset.mNetworkKey.m8, network_key, sizeof(network_key));
	memcpy(dataset.mExtendedPanId.m8, extended_pan_id, sizeof(extended_pan_id));
	memcpy(dataset.mMeshLocalPrefix.m8, mesh_local_prefix, sizeof(mesh_local_prefix));
	memcpy(dataset.mNetworkName.m8, network_name, sizeof(network_name));
	dataset.mSecurityPolicy.mRotationTime = 672; /* hours (28 days) */
	dataset.mSecurityPolicy.mObtainNetworkKeyEnabled = true;
	dataset.mSecurityPolicy.mNativeCommissioningEnabled = true;
	dataset.mSecurityPolicy.mRoutersEnabled = true;
	dataset.mSecurityPolicy.mExternalCommissioningEnabled = true;
	dataset.mSecurityPolicy.mTobleLinkEnabled = true;
	/*
	 * VERIFY(dataset components): otDatasetSetActive() converts the struct
	 * through Dataset::Info, which only writes components flagged present.
	 * The brief did not mention mComponents; without these flags the dataset
	 * would be empty. The Active Timestamp must be present: OpenThread's
	 * Mle::BecomeLeader() rejects a partially complete dataset, and
	 * ActiveDatasetManager::IsComplete() is defined by the timestamp.
	 */
	dataset.mComponents.mIsActiveTimestampPresent = true; /* timestamp stays 0 */
	dataset.mComponents.mIsChannelPresent = true;
	dataset.mComponents.mIsPanIdPresent = true;
	dataset.mComponents.mIsNetworkKeyPresent = true;
	dataset.mComponents.mIsNetworkNamePresent = true;
	dataset.mComponents.mIsExtendedPanIdPresent = true;
	dataset.mComponents.mIsMeshLocalPrefixPresent = true;
	dataset.mComponents.mIsSecurityPolicyPresent = true;

	/*
	 * VERIFY(socket types): without CONFIG_POSIX_API, NCS v3.4.0 exposes
	 * struct net_sockaddr_in6 / net_socklen_t / NET_AF_INET6 / NET_SOCK_DGRAM,
	 * not the POSIX sockaddr_in6 / AF_INET6 / SOCK_DGRAM names the brief used.
	 */
	int sock = zsock_socket(NET_AF_INET6, NET_SOCK_DGRAM, NET_IPPROTO_UDP);
	if (sock < 0) {
		return -errno;
	}

	int v6_only = 1;
	(void)zsock_setsockopt(sock, NET_IPPROTO_IPV6, ZSOCK_IPV6_V6ONLY, &v6_only,
			       sizeof(v6_only));

	struct net_sockaddr_in6 bind_addr;
	memset(&bind_addr, 0, sizeof(bind_addr));
	bind_addr.sin6_family = NET_AF_INET6;
	bind_addr.sin6_port = sys_cpu_to_be16((uint16_t)PC_TEAM_UDP_PORT);
	if (zsock_bind(sock, (struct net_sockaddr *)&bind_addr, sizeof(bind_addr)) < 0) {
		int error = -errno;

		zsock_close(sock);
		return error;
	}

	struct net_if *iface = net_if_get_default();

	if (iface == NULL) {
		iface = net_if_get_first_by_type(&NET_L2_GET_NAME(OPENTHREAD));
	}
	scope_id = (iface != NULL) ? net_if_get_by_iface(iface) : 0;
	if (scope_id < 0) {
		scope_id = 0;
	}

	openthread_mutex_lock();
	otError error = otLinkSetExtendedAddress(ot_instance, &extended);
	if (error == OT_ERROR_NONE) {
		error = otDatasetSetActive(ot_instance, &dataset);
	}
	if (error == OT_ERROR_NONE) {
		error = otIp6SetEnabled(ot_instance, true);
	}
#if defined(CONFIG_OPENTHREAD_MTD_SED)
	/*
	 * Mirror the Zephyr OpenThread start path: a SED attaches with
	 * RxOnWhenIdle cleared, then sets its poll period.
	 */
	if (error == OT_ERROR_NONE) {
		otLinkModeConfig mode = otThreadGetLinkMode(ot_instance);

		mode.mRxOnWhenIdle = false;
		error = otThreadSetLinkMode(ot_instance, mode);
	}
	if (error == OT_ERROR_NONE) {
		error = otLinkSetPollPeriod(ot_instance, CONFIG_OPENTHREAD_POLL_PERIOD);
	}
#endif /* CONFIG_OPENTHREAD_MTD_SED */
	if (error == OT_ERROR_NONE) {
		error = otThreadSetEnabled(ot_instance, true);
	}
	openthread_mutex_unlock();

	if (error != OT_ERROR_NONE) {
		zsock_close(sock);
		return -EIO;
	}

	sock_fd = sock;
	return 0;
}

static void link_tx_frame(const struct pc_link_frame *frame)
{
	if (sock_fd < 0 || frame->target >= PC_LINK_ROLES) {
		atomic_inc(&tx_errors);
		return;
	}

	struct net_sockaddr_in6 dest;
	memset(&dest, 0, sizeof(dest));
	dest.sin6_family = NET_AF_INET6;
	dest.sin6_port = sys_cpu_to_be16((uint16_t)PC_TEAM_UDP_PORT);
	memcpy(dest.sin6_addr.s6_addr, peer_address[frame->target], 16);
	dest.sin6_scope_id = (uint8_t)scope_id;

	const ssize_t sent = zsock_sendto(sock_fd, frame->bytes, frame->len,
					  ZSOCK_MSG_DONTWAIT,
					  (struct net_sockaddr *)&dest, sizeof(dest));
	if (sent != (ssize_t)frame->len) {
		atomic_inc(&tx_errors);
	}
}

static void link_rx_one(void)
{
	uint8_t buffer[128];
	struct net_sockaddr_in6 source;
	net_socklen_t length = sizeof(source);

	const ssize_t received = zsock_recvfrom(sock_fd, buffer, sizeof(buffer),
						ZSOCK_MSG_DONTWAIT,
						(struct net_sockaddr *)&source, &length);
	if (received < 0) {
		return;
	}
	if (received != (ssize_t)PC_LINK_PACKET_BYTES || source.sin6_family != NET_AF_INET6) {
		atomic_inc(&rx_dropped);
		return;
	}

	for (unsigned i = 0; i < PC_LINK_ROLES; ++i) {
		if (i == local_role) {
			continue;
		}
		if (memcmp(source.sin6_addr.s6_addr, peer_address[i], 16) == 0) {
			if (rx_handler != NULL) {
				rx_handler((uint8_t)i, buffer, (size_t)received);
			}
			return;
		}
	}
	/* Datagram from an address that is not one of the five team EUI-64s. */
	atomic_inc(&rx_dropped);
}

static void radio_thread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	struct zsock_pollfd fds = {
		.fd = sock_fd,
		.events = ZSOCK_POLLIN,
		.revents = 0,
	};
	struct pc_link_frame frame;

	for (;;) {
		fds.revents = 0;
		const int polled = zsock_poll(&fds, 1, PC_LINK_POLL_MS);

		if (polled > 0 && (fds.revents & ZSOCK_POLLIN) != 0) {
			link_rx_one();
		}

		/* Drain queued datagrams; each wait is bounded by the poll timeout. */
		while (k_msgq_get(&pc_tx_queue, &frame, K_MSEC(PC_LINK_POLL_MS)) == 0) {
			link_tx_frame(&frame);
		}
	}
}
#endif /* CONFIG_OPENTHREAD */

int pc_link_start(uint8_t role, pc_link_rx_fn rx_cb)
{
	if (role >= PC_LINK_ROLES || link_started) {
		return -EINVAL;
	}

	local_role = role;
	rx_handler = rx_cb;
	link_started = true;

#if PC_TEAM_CONFIGURED
	/* Provisioned: the team file fixes the on-air identity. */
	memcpy(local_eui, team_eui64[role], sizeof(local_eui));
#else
	/*
	 * Unprovisioned: report the chip's factory identity so the owner can read
	 * it with the "eui" console command before provisioning. The provisioner
	 * writes these eight bytes back into team_eui64[role] in this same array
	 * order, so after provisioning otLinkSetExtendedAddress() sends
	 * byte-identical data; only the U/L bit flip of the IPv6 IID derivation
	 * is applied on top.
	 *
	 * VERIFY(hwinfo): CONFIG_HWINFO=y selects CONFIG_HWINFO_NRF on the
	 * nRF54L15 (depends on NRF_SOC_SECURE_SUPPORTED), and hwinfo_nrf.c
	 * handles NRF_FICR_HAS_INFO_DEVICE_ID in NCS v3.4.0. The API leaves the
	 * buffer unchanged past a short copy and returns a negative errno on
	 * failure; the pre-zero plus the explicit zero-pad below cover both.
	 */
	memset(local_eui, 0, sizeof(local_eui));

	const ssize_t id_length = hwinfo_get_device_id(local_eui, sizeof(local_eui));

	if (id_length > 0 && (size_t)id_length < sizeof(local_eui)) {
		memset(local_eui + id_length, 0, sizeof(local_eui) - (size_t)id_length);
	}

	/* No team credentials: report NO CONFIG, keep TX silently dropped. */
	return 0;
#endif

#if defined(CONFIG_OPENTHREAD)
	const int error = link_bring_up();

	if (error != 0) {
		link_error = true;
		return error;
	}

	/*
	 * Above the OpenThread thread and its radio workqueue (defaults 8 and 7
	 * in NCS v3.4.0), below the 802.15.4 driver RX thread (cooperative 2).
	 */
	k_thread_create(&radio_thread_data, radio_stack, K_THREAD_STACK_SIZEOF(radio_stack),
			radio_thread, NULL, NULL, NULL, K_PRIO_PREEMPT(4), 0, K_NO_WAIT);
	k_thread_name_set(&radio_thread_data, "pc_radio");
	return 0;
#else
	link_error = true;
	return -ENOTSUP;
#endif
}

bool pc_link_ready(void)
{
#if !PC_TEAM_CONFIGURED
	return false;
#elif defined(CONFIG_OPENTHREAD)
	if (ot_instance == NULL || link_error) {
		return false;
	}

	openthread_mutex_lock();
	const otDeviceRole role = otThreadGetDeviceRole(ot_instance);
	openthread_mutex_unlock();

	return role != OT_DEVICE_ROLE_DISABLED && role != OT_DEVICE_ROLE_DETACHED;
#else
	return false;
#endif
}

const char *pc_link_state(void)
{
	if (!PC_TEAM_CONFIGURED) {
		return "NO CONFIG";
	}
	if (link_error) {
		return "ERROR";
	}
	return pc_link_ready() ? "UP" : "ATTACHING";
}

bool pc_link_send(uint8_t target_role, const uint8_t *bytes, size_t len)
{
	if (target_role >= PC_LINK_ROLES || target_role == local_role || bytes == NULL ||
	    len != PC_LINK_PACKET_BYTES || !link_started || link_error) {
		atomic_inc(&tx_dropped);
		return false;
	}

#if !PC_TEAM_CONFIGURED
	/* No team credentials: drop silently. */
	atomic_inc(&tx_dropped);
	return false;
#elif defined(PC_LINK_TX_QUEUE_ENABLED)
	struct pc_link_frame frame;

	frame.target = target_role;
	frame.len = (uint8_t)len;
	memcpy(frame.bytes, bytes, len);

	if (k_msgq_put(&pc_tx_queue, &frame, K_NO_WAIT) != 0) {
		atomic_inc(&tx_dropped);
		return false;
	}
	return true;
#else
	/* Thread transport not built: drop. */
	atomic_inc(&tx_dropped);
	return false;
#endif
}

void pc_link_local_eui64(uint8_t out[8])
{
	if (out == NULL) {
		return;
	}
	memcpy(out, local_eui, 8);
}

uint32_t pc_link_tx_dropped(void)
{
	return (uint32_t)atomic_get(&tx_dropped);
}

uint32_t pc_link_rx_dropped(void)
{
	return (uint32_t)atomic_get(&rx_dropped);
}

uint32_t pc_link_tx_errors(void)
{
	return (uint32_t)atomic_get(&tx_errors);
}
