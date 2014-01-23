/*
* Copyright (C) 2005, Ingo Molnar
*
* time-warp-test.c: check TSC synchronity on x86 CPUs. Also detects
*                   gettimeofday()-level time warps.
*
* Compile with: gcc -Wall -O2 -o time-warp-test time-warp-test.c -lrt
*/
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <signal.h>
#include <sys/wait.h>
#include <linux/unistd.h>
#include <unistd.h>
#include <string.h>
#include <pwd.h>
#include <grp.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <regex.h>
#include <fcntl.h>
#include <time.h>
#include <sys/mman.h>
#include <dlfcn.h>
#include <popt.h>
#include <sys/socket.h>
#include <ctype.h>
#include <assert.h>
#include <sched.h>
#include <time.h>

#define TEST_TSC 1
#define TEST_TOD 1
#define TEST_CLOCK 1

#if !TEST_TSC && !TEST_TOD && !TEST_CLOCK
# error this setting makes no sense ...
#endif

#if DEBUG
# define Printf(x...) printf(x)
#else
# define Printf(x...) do { } while (0)
#endif

/*
 * Shared locks and variables between the test tasks:
 */
enum {
    SHARED_LOCK     = 0,
    SHARED_TSC      = 2,
    SHARED_TOD      = 4,
    SHARED_CLOCK        = 6,
    SHARED_WORST_TSC    = 8,
    SHARED_WORST_TOD    = 10,
    SHARED_WORST_CLOCK  = 12,
    SHARED_NR_TSC_LOOPS = 14,
    SHARED_NR_TSC_WARPS = 16,
    SHARED_NR_TOD_LOOPS = 18,
    SHARED_NR_TOD_WARPS = 20,
    SHARED_NR_CLOCK_LOOPS   = 22,
    SHARED_NR_CLOCK_WARPS   = 24,
    SHARED_END      = 26,
};

#define SHARED(x)   (*(shared + SHARED_##x))
#define SHARED_LL(x)    (*(long long *)(shared + SHARED_##x))

#define BUG_ON(c) assert(!(c))

typedef unsigned long long cycles_t;
typedef unsigned long long usecs_t;
typedef unsigned long long u64;

#ifdef __x86_64__
#define DECLARE_ARGS(val, low, high)    unsigned low, high
#define EAX_EDX_VAL(val, low, high)     ((low) | ((u64)(high) << 32))
#define EAX_EDX_ARGS(val, low, high)    "a" (low), "d" (high)
#define EAX_EDX_RET(val, low, high)     "=a" (low), "=d" (high)
#else
#define DECLARE_ARGS(val, low, high)    unsigned long long val
#define EAX_EDX_VAL(val, low, high)     (val)
#define EAX_EDX_ARGS(val, low, high)    "A" (val)
#define EAX_EDX_RET(val, low, high)     "=A" (val)
#endif

static inline unsigned long long __rdtscll(void)
{
    DECLARE_ARGS(val, low, high);

    asm volatile("cpuid; rdtsc" : EAX_EDX_RET(val, low, high));

    return EAX_EDX_VAL(val, low, high);
}

#define rdtscll(val) do { (val) = __rdtscll(); } while (0)

#define rdtod(val)                  \
    do {                            \
        struct timeval tv;              \
        \
        gettimeofday(&tv, NULL);            \
        (val) = tv.tv_sec * 1000000ULL + tv.tv_usec;    \
    } while (0)

#define rdclock(val)                    \
    do {                            \
        struct timespec ts;             \
        \
        clock_gettime(CLOCK_MONOTONIC, &ts);        \
        (val) = ts.tv_sec * 1000000000ULL + ts.tv_nsec; \
    } while (0)

