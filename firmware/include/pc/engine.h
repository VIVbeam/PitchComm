#pragma once
#include "units.h"

namespace pc {
enum class Delivery : uint8_t { Unused, Pending, Delivered, Missing, OutputError };
enum class Submit : uint8_t { Accepted, Busy, Offline, Invalid, Expired, Incompatible };
struct Output { Category category; uint16_t code; uint32_t sequence, receivedAt; };
// Audio and field displays retain different calls. Keep the newest of each kind
// so a late pitch failure is still reported after a defensive play is sent.
struct CallRecord {
  Output output{};
  Delivery delivery[kUnitCount]{};
  uint64_t boots[kUnitCount]{};
  uint16_t window=0;
};
struct Hooks {
  virtual ~Hooks() = default;
  virtual bool send(const Packet&) = 0;
  virtual bool present(const Output&) = 0;
  virtual void clearOutput() = 0;
};
struct Peer {
  uint64_t boot=0, challenge=0;
  uint32_t seenAt=0, lastRequest=0, controlClock=0;
  uint32_t requestCall=0;
  uint16_t requestCode=0;
  Status requestStatus=Status::Invalid;
  bool ready=false, compatible=false, controlClockSeen=false;
};

class Engine {
 public:
  Engine(Role role, uint64_t boot, Hooks& hooks) : role_(role), boot_(boot ? boot : 1), hooks_(hooks) {
    session_ = role == kCoach ? boot_ : 0;
    if (role != kCoach) startSync();
  }
  Role role() const { return role_; }
  uint64_t session() const { return session_; }
  uint64_t boot() const { return boot_; }
  bool linked() const { return role_ == kCoach || (!syncing_ && session_ != 0); }
  bool incompatible() const { return incompatible_; }
  bool busy() const { return active_ || requesting_; }
  bool hasOutput() const { return hasOutput_; }
  const Output& output() const { return output_; }
  const Peer& peer(Role r) const { return peers_[uint8_t(r)]; }
  Delivery delivery(Role r) const { return delivery_[uint8_t(r)]; }
  const CallRecord& record(Category category) const { return records_[category==Category::Pitch ? 0 : 1]; }
  Status requestResult() const { return requestResult_; }
  bool requestFinished() const { return requestFinished_; }
  uint32_t outputAge(uint32_t now) const { return elapsed(now, output_.receivedAt); }
  bool outputOld(uint32_t now) const { return hasOutput_ && outputAge(now) >= kOldCall; }

  Submit submit(Category category, uint16_t code, uint32_t now) {
    const bool coach = role_ == kCoach;
    // Only the coach originates any call; a controls unit may request pitches.
    if (!findCall(category,code) ||
        (!coach && (!controlsRole(role_) || category != Category::Pitch))) {
      return Submit::Invalid;
    }
    if (!linked()) return Submit::Offline;
    if (busy()) return Submit::Busy;
    if (coach) { beginCall(category,code,now,kCallWindow); return Submit::Accepted; }
    request_ = base(Kind::Request,kCoach);
    request_.category=category; request_.code=code; request_.sequence=++requestCounter_;
    request_.deadline=coordinatorLower(now)+kCallWindow;
    if (!request_.sequence) request_.sequence=++requestCounter_;
    requestAt_=now; requestSent_=now-100; requesting_=true; requestFinished_=false;
    requestResult_=Status::Busy;
    return Submit::Accepted;
  }

