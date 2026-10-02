/*
 * HOST STUB: zephyr/net/socket.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Only the non-POSIX
 * zsock_* names used by thread_link.c are declared.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

typedef uint32_t net_socklen_t;

struct net_sockaddr {
	uint8_t sa_family;
	char sa_data[14];
};

struct net_in6_addr {
	uint8_t s6_addr[16];
};

struct net_sockaddr_in6 {
	uint8_t sin6_family;
	uint16_t sin6_port;
	uint32_t sin6_flowinfo;
	struct net_in6_addr sin6_addr;
	uint32_t sin6_scope_id;
};

struct zsock_pollfd {
	int fd;
	short events;
	short revents;
};

#define NET_AF_INET6 10
#define NET_SOCK_DGRAM 2
#define NET_SOCK_STREAM 1
#define NET_IPPROTO_UDP 17
#define NET_IPPROTO_IPV6 41
#define ZSOCK_IPV6_V6ONLY 26
#define ZSOCK_MSG_DONTWAIT 0x40
#define ZSOCK_POLLIN 0x0001
#define ZSOCK_POLLOUT 0x0004
#define ZSOCK_POLLERR 0x0008

int zsock_socket(int family, int type, int proto);
int zsock_setsockopt(int sock, int level, int optname, const void *optval,
		     net_socklen_t optlen);
int zsock_bind(int sock, const struct net_sockaddr *addr,
	       net_socklen_t addrlen);
int zsock_close(int sock);
ssize_t zsock_sendto(int sock, const void *buf, size_t len, int flags,
		     const struct net_sockaddr *dest,
		     net_socklen_t addrlen);
ssize_t zsock_recvfrom(int sock, void *buf, size_t len, int flags,
		       struct net_sockaddr *src, net_socklen_t *addrlen);
int zsock_poll(struct zsock_pollfd *fds, int nfds, int timeout);
