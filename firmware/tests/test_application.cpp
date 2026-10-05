// Run actual application paths against host mutex/queue/panel models.
// This verifies ownership and completion ordering, not Zephyr scheduling/I2C.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include "app/team_config.example.h"
#undef PC_TEAM_CONFIGURED
#define PC_TEAM_CONFIGURED 1
#define main pitchcomm_firmware_entrypoint
#include "../src/main.cpp"
#undef main

namespace model {
std::atomic<uint32_t> clock{1000};
std::mutex registry;
std::map<void*,std::unique_ptr<std::recursive_timed_mutex>> locks;
struct Queue {size_t size=0,limit=0;std::deque<std::vector<char>> items;};
std::map<void*,Queue> queues;
std::mutex radio;
std::vector<pc::Packet> sent;
std::mutex panel;
std::condition_variable changed;
bool stall=false,entered=false,released=false;
std::atomic<unsigned> panelWrites{0};
std::atomic<unsigned> menuWrites{0};
std::atomic<bool> panelOk{true};
unsigned checks=0,failures=0;
void check(bool value,const char* label) {
  ++checks;if(!value) {++failures;printf("FAIL application: %s\n",label);}
}
std::recursive_timed_mutex& lockFor(void* key) {
  std::lock_guard<std::mutex> guard(registry);
  auto& p=locks[key];if(!p) p=std::make_unique<std::recursive_timed_mutex>();return *p;
}
unsigned acks(uint32_t seq,pc::Status status=pc::Status::Ok) {
  std::lock_guard<std::mutex> guard(radio);unsigned count=0;
  for(const auto& p:sent) if(p.kind==pc::Kind::Ack && p.sequence==seq && p.status==status) ++count;
  return count;
}
pc::Packet last(pc::Kind kind) {
  std::lock_guard<std::mutex> guard(radio);
  for(auto it=sent.rbegin();it!=sent.rend();++it) if(it->kind==kind) return *it;
  return {};
}
void receive(const pc::Packet& p) {
  uint8_t bytes[pc::kPacketBytes];pc::encode(p,bytes);receiveLink(p.source,bytes,sizeof(bytes));engineStep();
}
void link(uint32_t now) {
  clock=now;engineStep();const auto hello=last(pc::Kind::Hello);
  pc::Packet sync;sync.kind=pc::Kind::Sync;sync.source=pc::kCoach;sync.target=kRole;
  sync.boot=engineView().boot;sync.token=hello.token;sync.session=88;sync.dictionary=pc::kDictionary;
  sync.clock=now;sync.reference=now;receive(sync);
  serviceOutput(now);check(engineView().linked,"mock handshake completes");
}
void call(uint32_t seq,unsigned pitch=1) {
  pc::Packet p;p.kind=pc::Kind::Call;p.source=pc::kCoach;p.target=kRole;
  p.boot=engineView().boot;p.session=88;p.dictionary=pc::kDictionary;
  p.sequence=seq;p.category=pc::Category::Pitch;p.code=pc::pitchTypeCode(pitch);
  p.ttl=800;p.deadline=clock.load()+800;p.clock=clock;receive(p);
}
std::thread blockPanel() {
  {std::lock_guard<std::mutex> guard(panel);stall=true;entered=false;released=false;}
  std::thread ui([]{serviceOutput(clock);});
  std::unique_lock<std::mutex> guard(panel);
  check(changed.wait_for(guard,std::chrono::seconds(1),[]{return entered;}),"UI entered stalled transfer");
  return ui;
}
void releasePanel(std::thread& ui) {
  {std::lock_guard<std::mutex> guard(panel);released=true;stall=false;}
  changed.notify_all();ui.join();
}
}

