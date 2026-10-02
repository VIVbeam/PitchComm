/*
 * PitchComm - 128x32 SSD1306 OLED for the XIAO nRF54L15 (Zephyr / NCS).
 *
 * The panel is a generic 0.91" 128x32 module at address 0x3C on i2c22
 * (SDA = P1.10 / D4, SCL = P1.11 / D5), see docs/wiring.md.
 *
 * Primary backend: the in-tree Zephyr SSD1306 display driver
 * (compatible = "solomon,ssd1306", CONFIG_SSD1306). Fallback backend: raw
 * I2C page writes, used only if CONFIG_SSD1306 is not enabled.
 *
 * Rendering goes into a 512-byte page-major frame buffer (bit 0 of each byte
 * is the top row of its 8-pixel page, matching SCREEN_INFO_MONO_VTILED), then
 * the whole frame is pushed in one pass, which is what the proven V1
 * Adafruit_SSD1306 code did (clearDisplay / print / display).
 *
 * Timeouts: Zephyr's synchronous I2C and display APIs take no per-transfer
 * timeout argument. The full-frame transfer below is a bounded, single
 * transaction series: no retries and no bus recovery loops are performed
 * here, and the SSD1306 driver itself only issues direct i2c_write_dt()
 * calls (it also returns on the first error).
 *
 * Threading: one static mutex serializes begin/menu/strip/probe/wake/sleep
 * because AppHooks::present() can call strip() from the engine thread while
 * the main thread runs menu()/strip() in draw(). Public calls wait at most
 * 50 ms for the panel and report failure on timeout; the mutex is never
 * taken recursively.
 */

#include "board/display.h"

#if defined(CONFIG_PITCHCOMM_DISPLAY)

#if !defined(CONFIG_SSD1306) && !defined(CONFIG_I2C)
#error "PitchComm display: enable CONFIG_DISPLAY=y and CONFIG_SSD1306=y (or CONFIG_I2C=y for the raw fallback)."
#endif

#include <cstring>

#include <zephyr/device.h>
#include <zephyr/drivers/display.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

