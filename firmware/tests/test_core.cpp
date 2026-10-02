// Host-side verification of the portable PitchComm core (firmware/include/pc).
// Build and run: firmware/tests/run_host_tests.ps1 (uses g++ or clang++).
// Pass -Sanitize for ASan/UBSan when the toolchain has sanitizer runtimes.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "pc/addr.h"
#include "pc/catalog.h"
#include "pc/controls.h"
#include "pc/diagnostics.h"
#include "pc/display_strip.h"
#include "pc/engine.h"
#include "pc/newcatcher_menu.h"
#include "pc/protocol.h"
#include "pc/units.h"
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

// Deterministic splitmix64 so every run sees the same packets.
struct Rng {
  uint64_t state;
  explicit Rng(uint64_t seed) : state(seed) {}
  uint64_t next() {
    state += 0x9e3779b97f4a7c15ULL;
    uint64_t z = state;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
  }
  uint32_t u32() { return uint32_t(next()); }
  uint16_t u16() { return uint16_t(next()); }
  unsigned below(unsigned n) { return unsigned(next() % n); }
};

// A shared simulated radio. Every send is encoded to the wire and decoded on
// delivery, so the tests exercise the real 56-byte format. Fault injection is
// seeded and deterministic: drop, jitter delay, Nth-packet reorder delay, and
// an optional fixed per-source delay.
class Bus {
 public:
  // dropPercent: chance a packet is lost outright.
  // jitterMax: seeded random extra delay in 0..jitterMax ms.
  // reorderEvery/reorderExtra: every Nth offered packet is held back, letting
  // later packets overtake it.
  void setFaults(unsigned dropPercent, uint32_t jitterMax = 0,
                 unsigned reorderEvery = 0, uint32_t reorderExtra = 0) {
    dropPercent_ = dropPercent > 100 ? 100 : dropPercent;
    jitterMax_ = jitterMax;
    reorderEvery_ = reorderEvery;
    reorderExtra_ = reorderExtra;
  }
  // Fixed extra delay for everything a role sends. Used to push a valid ACK
  // past a delivery deadline.
  void delayFrom(pc::Role source, uint32_t ms) {
    delaySource_ = int(uint8_t(source));
    delayMs_ = ms;
  }
  void clearFaults() {
    setFaults(0);
    delaySource_ = -1;
    delayMs_ = 0;
  }
  void reseed(uint64_t seed) { rng_.state = seed; }
  unsigned offered() const { return offered_; }
  unsigned dropped() const { return dropped_; }
  unsigned reordered() const { return reordered_; }

  Wire* post(const pc::Packet& p, uint32_t now, uint32_t delay = 0) {
    ++offered_;
    if (dropPercent_ && rng_.below(100) < dropPercent_) {
      ++dropped_;
      return nullptr;
    }
    uint32_t hold = delay;
    if (jitterMax_) hold += rng_.below(jitterMax_ + 1);
    if (reorderEvery_ && (offered_ % reorderEvery_) == 0) {
      hold += reorderExtra_;
      ++reordered_;
    }
    if (delayMs_ && delaySource_ == int(uint8_t(p.source))) hold += delayMs_;
    const size_t slot = wire_.size();
    wire_.push_back(Wire{});
    wire_[slot].packet = p;
    wire_[slot].deliverAt = now + hold;
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
    std::vector<Wire> due;
    due.reserve(wire_.size());
    for (auto& w : wire_) {
      // Half-range wrap math so a packet posted just before the 32-bit clock
      // rollover is still delivered once now wraps.
      if (!w.alive || uint32_t(now - w.deliverAt) >= 0x80000000u) continue;
      w.alive = false;
      due.push_back(w);
    }
    // Oldest first so a configured reorder delay actually changes the order
    // the receivers observe. Ages stay far below 2^31, so this is wrap-safe
    // and tie orders are insertion orders. Copies, so a callback that posts
    // another packet cannot invalidate the delivery list.
    std::stable_sort(due.begin(), due.end(), [now](const Wire& a, const Wire& b) {
      return uint32_t(now - a.deliverAt) > uint32_t(now - b.deliverAt);
    });
    for (const Wire& w : due) {
      uint8_t bytes[pc::kPacketBytes];
      pc::encode(w.packet, bytes);
      pc::Packet decoded;
      if (!pc::decode(bytes, sizeof(bytes), decoded)) continue;
      deliver(decoded, w.deliverAt);
    }
  }

 private:
  std::vector<Wire> wire_;
  Rng rng_{0x0F1E2D3C4B5A6978ULL};
  unsigned offered_ = 0;
  unsigned dropped_ = 0;
  unsigned reordered_ = 0;
  unsigned dropPercent_ = 0;
  unsigned reorderEvery_ = 0;
  uint32_t jitterMax_ = 0;
  uint32_t reorderExtra_ = 0;
  uint32_t delayMs_ = 0;
  int delaySource_ = -1;
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
  EngineUnderTest coach{pc::kCoach, 0x1001, &bus};
  EngineUnderTest catcher{pc::kUnitCatcher, 0x2002, &bus};
  EngineUnderTest pitcher{pc::kUnitPitcher, 0x3003, &bus};
  EngineUnderTest shortstop{pc::kUnitShortstop, 0x4004, &bus};
  EngineUnderTest center{pc::kUnitCenter, 0x5005, &bus};
  uint32_t now = 0;
  uint32_t ticks = 0;

  void tick() {
    ++ticks;
    coach.engine.tick(now);
    catcher.engine.tick(now);
    pitcher.engine.tick(now);
    shortstop.engine.tick(now);
    center.engine.tick(now);
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
      deliver(center);
    });
  }
  // Countdown style so the loop is correct when the 32-bit clock rolls over.
  void advance(uint32_t ms, uint32_t step = 10) {
    while (ms > 0) {
      const uint32_t delta = ms < step ? ms : step;
      now += delta;
      ms -= delta;
      tick();
    }
  }
  void linkAll() {
    // The field units start their own handshake; the coach answers.
    advance(4000);
    CHECK(coach.engine.peer(pc::kUnitCatcher).ready);
    CHECK(coach.engine.peer(pc::kUnitPitcher).ready);
    CHECK(coach.engine.peer(pc::kUnitShortstop).ready);
    CHECK(coach.engine.peer(pc::kUnitCenter).ready);
    CHECK(catcher.engine.linked());
    CHECK(pitcher.engine.linked());
    // The coach holds at most one queued control reply per peer. Drain them so
    // tests that count or inspect sends start from a quiet state.
    for (unsigned i = 0; i < pc::kUnitCount; ++i) coach.engine.tick(now);
  }
};

int countKind(const std::vector<pc::Packet>& log, pc::Kind kind) {
  int n = 0;
  for (const auto& p : log) {
    if (p.kind == kind) ++n;
  }
  return n;
}

pc::Packet findLast(const std::vector<pc::Packet>& log, pc::Kind kind) {
  pc::Packet out{};
  for (const auto& p : log) {
    if (p.kind == kind) out = p;
  }
  return out;
}

int countSent(const std::vector<pc::Packet>& log, pc::Kind kind, pc::Role target) {
  int n = 0;
  for (const auto& p : log) {
    if (p.kind == kind && p.target == target) ++n;
  }
  return n;
}

// A Call from the coach to a linked field unit, shaped like a real one.
pc::Packet makeCall(const World& w, pc::Role target, uint32_t sequence, uint16_t code,
                    pc::Category category = pc::Category::Pitch) {
  pc::Packet p;
  p.kind = pc::Kind::Call;
  p.source = pc::kCoach;
  p.target = target;
  p.category = category;
  p.code = code;
  p.sequence = sequence;
  p.ttl = 800;
  p.dictionary = pc::kDictionary;
  p.session = w.coach.engine.session();
  p.boot = w.coach.engine.peer(target).boot;
  p.deadline = w.now + 800;
  p.clock = w.now;
  return p;
}

// An ACK from a linked field unit to the coach.
pc::Packet makeAck(const World& w, pc::Role source, uint32_t sequence, uint16_t code,
                   pc::Status status, pc::Category category = pc::Category::Pitch) {
  pc::Packet p;
  p.kind = pc::Kind::Ack;
  p.source = source;
  p.target = pc::kCoach;
  p.category = category;
  p.code = code;
  p.sequence = sequence;
  p.status = status;
  p.dictionary = pc::kDictionary;
  p.session = w.coach.engine.session();
  p.boot = w.coach.engine.peer(source).boot;
  p.clock = w.now;
  return p;
}

using MenuAction = pc::CatcherMenu::Action;
using MenuScreen = pc::CatcherMenu::Screen;

