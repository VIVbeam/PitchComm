/*
 * PitchComm role application: portable call engine, Thread radio link,
 * buttons, OLED, LE Audio output and the USB console.
 *
 * Build (coach, USB console only, no field unit selector):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/coach -- \
 *     -DEXTRA_CONF_FILE=roles/coach.conf
 * Build (one enrolled unit; the key picks the generated unit index):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/pitcher -- \
 *     -DEXTRA_CPPFLAGS=-DPC_UNIT=PC_UNIT_pitcher \
 *     -DEXTRA_CONF_FILE="firmware/build/unit-confs/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf"
 *
 * tools/build_firmware.ps1 derives the fragments and the unit define from
 * config/roster.json; this header only needs the -DPC_UNIT shape.
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/random/random.h>

#include <new>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pc/engine.h"
#include "pc/units.h"
#include "pc/controls.h"
#include "pc/usb.h"
#include "pc/diagnostics.h"
#include "pc/display_strip.h"
#include "app/thread_link.h"

#if defined(__has_include)
#if __has_include("app/team_config.h")
#include "app/team_config.h"
#else
#include "app/team_config.example.h"
#endif
#else
#include "app/team_config.example.h"
#endif

#if defined(CONFIG_PITCHCOMM_AUDIO)
#include "app/audio_source.h"
#include "app/storage.h"
#endif
#if defined(CONFIG_PITCHCOMM_DISPLAY)
#include "board/display.h"
#endif
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU) || defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
#include "board/buttons.h"
#endif
#if defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
#include <zephyr/drivers/gpio.h>
#endif
#if defined(CONFIG_PITCHCOMM_BATTERY)
#include "board/battery.h"
#endif
#if defined(CONFIG_PITCHCOMM_CONSOLE)
#include <zephyr/console/console.h>
#endif
#if IS_ENABLED(CONFIG_SETTINGS)
#include <zephyr/settings/settings.h>
#endif

#if defined(PC_UNIT)
/* Field build: the unit selector from -DPC_UNIT=PC_UNIT_<key>. A key that is
 * not enrolled maps to 0 in catalog.h, which is only the coach. */
constexpr pc::Role kRole = PC_UNIT;
static_assert(pc::validRole(kRole), "PC_UNIT must be inside the generated roster");
#if defined(CONFIG_PITCHCOMM_ROLE_CATCHER) || defined(CONFIG_PITCHCOMM_ROLE_PITCHER) || \
	defined(CONFIG_PITCHCOMM_ROLE_SHORTSTOP) || defined(CONFIG_PITCHCOMM_ROLE_CENTERFIELD) || \
	defined(CONFIG_PITCHCOMM_AUDIO) || defined(CONFIG_PITCHCOMM_DISPLAY) || \
	defined(CONFIG_PITCHCOMM_CATCHER_MENU) || defined(CONFIG_PITCHCOMM_FIELD_BUTTON) || \
	defined(CONFIG_PITCHCOMM_BATTERY)
static_assert(kRole != pc::kCoach, "PC_UNIT names a unit that is not enrolled");
#endif
#else
/* Console-only coach build: no field unit selector. */
constexpr pc::Role kRole = pc::kCoach;
#endif

/* Capabilities come from the generated catalog, never from the key name. */
constexpr bool kAudio = pc::audioRole(kRole);
constexpr bool kDisplay = pc::displayRole(kRole);
constexpr bool kControls = pc::controlsRole(kRole);

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU) && !defined(CONFIG_PITCHCOMM_DISPLAY)
#error "The catcher menu needs the OLED display (CONFIG_PITCHCOMM_DISPLAY)"
#endif

