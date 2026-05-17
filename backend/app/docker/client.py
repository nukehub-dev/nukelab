import os
import uuid
from typing import Optional, Set
import aiodocker
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class DockerClient:
    def __init__(self):
        self.client: Optional[aiodocker.Docker] = None
        self._available_cgroup_controllers: Optional[Set[str]] = None
        self._storage_support: Optional[bool] = None
        self._lxcfs_support: Optional[bool] = None

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

    async def _get_available_controllers(self) -> Set[str]:
        """Detect available cgroup v2 controllers from the host"""
        if self._available_cgroup_controllers is not None:
            return self._available_cgroup_controllers

        controllers = set()
        try:
            # Root cgroup controllers
            cgroup_path = "/sys/fs/cgroup/cgroup.controllers"
            if os.path.exists(cgroup_path):
                with open(cgroup_path, 'r') as f:
                    controllers.update(f.read().strip().split())

            # Current user's subtree controllers
            subtree_path = "/sys/fs/cgroup/cgroup.subtree_control"
            if os.path.exists(subtree_path):
                with open(subtree_path, 'r') as f:
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
        proc_files = [
            "meminfo", "cpuinfo", "diskstats", "loadavg",
            "stat", "swaps", "uptime"
        ]
        
        for proc_file in proc_files:
            host_path = f"{lxcfs_base}/proc/{proc_file}"
            if os.path.exists(host_path):
                mounts.append(f"{host_path}:/proc/{proc_file}:rw")
        
        return mounts

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

            test_container = await self.client.containers.create({
                "Image": "busybox:latest",
                "HostConfig": {
                    "StorageOpt": {"size": "10m"}
                }
            }, name=f"test-storage-{uuid.uuid4().hex[:8]}")
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
        command: Optional[str] = None,
        ports: Optional[dict] = None,
        volumes: Optional[dict] = None,
        env: Optional[dict] = None,
        labels: Optional[dict] = None,
        network: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        memory_limit: Optional[str] = None,
        disk_limit: Optional[str] = None,
    ):
        """Create a new container with graceful cgroup fallback"""
        config = {
            "Image": image,
            "Cmd": command.split() if command else None,
            "Labels": labels or {},
            "Env": [f"{k}={v}" for k, v in (env or {}).items()],
            "HostConfig": {
                "NetworkMode": network or settings.docker_network,
                "PublishAllPorts": False,
            }
        }

        if ports:
            config["ExposedPorts"] = {f"{k}/tcp": {} for k in ports.keys()}
            config["HostConfig"]["PortBindings"] = {
                f"{k}/tcp": [{"HostPort": str(v)}] for k, v in ports.items()
            }

        if volumes:
            binds = []
            for host, container in volumes.items():
                if isinstance(container, dict):
                    # New format: {host: {"bind": path, "mode": "rw"}}
                    bind_str = f"{host}:{container['bind']}"
                    if 'mode' in container:
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
                cpus = ",".join(str(i) for i in range(int(cpu_limit)))
                config["HostConfig"]["CpusetCpus"] = cpus
                logger.info(f"Applied CPU affinity: cores {cpus}")
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

        container = await self.client.containers.create(config, name=name)
        return container

    async def start_container(self, container_id: str):
        """Start a container"""
        container = await self.client.containers.get(container_id)
        await container.start()

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

    async def list_containers(self, filters: Optional[dict] = None):
        """List containers"""
        return await self.client.containers.list(filters=filters)

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: Optional[int] = None,
        timestamps: bool = True,
        stdout: bool = True,
        stderr: bool = True
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
            return ''.join(logs)
        return logs

    async def stream_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        stdout: bool = True,
        stderr: bool = True
    ):
        """Stream container logs as async generator"""
        container = await self.client.containers.get(container_id)
        logs = await container.log(
            stdout=stdout,
            stderr=stderr,
            tail=tail,
            follow=True,
            timestamps=True
        )
        return logs

    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes"""
        memory_str = memory_str.lower()
        multipliers = {
            'b': 1,
            'k': 1024,
            'm': 1024**2,
            'g': 1024**3,
        }

        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)

        return int(memory_str)

# Singleton instance
docker_client = DockerClient()

async def get_docker_client():
    """Get initialized Docker client"""
    if not docker_client.client:
        await docker_client.connect()
    return docker_client


async def get_fresh_docker_client():
    """Get a fresh Docker client instance (for Celery workers)."""
    client = DockerClient()
    await client.connect()
    return client