void testProtocolRoundTrip() {
  pc::Packet in;
  in.kind = pc::Kind::Call;
  in.source = pc::kUnitCatcher;
  in.target = pc::kUnitPitcher;
  in.category = pc::Category::Pitch;
  in.status = pc::Status::OutputError;
  in.dictionary = 0x5a5a5a5a;
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

// Seeded-random field values must survive encode/decode unchanged, and encode
// must not write outside the 56-byte payload.
void testProtocolRandomRoundTrip() {
  Rng rng(0x1234abcd5678ef90ULL);
  for (int i = 0; i < 2000; ++i) {
    pc::Packet in;
    in.kind = pc::Kind(1 + rng.below(10));
    in.source = pc::Role(rng.below(pc::kMaxUnits));
    in.target = pc::Role(rng.below(pc::kMaxUnits));
    in.category = pc::Category(1 + rng.below(2));
    in.status = pc::Status(rng.below(6));
    in.dictionary = rng.u32();
    in.session = rng.next();
    in.boot = rng.next();
    in.sequence = rng.u32();
    in.code = rng.u16();
    in.ttl = rng.u16();
    in.token = rng.next();
    in.clock = rng.u32();
    in.reference = rng.u32();
    in.deadline = rng.u32();
    uint8_t buffer[pc::kPacketBytes + 4];
    std::memset(buffer, 0xEE, sizeof(buffer));
    pc::encode(in, buffer + 2);
    const bool canary = buffer[0] == 0xEE && buffer[1] == 0xEE &&
                        buffer[pc::kPacketBytes + 2] == 0xEE &&
                        buffer[pc::kPacketBytes + 3] == 0xEE;
    pc::Packet out;
    const bool decoded = pc::decode(buffer + 2, pc::kPacketBytes, out);
    const bool same = out.kind == in.kind && out.source == in.source &&
                      out.target == in.target && out.category == in.category &&
                      out.status == in.status && out.dictionary == in.dictionary &&
                      out.session == in.session && out.boot == in.boot &&
                      out.sequence == in.sequence && out.code == in.code &&
                      out.ttl == in.ttl && out.token == in.token &&
                      out.clock == in.clock && out.reference == in.reference &&
                      out.deadline == in.deadline;
    CHECK(decoded && same && canary);
  }
}

void testProtocolMalformed() {
  pc::Packet in;
  in.kind = pc::Kind::Call;
  in.source = pc::kUnitCatcher;
  in.target = pc::kUnitPitcher;
  in.category = pc::Category::Play;
  in.status = pc::Status::Ok;
  in.dictionary = pc::kDictionary;
  in.session = 0x11;
  in.boot = 0x22;
  in.sequence = 3;
  in.code = 4;
  in.ttl = 500;
  in.token = 0x33;
  in.clock = 0x44;
  in.reference = 0x55;
  in.deadline = 0x66;
  uint8_t bytes[pc::kPacketBytes];
  pc::encode(in, bytes);
  pc::Packet out;
  CHECK(pc::decode(bytes, sizeof(bytes), out));

  const auto rejected = [&](const uint8_t* b, size_t n) {
    return !pc::decode(b, n, out);
  };

  // Length must be exactly 56.
  CHECK(rejected(bytes, 0));
  CHECK(rejected(bytes, 1));
  CHECK(rejected(bytes, pc::kPacketBytes - 1));
  CHECK(rejected(bytes, pc::kPacketBytes + 1));

  uint8_t copy[pc::kPacketBytes];
  const auto tamper = [&](size_t index, uint8_t value) {
    std::memcpy(copy, bytes, sizeof(copy));
    copy[index] = value;
    return rejected(copy, sizeof(copy));
  };

  // Magic.
  CHECK(tamper(0, 'X'));
  CHECK(tamper(1, 'X'));
  // Version.
  CHECK(tamper(2, 0));
  CHECK(tamper(2, pc::kProtocolVersion + 1));
  CHECK(tamper(2, 0xFF));
  // Kind must be Hello..Ack.
  CHECK(tamper(3, 0));
  CHECK(tamper(3, uint8_t(pc::Kind::Ack) + 1));
  CHECK(tamper(3, 0xFF));
  // Role fields must stay inside the wire nibble range; the engine rejects
  // indices at or above the generated kUnitCount.
  CHECK(tamper(4, pc::kMaxUnits));
  CHECK(tamper(4, 0xFF));
  CHECK(tamper(5, pc::kMaxUnits));
  CHECK(tamper(5, 0xFF));
  CHECK(!tamper(4, pc::kMaxUnits - 1));  // the wire accepts 15; the engine filters it
  // Category must be Pitch or Play.
  CHECK(tamper(6, 0));
  CHECK(tamper(6, 3));
  CHECK(tamper(6, 0xFF));
  // Status must be a known value.
  CHECK(tamper(7, uint8_t(pc::Status::Expired) + 1));
  CHECK(tamper(7, 0xFF));
  // A failed decode leaves the output packet untouched.
  copy[0] = 'X';
  pc::Packet sentinel;
  sentinel.kind = pc::Kind::Ack;
  sentinel.code = 777;
  sentinel.session = 42;
  CHECK(!pc::decode(copy, sizeof(copy), sentinel));
  CHECK(sentinel.kind == pc::Kind::Ack && sentinel.code == 777 && sentinel.session == 42);
}

// 100,000 random and mutated 56-byte buffers. decode must never read or write
// outside the payload (guards plus ASan when available), and every buffer it
// accepts must re-encode byte for byte.
void testProtocolFuzz() {
  Rng rng(0x5EED0F1E2D3C4B5AULL);
  bool guardsOk = true;
  bool roundTripOk = true;
  bool sawValid = false;
  bool sawInvalid = false;
  pc::Packet decoded;
  for (int i = 0; i < 100000; ++i) {
    uint8_t mutated[pc::kPacketBytes];
    if ((i & 1) == 0) {
      for (size_t j = 0; j < pc::kPacketBytes; ++j) mutated[j] = uint8_t(rng.u32());
    } else {
      pc::Packet base;
      base.kind = pc::Kind(1 + rng.below(10));
      base.source = pc::Role(rng.below(pc::kMaxUnits));
      base.target = pc::Role(rng.below(pc::kMaxUnits));
      base.category = pc::Category(1 + rng.below(2));
      base.status = pc::Status(rng.below(6));
      base.dictionary = rng.u32();
      base.session = rng.next();
      base.boot = rng.next();
      base.sequence = rng.u32();
      base.code = rng.u16();
      base.ttl = rng.u16();
      base.token = rng.next();
      base.clock = rng.u32();
      base.reference = rng.u32();
      base.deadline = rng.u32();
      pc::encode(base, mutated);
      const unsigned flips = 1 + rng.below(4);
      for (unsigned f = 0; f < flips; ++f) {
        mutated[rng.below(pc::kPacketBytes)] = uint8_t(rng.u32());
      }
    }
    // Exact-size buffer: ASan can see any read past byte 55.
    if (pc::decode(mutated, pc::kPacketBytes, decoded)) {
      sawValid = true;
      uint8_t again[pc::kPacketBytes];
      pc::encode(decoded, again);
      if (std::memcmp(again, mutated, sizeof(mutated)) != 0) roundTripOk = false;
    } else {
      sawInvalid = true;
    }
    // Guarded copy: catches reads just past the payload without a sanitizer.
    uint8_t guarded[pc::kPacketBytes + 8];
    for (size_t j = 0; j < pc::kPacketBytes; ++j) guarded[j + 4] = mutated[j];
    for (size_t j = 0; j < 4; ++j) {
      guarded[j] = 0x5A;
      guarded[pc::kPacketBytes + 4 + j] = 0xA5;
    }
    pc::decode(guarded + 4, pc::kPacketBytes, decoded);
    for (size_t j = 0; j < 4; ++j) {
      if (guarded[j] != 0x5A || guarded[pc::kPacketBytes + 4 + j] != 0xA5) {
        guardsOk = false;
      }
    }
  }
  CHECK(sawValid && sawInvalid);
  CHECK(roundTripOk);
  CHECK(guardsOk);
}

void testProtocolHelpers() {
  CHECK(std::strcmp(pc::roleName(pc::kCoach), "Coach") == 0);
  CHECK(std::strcmp(pc::roleName(pc::kUnitCenter), "Center field") == 0);
  CHECK(std::strcmp(pc::roleName(pc::Role(9)), "UNKNOWN") == 0);
  CHECK(pc::validRole(pc::kUnitCenter));
  CHECK(pc::validRole(pc::kCoach));
  CHECK(!pc::validRole(pc::Role(pc::kUnitCount)));
  CHECK(pc::roleMask(pc::kCoach) == pc::kUnitMask(0));
  CHECK(pc::roleMask(pc::kUnitPitcher) == pc::kUnitMask(pc::kUnitPitcher));
  CHECK(pc::roleMask(pc::kUnitCatcher) == pc::kUnitMask(pc::kUnitCatcher));
  CHECK(pc::roleMask(pc::kUnitCenter) == pc::kUnitMask(4));
  CHECK(pc::audioRole(pc::kUnitPitcher));
  CHECK(!pc::audioRole(pc::kUnitCatcher));
  CHECK(pc::displayRole(pc::kUnitCatcher));
  CHECK(!pc::displayRole(pc::kUnitPitcher));
  CHECK(pc::controlsRole(pc::kUnitCatcher));
  CHECK(!pc::controlsRole(pc::kUnitPitcher));
  CHECK(!pc::controlsRole(pc::kCoach));
  // Default roster audiences: pitcher + catcher pitch, plays per their targets.
  constexpr uint16_t kPitchMask =
      pc::kUnitMask(pc::kUnitPitcher) | pc::kUnitMask(pc::kUnitCatcher);
  CHECK(pc::recipients(pc::Category::Pitch, 1) == kPitchMask);
  CHECK(pc::recipients(pc::Category::Pitch, pc::kPitchCount * pc::kRows * pc::kCols) == kPitchMask);
  CHECK(pc::recipients(pc::Category::Play, 2) == kPitchMask);  // STEP OFF: battery
  CHECK(pc::recipients(pc::Category::Play, 13) ==
        (kPitchMask | pc::kUnitMask(pc::kUnitShortstop) | pc::kUnitMask(pc::kUnitCenter)));
  CHECK(pc::recipients(pc::Category::Play, 18) == pc::kUnitMask(pc::kUnitCenter));
  // Every generated call reaches enrolled field units, never the coach.
  constexpr uint16_t kEnrolledMask = (1u << pc::kUnitCount) - 1u;
  for (const auto& c : pc::kCalls) {
    CHECK(c.audience != 0);
    CHECK((c.audience & pc::kUnitMask(pc::kCoach)) == 0);
    CHECK((c.audience & ~kEnrolledMask) == 0);
    CHECK(pc::recipients(c.category, c.code) == c.audience);
  }
  // 32-bit wrap math.
  CHECK(pc::elapsed(5u, 0xFFFFFFF0u) == 21u);
  CHECK(pc::newer(5u, 0xFFFFFFF0u));
  CHECK(!pc::newer(0xFFFFFFF0u, 5u));
  CHECK(!pc::newer(0x80000000u, 0u));
  CHECK(pc::newer(0x7FFFFFFFu, 0u));
  CHECK(!pc::newer(7u, 7u));
  // Catalog boundaries, driven by the generated counts.
  constexpr unsigned kPitchCodes = pc::kPitchCount * pc::kRows * pc::kCols;
  CHECK(pc::pitchCode(pc::kPitchCount, pc::kRows, pc::kCols) == kPitchCodes);
  CHECK(pc::pitchCode(0, 1, 1) == 0);
  CHECK(pc::pitchCode(1, pc::kRows + 1, 1) == 0);
  CHECK(pc::pitchCode(1, 1, pc::kCols + 1) == 0);
  CHECK(pc::findCall(pc::Category::Pitch, kPitchCodes) != nullptr);
  CHECK(pc::findCall(pc::Category::Pitch, kPitchCodes + 1) == nullptr);
  CHECK(pc::findCall(pc::Category::Pitch, 0) == nullptr);
  CHECK(pc::findCall(pc::Category::Play, 1) != nullptr);
  CHECK(pc::findCall(pc::Category::Play, pc::kPlayCount) != nullptr);
  CHECK(pc::findCall(pc::Category::Play, pc::kPlayCount + 1) == nullptr);
  CHECK(pc::findCall(pc::Category::Play, 1)->code == 1);
}

void testSelection() {
  pc::Selection s;
  CHECK(s.code() == 0);
  CHECK(!s.choose(0));
  CHECK(!s.choose(pc::kPitchCount + 1));
  CHECK(s.choose(5) && s.type == 5 && s.height == 0 && s.side == 0);
  CHECK(s.choose(2) && s.height == 2);
  CHECK(!s.choose(pc::kRows + 1));  // row keys are 1..kRows only
  CHECK(s.choose(pc::kCols) && s.side == pc::kCols);
  CHECK(s.code() == pc::pitchCode(5, 2, pc::kCols));
  // A complete selection restarts on the next key.
  CHECK(s.choose(7) && s.type == 7 && s.height == 0 && s.side == 0);
  s.clear();
  CHECK(s.type == 0 && s.height == 0 && s.side == 0 && s.code() == 0);
  CHECK(s.choose(pc::kPitchCount) && s.choose(pc::kRows + 1) == false && s.choose(1));
  CHECK(s.height == 1 && s.side == 0);
  CHECK(s.choose(1) && s.code() == pc::pitchCode(pc::kPitchCount, 1, 1));
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
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitShortstop) == pc::Delivery::Unused);
  // A center-only play (SEE DOWN) reaches center field and nobody else.
  CHECK(w.coach.engine.submit(pc::Category::Play, 18, w.now) == pc::Submit::Accepted);
  const int pitcherBefore = w.pitcher.presents;
  const int catcherBefore = w.catcher.presents;
  const int shortstopBefore = w.shortstop.presents;
  w.advance(1500);
  CHECK(w.center.presents >= 1);
  CHECK(w.pitcher.presents == pitcherBefore);
  CHECK(w.catcher.presents == catcherBefore);
  CHECK(w.shortstop.presents == shortstopBefore);
  CHECK(w.coach.engine.delivery(pc::kUnitCenter) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitShortstop) == pc::Delivery::Unused);
  // A team play (BUNT DEF) now reaches pitcher and catcher too.
  CHECK(w.coach.engine.submit(pc::Category::Play, 13, w.now) == pc::Submit::Accepted);
  w.advance(1500);
  CHECK(w.pitcher.presents >= pitcherBefore + 1);
  CHECK(w.catcher.presents >= catcherBefore + 1);
  CHECK(w.shortstop.presents >= shortstopBefore + 1);
  CHECK(w.center.presents >= 2);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitShortstop) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitCenter) == pc::Delivery::Delivered);
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
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::OutputError);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
}

void testOutputFailureOverride() {
  World w;
  w.linkAll();
  pc::Packet call = makeCall(w, pc::kUnitPitcher, 21, 5);
  w.pitcher.engine.receive(pc::kCoach, call, w.now, 0);
  CHECK(w.pitcher.presents >= 1);
  w.pitcher.engine.tick(w.now);  // flush the initial OK ACK
  w.pitcher.log.clear();
  w.pitcher.engine.outputFailed(999, w.now);  // unknown sequence is ignored
  w.pitcher.engine.tick(w.now);
  CHECK(countKind(w.pitcher.log, pc::Kind::Ack) == 0);
  w.pitcher.engine.outputFailed(21, w.now);
  w.pitcher.engine.tick(w.now);
  const pc::Packet ack = findLast(w.pitcher.log, pc::Kind::Ack);
  CHECK(ack.kind == pc::Kind::Ack);
  CHECK(ack.sequence == 21 && ack.status == pc::Status::OutputError);
}

void testOutputStaleness() {
  World w;
  w.linkAll();
  pc::Packet call = makeCall(w, pc::kUnitPitcher, 30, 1);
  w.pitcher.engine.receive(pc::kCoach, call, w.now, 0);
  CHECK(w.pitcher.engine.hasOutput());
  CHECK(w.pitcher.engine.outputAge(w.now) == 0);
  CHECK(!w.pitcher.engine.outputOld(w.now));
  CHECK(!w.pitcher.engine.outputOld(w.now + pc::kOldCall - 1));
  CHECK(w.pitcher.engine.outputOld(w.now + pc::kOldCall));
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
  // Only a controls unit may originate; the pitcher receives pitches, not menus.
  CHECK(w.pitcher.engine.submit(pc::Category::Pitch, 1, w.now) == pc::Submit::Invalid);
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
      if (p.target == pc::kUnitCatcher) {
        w.catcher.engine.receive(p.source, p, at, 0);
      }
    });
  }
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Expired);
}

