/*
 * PitchComm role application: portable call engine, Thread radio link,
 * buttons, OLED, LE Audio output and the USB console.
 *
 * Build (coach, USB console only):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/coach -- \
 *     -DEXTRA_CONF_FILE=roles/coach.conf
 * Build (pitcher, Thread SED + LE Audio):
 *   west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/pitcher -- \
 *     -DEXTRA_CONF_FILE="roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf"
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/random/random.h>

#include <new>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pc/engine.h"
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
#endif
#if defined(CONFIG_PITCHCOMM_DISPLAY)
#include "board/display.h"
#endif
#if defined(CONFIG_PITCHCOMM_CATCHER_MENU) || defined(CONFIG_PITCHCOMM_FIELD_BUTTON)
#include "board/buttons.h"
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

#if defined(CONFIG_PITCHCOMM_ROLE_AUDIO_PROOF)

/* ------------------------------------------------------------------ */
/* Bench proof build: LE Audio only; no Thread stack and no engine.   */
/* ------------------------------------------------------------------ */

int main(void)
{
	printf("PITCHCOMM AUDIO PROOF\n");

	const int startError = pc_audio_start();

	printf("AUDIO START rc=%d\n", startError);

	bool played = false;

	for (;;) {
		if (!played && pc_audio_ready()) {
			played = pc_audio_play("/audio/p01.wav", "/audio/h1.wav",
					       "/audio/s1.wav");
			printf("AUDIO PLAY queued=%d\n", played ? 1 : 0);
		}

		printf("AUDIO state=%s ready=%u busy=%u vol=%u frame_us=%lu\n",
			    pc_audio_state(), pc_audio_ready() ? 1u : 0u,
			    pc_audio_busy() ? 1u : 0u, pc_audio_volume(),
			    (unsigned long)pc_audio_frame_duration_us());
		k_msleep(1000);
	}

	return 0;
}

#else /* !CONFIG_PITCHCOMM_ROLE_AUDIO_PROOF */

#if defined(CONFIG_PITCHCOMM_ROLE_COACH)
constexpr pc::Role kRole = pc::Role::Coach;
#elif defined(CONFIG_PITCHCOMM_ROLE_CATCHER)
constexpr pc::Role kRole = pc::Role::Catcher;
#elif defined(CONFIG_PITCHCOMM_ROLE_PITCHER)
constexpr pc::Role kRole = pc::Role::Pitcher;
#elif defined(CONFIG_PITCHCOMM_ROLE_SHORTSTOP)
constexpr pc::Role kRole = pc::Role::Shortstop;
#elif defined(CONFIG_PITCHCOMM_ROLE_CENTERFIELD)
constexpr pc::Role kRole = pc::Role::Centerfield;
#else
#error "No PitchComm role selected: set CONFIG_PITCHCOMM_ROLE_* in the role .conf"
#endif

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

bool audioIsReady()
{
#if defined(CONFIG_PITCHCOMM_AUDIO)
	return pc::audioRole(kRole) ? pc_audio_ready() : true;
#else
	return true;
#endif
}

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

	bool present(const pc::Output& out) override
	{
		const auto* call = pc::findCall(out.category, out.code);

		if (call == nullptr) {
			return false;
		}

		lastOutputSeen = out.sequence;
		screenWake();
		lastInteraction = now32();
		printf("CALL #%lu %s\n", static_cast<unsigned long>(out.sequence),
			    pc::labelFor(*call, kRole));

#if defined(CONFIG_PITCHCOMM_AUDIO)
		if (pc::audioRole(kRole)) {
			return pc_audio_play(call->audio[0], call->audio[1], call->audio[2]);
		}
#endif

		/* The coach has no local output; the laptop GUI renders the state. */
		if (kRole == pc::Role::Coach) {
			return true;
		}

#if defined(CONFIG_PITCHCOMM_DISPLAY)
		if (!displayReady) {
			return false;
		}
		if (!screen.strip(pc::labelFor(*call, kRole), "CALL")) {
			displayReady = false;
			return false;
		}
		return true;
#else
		return true;
#endif
	}

	void clearOutput() override
	{
#if defined(CONFIG_PITCHCOMM_AUDIO)
		pc_audio_stop();
#endif
		lastOutputSeen = 0;
		screenWake();
	}
};

AppHooks hooks;

pc::Submit submit(pc::Category category, uint16_t code, uint32_t now)
{
	if (engine == nullptr || !provisioned() || linkStartFault || !linkReady()) {
		note("SETUP REQUIRED");
		return pc::Submit::Offline;
	}

	const auto result = engine->submit(category, code, now);

	note(resultName(result));
	requestNotified = false;
	return result;
}

