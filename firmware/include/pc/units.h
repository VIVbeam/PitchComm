#pragma once
// Unit model over the generated catalog: unit 0 is the coach and each enrolled
// roster key maps to a generated index. Capability helpers read the generated
// arrays, so the engine and the app never hardcode the five-role layout.
#include "catalog.h"
#include "protocol.h"

namespace pc {
using Role = uint8_t;
constexpr Role kCoach = 0;

// One selector per standard roster key. A key that is not enrolled maps to 0
// in catalog.h; field builds reject that through their static asserts.
constexpr Role kUnitPitcher = PC_UNIT_pitcher;
constexpr Role kUnitCatcher = PC_UNIT_catcher;
constexpr Role kUnitFirst = PC_UNIT_first;
constexpr Role kUnitSecond = PC_UNIT_second;
constexpr Role kUnitThird = PC_UNIT_third;
constexpr Role kUnitShortstop = PC_UNIT_shortstop;
constexpr Role kUnitLeft = PC_UNIT_left;
constexpr Role kUnitCenter = PC_UNIT_center;
constexpr Role kUnitRight = PC_UNIT_right;

constexpr bool validRole(Role r) { return uint8_t(r) < kUnitCount; }
constexpr uint16_t roleMask(Role r) {
  return validRole(r) ? kUnitMask(uint8_t(r)) : uint16_t(0);
}
inline const char* roleName(Role r) {
  return validRole(r) ? kUnitLabel[uint8_t(r)] : "UNKNOWN";
}
constexpr bool audioRole(Role r) { return validRole(r) && kUnitAudio[uint8_t(r)]; }
constexpr bool displayRole(Role r) { return validRole(r) && kUnitDisplay[uint8_t(r)]; }
constexpr bool controlsRole(Role r) { return validRole(r) && kUnitControls[uint8_t(r)]; }
} // namespace pc