void testCatcherRequestWhileCoachBusy() {
  World w;
  w.linkAll();
  // Start a coach call and a catcher request in the same tick, before any
  // receiver acknowledges. Deliver only the request to the coach.
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 1, w.now) == pc::Submit::Accepted);
  w.coach.engine.tick(w.now);
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 20, w.now) == pc::Submit::Accepted);
  w.catcher.engine.tick(w.now);
  w.bus.pump(w.now, [&](const pc::Packet& p, uint32_t at) {
    if (p.target == pc::kCoach && p.source == pc::kUnitCatcher) {
      w.coach.engine.receive(p.source, p, at, 0);
    }
  });
  // The coach answers Busy while its own call's window is open.
  w.advance(200);
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Busy);
  // The coach's own call still completes.
  w.advance(1500);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
}

// The catcher retransmits an unanswered request every 100 ms and expires it at
// the call window; ttl counts down on every retry.
void testRequestRetransmits() {
  World w;
  w.linkAll();
  w.catcher.log.clear();
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 9, w.now) == pc::Submit::Accepted);
  CHECK(w.catcher.engine.busy());
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 10, w.now) == pc::Submit::Busy);
  const uint32_t t0 = w.now;
  for (uint32_t t = 0; t < 1000; t += 10) {
    w.now += 10;
    w.catcher.engine.tick(w.now);
    if (t == 490 || t == 500) {
      CHECK(!w.catcher.engine.requestFinished());
      CHECK(w.catcher.engine.requestResult() == pc::Status::Busy);
    }
  }
  CHECK(t0 + 1000 == w.now);
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Expired);
  CHECK(!w.catcher.engine.busy());
  int requests = 0;
  uint16_t firstTtl = 0, lastTtl = 0;
  for (const auto& p : w.catcher.log) {
    if (p.kind != pc::Kind::Request) continue;
    ++requests;
    if (!firstTtl) firstTtl = p.ttl;
    lastTtl = p.ttl;
    CHECK(p.target == pc::kCoach);
  }
  CHECK(requests == 10);
  CHECK(firstTtl == 990 && lastTtl == 90);
}

// Reordered handshakes from the same boot must not roll the peer challenge or
// its ordering clock backwards.
void testHandshakeReorder() {
  World w;
  const uint64_t boot = 0x55aa;
  const auto feed = [&](uint32_t clock, uint64_t token) {
    pc::Packet p;
    p.kind = pc::Kind::Hello;
    p.source = pc::kUnitCatcher;
    p.target = pc::kCoach;
    p.boot = boot;
    p.token = token;
    p.dictionary = pc::kDictionary;
    p.clock = clock;
    w.coach.engine.receive(pc::kUnitCatcher, p, w.now, 0);
    const int before = w.coach.sends;
    w.coach.engine.tick(w.now);
    return w.coach.sends - before;
  };
  CHECK(feed(1000, 0x11) == 1);
  CHECK(w.coach.lastSent.kind == pc::Kind::Sync);
  CHECK(w.coach.lastSent.token == 0x11);
  CHECK(w.coach.lastSent.reference == 1000);
  CHECK(w.coach.lastSent.dictionary == pc::kDictionary);
  CHECK(feed(999, 0x11) == 0);   // reordered older Hello
  CHECK(feed(1000, 0x22) == 0);  // same clock, different challenge
  CHECK(feed(1001, 0x11) == 1);  // newer clock, same challenge
  CHECK(feed(1001, 0x22) == 0);  // same clock, different challenge
  CHECK(feed(1002, 0x22) == 1);  // newer clock adopts the new challenge
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).challenge == 0x22);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).boot == boot);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).compatible);
}

// One control reply per tick, round robin, so simultaneous handshakes all get
// answered instead of the first one starving the rest.
void testControlReplyRoundRobin() {
  World w;
  for (unsigned r = 1; r < pc::kUnitCount; ++r) {
    pc::Packet p;
    p.kind = pc::Kind::Hello;
    p.source = pc::Role(r);
    p.target = pc::kCoach;
    p.boot = 0x100 + r;
    p.token = 0x10 + r;
    p.dictionary = pc::kDictionary;
    p.clock = w.now + r;
    w.coach.engine.receive(pc::Role(r), p, w.now, 0);
  }
  for (unsigned i = 0; i < pc::kUnitCount - 1; ++i) w.coach.engine.tick(w.now);
  CHECK(countKind(w.coach.log, pc::Kind::Sync) == int(pc::kUnitCount - 1));
  bool seen[pc::kUnitCount] = {};
  for (const auto& p : w.coach.log) {
    if (p.kind == pc::Kind::Sync && pc::validRole(p.target)) seen[uint8_t(p.target)] = true;
  }
  CHECK(seen[1] && seen[2] && seen[3] && seen[4]);
}

// The field only accepts a Sync whose token matches the challenge it sent.
void testFieldSyncToken() {
  World w;
  w.catcher.engine.tick(w.now);
  CHECK(w.catcher.lastSent.kind == pc::Kind::Hello);
  const uint64_t token = w.catcher.lastSent.token;
  CHECK(token != 0);
  const auto sync = [&](uint64_t useToken, uint64_t useBoot, pc::Status status,
                        uint64_t session) {
    pc::Packet p;
    p.kind = pc::Kind::Sync;
    p.source = pc::kCoach;
    p.target = pc::kUnitCatcher;
    p.token = useToken;
    p.boot = useBoot;
    p.dictionary = pc::kDictionary;
    p.status = status;
    p.session = session;
    p.clock = w.now + 1;
    p.reference = w.now;
    return p;
  };
  w.catcher.engine.receive(pc::kCoach,
                           sync(token ^ 1, w.catcher.engine.boot(), pc::Status::Ok, 0x77),
                           w.now, 0);
  CHECK(!w.catcher.engine.linked());
  CHECK(!w.catcher.engine.incompatible());
  w.catcher.engine.receive(pc::kCoach,
                           sync(token, w.catcher.engine.boot() ^ 1, pc::Status::Ok, 0x77),
                           w.now, 0);
  CHECK(!w.catcher.engine.linked());
  w.catcher.engine.receive(pc::kCoach,
                           sync(token, w.catcher.engine.boot(), pc::Status::Ok, 0x77),
                           w.now, 0);
  CHECK(w.catcher.engine.linked());
  CHECK(w.catcher.engine.session() == 0x77);
  CHECK(!w.catcher.engine.incompatible());
}

// A mismatched dictionary or status in Sync must raise the incompatible flag
// and never link the field unit.
void testIncompatibleDictionary() {
  World w;
  w.catcher.engine.tick(w.now);
  const uint64_t token = w.catcher.lastSent.token;
  const auto sync = [&](uint32_t dictionary, pc::Status status, uint64_t session) {
    pc::Packet p;
    p.kind = pc::Kind::Sync;
    p.source = pc::kCoach;
    p.target = pc::kUnitCatcher;
    p.token = token;
    p.boot = w.catcher.engine.boot();
    p.dictionary = dictionary;
    p.status = status;
    p.session = session;
    p.clock = w.now + 1;
    p.reference = w.now;
    return p;
  };
  w.catcher.engine.receive(pc::kCoach, sync(pc::kDictionary ^ 1, pc::Status::Ok, 0x5),
                           w.now, 0);
  CHECK(w.catcher.engine.incompatible());
  CHECK(!w.catcher.engine.linked());
  // A later matching Sync clears the flag.
  w.catcher.engine.receive(pc::kCoach, sync(pc::kDictionary, pc::Status::Ok, 0x5),
                           w.now, 0);
  CHECK(w.catcher.engine.linked());
  CHECK(!w.catcher.engine.incompatible());
  CHECK(w.catcher.engine.session() == 0x5);
  // Incompatible status and a zero session are rejected the same way.
  World w2;
  w2.catcher.engine.tick(w2.now);
  const uint64_t token2 = w2.catcher.lastSent.token;
  pc::Packet bad;
  bad.kind = pc::Kind::Sync;
  bad.source = pc::kCoach;
  bad.target = pc::kUnitCatcher;
  bad.token = token2;
  bad.boot = w2.catcher.engine.boot();
  bad.dictionary = pc::kDictionary;
  bad.status = pc::Status::Incompatible;
  bad.session = 0x5;
  bad.clock = w2.now + 1;
  bad.reference = w2.now;
  w2.catcher.engine.receive(pc::kCoach, bad, w2.now, 0);
  CHECK(w2.catcher.engine.incompatible());
  bad.status = pc::Status::Ok;
  bad.session = 0;
  w2.catcher.engine.receive(pc::kCoach, bad, w2.now, 0);
  CHECK(w2.catcher.engine.incompatible());
  CHECK(!w2.catcher.engine.linked());
}

// An ACK processed exactly at or beyond the delivery deadline must not revive
// a call that the tick loop is about to mark Missing.
void testAckAfterDeadline() {
  World w;
  w.linkAll();
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 4, w.now) == pc::Submit::Accepted);
  const uint32_t firstSeq = w.coach.engine.record(pc::Category::Pitch).output.sequence;
  const uint32_t firstAt = w.now;
  w.now = firstAt + pc::kCallWindow - 1;
  w.coach.engine.receive(pc::kUnitPitcher, makeAck(w, pc::kUnitPitcher, firstSeq, 4, pc::Status::Ok),
                         w.now, 0);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  w.now = firstAt + pc::kCallWindow + 1;
  w.coach.engine.tick(w.now);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);

  CHECK(w.coach.engine.submit(pc::Category::Pitch, 5, w.now) == pc::Submit::Accepted);
  const uint32_t secondSeq = w.coach.engine.record(pc::Category::Pitch).output.sequence;
  const uint32_t secondAt = w.now;
  w.now = secondAt + pc::kCallWindow;
  w.coach.engine.receive(pc::kUnitPitcher, makeAck(w, pc::kUnitPitcher, secondSeq, 5, pc::Status::Ok),
                         w.now, 0);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Pending);
  w.coach.engine.tick(w.now);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Missing);
  CHECK(w.coach.engine.record(pc::Category::Pitch).delivery[uint8_t(pc::kUnitPitcher)] ==
        pc::Delivery::Missing);
  // A late ACK cannot flip a recorded Missing back to Delivered.
  w.coach.engine.receive(pc::kUnitPitcher, makeAck(w, pc::kUnitPitcher, secondSeq, 5, pc::Status::Ok),
                         w.now + 5, 0);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Missing);
}

// Duplicate and stale calls are suppressed; sequences survive 32-bit wrap.
void testStaleAndDuplicateCalls() {
  World w;
  w.linkAll();
  const auto call = [&](uint32_t sequence, uint16_t code, uint16_t ttl = 800) {
    pc::Packet p = makeCall(w, pc::kUnitPitcher, sequence, code);
    p.ttl = ttl;
    return p;
  };
  const int before = w.pitcher.presents;
  w.pitcher.engine.receive(pc::kCoach, call(0xFFFFFFF0u, 1), w.now, 0);
  CHECK(w.pitcher.presents == before + 1);
  w.pitcher.engine.receive(pc::kCoach, call(5, 2), w.now, 0);  // sequence wrap
  CHECK(w.pitcher.presents == before + 2);
  w.pitcher.engine.receive(pc::kCoach, call(5, 2), w.now, 0);  // exact duplicate
  CHECK(w.pitcher.presents == before + 2);
  w.pitcher.engine.receive(pc::kCoach, call(5, 3), w.now, 0);  // same sequence, new code
  CHECK(w.pitcher.presents == before + 2);
  w.pitcher.engine.receive(pc::kCoach, call(4, 1), w.now, 0);  // older, across the wrap
  CHECK(w.pitcher.presents == before + 2);
  w.pitcher.engine.receive(pc::kCoach, call(6, 4), w.now, 0);  // newer sequence
  CHECK(w.pitcher.presents == before + 3);
  // ttl and queue age bounds.
  w.pitcher.engine.receive(pc::kCoach, call(10, 6, 0), w.now, 0);
  CHECK(w.pitcher.presents == before + 3);
  w.pitcher.engine.receive(pc::kCoach, call(11, 7, pc::kCallWindow + 1), w.now, 0);
  CHECK(w.pitcher.presents == before + 3);
  w.pitcher.engine.receive(pc::kCoach, call(12, 8, 800), w.now, 800);
  CHECK(w.pitcher.presents == before + 3);
  // Deadline already passed.
  pc::Packet late = call(13, 1);
  late.deadline = w.now - 50;
  w.pitcher.engine.receive(pc::kCoach, late, w.now, 0);
  CHECK(w.pitcher.presents == before + 3);
  // Session and dictionary mismatches.
  pc::Packet wrongSession = call(14, 1);
  wrongSession.session ^= 1;
  w.pitcher.engine.receive(pc::kCoach, wrongSession, w.now, 0);
  CHECK(w.pitcher.presents == before + 3);
  pc::Packet wrongDictionary = call(15, 1);
  wrongDictionary.dictionary ^= 1;
  w.pitcher.engine.receive(pc::kCoach, wrongDictionary, w.now, 0);
  CHECK(w.pitcher.presents == before + 3);
  w.pitcher.engine.receive(pc::kCoach, call(16, 9), w.now, 0);
  CHECK(w.pitcher.presents == before + 4);
  // A duplicate of the retained call is ACKed again; a conflicting code is not.
  w.pitcher.log.clear();
  w.pitcher.engine.receive(pc::kCoach, call(16, 9), w.now, 0);
  w.pitcher.engine.tick(w.now);
  CHECK(countKind(w.pitcher.log, pc::Kind::Ack) == 1);
  w.pitcher.log.clear();
  w.pitcher.engine.receive(pc::kCoach, call(16, 8), w.now, 0);
  w.pitcher.engine.tick(w.now);
  CHECK(countKind(w.pitcher.log, pc::Kind::Ack) == 0);
}