  void tick(uint32_t now) {
    if (role_==kCoach) {
      // Heartbeats often arrive together. Keep one bounded control reply per peer
      // instead of dropping every reply after the first while the radio is busy.
      for (unsigned n=0;n<kUnitCount-1;++n) {
        const unsigned i=1+((controlRoundRobin_+n)%(kUnitCount-1));
        if (!controlPending_[i]) continue;
        if (transmit(control_[i],now)) {
          controlPending_[i]=false; controlRoundRobin_=i%(kUnitCount-1); break;
        }
      }
      for (unsigned i=1;i<kUnitCount;++i) {
        auto& p=peers_[i]; if (p.ready && elapsed(now,p.seenAt)>kLinkTimeout) p.ready=false;
      }
      if (active_) {
        if (elapsed(now,callAt_)>=callWindow_) finishCall();
        else {
          bool pending=false;
          for (unsigned n=0;n<kUnitCount-1;++n) {
            const unsigned i=1+((roundRobin_+n)%(kUnitCount-1));
            if (delivery_[i]!=Delivery::Pending) continue;
            pending=true; auto& peer=peers_[i];
            // Reconnecting receivers never get the call that preceded their handshake.
            if (!peer.ready || peer.boot!=callBoot_[i]) continue;
            if (elapsed(now,callSent_[i])<100) continue;
            Packet p=base(Kind::Call,Role(i)); p.boot=peer.boot;
            p.sequence=callSequence_; p.category=callCategory_; p.code=callCode_;
            p.deadline=callAt_+callWindow_;
            p.ttl=uint16_t(callWindow_-elapsed(now,callAt_));
            if (transmit(p,now)) { callSent_[i]=now; roundRobin_=i%(kUnitCount-1); break; }
          }
          if (!pending) active_=false;
        }
      }
      return;
    }
    if (!syncing_ && (elapsed(now,heardAt_)>kLinkTimeout || elapsed(now,clockAt_)>kLinkTimeout)) startSync();
    if (syncing_) {
      if (elapsed(now,helloAt_)>=600) {
        Packet p=base(Kind::Hello,kCoach); p.session=0; p.token=challenge_;
        if (transmit(p,now)) helloAt_=now;
      }
      return;
    }
    if (readyPending_) {
      Packet p=base(Kind::Ready,kCoach); p.token=challenge_;
      if (elapsed(now,readySent_)>=200 && transmit(p,now)) readySent_=now;
    }
    if (ackPending_ && elapsed(now,ackAt_)<kCallWindow && elapsed(now,ackSent_)>=80) {
      if (transmit(ack_,now)) ackSent_=now;
    }
    if (requesting_) {
      const auto age=elapsed(now,requestAt_);
      if (age>=kCallWindow) {
        requesting_=false; requestFinished_=true; requestResult_=Status::Expired;
      } else if (elapsed(now,requestSent_)>=100) {
        request_.ttl=uint16_t(kCallWindow-age);
        if (transmit(request_,now)) requestSent_=now;
      }
    }
    if (elapsed(now,pingAt_)>=1000) {
      Packet p=base(Kind::Ping,kCoach);
      if (transmit(p,now)) pingAt_=now;
    }
  }

