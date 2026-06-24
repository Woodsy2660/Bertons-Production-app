from datetime import date, datetime
from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict


class BatchHeaderCreate(BaseModel):
    product: str | None = None
    stock_item: str | None = None
    tank: str | None = None
    run_date: date | None = None
    packing_unit: str | None = None
    packaging_line: str | None = None
    run_quantity: int | None = None
    pick_list_lines: list[dict[str, Any]] | None = None
    extra: dict[str, Any] | None = None


class BatchCreate(BaseModel):
    run_number: str
    created_by: str
    header: BatchHeaderCreate | None = None


class BatchHeaderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    product: str | None = None
    stock_item: str | None = None
    tank: str | None = None
    run_date: date | None = None
    packing_unit: str | None = None
    packaging_line: str | None = None
    run_quantity: int | None = None
    pick_list_lines: list[dict[str, Any]] | None = None
    extra: dict[str, Any] | None = None


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_number: str
    status: str
    is_locked: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    header: BatchHeaderResponse | None = None


class BatchListResponse(BaseModel):
    batches: list[BatchResponse]
    total: int


class OperatorCreate(BaseModel):
    name: str
    initials: str


class OperatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    initials: str