namespace {

constexpr unsigned kEngineStackBytes = 4096;
#if defined(CONFIG_PITCHCOMM_CONSOLE)
constexpr unsigned kConsoleStackBytes = 2048;
#endif

#if defined(CONFIG_PITCHCOMM_DISPLAY)
board::Display screen;
bool displayReady = false;
#endif
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
board::CatcherControls catcherControls;
pc::CatcherMenu catcherMenu;
uint32_t catcherTouchedAt = 0;
uint32_t catcherCallAt = 0;
uint16_t lastRequestCode = 0;
#endif
#if defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
board::Button recall;
#endif
#if defined(CONFIG_PITCHCOMM_BATTERY)
board::Battery battery;
#endif

pc::UsbGate usbGate{kRole};
pc::I2cScan i2cScan;

bool linkStartFault = false;
#if IS_ENABLED(CONFIG_SETTINGS)
bool settingsReady = false;
#endif
bool requestNotified = false;
bool linkWarned = false;
uint32_t linkNotReadySince = 0;
#if defined(CONFIG_PITCHCOMM_DISPLAY)
uint32_t lastFrame = 0;
#endif
uint32_t lastDiag = 0;
uint32_t lastInteraction = 0;
uint32_t messageAt = 0;
char message[32] = "";
uint32_t lastOutputSeen = 0;

struct Inbound {
	uint8_t source;
	uint8_t bytes[pc::kPacketBytes];
	uint32_t receivedAt;
};

/*
 * Statically allocated inbox; initialized in appSetup() with k_msgq_init()
 * to avoid relying on C99 designated initializers in C++.
 */
alignas(4) char inboxBuffer[24 * sizeof(Inbound)];
struct k_msgq inbox;

atomic_t inboundDropped = 0;
atomic_t decodeErrors = 0;

/* No dynamic allocation: the engine lives in a static, aligned buffer. */
alignas(pc::Engine) unsigned char engineStorage[sizeof(pc::Engine)];
pc::Engine *engine = nullptr;

/* Only pure engine work, radio enqueue and bounded audio-request copies run
 * under this mutex. Never hold it across OLED/ADC/settings/printf work. */
K_MUTEX_DEFINE(engineLock);
struct EngineGuard {
  EngineGuard() { (void)k_mutex_lock(&engineLock,K_FOREVER); }
  ~EngineGuard() { (void)k_mutex_unlock(&engineLock); }
  EngineGuard(const EngineGuard&)=delete;
  EngineGuard& operator=(const EngineGuard&)=delete;
};
pc::EngineView engineView() {
  const EngineGuard guard;
  return engine ? engine->view() : pc::EngineView{};
}
void completeOutput(uint64_t revision,bool ok,uint32_t now) {
  const EngineGuard guard;
  if(engine) engine->outputCompleted(revision,ok,now);
}
#if defined(CONFIG_PITCHCOMM_DISPLAY)
void failOutput(const pc::Output& out,uint32_t now) {
  const EngineGuard guard;
  if(engine && engine->hasOutput() && engine->output().revision==out.revision)
    engine->outputFailed(out.sequence,now);
}
#endif

/* One latest-output slot: a newer call or clear supersedes an older pending
 * screen frame. Each completion is checked against a unique engine revision.
 * Lock order is engine -> event. UI releases event before taking engine. */
struct OutputEvent { pc::Output output{};bool clear=false; };
K_MUTEX_DEFINE(outputEventLock);
OutputEvent outputEvent;
bool outputEventPending=false;
void publishOutput(const pc::Output& out,bool clear=false) {
  (void)k_mutex_lock(&outputEventLock,K_FOREVER);
  outputEvent={out,clear};outputEventPending=true;
  (void)k_mutex_unlock(&outputEventLock);
}
bool takeOutput(OutputEvent& event) {
  (void)k_mutex_lock(&outputEventLock,K_FOREVER);
  const bool pending=outputEventPending;
  if(pending) {event=outputEvent;outputEventPending=false;}
  (void)k_mutex_unlock(&outputEventLock);
  return pending;
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
struct ConsoleLine { char text[192]{}; };
alignas(4) char consoleBuffer[4*sizeof(ConsoleLine)];
struct k_msgq consoleLines;
atomic_t consoleDropped=0;
#endif

uint32_t now32()
{
	return k_uptime_get_32();
}

bool provisioned()
{
	return PC_TEAM_CONFIGURED != 0;
}

bool linkReady()
{
	return provisioned() && pc_link_ready();
}

void screenWake()
{
#if defined(CONFIG_PITCHCOMM_DISPLAY)
	screen.wake();
#endif
}

void note(const char *text)
{
	snprintf(message, sizeof(message), "%s", text);
	messageAt = now32();
	printf("%s\n", text);
	screenWake();
}

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
bool audioIsReady()
{
#if defined(CONFIG_PITCHCOMM_AUDIO)
	return kAudio ? pc_audio_ready() : true;
#else
	return true;
#endif
}
#endif

const char *resultName(pc::Submit value)
{
	switch (value) {
	case pc::Submit::Accepted:
		return "SENDING";
	case pc::Submit::Busy:
		return "BUSY: TRY AGAIN";
	case pc::Submit::Offline:
		return "COACH OFFLINE";
	case pc::Submit::Expired:
		return "STALE USB CALL";
	case pc::Submit::Incompatible:
		return "USB SESSION CHANGED";
	default:
		return "INVALID CALL";
	}
}

const char *deliveryName(pc::Delivery value)
{
	switch (value) {
	case pc::Delivery::Pending:
		return "WAIT";
	case pc::Delivery::Delivered:
		return "OK";
	case pc::Delivery::Missing:
		return "MISS";
	case pc::Delivery::OutputError:
		return "ERR";
	default:
		return "--";
	}
}

void settingsBegin()
{
#if IS_ENABLED(CONFIG_SETTINGS)
	if (settings_subsys_init() != 0) {
		return;
	}
	settingsReady = true;

	/*
	 * VERIFY(settings load): settings_load_one() returns the value length on
	 * success (ssize_t), not 0; check for our single byte.
	 */
	uint8_t value = 0;

	if (settings_load_one("pitchcomm/volume", &value, sizeof(value)) ==
	    (ssize_t)sizeof(value) && value >= 1 && value <= 20) {
#if defined(CONFIG_PITCHCOMM_AUDIO)
		pc_audio_set_volume(value);
#endif
	}
#endif
}

void settingsSaveVolume(uint8_t value)
{
#if IS_ENABLED(CONFIG_SETTINGS)
	if (settingsReady) {
		(void)settings_save_one("pitchcomm/volume", &value, sizeof(value));
	}
#else
	ARG_UNUSED(value);
#endif
}

class AppHooks : public pc::Hooks {
 public:
	bool send(const pc::Packet& p) override
	{
		if (!linkReady() || !pc::validRole(p.target)) {
			return false;
		}

		uint8_t bytes[pc::kPacketBytes];

		pc::encode(p, bytes);
		return pc_link_send(uint8_t(p.target), bytes, pc::kPacketBytes);
	}

  bool present(const pc::Output& out) override {
    const auto* call=pc::findCall(out.category,out.code);
    if(!call) return false;
#if defined(CONFIG_PITCHCOMM_AUDIO)
    if(kAudio && !pc_audio_play(call->audio[0],call->audio[1],call->audio[2])) return false;
#endif
    publishOutput(out);
    return true;
  }
  bool deferOutput() const override {
    return kDisplay && !kAudio && kRole!=pc::kCoach;
  }
  void clearOutput() override {
#if defined(CONFIG_PITCHCOMM_AUDIO)
    pc_audio_stop();
#endif
    publishOutput(pc::Output{},true);
  }

};

AppHooks hooks;

/* This function and all UI state below run only on the main UI thread. */
pc::UsbResult submitResult(pc::Category category,uint16_t code,uint32_t now) {
  if(!engine || !provisioned() || linkStartFault || !linkReady()) {
    note("SETUP REQUIRED");return {pc::Submit::Offline,0};
  }
  pc::UsbResult result;
  {
    const EngineGuard guard;
    result.result=engine->submit(category,code,now);
    if(result.result==pc::Submit::Accepted && kRole==pc::kCoach)
      result.sequence=engine->output().sequence;
  }
  note(resultName(result.result));requestNotified=false;return result;
}
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
pc::Submit submit(pc::Category category,uint16_t code,uint32_t now) {
  return submitResult(category,code,now).result;
}
#endif

void serviceOutput(uint32_t now) {
  OutputEvent event;
  if(!takeOutput(event)) return;
  if(event.clear) {
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
    catcherCallAt=0;catcherMenu.cancel();
#endif
    lastOutputSeen=0;screenWake();return;
  }
  auto view=engineView();
  if(!view.hasOutput || view.output.revision!=event.output.revision) return;
  if(view.outputPending && pc::elapsed(now,view.output.receivedAt)>=view.outputWindow) {
    completeOutput(event.output.revision,false,now);return;
  }
  const auto* call=pc::findCall(event.output.category,event.output.code);
  if(!call) {completeOutput(event.output.revision,false,now);return;}
  bool ok=true;
#if defined(CONFIG_PITCHCOMM_DISPLAY)
  if(kDisplay && !kAudio && kRole!=pc::kCoach) {
    screenWake();
    ok=displayReady && screen.strip(call->label,"CALL");
    if(!ok) {displayReady=false;note("DISPLAY DISCONNECTED");}
  }
#endif
  completeOutput(event.output.revision,ok,now32());
  view=engineView();
  if(!view.hasOutput || view.output.revision!=event.output.revision) return;
  lastOutputSeen=event.output.sequence;lastInteraction=now32();screenWake();
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
  if(kControls) catcherCallAt=lastInteraction;
#endif
  printf("CALL #%lu %s\n",static_cast<unsigned long>(event.output.sequence),call->label);
}

void repeat(uint32_t now)
{
	const auto view=engineView();
	lastInteraction = now;
	screenWake();

	if (engine == nullptr || !view.hasOutput) {
		note("NO CALL TO RECALL");
		return;
	}

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	/* A controls unit has no audio: re-show the received call on the OLED. */
	if (kControls) {
		if (view.outputOld(now)) {
			note("CALL TOO OLD");
			return;
		}
		catcherCallAt = now;
		screenWake();
		return;
	}
#endif

	/* Old or disconnected audio is never silently replayed. */
	if (kAudio) {
		if (!linkReady() || !view.linked) {
			note("NO LINK TO RECALL");
			return;
		}
		if (view.outputOld(now)) {
			note("CALL TOO OLD");
			return;
		}
#if defined(CONFIG_PITCHCOMM_AUDIO)
		if (pc_audio_busy()) {
			note("AUDIO PLAYING");
			return;
		}
		const auto* call = pc::findCall(view.output.category, view.output.code);

        bool recalled=false;
        if(call) {
          const EngineGuard guard;
          // A resync/new call between the view and this action must not queue
          // recall after the engine cleared its output.
          recalled=engine->hasOutput() && engine->linked() &&
                   engine->output().revision==view.output.revision &&
                   !engine->outputOld(now32()) && pc_audio_ready() &&
                   !pc_audio_busy() && pc_audio_recall();
        }
		if (!recalled) {
			note("AUDIO NOT READY");
		}
#endif
	}
}

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU) || defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
void cycleVolume()
{
	if (!kAudio) {
		return;
	}

#if defined(CONFIG_PITCHCOMM_AUDIO)
	/* Retry the saved earbud without recalling a prior call. */
	if (!pc_audio_ready()) {
		pc_audio_reconnect();
		note("HEADSET RETRY");
		return;
	}

	const unsigned current = pc_audio_volume();
	const unsigned next = current >= 16 ? 4 : ((current / 4) + 1) * 4;

	pc_audio_set_volume(uint8_t(next));
	settingsSaveVolume(uint8_t(next));

	char text[24];

	snprintf(text, sizeof(text), "VOLUME %u PERCENT", next);
	note(text);
#endif
}
#endif

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
void handleCatcher(unsigned input, uint32_t now)
{
	catcherCallAt = 0;
	lastInteraction = now;
	catcherTouchedAt = now;
	screenWake();

	const auto action = input <= 4 ? catcherMenu.front(input) : catcherMenu.back(input == 6);

	switch (action) {
	case pc::CatcherMenu::Action::Send:
		/*
		 * The screen defines each numbered button's meaning. Probe a fresh
		 * frame before sending so an unplugged OLED cannot authorize a
		 * blind call.
		 */
		if (!displayReady || !screen.menu(catcherMenu.frame())) {
			displayReady = false;
			note("DISPLAY NOT READY");
			break;
		}
		if (!catcherControls.available()) {
			note("CONTROLS NOT READY");
			break;
		}
		if (!audioIsReady()) {
			note("HEADSET NOT READY");
			break;
		}
		catcherMenu.commit(displayReady, catcherControls.available(), audioIsReady(),
				   [&](uint16_t code) {
					   lastRequestCode = code;
					   return submit(pc::Category::Pitch, code, now) ==
						  pc::Submit::Accepted;
				   });
		break;
	case pc::CatcherMenu::Action::Recall:
		repeat(now);
		break;
	case pc::CatcherMenu::Action::Volume:
		cycleVolume();
		break;
	case pc::CatcherMenu::Action::Cancel:
		note("DRAFT CANCELLED");
		break;
	default:
		break;
	}
}
#endif /* CONFIG_PITCHCOMM_CATCHER_MENU */

void formatEui(char out[17])
{
	uint8_t eui[8] = {0};

	pc_link_local_eui64(eui);
	for (unsigned i = 0; i < 8; ++i) {
		snprintf(out + (i * 2), 3, "%02x", eui[i]);
	}
}

void diagnostics()
{
	const auto view=engineView();
	char eui[17];

	formatEui(eui);

	char batteryText[24];

#if defined(CONFIG_PITCHCOMM_BATTERY)
	snprintf(batteryText, sizeof(batteryText), "%lumV",
		      static_cast<unsigned long>(battery.millivolts()));
#else
	snprintf(batteryText, sizeof(batteryText), "N/A");
#endif

#if defined(CONFIG_PITCHCOMM_AUDIO)
	const char *audioText = pc_audio_state();
	const unsigned volume = pc_audio_volume();
#else
	const char *audioText = "N/A";
	const unsigned volume = 0;
#endif

#if defined(CONFIG_PITCHCOMM_DISPLAY)
	const char *oledText = displayReady ? "READY" : "NOT READY";
#else
	const char *oledText = "N/A";
#endif

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	const bool controlsReady = catcherControls.available();
#else
	const bool controlsReady = true;
#endif

	printf("UNIT=%s EUI=%s CONFIG=%s LINK=%s DICT=%08lx BATT=%s AUDIO=%s OLED=%s "
		    "CONTROLS=%s VOL=%u RX_DROP=%lu RX_BAD=%lu TX_ERR=%lu TX_DROP=%lu "
		    "IN_DROP=%lu\n",
		    pc::roleName(kRole), eui, provisioned() ? "YES" : "NO", pc_link_state(),
		    static_cast<unsigned long>(pc::kDictionary), batteryText, audioText,
		    oledText, controlsReady ? "READY" : "NOT READY", volume,
		    static_cast<unsigned long>(pc_link_rx_dropped()),
		    static_cast<unsigned long>(atomic_get(&decodeErrors)),
		    static_cast<unsigned long>(pc_link_tx_errors()),
		    static_cast<unsigned long>(pc_link_tx_dropped()),
		    static_cast<unsigned long>(atomic_get(&inboundDropped)));

	if (engine != nullptr && kRole == pc::kCoach) {
		for (unsigned i = 1; i < pc::kUnitCount; ++i) {
			printf("%s LINK=%s DELIVERY=%s\n", pc::kUnitLabel[i],
				    view.ready[i] ? "UP" : "DOWN",
				    deliveryName(view.delivery[i]));
		}
	}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
/* Append comma-separated decimal values for a compact JSON array; index 0 is
 * the coach and every caller reports it as 0. */
template <class Value>
void appendUnitJson(char *out, size_t size, Value value)
{
	size_t used = 0;

	if (size == 0) {
		return;
	}
	out[0] = '\0';
	for (unsigned i = 0; i < pc::kUnitCount && used + 8 < size; ++i) {
		const int written = snprintf(out + used, size - used, "%s%u",
					     i == 0 ? "" : ",", unsigned(value(i)));

		if (written <= 0 || static_cast<size_t>(written) >= size - used) {
			break;
		}
		used += static_cast<size_t>(written);
	}
}

void guiState()
{
	const auto view=engineView();
	if (engine == nullptr) {
		return;
	}

	const auto out = view.hasOutput ? view.output : pc::Output{};
	const auto& pitch = view.records[0];
	const auto& play = view.records[1];
	char links[4 * pc::kMaxUnits];
	char delivery[4 * pc::kMaxUnits];
	char pitchDelivery[4 * pc::kMaxUnits];
	char playDelivery[4 * pc::kMaxUnits];

	appendUnitJson(links, sizeof(links), [&](unsigned i) {
		return i != 0 && view.ready[i] ? 1u : 0u;
	});
	appendUnitJson(delivery, sizeof(delivery), [&](unsigned i) {
		return i == 0 ? 0u : unsigned(view.delivery[i]);
	});
	appendUnitJson(pitchDelivery, sizeof(pitchDelivery), [&](unsigned i) {
		return i == 0 ? 0u : unsigned(pitch.delivery[i]);
	});
	appendUnitJson(playDelivery, sizeof(playDelivery), [&](unsigned i) {
		return i == 0 ? 0u : unsigned(play.delivery[i]);
	});

	printf("@PC {\"type\":\"state\",\"v\":4,\"client\":\"%08lx\",\"clock\":%lu,"
		    "\"role\":%u,\"dictionary\":\"%08lx\",\"configured\":%u,\"radio\":%u,"
		    "\"busy\":%u,\"boot\":\"%016llx\",\"seq\":%lu,\"category\":%u,\"code\":%u,"
		    "\"links\":[%s],\"delivery\":[%s],"
		    "\"records\":[{\"category\":1,\"seq\":%lu,\"code\":%u,\"delivery\":[%s]},"
		    "{\"category\":2,\"seq\":%lu,\"code\":%u,\"delivery\":[%s]}]}\n",
		    static_cast<unsigned long>(usbGate.client()),
		    static_cast<unsigned long>(now32()), unsigned(kRole),
		    static_cast<unsigned long>(pc::kDictionary), unsigned(provisioned()),
		    unsigned(pc_link_ready()), unsigned(view.busy),
		    static_cast<unsigned long long>(view.boot),
		    static_cast<unsigned long>(out.sequence), unsigned(out.category),
		    unsigned(out.code), links, delivery,
		    static_cast<unsigned long>(pitch.output.sequence),
		    unsigned(pitch.output.code), pitchDelivery,
		    static_cast<unsigned long>(play.output.sequence),
		    unsigned(play.output.code), playDelivery);
}
#endif /* CONFIG_PITCHCOMM_CONSOLE */

void reportOutputFailures()
{
	const auto view=engineView();
	if (engine == nullptr || kRole != pc::kCoach) {
		return;
	}

	static uint32_t reported[2][pc::kUnitCount]{};

	for (unsigned index = 0; index < 2; ++index) {
		const auto& record = view.records[index];

		for (unsigned i = 1; i < pc::kUnitCount; ++i) {
			if (record.delivery[i] != pc::Delivery::OutputError ||
			    !record.output.sequence || reported[index][i] == record.output.sequence) {
				continue;
			}
			reported[index][i] = record.output.sequence;

			char text[32];

			snprintf(text, sizeof(text), "%s FAIL #%lu", pc::kUnitShort[i],
				      static_cast<unsigned long>(record.output.sequence));
			note(text);
		}
	}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
void selftest(uint32_t now)
{
	char eui[17];

	formatEui(eui);
	printf("SELFTEST UNIT=%s EUI=%s CONFIG=%s LINK=%s\n", pc::roleName(kRole), eui,
	       provisioned() ? "YES" : "NO", pc_link_state());

#if defined(CONFIG_PITCHCOMM_DISPLAY)
	printf("SELFTEST OLED=%s\n", board::Display::probe(0x3C) ? "PASS" : "FAIL");
#else
	printf("SELFTEST OLED=SKIP (no display on this unit)\n");
#endif

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	printf("SELFTEST CONTROLS=%s\n", catcherControls.available() ? "PASS" : "FAIL");
#elif defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
	/*
	 * Button::begin() is void; run it and confirm the same D1 pin (P1.05 =
	 * gpio1 pin 5) is configured and readable through the public GPIO API.
	 */
	recall.begin();

	const struct device *gpio1 = DEVICE_DT_GET(DT_NODELABEL(gpio1));
	const bool controlsOk = device_is_ready(gpio1) &&
				gpio_pin_configure(gpio1, 5, GPIO_INPUT | GPIO_PULL_UP) == 0 &&
				gpio_pin_get_raw(gpio1, 5) >= 0;

	printf("SELFTEST CONTROLS=%s\n", controlsOk ? "PASS" : "FAIL");
#else
	printf("SELFTEST CONTROLS=SKIP (no controls on this unit)\n");
#endif

#if defined(CONFIG_PITCHCOMM_BATTERY)
	battery.tick(now);
	printf("SELFTEST BATTERY=%lumV LOW=%s\n",
	       (unsigned long)battery.millivolts(), battery.low() ? "YES" : "NO");
#else
	ARG_UNUSED(now);
	printf("SELFTEST BATTERY=SKIP (no battery sense)\n");
#endif

#if defined(CONFIG_PITCHCOMM_AUDIO)
	printf("SELFTEST STORAGE=%s DICT=%08lx\n", pc_storage_ready() ? "READY" : "OFFLINE",
	       (unsigned long)pc_storage_dictionary());
	printf("SELFTEST AUDIO=%s READY=%u BUSY=%u VOL=%u\n", pc_audio_state(),
	       pc_audio_ready() ? 1u : 0u, pc_audio_busy() ? 1u : 0u,
	       (unsigned)pc_audio_volume());
#else
	printf("SELFTEST STORAGE=SKIP (no audio on this unit)\n");
	printf("SELFTEST AUDIO=SKIP (no audio on this unit)\n");
#endif

#if IS_ENABLED(CONFIG_SETTINGS)
	printf("SELFTEST SETTINGS=%s\n", settingsReady ? "READY" : "OFFLINE");
#else
	printf("SELFTEST SETTINGS=SKIP (settings disabled)\n");
#endif

	printf("SELFTEST DONE\n");
}

void serialInput(char *line, uint32_t now)
{
	const auto view=engineView();
	if (strcmp(line, "status") == 0) {
		diagnostics();
	} else if (strcmp(line, "selftest") == 0) {
		selftest(now);
	} else if (strcmp(line, "gui") == 0 || strncmp(line, "gui ", 4) == 0) {
		static uint32_t lastState = 0;
		uint32_t client = 0;

		if (strcmp(line, "gui") != 0 && !pc::parseGuiClient(line, client)) {
			note("INVALID GUI SESSION");
		} else {
			if (client) {
				usbGate.begin(client);
			}
			if (pc::elapsed(now, lastState) >= 250) {
				lastState = now;
				guiState();
			}
		}
	} else if (strncmp(line, "call ", 5) == 0) {
		pc::UsbCall call;

		if (!pc::parseUsbCall(line, call)) {
			note("INVALID COMPLETE CALL");
		} else {
			const auto response =
				usbGate.execute(call, view.boot, pc::kDictionary, now,
						[&]() {
              return submitResult(call.category,call.code,now);
						});

			printf("@PC {\"type\":\"result\",\"v\":4,\"client\":\"%08lx\","
				    "\"boot\":\"%016llx\",\"id\":%lu,\"result\":%u,"
				    "\"seq\":%lu}\n",
				    static_cast<unsigned long>(call.client),
				    static_cast<unsigned long long>(view.boot),
				    static_cast<unsigned long>(call.id),
				    unsigned(response.result),
				    static_cast<unsigned long>(response.sequence));
		}
	} else if (strcmp(line, "repeat") == 0) {
		repeat(now);
	} else if (strcmp(line, "help") == 0) {
		printf("status | selftest | eui | gui [CLIENT8HEX] | call CLIENT ID t TYPE BOOT DICT DEADLINE | call CLIENT ID l TYPE HEIGHT SIDE BOOT DICT DEADLINE | call CLIENT ID p TYPE "
		       "HEIGHT SIDE BOOT16HEX DICT8HEX DEADLINE | call CLIENT ID d PLAY "
		       "BOOT DICT DEADLINE | repeat | vol 1..20 | scan\n");
	} else if (strcmp(line, "eui") == 0) {
		char eui[17];

		formatEui(eui);
		printf("EUI=%s LINK=%s\n", eui, pc_link_state());
	} else if (strcmp(line, "scan") == 0) {
		note(i2cScan.start() ? "I2C SCAN STARTED" : "I2C SCAN ALREADY RUNNING");
	} else if (strncmp(line, "vol ", 4) == 0) {
		char *end = nullptr;
		const long value = strtol(line + 4, &end, 10);

		if (end == line + 4 || *end || value < 1 || value > 20) {
			note("VOLUME 1 TO 20");
		} else {
#if defined(CONFIG_PITCHCOMM_AUDIO)
			pc_audio_set_volume(uint8_t(value));
#endif
			settingsSaveVolume(uint8_t(value));
			note("VOLUME SAVED");
		}
	} else if (line[0]) {
		note("UNKNOWN: TYPE HELP");
	}
}
#endif /* CONFIG_PITCHCOMM_CONSOLE */

void scanI2c()
{
	if (!i2cScan.active()) {
		return;
	}

#if defined(CONFIG_PITCHCOMM_DISPLAY)
	/*
	 * Exactly one bus probe per loop. A disconnected bus must
	 * not turn the diagnostic into 126 consecutive timeouts that stall the
	 * UI. "I2C SCAN STARTED" is printed by the command handler.
	 */
	const uint8_t address = i2cScan.tick([](uint8_t candidate) {
		return board::Display::probe(candidate);
	});

	if (address) {
		printf("I2C 0x%02x\n", (unsigned)address);
	}
	if (!i2cScan.active()) {
		note("I2C SCAN COMPLETE");
	}
#else
	/*
	 * Roles without a display have no public bus probe; complete the request
	 * without issuing transactions. The GUI does not depend on this command.
	 */
	while (i2cScan.tick([](uint8_t) { return false; }) != 0) {
	}
	printf("I2C SCAN NOT SUPPORTED\n");
#endif
}

void draw(uint32_t now)
{
	const auto view=engineView();
#if defined(CONFIG_PITCHCOMM_DISPLAY)
	if (!displayReady || screen.sleeping() || pc::elapsed(now, lastFrame) < 150) {
		return;
	}
	lastFrame = now;

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	/* A received call owns the panel briefly, then the selection menu returns. */
	if (!catcherMenu.draft() && lastOutputSeen != 0 &&
	    pc::elapsed(now, catcherCallAt) < 4000) {
		const char *label = "CALL";

		if (view.hasOutput) {
			if (const auto* call =
				    pc::findCall(view.output.category, view.output.code)) {
				label = call->label;
			}
		}
		if (screen.strip(label, "CALL")) {
			return;
		}
		displayReady = false;
		if (view.hasOutput) {
			failOutput(view.output, now);
		}
		note("DISPLAY DISCONNECTED");
		return;
	}

	auto frame = catcherMenu.frame();
	const char *notice = nullptr;

	if (!provisioned()) {
		notice = "USB SETUP REQUIRED";
	} else if (linkStartFault) {
		notice = "RADIO SETUP ERROR";
	} else if (!pc_link_ready()) {
		notice = "RADIO NOT READY";
	} else if (!catcherControls.available()) {
		notice = "CONTROLS NOT READY";
	} else if (!view.linked) {
		notice = view.incompatible ? "DICTIONARY ERROR" : "COACH NOT LINKED";
	} else if (!audioIsReady()) {
		notice = "HEADSET NOT READY";
	} else if (view.busy) {
		notice = "CALL PENDING";
	} else if (message[0] && pc::elapsed(now, messageAt) < 2000) {
		notice = message;
	}
	if (notice != nullptr) {
		snprintf(frame.footer, sizeof(frame.footer), "%.21s", notice);
	}
	if (!screen.menu(frame)) {
		displayReady = false;
		note("DISPLAY DISCONNECTED");
	}
#else
	/* Shortstop / center field: one large call label plus a status word. */
	const char *play = "READY";
	const bool hasCall = view.hasOutput;

	if (hasCall) {
		if (const auto* call =
			    pc::findCall(view.output.category, view.output.code)) {
			play = call->label;
		}
	}

	const pc::StripState state{provisioned(), !linkStartFault && pc_link_ready(),
				   view.linked, view.incompatible,
				   hasCall && view.outputOld(now), hasCall};

	if (!screen.strip(play, pc::stripStatus(state))) {
		displayReady = false;
		if (hasCall) {
			failOutput(view.output, now);
		}
		note("DISPLAY DISCONNECTED");
	}
#endif
#else
	ARG_UNUSED(view);
	ARG_UNUSED(now);
#endif /* CONFIG_PITCHCOMM_DISPLAY */
}

void receiveLink(uint8_t source, const uint8_t *bytes, size_t len)
{
	if (len != pc::kPacketBytes || source >= pc::kUnitCount) {
		atomic_inc(&decodeErrors);
		return;
	}

	Inbound in{};

	in.source = source;
	memcpy(in.bytes, bytes, pc::kPacketBytes);
	in.receivedAt = now32();

	if (k_msgq_put(&inbox, &in, K_NO_WAIT) != 0) {
		atomic_inc(&inboundDropped);
	}
}

void engineStep()
{
		Inbound in;

		/* Bounded drain: a noisy link must not starve tick(). */
		for (unsigned budget = 0; budget < 12; ++budget) {
			if (k_msgq_get(&inbox, &in, K_NO_WAIT) != 0) {
				break;
			}

			pc::Packet packet;

			if (!pc::decode(in.bytes, pc::kPacketBytes, packet) ||
			    in.source >= pc::kUnitCount || pc::Role(in.source) == kRole) {
				atomic_inc(&decodeErrors);
				continue;
			}
			if (engine != nullptr) {
                const EngineGuard guard;
                const uint32_t receivedNow=now32();
                engine->receive(pc::Role(in.source),packet,receivedNow,
                                pc::elapsed(receivedNow,in.receivedAt));
			}
		}

		if (engine != nullptr) {
            const EngineGuard guard;
            engine->tick(now32());
        }
}
void engineThread(void *arg1,void *arg2,void *arg3) {
  ARG_UNUSED(arg1);ARG_UNUSED(arg2);ARG_UNUSED(arg3);
  for(;;) {engineStep();k_msleep(1);}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
void enqueueConsole(const char* line) {
  ConsoleLine item;
  const size_t length=strlen(line);
  if(length>=sizeof(item.text)) {atomic_inc(&consoleDropped);return;}
  memcpy(item.text,line,length+1);
  if(k_msgq_put(&consoleLines,&item,K_MSEC(50))!=0) atomic_inc(&consoleDropped);
}
void consoleThread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	for (;;) {
		char *line = console_getline();

		if (line == nullptr) {
			k_msleep(10);
			continue;
		}
        enqueueConsole(line);
	}
}
#endif

void appSetup()
{
	const uint32_t now = now32();

	k_msgq_init(&inbox, inboxBuffer, sizeof(Inbound), 24);
#if defined(CONFIG_PITCHCOMM_CONSOLE)
    k_msgq_init(&consoleLines,consoleBuffer,sizeof(ConsoleLine),4);
#endif
	lastInteraction = now;
	linkNotReadySince = now;

#if defined(CONFIG_PITCHCOMM_DISPLAY)
	displayReady = screen.begin();
#endif
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	catcherControls.begin();
#endif
#if defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
	recall.begin();
#endif
#if defined(CONFIG_PITCHCOMM_BATTERY)
	battery.begin();
	battery.tick(now);
#endif
#if defined(CONFIG_PITCHCOMM_AUDIO)
	if (kAudio) {
		(void)pc_audio_start();
	}
#endif

	settingsBegin();

	const uint64_t boot =
		(static_cast<uint64_t>(sys_rand32_get()) << 32) |
		static_cast<uint64_t>(sys_rand32_get());

	engine = new (engineStorage) pc::Engine(kRole, boot, hooks);

	linkStartFault = pc_link_start(uint8_t(kRole), receiveLink) != 0;

	printf("PITCHCOMM %s boot=%016llx config=%u link=%s\n", pc::roleName(kRole),
		    static_cast<unsigned long long>(engine->boot()),
		    unsigned(provisioned()), pc_link_state());
	diagnostics();
}

void loop()
{
	uint32_t now = now32();
    serviceOutput(now);
#if defined(CONFIG_PITCHCOMM_CONSOLE)
    static atomic_val_t reportedConsoleDrops=0;
    const auto dropped=atomic_get(&consoleDropped);
    if(dropped!=reportedConsoleDrops) {
      reportedConsoleDrops=dropped;note("CONSOLE QUEUE FULL");
    }
    for(unsigned budget=0;budget<2;++budget) {
      ConsoleLine line;
      if(k_msgq_get(&consoleLines,&line,K_NO_WAIT)!=0) break;
      serialInput(line.text,now32());
    }
#endif
    now=now32();
#if defined(CONFIG_PITCHCOMM_BATTERY)
	battery.tick(now);
	now = now32();
#endif

	/*
	 * Watchdog: a provisioned unit that never attaches logs once and keeps
	 * running. The engine keeps retrying its handshake.
	 */
	if (provisioned() && !linkStartFault && !pc_link_ready()) {
		if (!linkWarned && pc::elapsed(now, linkNotReadySince) > 5000) {
			linkWarned = true;
			printf("LINK NOT READY: %s\n", pc_link_state());
		}
	} else {
		linkNotReadySince = now;
		linkWarned = false;
	}

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
    const auto requestView=engineView();
	if (engine != nullptr && requestView.requestFinished && !requestNotified &&
	    kControls) {
		requestNotified = true;
		switch (requestView.requestResult) {
		case pc::Status::Ok:
			catcherMenu.confirmed(lastRequestCode);
			note("COACH ACCEPTED");
			break;
		case pc::Status::Busy:
			catcherMenu.restore(lastRequestCode);
			note("COACH BUSY: RESEND");
			break;
		case pc::Status::Invalid:
			catcherMenu.rejected(lastRequestCode);
			note("CHOOSE PITCH AGAIN");
			break;
		default:
			catcherMenu.restore(lastRequestCode);
			note("CALL STATUS UNKNOWN");
			break;
		}
	}
#endif

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	if (const auto input = catcherControls.tick(now)) {
		handleCatcher(input, now);
	}
	if (catcherMenu.draft() && pc::elapsed(now, catcherTouchedAt) > pc::kPitchDecisionWindow) {
		catcherMenu.cancel();
		note("DRAFT EXPIRED");
	}
#elif defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
	const auto recallEvent = recall.tick(now);

	if (recallEvent == board::Button::Event::Press) {
		repeat(now);
	} else if (recallEvent == board::Button::Event::LongPress) {
		cycleVolume();
	}
#endif

	reportOutputFailures();
	scanI2c();
	now = now32();
	draw(now);

#if defined(CONFIG_PITCHCOMM_DISPLAY)
	if (kRole != pc::kCoach && kDisplay && engine != nullptr &&
	    engineView().linked && pc::elapsed(now, lastInteraction) > 30000) {
		screen.sleep();
	}
#endif

	if (linkStartFault && pc::elapsed(now, lastDiag) >= 3000) {
		lastDiag = now;
		diagnostics();
	}

	k_msleep(1);
}

K_THREAD_STACK_DEFINE(engineStack, kEngineStackBytes);
struct k_thread engineThreadData;
#if defined(CONFIG_PITCHCOMM_CONSOLE)
K_THREAD_STACK_DEFINE(consoleStack, kConsoleStackBytes);
struct k_thread consoleThreadData;
#endif

}  // namespace

int main(void)
{
#if defined(CONFIG_PITCHCOMM_CONSOLE)
	console_getline_init();
#endif

	/*
	 * The UI loop is the lowest-priority application thread. A full OLED
	 * frame is a multi-millisecond I2C transfer and must not delay the
	 * radio, audio or engine threads.
	 */
	k_thread_priority_set(k_current_get(), K_PRIO_PREEMPT(7));

	appSetup();

	k_thread_create(&engineThreadData, engineStack, K_THREAD_STACK_SIZEOF(engineStack),
			engineThread, nullptr, nullptr, nullptr, K_PRIO_PREEMPT(6), 0,
			K_NO_WAIT);
	k_thread_name_set(&engineThreadData, "engine");

#if defined(CONFIG_PITCHCOMM_CONSOLE)
	k_thread_create(&consoleThreadData, consoleStack, K_THREAD_STACK_SIZEOF(consoleStack),
			consoleThread, nullptr, nullptr, nullptr, K_PRIO_PREEMPT(7), 0,
			K_NO_WAIT);
	k_thread_name_set(&consoleThreadData, "console");
#endif

	/* The main thread is the UI, button and display loop. */
	for (;;) {
		loop();
	}

	return 0;
}