// A rebooted field unit (new boot Hello) resets the peer entry and marks its
// in-flight delivery Missing; the stale boot is never retried.
void testNewBootResetsPeer() {
  World w;
  w.linkAll();
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 7, w.now) == pc::Submit::Accepted);
  w.coach.engine.tick(w.now);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Pending);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).boot == w.catcher.engine.boot());
  pc::Packet hello;
  hello.kind = pc::Kind::Hello;
  hello.source = pc::kUnitCatcher;
  hello.target = pc::kCoach;
  hello.boot = 0xB007;
  hello.token = 0x5151;
  hello.dictionary = pc::kDictionary;
  hello.clock = w.now + 1;
  w.coach.engine.receive(pc::kUnitCatcher, hello, w.now, 0);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).boot == 0xB007);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).challenge == 0x5151);
  CHECK(!w.coach.engine.peer(pc::kUnitCatcher).ready);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Missing);
  CHECK(w.coach.engine.record(pc::Category::Pitch).delivery[uint8_t(pc::kUnitCatcher)] ==
        pc::Delivery::Missing);
  // The real unit is told to resync and rejoins under its own boot.
  w.advance(2500);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).ready);
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).boot == w.catcher.engine.boot());
  CHECK(w.catcher.engine.linked());
}

// The receive entry point rejects spoofed sources, wrong targets and invalid
// authenticated roles before any state changes.
void testSourceTargetMismatch() {
  World w;
  w.linkAll();
  const int catcherBefore = w.catcher.presents;
  const int pitcherBefore = w.pitcher.presents;
  pc::Packet call = makeCall(w, pc::kUnitCatcher, 500, 5);
  // Wrong target: the pitcher ignores a call addressed to the catcher.
  w.pitcher.engine.receive(pc::kCoach, call, w.now, 0);
  CHECK(w.pitcher.presents == pitcherBefore);
  // The authenticated source must match the packet source.
  pc::Packet spoof = call;
  spoof.source = pc::kCoach;
  w.catcher.engine.receive(pc::kUnitCatcher, spoof, w.now, 0);
  CHECK(w.catcher.presents == catcherBefore);
  // Invalid authenticated role.
  w.catcher.engine.receive(pc::Role(pc::kUnitCount), call, w.now, 0);
  CHECK(w.catcher.presents == catcherBefore);
  // Field units only accept traffic that claims the coach as source.
  pc::Packet nonCoach = call;
  nonCoach.source = pc::kUnitPitcher;
  w.catcher.engine.receive(pc::kUnitPitcher, nonCoach, w.now, 0);
  CHECK(w.catcher.presents == catcherBefore);
  // A packet delivered to the coach that claims to come from the coach is
  // ignored without a reply.
  pc::Packet selfCall = call;
  selfCall.source = pc::kCoach;
  selfCall.target = pc::kCoach;
  w.coach.engine.tick(w.now);  // drain any pending control reply first
  const int coachSends = w.coach.sends;
  w.coach.engine.receive(pc::kCoach, selfCall, w.now, 0);
  w.coach.engine.tick(w.now);
  CHECK(w.coach.sends == coachSends);
  // The well-formed call still lands.
  w.catcher.engine.receive(pc::kCoach, call, w.now, 0);
  CHECK(w.catcher.presents == catcherBefore + 1);
}

// Only a Response with the live request sequence and code finishes a request.
void testResponseMatching() {
  World w;
  w.linkAll();
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 7, w.now) == pc::Submit::Accepted);
  CHECK(!w.catcher.engine.requestFinished());
  w.catcher.engine.tick(w.now);
  const pc::Packet request = findLast(w.catcher.log, pc::Kind::Request);
  CHECK(request.kind == pc::Kind::Request);
  CHECK(request.target == pc::kCoach);
  CHECK(w.catcher.engine.requestResult() == pc::Status::Busy);
  const auto response = [&](uint32_t sequence, uint16_t code, pc::Status status,
                            uint64_t session) {
    pc::Packet p;
    p.kind = pc::Kind::Response;
    p.source = pc::kCoach;
    p.target = pc::kUnitCatcher;
    p.category = pc::Category::Pitch;
    p.code = code;
    p.sequence = sequence;
    p.status = status;
    p.session = session;
    p.dictionary = pc::kDictionary;
    p.boot = w.catcher.engine.boot();
    p.clock = w.now;
    p.reference = w.now;
    return p;
  };
  // Wrong role claiming to be the response.
  pc::Packet spoof = response(request.sequence, request.code, pc::Status::Ok,
                              w.coach.engine.session());
  spoof.source = pc::kUnitPitcher;
  w.catcher.engine.receive(pc::kUnitPitcher, spoof, w.now, 0);
  CHECK(!w.catcher.engine.requestFinished());
  // Wrong sequence.
  w.catcher.engine.receive(pc::kCoach,
                           response(request.sequence + 1, request.code, pc::Status::Ok,
                                    w.coach.engine.session()),
                           w.now, 0);
  CHECK(!w.catcher.engine.requestFinished());
  // Wrong code.
  w.catcher.engine.receive(pc::kCoach,
                           response(request.sequence, uint16_t(request.code + 1),
                                    pc::Status::Ok, w.coach.engine.session()),
                           w.now, 0);
  CHECK(!w.catcher.engine.requestFinished());
  // Wrong session.
  w.catcher.engine.receive(pc::kCoach,
                           response(request.sequence, request.code, pc::Status::Ok,
                                    w.coach.engine.session() ^ 1),
                           w.now, 0);
  CHECK(!w.catcher.engine.requestFinished());
  // Matching response carries the status through.
  w.catcher.engine.receive(pc::kCoach,
                           response(request.sequence, request.code, pc::Status::Invalid,
                                    w.coach.engine.session()),
                           w.now, 0);
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Invalid);
  // A duplicate after the request ended is ignored.
  w.catcher.engine.receive(pc::kCoach,
                           response(request.sequence, request.code, pc::Status::Ok,
                                    w.coach.engine.session()),
                           w.now, 0);
  CHECK(w.catcher.engine.requestResult() == pc::Status::Invalid);
}

// The coach answers a repeated request sequence with the saved result and only
// starts one call; a new sequence while busy gets Busy.
void testCoachRequestRetries() {
  World w;
  w.linkAll();
  const auto request = [&](uint32_t sequence, uint16_t code, uint32_t deadline) {
    pc::Packet p;
    p.kind = pc::Kind::Request;
    p.source = pc::kUnitCatcher;
    p.target = pc::kCoach;
    p.category = pc::Category::Pitch;
    p.code = code;
    p.sequence = sequence;
    p.ttl = 800;
    p.dictionary = pc::kDictionary;
    p.session = w.coach.engine.session();
    p.boot = w.coach.engine.peer(pc::kUnitCatcher).boot;
    p.clock = w.now;
    p.deadline = deadline;
    return p;
  };
  w.coach.log.clear();
  const uint32_t deadline = w.now + 800;
  w.coach.engine.receive(pc::kUnitCatcher, request(1, 12, deadline), w.now, 0);
  w.coach.engine.tick(w.now);
  const pc::Packet first = findLast(w.coach.log, pc::Kind::Response);
  CHECK(first.kind == pc::Kind::Response);
  CHECK(first.target == pc::kUnitCatcher);
  CHECK(first.sequence == 1 && first.code == 12);
  CHECK(first.status == pc::Status::Ok);
  CHECK(first.token != 0);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == 1);
  // A retry of the same sequence returns the saved response, not a new call.
  w.coach.engine.receive(pc::kUnitCatcher, request(1, 12, deadline), w.now, 0);
  w.coach.engine.tick(w.now);
  const pc::Packet retry = findLast(w.coach.log, pc::Kind::Response);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == 2);
  CHECK(retry.token == first.token && retry.status == first.status);
  // Same sequence with a different code is not a retry.
  w.coach.engine.receive(pc::kUnitCatcher, request(1, 13, deadline), w.now, 0);
  w.coach.engine.tick(w.now);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == 2);
  // Sequence zero is rejected outright.
  w.coach.engine.receive(pc::kUnitCatcher, request(0, 12, deadline), w.now, 0);
  w.coach.engine.tick(w.now);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == 2);
  // A new sequence while the call window is open is answered Busy.
  w.coach.engine.receive(pc::kUnitCatcher, request(2, 12, deadline), w.now, 0);
  w.coach.engine.tick(w.now);
  const pc::Packet busy = findLast(w.coach.log, pc::Kind::Response);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == 3);
  CHECK(busy.status == pc::Status::Busy && busy.sequence == 2);
  CHECK(busy.token == 0);
  // A unit without the controls capability cannot originate: no response.
  pc::Packet pitcherRequest = request(4, 12, w.now + 800);
  pitcherRequest.source = pc::kUnitPitcher;
  pitcherRequest.boot = w.coach.engine.peer(pc::kUnitPitcher).boot;
  const int responsesBefore = countKind(w.coach.log, pc::Kind::Response);
  w.coach.engine.receive(pc::kUnitPitcher, pitcherRequest, w.now, 0);
  w.coach.engine.tick(w.now);
  CHECK(countKind(w.coach.log, pc::Kind::Response) == responsesBefore);
  // After the window a fresh sequence is accepted and starts a new call.
  w.advance(900);
  w.coach.engine.receive(pc::kUnitCatcher, request(3, 12, w.now + 800), w.now, 0);
  w.coach.engine.tick(w.now);
  const pc::Packet ok = findLast(w.coach.log, pc::Kind::Response);
  CHECK(ok.status == pc::Status::Ok && ok.sequence == 3);
  CHECK(ok.token != 0 && ok.token != first.token);
}

// Link timeout puts the field back into sync, drops its retained call, and a
// fresh handshake brings it back.
void testLinkTimeoutResync() {
  World w;
  w.linkAll();
  CHECK(w.catcher.engine.linked());
  // Retain an output so startSync() is observable.
  w.catcher.engine.receive(pc::kCoach, makeCall(w, pc::kUnitCatcher, 40, 1), w.now, 0);
  CHECK(w.catcher.engine.hasOutput());
  // Keep only the field alive; the coach stays silent so the link ages out.
  for (uint32_t t = 0; t < 3600; t += 10) {
    w.now += 10;
    w.catcher.engine.tick(w.now);
  }
  CHECK(!w.catcher.engine.linked());
  CHECK(!w.catcher.engine.hasOutput());
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 3, w.now) == pc::Submit::Offline);
  // Resume normal ticking: the field re-handshakes and the link returns.
  w.advance(2500);
  CHECK(w.catcher.engine.linked());
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).ready);
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 3, w.now) == pc::Submit::Accepted);
  w.advance(1200);
  CHECK(w.pitcher.presents >= 1);
}