  void receive(Role authenticatedSource, const Packet& p, uint32_t now, uint32_t queueAge=0) {
    if (!validRole(authenticatedSource) || p.source!=authenticatedSource || p.target!=role_) return;
    if (role_==kCoach) { receiveCoach(p,now,queueAge); return; }
    if (p.source!=kCoach || p.boot!=boot_) return;
    if (p.kind==Kind::Resync) { if (!syncing_) startSync(); return; }
    if (p.kind==Kind::Sync) {
      if (!syncing_ || p.token!=challenge_) return;
      if (p.dictionary!=kDictionary || p.status!=Status::Ok || !p.session) {
        incompatible_=true; return;
      }
      if (!updateClock(p,now)) return;
      session_=p.session; syncing_=false; incompatible_=false; heardAt_=now;
      lastSequence_=0; hasOutput_=false; hooks_.clearOutput(); readyPending_=true; readySent_=now-200;
      return;
    }
    if (syncing_ || p.dictionary!=kDictionary || p.session!=session_) return;
    if (p.kind==Kind::Pong) {
      if (updateClock(p,now)) { heardAt_=now; readyPending_=false; }
      return;
    }
    if (p.kind==Kind::Response && controlsRole(role_) && requesting_ &&
        p.sequence==request_.sequence && p.code==request_.code) {
      heardAt_=now; requesting_=false; requestFinished_=true; requestResult_=p.status; return;
    }
    if (p.kind!=Kind::Call || !p.sequence || !findCall(p.category,p.code) ||
        !(recipients(p.category,p.code) & roleMask(role_))) return;
    if (p.ttl==0 || p.ttl>kCallWindow || queueAge>=p.ttl ||
        elapsed(now,heardAt_)>kLinkTimeout || elapsed(now,clockAt_)>kLinkTimeout ||
        reached(coordinatorUpper(now)+40,p.deadline)) return;
    heardAt_=now;
    if (p.sequence==lastSequence_) {
      if (p.code==output_.code && p.category==output_.category) scheduleAck(p,lastOutputStatus_,now);
      return;
    }
    if (lastSequence_ && !newer(p.sequence,lastSequence_)) return;
    lastSequence_=p.sequence;
    output_={p.category,p.code,p.sequence,now}; hasOutput_=true;
    lastOutputStatus_=hooks_.present(output_) ? Status::Ok : Status::OutputError;
    scheduleAck(p,lastOutputStatus_,now);
  }

  void outputFailed(uint32_t sequence, uint32_t now) {
    if (role_==kCoach || !hasOutput_ || sequence!=lastSequence_) return;
    lastOutputStatus_=Status::OutputError;
    ack_.status=Status::OutputError; ackAt_=now; ackSent_=now-80; ackPending_=true;
  }

