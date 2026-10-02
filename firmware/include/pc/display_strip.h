#pragma once
namespace pc {
struct StripState {
  bool configured=true,radio=true,linked=true,incompatible=false,old=false,hasCall=false;
};
// Priority is independent of the displayed play: a retained label must not
// conceal setup, radio/link errors or the fact that a prior call is stale.
inline const char* stripStatus(const StripState& state) {
  if (!state.configured) return "USB SETUP";
  if (!state.radio) return "RADIO ERR";
  if (state.incompatible) return "DICT ERROR";
  if (!state.linked) return "NO LINK";
  if (state.old && state.hasCall) return "OLD";
  return state.hasCall ? "CALL" : "READY";
}
} // namespace pc
