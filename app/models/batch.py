import uuid
from datetime import datetime, date
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Date, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.db_enums import pg_enum

if TYPE_CHECKING:
    from app.models.form_instance import FormInstance
    from app.models.uploaded_document import UploadedDocument
    from app.models.compilation import Compilation


class BatchStatus(str, PyEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    COMPILED = "compiled"
    REOPENED = "reopened"


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        pg_enum(BatchStatus, "batchstatus"),
        default=BatchStatus.DRAFT,
        nullable=False,
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    header: Mapped["BatchHeader"] = relationship(
        "BatchHeader", back_populates="batch", uselist=False, cascade="all, delete-orphan"
    )
    form_instances: Mapped[list["FormInstance"]] = relationship(
        "FormInstance", back_populates="batch", cascade="all, delete-orphan"
    )
    uploaded_documents: Mapped[list["UploadedDocument"]] = relationship(
        "UploadedDocument", back_populates="batch", cascade="all, delete-orphan"
    )
    compilations: Mapped[list["Compilation"]] = relationship(
        "Compilation", back_populates="batch", cascade="all, delete-orphan"
    )


class BatchHeader(Base):
    __tablename__ = "batch_headers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stock_item: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tank: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    packing_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    packaging_line: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pick_list_lines: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch", back_populates="header")
