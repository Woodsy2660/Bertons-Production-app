"""Central run state machine: locks, visibility, and transitions."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.session import Role
from app.config import Settings
from app.forms import FormType
from app.models import Batch, BatchHeader, BatchStatus, Compilation, FormStatus

APP_FORM_TYPES = {ft.value for ft in FormType}


class BatchLifecycleError(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


def is_complete(batch: Batch) -> bool:
    return batch.status == BatchStatus.COMPLETE


def is_reopened(batch: Batch) -> bool:
    return batch.status == BatchStatus.REOPENED


def is_awaiting_review(batch: Batch) -> bool:
    return batch.status == BatchStatus.AWAITING_REVIEW


def is_greyed_out(batch: Batch) -> bool:
    """Complete runs appear read-only/greyed in run lists."""
    return is_complete(batch)


def operator_may_edit(batch: Batch) -> bool:
    """Operators may edit any run that is not complete or reopened."""
    return batch.status not in (BatchStatus.COMPLETE, BatchStatus.REOPENED)


def manager_may_edit(batch: Batch) -> bool:
    """Managers may edit any run except complete (until reopened)."""
    return not is_complete(batch) or is_reopened(batch)


def can_write_forms(batch: Batch, role: Role) -> bool:
    if is_complete(batch):
        return False
    if is_reopened(batch):
        return role == "manager"
    return True


def can_write_batch_header(batch: Batch, role: Role) -> bool:
    return role == "manager" and manager_may_edit(batch)


def can_upload_documents(batch: Batch, role: Role) -> bool:
    return role == "manager" and manager_may_edit(batch)


def can_compile(batch: Batch, role: Role) -> bool:
    """Managers may compile any active run, including partially completed forms."""
    if role != "manager":
        return False
    return batch.status in (
        BatchStatus.IN_PROGRESS,
        BatchStatus.AWAITING_REVIEW,
        BatchStatus.REOPENED,
    )


def can_mark_ready(batch: Batch, role: Role) -> bool:
    return role == "manager" and is_awaiting_review(batch)


def can_reopen(batch: Batch, role: Role) -> bool:
    return role == "manager" and is_complete(batch)


def assert_can_view(batch: Batch, role: Role) -> None:
    """Visibility is enforced at list query time; single-batch 404 if hidden."""
    pass


def assert_can_write_forms(batch: Batch, role: Role) -> None:
    if not can_write_forms(batch, role):
        if is_complete(batch):
            raise BatchLifecycleError(403, "Run is complete and locked")
        if is_reopened(batch):
            raise BatchLifecycleError(403, "Run is under manager review — operators cannot edit")
        raise BatchLifecycleError(403, "Run is not editable")


def assert_can_write_header(batch: Batch, role: Role) -> None:
    if not can_write_batch_header(batch, role):
        raise BatchLifecycleError(403, "Batch header cannot be edited")


def assert_can_upload(batch: Batch, role: Role) -> None:
    if not can_upload_documents(batch, role):
        raise BatchLifecycleError(403, "Document uploads are not allowed")


def assert_can_compile(batch: Batch, role: Role) -> None:
    if not can_compile(batch, role):
        raise BatchLifecycleError(403, "Compile is not allowed for this run")


def assert_can_reopen(batch: Batch, role: Role) -> None:
    if not can_reopen(batch, role):
        raise BatchLifecycleError(403, "Reopen is not allowed")


def sync_lock_flag(batch: Batch) -> None:
    """Keep is_locked aligned with lifecycle (complete = locked)."""
    batch.is_locked = is_complete(batch)


async def all_forms_submitted(db: AsyncSession, batch_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.form_instances))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        return False

    submitted = {
        fi.form_type.value
        for fi in batch.form_instances
        if fi.status == FormStatus.SUBMITTED
    }
    return APP_FORM_TYPES.issubset(submitted)


async def maybe_transition_to_awaiting_review(
    db: AsyncSession,
    batch: Batch,
) -> bool:
    """Auto-transition when all nine forms are submitted."""
    if batch.status not in (BatchStatus.IN_PROGRESS, BatchStatus.REOPENED):
        return False
    if not await all_forms_submitted(db, batch.id):
        return False
    batch.status = BatchStatus.AWAITING_REVIEW
    sync_lock_flag(batch)
    return True


def mark_complete(batch: Batch) -> None:
    batch.status = BatchStatus.COMPLETE
    sync_lock_flag(batch)


async def reopen_run(db: AsyncSession, batch: Batch) -> None:
    """Reopen a complete run: editable by manager, PDF stale, operators locked out."""
    for comp in batch.compilations:
        if comp.is_current:
            comp.is_current = False
    batch.status = BatchStatus.REOPENED
    sync_lock_flag(batch)


def operator_visibility_filter(settings: Settings, today: date | None = None):
    """SQLAlchemy filter for operator run list scoping.

    Active (non-complete) runs are not date-scoped so the operator dashboard stays
    in sync with the manager view. Completed runs remain limited to a recent window.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=settings.operator_completed_run_days)
    cutoff_dt = datetime.combine(cutoff, datetime.min.time())

    return or_(
        Batch.status != BatchStatus.COMPLETE,
        and_(
            Batch.status == BatchStatus.COMPLETE,
            or_(
                BatchHeader.run_date >= cutoff,
                Batch.updated_at >= cutoff_dt,
            ),
        ),
    )


