"""JSON API for incremental form saves (readings, headers, drafts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.forms import FormType
from app.models import FormInstance, FormType as ModelFormType, Reading
from app.services.form_persistence import (
    add_reading,
    build_form_payload_from_mapping,
    build_pick_list_lines,
    get_open_batch,
    save_atomic_form,
    save_form_header,
    serialize_reading,
    submit_accrual_form,
)

router = APIRouter()


class SaveResponse(BaseModel):
    ok: bool = True
    saved_at: datetime
    form_status: str
    reading_count: int | None = None
    redirect: str | None = None


class ReadingResponse(BaseModel):
    ok: bool = True
    saved_at: datetime
    form_status: str
    reading_count: int
    reading: dict[str, Any]


class ReadingCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    operator_identifier: str = Field(..., min_length=1)
    captured_at: str | None = None


def _reading_count_query(form_instance_id: uuid.UUID):
    return select(func.count(Reading.id)).where(
        Reading.form_instance_id == form_instance_id
    )


@router.post("/{batch_id}/forms/{form_type}/readings", response_model=ReadingResponse)
async def api_add_reading(
    batch_id: uuid.UUID,
    form_type: str,
    body: ReadingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingResponse:
    """Save one accrual reading immediately (per-entry save)."""
    try:
        FormType(form_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    batch = await get_open_batch(db, batch_id)
    raw = body.model_dump()
    operator = raw.pop("operator_identifier")
    captured_at = raw.pop("captured_at", None)
    payload = build_form_payload_from_mapping(raw)

    try:
        form_instance, reading, _ = await add_reading(
            db,
            batch,
            form_type,
            operator_identifier=operator,
            captured_at=captured_at,
            payload=payload,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add reading: {e}")

    count_result = await db.execute(_reading_count_query(form_instance.id))
    reading_count = count_result.scalar_one() or 0

    return ReadingResponse(
        saved_at=datetime.utcnow(),
        form_status=form_instance.status.value,
        reading_count=reading_count,
        reading=serialize_reading(reading, form_type),
    )


@router.post("/{batch_id}/forms/{form_type}/header", response_model=SaveResponse)
async def api_save_header(
    batch_id: uuid.UUID,
    form_type: str,
    body: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SaveResponse:
    """Auto-save accrual form header fields."""
    try:
        FormType(form_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    batch = await get_open_batch(db, batch_id)
    payload = build_form_payload_from_mapping(body, exclude={"action"})

    try:
        form_instance = await save_form_header(db, batch, form_type, payload)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save header: {e}")

    return SaveResponse(
        saved_at=datetime.utcnow(),
        form_status=form_instance.status.value,
    )


@router.post("/{batch_id}/forms/{form_type}/draft", response_model=SaveResponse)
async def api_save_draft(
    batch_id: uuid.UUID,
    form_type: str,
    body: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SaveResponse:
    """Auto-save atomic form fields without submitting."""
    try:
        FormType(form_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    batch = await get_open_batch(db, batch_id)
    action = str(body.get("action", "save"))
    payload = build_form_payload_from_mapping(body, exclude={"action"})

    if form_type == "pick_list":
        lines = build_pick_list_lines(body)
        if lines:
            payload["lines"] = lines

    try:
        form_instance = await save_atomic_form(
            db, batch, form_type, payload, action=action
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save draft: {e}")

    return SaveResponse(
        saved_at=datetime.utcnow(),
        form_status=form_instance.status.value,
        redirect=f"/batches/{batch_id}" if action == "submit" else None,
    )


@router.post("/{batch_id}/forms/{form_type}/submit", response_model=SaveResponse)
async def api_submit_form(
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SaveResponse:
    """Mark an accrual form complete."""
    try:
        FormType(form_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    await get_open_batch(db, batch_id)

    try:
        form_instance = await submit_accrual_form(db, batch_id, form_type)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit form: {e}")

    if not form_instance:
        raise HTTPException(status_code=400, detail="No form data to submit")

    count_result = await db.execute(_reading_count_query(form_instance.id))
    reading_count = count_result.scalar_one() or 0

    return SaveResponse(
        saved_at=datetime.utcnow(),
        form_status=form_instance.status.value,
        reading_count=reading_count,
    )