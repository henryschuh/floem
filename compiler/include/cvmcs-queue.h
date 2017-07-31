#ifndef QUEUE_H
#define QUEUE_H

#include <cvmx-atomic.h>
#include "cvmcs-nic.h"

#define ALIGN 8U
#define FLAG_OWN 1
#define TYPE_NOP 0
#define TYPE_SHIFT 8
#define TYPE_MASK  0xFF00

typedef cvmx_spinlock_t lock_t;
#define qlock_init(x) cvmx_spinlock_init(x)
#define qlock_lock(x) cvmx_spinlock_lock(x)
#define qlock_unlock(x) cvmx_spinlock_unlock(x)

typedef cvmx_spinlock_t spin_lock_t;
#define spinlock_init(x) cvmx_spinlock_init(x)
#define spinlock_lock(x) cvmx_spinlock_lock(x)
#define spinlock_unlock(x) cvmx_spinlock_unlock(x)

#define __sync_fetch_and_add32(ptr, inc) cvmx_atomic_fetch_and_add32(ptr, inc)
#define __sync_fetch_and_add64(ptr, inc) cvmx_atomic_fetch_and_add64(ptr, inc)

/* Functions to measure time using core clock in nanoseconds */
unsigned long long core_time_now_ns(void)
{
        unsigned long long t;
        t = cvmx_clock_get_count(CVMX_CLOCK_CORE);
        t = 1000000000ULL * t / cvmx_clock_get_rate(CVMX_CLOCK_CORE);
	return t;
}

/* Functions to measure time using core clock in microseconds */
uint64_t core_time_now_us(void)
{
        unsigned long long t;
        t = cvmx_clock_get_count(CVMX_CLOCK_CORE);
        t = 1000000ULL * t / cvmx_clock_get_rate(CVMX_CLOCK_CORE);
	return t;
}

typedef struct {
    size_t len;
    size_t offset;
    void* queue;
} circular_queue;

typedef struct {
    size_t len;
    size_t offset;
    void* queue;
    lock_t lock;
} circular_queue_lock;

typedef struct {
    size_t len;
    size_t offset;
    void* queue;
    size_t clean;
} circular_queue_scan;

typedef struct {
    size_t len;
    size_t offset;
    void* queue;
    lock_t lock;
    size_t clean;
} circular_queue_lock_scan;

typedef struct {
    uint16_t flags;
    uint16_t len;
} __attribute__((packed)) q_entry;

typedef struct {
    q_entry* entry;
    uintptr_t addr;
} q_buffer;

q_buffer enqueue_alloc(circular_queue* q, size_t len);
void enqueue_submit(q_buffer buf);
q_buffer dequeue_get(circular_queue* q);
void dequeue_release(q_buffer buf);
q_buffer next_clean(circular_queue_scan* q);
void clean_release(q_buffer buf);
#endif
