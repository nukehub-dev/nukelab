/*
 * libnukelab_cpu.so - LD_PRELOAD library to mask host CPU count in containers
 *
 * Intercepts sysconf(_SC_NPROCESSORS_ONLN) and returns the container's
 * actual CPU allocation instead of the host's core count.
 *
 * Resolution order (first match wins):
 *   1. NUKELAB_CPU_COUNT environment variable
 *   2. /sys/fs/cgroup/cpuset.cpus.effective  (cgroup cpuset)
 *   3. /sys/fs/cgroup/cpu.max                (cgroup cpu quota)
 *   4. real sysconf()                        (host fallback)
 *
 * Build:
 *     gcc -shared -fPIC -o libnukelab_cpu.so libnukelab_cpu.c -ldl
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif

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
    FILE *fp = fopen("/sys/fs/cgroup/cpuset.cpus.effective", "r");
    if (!fp) fp = fopen("/sys/fs/cgroup/cpuset.cpus", "r"); /* cgroup v1 fallback */
    if (!fp) return 0;

    char buf[256];
    if (fgets(buf, sizeof(buf), fp)) {
        /* Strip trailing newline */
        size_t len = strlen(buf);
        if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';
        fclose(fp);
        return count_cpuset_cpus(buf);
    }
    fclose(fp);
    return 0;
}

/* Read CPU count from cgroup cpu.max (e.g. "100000 100000" = 1 CPU) */
static long read_cpu_max(void) {
    FILE *fp = fopen("/sys/fs/cgroup/cpu.max", "r");
    if (!fp) return 0;

    char buf[256];
    long count = 0;
    if (fgets(buf, sizeof(buf), fp)) {
        long quota, period;
        if (sscanf(buf, "%ld %ld", &quota, &period) == 2 && period > 0) {
            if (quota > 0) {
                count = (quota + period - 1) / period; /* ceil(quota/period) */
            }
            /* quota <= 0 or "max" means unlimited, fall through to 0 */
        }
    }
    fclose(fp);
    return count > 0 ? count : 0;
}

long sysconf(int name) {
    static long (*real_sysconf)(int) = NULL;
    if (!real_sysconf) {
        real_sysconf = (long (*)(int)) dlsym(RTLD_NEXT, "sysconf");
    }

    if (name == _SC_NPROCESSORS_ONLN || name == _SC_NPROCESSORS_CONF) {
        /* 1. Environment variable (fastest, user-overridable) */
        const char *env = getenv("NUKELAB_CPU_COUNT");
        if (env && env[0]) {
            int n = atoi(env);
            if (n > 0) return n;
        }

        /* 2. Cgroup cpu quota (throttling-based limit, e.g. --cpus=1) */
        long n = read_cpu_max();
        if (n > 0) return n;

        /* 3. Cgroup cpuset (hard affinity, e.g. --cpuset-cpus) */
        n = read_cpuset_cpus();
        if (n > 0) return n;
    }

    return real_sysconf(name);
}

#ifdef __cplusplus
}
#endif
