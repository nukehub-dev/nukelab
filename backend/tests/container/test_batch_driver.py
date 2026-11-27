# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch jobs use a separate, fail-closed headless container profile."""

import uuid
from unittest.mock import AsyncMock, Mock

import aiodocker
import pytest

from app.config import settings
from app.container.docker_driver import DockerDriver
from app.container.driver import ContainerDriver, ContainerDriverError

JOB_ID = str(uuid.uuid4())
FENCE = str(uuid.uuid4())
NAME = "nukelab-job-" + JOB_ID
PREP_NAME = "nukelab-job-prep-" + JOB_ID
IMAGE = "ghcr.io/nukehub-dev/workspace@sha256:" + "a" * 64
WORK_VOLUME = "private-work"


def driver():
    runtime = DockerDriver()
    runtime.client = Mock()
    runtime.client.containers = AsyncMock()
    runtime.client.images = Mock()
    runtime.client.images.pull = AsyncMock()
    container = Mock()
    container.id = "job-container-id"
    runtime.client.containers.create.return_value = container
    return runtime, container


def work_mount(source=WORK_VOLUME):
    return {"Type": "volume", "Source": source, "Target": "/work", "ReadOnly": False}


def toolchain_mount(*, target="/opt/nuke", source="toolchain-cache", read_only=True, kind="volume"):
    return {"Type": kind, "Source": source, "Target": target, "ReadOnly": read_only}


def job_labels(**updates):
    labels = {
        "nukelab.workload": "job",
        "nukelab.job.id": JOB_ID,
        "nukelab.job.fence": FENCE,
        "nukelab.managed": "true",
        "com.example/job": "extra",
    }
    labels.update(updates)
    return labels


def prep_helper():
    helper = Mock()
    helper.id = "prep-helper-id"
    helper.start = AsyncMock()
    helper.wait = AsyncMock(return_value={"StatusCode": 0})
    helper.delete = AsyncMock()
    return helper


def prep_invocation(**overrides):
    args = {
        "name": PREP_NAME,
        "image": IMAGE,
        "volume": WORK_VOLUME,
        "labels": {
            "nukelab.managed": "true",
            "nukelab.batch.prep": JOB_ID,
            "nukelab.job.id": JOB_ID,
            "com.example/job": "extra",
        },
        "timeout_seconds": 30,
    }
    args.update(overrides)
    return args


def invocation(**overrides):
    args = {
        "name": NAME,
        "image": IMAGE,
        "argv": [
            "python",
            "-c",
            "print('hello world')",
            "--flag=a b",
            "$(touch /tmp/pwned)",
            "semi;colon|pipe",
        ],
        "mounts": [work_mount()],
        "labels": job_labels(),
        "limits": {
            "cpu": 1.5,
            "memory_bytes": 512 * 1024**2,
            "pids_limit": 128,
            "tmpfs_bytes": 32 * 1024**2,
        },
        "env": {
            "JOB_INDEX": "7",
            "JOB_INPUT": "two words",
            "PYTHONPATH": "/opt/nuke/lib",
        },
        "workdir": "/work",
        "timeout_seconds": None,
    }
    args.update(overrides)
    return args


@pytest.mark.asyncio
async def test_create_config_is_exact_and_hardened():
    runtime, container = driver()
    args = invocation()

    assert await runtime.create_batch_container(**args) == "job-container-id"

    expected = {
        "Image": IMAGE,
        "Entrypoint": ["python"],
        "Cmd": [
            "-c",
            "print('hello world')",
            "--flag=a b",
            "$(touch /tmp/pwned)",
            "semi;colon|pipe",
        ],
        "User": "65532:65532",
        "WorkingDir": "/work",
        "Env": [
            "HOME=/tmp",
            "TMPDIR=/tmp",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONUNBUFFERED=1",
            "JOB_INDEX=7",
            "JOB_INPUT=two words",
            "PYTHONPATH=/opt/nuke/lib",
        ],
        "Labels": job_labels(),
        "Healthcheck": {"Test": ["NONE"]},
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": WORK_VOLUME,
                    "Target": "/work",
                    "ReadOnly": False,
                    "VolumeOptions": {"NoCopy": True},
                }
            ],
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": "none",
            "PublishAllPorts": False,
            "Memory": 512 * 1024**2,
            "MemorySwap": 512 * 1024**2,
            "NanoCpus": 1_500_000_000,
            "PidsLimit": 128,
            "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,noexec,size=33554432,mode=1777",
                "/home": "rw,nosuid,nodev,noexec,size=16777216,mode=1777",
            },
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": "1m", "max-file": "1"},
            },
        },
    }
    runtime.client.containers.create.assert_awaited_once_with(expected, name=NAME)
    container.start.assert_not_called()
    runtime.client.images.pull.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_tmpfs_and_default_timeout_wrapper_are_absent():
    runtime, _ = driver()
    arguments = invocation()
    arguments["limits"] = {
        "cpu": 1,
        "memory_bytes": 64 * 1024**2,
        "pids_limit": 16,
    }
    arguments["timeout_seconds"] = None

    await runtime.create_batch_container(**arguments)

    config = runtime.client.containers.create.await_args.args[0]
    assert config["HostConfig"]["Tmpfs"]["/tmp"] == (
        "rw,nosuid,nodev,noexec,size=67108864,mode=1777"
    )
    assert config["Entrypoint"] == ["python"]
    assert config["Cmd"] == arguments["argv"][1:]
    assert "/usr/bin/timeout" not in config["Entrypoint"]


