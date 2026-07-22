import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PalletTagPrint(Base):
    __tablename__ = "pallet_tag_prints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    pallets_calculated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags_printed: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    printed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    dispatch_method: Mapped[str] = mapped_column(String(20), nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch = relationship("Batch", back_populates="pallet_tag_prints")