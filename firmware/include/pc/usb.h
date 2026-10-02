#pragma once
#include "controls.h"
#include "engine.h"
namespace pc {
struct UsbResult { Submit result=Submit::Invalid; uint32_t sequence=0; };
class UsbGate {
 public:
  explicit UsbGate(Role role) : role_(role) {}
  uint32_t client() const { return client_; }
  void begin(uint32_t client) {
    if (!client || client==client_) return;
    client_=client; last_=UsbCall{}; saved_=UsbResult{};
  }
  template<class SubmitCall>
  UsbResult execute(const UsbCall& call,uint64_t boot,uint32_t dictionary,uint32_t now,SubmitCall submit) {
    // The catcher calls from its keypad. USB calling belongs only to coach.
    if (role_!=kCoach || !client_ || call.client!=client_) return {};
    // Retries of the last command return its original result, including busy/expired.
    // They never become a new pitch after the coordinator becomes idle.
    if (call.id==last_.id && call.id) {
      return same(call,last_) ? saved_ : UsbResult{};
    }
    if (!call.id || (last_.id && !newer(call.id,last_.id))) return {};
    UsbResult result;
    if (call.boot!=boot || call.dictionary!=dictionary) result.result=Submit::Incompatible;
    else if (uint32_t(call.deadline-now)==0 || uint32_t(call.deadline-now)>kUsbGrant)
      result.result=Submit::Expired;
    else result=submit();
    last_=call; saved_=result; return result;
  }
 private:
  static bool same(const UsbCall& a,const UsbCall& b) {
    return a.client==b.client && a.id==b.id && a.boot==b.boot && a.dictionary==b.dictionary &&
      a.deadline==b.deadline && a.category==b.category && a.code==b.code;
  }
  Role role_; uint32_t client_=0; UsbCall last_{}; UsbResult saved_{};
};
} // namespace pc
