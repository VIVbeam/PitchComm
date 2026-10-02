// Host-side verification of the portable streaming resampler
// (firmware/include/pc/resampler.h): integer linear interpolation from a
// clip's native rate to the negotiated LC3 rate, volume gain, and per-frame
// assembly. Build and run: firmware/tests/run_audio_tests.ps1 (g++ or clang++).
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "pc/resampler.h"

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

// One clip the resampler can read in bounded chunks. `chunk` 0 means "hand
// out as much as the resampler asks for"; otherwise each read returns at most
// that many frames. `fail_next` makes the next read fail.
struct Source {
  const int16_t* data;
  size_t len;
  size_t pos;
  size_t chunk;
  int reads;
  int fail_next;
};

int readSource(void* ctx, int16_t* dst, size_t frames) {
  Source* s = static_cast<Source*>(ctx);
  ++s->reads;
  if (s->fail_next > 0) {
    --s->fail_next;
    return -5;  // an arbitrary negative errno
  }
  const size_t avail = s->len - s->pos;
  size_t n = frames < avail ? frames : avail;
  if (s->chunk != 0 && n > s->chunk) n = s->chunk;
  for (size_t i = 0; i < n; ++i) dst[i] = s->data[s->pos + i];
  s->pos += n;
  return static_cast<int>(n);
}

// Pull one resampled sample, like audio_source.c does when filling a frame.
struct StreamPull {
  pc_resampler* rs;
  Source* source;
  int32_t gain;
};

int pullSample(void* ctx, int16_t* out) {
  StreamPull* p = static_cast<StreamPull*>(ctx);
  return pc_resampler_next(p->rs, readSource, p->source, p->gain, out);
}

// Minimal mirror of audio_source.c's call state: up to three clips separated
// by a silence gap, assembled through pc_resampler_fill_frame. Each clip
// starts with pc_resampler_init() so its stream begins at sample 0.
struct TestCall {
  enum Phase { Play, Open, Gap, Done };
  pc_resampler rs;
  Source sources[3];
  int clip = 0;
  int next_clip = 0;
  bool played_any = false;
  Phase phase = Open;
  uint32_t gap_frames = 0;
  uint32_t gap_total = 3;
  uint32_t dst_rate = 16000;
  int32_t gain = 1024;
};

int pullCallSample(void* ctx, int16_t* out) {
  TestCall* c = static_cast<TestCall*>(ctx);
  for (;;) {
    switch (c->phase) {
      case TestCall::Play: {
        const int r =
            pc_resampler_next(&c->rs, readSource, &c->sources[c->clip], c->gain, out);
        if (r > 0) return 1;
        c->phase = TestCall::Open;
        continue;
      }
      case TestCall::Open: {
        if (c->next_clip >= 3) {
          c->phase = TestCall::Done;
          return 0;
        }
        const int i = c->next_clip++;
        pc_resampler_init(&c->rs, 8000, c->dst_rate);
        c->clip = i;
        if (c->played_any) {
          c->gap_frames = c->gap_total;
          c->phase = TestCall::Gap;
        } else {
          c->played_any = true;
          c->phase = TestCall::Play;
        }
        continue;
      }
      case TestCall::Gap:
        if (c->gap_frames > 0) {
          c->gap_frames--;
          *out = 0;
          return 1;
        }
        c->phase = TestCall::Play;
        continue;
      case TestCall::Done:
      default:
        return 0;
    }
  }
}

void checkSamples(const char* name, const int16_t* got, size_t gotCount,
                  const int16_t* want, size_t wantCount) {
  CHECK(gotCount == wantCount);
  const size_t n = gotCount < wantCount ? gotCount : wantCount;
  for (size_t i = 0; i < n; ++i) {
    ++g_checks;
    if (got[i] != want[i]) {
      ++g_failures;
      std::printf("FAIL %s sample %u: got %d want %d\n", name, unsigned(i), int(got[i]),
                  int(want[i]));
    }
  }
}

// Pull until the stream ends or `max` samples were produced.
size_t drain(pc_resampler* rs, Source* source, int32_t gain, int16_t* out, size_t max) {
  size_t n = 0;
  while (n < max) {
    const int r = pc_resampler_next(rs, readSource, source, gain, &out[n]);
    if (r <= 0) break;
    ++n;
  }
  return n;
}

