#pragma once
#include <cstddef>
#include <cstdint>

namespace pc {
// A unit index on the wire: 0 is the coach, 1..kUnitCount-1 are the enrolled
// field units generated from config/roster.json. units.h adds the named unit
// constants and the capability helpers over the generated catalog.
using Role = uint8_t;
enum class Kind : uint8_t { Hello=1, Sync, Ready, Ping, Pong, Resync, Request, Response, Call, Ack };
enum class Category : uint8_t { Pitch=1, Play=2 };
enum class Status : uint8_t { Ok, Busy, Invalid, Incompatible, OutputError, Expired };
// The wire holds one nibble per unit field; the engine rejects indices at or
// above the generated kUnitCount while a stale catalog can still be parsed.
constexpr unsigned kMaxUnits = 16;
constexpr size_t kPacketBytes = 56;
constexpr uint8_t kProtocolVersion = 1;
constexpr uint32_t kCallWindow = 1000;
constexpr uint32_t kLinkTimeout = 3500;
constexpr uint32_t kOldCall = 15000;
constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }
constexpr bool newer(uint32_t a, uint32_t b) { return a != b && uint32_t(a-b) < 0x80000000u; }

struct Packet {
  Kind kind = Kind::Hello;
  Role source = Role(0), target = Role(0);
  Category category = Category::Pitch;
  Status status = Status::Ok;
  uint32_t dictionary = 0;
  uint64_t session = 0, boot = 0;
  uint32_t sequence = 0;
  uint16_t code = 0, ttl = 0;
  uint64_t token = 0;
  uint32_t clock = 0, reference = 0, deadline = 0;
};
// Explicit little-endian wire format: no packed structs, ABI, or pointer data.
inline void put(uint8_t* dst, uint64_t value, unsigned bytes) {
  for (unsigned i=0; i<bytes; ++i) dst[i] = uint8_t(value >> (8*i));
}
inline uint64_t get(const uint8_t* src, unsigned bytes) {
  uint64_t v=0; for (unsigned i=0; i<bytes; ++i) v |= uint64_t(src[i]) << (8*i); return v;
}
inline void encode(const Packet& p, uint8_t* b) {
  b[0]='P'; b[1]='C'; b[2]=kProtocolVersion; b[3]=uint8_t(p.kind);
  b[4]=uint8_t(p.source); b[5]=uint8_t(p.target); b[6]=uint8_t(p.category); b[7]=uint8_t(p.status);
  put(b+8,p.dictionary,4); put(b+12,p.session,8); put(b+20,p.boot,8);
  put(b+28,p.sequence,4); put(b+32,p.code,2); put(b+34,p.ttl,2); put(b+36,p.token,8);
  put(b+44,p.clock,4); put(b+48,p.reference,4); put(b+52,p.deadline,4);
}
inline bool decode(const uint8_t* b, size_t n, Packet& p) {
  if (n != kPacketBytes || b[0]!='P' || b[1]!='C' || b[2]!=kProtocolVersion ||
      b[3]<uint8_t(Kind::Hello) || b[3]>uint8_t(Kind::Ack) || b[4]>=kMaxUnits || b[5]>=kMaxUnits ||
      b[6]<1 || b[6]>2 || b[7]>uint8_t(Status::Expired)) return false;
  p.kind=Kind(b[3]); p.source=Role(b[4]); p.target=Role(b[5]);
  p.category=Category(b[6]); p.status=Status(b[7]); p.dictionary=uint32_t(get(b+8,4));
  p.session=get(b+12,8); p.boot=get(b+20,8); p.sequence=uint32_t(get(b+28,4));
  p.code=uint16_t(get(b+32,2)); p.ttl=uint16_t(get(b+34,2)); p.token=get(b+36,8);
  p.clock=uint32_t(get(b+44,4)); p.reference=uint32_t(get(b+48,4)); p.deadline=uint32_t(get(b+52,4));
  return true;
}
} // namespace pc