// The field's Ping/Pong exchange keeps the coach reachable; a stale Pong must
// not refresh liveness, while a fresh one must.
void testPongLiveness() {
  {
    World w;
    w.linkAll();
    const uint64_t boot = w.catcher.engine.boot();
    const uint64_t session = w.catcher.engine.session();
    const auto pong = [&](uint32_t clock) {
      pc::Packet p;
      p.kind = pc::Kind::Pong;
      p.source = pc::kCoach;
      p.target = pc::kUnitCatcher;
      p.boot = boot;
      p.session = session;
      p.dictionary = pc::kDictionary;
      p.clock = clock;
      p.reference = w.now;
      return p;
    };
    // Pin liveness to the loop start, then send only stale Pongs.
    w.catcher.engine.receive(pc::kCoach, pong(w.now + 1), w.now, 0);
    for (uint32_t t = 0; t < 3600; t += 10) {
      w.now += 10;
      w.catcher.engine.tick(w.now);
      w.catcher.engine.receive(pc::kCoach, pong(w.now - 20000), w.now, 0);
    }
    CHECK(!w.catcher.engine.linked());
  }
  {
    World w;
    w.linkAll();
    const uint64_t boot = w.catcher.engine.boot();
    const uint64_t session = w.catcher.engine.session();
    const auto pong = [&](uint32_t clock) {
      pc::Packet p;
      p.kind = pc::Kind::Pong;
      p.source = pc::kCoach;
      p.target = pc::kUnitCatcher;
      p.boot = boot;
      p.session = session;
      p.dictionary = pc::kDictionary;
      p.clock = clock;
      p.reference = w.now;
      return p;
    };
    // Pin liveness to the loop start, then send only stale Pongs.
    w.catcher.engine.receive(pc::kCoach, pong(w.now + 1), w.now, 0);
    for (uint32_t t = 0; t < 3400; t += 10) {
      w.now += 10;
      w.catcher.engine.tick(w.now);
      w.catcher.engine.receive(pc::kCoach, pong(w.now - 20000), w.now, 0);
    }
    CHECK(w.catcher.engine.linked());
    w.catcher.engine.receive(pc::kCoach, pong(w.now + 1), w.now, 0);
    for (uint32_t t = 0; t < 1000; t += 10) {
      w.now += 10;
      w.catcher.engine.tick(w.now);
      w.catcher.engine.receive(pc::kCoach, pong(w.now - 20000), w.now, 0);
    }
    CHECK(w.catcher.engine.linked());
  }
}

// The coach replies to Ping with a Pong that references the Ping clock.
void testPingPongMechanics() {
  World w;
  w.linkAll();
  w.catcher.log.clear();
  w.advance(1100);
  const pc::Packet ping = findLast(w.catcher.log, pc::Kind::Ping);
  CHECK(ping.kind == pc::Kind::Ping);
  CHECK(ping.source == pc::kUnitCatcher && ping.target == pc::kCoach);
  CHECK(ping.dictionary == pc::kDictionary);
  CHECK(ping.session == w.catcher.engine.session());
  w.coach.log.clear();
  w.coach.engine.receive(pc::kUnitCatcher, ping, w.now, 0);
  w.coach.engine.tick(w.now);
  const pc::Packet pong = findLast(w.coach.log, pc::Kind::Pong);
  CHECK(pong.kind == pc::Kind::Pong);
  CHECK(pong.reference == ping.clock);
  CHECK(pong.boot == w.catcher.engine.boot());
  CHECK(pong.target == pc::kUnitCatcher);
}

// Full handshake, calls, and Ping/Pong across the 32-bit millisecond rollover.
void testClockWrap() {
  World w;
  w.now = 0xFFFFF800u;  // 2 s before wrap; linkAll() crosses it
  w.linkAll();
  CHECK(w.catcher.engine.linked());
  CHECK(w.coach.engine.peer(pc::kUnitCatcher).ready);
  w.advance(6000);
  CHECK(w.catcher.engine.linked());
  CHECK(w.coach.engine.peer(pc::kUnitPitcher).ready);
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 1, w.now) == pc::Submit::Accepted);
  w.advance(1200);
  CHECK(w.pitcher.presents >= 1);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
}

// Link-local IPv6 derivation: fe80::/64 plus the EUI-64 with the U/L bit of
// the first byte flipped.
void testAddrLinkLocal() {
  uint8_t out[16];
  // 00:11:22:33:44:55:66:77 -> fe80::0211:2233:4455:6677
  const uint8_t eui[8] = {0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77};
  const uint8_t want[16] = {0xfe, 0x80, 0, 0, 0, 0, 0, 0,
                            0x02, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77};
  pc_link_local_from_eui(eui, out);
  CHECK(std::memcmp(out, want, sizeof(want)) == 0);
  CHECK(out[0] == 0xfe && out[1] == 0x80);
  CHECK((out[8] & 0x02u) != 0);  // U/L flipped from 0 to 1
  // All-zero -> fe80::0200:0000:0000:0000
  const uint8_t zero[8] = {};
  const uint8_t wantZero[16] = {0xfe, 0x80, 0, 0, 0, 0, 0, 0,
                                0x02, 0, 0, 0, 0, 0, 0, 0};
  pc_link_local_from_eui(zero, out);
  CHECK(std::memcmp(out, wantZero, sizeof(wantZero)) == 0);
  CHECK(out[0] == 0xfe && out[1] == 0x80);
  CHECK((out[8] & 0x02u) != 0);
  // All-FF -> fe80::fdff:ffff:ffff:ffff (flipping clears the U/L bit).
  uint8_t allFf[8];
  std::memset(allFf, 0xFF, sizeof(allFf));
  const uint8_t wantFf[16] = {0xfe, 0x80, 0, 0, 0, 0, 0, 0,
                              0xfd, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
  pc_link_local_from_eui(allFf, out);
  CHECK(std::memcmp(out, wantFf, sizeof(wantFf)) == 0);
  CHECK(out[0] == 0xfe && out[1] == 0x80);
  CHECK(out[8] == 0xfd && (out[8] & 0x02u) == 0);
  // Every first byte: zero interface ID prefix, flipped U/L bit, copied tail.
  bool allOk = true;
  for (unsigned first = 0; first < 256; ++first) {
    uint8_t probe[8] = {uint8_t(first), 1, 2, 3, 4, 5, 6, 7};
    pc_link_local_from_eui(probe, out);
    if (out[0] != 0xfe || out[1] != 0x80) allOk = false;
    for (unsigned i = 2; i < 8; ++i) {
      if (out[i] != 0) allOk = false;
    }
    if (out[8] != uint8_t(first ^ 0x02u)) allOk = false;
    for (unsigned i = 1; i < 8; ++i) {
      if (out[8 + i] != probe[i]) allOk = false;
    }
  }
  CHECK(allOk);
}

// The full handshake completes under 30 percent loss plus seeded jitter and
// reordering, within a bounded number of simulated steps.
void testLossyHandshakeBounded() {
  World w;
  w.bus.reseed(0x10CC1E55u);
  w.bus.setFaults(30, 25, 4, 30);
  const int kMaxSteps = 4000;  // 40 s of simulated time
  bool linked = false;
  int steps = 0;
  for (; steps < kMaxSteps; ++steps) {
    w.now += 10;
    w.tick();
    linked = w.catcher.engine.linked() && w.pitcher.engine.linked() &&
             w.shortstop.engine.linked() && w.center.engine.linked() &&
             w.coach.engine.peer(pc::kUnitCatcher).ready &&
             w.coach.engine.peer(pc::kUnitPitcher).ready &&
             w.coach.engine.peer(pc::kUnitShortstop).ready &&
             w.coach.engine.peer(pc::kUnitCenter).ready;
    if (linked) break;
  }
  CHECK(linked);
  CHECK(steps < kMaxSteps);
  CHECK(steps < 3000);  // linked comfortably inside the 30 s budget
  CHECK(w.bus.offered() > 0 && w.bus.dropped() > 0);
  CHECK(w.bus.reordered() > 0);  // the reorder fault actually fired
}

// Under loss the coach retransmits a pending call until every recipient ACKs;
// all deliveries settle inside the call window and at least one retry happens.
void testLossyCallRetries() {
  World w;
  w.linkAll();
  w.bus.reseed(0x5EEDCA11u);
  w.bus.setFaults(30);
  w.coach.log.clear();
  const uint32_t submittedAt = w.now;
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 21, w.now) == pc::Submit::Accepted);
  const int kMaxSteps = 200;  // 2 s: the call window plus margin
  int steps = 0;
  while ((w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Pending ||
          w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Pending) &&
         steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(pc::elapsed(w.now, submittedAt) <= pc::kCallWindow);
  CHECK(w.catcher.presents >= 1 && w.pitcher.presents >= 1);
  CHECK(pc::elapsed(w.catcher.last.receivedAt, submittedAt) <= pc::kCallWindow);
  CHECK(pc::elapsed(w.pitcher.last.receivedAt, submittedAt) <= pc::kCallWindow);
  const int calls = countSent(w.coach.log, pc::Kind::Call, pc::kUnitCatcher) +
                    countSent(w.coach.log, pc::Kind::Call, pc::kUnitPitcher);
  CHECK(w.bus.dropped() > 0);
  CHECK(calls > 2);  // lost attempts were retransmitted
}

// A valid ACK delayed past the delivery deadline must leave the call Missing;
// when it finally lands it cannot revive the recorded delivery.
void testDelayedAckStaysMissing() {
  World w;
  w.linkAll();
  w.bus.delayFrom(pc::kUnitPitcher, pc::kCallWindow + 300);
  const int presentsBefore = w.pitcher.presents;
  w.pitcher.log.clear();
  w.coach.log.clear();
  const uint32_t submittedAt = w.now;
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 22, w.now) == pc::Submit::Accepted);
  const int kMaxSteps = 180;  // 1.8 s: window close plus the delayed ACK
  int steps = 0;
  while (pc::elapsed(w.now, submittedAt) < pc::kCallWindow + 500 && steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(pc::elapsed(w.now, submittedAt) >= pc::kCallWindow + 300);
  CHECK(w.pitcher.presents == presentsBefore + 1);  // retries deduplicated
  const pc::Packet ack = findLast(w.pitcher.log, pc::Kind::Ack);
  CHECK(ack.kind == pc::Kind::Ack && ack.status == pc::Status::Ok);
  CHECK(ack.sequence == w.coach.engine.record(pc::Category::Pitch).output.sequence);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Missing);
  CHECK(w.coach.engine.record(pc::Category::Pitch).delivery[uint8_t(pc::kUnitPitcher)] ==
        pc::Delivery::Missing);
  CHECK(countSent(w.coach.log, pc::Kind::Call, pc::kUnitPitcher) >= 2);
}

// Reordering makes the newer call arrive first; the late older call is stale,
// and a later duplicate of the retained call is re-ACKed without replay.
void testReorderedDuplicates() {
  World w;
  w.linkAll();
  const int presentsBefore = w.pitcher.presents;
  pc::Packet older = makeCall(w, pc::kUnitPitcher, 100, 1);
  pc::Packet newer = makeCall(w, pc::kUnitPitcher, 101, 2);
  w.bus.post(older, w.now, 200);  // held back on the wire
  w.bus.post(newer, w.now, 20);   // overtakes it
  w.pitcher.log.clear();
  w.advance(400);
  CHECK(w.pitcher.presents == presentsBefore + 1);
  CHECK(w.pitcher.last.code == 2);
  CHECK(w.pitcher.engine.output().sequence == 101);
  CHECK(countKind(w.pitcher.log, pc::Kind::Ack) >= 1);
  // Silence the retained call's ACK retransmits, then replay the stale older
  // call: it must be dropped without an ACK or a replay.
  w.advance(1200);
  older = makeCall(w, pc::kUnitPitcher, 100, 1);
  w.pitcher.log.clear();
  w.bus.post(older, w.now, 0);
  w.advance(50);
  CHECK(w.pitcher.presents == presentsBefore + 1);
  CHECK(countKind(w.pitcher.log, pc::Kind::Ack) == 0);
  // A duplicate of the retained call is ACKed again, never presented again.
  newer = makeCall(w, pc::kUnitPitcher, 101, 2);
  w.pitcher.log.clear();
  w.bus.post(newer, w.now, 0);
  w.advance(50);
  CHECK(w.pitcher.presents == presentsBefore + 1);
  const pc::Packet ack = findLast(w.pitcher.log, pc::Kind::Ack);
  CHECK(ack.kind == pc::Kind::Ack && ack.sequence == 101 && ack.status == pc::Status::Ok);
  CHECK(w.ticks < 1000);  // fixed-step scenario, bounded by construction
}

