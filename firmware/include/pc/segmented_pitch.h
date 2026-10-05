#pragma once
#include "catalog.h"

namespace pc {
// Placement carries its pitch identity while playing only the location clip.
// A new dictionary separates this wire vocabulary from older firmware.
constexpr uint16_t kFullPitchCodes = kPitchCount*kRows*kCols;
constexpr uint16_t kPitchTypeBase = kFullPitchCodes;
constexpr uint16_t kPlacementBase = kPitchTypeBase+kPitchCount;
constexpr uint16_t kMaxPitchCode = kPlacementBase+kFullPitchCodes;
constexpr uint16_t pitchTypeCode(unsigned pitch) {
  return pitch>=1 && pitch<=kPitchCount ? uint16_t(kPitchTypeBase+pitch) : 0;
}
constexpr uint16_t placementCode(unsigned pitch,unsigned row,unsigned col) {
  return pitchCode(pitch,row,col) ? uint16_t(kPlacementBase+pitchCode(pitch,row,col)) : 0;
}
constexpr bool isPitchType(uint16_t code) { return code>kPitchTypeBase && code<=kPlacementBase; }
constexpr bool isPlacement(uint16_t code) { return code>kPlacementBase && code<=kMaxPitchCode; }
constexpr unsigned segmentedPitch(uint16_t code) {
  return isPitchType(code) ? code-kPitchTypeBase : isPlacement(code) ? (code-kPlacementBase-1)/(kRows*kCols)+1 : 0;
}
constexpr uint32_t kPitchDecisionWindow = 120000;
}
