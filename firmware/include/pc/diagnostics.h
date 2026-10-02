#pragma once
#include <cstdint>

namespace pc {
// One I2C transaction per loop: a disconnected bus must not turn a diagnostic
// command into 126 consecutive timeouts that starve audio and call handling.
class I2cScan {
 public:
  bool active() const { return next_!=0; }
  bool start() {
    if (active()) return false;
    next_=1; return true;
  }
  template<class Probe> uint8_t tick(Probe probe) {
    if (!active()) return 0;
    const uint8_t address=next_;
    next_=address==126 ? 0 : uint8_t(address+1);
    return probe(address) ? address : 0;
  }
 private:
  uint8_t next_=0;
};
} // namespace pc