@pytest.mark.asyncio
async def test_timeout_uses_the_trusted_supervisor_without_a_shell():
    runtime, _ = driver()
    arguments = invocation(timeout_seconds=3600)

    await runtime.create_batch_container(**arguments)

    config = runtime.client.containers.create.await_args.args[0]
    assert config["Entrypoint"] == ["/usr/bin/timeout"]
    assert config["Cmd"] == [
        "--signal=TERM",
        "--kill-after=10",
        "3600",
        *arguments["argv"],
    ]
    assert "--" not in config["Cmd"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image",
    [
        IMAGE,
        "sha256:" + "b" * 64,
        "registry.test:5000/team/workspace@sha256:" + "c" * 64,
    ],
)
async def test_pinned_image_forms_are_accepted(image):
    runtime, _ = driver()

    await runtime.create_batch_container(**invocation(image=image))

    config = runtime.client.containers.create.await_args.args[0]
    assert config["Image"] == image
    runtime.client.images.pull.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mount",
    [
        toolchain_mount(),
        toolchain_mount(kind="bind", source="/opt/nukelab/toolchain"),
    ],
)
async def test_approved_toolchain_mount_is_read_only(mount):
    runtime, _ = driver()
    arguments = invocation()
    arguments["mounts"] = [work_mount(), mount]

    await runtime.create_batch_container(**arguments)

    config = runtime.client.containers.create.await_args.args[0]
    expected = {
        "Type": mount["Type"],
        "Source": mount["Source"],
        "Target": mount["Target"],
        "ReadOnly": True,
    }
    if mount["Type"] == "volume":
        expected["VolumeOptions"] = {"NoCopy": True}
    assert config["HostConfig"]["Mounts"] == [
        {
            "Type": "volume",
            "Source": WORK_VOLUME,
            "Target": "/work",
            "ReadOnly": False,
            "VolumeOptions": {"NoCopy": True},
        },
        expected,
    ]


@pytest.mark.asyncio
async def test_batch_profile_ignores_the_interactive_hardening_toggle(monkeypatch):
    monkeypatch.setattr(settings, "container_hardening_enabled", False)
    runtime, _ = driver()

    await runtime.create_batch_container(**invocation())

    config = runtime.client.containers.create.await_args.args[0]
    assert config["User"] == "65532:65532"
    assert config["HostConfig"]["ReadonlyRootfs"] is True
    assert config["HostConfig"]["CapDrop"] == ["ALL"]
    assert config["HostConfig"]["SecurityOpt"] == ["no-new-privileges:true"]
    assert config["HostConfig"]["NetworkMode"] == "none"


@pytest.mark.asyncio
async def test_unapproved_configured_user_never_becomes_root(monkeypatch):
    monkeypatch.setattr(settings, "container_uid", 0)
    monkeypatch.setattr(settings, "container_gid", 0)
    runtime, _ = driver()

    await runtime.create_batch_container(**invocation())

    config = runtime.client.containers.create.await_args.args[0]
    assert config["User"] == "65532:65532"


