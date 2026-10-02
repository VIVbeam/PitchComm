/*
 * HOST STUB: openthread/link.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include <openthread/instance.h>

typedef struct {
	uint8_t m8[8];
} otExtAddress;

typedef struct {
	bool mRxOnWhenIdle : 1;
	bool mReserved : 1;
	bool mFullThreadDevice : 1;
	bool mFullNetworkData : 1;
} otLinkModeConfig;

otError otLinkSetExtendedAddress(otInstance *aInstance,
				 const otExtAddress *aExtAddress);
otLinkModeConfig otThreadGetLinkMode(otInstance *aInstance);
otError otThreadSetLinkMode(otInstance *aInstance, otLinkModeConfig aConfig);
otError otLinkSetPollPeriod(otInstance *aInstance, uint32_t aPollPeriod);
uint32_t otLinkGetPollPeriod(otInstance *aInstance);
