from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import Role, require_manager, require_operator_or_manager
from app.database import get_db
from app.models import Batch, BatchHeader
from app.schemas import BatchCreate, BatchResponse, BatchListResponse

router = APIRouter()


@router.post("/", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(
    batch_data: BatchCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
) -> Batch:
    """Create a new batch with optional header data."""
    # Check if run_number already exists
    existing = await db.execute(
        select(Batch).where(Batch.run_number == batch_data.run_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch with run number '{batch_data.run_number}' already exists",
        )

    # Create the batch
    batch = Batch(
        run_number=batch_data.run_number,
        created_by=batch_data.created_by,
    )
    db.add(batch)

    # Create header if provided
    if batch_data.header:
        header = BatchHeader(
            batch=batch,
            product=batch_data.header.product,
            stock_item=batch_data.header.stock_item,
            tank=batch_data.header.tank,
            run_date=batch_data.header.run_date,
            packing_unit=batch_data.header.packing_unit,
            packaging_line=batch_data.header.packaging_line,
            run_quantity=batch_data.header.run_quantity,
            pick_list_lines=batch_data.header.pick_list_lines,
            extra=batch_data.header.extra,
        )
        db.add(header)

    await db.commit()
    await db.refresh(batch)

    # Load header relationship
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.id == batch.id)
    )
    return result.scalar_one()


@router.get("/", response_model=BatchListResponse)
async def list_batches(
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
    skip: int = 0,
    limit: int = 100,
) -> dict:
    """List all batches with pagination."""
    # Get total count
    count_result = await db.execute(select(func.count(Batch.id)))
    total = count_result.scalar_one()

    # Get batches
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .order_by(Batch.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    batches = result.scalars().all()

    return {"batches": batches, "total": total}


@router.get("/{batch_id}", response_model=BatchResponse)
async def get_batch(
    batch_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
) -> Batch:
    """Get a single batch by ID."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with id '{batch_id}' not found",
        )

    return batch


@router.get("/by-run/{run_number}", response_model=BatchResponse)
async def get_batch_by_run_number(
    run_number: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
) -> Batch:
    """Get a single batch by run number."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.run_number == run_number)
    )
    batch = result.scalar_one_or_none()

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with run number '{run_number}' not found",
        )

    return batch