INVALID_REQUESTS = [
    pytest.param(lambda value: value.update(name="server-" + JOB_ID), id="name-prefix"),
    pytest.param(lambda value: value.update(name="nukelab-job-not-a-uuid"), id="name-uuid"),
    pytest.param(
        lambda value: value.update(name="nukelab-job-" + JOB_ID.upper()), id="name-uppercase"
    ),
    pytest.param(lambda value: value.update(image="workspace:latest"), id="image-tag"),
    pytest.param(
        lambda value: value.update(image="https://registry.test/workspace@sha256:" + "a" * 64),
        id="image-url",
    ),
    pytest.param(
        lambda value: value.update(image="workspace@sha256:" + "A" * 64),
        id="image-uppercase-digest",
    ),
    pytest.param(
        lambda value: value.update(image="user:secret@registry.test/workspace@sha256:" + "a" * 64),
        id="image-credentials",
    ),
    pytest.param(
        lambda value: value.update(image="workspace:tag@sha256:" + "a" * 64),
        id="image-tag-and-digest",
    ),
    pytest.param(
        lambda value: value.update(image="workspace:5000@sha256:" + "a" * 64),
        id="image-numeric-tag",
    ),
    pytest.param(lambda value: value.update(argv=[]), id="argv-empty"),
    pytest.param(lambda value: value.update(argv=["-c", "print('x')"]), id="argv-leading-dash"),
    pytest.param(lambda value: value.update(argv=["--", "x"]), id="argv-option-separator"),
    pytest.param(lambda value: value.update(argv=["python", "bad\x00arg"]), id="argv-nul"),
    pytest.param(lambda value: value.update(argv=["x"] * 65), id="argv-count"),
    pytest.param(lambda value: value.update(argv=["x" * 16385]), id="argv-size"),
    pytest.param(lambda value: value.update(argv="python -c print"), id="argv-string"),
    pytest.param(lambda value: value.update(argv=[123]), id="argv-type"),
    pytest.param(
        lambda value: value.update(labels=job_labels(**{"nukelab.job.id": str(uuid.uuid4())})),
        id="label-job-id",
    ),
    pytest.param(
        lambda value: value.update(labels=job_labels(**{"nukelab.workload": "server"})),
        id="label-workload",
    ),
    pytest.param(
        lambda value: value.update(labels=job_labels(**{"nukelab.job.fence": "not-a-uuid"})),
        id="label-fence",
    ),
    pytest.param(
        lambda value: value.update(labels=job_labels(extra="x" * 1025)),
        id="label-value-size",
    ),
    pytest.param(
        lambda value: value.update(labels=job_labels(extra="bad\nlabel")),
        id="label-control-character",
    ),
    pytest.param(lambda value: value.update(mounts=[]), id="mount-missing-work"),
    pytest.param(lambda value: value["mounts"][0].update(ReadOnly=True), id="mount-work-readonly"),
    pytest.param(lambda value: value["mounts"].append(work_mount()), id="mount-duplicate-work"),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(read_only=False)),
        id="mount-writable-toolchain",
    ),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(target="/etc")),
        id="mount-toolchain-etc",
    ),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(target="/etc/nukelab/auth")),
        id="mount-toolchain-secret-path",
    ),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(target="/opt/../etc")),
        id="mount-target-traversal",
    ),
    pytest.param(
        lambda value: value["mounts"].append(
            toolchain_mount(kind="bind", source="/opt/nukelab/../secret")
        ),
        id="mount-bind-traversal",
    ),
    pytest.param(
        lambda value: value["mounts"].append(
            toolchain_mount(kind="bind", source="relative/toolchain")
        ),
        id="mount-bind-relative",
    ),
    pytest.param(
        lambda value: value["mounts"][0].update(Source="-bad-volume"), id="mount-volume-name"
    ),
    pytest.param(
        lambda value: value["mounts"][0].update(Propagation="rprivate"), id="mount-extra-key"
    ),
    pytest.param(lambda value: value["mounts"][0].update(ReadOnly=0), id="mount-readonly-type"),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(target="/data", read_only=False)),
        id="mount-writable-extra",
    ),
    pytest.param(
        lambda value: value["mounts"].append(toolchain_mount(target="/home")),
        id="mount-fixed-tmpfs",
    ),
    pytest.param(lambda value: value["limits"].update(cpu=0.05), id="limit-cpu-low"),
    pytest.param(lambda value: value["limits"].update(cpu=True), id="limit-cpu-bool"),
    pytest.param(
        lambda value: value["limits"].update(memory_bytes=64 * 1024**2 - 1), id="limit-memory-low"
    ),
    pytest.param(lambda value: value["limits"].update(memory_bytes=True), id="limit-memory-bool"),
    pytest.param(lambda value: value["limits"].update(pids_limit=15), id="limit-pids-low"),
    pytest.param(
        lambda value: value["limits"].update(tmpfs_bytes=16 * 1024**2 - 1), id="limit-tmpfs-low"
    ),
    pytest.param(lambda value: value["limits"].update(disk_bytes=1), id="limit-unknown"),
    pytest.param(lambda value: value["limits"].pop("pids_limit"), id="limit-missing-pids"),
    pytest.param(lambda value: value["env"].update(HOME="/work"), id="env-home-override"),
    pytest.param(lambda value: value["env"].update(TMPDIR="/work"), id="env-tmpdir-override"),
    pytest.param(
        lambda value: value["env"].update(PYTHONDONTWRITEBYTECODE="0"),
        id="env-bytecode-override",
    ),
    pytest.param(
        lambda value: value["env"].update(PYTHONUNBUFFERED="0"), id="env-buffered-override"
    ),
    pytest.param(lambda value: value["env"].update(EXTRA="bad\x00value"), id="env-nul"),
    pytest.param(lambda value: value["env"].update(EXTRA=7), id="env-value-type"),
    pytest.param(lambda value: value["env"].update(**{"BAD=KEY": "value"}), id="env-key"),
    pytest.param(lambda value: value["env"].update(EXTRA="x" * 8193), id="env-value-size"),
    pytest.param(lambda value: value.update(workdir="/tmp"), id="workdir"),
    pytest.param(lambda value: value.update(timeout_seconds=0), id="timeout-zero"),
    pytest.param(lambda value: value.update(timeout_seconds=24 * 3600 + 1), id="timeout-high"),
    pytest.param(lambda value: value.update(timeout_seconds=True), id="timeout-bool"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", INVALID_REQUESTS)
async def test_invalid_requests_never_reach_the_runtime(mutate):
    runtime, _ = driver()
    arguments = invocation()
    mutate(arguments)

    with pytest.raises(ContainerDriverError, match="Invalid batch job request"):
        await runtime.create_batch_container(**arguments)

    runtime.client.containers.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_create_error_is_mapped_and_never_started():
    runtime, container = driver()
    runtime.client.containers.create.side_effect = aiodocker.DockerError(
        status=409, data={"message": "name exists"}
    )

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.create_batch_container(**invocation())

    assert exc_info.value.message == "name exists"
    assert exc_info.value.status == 409
    container.start.assert_not_called()


@pytest.mark.asyncio
async def test_default_interface_fails_closed():
    with pytest.raises(ContainerDriverError, match="unsupported"):
        await ContainerDriver.create_batch_container(Mock(), **invocation())


@pytest.mark.asyncio
async def test_volume_prepare_config_is_exact_and_root_only_for_the_helper():
    runtime, _ = driver()
    helper = prep_helper()
    runtime.client.containers.create.return_value = helper
    arguments = prep_invocation()

    assert await runtime.prepare_batch_volume(**arguments) is None

    expected = {
        "Image": IMAGE,
        "Entrypoint": ["/bin/chmod"],
        "Cmd": ["0777", "/work"],
        "User": "0:0",
        "WorkingDir": "/",
        "Labels": {
            "nukelab.managed": "true",
            "nukelab.batch.prep": JOB_ID,
            "nukelab.job.id": JOB_ID,
            "com.example/job": "extra",
        },
        "Healthcheck": {"Test": ["NONE"]},
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": WORK_VOLUME,
                    "Target": "/work",
                    "ReadOnly": False,
                    "VolumeOptions": {"NoCopy": True},
                }
            ],
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": "none",
            "Memory": 64 * 1024**2,
            "NanoCpus": 100_000_000,
            "PidsLimit": 16,
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": "1m", "max-file": "1"},
            },
        },
    }
    runtime.client.containers.create.assert_awaited_once_with(expected, name=PREP_NAME)
    helper.start.assert_awaited_once_with()
    helper.wait.assert_awaited_once_with()
    helper.delete.assert_awaited_once_with(force=True)
    runtime.client.images.pull.assert_not_awaited()


