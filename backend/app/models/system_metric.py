import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Float, Integer, BigInteger, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class SystemMetric(Base):
    __tablename__ = "system_metrics"
    __table_args__ = (Index("ix_system_metrics_collected_at", "collected_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host = Column(String(255), nullable=False, default="localhost")

    # CPU
    cpu_percent = Column(Float)
    cpu_count = Column(Integer)
    cpu_load_1m = Column(Float)
    cpu_load_5m = Column(Float)
    cpu_load_15m = Column(Float)

    # Memory
    memory_used = Column(BigInteger)
    memory_total = Column(BigInteger)
    memory_percent = Column(Float)
    memory_available = Column(BigInteger)

    # Disk
    disk_used = Column(BigInteger)
    disk_total = Column(BigInteger)
    disk_percent = Column(Float)
    disk_read_bytes = Column(BigInteger)
    disk_write_bytes = Column(BigInteger)

    # Network
    network_rx_bytes = Column(BigInteger)
    network_tx_bytes = Column(BigInteger)

    # Docker
    docker_containers_running = Column(Integer)
    docker_containers_total = Column(Integer)
    docker_images_total = Column(Integer)

    collected_at = Column(DateTime, nullable=False, default=utc_now)

    def to_dict(self):
        return {
            "id": str(self.id),
            "host": self.host,
            "cpu": {
                "percent": self.cpu_percent,
                "count": self.cpu_count,
                "load_1m": self.cpu_load_1m,
                "load_5m": self.cpu_load_5m,
                "load_15m": self.cpu_load_15m,
            },
            "memory": {
                "used": self.memory_used,
                "total": self.memory_total,
                "percent": self.memory_percent,
                "available": self.memory_available,
            },
            "disk": {
                "used": self.disk_used,
                "total": self.disk_total,
                "percent": self.disk_percent,
                "read_bytes": self.disk_read_bytes,
                "write_bytes": self.disk_write_bytes,
            },
            "network": {
                "rx_bytes": self.network_rx_bytes,
                "tx_bytes": self.network_tx_bytes,
            },
            "docker": {
                "containers_running": self.docker_containers_running,
                "containers_total": self.docker_containers_total,
                "images_total": self.docker_images_total,
            },
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }
