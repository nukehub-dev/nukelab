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


def run_with_preload(binary: str, so: str, env: dict = None):
    """Run a binary with LD_PRELOAD set."""
    test_env = os.environ.copy()
    test_env["LD_PRELOAD"] = so
    # Remove any pre-existing NUKELAB_CPU_COUNT to avoid interference
    test_env.pop("NUKELAB_CPU_COUNT", None)
    if env:
        test_env.update(env)

    result = subprocess.run(
        [binary],
        capture_output=True,
        text=True,
        env=test_env,
    )
    return result


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