void repeat(uint32_t now)
{
	lastInteraction = now;
	screenWake();

	if (engine == nullptr || !engine->hasOutput()) {
		note("NO CALL TO RECALL");
		return;
	}

	/* Old or disconnected audio is never silently replayed. */
	if (pc::audioRole(kRole)) {
		if (!linkReady() || !engine->linked()) {
			note("NO LINK TO RECALL");
			return;
		}
		if (engine->outputOld(now)) {
			note("CALL TOO OLD");
			return;
		}
#if defined(CONFIG_PITCHCOMM_AUDIO)
		if (pc_audio_busy()) {
			note("AUDIO PLAYING");
			return;
		}
		const auto* call = pc::findCall(engine->output().category, engine->output().code);

		if (call == nullptr || !pc_audio_recall()) {
			note("AUDIO NOT READY");
		}
#endif
	}
}

void cycleVolume()
{
	if (!pc::audioRole(kRole)) {
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

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
void handleCatcher(unsigned input, uint32_t now)
{
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

	printf("ROLE=%s EUI=%s CONFIG=%s LINK=%s DICT=%08lx BATT=%s AUDIO=%s OLED=%s "
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

	if (engine != nullptr && kRole == pc::Role::Coach) {
		for (unsigned i = 1; i < pc::kRoles; ++i) {
			printf("%s LINK=%s DELIVERY=%s\n", pc::roleName(pc::Role(i)),
				    engine->peer(pc::Role(i)).ready ? "UP" : "DOWN",
				    deliveryName(engine->delivery(pc::Role(i))));
		}
	}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
void guiState()
{
	if (engine == nullptr) {
		return;
	}

	const auto out = engine->hasOutput() ? engine->output() : pc::Output{};
	const auto& pitch = engine->record(pc::Category::Pitch);
	const auto& play = engine->record(pc::Category::Play);

	printf("@PC {\"type\":\"state\",\"v\":4,\"client\":\"%08lx\",\"clock\":%lu,"
		    "\"role\":%u,\"dictionary\":\"%08lx\",\"configured\":%u,\"radio\":%u,"
		    "\"busy\":%u,\"boot\":\"%016llx\",\"seq\":%lu,\"category\":%u,\"code\":%u,"
		    "\"links\":[%u,%u,%u,%u],\"delivery\":[%u,%u,%u,%u],"
		    "\"records\":[{\"category\":1,\"seq\":%lu,\"code\":%u,\"delivery\":[%u,%u]},"
		    "{\"category\":2,\"seq\":%lu,\"code\":%u,\"delivery\":[%u,%u]}]}\n",
		    static_cast<unsigned long>(usbGate.client()),
		    static_cast<unsigned long>(now32()), unsigned(uint8_t(kRole)),
		    static_cast<unsigned long>(pc::kDictionary), unsigned(provisioned()),
		    unsigned(pc_link_ready()), unsigned(engine->busy()),
		    static_cast<unsigned long long>(engine->boot()),
		    static_cast<unsigned long>(out.sequence), unsigned(out.category),
		    unsigned(out.code), unsigned(engine->peer(pc::Role::Catcher).ready),
		    unsigned(engine->peer(pc::Role::Pitcher).ready),
		    unsigned(engine->peer(pc::Role::Shortstop).ready),
		    unsigned(engine->peer(pc::Role::Centerfield).ready),
		    unsigned(engine->delivery(pc::Role::Catcher)),
		    unsigned(engine->delivery(pc::Role::Pitcher)),
		    unsigned(engine->delivery(pc::Role::Shortstop)),
		    unsigned(engine->delivery(pc::Role::Centerfield)),
		    static_cast<unsigned long>(pitch.output.sequence),
		    unsigned(pitch.output.code), unsigned(pitch.delivery[1]),
		    unsigned(pitch.delivery[2]),
		    static_cast<unsigned long>(play.output.sequence),
		    unsigned(play.output.code), unsigned(play.delivery[3]),
		    unsigned(play.delivery[4]));
}
#endif /* CONFIG_PITCHCOMM_CONSOLE */

void reportOutputFailures()
{
	if (engine == nullptr || kRole != pc::Role::Coach) {
		return;
	}

	static uint32_t reported[pc::kRoles]{};

	for (unsigned i = 1; i < pc::kRoles; ++i) {
		const auto& record = engine->record(i <= 2 ? pc::Category::Pitch
							   : pc::Category::Play);

		if (record.delivery[i] != pc::Delivery::OutputError || !record.output.sequence ||
		    reported[i] == record.output.sequence) {
			continue;
		}
		reported[i] = record.output.sequence;

		char text[32];

		snprintf(text, sizeof(text), "%s FAIL #%lu",
			      i == 1 ? "C" : i == 2 ? "P" : i == 3 ? "SS" : "CF",
			      static_cast<unsigned long>(record.output.sequence));
		note(text);
	}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
void serialInput(char *line, uint32_t now)
{
	if (strcmp(line, "status") == 0) {
		diagnostics();
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
				usbGate.execute(call, engine->boot(), pc::kDictionary, now,
						[&]() {
							const auto result = submit(
								call.category, call.code, now);

							return pc::UsbResult{
								result,
								result == pc::Submit::Accepted &&
										kRole ==
											pc::Role::Coach
									? engine->output()
										  .sequence
									: 0};
						});

			printf("@PC {\"type\":\"result\",\"v\":4,\"client\":\"%08lx\","
				    "\"boot\":\"%016llx\",\"id\":%lu,\"result\":%u,"
				    "\"seq\":%lu}\n",
				    static_cast<unsigned long>(call.client),
				    static_cast<unsigned long long>(engine->boot()),
				    static_cast<unsigned long>(call.id),
				    unsigned(response.result),
				    static_cast<unsigned long>(response.sequence));
		}
	} else if (strcmp(line, "repeat") == 0) {
		repeat(now);
	} else if (strcmp(line, "help") == 0) {
		printf("status | eui | gui [CLIENT8HEX] | call CLIENT ID p TYPE HEIGHT "
			    "SIDE BOOT16HEX DICT8HEX DEADLINE | call CLIENT ID d PLAY BOOT "
			    "DICT DEADLINE | repeat | vol 1..20 | scan\n");
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
	 * V1 cadence: exactly one bus probe per loop. A disconnected bus must
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
#if defined(CONFIG_PITCHCOMM_DISPLAY)
	if (!displayReady || screen.sleeping() || pc::elapsed(now, lastFrame) < 150) {
		return;
	}
	lastFrame = now;

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
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
	} else if (!engine->linked()) {
		notice = engine->incompatible() ? "DICTIONARY ERROR" : "COACH NOT LINKED";
	} else if (!audioIsReady()) {
		notice = "HEADSET NOT READY";
	} else if (engine->busy()) {
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
	const bool hasCall = engine->hasOutput();

	if (hasCall) {
		if (const auto* call =
			    pc::findCall(engine->output().category, engine->output().code)) {
			play = pc::labelFor(*call, kRole);
		}
	}

	const pc::StripState state{provisioned(), !linkStartFault && pc_link_ready(),
				   engine->linked(), engine->incompatible(),
				   hasCall && engine->outputOld(now), hasCall};

	if (!screen.strip(play, pc::stripStatus(state))) {
		displayReady = false;
		if (hasCall) {
			engine->outputFailed(engine->output().sequence, now);
		}
		note("DISPLAY DISCONNECTED");
	}
#endif
#else
	ARG_UNUSED(now);
#endif /* CONFIG_PITCHCOMM_DISPLAY */
}

void receiveLink(uint8_t source, const uint8_t *bytes, size_t len)
{
	if (len != pc::kPacketBytes || source >= pc::kRoles) {
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

void engineThread(void *arg1, void *arg2, void *arg3)
{
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);

	for (;;) {
		Inbound in;

		/* Bounded drain: a noisy link must not starve tick(). */
		for (unsigned budget = 0; budget < 12; ++budget) {
			if (k_msgq_get(&inbox, &in, K_NO_WAIT) != 0) {
				break;
			}

			const uint32_t now = now32();
			pc::Packet packet;

			if (!pc::decode(in.bytes, pc::kPacketBytes, packet) ||
			    in.source >= pc::kRoles || pc::Role(in.source) == kRole) {
				atomic_inc(&decodeErrors);
				continue;
			}
			if (engine != nullptr) {
				engine->receive(pc::Role(in.source), packet, now,
						pc::elapsed(now, in.receivedAt));
			}
		}

		const uint32_t now = now32();

		if (engine != nullptr) {
			engine->tick(now);
		}
		k_msleep(1);
	}
}

#if defined(CONFIG_PITCHCOMM_CONSOLE)
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
		serialInput(line, now32());
	}
}
#endif

void appSetup()
{
	const uint32_t now = now32();

	k_msgq_init(&inbox, inboxBuffer, sizeof(Inbound), 24);
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
	if (pc::audioRole(kRole)) {
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

	if (engine != nullptr && engine->requestFinished() && !requestNotified &&
	    kRole == pc::Role::Catcher) {
		requestNotified = true;
		switch (engine->requestResult()) {
		case pc::Status::Ok:
			note("COACH ACCEPTED");
			break;
		case pc::Status::Busy:
			note("COACH BUSY: RESEND");
			break;
		default:
			note("CALL STATUS UNKNOWN");
			break;
		}
	}

#if defined(CONFIG_PITCHCOMM_CATCHER_MENU)
	if (const auto input = catcherControls.tick(now)) {
		handleCatcher(input, now);
	}
	if (catcherMenu.draft() && pc::elapsed(now, catcherTouchedAt) > 10000) {
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
	if (kRole != pc::Role::Coach && pc::displayRole(kRole) && engine != nullptr &&
	    engine->linked() && pc::elapsed(now, lastInteraction) > 30000) {
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

#endif /* CONFIG_PITCHCOMM_ROLE_AUDIO_PROOF */
