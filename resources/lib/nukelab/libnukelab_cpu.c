/*
 * libnukelab_cpu.so - LD_PRELOAD library for container-scoped CPU views
 *
 * Two interceptions:
 *
 * 1. sysconf(_SC_NPROCESSORS_ONLN/_SC_NPROCESSORS_CONF) returns the
 *    container's actual CPU allocation instead of the host's core count.
 *
 * 2. Read-only open()/fopen() of /proc/stat returns a synthesized,
 *    container-scoped stat file derived from the cgroup CPU counters, so
 *    tools like top/htop/psutil report this container's usage instead of
 *    the host's. Synthesis only activates when a CPU restriction is
 *    visible (env var or cgroup quota/cpuset); without one the real
 *    /proc/stat is served, which is correct on bare metal.
 *
 * CPU count resolution order (first match wins):
 *   1. NUKELAB_CPU_COUNT environment variable
 *   2. /sys/fs/cgroup/cpu.max                  (cgroup v2 CPU quota)
 *   3. /sys/fs/cgroup/cpu/cpu.cfs_quota_us     (cgroup v1 CPU quota)
 *   4. /sys/fs/cgroup/cpuset.cpus.effective    (cpuset narrower than host)
 *   5. real sysconf()                          (host fallback)
 *
 * Build:
 *     gcc -shared -fPIC -o libnukelab_cpu.so libnukelab_cpu.c -ldl
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- real libc entry points ------------------------------------------- */

static long (*real_sysconf)(int) = NULL;
static int (*real_open)(const char *, int, ...) = NULL;
static int (*real_open64)(const char *, int, ...) = NULL;
static int (*real_openat)(int, const char *, int, ...) = NULL;
static int (*real_openat64)(int, const char *, int, ...) = NULL;
static int (*real___open_2)(const char *, int) = NULL;
static int (*real___open64_2)(const char *, int) = NULL;
static int (*real___openat_2)(int, const char *, int) = NULL;
static int (*real___openat64_2)(int, const char *, int) = NULL;
static FILE *(*real_fopen)(const char *, const char *) = NULL;
static FILE *(*real_fopen64)(const char *, const char *) = NULL;

static void resolve_real(void) {
    if (!real_sysconf) real_sysconf = (long (*)(int)) dlsym(RTLD_NEXT, "sysconf");
    if (!real_open) real_open = (int (*)(const char *, int, ...)) dlsym(RTLD_NEXT, "open");
    if (!real_open64) real_open64 = (int (*)(const char *, int, ...)) dlsym(RTLD_NEXT, "open64");
    if (!real_openat) real_openat = (int (*)(int, const char *, int, ...)) dlsym(RTLD_NEXT, "openat");
    if (!real_openat64) real_openat64 = (int (*)(int, const char *, int, ...)) dlsym(RTLD_NEXT, "openat64");
    if (!real___open_2) real___open_2 = (int (*)(const char *, int)) dlsym(RTLD_NEXT, "__open_2");
    if (!real___open64_2) real___open64_2 = (int (*)(const char *, int)) dlsym(RTLD_NEXT, "__open64_2");
    if (!real___openat_2) real___openat_2 = (int (*)(int, const char *, int)) dlsym(RTLD_NEXT, "__openat_2");
    if (!real___openat64_2) real___openat64_2 = (int (*)(int, const char *, int)) dlsym(RTLD_NEXT, "__openat64_2");
    if (!real_fopen) real_fopen = (FILE * (*)(const char *, const char *)) dlsym(RTLD_NEXT, "fopen");
    if (!real_fopen64) real_fopen64 = (FILE * (*)(const char *, const char *)) dlsym(RTLD_NEXT, "fopen64");
}

/* ---- small file helpers ------------------------------------------------
 * Cgroup reads use raw syscalls so they can never recurse back into the
 * interceptions below. */

