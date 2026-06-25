import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Float, Integer, BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class ServerMetric(Base):
    __tablename__ = "server_metrics"
    __table_args__ = (
        Index("ix_server_metrics_collected_at", "collected_at"),
        Index("ix_server_metrics_server_id_collected_at", "server_id", "collected_at"),
        {"postgresql_partition_by": "RANGE (collected_at)"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    container_id = Column(String(255), nullable=False)

    # CPU
    cpu_percent = Column(Float)
    cpu_usage_ns = Column(BigInteger)
    cpu_system_ns = Column(BigInteger)
    cpu_cores = Column(Integer)

    # Memory
    memory_used = Column(BigInteger)
    memory_total = Column(BigInteger)
    memory_percent = Column(Float)
    memory_cache = Column(BigInteger)
    memory_swap_used = Column(BigInteger)

    # Disk
    disk_read_bytes = Column(BigInteger)
    disk_write_bytes = Column(BigInteger)
    disk_read_iops = Column(Integer)
    disk_write_iops = Column(Integer)

    # Network
    network_rx_bytes = Column(BigInteger)
    network_tx_bytes = Column(BigInteger)
    network_rx_packets = Column(BigInteger)
    network_tx_packets = Column(BigInteger)
    network_rx_errors = Column(Integer)
    network_tx_errors = Column(Integer)

    # GPU
    gpu_percent = Column(Float)
    gpu_memory_used = Column(BigInteger)
    gpu_memory_total = Column(BigInteger)
    gpu_temperature = Column(Float)

    # Process
    pids = Column(Integer)

    # Timestamp (partition key — must be part of PK)
    collected_at = Column(DateTime, nullable=False, default=utc_now, primary_key=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "server_id": str(self.server_id),
            "container_id": self.container_id,
            "cpu": {
                "percent": self.cpu_percent,
                "cores": self.cpu_cores,
            },
            "memory": {
                "used": self.memory_used,
                "total": self.memory_total,
                "percent": self.memory_percent,
            },
            "disk": {
                "read_bytes": self.disk_read_bytes,
                "write_bytes": self.disk_write_bytes,
            },
            "network": {
                "rx_bytes": self.network_rx_bytes,
                "tx_bytes": self.network_tx_bytes,
            },
            "gpu": {
                "percent": self.gpu_percent,
                "memory_used": self.gpu_memory_used,
                "temperature": self.gpu_temperature,
            }
            if self.gpu_percent
            else None,
            "pids": self.pids,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }
