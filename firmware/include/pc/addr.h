#pragma once
#include <stdint.h>
// Plain C on purpose: this header is included by the Zephyr radio link (C) and
// by the host tests (C++), so it must not use namespaces or C++ constructs.
//
// Link-local IPv6 address of an 802.15.4 EUI-64: fe80::/64 plus the EUI-64
// with the universal/local bit of its first byte flipped. This is exactly how
// OpenThread derives the link-local address from an extended address
// (otIp6AddressFromExtAddr), so it also matches peers provisioned by EUI-64.
static inline void pc_link_local_from_eui(const uint8_t eui[8], uint8_t out[16]) {
  out[0]=0xfe; out[1]=0x80;
  for (unsigned i=2;i<8;++i) out[i]=0;
  out[8]=(uint8_t)(eui[0]^0x02u);
  for (unsigned i=1;i<8;++i) out[8+i]=eui[i];
}
