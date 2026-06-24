import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.batch import Batch


class Compilation(Base):
    __tablename__ = "compilations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    output_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    slot_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    compiled_by: Mapped[str] = mapped_column(String(100), nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch", back_populates="compilations")