namespace board {
namespace {

constexpr uint16_t kWidth = 128;
constexpr uint16_t kHeight = 32;
constexpr uint16_t kFrameBytes = kWidth * kHeight / 8; /* 512 bytes */

constexpr uint8_t kGlyphColumns = 5;
constexpr uint8_t kGlyphRows = 7;
constexpr uint8_t kGlyphAdvance = 6;    /* 5x7 cell + 1 blank column, 1x text */
constexpr uint8_t kLabelAdvance = 12;   /* 2x text uses 12 px cells like V1 */
constexpr uint8_t kLabelAdvance11 = 11; /* 11-char labels use an 11 px advance */

/* The panel address is fixed by the overlay: ssd1306@3c. */
static_assert(DT_REG_ADDR(DT_NODELABEL(ssd1306)) == 0x3c,
              "PitchComm display must be the SSD1306 at I2C address 0x3C");

/*
 * 5x7 ASCII glyphs, one byte per column, bit 0 = top row (the classic
 * Adafruit GFX 5x7 layout). Data ported from the Adafruit GFX glcdfont.c
 * font (Copyright (c) 2012 Adafruit Industries, BSD license,
 * https://github.com/adafruit/Adafruit-GFX-Library/blob/master/license.txt).
 * Only the printable range 0x20..0x7E (95 glyphs) is kept here.
 */
const uint8_t kFont[95][kGlyphColumns] = {
  {0x00,0x00,0x00,0x00,0x00}, /* ' ' */
  {0x00,0x00,0x5f,0x00,0x00}, /* '!' */
  {0x00,0x07,0x00,0x07,0x00}, /* '"' */
  {0x14,0x7f,0x14,0x7f,0x14}, /* '#' */
  {0x24,0x2a,0x7f,0x2a,0x12}, /* '$' */
  {0x23,0x13,0x08,0x64,0x62}, /* '%' */
  {0x36,0x49,0x56,0x20,0x50}, /* '&' */
  {0x00,0x08,0x07,0x03,0x00}, /* '\'' */
  {0x00,0x1c,0x22,0x41,0x00}, /* '(' */
  {0x00,0x41,0x22,0x1c,0x00}, /* ')' */
  {0x2a,0x1c,0x7f,0x1c,0x2a}, /* '*' */
  {0x08,0x08,0x3e,0x08,0x08}, /* '+' */
  {0x00,0x80,0x70,0x30,0x00}, /* ',' */
  {0x08,0x08,0x08,0x08,0x08}, /* '-' */
  {0x00,0x00,0x60,0x60,0x00}, /* '.' */
  {0x20,0x10,0x08,0x04,0x02}, /* '/' */
  {0x3e,0x51,0x49,0x45,0x3e}, /* '0' */
  {0x00,0x42,0x7f,0x40,0x00}, /* '1' */
  {0x72,0x49,0x49,0x49,0x46}, /* '2' */
  {0x21,0x41,0x49,0x4d,0x33}, /* '3' */
  {0x18,0x14,0x12,0x7f,0x10}, /* '4' */
  {0x27,0x45,0x45,0x45,0x39}, /* '5' */
  {0x3c,0x4a,0x49,0x49,0x31}, /* '6' */
  {0x41,0x21,0x11,0x09,0x07}, /* '7' */
  {0x36,0x49,0x49,0x49,0x36}, /* '8' */
  {0x46,0x49,0x49,0x29,0x1e}, /* '9' */
  {0x00,0x00,0x14,0x00,0x00}, /* ':' */
  {0x00,0x40,0x34,0x00,0x00}, /* ';' */
  {0x00,0x08,0x14,0x22,0x41}, /* '<' */
  {0x14,0x14,0x14,0x14,0x14}, /* '=' */
  {0x00,0x41,0x22,0x14,0x08}, /* '>' */
  {0x02,0x01,0x59,0x09,0x06}, /* '?' */
  {0x3e,0x41,0x5d,0x59,0x4e}, /* '@' */
  {0x7c,0x12,0x11,0x12,0x7c}, /* 'A' */
  {0x7f,0x49,0x49,0x49,0x36}, /* 'B' */
  {0x3e,0x41,0x41,0x41,0x22}, /* 'C' */
  {0x7f,0x41,0x41,0x41,0x3e}, /* 'D' */
  {0x7f,0x49,0x49,0x49,0x41}, /* 'E' */
  {0x7f,0x09,0x09,0x09,0x01}, /* 'F' */
  {0x3e,0x41,0x41,0x51,0x73}, /* 'G' */
  {0x7f,0x08,0x08,0x08,0x7f}, /* 'H' */
  {0x00,0x41,0x7f,0x41,0x00}, /* 'I' */
  {0x20,0x40,0x41,0x3f,0x01}, /* 'J' */
  {0x7f,0x08,0x14,0x22,0x41}, /* 'K' */
  {0x7f,0x40,0x40,0x40,0x40}, /* 'L' */
  {0x7f,0x02,0x1c,0x02,0x7f}, /* 'M' */
  {0x7f,0x04,0x08,0x10,0x7f}, /* 'N' */
  {0x3e,0x41,0x41,0x41,0x3e}, /* 'O' */
  {0x7f,0x09,0x09,0x09,0x06}, /* 'P' */
  {0x3e,0x41,0x51,0x21,0x5e}, /* 'Q' */
  {0x7f,0x09,0x19,0x29,0x46}, /* 'R' */
  {0x26,0x49,0x49,0x49,0x32}, /* 'S' */
  {0x03,0x01,0x7f,0x01,0x03}, /* 'T' */
  {0x3f,0x40,0x40,0x40,0x3f}, /* 'U' */
  {0x1f,0x20,0x40,0x20,0x1f}, /* 'V' */
  {0x3f,0x40,0x38,0x40,0x3f}, /* 'W' */
  {0x63,0x14,0x08,0x14,0x63}, /* 'X' */
  {0x03,0x04,0x78,0x04,0x03}, /* 'Y' */
  {0x61,0x59,0x49,0x4d,0x43}, /* 'Z' */
  {0x00,0x7f,0x41,0x41,0x41}, /* '[' */
  {0x02,0x04,0x08,0x10,0x20}, /* '\\' */
  {0x00,0x41,0x41,0x41,0x7f}, /* ']' */
  {0x04,0x02,0x01,0x02,0x04}, /* '^' */
  {0x40,0x40,0x40,0x40,0x40}, /* '_' */
  {0x00,0x03,0x07,0x08,0x00}, /* '`' */
  {0x20,0x54,0x54,0x78,0x40}, /* 'a' */
  {0x7f,0x28,0x44,0x44,0x38}, /* 'b' */
  {0x38,0x44,0x44,0x44,0x28}, /* 'c' */
  {0x38,0x44,0x44,0x28,0x7f}, /* 'd' */
  {0x38,0x54,0x54,0x54,0x18}, /* 'e' */
  {0x00,0x08,0x7e,0x09,0x02}, /* 'f' */
  {0x18,0xa4,0xa4,0x9c,0x78}, /* 'g' */
  {0x7f,0x08,0x04,0x04,0x78}, /* 'h' */
  {0x00,0x44,0x7d,0x40,0x00}, /* 'i' */
  {0x20,0x40,0x40,0x3d,0x00}, /* 'j' */
  {0x7f,0x10,0x28,0x44,0x00}, /* 'k' */
  {0x00,0x41,0x7f,0x40,0x00}, /* 'l' */
  {0x7c,0x04,0x78,0x04,0x78}, /* 'm' */
  {0x7c,0x08,0x04,0x04,0x78}, /* 'n' */
  {0x38,0x44,0x44,0x44,0x38}, /* 'o' */
  {0xfc,0x18,0x24,0x24,0x18}, /* 'p' */
  {0x18,0x24,0x24,0x18,0xfc}, /* 'q' */
  {0x7c,0x08,0x04,0x04,0x08}, /* 'r' */
  {0x48,0x54,0x54,0x54,0x24}, /* 's' */
  {0x04,0x04,0x3f,0x44,0x24}, /* 't' */
  {0x3c,0x40,0x40,0x20,0x7c}, /* 'u' */
  {0x1c,0x20,0x40,0x20,0x1c}, /* 'v' */
  {0x3c,0x40,0x30,0x40,0x3c}, /* 'w' */
  {0x44,0x28,0x10,0x28,0x44}, /* 'x' */
  {0x4c,0x90,0x90,0x90,0x7c}, /* 'y' */
  {0x44,0x64,0x54,0x4c,0x44}, /* 'z' */
  {0x00,0x08,0x36,0x41,0x00}, /* '{' */
  {0x00,0x00,0x77,0x00,0x00}, /* '|' */
  {0x00,0x41,0x36,0x08,0x00}, /* '}' */
  {0x02,0x01,0x02,0x04,0x02}, /* '~' */
};

uint8_t gFrame[kFrameBytes];

inline void setPixel(uint16_t x, uint16_t y) {
  if (x >= kWidth || y >= kHeight) {
    return;
  }
  gFrame[(y / 8) * kWidth + x] |= static_cast<uint8_t>(1u << (y % 8));
}

void clearFrame() { std::memset(gFrame, 0, sizeof(gFrame)); }

void drawGlyph(uint16_t x, uint16_t y, char c, uint8_t scale) {
  if (c < 0x20 || c > 0x7e) {
    c = '?';
  }
  const uint8_t* glyph = kFont[static_cast<uint8_t>(c) - 0x20];
  for (uint8_t column = 0; column < kGlyphColumns; ++column) {
    const uint8_t bits = glyph[column];
    for (uint8_t row = 0; row < kGlyphRows; ++row) {
      if ((bits & (1u << row)) == 0) {
        continue;
      }
      if (scale == 2) {
        const uint16_t px = x + column * 2;
        const uint16_t py = y + row * 2;
        setPixel(px, py);
        setPixel(px + 1, py);
        setPixel(px, py + 1);
        setPixel(px + 1, py + 1);
      } else {
        setPixel(x + column, y + row);
      }
    }
  }
}

void drawText(uint16_t x, uint16_t y, const char* text, uint8_t scale,
              uint8_t advance) {
  if (text == nullptr) {
    return;
  }
  const uint16_t glyphWidth = (scale == 2) ? kGlyphColumns * 2 : kGlyphColumns;
  for (; *text != '\0'; ++text) {
    if (x + glyphWidth > kWidth) {
      break; /* clip at the right edge; callers keep the text in range */
    }
    drawGlyph(x, y, *text, scale);
    x += advance;
  }
}

const struct i2c_dt_spec gPanelI2c = I2C_DT_SPEC_GET(DT_NODELABEL(ssd1306));

/*
 * Serializes all panel traffic and the shared frame buffer between the main
 * UI thread and the engine thread (AppHooks::present() can call strip()).
 * One full frame is about 13 ms of bus time at the configured 400 kHz, so a
 * 50 ms wait is enough for the current holder to finish.
 */
K_MUTEX_DEFINE(gLock);

/* RAII helper so every early return releases the panel mutex. */
struct Guard {
  explicit Guard(k_timeout_t timeout)
      : held(k_mutex_lock(&gLock, timeout) == 0) {}
  ~Guard() {
    if (held) {
      k_mutex_unlock(&gLock);
    }
  }
  bool held;
};

/*
 * One-byte bus probe: SSD1306 panels are write-only on I2C. A one-byte write
 * of the command-stream control byte (Co = 0, D/C# = 0) is ACKed by a present
 * panel and NACKed when it is absent or unpowered. The address argument lets
 * the console `scan` diagnostic walk other addresses on the same bus.
 * Callers hold gLock; probeBus itself never takes it.
 */
bool probeBus(uint8_t address) {
  struct i2c_dt_spec spec = gPanelI2c;
  spec.addr = address;
  uint8_t control = 0x00;
  return i2c_write_dt(&spec, &control, 1) == 0;
}

#if defined(CONFIG_SSD1306)

const struct device* const gPanel = DEVICE_DT_GET(DT_NODELABEL(ssd1306));

bool panelOn() { return display_blanking_off(gPanel) == 0; }
bool panelOff() { return display_blanking_on(gPanel) == 0; }

bool flush() {
  struct display_buffer_descriptor desc{};
  desc.buf_size = sizeof(gFrame);
  desc.width = kWidth;
  desc.height = kHeight;
  desc.pitch = kWidth; /* the SSD1306 driver requires pitch == width */
  desc.frame_incomplete = false;
  /* The driver requires y and height to be page-aligned; a full frame is. */
  return display_write(gPanel, 0, 0, &desc, gFrame) == 0;
}

#else /* Raw SSD1306 I2C fallback, only if the in-tree driver is unavailable. */

/* Standard SSD1306 128x32 power-up sequence; values follow the datasheet and
 * the settings requested in the overlay (segment remap, reversed COM scan,
 * sequential COM pins, precharge 0xF1). */
bool rawInit() {
  static const uint8_t kInit[] = {
      0xae,             /* display off while configuring */
      0xd5, 0x80,       /* clock divide ratio / oscillator frequency */
      0xa8, 0x1f,       /* multiplex ratio: 32 rows */
      0xd3, 0x00,       /* display offset 0 */
      0x40,             /* display start line 0 */
      0x8d, 0x14,       /* charge pump enabled */
      0x20, 0x02,       /* page addressing mode */
      0xa1,             /* segment remap */
      0xc8,             /* COM output scan direction reversed */
      0xda, 0x02,       /* COM pins: sequential, no left/right remap */
      0x81, 0x8f,       /* contrast */
      0xd9, 0xf1,       /* pre-charge period */
      0xdb, 0x40,       /* VCOMH deselect level */
      0xa4,             /* display follows GDDRAM */
      0xa6,             /* normal (not inverted) display */
      0xaf,             /* display on */
  };
  uint8_t buffer[1 + sizeof(kInit)];
  buffer[0] = 0x00; /* Co = 0, D/C# = 0: all following bytes are commands */
  std::memcpy(&buffer[1], kInit, sizeof(kInit));
  return i2c_write_dt(&gPanelI2c, buffer, sizeof(buffer)) == 0;
}

bool rawFlush() {
  uint8_t data[1 + kWidth];
  data[0] = 0x40; /* Co = 0, D/C# = 1: all following bytes are GDDRAM data */
  for (uint8_t page = 0; page < kHeight / 8; ++page) {
    const uint8_t position[4] = {
        0x00, static_cast<uint8_t>(0xb0 | page), 0x00, 0x10};
    if (i2c_write_dt(&gPanelI2c, position, sizeof(position)) != 0) {
      return false;
    }
    std::memcpy(&data[1], &gFrame[page * kWidth], kWidth);
    if (i2c_write_dt(&gPanelI2c, data, sizeof(data)) != 0) {
      return false;
    }
  }
  return true;
}

bool panelOn() {
  const uint8_t command[2] = {0x00, 0xaf}; /* display on */
  return i2c_write_dt(&gPanelI2c, command, sizeof(command)) == 0;
}

bool panelOff() {
  const uint8_t command[2] = {0x00, 0xae}; /* display off */
  return i2c_write_dt(&gPanelI2c, command, sizeof(command)) == 0;
}

bool flush() { return rawFlush(); }

#endif /* CONFIG_SSD1306 */

}  // namespace

bool Display::begin() {
  const Guard lock(K_MSEC(50));
  if (!lock.held) {
    return false;
  }
  if (ready_) {
    return true;
  }
  if (!probeBus(gPanelI2c.addr)) {
    return false;
  }
#if defined(CONFIG_SSD1306)
  if (!device_is_ready(gPanel)) {
    return false;
  }
  struct display_capabilities caps{};
  display_get_capabilities(gPanel, &caps);
  if (caps.x_resolution != kWidth || caps.y_resolution != kHeight) {
    return false; /* the overlay must describe the 128x32 panel */
  }
#else
  if (!rawInit()) {
    return false;
  }
#endif
  clearFrame();
  if (!flush()) {
    return false;
  }
  sleeping_ = false;
  ready_ = true;
  return true;
}

bool Display::probe(uint8_t address) {
  /* Works whether or not begin() has run: a disconnected panel must fail. */
  const Guard lock(K_MSEC(50));
  if (!lock.held) {
    return false; /* a transfer is in flight; report not found */
  }
  return probeBus(address);
}

bool Display::available() const {
  const Guard lock(K_MSEC(50));
  if (!lock.held) {
    return false; /* a display update is in flight; report unavailable */
  }
  return ready_;
}

void Display::wake() {
  const Guard lock(K_MSEC(50));
  if (!lock.held || !ready_) {
    return;
  }
  panelOn();
  sleeping_ = false;
}

void Display::sleep() {
  const Guard lock(K_MSEC(50));
  if (!lock.held || !ready_ || sleeping_) {
    return;
  }
  panelOff();
  sleeping_ = true;
}

bool Display::sleeping() const {
  const Guard lock(K_MSEC(50));
  if (!lock.held) {
    return false;
  }
  return sleeping_;
}

bool Display::menu(const pc::CatcherMenu::Frame& frame) {
  const Guard lock(K_MSEC(50));
  if (!lock.held || !ready_ || sleeping_) {
    return false;
  }
  clearFrame();
  drawText(0, 0, frame.header, 1, kGlyphAdvance);
  drawText(0, 8, frame.rows[0], 1, kGlyphAdvance);
  drawText(0, 16, frame.rows[1], 1, kGlyphAdvance);
  drawText(0, 24, frame.footer, 1, kGlyphAdvance);
  return flush();
}

bool Display::strip(const char* label, const char* status) {
  const Guard lock(K_MSEC(50));
  if (!lock.held || !ready_ || sleeping_ || label == nullptr ||
      status == nullptr) {
    return false;
  }
  const size_t labelLength = std::strlen(label);
  /* V1 rejected oversized caller text instead of silently clipping a call
   * or hiding its safety status. */
  if (labelLength > 11 || std::strlen(status) > 10) {
    return false;
  }
  clearFrame();
  if (labelLength == 11) {
    /* SHADE RIGHT needs eleven unchanged 2x glyphs. Keep the glyphs and
     * reduce only the blank inter-character advance from 12 to 11 px. */
    uint16_t x = 0;
    for (const char* p = label; *p != '\0'; ++p) {
      drawGlyph(x, 0, *p, 2);
      x += kLabelAdvance11;
    }
  } else {
    drawText(0, 0, label, 2, kLabelAdvance);
  }
  drawText(0, 16, status, 1, kGlyphAdvance);
  return flush();
}

} // namespace board

#endif /* CONFIG_PITCHCOMM_DISPLAY */