@pytest.mark.asyncio
async def test_volume_prepare_injects_reserved_labels():
    runtime, _ = driver()
    helper = prep_helper()
    runtime.client.containers.create.return_value = helper

    await runtime.prepare_batch_volume(**prep_invocation(labels={}))

    config = runtime.client.containers.create.await_args.args[0]
    assert config["Labels"] == {
        "nukelab.managed": "true",
        "nukelab.batch.prep": JOB_ID,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"StatusCode": 17}, {"StatusCode": "0"}, {"StatusCode": True}])
async def test_volume_prepare_nonzero_or_invalid_exit_fails_and_cleans_up(result):
    runtime, _ = driver()
    helper = prep_helper()
    helper.wait.return_value = result
    runtime.client.containers.create.return_value = helper

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.prepare_batch_volume(**prep_invocation())

    assert exc_info.value.message == "batch_volume_prepare_failed"
    helper.delete.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_volume_prepare_timeout_fails_and_cleans_up():
    runtime, _ = driver()
    helper = prep_helper()
    helper.wait = AsyncMock(side_effect=TimeoutError)
    runtime.client.containers.create.return_value = helper

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.prepare_batch_volume(**prep_invocation())

    assert exc_info.value.message == "batch_volume_prepare_failed"
    helper.delete.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_volume_prepare_start_failure_fails_and_cleans_up():
    runtime, _ = driver()
    helper = prep_helper()
    helper.start = AsyncMock(
        side_effect=aiodocker.DockerError(status=500, data={"message": "start failed"})
    )
    runtime.client.containers.create.return_value = helper

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.prepare_batch_volume(**prep_invocation())

    assert exc_info.value.message == "batch_volume_prepare_failed"
    helper.delete.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 1])
