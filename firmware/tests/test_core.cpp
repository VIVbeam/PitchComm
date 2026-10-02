// Host-side verification of the portable PitchComm core (firmware/include/pc).
// Build and run: tools/run_host_tests.ps1 (uses g++ or clang++).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "pc/controls.h"
#include "pc/display_strip.h"
#include "pc/engine.h"
#include "pc/newcatcher_menu.h"
#include "pc/protocol.h"
#include "pc/usb.h"

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

namespace {

struct Wire {
  pc::Packet packet{};
  uint32_t deliverAt = 0;
  bool alive = false;
};

// A shared simulated radio. Every send is encoded to the wire and decoded on
// delivery, so the tests exercise the real 56-byte format.
class Bus {
 public:
  Wire* post(const pc::Packet& p, uint32_t now, uint32_t delay = 0) {
    const size_t slot = wire_.size();
    wire_.push_back(Wire{});
    wire_[slot].packet = p;
    wire_[slot].deliverAt = now + delay;
    wire_[slot].alive = true;
    return &wire_[slot];
  }
  size_t pending() const {
    size_t n = 0;
    for (const auto& w : wire_) n += w.alive ? 1 : 0;
    return n;
  }
  template <class Deliver>
  void pump(uint32_t now, Deliver deliver) {
    for (auto& w : wire_) {
      if (!w.alive || w.deliverAt > now) continue;
      w.alive = false;
      uint8_t bytes[pc::kPacketBytes];
      pc::encode(w.packet, bytes);
      pc::Packet decoded;
      if (!pc::decode(bytes, sizeof(bytes), decoded)) continue;
      deliver(decoded, w.deliverAt);
    }
  }

 private:
  std::vector<Wire> wire_;
};

struct EngineUnderTest {
  struct Hooks : pc::Hooks {
    EngineUnderTest* owner = nullptr;
    bool send(const pc::Packet& p) override {
      if (!owner) return false;
      owner->lastSentAt = p.clock;
      owner->lastSent = p;
      owner->sends++;
      owner->log.push_back(p);
      owner->bus->post(p, p.clock);
      return true;
    }
    bool present(const pc::Output& out) override {
      if (!owner) return false;
      owner->presents++;
      owner->last = out;
      return owner->presentResult;
    }
    void clearOutput() override {
      if (owner) owner->clears++;
    }
  };

  // hooks and bus are declared before engine: the engine constructor calls
  // clearOutput() while the wrapper is still being constructed.
  Hooks hooks;
  Bus* bus = nullptr;
  pc::Engine engine;
  pc::Output last{};
  int presents = 0;
  bool presentResult = true;
  int clears = 0;
  int sends = 0;
  uint32_t lastSentAt = 0;
  pc::Packet lastSent{};
  std::vector<pc::Packet> log;

  EngineUnderTest(pc::Role role, uint64_t boot, Bus* shared)
      : bus(shared), engine(role, boot, hooks) {
    hooks.owner = this;
  }
};

struct World {
  Bus bus;
  EngineUnderTest coach{pc::Role::Coach, 0x1001, &bus};
  EngineUnderTest catcher{pc::Role::Catcher, 0x2002, &bus};
  EngineUnderTest pitcher{pc::Role::Pitcher, 0x3003, &bus};
  EngineUnderTest shortstop{pc::Role::Shortstop, 0x4004, &bus};
  EngineUnderTest centerfield{pc::Role::Centerfield, 0x5005, &bus};
  uint32_t now = 0;

