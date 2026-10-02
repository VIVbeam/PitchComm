#pragma once
#include <stdio.h>
#include "catalog.h"

namespace pc {
// Inputs are release events, except the side button's single long-hold event.
// The model only asks its caller to send; selection never transmits by itself.
class CatcherMenu {
 public:
  enum class Screen { Pitches, Height, Location };
  enum class Action { None, Send, Recall, Volume, Cancel };
  // Three numbered slots per page; the fourth front key pages forward.
  static constexpr unsigned kPitchPages = (kPitchCount + 2) / 3;
  Screen screen() const { return screen_; }
  unsigned page() const { return page_; }
  unsigned pitch() const { return pitch_; }
  unsigned height() const { return height_; }
  unsigned location() const { return location_; }
  bool draft() const { return engaged_; }
  uint16_t code() const { return pitchCode(pitch_,height_,location_); }
  void cancel() { screen_=Screen::Pitches; pitch_=height_=location_=0; engaged_=false; }
  // Call only after queue acceptance; a rejected Send retains the editable draft.
  void accepted() { cancel(); }
  // Re-arm a complete selection after the coach rejects the request (busy) or
  // it expires, so a resend is one press from the Location screen.
  void restore(uint16_t code) {
    constexpr unsigned kCodesPerPitch = kRows * kCols;
    if (!code || code > kPitchCount * kCodesPerPitch) return;
    pitch_=(code-1)/kCodesPerPitch+1;
    height_=((code-1)%kCodesPerPitch)/kCols+1;
    location_=(code-1)%kCols+1;
    page_=(pitch_-1)/3; screen_=Screen::Location; engaged_=true;
  }
  template<class Submit>
  bool commit(bool displayReady,bool controlsReady,bool audioReady,Submit submit) {
    if (screen_!=Screen::Location || !code() || !displayReady || !controlsReady || !audioReady)
      return false;
    if (!submit(code())) return false;
    accepted(); return true;
  }
  Action front(unsigned key) {
    if (key<1 || key>4) return Action::None;
    if (screen_==Screen::Pitches) {
      if (key==4) { page_=(page_+1)%kPitchPages; engaged_=true; return Action::None; }
      const unsigned selected=page_*3+key;
      if (selected>kPitchCount) return Action::None;  // short final page
      if (selected!=pitch_) height_=location_=0;
      engaged_=true; pitch_=selected; screen_=Screen::Height;
    } else if (screen_==Screen::Height) {
      if (key<4 && key<=kRows) { if (height_!=key) location_=0; height_=key; }
      else if (key==4 && height_) screen_=Screen::Location;
    } else if (key<4 && key<=kCols) location_=key;
    else if (key==4 && code()) return Action::Send;
    return Action::None;
  }
  Action back(bool longHold) {
    if (longHold) {
      if (!draft()) return Action::Volume;
      cancel(); return Action::Cancel;
    }
    if (screen_==Screen::Location) screen_=Screen::Height;
    else if (screen_==Screen::Height) { screen_=Screen::Pitches; page_=(pitch_-1)/3; }
    else if (!draft()) return Action::Recall;
    return Action::None;
  }
  // The generated short forms are the only labels the menu displays.
  struct Frame { char header[24]{}, rows[2][24]{}, footer[24]{}; };
  Frame frame() const {
    Frame f;
    const char* labels[3]={"","",""}; unsigned selected=0;
    const char* fourth="--";
    if (screen_==Screen::Pitches) {
      snprintf(f.header,sizeof(f.header),"PITCHES %u/%u",page_+1,kPitchPages);
      for (unsigned i=0;i<3;++i) {
        const unsigned index=page_*3+i;
        if (index<kPitchCount) labels[i]=kPitchShort[index];
      }
      if (pitch_ && (pitch_-1)/3==page_) selected=(pitch_-1)%3+1;
      fourth="Next";
      snprintf(f.footer,sizeof(f.footer),"%s",draft() ? "Hold Back: cancel" : "Back recall; hold vol");
    } else {
      const bool heightScreen=screen_==Screen::Height;
      selected=heightScreen ? height_ : location_;
      for (unsigned i=0;i<3;++i) {
        if (heightScreen) { if (i<kRows) labels[i]=kRowShort[i]; }
        else if (i<kCols) labels[i]=kColShort[i];
      }
      if (heightScreen) snprintf(f.header,sizeof(f.header),"%s HEIGHT",kPitchShort[pitch_-1]);
      else snprintf(f.header,sizeof(f.header),"%s %s %s",kPitchShort[pitch_-1],
                         kRowShort[height_-1],location_ ? kColShort[location_-1] : "--");
      if (selected) fourth=heightScreen ? "Confirm" : "Send";
      snprintf(f.footer,sizeof(f.footer),"%s",selected ? "Back; hold: cancel" :
                    (heightScreen ? "Choose height; Back" : "Choose side; Back"));
    }
    snprintf(f.rows[0],sizeof(f.rows[0]),"1%c%-4s 2%c%s",selected==1 ? '>' : ' ',labels[0],
                  selected==2 ? '>' : ' ',labels[1]);
    snprintf(f.rows[1],sizeof(f.rows[1]),"3%c%-4s 4 %s",selected==3 ? '>' : ' ',labels[2],fourth);
    return f;
  }
 private:
  bool engaged_=false;
  Screen screen_=Screen::Pitches;
  unsigned page_=0,pitch_=0,height_=0,location_=0;
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
