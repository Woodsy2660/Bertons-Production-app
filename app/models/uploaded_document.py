import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.db_enums import pg_enum

if TYPE_CHECKING:
    from app.models.batch import Batch


class DocumentSlot(str, PyEnum):
    EZYWINE_LISTING = "ezywine_listing"
    WORK_ORDER = "work_order"
    LABEL_REFERENCE = "label_reference"


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[DocumentSlot] = mapped_column(pg_enum(DocumentSlot, "documentslot"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch", back_populates="uploaded_documents")
