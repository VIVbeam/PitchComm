#pragma once
#include "pc/newcatcher_menu.h"

namespace board {
// SSD1306 over the default I2C bus (D4/D5): 128x32 on the catcher, 128x64 on
// a display64 fielder watch. The board overlay selects the geometry.
class Display {
 public:
  bool begin();
  bool available() const;
  void wake();
  void sleep();
  bool sleeping() const;
  // Catcher menu: four text rows of the ported catcher model.
  bool menu(const pc::CatcherMenu::Frame& frame);
  // Fielder strip: one large label plus one status word.
  bool strip(const char* label, const char* status);
  // Probe one address on the display I2C bus (console `scan` diagnostic).
  static bool probe(uint8_t address);
 private:
  bool ready_ = false;
  bool sleeping_ = false;
};
} // namespace board
