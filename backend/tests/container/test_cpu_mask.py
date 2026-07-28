# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for libnukelab_cpu.so CPU masking library.

These tests compile the C source and verify sysconf interception
including env var override and cgroup fallback parsing.
"""

import os
import subprocess
import tempfile

import pytest

# Path to C source file
C_SOURCE = os.path.join(
    os.path.dirname(__file__), "..", "..", "resources", "lib", "nukelab", "libnukelab_cpu.c"
)

# Small C test program that prints sysconf(_SC_NPROCESSORS_ONLN)
TEST_C_PROGRAM = """
#include <unistd.h>
#include <stdio.h>
int main() {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    printf("%ld\\n", n);
    return 0;
}
"""

# Test program that dumps /proc/stat via open()+read() or fopen()+fgets().
TEST_C_STAT_PROGRAM = r"""
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    char buf[65536];
    ssize_t n = 0;
    if (argc > 1 && strcmp(argv[1], "fopen") == 0) {
        FILE *f = fopen("/proc/stat", "r");
        if (!f) { perror("fopen"); return 1; }
        n = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
    } else {
        int fd = open("/proc/stat", O_RDONLY);
        if (fd < 0) { perror("open"); return 1; }
        n = read(fd, buf, sizeof(buf) - 1);
        close(fd);
    }
    if (n <= 0) { perror("read"); return 1; }
    buf[n] = '\0';
    fwrite(buf, 1, n, stdout);
    return 0;
}
"""


@pytest.fixture(scope="module")
def compiled_so():
    """Compile libnukelab_cpu.so once for all tests."""
    so_path = os.path.join(tempfile.gettempdir(), "libnukelab_cpu_test.so")
    src_path = os.path.abspath(C_SOURCE)

    if not os.path.exists(src_path):
        pytest.skip(f"C source not found: {src_path}")

    result = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-o", so_path, src_path, "-ldl"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to compile .so: {result.stderr}")

    yield so_path

    # Cleanup
    if os.path.exists(so_path):
        os.remove(so_path)


@pytest.fixture(scope="module")
def test_binary():
    """Compile the test C program once."""
    bin_path = os.path.join(tempfile.gettempdir(), "cpu_count_test")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
        f.write(TEST_C_PROGRAM)
        src = f.name

    result = subprocess.run(
        ["gcc", "-o", bin_path, src],
        capture_output=True,
        text=True,
    )
    os.remove(src)

    if result.returncode != 0:
        pytest.skip(f"Failed to compile test binary: {result.stderr}")

    yield bin_path

    if os.path.exists(bin_path):
        os.remove(bin_path)


def run_with_preload(binary: str, so: str, env: dict = None, args: list = None):
    """Run a binary with LD_PRELOAD set."""
    test_env = os.environ.copy()
    test_env["LD_PRELOAD"] = so
    # Remove any pre-existing NUKELAB_CPU_COUNT to avoid interference
    test_env.pop("NUKELAB_CPU_COUNT", None)
    if env:
        test_env.update(env)

    result = subprocess.run(
        [binary] + (args or []),
        capture_output=True,
        text=True,
        env=test_env,
    )
    return result


@pytest.fixture(scope="module")
def stat_binary():
    """Compile the /proc/stat reader once, with _FORTIFY_SOURCE so the
    fortified __open_2 interposition path is exercised too."""
    bin_path = os.path.join(tempfile.gettempdir(), "proc_stat_test")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
        f.write(TEST_C_STAT_PROGRAM)
        src = f.name

    result = subprocess.run(
        ["gcc", "-O2", "-D_FORTIFY_SOURCE=2", "-o", bin_path, src],
        capture_output=True,
        text=True,
    )
    os.remove(src)

    if result.returncode != 0:
        pytest.skip(f"Failed to compile stat test binary: {result.stderr}")

    yield bin_path

    if os.path.exists(bin_path):
        os.remove(bin_path)


def parse_cpu_lines(stat_text: str):
    """Split /proc/stat content into (aggregate fields, per-cpu line count)."""
    aggregate = None
    per_cpu = 0
    for line in stat_text.splitlines():
        if line.startswith("cpu ") and aggregate is None:
            aggregate = line.split()[1:]
        elif line.startswith("cpu") and line[3:4].isdigit():
            per_cpu += 1
    return aggregate, per_cpu


class TestCpuMaskEnvVar:
    """Tests for NUKELAB_CPU_COUNT env var override."""

    def test_env_var_override(self, compiled_so, test_binary):
        """sysconf should return env var value when set."""
        result = run_with_preload(test_binary, compiled_so, {"NUKELAB_CPU_COUNT": "4"})
        assert result.returncode == 0
        assert result.stdout.strip() == "4"

    def test_env_var_invalid_ignored(self, compiled_so, test_binary):
        """Invalid env var should fall through to real sysconf."""
        result = run_with_preload(test_binary, compiled_so, {"NUKELAB_CPU_COUNT": "abc"})
        assert result.returncode == 0
        # Should fall back to real CPU count (>= 1)
        assert int(result.stdout.strip()) >= 1

    def test_env_var_zero_ignored(self, compiled_so, test_binary):
        """Zero env var should fall through to real sysconf."""
        result = run_with_preload(test_binary, compiled_so, {"NUKELAB_CPU_COUNT": "0"})
        assert result.returncode == 0
        assert int(result.stdout.strip()) >= 1

    def test_env_var_negative_ignored(self, compiled_so, test_binary):
        """Negative env var should fall through to real sysconf."""
        result = run_with_preload(test_binary, compiled_so, {"NUKELAB_CPU_COUNT": "-1"})
        assert result.returncode == 0
        assert int(result.stdout.strip()) >= 1


class TestCpuMaskCgroupFallback:
    """Tests for cgroup fallback when env var is not set."""

    def test_falls_back_to_real_sysconf(self, compiled_so, test_binary):
        """Without env var and without cgroup files, should return real count."""
        result = run_with_preload(test_binary, compiled_so)
        assert result.returncode == 0
        real_count = os.cpu_count()
        assert int(result.stdout.strip()) == real_count


class TestCpuMaskConf:
    """Tests for _SC_NPROCESSORS_CONF in addition to _SC_NPROCESSORS_ONLN."""

    def test_conf_override(self, compiled_so):
        """_SC_NPROCESSORS_CONF should also be intercepted."""
        program = """
        #include <unistd.h>
        #include <stdio.h>
        int main() {
            long onln = sysconf(_SC_NPROCESSORS_ONLN);
            long conf = sysconf(_SC_NPROCESSORS_CONF);
            printf("%ld %ld\\n", onln, conf);
            return 0;
        }
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(program)
            src = f.name

        bin_path = os.path.join(tempfile.gettempdir(), "cpu_conf_test")
        subprocess.run(["gcc", "-o", bin_path, src], check=True)
        os.remove(src)

        result = run_with_preload(bin_path, compiled_so, {"NUKELAB_CPU_COUNT": "2"})
        os.remove(bin_path)

        assert result.returncode == 0
        onln, conf = result.stdout.strip().split()
        assert onln == "2"
        assert conf == "2"


