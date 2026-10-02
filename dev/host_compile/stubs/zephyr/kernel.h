/*
 * HOST STUB: zephyr/kernel.h
 *
 * Declaration-only stand-in used by dev/host_compile/run.ps1 with
 * -fsyntax-only. It is NOT a Zephyr header and must never be used in a
 * firmware build. Only the kernel surface the PitchComm sources touch is
 * declared.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/sys/atomic.h>
#include <zephyr/sys/util.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int64_t k_timeout_t;

#define K_NO_WAIT ((k_timeout_t)0)
#define K_FOREVER ((k_timeout_t)-1)
/*
 * HOST STUB: the real macros convert to ticks. The stub keeps the argument
 * value; it is never passed to an implementation.
 */
#define K_MSEC(ms) ((k_timeout_t)(ms))
#define K_USEC(us) ((k_timeout_t)(us))

struct k_thread {
	int unused;
};

typedef struct k_thread *k_tid_t;
typedef void (*k_thread_entry_t)(void *p1, void *p2, void *p3);
typedef uint8_t k_thread_stack_t;

struct k_msgq {
	int unused;
};

struct k_mutex {
	int unused;
};

struct k_event {
	int unused;
};

/*
 * HOST STUB: expands to an array declaration without a storage class, so it
 * can follow a caller's `static` like the real Zephyr macro.
 */
#define K_THREAD_STACK_DEFINE(sym, size) \
	uint8_t sym[(((size) + 7u) & ~7u)]
#define K_THREAD_STACK_SIZEOF(sym) sizeof(sym)
#define K_MSGQ_DEFINE(name, msg_size, max_msgs, align) \
	struct k_msgq name __attribute__((unused))
#define K_MUTEX_DEFINE(name) \
	struct k_mutex name __attribute__((unused)) = { 0 }
#define K_EVENT_DEFINE(name) \
	struct k_event name __attribute__((unused)) = { 0 }

#define K_PRIO_PREEMPT(prio) (prio)

k_tid_t k_current_get(void);
void k_thread_priority_set(k_tid_t thread, int prio);
k_tid_t k_thread_create(struct k_thread *new_thread, k_thread_stack_t *stack,
			size_t stack_size, k_thread_entry_t entry, void *p1,
			void *p2, void *p3, int prio, uint32_t options,
			k_timeout_t delay);
int k_thread_name_set(k_tid_t thread, const char *str);

int32_t k_msleep(int32_t ms);
int32_t k_usleep(int32_t us);
int64_t k_uptime_get(void);
uint32_t k_uptime_get_32(void);

int k_msgq_init(struct k_msgq *msgq, char *buffer, size_t msg_size,
		uint32_t max_msgs);
int k_msgq_put(struct k_msgq *msgq, const void *data, k_timeout_t timeout);
int k_msgq_get(struct k_msgq *msgq, void *data, k_timeout_t timeout);
void k_msgq_purge(struct k_msgq *msgq);
uint32_t k_msgq_num_used_get(struct k_msgq *msgq);

int k_mutex_lock(struct k_mutex *mutex, k_timeout_t timeout);
int k_mutex_unlock(struct k_mutex *mutex);

void k_event_post(struct k_event *event, uint32_t events);
void k_event_clear(struct k_event *event, uint32_t events);
uint32_t k_event_test(struct k_event *event, uint32_t events);
uint32_t k_event_wait(struct k_event *event, uint32_t events, bool reset,
		      k_timeout_t timeout);

void *k_malloc(size_t size);
void k_free(void *ptr);

#ifdef __cplusplus
}
#endif
