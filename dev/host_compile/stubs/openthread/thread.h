/*
 * HOST STUB: openthread/thread.h
 *
 * Declaration-only stand-in for -fsyntax-only checks.
 */
#pragma once

#include <stdbool.h>

#include <openthread/instance.h>

typedef enum {
	OT_DEVICE_ROLE_DISABLED = 0,
	OT_DEVICE_ROLE_DETACHED = 1,
	OT_DEVICE_ROLE_CHILD = 2,
	OT_DEVICE_ROLE_ROUTER = 3,
	OT_DEVICE_ROLE_LEADER = 4,
} otDeviceRole;

otDeviceRole otThreadGetDeviceRole(otInstance *aInstance);
otError otThreadSetEnabled(otInstance *aInstance, bool aEnabled);
bool otThreadGetLinkModeFullThreadDevice(void);