  void tick() {
    coach.engine.tick(now);
    catcher.engine.tick(now);
    pitcher.engine.tick(now);
    shortstop.engine.tick(now);
    centerfield.engine.tick(now);
    bus.pump(now, [this](const pc::Packet& p, uint32_t at) {
      auto deliver = [&](EngineUnderTest& target) {
        if (p.target == target.engine.role()) {
          target.engine.receive(p.source, p, at, 0);
        }
      };
      deliver(coach);
      deliver(catcher);
      deliver(pitcher);
      deliver(shortstop);
      deliver(centerfield);
    });
  }
  void advance(uint32_t ms, uint32_t step = 10) {
    const uint32_t end = now + ms;
    while (now < end) {
      now += step;
      tick();
    }
  }
  void linkAll() {
    // The field units start their own handshake; the coach answers.
    advance(4000);
    CHECK(coach.engine.peer(pc::Role::Catcher).ready);
    CHECK(coach.engine.peer(pc::Role::Pitcher).ready);
    CHECK(coach.engine.peer(pc::Role::Shortstop).ready);
    CHECK(coach.engine.peer(pc::Role::Centerfield).ready);
    CHECK(catcher.engine.linked());
    CHECK(pitcher.engine.linked());
  }
};

void testProtocolRoundTrip() {
  pc::Packet in;
  in.kind = pc::Kind::Call;
  in.source = pc::Role::Catcher;
  in.target = pc::Role::Pitcher;
  in.category = pc::Category::Pitch;
  in.status = pc::Status::OutputError;
  in.dictionary = 0x7d8e943c;
  in.session = 0x1122334455667788ULL;
  in.boot = 0x99aabbccddeeff00ULL;
  in.sequence = 0xabcdef01;
  in.code = 42;
  in.ttl = 999;
  in.token = 0x0102030405060708ULL;
  in.clock = 0xdeadbeef;
  in.reference = 0x0badf00d;
  in.deadline = 0xcafebabe;
  uint8_t bytes[pc::kPacketBytes];
  pc::encode(in, bytes);
  pc::Packet out;
  CHECK(pc::decode(bytes, sizeof(bytes), out));
  CHECK(out.kind == in.kind && out.source == in.source && out.target == in.target);
  CHECK(out.category == in.category && out.status == in.status);
  CHECK(out.dictionary == in.dictionary && out.session == in.session && out.boot == in.boot);
  CHECK(out.sequence == in.sequence && out.code == in.code && out.ttl == in.ttl);
  CHECK(out.token == in.token && out.clock == in.clock && out.reference == in.reference);
  CHECK(out.deadline == in.deadline);
  CHECK(!pc::decode(bytes, sizeof(bytes) - 1, out));
  bytes[0] = 'X';
  CHECK(!pc::decode(bytes, sizeof(bytes), out));
  bytes[0] = 'P';
  bytes[3] = 0;
  CHECK(!pc::decode(bytes, sizeof(bytes), out));
}

void testHandshakeAndCall() {
  World w;
  w.linkAll();
  const auto result = w.coach.engine.submit(pc::Category::Pitch, 5, w.now);
  CHECK(result == pc::Submit::Accepted);
  w.advance(1500);
  CHECK(w.catcher.presents >= 1);
  CHECK(w.pitcher.presents >= 1);
  CHECK(w.catcher.last.code == 5);
  CHECK(w.pitcher.last.category == pc::Category::Pitch);
  CHECK(w.coach.engine.delivery(pc::Role::Catcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::Role::Pitcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::Role::Shortstop) == pc::Delivery::Unused);
  // A defensive play goes only to the fielders.
  CHECK(w.coach.engine.submit(pc::Category::Play, 2, w.now) == pc::Submit::Accepted);
  const int catcherBefore = w.catcher.presents;
  w.advance(1500);
  CHECK(w.shortstop.presents >= 1 && w.centerfield.presents >= 1);
  CHECK(w.catcher.presents == catcherBefore);
  CHECK(w.coach.engine.delivery(pc::Role::Shortstop) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::Role::Centerfield) == pc::Delivery::Delivered);
}

void testDuplicateCallDoesNotReplay() {
  World w;
  w.linkAll();
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 9, w.now) == pc::Submit::Accepted);
  w.advance(200);
  const int before = w.catcher.presents;
  // Replay the exact packet that the coach sent last.
  pc::Packet copy = w.coach.lastSent;
  w.catcher.engine.receive(copy.source, copy, w.now, 0);
  CHECK(w.catcher.presents == before);
}

void testOutputFailureIsReported() {
  World w;
  w.linkAll();
  w.pitcher.presentResult = false;
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 1, w.now) == pc::Submit::Accepted);
  w.advance(500);
  CHECK(w.coach.engine.delivery(pc::Role::Pitcher) == pc::Delivery::OutputError);
  CHECK(w.coach.engine.delivery(pc::Role::Catcher) == pc::Delivery::Delivered);
}