class TestProcStatVirtualization:
    """Tests for container-scoped /proc/stat synthesis."""

    @pytest.fixture
    def cgroup_cpu_counters(self):
        if not (
            os.path.exists("/sys/fs/cgroup/cpu.stat")
            or os.path.exists("/sys/fs/cgroup/cpuacct/cpuacct.usage")
        ):
            pytest.skip("cgroup CPU counters not available in this environment")

    def test_open_returns_synthesized_stat(self, compiled_so, stat_binary, cgroup_cpu_counters):
        """With a CPU limit, open('/proc/stat') yields a container-scoped file."""
        result = run_with_preload(stat_binary, compiled_so, {"NUKELAB_CPU_COUNT": "2"})
        assert result.returncode == 0, result.stderr

        aggregate, per_cpu = parse_cpu_lines(result.stdout)
        assert aggregate is not None
        assert per_cpu == 2
        # Kernel format: user nice system idle iowait irq softirq steal guest guest_nice
        assert len(aggregate) == 10
        assert all(int(field) >= 0 for field in aggregate)

    def test_fopen_returns_synthesized_stat(self, compiled_so, stat_binary, cgroup_cpu_counters):
        """The fopen() interposition path must behave like open()."""
        result = run_with_preload(stat_binary, compiled_so, {"NUKELAB_CPU_COUNT": "3"}, args=["fopen"])
        assert result.returncode == 0, result.stderr

        _, per_cpu = parse_cpu_lines(result.stdout)
        assert per_cpu == 3

    def test_per_cpu_lines_sum_to_aggregate(self, compiled_so, stat_binary, cgroup_cpu_counters):
        """Evenly split per-cpu lines must add back up to the aggregate."""
        result = run_with_preload(stat_binary, compiled_so, {"NUKELAB_CPU_COUNT": "4"})
        assert result.returncode == 0, result.stderr

        lines = [l.split() for l in result.stdout.splitlines() if l.startswith("cpu")]
        aggregate = [int(v) for v in lines[0][1:11]]
        per_cpu = [[int(v) for v in l[1:11]] for l in lines[1:]]
        assert len(per_cpu) == 4
        for col in range(10):
            assert sum(row[col] for row in per_cpu) == aggregate[col]

    def test_passthrough_without_limit(self, compiled_so, stat_binary):
        """Without env var or cgroup limit, the real /proc/stat is served."""
        result = run_with_preload(stat_binary, compiled_so)
        assert result.returncode == 0, result.stderr

        _, per_cpu = parse_cpu_lines(result.stdout)
        assert per_cpu == os.cpu_count()

    def test_write_open_not_intercepted(self, compiled_so, stat_binary):
        """Write-mode opens must keep the kernel's semantics (read-only file)."""
        program = r"""
        #include <fcntl.h>
        #include <stdio.h>
        int main(void) {
            int fd = open("/proc/stat", O_WRONLY);
            printf("%d\n", fd < 0 ? 0 : 1);
            return 0;
        }
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(program)
            src = f.name

        bin_path = os.path.join(tempfile.gettempdir(), "proc_stat_write_test")
        subprocess.run(["gcc", "-o", bin_path, src], check=True)
        os.remove(src)

        result = run_with_preload(bin_path, compiled_so, {"NUKELAB_CPU_COUNT": "2"})
        os.remove(bin_path)

        assert result.returncode == 0
        assert result.stdout.strip() == "0"