 private:
  Packet base(Kind kind, Role target) const {
    Packet p; p.kind=kind; p.source=role_; p.target=target; p.dictionary=kDictionary;
    p.session=session_; p.boot=boot_; return p;
  }
  bool transmit(Packet& p,uint32_t now) { p.clock=now; return hooks_.send(p); }
  void queueControl(const Packet& p) {
    const auto i=uint8_t(p.target);
    if (i>0 && i<kUnitCount) { control_[i]=p; controlPending_[i]=true; }
  }
  static bool reached(uint32_t now,uint32_t deadline) { return uint32_t(now-deadline)<0x80000000u; }
  bool updateClock(const Packet& p,uint32_t now) {
    const uint32_t roundTrip=elapsed(now,p.reference);
    if (roundTrip>250) return false;
    // Coordinator time at receipt lies between its send clock and send clock + RTT.
    // Use the upper bound to expire received calls early rather than play them late.
    if (clockReady_ && p.session==session_ && !newer(p.clock,clockLower_) && p.clock!=clockLower_) return false;
    clockLower_=p.clock; clockUpper_=p.clock+roundTrip+5; clockAt_=now; clockReady_=true;
    return true;
  }
  uint32_t coordinatorLower(uint32_t now) const { return clockLower_+elapsed(now,clockAt_); }
  uint32_t coordinatorUpper(uint32_t now) const { return clockUpper_+elapsed(now,clockAt_); }
  void startSync() {
    syncing_=true; incompatible_=false; session_=0; hasOutput_=false;
    clockReady_=false;
    hooks_.clearOutput(); ackPending_=false; readyPending_=false;
    if (requesting_) { requestFinished_=true; requestResult_=Status::Expired; }
    requesting_=false;
    challenge_=boot_ ^ (++challengeCounter_*0x9e3779b97f4a7c15ULL);
    if (!challenge_) challenge_=1;
    helloAt_=uint32_t(0)-600;
  }
  void scheduleAck(const Packet& p, Status status, uint32_t now) {
    ack_=base(Kind::Ack,kCoach); ack_.sequence=p.sequence; ack_.category=p.category;
    ack_.code=p.code; ack_.status=status; ackAt_=now; ackSent_=now-80; ackPending_=true;
  }
  void beginCall(Category category, uint16_t code, uint32_t now, uint16_t window) {
    ++callSequence_; if (!callSequence_) ++callSequence_;
    callCategory_=category; callCode_=code; callAt_=now; callWindow_=window; active_=true;
    output_={category,code,callSequence_,now}; hasOutput_=true;
    const bool localOk=hooks_.present(output_);
    for (unsigned i=0;i<kUnitCount;++i) {
      delivery_[i]=(recipients(category,code)&roleMask(Role(i))) ? Delivery::Pending : Delivery::Unused;
      callBoot_[i]=peers_[i].ready ? peers_[i].boot : 0; callSent_[i]=now-100;
    }
    delivery_[0]=localOk ? Delivery::Delivered : Delivery::OutputError;
    auto& record=records_[category==Category::Pitch ? 0 : 1];
    record.output=output_; record.window=window;
    for (unsigned i=0;i<kUnitCount;++i) { record.delivery[i]=delivery_[i]; record.boots[i]=callBoot_[i]; }
  }
  void finishCall() {
    for (auto& d:delivery_) if (d==Delivery::Pending) d=Delivery::Missing;
    auto& record=records_[callCategory_==Category::Pitch ? 0 : 1];
    for (unsigned i=0;i<kUnitCount;++i) record.delivery[i]=delivery_[i];
    active_=false;
  }
  void response(const Packet& request, Status status, uint32_t call) {
    Packet p=base(Kind::Response,request.source); p.boot=request.boot;
    p.sequence=request.sequence; p.code=request.code; p.status=status; p.token=call;
    queueControl(p);
  }
  void receiveCoach(const Packet& p, uint32_t now, uint32_t queueAge) {
    if (p.source==kCoach) return;
    auto& peer=peers_[uint8_t(p.source)];
    if (p.kind==Kind::Hello) {
      if (!p.boot || !p.token) return;
      // Reordered handshakes from the same boot must not roll its challenge
      // back after recovery. A new boot can legitimately restart its clock.
      if (p.boot==peer.boot && peer.controlClockSeen && !newer(p.clock,peer.controlClock) &&
          (p.clock!=peer.controlClock || p.token!=peer.challenge)) return;
      const bool changed=p.boot!=peer.boot || p.token!=peer.challenge;
      if (changed) {
        if (delivery_[uint8_t(p.source)]==Delivery::Pending) {
          delivery_[uint8_t(p.source)]=Delivery::Missing;
          records_[callCategory_==Category::Pitch ? 0 : 1].delivery[uint8_t(p.source)]=Delivery::Missing;
        }
        const bool newBoot=p.boot!=peer.boot;
        if (newBoot) peer=Peer{};
        peer.boot=p.boot; peer.challenge=p.token; peer.ready=false;
      }
      peer.controlClock=p.clock; peer.controlClockSeen=true;
      peer.compatible=p.dictionary==kDictionary; peer.seenAt=now;
      if (!peer.compatible) peer.ready=false;
      Packet reply=base(Kind::Sync,p.source); reply.boot=p.boot; reply.token=p.token;
      reply.reference=p.clock;
      reply.status=peer.compatible ? Status::Ok : Status::Incompatible; queueControl(reply); return;
    }
    if (p.session!=session_ || p.boot!=peer.boot || !peer.compatible || p.dictionary!=kDictionary) {
      if (p.boot) { Packet reply=base(Kind::Resync,p.source); reply.boot=p.boot; queueControl(reply); }
      return;
    }
    if (p.kind==Kind::Ready && p.token==peer.challenge) {
      if (newer(p.clock,peer.controlClock)) peer.controlClock=p.clock;
      peer.ready=true; peer.seenAt=now;
      Packet reply=base(Kind::Pong,p.source); reply.boot=p.boot; reply.reference=p.clock; queueControl(reply); return;
    }
    if (!peer.ready) return;
    if (p.kind==Kind::Ping) {
      // Keep the ordering reference current through clock rollover and long
      // uptime. A reordered heartbeat cannot move it backwards.
      if (newer(p.clock,peer.controlClock)) peer.controlClock=p.clock;
      peer.seenAt=now; Packet reply=base(Kind::Pong,p.source); reply.boot=p.boot; reply.reference=p.clock; queueControl(reply); return;
    }
    if (p.kind==Kind::Ack && (p.status==Status::Ok || p.status==Status::OutputError)) {
      if (p.category!=Category::Pitch && p.category!=Category::Play) return;
      auto& record=records_[p.category==Category::Pitch ? 0 : 1];
      if (!p.sequence || p.sequence!=record.output.sequence || p.code!=record.output.code) return;
      auto& d=record.delivery[uint8_t(p.source)];
      if ((d!=Delivery::Pending && d!=Delivery::Delivered) || p.boot!=record.boots[uint8_t(p.source)]) return;
      // An ACK processed beyond the delivery deadline cannot turn a timeout into success.
      if (d==Delivery::Pending && elapsed(now,record.output.receivedAt)>=record.window) return;
      peer.seenAt=now; d=p.status==Status::Ok ? Delivery::Delivered : Delivery::OutputError;
      if (p.sequence==callSequence_ && p.category==callCategory_) delivery_[uint8_t(p.source)]=d;
      return;
    }
    if (p.kind!=Kind::Request || !controlsRole(p.source) || !p.sequence) return;
    peer.seenAt=now;
    if (p.sequence==peer.lastRequest) {
      if (p.code==peer.requestCode) response(p,peer.requestStatus,peer.requestCall);
      return;
    }
    if (peer.lastRequest && !newer(p.sequence,peer.lastRequest)) return;
    Status result=Status::Ok;
    if (p.category!=Category::Pitch || !findCall(p.category,p.code)) result=Status::Invalid;
    else if (!p.ttl || p.ttl>kCallWindow || queueAge>=p.ttl || reached(now,p.deadline)) result=Status::Expired;
    else if (active_) result=Status::Busy;
    if (result==Status::Ok) {
      const auto remaining=p.deadline-now;
      const auto ttl=uint32_t(p.ttl-queueAge);
      beginCall(p.category,p.code,now,uint16_t(remaining<ttl ? remaining : ttl));
    }
    peer.lastRequest=p.sequence; peer.requestCode=p.code; peer.requestStatus=result;
    peer.requestCall=result==Status::Ok ? callSequence_ : 0;
    response(p,result,peer.requestCall);
  }

