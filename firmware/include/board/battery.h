#pragma once
#include <cstdint>

namespace board {
// Internal VBAT sense: P1.14 (AIN7) behind the P1.15 load switch, scale x2.
class Battery {
 public:
  void begin();
  void tick(uint32_t now);
  uint32_t millivolts() const;
  bool low() const;          // 2800..3499 mV
  bool audioPower() const;   // 3100..4400 mV
 private:
  uint32_t millivolts_ = 0;
  uint32_t sampledAt_ = 0;
  bool sampled_ = false;
};
} // namespace board