async def test_volume_prepare_cleanup_failure_is_distinct(exit_code):
    runtime, _ = driver()
    helper = prep_helper()
    helper.wait.return_value = {"StatusCode": exit_code}
    helper.delete = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    runtime.client.containers.create.return_value = helper

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.prepare_batch_volume(**prep_invocation())

    assert exc_info.value.message == "batch_volume_prepare_unknown"


@pytest.mark.asyncio
async def test_volume_prepare_create_error_is_mapped():
    runtime, _ = driver()
    runtime.client.containers.create.side_effect = aiodocker.DockerError(
        status=409, data={"message": "name exists"}
    )

    with pytest.raises(ContainerDriverError) as exc_info:
        await runtime.prepare_batch_volume(**prep_invocation())

    assert exc_info.value.message == "name exists"
    assert exc_info.value.status == 409


INVALID_PREP_REQUESTS = [
    pytest.param(lambda value: value.update(name="nukelab-job-" + JOB_ID), id="name-prefix"),
    pytest.param(lambda value: value.update(name="nukelab-job-prep-not-a-uuid"), id="name-uuid"),
    pytest.param(
        lambda value: value.update(name="nukelab-job-prep-" + JOB_ID.upper()),
        id="name-uppercase",
    ),
    pytest.param(lambda value: value.update(image="workspace:latest"), id="image-tag"),
    pytest.param(
        lambda value: value.update(image="workspace:5000@sha256:" + "a" * 64),
        id="image-numeric-tag",
    ),
    pytest.param(lambda value: value.update(volume="bad name"), id="volume-space"),
    pytest.param(lambda value: value.update(volume="/absolute"), id="volume-absolute"),
    pytest.param(lambda value: value.update(volume="-leading"), id="volume-leading"),
    pytest.param(lambda value: value.update(volume="a" * 256), id="volume-size"),
    pytest.param(
        lambda value: value.update(labels={"nukelab.managed": "false"}),
        id="label-managed",
    ),
    pytest.param(
        lambda value: value.update(labels={"nukelab.batch.prep": str(uuid.uuid4())}),
        id="label-prep-mismatch",
    ),
    pytest.param(lambda value: value.update(labels={"extra": 7}), id="label-type"),
    pytest.param(lambda value: value.update(labels={"extra": "x" * 1025}), id="label-size"),
    pytest.param(lambda value: value.update(timeout_seconds=0), id="timeout-zero"),
    pytest.param(lambda value: value.update(timeout_seconds=301), id="timeout-high"),
    pytest.param(lambda value: value.update(timeout_seconds=True), id="timeout-bool"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", INVALID_PREP_REQUESTS)
async def test_invalid_volume_prepare_never_reaches_the_runtime(mutate):
    runtime, _ = driver()
    arguments = prep_invocation()
    mutate(arguments)

    with pytest.raises(ContainerDriverError, match="Invalid batch job request"):
        await runtime.prepare_batch_volume(**arguments)

    runtime.client.containers.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_volume_prepare_interface_fails_closed():
    with pytest.raises(ContainerDriverError, match="unsupported"):
        await ContainerDriver.prepare_batch_volume(Mock(), **prep_invocation())
