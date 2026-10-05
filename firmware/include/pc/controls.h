#pragma once
#include <string.h>
#include "segmented_pitch.h"
namespace pc {
// Three explicit keypad selections. No inferred location or automatic send.
struct Selection {
  unsigned type=0, height=0, side=0;
  void clear() { type=height=side=0; }
  uint16_t code() const { return pitchCode(type,height,side); }
  bool choose(unsigned key) {
    if (!key || key>kPitchCount) return false;
    if (!type) type=key;
    else if (!height) { if (key>kRows) return false; height=key; }
    else if (!side) { if (key>kCols) return false; side=key; }
    else { clear(); type=key; }
    return true;
  }
};
constexpr uint32_t kUsbGrant=1500;
struct UsbCall {
  uint32_t client=0,id=0,dictionary=0,deadline=0;
  uint64_t boot=0;
  Category category=Category::Pitch; uint16_t code=0;
};
inline bool parseHex(const char*& cursor,unsigned digits,uint64_t& value) {
  value=0;
  for (unsigned i=0;i<digits;++i) {
    const char ch=*cursor;
    unsigned digit=0;
    if (ch>='0' && ch<='9') digit=unsigned(ch-'0');
    else if (ch>='a' && ch<='f') digit=unsigned(ch-'a'+10);
    else if (ch>='A' && ch<='F') digit=unsigned(ch-'A'+10);
    else return false;
    ++cursor; value=(value<<4)|digit;
  }
  return true;
}
inline bool parseGuiClient(const char* line,uint32_t& client) {
  if (strncmp(line,"gui ",4)) return false;
  const char* cursor=line+4; uint64_t value=0;
  if (!parseHex(cursor,8,value) || *cursor || !value) return false;
  client=uint32_t(value); return true;
}
inline bool parseUsbCall(const char* line, UsbCall& result) {
  if (strncmp(line,"call ",5)) return false;
  const char* cursor=line+5;
  auto number=[&](uint32_t& value) {
    value=0;
    if (*cursor<'0' || *cursor>'9') return false;
    while (*cursor>='0' && *cursor<='9') {
      const unsigned digit=unsigned(*cursor++-'0');
      if (value>(UINT32_MAX-digit)/10) return false;
      value=value*10+digit;
    }
    return true;
  };
  auto space=[&]() { if (*cursor!=' ') return false; ++cursor; return true; };
  uint32_t id=0,type=0,height=0,side=0,deadline=0;
  uint64_t client=0,boot=0,dictionary=0;
  if (!parseHex(cursor,8,client) || !client || !space() || !number(id) || !id || !space() || (*cursor!='p' && *cursor!='d' && *cursor!='t' && *cursor!='l')) return false;
  const char category=*cursor++;
  if (!space() || !number(type)) return false;
  uint16_t code=0;
  if (category=='p' || category=='l') {
    if (!space() || !number(height) || !space() || !number(side)) return false;
    code=category=='l' ? placementCode(type,height,side) : pitchCode(type,height,side);
  } else if(category=='t') { code=pitchTypeCode(type); } else if (category=='d') { if (type<1 || type>kPlayCount) return false; code=uint16_t(type); }
  else return false;
  if (!code || !space() || !parseHex(cursor,16,boot) || !boot || !space() || !parseHex(cursor,8,dictionary) ||
      !space() || !number(deadline) || *cursor) return false;
  result={uint32_t(client),id,uint32_t(dictionary),deadline,boot,category=='d' ? Category::Play : Category::Pitch,code}; return true;
}
} // namespace pc