// A catcher request retransmitted under loss still completes with the coach's
// saved response and delivers the resulting call.
void testCatcherRequestRetriesUnderLoss() {
  World w;
  w.linkAll();
  w.bus.reseed(0x0BADCAFEu);
  w.bus.setFaults(30);
  w.catcher.log.clear();
  const int pitcherBefore = w.pitcher.presents;
  CHECK(w.catcher.engine.submit(pc::Category::Pitch, 14, w.now) == pc::Submit::Accepted);
  const int kMaxSteps = 400;  // 4 s
  int steps = 0;
  while (!(w.catcher.engine.requestFinished() && !w.coach.engine.busy() &&
           w.pitcher.presents > pitcherBefore) &&
         steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(w.bus.dropped() > 0);
  CHECK(w.catcher.engine.requestFinished());
  CHECK(w.catcher.engine.requestResult() == pc::Status::Ok);
  CHECK(w.catcher.engine.hasOutput());
  CHECK(w.catcher.engine.output().code == 14);
  CHECK(w.pitcher.presents > pitcherBefore);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(countKind(w.catcher.log, pc::Kind::Request) >= 2);  // retried
}

// One world with all five engines: every field pinging, a pitch and a play,
// seeded jitter/reorder, and a 32-bit clock wrap. The coach's one-reply-per-
// tick control queue must be fair, both calls must land inside kCallWindow,
// and every delivery must settle.
void testMultiNodeLoadAndFairness() {
  World w;
  w.now = 0xFFFFF800u;  // 2 s before wrap; linkAll() crosses it
  w.bus.reseed(0xF41E5EEDu);
  w.bus.setFaults(0, 40, 6, 30);
  w.linkAll();
  CHECK(pc::elapsed(w.now, 0xFFFFF800u) >= 4000u);  // crossed the rollover
  CHECK(w.catcher.engine.linked() && w.pitcher.engine.linked() &&
        w.shortstop.engine.linked() && w.center.engine.linked());
  // Let the Ready/Pong exchanges settle before counting heartbeat replies.
  w.advance(1000);
  w.coach.log.clear();
  w.catcher.log.clear();
  w.pitcher.log.clear();
  w.shortstop.log.clear();
  w.center.log.clear();

  const uint32_t runStart = w.now;
  const int kMaxSteps = 1600;  // 16 s cap; the run target is 12 s
  int steps = 0;
  while (pc::elapsed(w.now, runStart) < 1000 && steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);

  // Pitch to the catcher and the pitcher.
  const uint32_t pitchAt = w.now;
  CHECK(w.coach.engine.submit(pc::Category::Pitch, 5, w.now) == pc::Submit::Accepted);
  while ((w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Pending ||
          w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Pending) &&
         steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(pc::elapsed(w.now, pitchAt) <= pc::kCallWindow);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(pc::elapsed(w.catcher.last.receivedAt, pitchAt) <= pc::kCallWindow);
  CHECK(pc::elapsed(w.pitcher.last.receivedAt, pitchAt) <= pc::kCallWindow);
  CHECK(w.catcher.last.code == 5 && w.pitcher.last.code == 5);

  // A short gap, then a team play (BUNT DEF) to every field unit.
  while ((w.coach.engine.busy() || pc::elapsed(w.now, pitchAt) < 1500) &&
         steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  const uint32_t playAt = w.now;
  CHECK(w.coach.engine.submit(pc::Category::Play, 13, w.now) == pc::Submit::Accepted);
  while ((w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Pending ||
          w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Pending ||
          w.coach.engine.delivery(pc::kUnitShortstop) == pc::Delivery::Pending ||
          w.coach.engine.delivery(pc::kUnitCenter) == pc::Delivery::Pending) &&
         steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(pc::elapsed(w.now, playAt) <= pc::kCallWindow);
  CHECK(w.coach.engine.delivery(pc::kUnitPitcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitCatcher) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitShortstop) == pc::Delivery::Delivered);
  CHECK(w.coach.engine.delivery(pc::kUnitCenter) == pc::Delivery::Delivered);
  CHECK(pc::elapsed(w.pitcher.last.receivedAt, playAt) <= pc::kCallWindow);
  CHECK(pc::elapsed(w.catcher.last.receivedAt, playAt) <= pc::kCallWindow);
  CHECK(pc::elapsed(w.shortstop.last.receivedAt, playAt) <= pc::kCallWindow);
  CHECK(pc::elapsed(w.center.last.receivedAt, playAt) <= pc::kCallWindow);
  CHECK(w.pitcher.last.code == 13 && w.catcher.last.code == 13);
  CHECK(w.shortstop.last.code == 13 && w.center.last.code == 13);

  // Keep running so every peer accumulates heartbeat rounds.
  while (pc::elapsed(w.now, runStart) < 12000 && steps < kMaxSteps) {
    w.now += 10;
    w.tick();
    ++steps;
  }
  CHECK(steps < kMaxSteps);
  CHECK(pc::elapsed(w.now, runStart) >= 12000u);

  // Every ping got exactly one Pong and no peer was starved.
  const EngineUnderTest* fields[pc::kUnitCount] = {nullptr, &w.pitcher, &w.catcher,
                                              &w.shortstop, &w.center};
  int pings[pc::kUnitCount] = {};
  int pongs[pc::kUnitCount] = {};
  int minPongs = 0, maxPongs = 0;
  for (unsigned r = 1; r < pc::kUnitCount; ++r) {
    pings[r] = countKind(fields[r]->log, pc::Kind::Ping);
    pongs[r] = countSent(w.coach.log, pc::Kind::Pong, pc::Role(r));
    CHECK(pings[r] >= 8);
    CHECK(pongs[r] == pings[r]);
    if (r == 1 || pongs[r] < minPongs) minPongs = pongs[r];
    if (r == 1 || pongs[r] > maxPongs) maxPongs = pongs[r];
  }
  CHECK(maxPongs - minPongs <= 1);

  // Both calls are recorded with settled delivery statuses.
  CHECK(w.coach.engine.record(pc::Category::Pitch).delivery[uint8_t(pc::kUnitCatcher)] ==
        pc::Delivery::Delivered);
  CHECK(w.coach.engine.record(pc::Category::Pitch).delivery[uint8_t(pc::kUnitPitcher)] ==
        pc::Delivery::Delivered);
  CHECK(w.coach.engine.record(pc::Category::Play).delivery[uint8_t(pc::kUnitPitcher)] ==
        pc::Delivery::Delivered);
  CHECK(w.coach.engine.record(pc::Category::Play).delivery[uint8_t(pc::kUnitCatcher)] ==
        pc::Delivery::Delivered);
  CHECK(w.coach.engine.record(pc::Category::Play).delivery[uint8_t(pc::kUnitShortstop)] ==
        pc::Delivery::Delivered);
  CHECK(w.coach.engine.record(pc::Category::Play).delivery[uint8_t(pc::kUnitCenter)] ==
        pc::Delivery::Delivered);
  for (unsigned r = 1; r < pc::kUnitCount; ++r) {
    const pc::Delivery d = w.coach.engine.delivery(pc::Role(r));
    CHECK(d == pc::Delivery::Delivered || d == pc::Delivery::Unused);
  }
}

void testEngineDefaults() {
  Bus bus;
  EngineUnderTest e(pc::kUnitCatcher, 0, &bus);
  CHECK(e.engine.boot() == 1);  // boot 0 is replaced so tokens stay nonzero
  CHECK(!e.engine.linked());
  CHECK(!e.engine.busy());
  CHECK(!e.engine.hasOutput());
  CHECK(e.engine.role() == pc::kUnitCatcher);
  EngineUnderTest coach(pc::kCoach, 0x10, &bus);
  CHECK(coach.engine.linked());  // the coach is the coordinator
  CHECK(coach.engine.session() == 0x10);
  CHECK(coach.engine.boot() == 0x10);
}

void testUsbGate() {
  pc::UsbGate gate(pc::kCoach);
  CHECK(gate.execute(pc::UsbCall{}, 1, 1, 0, [] { return pc::UsbResult{}; }).result == pc::Submit::Invalid);
  gate.begin(0x12345678);
  pc::UsbCall call;
  call.client = 0x12345678;
  call.id = 7;
  call.dictionary = 0x5a5a5a5a;
  call.boot = 0xabc;
  call.deadline = 1000;
  call.category = pc::Category::Pitch;
  call.code = uint16_t(pc::kPitchCount * pc::kRows * pc::kCols);
  int submissions = 0;
  const auto run = [&] {
    return gate.execute(call, 0xabc, 0x5a5a5a5a, 500, [&] {
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
  CHECK(gate.execute(other, 0xabc, 0x5a5a5a5a, 500, [&] {
    return pc::UsbResult{pc::Submit::Accepted, 12};
  }).result == pc::Submit::Incompatible);
  pc::UsbCall stale = call;
  stale.id = 9;
  stale.deadline = 4000;
  CHECK(gate.execute(stale, 0xabc, 0x5a5a5a5a, 500, [&] {
    return pc::UsbResult{pc::Submit::Accepted, 13};
  }).result == pc::Submit::Expired);
}

void testUsbGateEdges() {
  pc::UsbCall call;
  call.client = 0xCAFE;
  call.id = 7;
  call.dictionary = pc::kDictionary;
  call.boot = 1;
  call.deadline = 500;
  call.category = pc::Category::Pitch;
  call.code = 1;
  // The catcher has a keypad, not USB calling rights.
  pc::UsbGate catcherGate(pc::kUnitCatcher);
  CHECK(catcherGate.execute(call, 1, pc::kDictionary, 0,
                            [] { return pc::UsbResult{pc::Submit::Accepted, 1}; }).result ==
        pc::Submit::Invalid);
  pc::UsbGate gate(pc::kCoach);
  CHECK(gate.client() == 0);
  gate.begin(0);
  CHECK(gate.client() == 0);
  int submits = 0;
  int nextSequence = 0;
  const auto submit = [&] {
    ++submits;
    return pc::UsbResult{pc::Submit::Accepted, uint32_t(++nextSequence)};
  };
  // Commands before begin() are refused.
  CHECK(gate.execute(call, 1, pc::kDictionary, 0, submit).result == pc::Submit::Invalid);
  gate.begin(0xCAFE);
  CHECK(gate.client() == 0xCAFE);
  // A different client cannot reuse the gate.
  pc::UsbCall otherClient = call;
  otherClient.client = 0xBEEF;
  CHECK(gate.execute(otherClient, 1, pc::kDictionary, 0, submit).result == pc::Submit::Invalid);
  CHECK(submits == 0);
  // Boot mismatch (id 7).
  CHECK(gate.execute(call, 2, pc::kDictionary, 0, submit).result == pc::Submit::Incompatible);
  // Dictionary mismatch (id 8).
  pc::UsbCall badDict = call;
  badDict.id = 8;
  CHECK(gate.execute(badDict, 1, pc::kDictionary ^ 1, 0, submit).result == pc::Submit::Incompatible);
  // Deadline exactly now (id 9).
  pc::UsbCall expired = call;
  expired.id = 9;
  expired.deadline = 500;
  CHECK(gate.execute(expired, 1, pc::kDictionary, 500, submit).result == pc::Submit::Expired);
  // Deadline beyond the grant (id 10).
  pc::UsbCall tooFar = call;
  tooFar.id = 10;
  tooFar.deadline = 500 + pc::kUsbGrant + 1;
  CHECK(gate.execute(tooFar, 1, pc::kDictionary, 500, submit).result == pc::Submit::Expired);
  CHECK(submits == 0);
  // First accepted command (id 11; a full grant is allowed).
  pc::UsbCall good = call;
  good.id = 11;
  good.deadline = 500 + pc::kUsbGrant;
  const auto first = gate.execute(good, 1, pc::kDictionary, 500, submit);
  CHECK(first.result == pc::Submit::Accepted && first.sequence == 1);
  CHECK(submits == 1);
  // Exact retry returns the saved result without resubmitting.
  const auto retry = gate.execute(good, 1, pc::kDictionary, 900, submit);
  CHECK(retry.result == pc::Submit::Accepted && retry.sequence == 1);
  CHECK(submits == 1);
  // Same id with any different field is not a retry.
  pc::UsbCall altered = good;
  altered.code = 2;
  CHECK(gate.execute(altered, 1, pc::kDictionary, 500, submit).result == pc::Submit::Invalid);
  pc::UsbCall alteredDeadline = good;
  alteredDeadline.deadline = 2001;
  CHECK(gate.execute(alteredDeadline, 1, pc::kDictionary, 500, submit).result == pc::Submit::Invalid);
  CHECK(submits == 1);
  // Older ids are rejected (10 < 11).
  pc::UsbCall older = good;
  older.id = 10;
  CHECK(gate.execute(older, 1, pc::kDictionary, 500, submit).result == pc::Submit::Invalid);
  CHECK(submits == 1);
  // A new id runs and advances the saved command (id 12).
  pc::UsbCall newer = good;
  newer.id = 12;
  newer.code = 3;
  const auto second = gate.execute(newer, 1, pc::kDictionary, 500, submit);
  CHECK(second.result == pc::Submit::Accepted && second.sequence == 2);
  CHECK(submits == 2);
  // Busy results are remembered by retry too (id 99).
  const auto busy = [&] {
    ++submits;
    return pc::UsbResult{pc::Submit::Busy, 0};
  };
  pc::UsbCall busyCall = good;
  busyCall.id = 99;
  busyCall.deadline = 1500;
  CHECK(gate.execute(busyCall, 1, pc::kDictionary, 500, busy).result == pc::Submit::Busy);
  CHECK(gate.execute(busyCall, 1, pc::kDictionary, 900, busy).result == pc::Submit::Busy);
  CHECK(submits == 3);
  // begin() with the same client keeps the saved command; a new client clears it.
  gate.begin(0xCAFE);
  CHECK(gate.client() == 0xCAFE);
  pc::UsbCall replay = good;  // id 11, older than the last saved id 99
  CHECK(gate.execute(replay, 1, pc::kDictionary, 500, submit).result == pc::Submit::Invalid);
  gate.begin(0xF00D);
  CHECK(gate.client() == 0xF00D);
  pc::UsbCall fresh = good;
  fresh.client = 0xF00D;
  fresh.id = 7;
  fresh.deadline = 1500;
  const auto third = gate.execute(fresh, 1, pc::kDictionary, 500, submit);
  CHECK(third.result == pc::Submit::Accepted && third.sequence == 3);
  CHECK(submits == 4);
}

void testUsbParsing() {
  pc::UsbCall call;
  char pitchLine[96];
  std::snprintf(pitchLine, sizeof(pitchLine),
                "call 3f2a1b0c 7 p 2 %u %u abcdef0123456789 5a5a5a5a 99", pc::kRows, pc::kCols);
  CHECK(pc::parseUsbCall(pitchLine, call));
  CHECK(call.client == 0x3f2a1b0c && call.id == 7 && call.category == pc::Category::Pitch);
  CHECK(call.code == pc::pitchCode(2, pc::kRows, pc::kCols));
  CHECK(pc::parseUsbCall("call 3f2a1b0c 7 d 5 abcdef0123456789 5a5a5a5a 99", call));
  CHECK(call.category == pc::Category::Play && call.code == 5);
  CHECK(!pc::parseUsbCall("call 0 7 p 2 3 1 abcdef0123456789 5a5a5a5a 99", call));
  CHECK(!pc::parseUsbCall("call 3f2a1b0c 0 p 2 3 1 abcdef0123456789 5a5a5a5a 99", call));
  std::snprintf(pitchLine, sizeof(pitchLine),
                "call 3f2a1b0c 7 p 2 %u 1 abcdef0123456789 5a5a5a5a 99", pc::kRows + 1);
  CHECK(!pc::parseUsbCall(pitchLine, call));
  uint32_t client = 0;
  CHECK(pc::parseGuiClient("gui 1234abcd", client) && client == 0x1234abcd);
  CHECK(!pc::parseGuiClient("gui 1234abc", client));
  CHECK(!pc::parseGuiClient("gui 00000000", client));
}

void testUsbParsingEdges() {
  pc::UsbCall call;
  // Boundaries and exact field widths.
  CHECK(pc::parseUsbCall("call 00000001 1 p 1 1 1 0000000000000001 00000001 1", call));
  CHECK(call.client == 1 && call.id == 1 && call.category == pc::Category::Pitch);
  CHECK(call.code == pc::pitchCode(1, 1, 1));
  CHECK(call.boot == 1 && call.dictionary == 1 && call.deadline == 1);
  // Uppercase hex, the last catalog play, and maximum deadline.
  char line[96];
  std::snprintf(line, sizeof(line),
                "call ABCDEF01 2 d %u 0011223344556677 5A5A5A5A 4294967295", pc::kPlayCount);
  CHECK(pc::parseUsbCall(line, call));
  CHECK(call.client == 0xABCDEF01u && call.code == pc::kPlayCount);
  CHECK(call.boot == 0x0011223344556677ULL && call.dictionary == 0x5A5A5A5A);
  CHECK(call.deadline == 4294967295u);
  // A zero dictionary parses; only code and boot must be nonzero.
  CHECK(pc::parseUsbCall("call 00000001 1 p 1 1 1 0000000000000001 00000000 1", call));
  CHECK(call.dictionary == 0);
  // Rejections.
  CHECK(!pc::parseUsbCall("", call));
  CHECK(!pc::parseUsbCall("call", call));
  CHECK(!pc::parseUsbCall("call ", call));
  CHECK(!pc::parseUsbCall("CALL 12345678 1 p 1 1 1 01 1 1", call));
  CHECK(!pc::parseUsbCall("guid 12345678 1 p 1 1 1 01 1 1", call));
  CHECK(!pc::parseUsbCall("call 1234567 1 p 1 1 1 01 1 1", call));      // short client
  CHECK(!pc::parseUsbCall("call 00000000 1 p 1 1 1 01 1 1", call));     // zero client
  CHECK(!pc::parseUsbCall("call 12345678 0 p 1 1 1 01 1 1", call));     // zero id
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 00 1 1", call));     // zero boot
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 01 1 1", call));     // short boot
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 01 1", call));       // no deadline
  std::snprintf(line, sizeof(line), "call 12345678 1 p %u 1 1 01 1 1", pc::kPitchCount + 1);
  CHECK(!pc::parseUsbCall(line, call));                                 // pitch above catalog
  std::snprintf(line, sizeof(line), "call 12345678 1 p 1 %u 1 01 1 1", pc::kRows + 1);
  CHECK(!pc::parseUsbCall(line, call));                                 // row above catalog
  std::snprintf(line, sizeof(line), "call 12345678 1 p 1 1 %u 01 1 1", pc::kCols + 1);
  CHECK(!pc::parseUsbCall(line, call));                                 // col above catalog
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 0 01 1 1", call));     // side 0
  CHECK(!pc::parseUsbCall("call 12345678 1 d 0 01 1 1", call));         // play 0
  std::snprintf(line, sizeof(line), "call 12345678 1 d %u 01 1 1", pc::kPlayCount + 1);
  CHECK(!pc::parseUsbCall(line, call));                                 // play above catalog
  CHECK(!pc::parseUsbCall("call 12345678 1 x 1 01 1 1", call));         // bad category
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 01 1 1 ", call));    // trailing space
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 01 1 1x", call));    // trailing junk
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 01 1 4294967296", call));  // overflow
  CHECK(!pc::parseUsbCall("call 12345678 4294967296 p 1 1 1 01 1 1", call));  // id overflow
  CHECK(!pc::parseUsbCall("call 12345678 1 p 1 1 1 g1 1 1", call));     // bad hex
  // A failed parse leaves the caller's value alone.
  pc::UsbCall untouched;
  untouched.id = 77;
  CHECK(!pc::parseUsbCall("nope", untouched));
  CHECK(untouched.id == 77);
  // GUI client parsing.
  uint32_t client = 0;
  CHECK(pc::parseGuiClient("gui ABCDEF01", client) && client == 0xABCDEF01u);
  CHECK(pc::parseGuiClient("gui 00000001", client) && client == 1);
  CHECK(!pc::parseGuiClient("gui 00000000", client));
  CHECK(!pc::parseGuiClient("gui 0000000g", client));
  CHECK(!pc::parseGuiClient("gui 123456789", client));
  CHECK(!pc::parseGuiClient("gui 12345678 ", client));
  CHECK(!pc::parseGuiClient("gui 12345678x", client));
  CHECK(!pc::parseGuiClient("guid 12345678", client));
  CHECK(!pc::parseGuiClient("", client));
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

  // Choose pitch 1 -> row 1 -> col 1 -> Send.
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
  // A rejected or expired request re-arms the draft at the Location screen.
  menu.restore(pc::pitchCode(3, pc::kRows, pc::kCols));
  CHECK(menu.draft());
  CHECK(menu.screen() == pc::CatcherMenu::Screen::Location);
  CHECK(menu.code() == pc::pitchCode(3, pc::kRows, pc::kCols));
  CHECK(menu.front(4) == pc::CatcherMenu::Action::Send);
  menu.accepted();
  menu.restore(0);
  CHECK(!menu.draft());
}

// Every navigation path, page wrap, frame text and restore() edge case.
void testCatcherMenuNavigation() {
  pc::CatcherMenu menu;
  CHECK(menu.screen() == MenuScreen::Pitches && menu.page() == 0);
  CHECK(menu.pitch() == 0 && menu.height() == 0 && menu.location() == 0);
  CHECK(!menu.draft() && menu.code() == 0);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.header) ==
          "PITCHES 1/" + std::to_string(pc::CatcherMenu::kPitchPages));
    CHECK(std::string(f.footer) == "Back recall; hold vol");
    CHECK(std::string(f.rows[0]) == "1 4S   2 CB");
    CHECK(std::string(f.rows[1]) == "3 SL   4 Next");
  }
  CHECK(menu.front(0) == MenuAction::None);
  CHECK(menu.front(5) == MenuAction::None);
  // Paging forward wraps 0 -> 1 -> 2 -> 0 and starts a draft.
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.page() == 1 && menu.draft());
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.page() == 2);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.header) ==
          "PITCHES 3/" + std::to_string(pc::CatcherMenu::kPitchPages));
    CHECK(std::string(f.rows[0]) == "1 CT   2 SW");
    CHECK(std::string(f.rows[1]) == "3 SP   4 Next");
    CHECK(std::string(f.footer) == "Hold Back: cancel");
  }
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.page() == 0);
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.page() == 2);
  // Page 3, second pitch (SWEEPER, code 8): row and col still unset.
  CHECK(menu.front(2) == MenuAction::None);
  CHECK(menu.pitch() == 8 && menu.screen() == MenuScreen::Height);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.header) == "SW HEIGHT");
    CHECK(std::string(f.footer) == "Choose height; Back");
    CHECK(std::string(f.rows[0]) == "1 HI   2 MID");
    CHECK(std::string(f.rows[1]) == "3 LO   4 --");
  }
  CHECK(menu.front(4) == MenuAction::None);  // no height yet, Confirm ignored
  CHECK(menu.screen() == MenuScreen::Height);
  CHECK(menu.front(3) == MenuAction::None);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.footer) == "Back; hold: cancel");
    CHECK(std::string(f.rows[1]) == "3>LO   4 Confirm");
  }
  CHECK(menu.front(4) == MenuAction::None);  // Confirm -> Location
  CHECK(menu.screen() == MenuScreen::Location);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.header) == "SW LO --");
    CHECK(std::string(f.footer) == "Choose side; Back");
    CHECK(std::string(f.rows[1]) == "3 OUT  4 --");
  }
  CHECK(menu.front(4) == MenuAction::None);  // no side yet, Send ignored
  CHECK(menu.screen() == MenuScreen::Location);
  CHECK(menu.front(1) == MenuAction::None);
  {
    const auto f = menu.frame();
    CHECK(std::string(f.header) == "SW LO IN");
    CHECK(std::string(f.rows[0]) == "1>IN   2 MID");
    CHECK(std::string(f.rows[1]) == "3 OUT  4 Send");
  }
  CHECK(menu.code() == pc::pitchCode(8, pc::kRows, 1));
  CHECK(menu.front(4) == MenuAction::Send);
  menu.accepted();
  CHECK(!menu.draft() && menu.screen() == MenuScreen::Pitches);
  CHECK(menu.pitch() == 0 && menu.page() == 2);  // page persists after a send
  // Back walks Location -> Height -> Pitches; short Back never cancels.
  CHECK(menu.front(1) == MenuAction::None);  // pitch 7 (CUTTER)
  CHECK(menu.front(2) == MenuAction::None);
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.front(3) == MenuAction::None);
  CHECK(menu.code() == pc::pitchCode(7, 2, pc::kCols));
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.screen() == MenuScreen::Height && menu.location() == pc::kCols);
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.screen() == MenuScreen::Pitches && menu.page() == 2);
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.draft());
  CHECK(menu.back(true) == MenuAction::Cancel);
  CHECK(!menu.draft() && menu.screen() == MenuScreen::Pitches && menu.page() == 2);
  CHECK(menu.back(false) == MenuAction::Recall);
  CHECK(menu.back(true) == MenuAction::Volume);
  // Choosing the same pitch keeps the axes; a different pitch resets them.
  menu.restore(pc::pitchCode(7, 2, pc::kCols));
  CHECK(menu.screen() == MenuScreen::Location && menu.page() == 2);
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.page() == 2 && menu.pitch() == 7);
  CHECK(menu.front(1) == MenuAction::None);
  CHECK(menu.height() == 2 && menu.location() == pc::kCols);
  CHECK(menu.screen() == MenuScreen::Height);
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.front(2) == MenuAction::None);  // pitch 8 differs
  CHECK(menu.pitch() == 8 && menu.height() == 0 && menu.location() == 0);
  // Same height keeps the side; a different height clears it.
  menu.restore(pc::pitchCode(7, 2, pc::kCols));
  CHECK(menu.back(false) == MenuAction::None);
  CHECK(menu.front(2) == MenuAction::None);
  CHECK(menu.height() == 2 && menu.location() == pc::kCols);
  CHECK(menu.front(pc::kRows) == MenuAction::None);
  CHECK(menu.height() == pc::kRows && menu.location() == 0);
  CHECK(menu.front(4) == MenuAction::None);
  CHECK(menu.screen() == MenuScreen::Location);
  CHECK(menu.front(4) == MenuAction::None);  // still no side
  CHECK(menu.code() == 0);
  // restore() ignores 0 and out-of-range codes.
  constexpr unsigned kPitchCodes = pc::kPitchCount * pc::kRows * pc::kCols;
  menu.restore(0);
  CHECK(menu.draft() && menu.screen() == MenuScreen::Location);
  CHECK(menu.pitch() == 7 && menu.height() == pc::kRows && menu.location() == 0);
  menu.restore(uint16_t(kPitchCodes + 1));
  CHECK(menu.pitch() == 7 && menu.height() == pc::kRows && menu.location() == 0);
  menu.restore(uint16_t(kPitchCodes));
  CHECK(menu.pitch() == pc::kPitchCount && menu.height() == pc::kRows &&
        menu.location() == pc::kCols && menu.page() == pc::CatcherMenu::kPitchPages - 1);
  CHECK(menu.code() == kPitchCodes);
  menu.restore(1);
  CHECK(menu.pitch() == 1 && menu.height() == 1 && menu.location() == 1 && menu.page() == 0);
  CHECK(menu.screen() == MenuScreen::Location && menu.draft());
  menu.cancel();
  CHECK(!menu.draft() && menu.screen() == MenuScreen::Pitches && menu.pitch() == 0);
  CHECK(menu.code() == 0);
}