static unsigned long *setup_shared_var(void)
{
    char zerobuff [4096] = { 0, };
    int ret, fd;
    unsigned long *buf;

    fd = creat(".tmp_mmap", 0700);
    BUG_ON(fd == -1);
    close(fd);

    fd = open(".tmp_mmap", O_RDWR|O_CREAT|O_TRUNC);
    BUG_ON(fd == -1);
    ret = write(fd, zerobuff, 4096);
    BUG_ON(ret != 4096);

    buf = (void *)mmap(0, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    BUG_ON(buf == (void *)-1);

    close(fd);
    unlink(".tmp_mmap");

    return buf;
}

static inline void lock(unsigned long *flag)
{
#if 0
    __asm__ __volatile__(
            "1: lock; btsl $0,%0\n"
            "jc 1b\n"
            : "=g"(*flag) : : "memory");
#else
    __asm__ __volatile__(
            "1: lock; btsl $0,%0\n\t"
            "jnc 3f\n"
            "2: testl $1,%0\n\t"
            "je 1b\n\t"
            "rep ; nop\n\t"
            "jmp 2b\n"
            "3:"
            : "+m"(*flag) : : "memory");
#endif
}

static inline void unlock(unsigned long *flag)
{
#if 0
    __asm__ __volatile__(
            "lock; btrl $0,%0\n"
            : "=g"(*flag) :: "memory");
    __asm__ __volatile__("rep; nop");
#else
    __asm__ __volatile__("mov $0,%0; rep; nop" : "=g"(*flag) :: "memory");
#endif
}

static void print_status(unsigned long *shared)
{
    const char progress[] = "\\|/-";

    static unsigned long long sum_tsc_loops, sum_tod_loops, sum_clock_loops,
                         sum_tod;
    static unsigned int count1, count2;
    static usecs_t prev_tod;

    usecs_t tod;

    if (!prev_tod)
        rdtod(prev_tod);

    count1++;
    if (count1 < 1000)
        return;
    count1 = 0;

    rdtod(tod);
    if (abs(tod - prev_tod) < 100000ULL)
        return;

    sum_tod += tod - prev_tod;
    sum_tsc_loops += SHARED_LL(NR_TSC_LOOPS);
    sum_tod_loops += SHARED_LL(NR_TOD_LOOPS);
    sum_clock_loops += SHARED_LL(NR_CLOCK_LOOPS);
    SHARED_LL(NR_TSC_LOOPS) = 0;
    SHARED_LL(NR_TOD_LOOPS) = 0;
    SHARED_LL(NR_CLOCK_LOOPS) = 0;

    if (TEST_TSC)
        printf(" | TSC: %.2fus, fail:%ld",
                (double)sum_tod/(double)sum_tsc_loops,
                SHARED(NR_TSC_WARPS));

    if (TEST_TOD)
        printf(" | TOD: %.2fus, fail:%ld",
                (double)sum_tod/(double)sum_tod_loops,
                SHARED(NR_TOD_WARPS));

    if (TEST_CLOCK)
        printf(" | CLK: %.2fus, fail:%ld",
                (double)sum_tod/(double)sum_clock_loops,
                SHARED(NR_CLOCK_WARPS));

    prev_tod = tod;
    count2++;
    printf(" %c\r", progress[count2 & 3]);
    fflush(stdout);
}

static inline void test_TSC(unsigned long *shared)
{
#if TEST_TSC
    cycles_t t0, t1;
    long long delta;

    lock(&SHARED(LOCK));
    rdtscll(t1);
    t0 = SHARED_LL(TSC);
    SHARED_LL(TSC) = t1;
    SHARED_LL(NR_TSC_LOOPS)++;
    unlock(&SHARED(LOCK));

    delta = t1-t0;
    if (delta < 0) {
        lock(&SHARED(LOCK));
        SHARED(NR_TSC_WARPS)++;
        if (delta < SHARED_LL(WORST_TSC)) {
            SHARED_LL(WORST_TSC) = delta;
            fprintf(stderr, "\rnew TSC-warp maximum: %9Ld cycles, %016Lx -> %016Lx\n",
                    delta, t0, t1);
        }
        unlock(&SHARED(LOCK));
    }
    if (!((unsigned long)t0 & 31))
        asm volatile ("rep; nop");
#endif
}

static inline void test_TOD(unsigned long *shared)
{
#if TEST_TOD
    usecs_t T0, T1;
    long long delta;

    lock(&SHARED(LOCK));
    rdtod(T1);
    T0 = SHARED_LL(TOD);
    SHARED_LL(TOD) = T1;
    SHARED_LL(NR_TOD_LOOPS)++;
    unlock(&SHARED(LOCK));

    delta = T1-T0;
    if (delta < 0) {
        lock(&SHARED(LOCK));
        SHARED(NR_TOD_WARPS)++;
        if (delta < SHARED_LL(WORST_TOD)) {
            SHARED_LL(WORST_TOD) = delta;
            fprintf(stderr, "\rnew TOD-warp maximum: %9Ld usecs,  %016Lx -> %016Lx\n",
                    delta, T0, T1);
        }
        unlock(&SHARED(LOCK));
    }
#endif
}

static inline void test_CLOCK(unsigned long *shared)
{
#if TEST_CLOCK
    usecs_t T0, T1;
    long long delta;

    lock(&SHARED(LOCK));
    rdclock(T1);
    T0 = SHARED_LL(CLOCK);
    SHARED_LL(CLOCK) = T1;
    SHARED_LL(NR_CLOCK_LOOPS)++;
    unlock(&SHARED(LOCK));

    delta = T1-T0;
    if (delta < 0) {
        lock(&SHARED(LOCK));
        SHARED(NR_CLOCK_WARPS)++;
        if (delta < SHARED_LL(WORST_CLOCK)) {
            SHARED_LL(WORST_CLOCK) = delta;
            fprintf(stderr, "\rnew CLOCK-warp maximum: %9Ld nsecs,  %016Lx -> %016Lx\n",
                    delta, T0, T1);
        }
        unlock(&SHARED(LOCK));
    }
#endif
}

int main(int argc, char **argv)
{
    int i, parent, me;
    unsigned long *shared;
    unsigned long cpus, tasks;

    cpus = system("exit `grep ^processor /proc/cpuinfo  | wc -l`");
    cpus = WEXITSTATUS(cpus);

    if (argc > 2) {
usage:
        fprintf(stderr,
                "usage: tsc-sync-test <threads>\n");
        exit(-1);
    }
    if (argc == 2) {
        tasks = atol(argv[1]);
        if (!tasks)
            goto usage;
    } else
        tasks = cpus;

    printf("%ld CPUs, running %ld parallel test-tasks.\n", cpus, tasks);
    printf("checking for time-warps via:\n"
#if TEST_TSC
            "- read time stamp counter (RDTSC) instruction (cycle resolution)\n"
#endif
#if TEST_TOD
            "- gettimeofday (TOD) syscall (usec resolution)\n"
#endif
#if TEST_CLOCK
            "- clock_gettime(CLOCK_MONOTONIC) syscall (nsec resolution)\n"
#endif
            "\n"
          );
    shared = setup_shared_var();

    parent = getpid();

    for (i = 1; i < tasks; i++) {
        if (!fork())
            break;
    }
    me = getpid();

    while (1) {
        int i;

        for (i = 0; i < 10; i++)
            test_TSC(shared);
        for (i = 0; i < 10; i++)
            test_TOD(shared);
        for (i = 0; i < 10; i++)
            test_CLOCK(shared);

        if (me == parent)
            print_status(shared);
    }

    return 0;
}
