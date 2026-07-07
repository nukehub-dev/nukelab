# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import io
import logging
import os
import tarfile
import uuid

import aiodocker
import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class ContainerClient:
    VOLUME_CPU_LIB = "nukelab-cpu-lib"
    CPU_LIB_TARGET = "/usr/local/lib/nukelab"

    def __init__(self):
        self.client: aiodocker.Docker | None = None
        self._available_cgroup_controllers: set[str] | None = None
        self._storage_support: bool | None = None
        self._lxcfs_support: bool | None = None
        self._cpu_lib_volume_ready: bool = False

    async def connect(self):
        """Connect to Docker/Podman socket"""
        self.client = aiodocker.Docker(url=f"unix://{settings.docker_socket}")

    async def close(self):
        """Close connection"""
        if self.client:
            await self.client.close()

    async def pull_image(self, image: str):
        """Pull Docker image"""
        await self.client.images.pull(image)

    async def _get_available_controllers(self) -> set[str]:
        """Detect available cgroup v2 controllers from the host"""
        if self._available_cgroup_controllers is not None:
            return self._available_cgroup_controllers

        controllers = set()
        try:
            # Root cgroup controllers
            cgroup_path = "/sys/fs/cgroup/cgroup.controllers"
            if os.path.exists(cgroup_path):
                with open(cgroup_path) as f:
                    controllers.update(f.read().strip().split())

            # Current user's subtree controllers
            subtree_path = "/sys/fs/cgroup/cgroup.subtree_control"
            if os.path.exists(subtree_path):
                with open(subtree_path) as f:
                    controllers.update(f.read().strip().split())
        except Exception as e:
            logger.warning(f"Could not detect cgroup controllers: {e}")

        self._available_cgroup_controllers = controllers
        return controllers

    async def _check_lxcfs_support(self) -> bool:
        """Check if lxcfs is available on the host for cgroup-aware /proc"""
        if self._lxcfs_support is not None:
            return self._lxcfs_support

        lxcfs_procs = [
            "/var/lib/lxcfs/proc/meminfo",
            "/var/lib/lxcfs/proc/cpuinfo",
            "/var/lib/lxcfs/proc/uptime",
        ]

        # Check if lxcfs proc files exist on the host
        for proc_file in lxcfs_procs:
            if not os.path.exists(proc_file):
                logger.info(
                    f"lxcfs not available ({proc_file} missing). "
                    f"Install and start lxcfs on the host for cgroup-aware /proc inside containers:\n"
                    f"  Ubuntu/Debian: sudo apt install lxcfs && sudo systemctl enable --now lxcfs\n"
                    f"  RHEL/CentOS:   sudo dnf install lxcfs && sudo systemctl enable --now lxcfs\n"
                    f"  Arch:          sudo pacman -S lxcfs && sudo systemctl enable --now lxcfs"
                )
                self._lxcfs_support = False
                return False

        logger.info("lxcfs detected. Cgroup-aware /proc will be mounted into containers.")
        self._lxcfs_support = True
        return True

    def _get_lxcfs_mounts(self) -> list:
        """Get lxcfs bind mounts for cgroup-aware /proc files"""
        if not self._lxcfs_support:
            return []

        mounts = []
        lxcfs_base = "/var/lib/lxcfs"
        proc_files = ["meminfo", "cpuinfo", "diskstats", "loadavg", "stat", "swaps", "uptime"]

        for proc_file in proc_files:
            host_path = f"{lxcfs_base}/proc/{proc_file}"
            if os.path.exists(host_path):
                mounts.append(f"{host_path}:/proc/{proc_file}:rw")

        return mounts

    def _get_cpu_env(self, cpu_limit: float | None) -> dict:
        """
        Return environment variables that tell common libraries how many
        threads/cores to use, and set LD_PRELOAD to intercept sysconf()
        so programs see the plan's CPU count instead of host cores.
        """
        if not cpu_limit or cpu_limit < 1:
            cpu_limit = os.cpu_count() or 1
        n = int(cpu_limit)
        return {
            "OMP_NUM_THREADS": str(n),
            "MKL_NUM_THREADS": str(n),
            "OPENBLAS_NUM_THREADS": str(n),
            "VECLIB_MAXIMUM_THREADS": str(n),
            "NUMEXPR_NUM_THREADS": str(n),
            "NUKELAB_CPU_COUNT": str(n),
            "LD_PRELOAD": "/usr/local/lib/nukelab/libnukelab_cpu.so",
        }

    async def _inject_cpu_files(self, container, cpu_limit: float | None) -> None:
        """Inject system-wide CPU masking files into the container.

        Writes:
          - /etc/ld.so.preload   (root-only, survives any env clearing)
          - /etc/profile.d/nukelab-cpu.sh  (login shells get env vars)
        """
        if not cpu_limit or cpu_limit < 1:
            cpu_limit = os.cpu_count() or 1
        n = int(cpu_limit)

        # /etc/ld.so.preload — system-wide library preload, root-only
        preload_path = "/usr/local/lib/nukelab/libnukelab_cpu.so"
        ld_preload = f"{preload_path}\n"

        # /etc/profile.d/nukelab-cpu.sh — env vars for login shells
        # Preserve an existing LD_PRELOAD (e.g. libnss_wrapper.so) by appending
        # the CPU mask library instead of replacing it.
        profile_script = (
            f'export LD_PRELOAD="${{LD_PRELOAD:+${{LD_PRELOAD}}:}}{preload_path}"\n'
            f"export NUKELAB_CPU_COUNT={n}\n"
            f"export OMP_NUM_THREADS={n}\n"
            f"export MKL_NUM_THREADS={n}\n"
            f"export OPENBLAS_NUM_THREADS={n}\n"
            f"export VECLIB_MAXIMUM_THREADS={n}\n"
            f"export NUMEXPR_NUM_THREADS={n}\n"
        )

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            # /etc/ld.so.preload
            data = ld_preload.encode("utf-8")
            info = tarfile.TarInfo(name="ld.so.preload")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

            # /etc/profile.d/nukelab-cpu.sh
            data = profile_script.encode("utf-8")
            info = tarfile.TarInfo(name="profile.d/nukelab-cpu.sh")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

        tar_buffer.seek(0)

        try:
            await container.put_archive("/etc", tar_buffer.read())
        except Exception as e:
            logger.warning(f"Failed to inject CPU system files: {e}")

    async def _ensure_cpu_lib_volume(self) -> None:
        """Ensure the CPU mask library volume is mounted into containers.

        The volume is created and populated by nukelabctl during startup.
        The backend only checks for its existence and mounts it.
        """
        if self._cpu_lib_volume_ready:
            return

        try:
            await self.client.volumes.get(self.VOLUME_CPU_LIB)
            self._cpu_lib_volume_ready = True
        except Exception:
            logger.warning(
                f"Volume {self.VOLUME_CPU_LIB} not found. "
                f"Run './nukelabctl start' or './nukelabctl build' to create it."
            )

    async def _check_storage_support(self) -> bool:
        """Check if storage limits are supported (requires XFS with pquota, ZFS, etc.)"""
        if self._storage_support is not None:
            return self._storage_support

        try:
            # Ensure busybox is available for the test
            try:
                await self.client.images.get("busybox:latest")
            except Exception:
                try:
                    await self.client.images.pull("busybox:latest")
                except Exception as pull_err:
                    logger.warning(
                        f"Could not pull busybox for storage test: {pull_err}. "
                        f"Storage limits will be disabled."
                    )
                    self._storage_support = False
                    return False

            test_container = await self.client.containers.create(
                {"Image": "busybox:latest", "HostConfig": {"StorageOpt": {"size": "10m"}}},
                name=f"test-storage-{uuid.uuid4().hex[:8]}",
            )
            await test_container.delete(force=True)
            logger.info("Storage limits are supported by the current driver.")
            self._storage_support = True
            return True
        except Exception as e:
            logger.warning(
                f"Storage limits not supported: {e}. "
                f"Common in rootless dev environments (overlayfs). "
                f"Expected in production with XFS(pquota)/ZFS/Btrfs."
            )
            self._storage_support = False
            return False

    async def create_container(
        self,
        name: str,
        image: str,
        command: str | None = None,
        ports: dict | None = None,
        volumes: dict | None = None,
        env: dict | None = None,
        labels: dict | None = None,
        network: str | None = None,
        cpu_limit: float | None = None,
        memory_limit: str | None = None,
        disk_limit: str | None = None,
        hostname: str | None = None,
        network_aliases: list[str] | None = None,
    ):
        """Create a new container with graceful cgroup fallback"""
        env_vars = dict(env or {})
        cpu_env = self._get_cpu_env(cpu_limit)
        # Combine LD_PRELOAD so both nss-wrapper and the CPU-mask library load.
        if "LD_PRELOAD" in env_vars and "LD_PRELOAD" in cpu_env:
            env_vars["LD_PRELOAD"] = f"{env_vars['LD_PRELOAD']}:{cpu_env['LD_PRELOAD']}"
            del cpu_env["LD_PRELOAD"]

        config = {
            "Image": image,
            "Cmd": command.split() if command else None,
            "Labels": labels or {},
            "Env": [f"{k}={v}" for k, v in env_vars.items()]
            + [f"{k}={v}" for k, v in cpu_env.items()],
            "HostConfig": {
                "NetworkMode": network or settings.docker_network,
                "PublishAllPorts": False,
            },
        }

        # Add a short network alias so the backend health probe can use a
        # DNS-safe hostname instead of the potentially very long container name.
        # Container names can exceed the 63-byte DNS label limit, causing
        # getaddrinfo to fail with "label too long".
        net_name = network or settings.docker_network
        if network_aliases:
            config["NetworkingConfig"] = {
                "EndpointsConfig": {
                    net_name: {
                        "Aliases": list(network_aliases),
                    }
                }
            }

        if hostname:
            config["Hostname"] = hostname

        if ports:
            config["ExposedPorts"] = {f"{k}/tcp": {} for k in ports}
            config["HostConfig"]["PortBindings"] = {
                f"{k}/tcp": [{"HostPort": str(v)}] for k, v in ports.items()
            }

        if volumes:
            binds = []
            for host, container in volumes.items():
                if isinstance(container, dict):
                    # New format: {host: {"bind": path, "mode": "rw"}}
                    bind_str = f"{host}:{container['bind']}"
                    if "mode" in container:
                        bind_str += f":{container['mode']}"
                    binds.append(bind_str)
                else:
                    # Old format: {host: container_path}
                    binds.append(f"{host}:{container}")
            config["HostConfig"]["Binds"] = binds

        # --- lxcfs for cgroup-aware /proc (free, top, htop) ---
        await self._check_lxcfs_support()
        lxcfs_mounts = self._get_lxcfs_mounts()
        if lxcfs_mounts:
            if "Binds" not in config["HostConfig"]:
                config["HostConfig"]["Binds"] = []
            config["HostConfig"]["Binds"].extend(lxcfs_mounts)
            logger.info(f"Mounted lxcfs /proc files: {len(lxcfs_mounts)} files")

        # --- CPU limits with graceful fallback ---
        if cpu_limit:
            controllers = await self._get_available_controllers()
            has_cpu = "cpu" in controllers
            has_cpuset = "cpuset" in controllers

            if has_cpu:
                config["HostConfig"]["NanoCpus"] = int(cpu_limit * 1e9)
                logger.info(f"Applied CPU limit: {cpu_limit} cores (NanoCpus)")
            else:
                logger.warning(
                    f"CPU limit requested ({cpu_limit} cores) but 'cpu' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"CPU throttling will not be enforced. "
                    f"To enable on systemd systems: "
                    f"sudo mkdir -p /etc/systemd/system/user@.service.d/ && "
                    f"echo '[Service]\\nDelegate=cpu cpuset io memory pids' | sudo tee "
                    f"/etc/systemd/system/user@.service.d/delegate.conf && "
                    f"sudo systemctl daemon-reload"
                )

            if has_cpuset:
                # Cap affinity to available host cores to avoid failure
                # when plan requests more cores than the host has
                available_cores = os.cpu_count() or int(cpu_limit)
                pinned_cores = min(int(cpu_limit), available_cores)
                cpus = ",".join(str(i) for i in range(pinned_cores))
                config["HostConfig"]["CpusetCpus"] = cpus
                logger.info(
                    f"Applied CPU affinity: cores {cpus} (requested {cpu_limit}, host has {available_cores})"
                )
            else:
                logger.warning(
                    f"CPU affinity requested but 'cpuset' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"CPU pinning will not be enforced."
                )

        # --- Memory limits ---
        if memory_limit:
            controllers = await self._get_available_controllers()
            if "memory" in controllers:
                memory_bytes = self._parse_memory(memory_limit)
                config["HostConfig"]["Memory"] = memory_bytes
                config["HostConfig"]["MemorySwap"] = memory_bytes
                logger.info(f"Applied memory limit: {memory_limit} ({memory_bytes} bytes)")
            else:
                logger.warning(
                    f"Memory limit requested ({memory_limit}) but 'memory' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"Memory limits will not be enforced."
                )

        # --- Disk limits with graceful fallback ---
        if disk_limit:
            supports = await self._check_storage_support()
            if supports:
                try:
                    disk_bytes = self._parse_memory(disk_limit)
                    config["HostConfig"]["StorageOpt"] = {"size": f"{disk_bytes}b"}
                    logger.info(f"Applied disk limit: {disk_limit} ({disk_bytes} bytes)")
                except Exception as e:
                    logger.warning(f"Failed to parse/apply disk limit: {e}")
            else:
                logger.warning(
                    f"Disk limit requested ({disk_limit}) but storage quotas are not supported "
                    f"by the current storage driver or configuration. "
                    f"Expected in production with XFS(pquota), ZFS, or Btrfs. "
                    f"Disk limits will not be enforced."
                )

        # --- CPU mask library volume (read-only) ---
        await self._ensure_cpu_lib_volume()
        if self._cpu_lib_volume_ready:
            config["HostConfig"].setdefault("Mounts", [])
            config["HostConfig"]["Mounts"].append(
                {
                    "Type": "volume",
                    "Source": self.VOLUME_CPU_LIB,
                    "Target": self.CPU_LIB_TARGET,
                    "ReadOnly": True,
                }
            )

        # --- Container runtime hardening ---
        if settings.container_hardening_enabled:
            host_config = config["HostConfig"]
            # Set both HostConfig.User (for internal verification/tests) and
            # top-level Config.User (the Docker/Podman API field that actually
            # controls the container process user).
            host_config["User"] = f"{settings.container_uid}:{settings.container_gid}"
            config["User"] = f"{settings.container_uid}:{settings.container_gid}"
            if settings.container_drop_all_capabilities:
                host_config["CapDrop"] = ["ALL"]
            if settings.container_no_new_privileges:
                host_config["SecurityOpt"] = ["no-new-privileges:true"]
            if settings.container_readonly_rootfs:
                host_config["ReadonlyRootfs"] = True
                tmpfs_paths = settings.container_readonly_tmpfs_paths or []
                if tmpfs_paths:
                    host_config["Tmpfs"] = dict.fromkeys(tmpfs_paths, "mode=1777,size=100m")
            logger.info(
                "Applied container hardening: user=%s, cap_drop=%s, "
                "no_new_privileges=%s, readonly_rootfs=%s",
                host_config.get("User"),
                settings.container_drop_all_capabilities,
                settings.container_no_new_privileges,
                settings.container_readonly_rootfs,
            )

        container = await self.client.containers.create(config, name=name)
        await self._inject_cpu_files(container, cpu_limit)
        return container

    async def start_container(self, container_id: str):
        """Start a container"""
        container = await self.client.containers.get(container_id)
        await container.start()

    async def wait_for_container_ready(
        self,
        container_name: str,
        health_url: str,
        timeout: int | None = None,
        interval: float | None = None,
    ) -> bool:
        """Wait until the container responds successfully on health_url.

        The probe is issued from the backend container over the shared container
        network (e.g. http://<container_name>:8080/health), so it verifies both
        that the server process is up and that it is reachable on the internal
        network before Traefik has picked up the route.
        """
        timeout = timeout if timeout is not None else settings.container_readiness_timeout
        interval = interval if interval is not None else settings.container_readiness_interval
        deadline = asyncio.get_event_loop().time() + timeout

        logger.info(
            "Waiting up to %ss for container %s to become ready at %s",
            timeout,
            container_name,
            health_url,
        )

        while asyncio.get_event_loop().time() < deadline:
            try:
                timeout_obj = aiohttp.ClientTimeout(total=2)
                async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                    async with session.get(health_url) as resp:
                        if resp.status == 200:
                            logger.info("Container %s is ready", container_name)
                            return True
            except Exception as e:
                logger.debug("Container %s not ready yet: %s", container_name, e)
            await asyncio.sleep(interval)

        logger.warning("Container %s did not become ready within %ss", container_name, timeout)
        return False

    async def stop_container(self, container_id: str, timeout: int = 30):
        """Stop a container"""
        try:
            container = await self.client.containers.get(container_id)
            await container.stop(timeout=timeout)
        except Exception:
            pass

    async def delete_container(self, container_id: str, force: bool = True):
        """Delete a container"""
        try:
            container = await self.client.containers.get(container_id)
            await container.delete(force=force)
        except Exception:
            pass

    async def get_container_info(self, container_id: str):
        """Get container info"""
        container = await self.client.containers.get(container_id)
        return await container.show()

    async def version(self):
        """Get container runtime version info"""
        return await self.client.version()

    async def list_containers(self, filters: dict | None = None):
        """List containers"""
        return await self.client.containers.list(filters=filters)

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: int | None = None,
        timestamps: bool = True,
        stdout: bool = True,
        stderr: bool = True,
    ) -> str:
        """Get container logs"""
        container = await self.client.containers.get(container_id)
        kwargs = {
            "stdout": stdout,
            "stderr": stderr,
            "tail": tail,
            "timestamps": timestamps,
            "follow": False,
        }
        if since is not None:
            kwargs["since"] = since
        logs = await container.log(**kwargs)
        # aiodocker returns list of lines; join into single string
        if isinstance(logs, list):
            return "".join(logs)
        return logs

    async def stream_container_logs(
        self, container_id: str, tail: int = 100, stdout: bool = True, stderr: bool = True
    ):
        """Stream container logs as async generator"""
        container = await self.client.containers.get(container_id)
        logs = await container.log(
            stdout=stdout, stderr=stderr, tail=tail, follow=True, timestamps=True
        )
        return logs

    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes"""
        memory_str = memory_str.lower()
        multipliers = {
            "b": 1,
            "k": 1024,
            "m": 1024**2,
            "g": 1024**3,
        }

        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)

        return int(memory_str)


# Singleton instance
container_client = ContainerClient()


async def get_container_client():
    """Get initialized Docker client"""
    if not container_client.client:
        await container_client.connect()
    return container_client


async def get_fresh_container_client():
    """Get a fresh Docker client instance (for Celery workers)."""
    client = ContainerClient()
    await client.connect()
    return client