// 1..20 maps linearly to 5 %..100 % with a 5 % headroom guard, as Q10.
void testGainTable() {
  CHECK(pc_resampler_gain_q10(1) == 48);
  CHECK(pc_resampler_gain_q10(2) == 97);
  CHECK(pc_resampler_gain_q10(10) == 486);
  CHECK(pc_resampler_gain_q10(20) == 972);
  // Out-of-range volumes clamp to the 1..20 table ends.
  CHECK(pc_resampler_gain_q10(0) == 48);
  CHECK(pc_resampler_gain_q10(21) == 972);
  CHECK(pc_resampler_gain_q10(255) == 972);
}

void testApplyGain() {
  CHECK(pc_resampler_apply_gain(1000, 972) == 949);
  // The shift floors, so a negative product rounds down.
  CHECK(pc_resampler_apply_gain(-1000, 972) == -950);
  CHECK(pc_resampler_apply_gain(1000, 486) == 474);
  CHECK(pc_resampler_apply_gain(1000, 48) == 46);
  CHECK(pc_resampler_apply_gain(32767, 1024) == 32767);
  // Values beyond the int16 range clamp instead of wrapping.
  CHECK(pc_resampler_apply_gain(40000, 1024) == 32767);
  CHECK(pc_resampler_apply_gain(-40000, 1024) == -32768);
  // Full-scale inputs at maximum volume stay in range.
  CHECK(pc_resampler_apply_gain(INT16_MAX, 972) == 31103);
  CHECK(pc_resampler_apply_gain(INT16_MIN, 972) == -31104);
}

void testStepQ16() {
  CHECK(pc_resampler_step_q16(8000, 16000) == 32768);
  CHECK(pc_resampler_step_q16(16000, 16000) == 65536);
  CHECK(pc_resampler_step_q16(16000, 24000) == 43690);
  CHECK(pc_resampler_step_q16(16000, 32000) == 32768);
  CHECK(pc_resampler_step_q16(16000, 48000) == 21845);
  CHECK(pc_resampler_step_q16(8000, 48000) == 10922);
  CHECK(pc_resampler_step_q16(48000, 16000) == 196608);
  CHECK(pc_resampler_step_q16(0, 16000) == 0);
  CHECK(pc_resampler_step_q16(16000, 0) == 0);
}

// 8 kHz to 16 kHz doubles the rate: each source pair yields the two endpoints
// and their midpoint, and the clip's last sample is held until the stream ends.
void testRamp8kTo16k() {
  const int16_t src[] = {0, 100, 200, 300};
  const int16_t want[] = {0, 50, 100, 150, 200, 250, 300, 300};
  int16_t got[16];
  Source source{src, 4, 0, 0, 0, 0};
  pc_resampler rs;

  pc_resampler_init(&rs, 8000, 16000);
  const size_t n = drain(&rs, &source, 1024, got, 16);
  checkSamples("8k->16k unity", got, n, want, 8);

  // The next pull reports the end and leaves the output untouched.
  int16_t extra = 1234;
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &extra) == 0);
  CHECK(extra == 1234);
  // Four frames in one read, plus the read that reports EOF.
  CHECK(source.reads == 2);
}

// 16 kHz to 48 kHz uses a Q16 step of 21845 (not exactly one third), so the
// expected samples pin the exact integer interpolation.
void testRamp16kTo48k() {
  const int16_t src[] = {0, 300, 600, 900, 1200};
  const int16_t want[] = {0,   99,   199,  299,  399,  499,  599,  699,
                          799, 899,  999,  1099, 1199, 1200, 1200, 1200};
  int16_t got[24];
  Source source{src, 5, 0, 0, 0, 0};
  pc_resampler rs;

  pc_resampler_init(&rs, 16000, 48000);
  const size_t n = drain(&rs, &source, 1024, got, 24);
  checkSamples("16k->48k unity", got, n, want, 16);
}

