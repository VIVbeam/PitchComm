#pragma once
#include <stdio.h>
#include "segmented_pitch.h"

namespace pc {
// A pitch selection announces immediately; a human confirms the observed nod.
class CatcherMenu {
 public:
  enum class Screen { Pitches, AwaitPitch, AwaitNod, Height, Location, AwaitPlacement };
  enum class Action { None, Send, Recall, Volume, Cancel };
  static constexpr unsigned kPitchPages=(kPitchCount+2)/3;
  Screen screen() const { return screen_; }
  unsigned page() const { return page_; }
  unsigned pitch() const { return pitch_; }
  unsigned height() const { return height_; }
  unsigned location() const { return location_; }
  bool draft() const { return engaged_; }
  uint16_t code() const {
    return screen_==Screen::Pitches ? pitchTypeCode(pitch_) :
           screen_==Screen::Location ? placementCode(pitch_,height_,location_) : 0;
  }
  void cancel() { screen_=Screen::Pitches;pitch_=height_=location_=pending_=0;engaged_=false; }
  void accepted() {
    pending_=code();
    screen_=screen_==Screen::Pitches ? Screen::AwaitPitch : Screen::AwaitPlacement;
  }
  // Only the current request may advance or restore the draft. Back/cancel
  // invalidates it, so a late response cannot resurrect an abandoned call.
  void confirmed(uint16_t code) {
    if (!pending_ || pending_!=code) return;
    pending_=0;
    if (screen_==Screen::AwaitPitch) screen_=Screen::AwaitNod;
    else if (screen_==Screen::AwaitPlacement) cancel();
  }
  void restore(uint16_t code) {
    if (!pending_ || pending_!=code) return;
    pending_=0;
    if (isPitchType(code)) { screen_=Screen::Pitches;height_=location_=0; }
    else if (isPlacement(code)) screen_=Screen::Location;
  }
  void rejected(uint16_t code) {
    if (pending_ && pending_==code) cancel();
  }
  template<class Submit>
  bool commit(bool displayReady,bool controlsReady,bool audioReady,Submit submit) {
    if (!code() || !displayReady || !controlsReady || !audioReady) return false;
    if (!submit(code())) return false;
    accepted();return true;
  }
  Action front(unsigned key) {
    if (key<1 || key>4) return Action::None;
    if (screen_==Screen::Pitches) {
      if (key==4) { page_=(page_+1)%kPitchPages;pitch_=0;engaged_=true;return Action::None; }
      unsigned selected=page_*3+key;
      if (selected>kPitchCount) return Action::None;
      pitch_=selected;height_=location_=0;engaged_=true;return Action::Send;
    }
    if (screen_==Screen::AwaitNod) {
      if (key==4) screen_=Screen::Height;
    } else if (screen_==Screen::Height) {
      if (key<4 && key<=kRows) { if(height_!=key) location_=0;height_=key; }
      else if(key==4 && height_) screen_=Screen::Location;
    } else if(screen_==Screen::Location) {
      if(key<4 && key<=kCols) location_=key;
      else if(key==4 && code()) return Action::Send;
    }
    return Action::None;
  }
  Action back(bool longHold) {
    if(longHold) { if(!draft()) return Action::Volume;cancel();return Action::Cancel; }
    if(screen_==Screen::Location) screen_=Screen::Height;
    else if(screen_==Screen::Height) screen_=Screen::AwaitNod;
    else if(screen_!=Screen::Pitches) { page_=(pitch_-1)/3;cancel(); }
    else if(!draft()) return Action::Recall;
    return Action::None;
  }
  struct Frame { char header[24]{},footer[24]{},keys[4][6]{};unsigned selected=0; };
  Frame frame() const {
    Frame f;const char* labels[4]={"--","--","--","--"};
    if(screen_==Screen::Pitches) {
      snprintf(f.header,sizeof(f.header),"PITCHES %u/%u",page_+1,kPitchPages);
      for(unsigned i=0;i<3;++i) if(page_*3+i<kPitchCount) labels[i]=kPitchShort[page_*3+i];
      labels[3]="NEXT";f.selected=pitch_ ? (pitch_-1)%3+1 : 0;
      snprintf(f.footer,sizeof(f.footer),"%s",draft()?"Select; hold cancels":"Back recall; hold vol");
    } else {
      snprintf(f.header,sizeof(f.header),"%s %s",kPitchShort[pitch_-1],
        screen_==Screen::Height?"HEIGHT":screen_==Screen::Location?"PLACEMENT":"PITCH");
      if(screen_==Screen::AwaitNod) {
        labels[3]="NOD";snprintf(f.footer,sizeof(f.footer),"Saw nod? 4; Back edit");
      } else if(screen_==Screen::AwaitPitch || screen_==Screen::AwaitPlacement) {
        snprintf(f.footer,sizeof(f.footer),"Sending; Back exits");
      } else {
        bool h=screen_==Screen::Height;f.selected=h?height_:location_;
        for(unsigned i=0;i<3;++i) labels[i]=h?(i<kRows?kRowShort[i]:"--"):(i<kCols?kColShort[i]:"--");
        labels[3]=f.selected?(h?"OK":"SEND"):"--";
        snprintf(f.footer,sizeof(f.footer),"%s",h?"Choose height; Back":"Choose side; Back");
      }
    }
    for(unsigned i=0;i<4;++i) snprintf(f.keys[i],sizeof(f.keys[i]),"%s",labels[i]);
    return f;
  }
 private:
  bool engaged_=false;
  Screen screen_=Screen::Pitches;
  unsigned page_=0,pitch_=0,height_=0,location_=0;
  uint16_t pending_=0;
};

// Combined five-button filter. Faults, even transient chords and startup-held
// switches suppress actions until every switch has been released for 35 ms.
class CatcherButtons {
 public:
  unsigned tick(uint8_t mask,bool valid,uint32_t now) {
    mask&=0x1f;
    if (!valid || (mask && (mask&(mask-1)))) {
      blocked_=true; held_=0; longReported_=false; raw_=mask; changed_=now;
      return 0;
    }
    if (mask!=raw_) { raw_=mask; changed_=now; }
    if (blocked_) {
      if (!mask && elapsed(now,changed_)>=35) blocked_=false;
      return 0;
    }
    if (elapsed(now,changed_)<35) return 0;
    if (mask!=held_) {
      // Switching directly between buttons without full release is a chord.
      if (held_ && mask) { blocked_=true; held_=0; return 0; }
      if (mask) { held_=mask; pressed_=now; longReported_=false; }
      else {
        const uint8_t released=held_; held_=0;
        if (longReported_) return 0;
        for (unsigned i=0;i<5;++i) if (released==(1u<<i)) return i+1;
      }
    }
    if (held_==0x10 && !longReported_ && elapsed(now,pressed_)>=700) {
      longReported_=true; return 6;
    }
    return 0;
  }
 private:
  bool blocked_=true,longReported_=false;
  uint8_t raw_=0,held_=0;
  uint32_t changed_=0,pressed_=0;
};
} // namespace pc
