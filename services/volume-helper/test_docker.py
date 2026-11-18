# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Explicitly opt-in Docker data test using only uniquely labelled resources.

Build the helper image first, then set NUKELAB_VOLUME_HELPER_TEST_IMAGE to its
local tag or ID. Run on a local/CI test daemon; never use a production daemon.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

IMAGE = os.environ.get("NUKELAB_VOLUME_HELPER_TEST_IMAGE")
pytestmark = pytest.mark.skipif(
    not IMAGE, reason="requires an explicit local helper test image"
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def test_real_hardened_capture_restore():
    owner = str(uuid4())
    label = "nukelab.test.owner=" + owner
    source, target = (
        "nukelab-recovery-test-" + owner + suffix for suffix in ("-source", "-target")
    )
    containers = []
    volumes = []
    root = Path(tempfile.mkdtemp(prefix="nukelab-recovery-test-"))
    try:
        for volume in (source, target):
            docker("volume", "create", "--label", label, volume)
            volumes.append(volume)
        # Fixture preparation has its own root container; recovery executors below
        # always use the production non-root and no-capability configuration.
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--label",
            label,
            "--mount",
            "type=bind,source=" + str(root) + ",target=/fixture",
            "--entrypoint",
            "python",
            IMAGE,
            "-I",
            "-c",
            "import os;[(os.mkdir('/fixture/'+n,0o700),os.chown('/fixture/'+n,65532,65532)) for n in ('capture','restore')]",
        )
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            label,
            "--mount",
            "type=volume,source=" + source + ",target=/target",
            "--entrypoint",
            "python",
            IMAGE,
            "-I",
            "-c",
            "from pathlib import Path;import os;p=Path('/target');(p/'日本語').mkdir();f=p/'日本語/data';f.write_bytes(b'scientific data');os.link(f,p/'copy');(p/'link').symlink_to('日本語/data')",
        )
        limits = json.dumps(
            {
                "max_compressed_bytes": 1048576,
                "max_tar_bytes": 2097152,
                "max_file_bytes": 65536,
                "max_logical_bytes": 65536,
                "max_members": 32,
            }
        )
        backup = str(uuid4())
        checksum = None
        for action, volume in (("capture", source), ("restore", target)):
            operation, fence = str(uuid4()), str(uuid4())
            name = "nukelab-recovery-test-" + operation
            mount = (
                "type=volume,source="
                + volume
                + ",target="
                + (
                    "/source,readonly,volume-nocopy"
                    if action == "capture"
                    else "/target"
                )
            )
            args = [
                "create",
                "--name",
                name,
                "--label",
                label,
                "--network",
                "none",
                "--user",
                "65532:65532",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "64",
                "--memory",
                "1g",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=64m",
                "--mount",
                mount,
                "--mount",
                "type=bind,source=" + str(root / action) + ",target=/artifact",
            ]
            if action == "restore":
                args += [
                    "--mount",
                    "type=bind,source="
                    + str(root / "capture")
                    + ",target=/archive,readonly",
                ]
            args += [IMAGE, action, operation, fence, backup, limits]
            if checksum:
                args.append(checksum)
            identity = docker(*args)
            containers.append(identity)
            docker("start", "--attach", identity)
            info = json.loads(docker("inspect", identity))[0]
            assert info["State"]["ExitCode"] == 0
            assert info["Config"]["User"] == "65532:65532"
            host = info["HostConfig"]
            assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
            assert host["CapDrop"] == ["ALL"] and host["PidsLimit"] == 64
            assert "no-new-privileges:true" in host["SecurityOpt"]
            if action == "capture":
                metadata = json.loads(
                    docker(
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--label",
                        label,
                        "--mount",
                        "type=bind,source="
                        + str(root / "capture")
                        + ",target=/archive,readonly",
                        "--entrypoint",
                        "python",
                        IMAGE,
                        "-I",
                        "-c",
                        "print(open('/archive/completion.json').read())",
                    )
                )
                checksum = metadata["sha256"]
                assert metadata["logical_bytes"] == 15 and metadata["member_count"] == 4
        verified = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            label,
            "--mount",
            "type=volume,source=" + target + ",target=/target,readonly,volume-nocopy",
            "--entrypoint",
            "python",
            IMAGE,
            "-I",
            "-c",
            "from pathlib import Path;import os;p=Path('/target');assert (p/'copy').read_bytes()==b'scientific data';assert (p/'copy').stat().st_ino==(p/'日本語/data').stat().st_ino;assert os.readlink(p/'link')=='日本語/data';assert (p/'copy').stat().st_uid==65532;print('verified')",
        )
        assert verified == "verified"
    finally:
        for identity in containers:
            info = json.loads(docker("inspect", identity))[0]
            if info["Config"]["Labels"].get("nukelab.test.owner") == owner:
                docker("rm", "-f", identity)
        for volume in volumes:
            info = json.loads(docker("volume", "inspect", volume))[0]
            if info["Labels"].get("nukelab.test.owner") == owner:
                docker("volume", "rm", volume)
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--label",
            label,
            "--mount",
            "type=bind,source=" + str(root) + ",target=/fixture",
            "--entrypoint",
            "python",
            IMAGE,
            "-I",
            "-c",
            "from pathlib import Path;import shutil;[shutil.rmtree(p) for p in Path('/fixture').iterdir()]",
        )
        root.rmdir()