void testCatcherRequest() {
  World w;
  w.linkAll();
  const auto result = w.catcher.engine.submit(pc::Category::Pitch, 14, w.now);
  CHECK(result == pc::Submit::Accepted);
  w.advance(1500);
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Ok);
  CHECK(w.catcher.engine.hasOutput());
  CHECK(w.catcher.engine.output().code == 14);
  CHECK(w.pitcher.presents >= 1);
  CHECK(w.catcher.engine.submit(pc::Category::Play, 1, w.now) == pc::Submit::Invalid);
}

void testExpiredRequest() {
  World w;
  w.linkAll();
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 3, w.now) == pc::Submit::Accepted);
  // Hold the coach silent so the request ages out without a response.
  const uint32_t end = w.now + 1400;
  while (w.now < end) {
    w.now += 10;
    w.catcher.engine.tick(w.now);
    w.bus.pump(w.now, [&](const pc::Packet& p, uint32_t at) {
      if (p.target == pc::Role::Catcher) {
        w.catcher.engine.receive(p.source, p, at, 0);
      }
    });
  }
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Expired);
}

void testUsbGate() {
  pc::UsbGate gate(pc::Role::Coach);
  CHECK(gate.execute(pc::UsbCall{}, 1, 1, 0, [] { return pc::UsbResult{}; }).result == pc::Submit::Invalid);
  gate.begin(0x12345678);
  pc::UsbCall call;
  call.client = 0x12345678;
  call.id = 7;
  call.dictionary = 0x7d8e943c;
  call.boot = 0xabc;
  call.deadline = 1000;
  call.category = pc::Category::Pitch;
  call.code = 81;
  int submissions = 0;
  const auto run = [&] {
    return gate.execute(call, 0xabc, 0x7d8e943c, 500, [&] {
      ++submissions;
      return pc::UsbResult{pc::Submit::Accepted, 11};
    });
  };
  const auto first = run();
  CHECK(first.result == pc::Submit::Accepted && first.sequence == 11);
  const auto retry = run();
  CHECK(retry.result == pc::Submit::Accepted && retry.sequence == 11);
  CHECK(submissions == 1);
  // Different boot of the same id is a new command and must be rejected.
  pc::UsbCall other = call;
  other.id = 8;
  other.boot = 0xdef;
  CHECK(gate.execute(other, 0xabc, 0x7d8e943c, 500, [&] {
    return pc::UsbResult{pc::Submit::Accepted, 12};
  }).result == pc::Submit::Incompatible);
  pc::UsbCall stale = call;
  stale.id = 9;
  stale.deadline = 4000;
  CHECK(gate.execute(stale, 0xabc, 0x7d8e943c, 500, [&] {
    return pc::UsbResult{pc::Submit::Accepted, 13};
  }).result == pc::Submit::Expired);
}

void testUsbParsing() {
  pc::UsbCall call;
  CHECK(pc::parseUsbCall("call 3f2a1b0c 7 p 2 3 1 abcdef0123456789 7d8e943c 99", call));
  CHECK(call.client == 0x3f2a1b0c && call.id == 7 && call.category == pc::Category::Pitch);
  CHECK(call.code == pc::pitchCode(2, 3, 1));
  CHECK(pc::parseUsbCall("call 3f2a1b0c 7 d 5 abcdef0123456789 7d8e943c 99", call));
  CHECK(call.category == pc::Category::Play && call.code == 5);
  CHECK(!pc::parseUsbCall("call 0 7 p 2 3 1 abcdef0123456789 7d8e943c 99", call));
  CHECK(!pc::parseUsbCall("call 3f2a1b0c 0 p 2 3 1 abcdef0123456789 7d8e943c 99", call));
  CHECK(!pc::parseUsbCall("call 3f2a1b0c 7 p 2 4 1 abcdef0123456789 7d8e943c 99", call));
  uint32_t client = 0;
  CHECK(pc::parseGuiClient("gui 1234abcd", client) && client == 0x1234abcd);
  CHECK(!pc::parseGuiClient("gui 1234abc", client));
  CHECK(!pc::parseGuiClient("gui 00000000", client));
}

