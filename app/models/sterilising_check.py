"""Standalone sterilising checks — FOR CA 005 (cask) and FOR PK 026 (bottling)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.batch import LineType
from app.models.db_enums import pg_enum

if TYPE_CHECKING:
    from app.models.batch import Batch


class SterilisingCheck(Base):
    """Completed independently of a run; may attach to many same-line-type runs."""

    __tablename__ = "sterilising_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Which paper form / production line this record belongs to
    line_type: Mapped[LineType] = mapped_column(
        pg_enum(LineType, "linetype"),
        default=LineType.CASK,
        nullable=False,
        index=True,
    )
    # FOR PK 026 only — System 1 / System 2
    system_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    operator_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    check_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    filters_integrity_tested: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # Structured filter reading rows (label, pressure_mbar, pass_yn)
    filter_readings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    lenticular_temp_c: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lenticular_duration_mins: Mapped[str | None] = mapped_column(String(20), nullable=True)
    line_temp_c: Mapped[str | None] = mapped_column(String(20), nullable=True)
    line_duration_mins: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # FOR CA 005 only — daily pre-start
    filler_clean: Mapped[str | None] = mapped_column(String(1), nullable=True)
    carton_erector_clean: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # FOR CA 005 QC initials; bottling uses operator_name as sign-off
    qc_sign_off: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    attachments: Mapped[list["RunSterilisingCheck"]] = relationship(
        "RunSterilisingCheck",
        back_populates="sterilising_check",
        cascade="all, delete-orphan",
    )

    @property
    def doc_number(self) -> str:
        if self.line_type == LineType.BOTTLING:
            return "FOR PK 026"
        return "FOR CA 005"

    @property
    def form_title(self) -> str:
        if self.line_type == LineType.BOTTLING:
            return "Weekly Sterilising Check"
        return "Cask Line Sterilising & Pre-Start Check"


class RunSterilisingCheck(Base):
    """Join: one sterilising record may attach to many runs (same line type)."""

    __tablename__ = "run_sterilising_checks"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "sterilising_check_id",
            name="uq_run_sterilising_check_batch_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sterilising_check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sterilising_checks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attached_by_role: Mapped[str] = mapped_column(String(20), nullable=False)
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    batch: Mapped["Batch"] = relationship("Batch", back_populates="sterilising_attachments")
    sterilising_check: Mapped[SterilisingCheck] = relationship(
        "SterilisingCheck", back_populates="attachments"
    )
