// Consume the shared coach protocol fixtures with the real firmware parsers.
// The GUI emits dev/protocol/gui_commands.txt from gui/core.js; this test
// proves the firmware side accepts every record, so the two cannot drift.
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>

#include "pc/catalog.h"
#include "pc/controls.h"
#include "pc/protocol.h"
#include "pc/units.h"

static int g_failures = 0;
static int g_checks = 0;

#define CHECK(condition)                                                       \
  do {                                                                         \
    ++g_checks;                                                                \
    if (!(condition)) {                                                        \
      ++g_failures;                                                            \
      std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition);         \
    }                                                                          \
  } while (0)

static bool readLine(std::ifstream& in, std::string& line) {
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty() || line[0] == '#') continue;
    return true;
  }
  return false;
}

// Every "key":[ ... ] array in the frame must hold exactly want non-negative
// decimal entries. The state frames carry links, delivery and two record
// delivery arrays, all sized to the generated unit count.
static bool arraysSized(const std::string& line, const std::string& key, int want) {
  const std::string needle = "\"" + key + "\":[";
  size_t at = 0;
  int seen = 0;
  while ((at = line.find(needle, at)) != std::string::npos) {
    ++seen;
    size_t cursor = at + needle.size();
    int entries = 0;
    bool inNumber = false;
    bool closed = false;
    for (; cursor < line.size(); ++cursor) {
      const char ch = line[cursor];
      if (ch == ']') { closed = true; break; }
      if (ch >= '0' && ch <= '9') {
        if (!inNumber) ++entries;
        inNumber = true;
      } else if (ch == ',' || ch == ' ') {
        inNumber = false;
      } else {
        return false;
      }
    }
    if (!closed || entries != want) return false;
    at = cursor + 1;
  }
  return seen > 0;
}

static int checkCommands(const char* path) {
  std::ifstream in(path);
  if (!in) {
    std::printf("cannot open %s\n", path);
    return 2;
  }

  constexpr uint32_t kClient = 0x1a2b3c4d;
  constexpr uint64_t kBoot = 0x0011223344556677ULL;
  constexpr unsigned kPitchCodes = pc::kPitchCount * pc::kRows * pc::kCols;
  int handshake = 0, calls = 0;
  uint32_t previousId = 0;
  std::string line;

  while (readLine(in, line)) {
    if (line.rfind("gui ", 0) == 0) {
      uint32_t client = 0;
      CHECK(pc::parseGuiClient(line.c_str(), client));
      CHECK(client == kClient);
      ++handshake;
      continue;
    }
    CHECK(line.rfind("call ", 0) == 0);
    if (line.rfind("call ", 0) != 0) continue;

    pc::UsbCall call;
    const bool parsed = pc::parseUsbCall(line.c_str(), call);
    CHECK(parsed);
    if (!parsed) {
      std::printf("FAIL parse: %s\n", line.c_str());
      continue;
    }
    ++calls;
    CHECK(call.client == kClient);
    CHECK(call.id != 0);
    CHECK(call.boot == kBoot);
    CHECK(call.dictionary == pc::kDictionary);
    if (call.category == pc::Category::Pitch) {
      CHECK(call.code >= 1 && call.code <= kPitchCodes);
      CHECK(pc::findCall(call.category, call.code) != nullptr);
    } else {
      CHECK(call.code >= 1 && call.code <= pc::kPlayCount);
      CHECK(pc::findCall(call.category, call.code) != nullptr);
    }
    if (previousId) CHECK(call.id > previousId);
    previousId = call.id;
  }

  CHECK(handshake == 1);
  CHECK(calls >= 13);
  return 0;
}

static int checkStateFrames(const char* path) {
  std::ifstream in(path);
  if (!in) {
    std::printf("cannot open %s\n", path);
    return 2;
  }
  char dictionary[9];
  std::snprintf(dictionary, sizeof(dictionary), "%08x", pc::kDictionary);
  int frames = 0;
  std::string line;
  while (readLine(in, line)) {
    const bool isFrame = line.rfind("@PC ", 0) == 0 && line.back() == '}';
    CHECK(isFrame);
    int depth = 0;
    bool balanced = true;
    for (const char ch : line) {
      if (ch == '{') ++depth;
      if (ch == '}') { if (depth == 0) balanced = false; else --depth; }
    }
    CHECK(balanced && depth == 0);
    if (line.find("\"type\":\"state\"") != std::string::npos) {
      CHECK(line.find(std::string("\"dictionary\":\"") + dictionary + "\"") != std::string::npos);
      CHECK(arraysSized(line, "links", int(pc::kUnitCount)));
      CHECK(arraysSized(line, "delivery", int(pc::kUnitCount)));
    }
    ++frames;
  }
  CHECK(frames >= 12);
  return 0;
}

int main(int argc, char** argv) {
  const char* commands = argc > 1 ? argv[1] : "dev/protocol/gui_commands.txt";
  if (checkCommands(commands) != 0) return 2;
  if (argc > 2) {
    if (checkStateFrames(argv[2]) != 0) return 2;
  }
  std::printf("protocol fixtures: %d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