void testCatcherMenu() {
  pc::CatcherMenu menu;
  pc::CatcherButtons filter;
  // Startup block clears after every switch has been released for 35 ms.
  CHECK(filter.tick(0x00, true, 0) == 0);
  CHECK(filter.tick(0x00, true, 40) == 0);
  // A normal press is reported on release, one debounce interval later.
  CHECK(filter.tick(0x01, true, 50) == 0);
  CHECK(filter.tick(0x01, true, 100) == 0);
  CHECK(filter.tick(0x00, true, 150) == 0);
  CHECK(filter.tick(0x00, true, 200) == 1);
  // A chord is ignored and blocks until a 35 ms release.
  CHECK(filter.tick(0x03, true, 210) == 0);
  CHECK(filter.tick(0x00, true, 260) == 0);
  CHECK(filter.tick(0x00, true, 300) == 0);
  CHECK(filter.tick(0x02, true, 310) == 0);
  CHECK(filter.tick(0x02, true, 360) == 0);
  CHECK(filter.tick(0x00, true, 410) == 0);
  CHECK(filter.tick(0x00, true, 460) == 2);
  // Long hold of Back (bit 4) is event 6 while still held.
  CHECK(filter.tick(0x10, true, 500) == 0);
  CHECK(filter.tick(0x10, true, 560) == 0);
  CHECK(filter.tick(0x10, true, 1260) == 6);
  CHECK(filter.tick(0x00, true, 1300) == 0);
  CHECK(filter.tick(0x00, true, 1350) == 0);

  // Choose FASTBALL (1) -> UP (1) -> INSIDE (1) -> Send.
  CHECK(menu.front(1) == pc::CatcherMenu::Action::None);  // pitch -> height
  CHECK(menu.front(1) == pc::CatcherMenu::Action::None);  // height = 1
  CHECK(menu.front(4) == pc::CatcherMenu::Action::None);  // height -> location
  CHECK(menu.front(1) == pc::CatcherMenu::Action::None);  // location = 1
  CHECK(menu.code() == pc::pitchCode(1, 1, 1));
  CHECK(menu.front(4) == pc::CatcherMenu::Action::Send);
  menu.accepted();
  CHECK(!menu.draft());
  // A fresh draft: pitch 3, height 2, then Back steps to the pitch screen.
  CHECK(menu.front(3) == pc::CatcherMenu::Action::None);
  CHECK(menu.front(2) == pc::CatcherMenu::Action::None);
  menu.back(false);
  CHECK(menu.screen() == pc::CatcherMenu::Screen::Pitches);
  CHECK(menu.back(false) == pc::CatcherMenu::Action::None);  // short Back never cancels a draft
  // Page 2, then pitch 6, then long Back cancels the draft.
  CHECK(menu.front(4) == pc::CatcherMenu::Action::None);
  CHECK(menu.page() == 1);
  CHECK(menu.front(3) == pc::CatcherMenu::Action::None);
  CHECK(menu.pitch() == 6);
  menu.back(true);
  CHECK(!menu.draft());
  CHECK(menu.back(false) == pc::CatcherMenu::Action::Recall);
  // Commit only fires from a complete location screen.
  CHECK(!menu.commit(true, true, true, [](uint16_t) { return true; }));
}

void testStripPriority() {
  pc::StripState state;
  CHECK(std::strcmp(pc::stripStatus(state), "READY") == 0);
  state.hasCall = true;
  CHECK(std::strcmp(pc::stripStatus(state), "CALL") == 0);
  state.old = true;
  CHECK(std::strcmp(pc::stripStatus(state), "OLD") == 0);
  state.incompatible = true;
  CHECK(std::strcmp(pc::stripStatus(state), "DICT ERROR") == 0);
  state.radio = false;
  CHECK(std::strcmp(pc::stripStatus(state), "RADIO ERR") == 0);
  state.configured = false;
  CHECK(std::strcmp(pc::stripStatus(state), "USB SETUP") == 0);
}

}  // namespace

int main() {
  testProtocolRoundTrip();
  testHandshakeAndCall();
  testDuplicateCallDoesNotReplay();
  testOutputFailureIsReported();
  testCatcherRequest();
  testExpiredRequest();
  testUsbGate();
  testUsbParsing();
  testCatcherMenu();
  testStripPriority();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