async def list_batches_for_role(
    db: AsyncSession,
    role: Role,
    settings: Settings,
) -> tuple[list[Batch], list[Batch]]:
    """
    Return (all_batches, review_queue) for dashboard.

    Managers see all runs; review_queue is awaiting_review only.
    Operators see all active runs plus recent complete runs.
    """
    base = (
        select(Batch)
        .options(selectinload(Batch.header))
        .order_by(Batch.created_at.desc())
    )

    if role == "manager":
        result = await db.execute(base.limit(500))
        batches = list(result.scalars().all())
        review_queue = [b for b in batches if is_awaiting_review(b)]
        return batches, review_queue

    stmt = (
        base.join(BatchHeader, BatchHeader.batch_id == Batch.id, isouter=True)
        .where(operator_visibility_filter(settings))
        .limit(settings.operator_completed_run_limit + 50)
    )
    result = await db.execute(stmt)
    batches = list(result.scalars().unique().all())

    complete = [b for b in batches if is_complete(b)]
    if len(complete) > settings.operator_completed_run_limit:
        complete_ids = {b.id for b in complete[settings.operator_completed_run_limit:]}
        batches = [b for b in batches if b.id not in complete_ids]

    # Operators also get a dedicated awaiting-review list (read-only queue).
    review_queue = [b for b in batches if is_awaiting_review(b)]
    return batches, review_queue

async def search_completed_runs(
    db: AsyncSession,
    *,
    q: str | None = None,
    product: str | None = None,
    stock_item: str | None = None,
    run_date_from: date | None = None,
    run_date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Batch], int]:
    """Search COMPLETE runs for managers (history archive).

    Free-text ``q`` matches run number, product, stock item, or tank (ILIKE).
    Returns (page of batches with header loaded, total matching count).
    """
    filters = [Batch.status == BatchStatus.COMPLETE]

    text = (q or "").strip()
    if text:
        pattern = f"%{text}%"
        filters.append(
            or_(
                Batch.run_number.ilike(pattern),
                BatchHeader.product.ilike(pattern),
                BatchHeader.stock_item.ilike(pattern),
                BatchHeader.tank.ilike(pattern),
            )
        )

    product_f = (product or "").strip()
    if product_f:
        filters.append(BatchHeader.product.ilike(f"%{product_f}%"))

    stock_f = (stock_item or "").strip()
    if stock_f:
        filters.append(BatchHeader.stock_item.ilike(f"%{stock_f}%"))

    if run_date_from is not None:
        filters.append(BatchHeader.run_date >= run_date_from)
    if run_date_to is not None:
        filters.append(BatchHeader.run_date <= run_date_to)

    where_clause = and_(*filters)

    count_stmt = (
        select(func.count(Batch.id))
        .select_from(Batch)
        .join(BatchHeader, BatchHeader.batch_id == Batch.id, isouter=True)
        .where(where_clause)
    )
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        select(Batch)
        .options(selectinload(Batch.header), selectinload(Batch.compilations))
        .join(BatchHeader, BatchHeader.batch_id == Batch.id, isouter=True)
        .where(where_clause)
        .order_by(
            BatchHeader.run_date.desc().nullslast(),
            Batch.updated_at.desc(),
        )
        .offset(max(offset, 0))
        .limit(max(1, min(limit, 200)))
    )
    rows = list((await db.execute(stmt)).scalars().unique().all())
    return rows, total