static int read_small_file(const char *path, char *buf, size_t cap) {
    int fd = (int) syscall(SYS_openat, AT_FDCWD, path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = syscall(SYS_read, fd, buf, cap - 1);
    syscall(SYS_close, fd);
    if (n <= 0) return -1;
    buf[n] = '\0';
    return 0;
}

/* Value of "key <n>" at the start of a line; 0 when absent. */
static unsigned long long parse_key(const char *buf, const char *key) {
    size_t klen = strlen(key);
    const char *p = buf;
    while ((p = strstr(p, key))) {
        if ((p == buf || p[-1] == '\n') && p[klen] == ' ')
            return strtoull(p + klen + 1, NULL, 10);
        p += klen;
    }
    return 0;
}

/* ---- CPU count resolution ---------------------------------------------- */

/* Count CPUs from a cpuset.cpus.effective string like "0-3,5,7-9" */
static long count_cpuset_cpus(const char *buf) {
    long count = 0;
    char *s = strdup(buf);
    if (!s) return 0;

    char *token = strtok(s, ",");
    while (token) {
        char *dash = strchr(token, '-');
        if (dash) {
            int start = atoi(token);
            int end = atoi(dash + 1);
            if (end >= start) count += (end - start + 1);
        } else {
            count++;
        }
        token = strtok(NULL, ",");
    }
    free(s);
    return count > 0 ? count : 0;
}

/* Read CPU count from cgroup cpuset (e.g. /sys/fs/cgroup/cpuset.cpus.effective) */
static long read_cpuset_cpus(void) {
    char buf[256];
    if (read_small_file("/sys/fs/cgroup/cpuset.cpus.effective", buf, sizeof(buf)) != 0 &&
        read_small_file("/sys/fs/cgroup/cpuset.cpus", buf, sizeof(buf)) != 0) /* cgroup v1 fallback */
        return 0;

    /* Strip trailing newline */
    size_t len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';
    return count_cpuset_cpus(buf);
}

/* Read CPU count from cgroup cpu.max (e.g. "100000 100000" = 1 CPU) */
static long read_cpu_max(void) {
    char buf[256];
    if (read_small_file("/sys/fs/cgroup/cpu.max", buf, sizeof(buf)) != 0)
        return 0;

    long quota, period;
    if (sscanf(buf, "%ld %ld", &quota, &period) == 2 && period > 0 && quota > 0)
        return (quota + period - 1) / period; /* ceil(quota/period) */
    /* quota <= 0 or "max" means unlimited */
    return 0;
}

/* Read CPU count from cgroup v1 cfs quota (cpu.cfs_quota_us / cpu.cfs_period_us) */
static long read_cfs_quota_v1(void) {
    char buf[64];
    if (read_small_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", buf, sizeof(buf)) != 0)
        return 0;
    long quota = atol(buf);
    if (quota <= 0) return 0;
    if (read_small_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us", buf, sizeof(buf)) != 0)
        return 0;
    long period = atol(buf);
    if (period <= 0) return 0;
    return (quota + period - 1) / period;
}

/*
 * Resolve the container's CPU allocation. Sets *limited when a real
 * restriction was found (env var, quota, or a cpuset narrower than the
 * host); callers use that to decide whether host views need masking.
 */
static long resolve_cpu_count(int *limited) {
    long n;
    if (limited) *limited = 0;

    /* 1. Environment variable (fastest, user-overridable) */
    const char *env = getenv("NUKELAB_CPU_COUNT");
    if (env && env[0]) {
        n = atol(env);
        if (n > 0) {
            if (limited) *limited = 1;
            return n;
        }
    }

    /* 2. Cgroup v2 cpu quota (throttling-based limit, e.g. --cpus=1) */
    n = read_cpu_max();
    if (n > 0) {
        if (limited) *limited = 1;
        return n;
    }

    /* 3. Cgroup v1 cfs quota */
    n = read_cfs_quota_v1();
    if (n > 0) {
        if (limited) *limited = 1;
        return n;
    }

    /* 4. Cgroup cpuset (hard affinity, e.g. --cpuset-cpus) */
    n = read_cpuset_cpus();
    if (n > 0) {
        long host = real_sysconf ? real_sysconf(_SC_NPROCESSORS_ONLN) : 0;
        if (limited && host > 0 && n < host) *limited = 1;
        return n;
    }

    /* 5. Host fallback */
    return real_sysconf ? real_sysconf(_SC_NPROCESSORS_ONLN) : 1;
}

long sysconf(int name) {
    resolve_real();

    if (name == _SC_NPROCESSORS_ONLN || name == _SC_NPROCESSORS_CONF)
        return resolve_cpu_count(NULL);

    return real_sysconf(name);
}

/* ---- /proc/stat synthesis ---------------------------------------------- */

struct cgroup_cpu_usage {
    unsigned long long usage_us; /* total CPU consumed by the cgroup */
    unsigned long long user_us;
    unsigned long long system_us;
};

static int read_cgroup_cpu_usage(struct cgroup_cpu_usage *u) {
    char buf[1024];

    /* cgroup v2: /sys/fs/cgroup/cpu.stat */
    if (read_small_file("/sys/fs/cgroup/cpu.stat", buf, sizeof(buf)) == 0) {
        u->usage_us = parse_key(buf, "usage_usec");
        u->user_us = parse_key(buf, "user_usec");
        u->system_us = parse_key(buf, "system_usec");
        return 0;
    }

    /* cgroup v1: cpuacct.usage is in nanoseconds; cpuacct.stat user/system
     * are in USER_HZ ticks. */
    if (read_small_file("/sys/fs/cgroup/cpuacct/cpuacct.usage", buf, sizeof(buf)) == 0) {
        long hz = real_sysconf ? real_sysconf(_SC_CLK_TCK) : 100;
        if (hz <= 0) hz = 100;
        u->usage_us = strtoull(buf, NULL, 10) / 1000;
        u->user_us = 0;
        u->system_us = 0;
        if (read_small_file("/sys/fs/cgroup/cpuacct/cpuacct.stat", buf, sizeof(buf)) == 0) {
            u->user_us = parse_key(buf, "user") * 1000000ULL / (unsigned long long) hz;
            u->system_us = parse_key(buf, "system") * 1000000ULL / (unsigned long long) hz;
        }
        return 0;
    }

    return -1;
}

/*
 * Build a container-scoped /proc/stat and return it as an memfd-backed
 * read-only fd, or -1 to let the caller fall through to the real file.
 *
 * Layout mirrors the kernel format: one aggregate "cpu" line followed by
 * ncpus "cpuN" lines. cgroup only exposes aggregate user/system time, so
 * per-cpu lines split the totals evenly (aggregate sums stay exact).
 * Idle is derived from wall-clock capacity since boot so that
 * usage + idle ~= ncpus * elapsed, matching what delta-based readers
 * (top, htop, psutil, systeminformation) expect.
 */
static int synth_proc_stat_fd(void) {
#ifdef SYS_memfd_create
    int limited = 0;
    long ncpus = resolve_cpu_count(&limited);
    if (!limited || ncpus <= 0) return -1;

    struct cgroup_cpu_usage u;
    if (read_cgroup_cpu_usage(&u) != 0) return -1;

    long hz = real_sysconf ? real_sysconf(_SC_CLK_TCK) : 100;
    if (hz <= 0) hz = 100;

    unsigned long long elapsed_us = 0;
    struct timespec ts;
    if (clock_gettime(CLOCK_BOOTTIME, &ts) == 0)
        elapsed_us = (unsigned long long) ts.tv_sec * 1000000ULL + (unsigned long long) ts.tv_nsec / 1000;

    /* If only total usage is known, attribute it all to user time. */
    if (u.user_us + u.system_us == 0) u.user_us = u.usage_us;

    unsigned long long capacity_us = elapsed_us * (unsigned long long) ncpus;
    unsigned long long idle_us = capacity_us > u.usage_us ? capacity_us - u.usage_us : 0;

    unsigned long long user_t = u.user_us * (unsigned long long) hz / 1000000ULL;
    unsigned long long sys_t = u.system_us * (unsigned long long) hz / 1000000ULL;
    unsigned long long idle_t = idle_us * (unsigned long long) hz / 1000000ULL;

    char buf[65536];
    size_t off = 0;
    off += (size_t) snprintf(buf + off, sizeof(buf) - off,
                             "cpu  %llu 0 %llu %llu 0 0 0 0 0 0\n",
                             user_t, sys_t, idle_t);

    for (long i = 0; i < ncpus && off < sizeof(buf) - 128; i++) {
        unsigned long long cu = user_t / (unsigned long long) ncpus + (i < (long) (user_t % (unsigned long long) ncpus));
        unsigned long long cs = sys_t / (unsigned long long) ncpus + (i < (long) (sys_t % (unsigned long long) ncpus));
        unsigned long long ci = idle_t / (unsigned long long) ncpus + (i < (long) (idle_t % (unsigned long long) ncpus));
        off += (size_t) snprintf(buf + off, sizeof(buf) - off,
                                 "cpu%ld %llu 0 %llu %llu 0 0 0 0 0 0\n",
                                 i, cu, cs, ci);
    }

    int fd = (int) syscall(SYS_memfd_create, "nukelab_proc_stat", 0);
    if (fd < 0) return -1;

    size_t remaining = off;
    const char *p = buf;
    while (remaining > 0) {
        ssize_t w = write(fd, p, remaining);
        if (w <= 0) {
            close(fd);
            return -1;
        }
        p += w;
        remaining -= (size_t) w;
    }
    lseek(fd, 0, SEEK_SET);
    return fd;
#else
    return -1;
#endif
}

/* Intercept only read-only opens of exactly "/proc/stat". */
static int try_synth_proc_stat(const char *path, int flags) {
    if (!path || strcmp(path, "/proc/stat") != 0) return -1;
    if ((flags & O_ACCMODE) != O_RDONLY) return -1;
    resolve_real();
    return synth_proc_stat_fd();
}

#define OPEN_BODY(real_fn)                                     \
    mode_t mode = 0;                                           \
    if (flags & (O_CREAT | O_TMPFILE)) {                       \
        va_list ap;                                            \
        va_start(ap, flags);                                   \
        mode = va_arg(ap, mode_t);                             \
        va_end(ap);                                            \
    }                                                          \
    int fd = try_synth_proc_stat(path, flags);                 \
    if (fd >= 0) return fd;                                    \
    resolve_real();                                            \
    return real_fn(path, flags, mode)

#define OPENAT_BODY(real_fn)                                   \
    mode_t mode = 0;                                           \
    if (flags & (O_CREAT | O_TMPFILE)) {                       \
        va_list ap;                                            \
        va_start(ap, flags);                                   \
        mode = va_arg(ap, mode_t);                             \
        va_end(ap);                                            \
    }                                                          \
    if (path && path[0] == '/') {                              \
        int fd = try_synth_proc_stat(path, flags);             \
        if (fd >= 0) return fd;                                \
    }                                                          \
    resolve_real();                                            \
    return real_fn(dirfd, path, flags, mode)

int open(const char *path, int flags, ...) { OPEN_BODY(real_open); }

static int call_real_open64(const char *path, int flags, mode_t mode) {
    return (real_open64 ? real_open64 : real_open)(path, flags, mode);
}
int open64(const char *path, int flags, ...) { OPEN_BODY(call_real_open64); }

int openat(int dirfd, const char *path, int flags, ...) { OPENAT_BODY(real_openat); }

static int call_real_openat64(int dirfd, const char *path, int flags, mode_t mode) {
    return (real_openat64 ? real_openat64 : real_openat)(dirfd, path, flags, mode);
}
int openat64(int dirfd, const char *path, int flags, ...) { OPENAT_BODY(call_real_openat64); }

/* _FORTIFY_SOURCE variants used by optimized glibc builds (top, htop, …). */
int __open_2(const char *path, int flags) {
    int fd = try_synth_proc_stat(path, flags);
    if (fd >= 0) return fd;
    resolve_real();
    return real___open_2 ? real___open_2(path, flags) : real_open(path, flags, 0);
}
int __open64_2(const char *path, int flags) {
    int fd = try_synth_proc_stat(path, flags);
    if (fd >= 0) return fd;
    resolve_real();
    if (real___open64_2) return real___open64_2(path, flags);
    return (real_open64 ? real_open64 : real_open)(path, flags, 0);
}
int __openat_2(int dirfd, const char *path, int flags) {
    if (path && path[0] == '/') {
        int fd = try_synth_proc_stat(path, flags);
        if (fd >= 0) return fd;
    }
    resolve_real();
    return real___openat_2 ? real___openat_2(dirfd, path, flags) : real_openat(dirfd, path, flags, 0);
}
int __openat64_2(int dirfd, const char *path, int flags) {
    if (path && path[0] == '/') {
        int fd = try_synth_proc_stat(path, flags);
        if (fd >= 0) return fd;
    }
    resolve_real();
    if (real___openat64_2) return real___openat64_2(dirfd, path, flags);
    return (real_openat64 ? real_openat64 : real_openat)(dirfd, path, flags, 0);
}

#define FOPEN_BODY(real_fn)                                    \
    resolve_real();                                            \
    if (path && mode && mode[0] == 'r' &&                      \
        strcmp(path, "/proc/stat") == 0) {                     \
        int fd = synth_proc_stat_fd();                         \
        if (fd >= 0) {                                         \
            FILE *f = fdopen(fd, mode);                        \
            if (f) return f;                                   \
            close(fd);                                         \
        }                                                      \
    }                                                          \
    return real_fn(path, mode)

FILE *fopen(const char *path, const char *mode) { FOPEN_BODY(real_fopen); }

static FILE *call_real_fopen64(const char *path, const char *mode) {
    return (real_fopen64 ? real_fopen64 : real_fopen)(path, mode);
}
FILE *fopen64(const char *path, const char *mode) { FOPEN_BODY(call_real_fopen64); }

#ifdef __cplusplus
}
#endif