extern "C" {
int k_mutex_lock(struct k_mutex* key,k_timeout_t timeout) {
  auto& mutex=model::lockFor(key);
  if(timeout==K_FOREVER) {mutex.lock();return 0;}
  return mutex.try_lock_for(std::chrono::milliseconds(timeout)) ? 0 : -1;
}
int k_mutex_unlock(struct k_mutex* key) {model::lockFor(key).unlock();return 0;}
int k_msgq_init(struct k_msgq* q,char*,size_t size,uint32_t count) {
  std::lock_guard<std::mutex> guard(model::registry);model::queues[q]={size,count,{}};return 0;
}
int k_msgq_put(struct k_msgq* q,const void* data,k_timeout_t) {
  std::lock_guard<std::mutex> guard(model::registry);auto& queue=model::queues.at(q);
  if(queue.items.size()>=queue.limit) return -1;
  const auto* bytes=static_cast<const char*>(data);queue.items.emplace_back(bytes,bytes+queue.size);return 0;
}
int k_msgq_get(struct k_msgq* q,void* out,k_timeout_t) {
  std::lock_guard<std::mutex> guard(model::registry);auto& queue=model::queues.at(q);
  if(queue.items.empty()) return -1;
  memcpy(out,queue.items.front().data(),queue.size);queue.items.pop_front();return 0;
}
uint32_t k_msgq_num_used_get(struct k_msgq* q) {
  std::lock_guard<std::mutex> guard(model::registry);return model::queues.at(q).items.size();
}
uint32_t k_uptime_get_32(void) {return model::clock;}
int32_t k_msleep(int32_t) {return 0;}
k_tid_t k_current_get(void) {return nullptr;}
void k_thread_priority_set(k_tid_t,int) {}
k_tid_t k_thread_create(struct k_thread* thread,k_thread_stack_t*,size_t,k_thread_entry_t,
                       void*,void*,void*,int,uint32_t,k_timeout_t) {return thread;}
int k_thread_name_set(k_tid_t,const char*) {return 0;}
int pc_link_start(uint8_t,pc_link_rx_fn) {return 0;}
bool pc_link_ready(void) {return true;}
const char* pc_link_state(void) {return "HOST MODEL";}
bool pc_link_send(uint8_t,const uint8_t* bytes,size_t size) {
  pc::Packet p;if(!pc::decode(bytes,size,p)) return false;
  std::lock_guard<std::mutex> guard(model::radio);model::sent.push_back(p);return true;
}
void pc_link_local_eui64(uint8_t out[8]) {memset(out,0,8);}
uint32_t pc_link_tx_dropped(void) {return 0;}
uint32_t pc_link_rx_dropped(void) {return 0;}
uint32_t pc_link_tx_errors(void) {return 0;}
}
atomic_val_t atomic_get(const atomic_t* p) {std::lock_guard<std::mutex> guard(model::registry);return *p;}
void atomic_set(atomic_t* p,atomic_val_t value) {std::lock_guard<std::mutex> guard(model::registry);*p=value;}
atomic_val_t atomic_inc(atomic_t* p) {std::lock_guard<std::mutex> guard(model::registry);return (*p)++;}
uint32_t sys_rand32_get(void) {return 101;}
void console_getline_init(void) {}
char* console_getline(void) {return nullptr;}

#if defined(CONFIG_PITCHCOMM_DISPLAY)
namespace board {
bool Display::begin() {return true;}
void Display::wake() {}
void Display::sleep() {}
bool Display::sleeping() const {return false;}
bool Display::strip(const char*,const char*) {
  ++model::panelWrites;
  std::unique_lock<std::mutex> guard(model::panel);
  if(model::stall) {model::entered=true;model::changed.notify_all();model::changed.wait(guard,[]{return model::released;});}
  return model::panelOk;
}
bool Display::menu(const pc::CatcherMenu::Frame&) {++model::menuWrites;return true;}
bool Display::probe(uint8_t) {return true;}
bool CatcherControls::begin() {return true;}
bool CatcherControls::available() const {return true;}
unsigned CatcherControls::tick(uint32_t) {return 0;}
}
#endif

