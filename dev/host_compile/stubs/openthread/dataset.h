/*
 * HOST STUB: openthread/dataset.h
 *
 * Declaration-only stand-in for -fsyntax-only checks. Only the members
 * thread_link.c addresses are present.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include <openthread/instance.h>

typedef struct {
	uint8_t m8[16];
} otNetworkKey;

typedef struct {
	uint8_t m8[8];
} otExtendedPanId;

typedef struct {
	uint8_t m8[8];
} otMeshLocalPrefix;

typedef struct {
	char m8[17];
} otNetworkName;

typedef struct {
	uint16_t mRotationTime;
	bool mObtainNetworkKeyEnabled : 1;
	bool mNativeCommissioningEnabled : 1;
	bool mRoutersEnabled : 1;
	bool mExternalCommissioningEnabled : 1;
	bool mCommercialCommissioningEnabled : 1;
	bool mAutonomousEnrollmentEnabled : 1;
	bool mNetworkKeyProvisioningEnabled : 1;
	bool mTobleLinkEnabled : 1;
	bool mNonCcmRoutersEnabled : 1;
	bool mVersionThresholdForDua : 1;
} otSecurityPolicy;

typedef struct {
	bool mIsActiveTimestampPresent : 1;
	bool mIsPendingTimestampPresent : 1;
	bool mIsNetworkKeyPresent : 1;
	bool mIsNetworkNamePresent : 1;
	bool mIsExtendedPanIdPresent : 1;
	bool mIsMeshLocalPrefixPresent : 1;
	bool mIsDelayPresent : 1;
	bool mIsPanIdPresent : 1;
	bool mIsChannelPresent : 1;
	bool mIsPskcPresent : 1;
	bool mIsSecurityPolicyPresent : 1;
	bool mIsChannelMaskPresent : 1;
} otOperationalDatasetComponents;

typedef struct {
	uint64_t mActiveTimestamp;
	uint64_t mPendingTimestamp;
	otNetworkKey mNetworkKey;
	otNetworkName mNetworkName;
	otExtendedPanId mExtendedPanId;
	otMeshLocalPrefix mMeshLocalPrefix;
	uint32_t mDelay;
	uint16_t mPanId;
	uint16_t mChannel;
	otSecurityPolicy mSecurityPolicy;
	otOperationalDatasetComponents mComponents;
} otOperationalDataset;

otError otDatasetSetActive(otInstance *aInstance,
			   const otOperationalDataset *aDataset);
otError otDatasetGetActive(otInstance *aInstance,
			   otOperationalDataset *aDataset);