// The whole pipeline including the volume gain, at the default maximum.
void testVolumeScaling() {
  const int16_t src[] = {1000};
  int16_t got[4];
  pc_resampler rs;

  Source s20{src, 1, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  size_t n = drain(&rs, &s20, pc_resampler_gain_q10(20), got, 4);
  const int16_t want20[] = {949, 949};  // 1000 * 972 / 1024, then held
  checkSamples("volume 20", got, n, want20, 2);

  Source s10{src, 1, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  n = drain(&rs, &s10, pc_resampler_gain_q10(10), got, 4);
  const int16_t want10[] = {474, 474};
  checkSamples("volume 10", got, n, want10, 2);

  Source s1{src, 1, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  n = drain(&rs, &s1, pc_resampler_gain_q10(1), got, 4);
  const int16_t want1[] = {46, 46};
  checkSamples("volume 1", got, n, want1, 2);
}

// 8 kHz to 16 kHz again but read in three-frame chunks, so the source window
// slides across the clip boundary and the held last sample is checked.
void testChunkedRefill() {
  const int16_t src[] = {0, 100, 200, 300};
  const int16_t want[] = {0, 50, 100, 150, 200, 250, 300, 300};
  int16_t got[16];
  Source source{src, 4, 0, 3, 0, 0};
  pc_resampler rs;

  pc_resampler_init(&rs, 8000, 16000);
  const size_t n = drain(&rs, &source, 1024, got, 16);
  checkSamples("8k->16k chunked", got, n, want, 8);
  // Three frames, then one, then the read that reports EOF.
  CHECK(source.reads == 3);
}

// Frame assembly: frames that end before the clip fill completely, the frame
// that reaches the end holds the last sample then zero-pads, and frames after
// that stay silent without touching the source again.
void testFrameBoundaries() {
  const int16_t src[] = {0, 100, 200, 300};
  Source source{src, 4, 0, 0, 0, 0};
  pc_resampler rs;
  pc_resampler_init(&rs, 8000, 16000);
  StreamPull pull{&rs, &source, 1024};
  int16_t frame[3];

  // Zero-length frames are a no-op that reports the stream alive.
  CHECK(pc_resampler_fill_frame(pullSample, &pull, frame, 0));

  CHECK(pc_resampler_fill_frame(pullSample, &pull, frame, 3));
  CHECK(frame[0] == 0 && frame[1] == 50 && frame[2] == 100);
  CHECK(pc_resampler_fill_frame(pullSample, &pull, frame, 3));
  CHECK(frame[0] == 150 && frame[1] == 200 && frame[2] == 250);

  // Pull 7 yields 300, pull 8 holds it, pull 9 reports the end.
  CHECK(!pc_resampler_fill_frame(pullSample, &pull, frame, 3));
  CHECK(frame[0] == 300 && frame[1] == 300 && frame[2] == 0);

  const int reads = source.reads;
  CHECK(!pc_resampler_fill_frame(pullSample, &pull, frame, 3));
  CHECK(frame[0] == 0 && frame[1] == 0 && frame[2] == 0);
  CHECK(source.reads == reads);
}

// Full-scale samples at maximum volume must not wrap; interpolation between
// the two extremes must stay inside the int16 range too.
void testFullScale() {
  int16_t got[8];
  pc_resampler rs;
  const int32_t gain = pc_resampler_gain_q10(20);
  CHECK(gain == 972);

  const int16_t hi[] = {INT16_MAX};
  Source hiSource{hi, 1, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  size_t n = drain(&rs, &hiSource, gain, got, 8);
  const int16_t wantHi[] = {31103, 31103};
  checkSamples("full-scale positive", got, n, wantHi, 2);

  const int16_t lo[] = {INT16_MIN};
  Source loSource{lo, 1, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  n = drain(&rs, &loSource, gain, got, 8);
  const int16_t wantLo[] = {-31104, -31104};
  checkSamples("full-scale negative", got, n, wantLo, 2);

  const int16_t extremes[] = {INT16_MIN, INT16_MAX};
  Source exSource{extremes, 2, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  n = drain(&rs, &exSource, 1024, got, 8);
  const int16_t wantEx[] = {-32768, -1, 32767, 32767};
  checkSamples("full-scale extremes", got, n, wantEx, 4);
}

// A clip with no frames is over on the first pull; EOF is latched so later
// pulls neither read nor write.
void testZeroLength() {
  const int16_t dummy = 0;
  Source source{&dummy, 0, 0, 0, 0, 0};
  pc_resampler rs;
  pc_resampler_init(&rs, 8000, 16000);

  int16_t out = 321;
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &out) == 0);
  CHECK(out == 321);
  CHECK(source.reads == 1);
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &out) == 0);
  CHECK(out == 321);
  CHECK(source.reads == 1);
}

void testInvalidRates() {
  const int16_t src[] = {1, 2, 3};
  Source source{src, 3, 0, 0, 0, 0};
  pc_resampler rs;
  int16_t out = 0;

  pc_resampler_init(&rs, 0, 16000);
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &out) == -EINVAL);
  pc_resampler_init(&rs, 8000, 0);
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &out) == -EINVAL);
  CHECK(source.reads == 0);
}

