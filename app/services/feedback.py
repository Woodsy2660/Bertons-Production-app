"""In-app feedback / bug reporting service."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.feedback_report import (
    FeedbackReport,
    FeedbackReportType,
    FeedbackStatus,
)

SYDNEY = ZoneInfo("Australia/Sydney")

MAX_DESCRIPTION = 4000
MAX_SOURCE_PATH = 500
MAX_PAGE_CONTEXT = 300
MAX_USER_AGENT = 1000

_REPORT_TYPE_ALIASES = {
    "bug": FeedbackReportType.BUG,
    "data_change": FeedbackReportType.DATA_CHANGE,
    "data-change": FeedbackReportType.DATA_CHANGE,
    "data field change": FeedbackReportType.DATA_CHANGE,
    "suggestion": FeedbackReportType.SUGGESTION,
}


class FeedbackValidationError(ValueError):
    """Raised when feedback form input fails validation."""


def parse_report_type(raw: str | None) -> FeedbackReportType:
    if not raw or not str(raw).strip():
        raise FeedbackValidationError("Report type is required")
    key = str(raw).strip().lower().replace(" ", "_")
    # Accept enum names too (BUG, DATA_CHANGE)
    key_name = str(raw).strip().upper()
    for member in FeedbackReportType:
        if member.name == key_name or member.value == key:
            return member
    mapped = _REPORT_TYPE_ALIASES.get(key)
    if mapped is None:
        raise FeedbackValidationError("Invalid report type")
    return mapped


def normalize_description(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        raise FeedbackValidationError("Description is required")
    if len(text) > MAX_DESCRIPTION:
        return text[:MAX_DESCRIPTION]
    return text


def normalize_source_path(raw: str | None) -> str:
    path = (raw or "").strip() or "/"
    if len(path) > MAX_SOURCE_PATH:
        return path[:MAX_SOURCE_PATH]
    return path


def normalize_page_context(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) > MAX_PAGE_CONTEXT:
        return text[:MAX_PAGE_CONTEXT]
    return text


def parse_optional_batch_id(raw: str | None) -> uuid.UUID | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def summarize_user_agent(ua: str | None) -> str:
    """Short device/browser label for the manager review list."""
    if not ua or not str(ua).strip():
        return "Unknown"
    s = str(ua)
    lower = s.lower()

    is_ipad = "ipad" in lower or ("macintosh" in lower and "mobile" in lower)
    is_iphone = "iphone" in lower
    is_android = "android" in lower
    is_tablet = is_ipad or ("android" in lower and "mobile" not in lower)

    if "edg/" in lower or "edgios" in lower:
        browser = "Edge"
    elif "chrome" in lower and "edg" not in lower and "opr/" not in lower:
        browser = "Chrome"
    elif "safari" in lower and "chrome" not in lower and "chromium" not in lower:
        browser = "Safari"
    elif "firefox" in lower:
        browser = "Firefox"
    else:
        browser = None

    if is_ipad:
        return f"iPad {browser}" if browser else "iPad"
    if is_iphone:
        return f"iPhone {browser}" if browser else "iPhone"
    if is_android and is_tablet:
        return f"Android tablet {browser}" if browser else "Android tablet"
    if is_android:
        return f"Android {browser}" if browser else "Android Chrome"
    if browser:
        return f"Desktop {browser}" if browser != "Safari" else "Desktop Safari"
    # Truncate raw UA for unknown clients
    return s[:80] + ("…" if len(s) > 80 else "")


def format_sydney(dt: datetime | None) -> str:
    """Format a timestamptz for display in Australia/Sydney (no zone suffix)."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        # Stored values use utcnow without tz; treat as UTC.
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(SYDNEY)
    return local.strftime("%d %b %Y %H:%M")


def safe_return_path(raw: str | None, fallback: str = "/") -> str:
    """Only allow same-origin relative paths (open-redirect safe)."""
    if not raw:
        return fallback
    path = str(raw).strip()
    if not path.startswith("/") or path.startswith("//"):
        return fallback
    # Block scheme-relative and absolute URLs
    if re.match(r"^https?:", path, re.I):
        return fallback
    if len(path) > MAX_SOURCE_PATH:
        return fallback
    return path


async def create_feedback_report(
    db: AsyncSession,
    *,
    report_type: FeedbackReportType | str,
    description: str,
    submitted_role: str,
    source_path: str | None = None,
    page_context: str | None = None,
    batch_id: uuid.UUID | str | None = None,
    user_agent: str | None = None,
) -> FeedbackReport:
    if isinstance(report_type, str):
        report_type = parse_report_type(report_type)
    desc = normalize_description(description)
    role = (submitted_role or "").strip().lower()
    if role not in ("manager", "operator"):
        raise FeedbackValidationError("Invalid role")

    bid: uuid.UUID | None
    if isinstance(batch_id, uuid.UUID):
        bid = batch_id
    else:
        bid = parse_optional_batch_id(str(batch_id) if batch_id else None)

    ua = (user_agent or "")[:MAX_USER_AGENT]

    report = FeedbackReport(
        report_type=report_type,
        description=desc,
        submitted_role=role,
        source_path=normalize_source_path(source_path),
        page_context=normalize_page_context(page_context),
        batch_id=bid,
        user_agent=ua,
        submitted_at=datetime.utcnow(),
        status=FeedbackStatus.NEW,
    )
    db.add(report)
    try:
        await db.commit()
    except IntegrityError:
        # Invalid / missing batch FK → keep the report without batch context
        await db.rollback()
        if bid is not None:
            report = FeedbackReport(
                report_type=report_type,
                description=desc,
                submitted_role=role,
                source_path=normalize_source_path(source_path),
                page_context=normalize_page_context(page_context),
                batch_id=None,
                user_agent=ua,
                submitted_at=datetime.utcnow(),
                status=FeedbackStatus.NEW,
            )
            db.add(report)
            await db.commit()
        else:
            raise
    await db.refresh(report)
    return report


async def list_feedback_reports(
    db: AsyncSession,
    *,
    report_type: FeedbackReportType | str | None = None,
    limit: int = 200,
) -> list[FeedbackReport]:
    stmt = (
        select(FeedbackReport)
        .options(selectinload(FeedbackReport.batch))
        .order_by(FeedbackReport.submitted_at.desc())
        .limit(limit)
    )
    if report_type is not None:
        if isinstance(report_type, str):
            report_type = parse_report_type(report_type)
        stmt = stmt.where(FeedbackReport.report_type == report_type)

    result = await db.execute(stmt)
    return list(result.scalars().all())
