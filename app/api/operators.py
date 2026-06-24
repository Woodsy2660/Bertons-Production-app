from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Operator
from app.schemas import OperatorCreate, OperatorResponse

router = APIRouter()


@router.post("/", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def create_operator(
    operator_data: OperatorCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Operator:
    """Create a new operator."""
    operator = Operator(
        name=operator_data.name,
        initials=operator_data.initials,
    )
    db.add(operator)
    await db.commit()
    await db.refresh(operator)
    return operator


@router.get("/", response_model=list[OperatorResponse])
async def list_operators(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Operator]:
    """List all operators."""
    result = await db.execute(
        select(Operator).order_by(Operator.name)
    )
    return list(result.scalars().all())


@router.get("/{operator_id}", response_model=OperatorResponse)
async def get_operator(
    operator_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Operator:
    """Get a single operator by ID."""
    result = await db.execute(
        select(Operator).where(Operator.id == operator_id)
    )
    operator = result.scalar_one_or_none()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operator with id '{operator_id}' not found",
        )

    return operator
