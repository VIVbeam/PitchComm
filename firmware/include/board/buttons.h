#pragma once
#include <cstdint>

namespace board {
// One active-low button to ground with 30 ms debounce and a 700 ms long press.
struct Button {
  enum class Event { None, Press, LongPress };
  void begin();
  Event tick(uint32_t now);
};

// Catcher keypad: four numbered buttons plus the side Back button.
// tick() returns 1..4 on a numbered release, 6 on the Back long hold, else 0.
class CatcherControls {
 public:
  bool begin();
  bool available() const;
  unsigned tick(uint32_t now);
 private:
  bool present_ = false;
};
} // namespace board