void testReadError() {
  const int16_t src[] = {1, 2, 3};
  Source source{src, 3, 0, 0, 0, 1};
  pc_resampler rs;
  pc_resampler_init(&rs, 8000, 16000);

  int16_t out = 0;
  CHECK(pc_resampler_next(&rs, readSource, &source, 1024, &out) == -5);
}

// Opening the next clip of a call resets the stream (window, position, EOF)
// and sets the new rate, so the second clip starts at its first sample.
void testSourceRateSwitch() {
  const int16_t first[] = {0, 100, 200, 300};
  const int16_t second[] = {5, -5, 10};
  int16_t got[16];
  pc_resampler rs;

  Source s1{first, 4, 0, 0, 0, 0};
  pc_resampler_init(&rs, 8000, 16000);
  CHECK(drain(&rs, &s1, 1024, got, 16) == 8);
  int16_t out = 0;
  CHECK(pc_resampler_next(&rs, readSource, &s1, 1024, &out) == 0);

  // The clip switch resets the stream, so the second clip plays in full at
  // its own rate (16 kHz to 16 kHz here) instead of ending immediately.
  Source s2{second, 3, 0, 0, 0, 0};
  pc_resampler_init(&rs, 16000, 16000);
  const size_t n = drain(&rs, &s2, 1024, got, 16);
  const int16_t want[] = {5, -5, 10};
  checkSamples("clip switch", got, n, want, 3);
  CHECK(s2.reads == 2);
}

// A three-clip call assembled frame by frame: every clip starts at sample 0,
// the inter-clip gap stays silent, and the final frame is zero-padded.
void testThreeClipCallFrames() {
  const int16_t a[] = {100, 100, 100};
  const int16_t b[] = {200, 200};
  const int16_t c[] = {300, 300, 300};
  TestCall call;
  call.sources[0] = Source{a, 3, 0, 0, 0, 0};
  call.sources[1] = Source{b, 2, 0, 0, 0, 0};
  call.sources[2] = Source{c, 3, 0, 0, 0, 0};

  int16_t frame[5];
  int16_t got[30];
  size_t total = 0;
  bool alive = true;
  int frames = 0;
  while (alive && frames < 6) {
    alive = pc_resampler_fill_frame(pullCallSample, &call, frame, 5);
    for (int i = 0; i < 5; ++i) got[total++] = frame[i];
    ++frames;
  }
  CHECK(frames == 5);
  CHECK(!alive);

  // 6 x 100, 3 x 0, 4 x 200, 3 x 0, 6 x 300, then the zero-padded tail.
  const int16_t want[] = {
      100, 100, 100, 100, 100, 100, 0,   0,   0,   200, 200, 200, 200,
      0,   0,   0,   300, 300, 300, 300, 300, 300, 0,   0,   0,
  };
  checkSamples("three-clip call", got, total, want, 25);

  // Each segment is non-silent and the order is preserved.
  CHECK(got[0] == 100 && got[5] == 100);
  CHECK(got[9] == 200 && got[12] == 200);
  CHECK(got[16] == 300 && got[21] == 300);

  // A frame after the call stays silent without touching any source.
  const int reads = call.sources[0].reads + call.sources[1].reads + call.sources[2].reads;
  CHECK(!pc_resampler_fill_frame(pullCallSample, &call, frame, 5));
  CHECK(frame[0] == 0 && frame[4] == 0);
  CHECK(call.sources[0].reads + call.sources[1].reads + call.sources[2].reads == reads);
}

}  // namespace

int main() {
  testGainTable();
  testApplyGain();
  testStepQ16();
  testRamp8kTo16k();
  testRamp16kTo48k();
  testVolumeScaling();
  testChunkedRefill();
  testFrameBoundaries();
  testFullScale();
  testZeroLength();
  testInvalidRates();
  testReadError();
  testSourceRateSwitch();
  testThreeClipCallFrames();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