int main() {
  using model::check;
  k_msgq_init(&inbox,inboxBuffer,sizeof(Inbound),24);
  k_msgq_init(&consoleLines,consoleBuffer,sizeof(ConsoleLine),4);
#if defined(PITCHCOMM_HOST_COACH)
  engine=new(engineStorage) pc::Engine(kRole,101,hooks);
  for(unsigned i=1;i<pc::kUnitCount;++i) {
    pc::Packet hello;hello.kind=pc::Kind::Hello;hello.source=pc::Role(i);hello.target=kRole;
    hello.boot=1000+i;hello.token=2000+i;hello.dictionary=pc::kDictionary;hello.clock=model::clock;
    model::receive(hello);
    auto ready=hello;ready.kind=pc::Kind::Ready;ready.session=101;model::receive(ready);
    check(engineView().ready[i],"coach links each simulated receiver");
  }
  char session[]="gui 1234abcd";enqueueConsole(session);
  check(usbGate.client()==0,"coach console producer leaves session unchanged");
  loop();check(usbGate.client()==0x1234abcd,"coach UI owns USB session update");
  auto result=submitResult(pc::Category::Pitch,1,model::clock);
  check(result.result==pc::Submit::Accepted && result.sequence==1,"submission captures its accepted sequence atomically");
  auto acknowledge=[&]{
    auto view=engineView();
    for(unsigned i=1;i<pc::kUnitCount;++i) if(view.delivery[i]==pc::Delivery::Pending) {
      pc::Packet ack;ack.kind=pc::Kind::Ack;ack.source=pc::Role(i);ack.target=kRole;
      ack.boot=1000+i;ack.session=101;ack.dictionary=pc::kDictionary;
      ack.sequence=view.output.sequence;ack.code=view.output.code;ack.category=view.output.category;
      ack.status=pc::Status::Ok;model::receive(ack);
    }
  };
  acknowledge();check(!engineView().busy,"receiver acknowledgements finish coach call");
  std::atomic<bool> done{false};bool consistent=true;unsigned frames=0;
  std::thread worker([&]{
    for(unsigned n=1;n<=200;++n) {
      ++model::clock;
      pc::Packet request;request.kind=pc::Kind::Request;request.source=pc::kUnitCatcher;request.target=kRole;
      request.boot=1000+pc::kUnitCatcher;request.session=101;request.dictionary=pc::kDictionary;
      request.sequence=n;request.category=pc::Category::Pitch;request.code=pc::pitchCode(n%pc::kPitchCount+1,1,1);
      request.ttl=800;request.deadline=model::clock.load()+800;model::receive(request);acknowledge();
      std::this_thread::yield();
    }
    done=true;
  });
  do {
    auto view=engineView();
    consistent=consistent && view.output.sequence==view.records[0].output.sequence &&
               view.output.code==view.records[0].output.code;
    for(unsigned i=1;i<pc::kUnitCount;++i) consistent=consistent && view.delivery[i]==view.records[0].delivery[i];
    guiState();++frames;std::this_thread::yield();
  } while(!done && frames<400);
  worker.join();
  check(consistent && frames>0,"coach snapshots keep output, record and delivery arrays together");
  check(engineView().output.sequence==201 && !engineView().busy,"concurrent requests and receipts complete without lost calls");
  serviceOutput(model::clock);
  printf("%u coach application checks, %u failures; %u serialized frames (host model)\n",model::checks,model::failures,frames);
  return model::failures ? 1 : 0;
#else
  displayReady=true;
  engine=new(engineStorage) pc::Engine(kRole,101,hooks);
  model::link(1000);model::clock=1010;model::call(7);
  check(engineView().outputPending,"display receipt is pending");
  check(model::acks(7)==0,"no output accepted before screen transfer");
  auto ui=model::blockPanel();
  auto radio=std::async(std::launch::async,[]{model::clock=1020;model::call(8,2);});
  const bool serviced=radio.wait_for(std::chrono::milliseconds(200))==std::future_status::ready;
  check(serviced,"radio services newer call while OLED transfer is blocked");
  model::releasePanel(ui);radio.get();
  check(engineView().output.sequence==8 && engineView().outputPending,"old completion cannot acknowledge newer call");
  check(model::acks(7)==0 && model::acks(8)==0,"superseded frame produced no accepted receipt");
  serviceOutput(model::clock);engineStep();
  check(model::acks(8)>0,"current successful transfer acknowledges exact call");
  check(lastOutputSeen==8,"UI tracks current frame");
  unsigned menuBefore=model::menuWrites;
  lastFrame=0;draw(model::clock);
  check(model::menuWrites==menuBefore,"received call stays visible immediately after transfer");
  lastFrame=0;draw(model::clock.load()+3999);
  check(model::menuWrites==menuBefore,"received call stays visible for the full four seconds");
  lastFrame=0;draw(model::clock.load()+4000);
  check(model::menuWrites==menuBefore+1,"selection menu returns at the four-second boundary");
  const uint32_t shownAt=catcherCallAt;
  catcherCallAt=UINT32_MAX-1000;lastFrame=0;menuBefore=model::menuWrites;draw(1000);
  check(model::menuWrites==menuBefore,"received call display duration survives clock rollover");
  catcherCallAt=shownAt;
  model::call(9,3);ui=model::blockPanel();
  pc::Packet reset;reset.kind=pc::Kind::Resync;reset.source=pc::kCoach;reset.target=kRole;reset.boot=engineView().boot;
  model::receive(reset);check(!engineView().hasOutput,"resync clears output during OLED transfer");
  model::releasePanel(ui);serviceOutput(model::clock);engineStep();
  check(model::acks(9)==0 && lastOutputSeen==0,"late display completion cannot undo clear");
  model::link(2000);model::clock=2010;model::call(10,4);ui=model::blockPanel();
  model::clock=3010;engineStep();
  check(!engineView().hasOutput && !engineView().outputPending,"pending display expires while UI is stalled");
  model::releasePanel(ui);serviceOutput(model::clock);engineStep();
  check(model::acks(10)==0 && model::acks(10,pc::Status::OutputError)>0,"expired transfer has no success receipt");
  model::call(11,5);model::panelOk=false;serviceOutput(model::clock);engineStep();
  check(!displayReady && !engineView().hasOutput,"failed panel transfer clears pending output");
  check(model::acks(11)==0 && model::acks(11,pc::Status::OutputError)>0,"failed panel transfer reports output error");
  model::panelOk=true;displayReady=true;serviceOutput(model::clock);
  // Exercise concurrent snapshot reads during actual inbound worker updates.
  std::atomic<bool> done{false};bool coherent=true;unsigned observed=0;
  std::thread producer([&]{
    for(unsigned seq=30;seq<=230;++seq) {++model::clock;model::call(seq,seq%pc::kPitchCount+1);std::this_thread::yield();}
    done=true;
  });
  uint64_t lastRevision=0;
  do {
    const auto view=engineView();
    if(view.hasOutput && view.output.sequence>=30) {
      ++observed;
      coherent=coherent && view.output.code==pc::pitchTypeCode(view.output.sequence%pc::kPitchCount+1) &&
               view.output.revision>=lastRevision;
      lastRevision=view.output.revision;
    }
    std::this_thread::yield();
  } while(!done);
  producer.join();
  check(coherent && observed>0,"concurrent views retain matching code/sequence and ordered revision");
  check(engineView().output.sequence==230,"bounded output slot retains newest rapid call");
  serviceOutput(model::clock);engineStep();
  check(model::acks(230)>0 && lastOutputSeen==230,"newest rapid call gets its own completed receipt");
  // Producer copies and queues commands; it never changes UI/USB state.
  char commandLine[]="gui 1234abcd";enqueueConsole(commandLine);commandLine[4]='9';
  check(usbGate.client()==0,"console producer does not mutate USB session");
  loop();check(usbGate.client()==0x1234abcd,"UI executes owned copy of console line");
  for(unsigned i=0;i<5;++i) enqueueConsole("help");
  check(k_msgq_num_used_get(&consoleLines)==4 && atomic_get(&consoleDropped)==1,"console queue is bounded");
  loop();check(k_msgq_num_used_get(&consoleLines)==2,"UI command drain is bounded");
  char oversized[193];memset(oversized,'x',192);oversized[192]=0;enqueueConsole(oversized);
  check(atomic_get(&consoleDropped)==2,"oversized console line is rejected whole");
  printf("%u application checks, %u failures (host mutex/queue/panel model)\n",model::checks,model::failures);
  return model::failures ? 1 : 0;
#endif
}