void testCatcherMenuCommit() {
  pc::CatcherMenu menu;
  int calls = 0;
  uint16_t seen = 0;
  const auto submitOk = [&](uint16_t code) {
    ++calls;
    seen = code;
    return true;
  };
  const auto submitNo = [&](uint16_t code) {
    ++calls;
    seen = code;
    return false;
  };
  CHECK(!menu.commit(true, true, true, submitOk));  // nothing selected yet
  CHECK(calls == 0);
  menu.restore(pc::pitchCode(2, 1, 3));
  CHECK(!menu.commit(false, true, true, submitOk));
  CHECK(!menu.commit(true, false, true, submitOk));
  CHECK(!menu.commit(true, true, false, submitOk));
  CHECK(calls == 0);
  CHECK(menu.draft() && menu.screen() == MenuScreen::Location);
  CHECK(menu.commit(true, true, true, submitOk));
  CHECK(calls == 1 && seen == pc::pitchCode(2, 1, 3));
  CHECK(!menu.draft());
  // A rejected submit keeps the draft for a retry.
  menu.restore(pc::pitchCode(3, 2, 2));
  CHECK(!menu.commit(true, true, true, submitNo));
  CHECK(calls == 2 && seen == pc::pitchCode(3, 2, 2));
  CHECK(menu.draft() && menu.screen() == MenuScreen::Location);
  CHECK(menu.code() == pc::pitchCode(3, 2, 2));
  CHECK(menu.commit(true, true, true, submitOk));
  CHECK(calls == 3 && !menu.draft());
  CHECK(!menu.commit(true, true, true, submitOk));  // nothing left to send
  CHECK(calls == 3);
}

