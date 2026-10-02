// Variant-roster probe for dev/host_compile/run.ps1 -RosterVariant.
//
// The harness renders the catalog for dev/host_compile/roster-variant.json with
// tools/generate_catalog.py into a temporary include overlay, so "pc/catalog.h"
// here is that variant and not the committed one. Every static_assert pins a
// value that only holds for the variant: coach plus six enrolled units (the
// default four plus right and the custom key bench), center switched to audio,
// and the committed config/calls.json unchanged.
#include "pc/engine.h"

using pc::Category;

constexpr uint16_t kCoachBit = pc::kUnitMask(pc::kCoach);
constexpr uint16_t kPitcherBit = pc::kUnitMask(PC_UNIT_pitcher);
constexpr uint16_t kCatcherBit = pc::kUnitMask(PC_UNIT_catcher);
constexpr uint16_t kShortstopBit = pc::kUnitMask(PC_UNIT_shortstop);
constexpr uint16_t kCenterBit = pc::kUnitMask(PC_UNIT_center);
constexpr uint16_t kRightBit = pc::kUnitMask(PC_UNIT_right);
constexpr uint16_t kBenchBit = pc::kUnitMask(PC_UNIT_bench);

constexpr bool textEqual(const char* a, const char* b) {
  while (*a != '\0' && *a == *b) {
    ++a;
    ++b;
  }
  return *a == *b;
}

// Count the audio-capable units inside one resolved audience mask.
constexpr unsigned audioUnitsIn(uint16_t audience) {
  unsigned count = 0;
  for (unsigned unit = 0; unit < pc::kUnitCount; ++unit) {
    if ((audience & pc::kUnitMask(unit)) != 0 && pc::kUnitAudio[unit]) ++count;
  }
  return count;
}

// Every pitch call shares one audience: the enrolled units with `pitches`.
constexpr bool everyPitchReaches(uint16_t expected) {
  for (unsigned type = 1; type <= pc::kPitchCount; ++type) {
    for (unsigned row = 1; row <= pc::kRows; ++row) {
      for (unsigned col = 1; col <= pc::kCols; ++col) {
        if (pc::recipients(Category::Pitch, pc::pitchCode(type, row, col)) != expected) return false;
      }
    }
  }
  return true;
}

// The engine arrays are sized from kUnitCount, so a six-unit roster must give
// them seven entries (coach plus six).
constexpr bool engineArraysMatchRoster() {
  pc::CallRecord record{};
  return sizeof(record.delivery) / sizeof(record.delivery[0]) == pc::kUnitCount &&
         sizeof(record.boots) / sizeof(record.boots[0]) == pc::kUnitCount;
}

// --- roster shape -----------------------------------------------------------

static_assert(pc::kUnitCount == 7, "coach plus six enrolled units");
static_assert(PC_UNIT_pitcher == 1 && PC_UNIT_catcher == 2 && PC_UNIT_shortstop == 3 &&
                  PC_UNIT_center == 4 && PC_UNIT_right == 5 && PC_UNIT_bench == 6,
              "enrolled order is pitcher, catcher, shortstop, center, right, bench");
static_assert(PC_UNIT_first == 0 && PC_UNIT_second == 0 && PC_UNIT_third == 0 && PC_UNIT_left == 0,
              "non-enrolled standard keys keep mapping to the coach");
static_assert(kCoachBit == 1 && kBenchBit == 64 && kRightBit == 32 && kCenterBit == 16,
              "one bit per generated unit index");
static_assert(pc::roleMask(PC_UNIT_bench) == kBenchBit, "roleMask tracks the custom unit");

// --- the custom unit and the changed center capability ----------------------

static_assert(textEqual(pc::kUnitLabel[PC_UNIT_bench], "Bench"), "custom unit label");
static_assert(textEqual(pc::kUnitShort[PC_UNIT_bench], "BN"), "custom unit short label");
static_assert(pc::kUnitAudio[PC_UNIT_bench] == false &&
                  pc::kUnitDisplay[PC_UNIT_bench] == true &&
                  pc::kUnitControls[PC_UNIT_bench] == false &&
                  pc::kUnitPitches[PC_UNIT_bench] == true,
              "custom unit capability arrays");
static_assert(pc::displayRole(PC_UNIT_bench) && !pc::audioRole(PC_UNIT_bench) &&
                  !pc::controlsRole(PC_UNIT_bench),
              "capability helpers read the custom unit");
static_assert(pc::kUnitAudio[PC_UNIT_center] && pc::kUnitAudio[PC_UNIT_right],
              "center switched to audio and right enrolled with audio");

// --- audiences and clip paths ----------------------------------------------

static_assert(everyPitchReaches(kPitcherBit | kCatcherBit | kBenchBit),
              "pitch calls reach pitcher, catcher and the custom bench unit");
static_assert(pc::recipients(Category::Play, 1) == (kPitcherBit | kCatcherBit | kShortstopBit),
              "battery+infield still holds only the enrolled infielder");
static_assert(pc::recipients(Category::Play, 13) ==
                  (kPitcherBit | kCatcherBit | kShortstopBit | kCenterBit | kRightBit),
              "all now reaches the newly enrolled right fielder");
static_assert((pc::recipients(Category::Play, 13) & kRightBit) != 0,
              "an added unit is in a resolved audience");
static_assert((pc::recipients(Category::Play, 13) & kBenchBit) == 0,
              "custom keys are not part of the all group");
static_assert(pc::recipients(Category::Play, 18) == (kCenterBit | kRightBit),
              "outfield changed from center only to center plus right");
static_assert(audioUnitsIn(pc::recipients(Category::Play, 18)) == 2,
              "the outfield play now reaches two audio units");

// The two-audio outfield play must resolve with its clip path filled.
constexpr bool seeDownCarriesClip() {
  const pc::Call* call = pc::findCall(Category::Play, 18);
  return call != nullptr && call->category == Category::Play && call->code == 18 &&
         textEqual(call->audio[0], "/audio/d18.wav") &&
         call->audio[1][0] == '\0' && call->audio[2][0] == '\0';
}
static_assert(seeDownCarriesClip(), "SEE DOWN resolves with the two-audio clip path");

// --- engine bounds ----------------------------------------------------------

static_assert(engineArraysMatchRoster(), "engine arrays size to the expanded roster");
static_assert(pc::validRole(pc::Role(6)) && !pc::validRole(pc::Role(7)),
              "role validation follows kUnitCount");

int main() { return 0; }