  Role role_; uint64_t boot_; Hooks& hooks_;
  Peer peers_[kUnitCount]{}; Delivery delivery_[kUnitCount]{};
  CallRecord records_[2]{};
  Packet control_[kUnitCount]{}; bool controlPending_[kUnitCount]{}; unsigned controlRoundRobin_=0;
  uint64_t session_=0, challenge_=0, challengeCounter_=0, callBoot_[kUnitCount]{};
  uint32_t helloAt_=0, heardAt_=0, pingAt_=0, lastSequence_=0, readySent_=0;
  uint32_t clockLower_=0, clockUpper_=0, clockAt_=0; bool clockReady_=false;
  bool syncing_=false, incompatible_=false, readyPending_=false, hasOutput_=false;
  Output output_{}; Status lastOutputStatus_=Status::Ok;
  Packet ack_{}; bool ackPending_=false; uint32_t ackAt_=0, ackSent_=0;
  Packet request_{}; bool requesting_=false, requestFinished_=false;
  Status requestResult_=Status::Ok; uint32_t requestCounter_=0, requestAt_=0, requestSent_=0;
  bool active_=false; uint32_t callSequence_=0, callAt_=0, callSent_[kUnitCount]{};
  uint16_t callCode_=0, callWindow_=kCallWindow; Category callCategory_=Category::Pitch;
  unsigned roundRobin_=0;
};
} // namespace pc
