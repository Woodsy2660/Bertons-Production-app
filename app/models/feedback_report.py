import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.db_enums import pg_enum

if TYPE_CHECKING:
    from app.models.batch import Batch


class FeedbackReportType(str, PyEnum):
    BUG = "bug"
    DATA_CHANGE = "data_change"
    SUGGESTION = "suggestion"


class FeedbackStatus(str, PyEnum):
    NEW = "new"
    # Reserved for a future review workflow (not used in UI yet).
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_type: Mapped[FeedbackReportType] = mapped_column(
        pg_enum(FeedbackReportType, "feedbackreporttype"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_role: Mapped[str] = mapped_column(String(20), nullable=False)
    source_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    page_context: Mapped[str | None] = mapped_column(String(300), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    status: Mapped[FeedbackStatus] = mapped_column(
        pg_enum(FeedbackStatus, "feedbackstatus"),
        default=FeedbackStatus.NEW,
        nullable=False,
    )

    batch: Mapped["Batch | None"] = relationship("Batch", lazy="selectin")
