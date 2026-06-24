import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.db_enums import pg_enum

if TYPE_CHECKING:
    from app.models.batch import Batch
    from app.models.reading import Reading


class FormType(str, PyEnum):
    DAILY_PRODUCTION = "daily_production"
    FILLER_LINE_CHECK = "filler_line_check"
    BOTTLE_SEALING = "bottle_sealing"
    LABEL_USAGE = "label_usage"
    FINISHED_PRODUCT_LINE_CHECK = "finished_product_line_check"
    PICK_LIST = "pick_list"
    CARTON_QC = "carton_qc"
    FINAL_PALLET_COUNT = "final_pallet_count"
    FINISHED_PRODUCT_PALLET = "finished_product_pallet"


class AccrualMode(str, PyEnum):
    ATOMIC = "atomic"
    LOG = "log"
    MATRIX = "matrix"


class FormStatus(str, PyEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EDITED_SINCE_SUBMIT = "edited_since_submit"


class FormInstance(Base):
    __tablename__ = "form_instances"
    __table_args__ = (
        UniqueConstraint("batch_id", "form_type", name="uq_batch_form_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    form_type: Mapped[FormType] = mapped_column(pg_enum(FormType, "formtype"), nullable=False)
    accrual_mode: Mapped[AccrualMode] = mapped_column(pg_enum(AccrualMode, "accrualmode"), nullable=False)
    status: Mapped[FormStatus] = mapped_column(
        pg_enum(FormStatus, "formstatus"),
        default=FormStatus.NOT_STARTED,
        nullable=False,
    )
    header_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_edited_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch", back_populates="form_instances")
    readings: Mapped[list["Reading"]] = relationship(
        "Reading", back_populates="form_instance", cascade="all, delete-orphan"
    )