// Timing paths: glitch presses, chords, direct switches, long hold, faults.
void testCatcherButtonsDetailed() {
  pc::CatcherButtons f;
  // Startup block clears only after 35 ms with every switch released.
  CHECK(f.tick(0x00, true, 0) == 0);
  CHECK(f.tick(0x00, true, 34) == 0);
  CHECK(f.tick(0x00, true, 35) == 0);
  // Press accepted 35 ms after the raw change; release reports one later.
  CHECK(f.tick(0x01, true, 100) == 0);
  CHECK(f.tick(0x01, true, 134) == 0);
  CHECK(f.tick(0x01, true, 135) == 0);
  CHECK(f.tick(0x00, true, 200) == 0);
  CHECK(f.tick(0x00, true, 234) == 0);
  CHECK(f.tick(0x00, true, 235) == 1);
  // A press shorter than 35 ms is a glitch and reports nothing.
  CHECK(f.tick(0x02, true, 300) == 0);
  CHECK(f.tick(0x00, true, 320) == 0);
  CHECK(f.tick(0x00, true, 340) == 0);
  CHECK(f.tick(0x00, true, 400) == 0);
  // A transient chord during a hold blocks until 35 ms of full release.
  CHECK(f.tick(0x01, true, 500) == 0);
  CHECK(f.tick(0x01, true, 535) == 0);
  CHECK(f.tick(0x03, true, 600) == 0);
  CHECK(f.tick(0x00, true, 650) == 0);
  CHECK(f.tick(0x00, true, 684) == 0);
  CHECK(f.tick(0x00, true, 685) == 0);
  CHECK(f.tick(0x04, true, 700) == 0);
  CHECK(f.tick(0x04, true, 735) == 0);
  CHECK(f.tick(0x00, true, 800) == 0);
  CHECK(f.tick(0x00, true, 835) == 3);
  // Direct switch between two buttons without a release is a chord.
  CHECK(f.tick(0x01, true, 900) == 0);
  CHECK(f.tick(0x01, true, 935) == 0);
  CHECK(f.tick(0x02, true, 1000) == 0);
  CHECK(f.tick(0x02, true, 1035) == 0);  // blocked here
  CHECK(f.tick(0x02, true, 1100) == 0);
  CHECK(f.tick(0x00, true, 1150) == 0);
  CHECK(f.tick(0x00, true, 1185) == 0);
  CHECK(f.tick(0x01, true, 1200) == 0);
  CHECK(f.tick(0x01, true, 1235) == 0);
  CHECK(f.tick(0x00, true, 1300) == 0);
  CHECK(f.tick(0x00, true, 1335) == 1);
  // Back long press fires at 700 ms and suppresses the release event.
  CHECK(f.tick(0x10, true, 2000) == 0);
  CHECK(f.tick(0x10, true, 2035) == 0);
  CHECK(f.tick(0x10, true, 2734) == 0);
  CHECK(f.tick(0x10, true, 2735) == 6);
  CHECK(f.tick(0x10, true, 2900) == 0);
  CHECK(f.tick(0x00, true, 3000) == 0);
  CHECK(f.tick(0x00, true, 3035) == 0);
  // A fresh short Back press reports event 5.
  CHECK(f.tick(0x10, true, 3100) == 0);
  CHECK(f.tick(0x10, true, 3135) == 0);
  CHECK(f.tick(0x00, true, 3200) == 0);
  CHECK(f.tick(0x00, true, 3235) == 5);
  // Long hold of any other button does nothing extra.
  CHECK(f.tick(0x08, true, 4000) == 0);
  CHECK(f.tick(0x08, true, 4035) == 0);
  CHECK(f.tick(0x08, true, 4800) == 0);
  CHECK(f.tick(0x00, true, 4900) == 0);
  CHECK(f.tick(0x00, true, 4935) == 4);
  // An invalid sample blocks and drops the held press.
  CHECK(f.tick(0x01, true, 5000) == 0);
  CHECK(f.tick(0x01, true, 5035) == 0);
  CHECK(f.tick(0x01, false, 5100) == 0);
  CHECK(f.tick(0x01, true, 5200) == 0);
  CHECK(f.tick(0x00, true, 5240) == 0);
  CHECK(f.tick(0x00, true, 5275) == 0);
  CHECK(f.tick(0x01, true, 5300) == 0);
  CHECK(f.tick(0x01, true, 5335) == 0);
  CHECK(f.tick(0x00, true, 5400) == 0);
  CHECK(f.tick(0x00, true, 5435) == 1);
  // Bits above 0x1f are not buttons and are stripped.
  pc::CatcherButtons g;
  CHECK(g.tick(0x00, true, 0) == 0);
  CHECK(g.tick(0x00, true, 35) == 0);
  CHECK(g.tick(0x21, true, 100) == 0);
  CHECK(g.tick(0x21, true, 135) == 0);
  CHECK(g.tick(0x00, true, 200) == 0);
  CHECK(g.tick(0x00, true, 235) == 1);
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

// Exhaustive priority: USB setup > radio > dictionary > link > stale call >
// call > ready. Every one of the 64 input combinations is checked.
void testStripPriorityMatrix() {
  for (unsigned bits = 0; bits < 64; ++bits) {
    pc::StripState s;
    s.configured = (bits & 1) == 0;
    s.radio = (bits & 2) == 0;
    s.incompatible = (bits & 4) != 0;
    s.linked = (bits & 8) == 0;
    s.old = (bits & 16) != 0;
    s.hasCall = (bits & 32) != 0;
    const char* expected;
    if (!s.configured) expected = "USB SETUP";
    else if (!s.radio) expected = "RADIO ERR";
    else if (s.incompatible) expected = "DICT ERROR";
    else if (!s.linked) expected = "NO LINK";
    else if (s.old && s.hasCall) expected = "OLD";
    else if (s.hasCall) expected = "CALL";
    else expected = "READY";
    CHECK(std::strcmp(pc::stripStatus(s), expected) == 0);
  }
  // Stale without a call must not show OLD; a missing link outranks it.
  pc::StripState oldOnly;
  oldOnly.old = true;
  CHECK(std::strcmp(pc::stripStatus(oldOnly), "READY") == 0);
  pc::StripState legacy;
  legacy.old = true;
  legacy.hasCall = true;
  legacy.linked = false;
  CHECK(std::strcmp(pc::stripStatus(legacy), "NO LINK") == 0);
  pc::StripState noisy;
  noisy.incompatible = true;
  noisy.radio = false;
  CHECK(std::strcmp(pc::stripStatus(noisy), "RADIO ERR") == 0);
}

// Diagnostics scanner probes one address per tick, 1..126, then stops.
void testDiagnosticsScan() {
  pc::I2cScan scan;
  CHECK(!scan.active());
  CHECK(scan.start());
  CHECK(scan.active());
  CHECK(!scan.start());
  int probed = 0;
  uint8_t found = 0;
  for (int i = 0; i < 10; ++i) {
    const uint8_t result = scan.tick([&](uint8_t address) {
      ++probed;
      return address == 3;
    });
    if (result) found = result;
  }
  CHECK(probed == 10);
  CHECK(found == 3);
  while (scan.active()) {
    scan.tick([&](uint8_t) {
      ++probed;
      return false;
    });
  }
  CHECK(probed == 126);
  CHECK(scan.start());
  CHECK(scan.active());
}

}  // namespace

int main() {
  testProtocolRoundTrip();
  testProtocolRandomRoundTrip();
  testProtocolMalformed();
  testProtocolFuzz();
  testProtocolHelpers();
  testAddrLinkLocal();
  testSelection();
  testHandshakeAndCall();
  testDuplicateCallDoesNotReplay();
  testOutputFailureIsReported();
  testOutputFailureOverride();
  testOutputStaleness();
  testCatcherRequest();
  testCatcherRequestWhileCoachBusy();
  testExpiredRequest();
  testRequestRetransmits();
  testHandshakeReorder();
  testControlReplyRoundRobin();
  testFieldSyncToken();
  testIncompatibleDictionary();
  testAckAfterDeadline();
  testStaleAndDuplicateCalls();
  testNewBootResetsPeer();
  testSourceTargetMismatch();
  testResponseMatching();
  testCoachRequestRetries();
  testLinkTimeoutResync();
  testPongLiveness();
  testPingPongMechanics();
  testClockWrap();
  testLossyHandshakeBounded();
  testLossyCallRetries();
  testDelayedAckStaysMissing();
  testReorderedDuplicates();
  testCatcherRequestRetriesUnderLoss();
  testMultiNodeLoadAndFairness();
  testEngineDefaults();
  testUsbGate();
  testUsbGateEdges();
  testUsbParsing();
  testUsbParsingEdges();
  testCatcherMenu();
  testCatcherMenuNavigation();
  testCatcherMenuCommit();
  testCatcherButtonsDetailed();
  testStripPriority();
  testStripPriorityMatrix();
  testDiagnosticsScan();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
