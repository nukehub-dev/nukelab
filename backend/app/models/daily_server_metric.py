import uuid
from app.core.time_utils import utc_now
from datetime import date
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    BigInteger,
    DateTime,
    Date,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class DailyServerMetric(Base):
    __tablename__ = "daily_server_metrics"
    __table_args__ = (
        UniqueConstraint("server_id", "date", name="uq_daily_server_metrics_server_id_date"),
        Index("ix_daily_server_metrics_server_id_date", "server_id", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    date = Column(Date, nullable=False)

    avg_cpu = Column(Float)
    peak_cpu = Column(Float)
    avg_memory = Column(Float)
    peak_memory = Column(Float)
    avg_network_rx = Column(BigInteger)
    avg_network_tx = Column(BigInteger)
    avg_disk_read = Column(BigInteger)
    avg_disk_write = Column(BigInteger)
    avg_gpu = Column(Float)
    peak_gpu = Column(Float)
    data_points = Column(Integer, default=0)

    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": str(self.id),
            "server_id": str(self.server_id),
            "date": self.date.isoformat() if self.date else None,
            "avg_cpu": float(self.avg_cpu or 0),
            "peak_cpu": float(self.peak_cpu or 0),
            "avg_memory": float(self.avg_memory or 0),
            "peak_memory": float(self.peak_memory or 0),
            "avg_network_rx": int(self.avg_network_rx or 0),
            "avg_network_tx": int(self.avg_network_tx or 0),
            "avg_disk_read": int(self.avg_disk_read or 0),
            "avg_disk_write": int(self.avg_disk_write or 0),
            "avg_gpu": float(self.avg_gpu or 0) if self.avg_gpu else 0,
            "peak_gpu": float(self.peak_gpu or 0) if self.peak_gpu else 0,
            "data_points": self.data_points or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
