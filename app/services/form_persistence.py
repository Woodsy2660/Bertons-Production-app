"""Shared form save logic for HTML routes and JSON API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import Role
from app.forms import FormType, get_form_template
from app.models import (
    AccrualMode as ModelAccrualMode,
    Batch,
    BatchStatus,
    FormInstance,
    FormStatus,
    FormType as ModelFormType,
    Reading,
)
from app.services.batch_lifecycle import (
    assert_can_write_forms,
    maybe_transition_to_awaiting_review,
)


def build_form_payload_from_mapping(
    data: dict[str, Any],
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """Build a JSON payload from a flat mapping, handling multi-value arrays."""
    exclude = exclude or set()
    payload: dict[str, Any] = {}
    multi_value_fields: dict[str, list] = {}

    for key, value in data.items():
        if key in exclude:
            continue
        if key.endswith("[]"):
            field_key = key[:-2]
            if field_key not in multi_value_fields:
                multi_value_fields[field_key] = []
            if value is not None and str(value).strip():
                multi_value_fields[field_key].append(value)
        elif isinstance(value, list):
            payload[key] = value if value else None
        else:
            payload[key] = value if value not in ("", None) else None

    for key, values in multi_value_fields.items():
        payload[key] = values if values else None

    return payload


def build_pick_list_lines(data: dict[str, Any]) -> list[dict]:
    """Extract pick-list line rows from form/API data."""
    lines = []
    line_indices: set[int] = set()

    for key in data:
        if key.startswith("lines_") and "_stock_item" in key:
            line_indices.add(int(key.split("_")[1]))

    for idx in sorted(line_indices):
        lines.append({
            "stock_item": data.get(f"lines_{idx}_stock_item", ""),
            "description": data.get(f"lines_{idx}_description", ""),
            "required": data.get(f"lines_{idx}_required") or None,
            "supplied_qty": data.get(f"lines_{idx}_supplied_qty") or None,
            "returned_qty": data.get(f"lines_{idx}_returned_qty") or None,
        })

    return lines


def reading_summary(form_type: str, payload: dict[str, Any]) -> str:
    """Short summary for the readings table / status board."""
    if form_type == "carton_qc":
        table = payload.get("table", "")
        if table == "carton_details" and payload.get("carton_code"):
            return str(payload["carton_code"])
        if table == "hourly_qc" and payload.get("record_carton_print"):
            return str(payload["record_carton_print"])
        return (table or "entry").replace("_", " ").title()

    if form_type == "final_pallet_count":
        region = payload.get("region", "")
        if region == "bottles" and payload.get("pallet_no"):
            return f"Pallet {payload['pallet_no']}"
        if region == "finished" and payload.get("high") is not None:
            return f"High: {payload['high']}"
        return region.title() if region else "Entry"

    if payload.get("batch_number"):
        return str(payload["batch_number"])
    if payload.get("section"):
        return f"{payload['section']} — {payload.get('counter', '')}".strip(" —")
    if payload.get("high") is not None:
        return f"High: {payload['high']}"
    return "Entry"


def reading_row_extra(form_type: str, payload: dict[str, Any]) -> dict[str, str]:
    """Extra columns for the readings table (section, region, etc.)."""
    if form_type == "carton_qc":
        table = payload.get("table", "")
        return {"section": table.replace("_", " ").title() if table else ""}
    if form_type == "final_pallet_count":
        region = payload.get("region", "")
        return {"section": region.title() if region else ""}
    return {}


def serialize_reading(reading: Reading, form_type: str) -> dict[str, Any]:
    """JSON-serializable reading for API responses."""
    payload = reading.payload or {}
    return {
        "id": str(reading.id),
        "sequence": reading.sequence,
        "captured_at": reading.captured_at.strftime("%H:%M"),
        "operator_identifier": reading.operator_identifier,
        "payload": payload,
        "summary": reading_summary(form_type, payload),
        **reading_row_extra(form_type, payload),
    }


def require_operator_identifier(value: str | None, *, field: str = "operator_identifier") -> str:
    identifier = (value or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return identifier


async def get_batch_for_write(
    db: AsyncSession,
    batch_id: uuid.UUID,
    role: Role,
) -> Batch:
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_write_forms(batch, role)
    return batch


async def get_open_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    role: Role = "operator",
) -> Batch:
    """Backward-compatible alias used by API routes."""
    return await get_batch_for_write(db, batch_id, role)


def _parse_captured_at(value: str | None) -> datetime:
    if value:
        today = date.today()
        time_parts = value.split(":")
        return datetime(
            today.year,
            today.month,
            today.day,
            int(time_parts[0]),
            int(time_parts[1]) if len(time_parts) > 1 else 0,
        )
    return datetime.utcnow()


async def save_atomic_form(
    db: AsyncSession,
    batch: Batch,
    form_type: str,
    payload: dict[str, Any],
    *,
    action: str = "save",
    role: Role = "operator",
) -> FormInstance:
    """Save or submit an atomic form (daily production, pick list)."""
    assert_can_write_forms(batch, role)
    form_template = get_form_template(FormType(form_type))

    submitted_by: str | None = None
    if action == "submit":
        submitted_by = require_operator_identifier(
            payload.get("initials") or payload.get("operator_identifier"),
            field="initials",
        )

    fi_result = await db.execute(
        select(FormInstance)
        .where(FormInstance.batch_id == batch.id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()

    if form_instance:
        form_instance.header_payload = payload
        form_instance.last_edited_at = datetime.utcnow()
        if action == "submit":
            form_instance.status = FormStatus.SUBMITTED
            form_instance.submitted_at = datetime.utcnow()
            form_instance.submitted_by = submitted_by
            form_instance.last_edited_by = submitted_by
        elif form_instance.status == FormStatus.SUBMITTED:
            form_instance.status = FormStatus.EDITED_SINCE_SUBMIT
        elif form_instance.status == FormStatus.NOT_STARTED:
            form_instance.status = FormStatus.IN_PROGRESS
    else:
        form_instance = FormInstance(
            batch_id=batch.id,
            form_type=ModelFormType(form_type),
            accrual_mode=ModelAccrualMode(form_template.accrual_mode.value),
            status=FormStatus.SUBMITTED if action == "submit" else FormStatus.IN_PROGRESS,
            header_payload=payload,
            submitted_at=datetime.utcnow() if action == "submit" else None,
            submitted_by=submitted_by,
            last_edited_by=submitted_by if action == "submit" else None,
        )
        db.add(form_instance)

    if batch.status == BatchStatus.REOPENED and action == "submit":
        batch.status = BatchStatus.IN_PROGRESS

    await maybe_transition_to_awaiting_review(db, batch)
    await db.commit()
    await db.refresh(form_instance)
    return form_instance


async def save_form_header(
    db: AsyncSession,
    batch: Batch,
    form_type: str,
    payload: dict[str, Any],
    *,
    role: Role = "operator",
) -> FormInstance:
    """Save accrual form header fields (manufacturer, filters, etc.)."""
    assert_can_write_forms(batch, role)
    form_template = get_form_template(FormType(form_type))

    fi_result = await db.execute(
        select(FormInstance)
        .where(FormInstance.batch_id == batch.id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()

    if form_instance:
        form_instance.header_payload = payload
        form_instance.last_edited_at = datetime.utcnow()
        if form_instance.status == FormStatus.NOT_STARTED:
            form_instance.status = FormStatus.IN_PROGRESS
    else:
        form_instance = FormInstance(
            batch_id=batch.id,
            form_type=ModelFormType(form_type),
            accrual_mode=ModelAccrualMode(form_template.accrual_mode.value),
            status=FormStatus.IN_PROGRESS,
            header_payload=payload,
        )
        db.add(form_instance)

    await db.commit()
    await db.refresh(form_instance)
    return form_instance


async def add_reading(
    db: AsyncSession,
    batch: Batch,
    form_type: str,
    *,
    operator_identifier: str,
    captured_at: str | None,
    payload: dict[str, Any],
    role: Role = "operator",
) -> tuple[FormInstance, Reading, int]:
    """Append one reading to an accrual form. Returns instance, reading, total count."""
    assert_can_write_forms(batch, role)
    operator_identifier = require_operator_identifier(operator_identifier)
    form_template = get_form_template(FormType(form_type))

    fi_result = await db.execute(
        select(FormInstance)
        .where(FormInstance.batch_id == batch.id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()

    if not form_instance:
        form_instance = FormInstance(
            batch_id=batch.id,
            form_type=ModelFormType(form_type),
            accrual_mode=ModelAccrualMode(form_template.accrual_mode.value),
            status=FormStatus.IN_PROGRESS,
        )
        db.add(form_instance)
        await db.flush()

    count_result = await db.execute(
        select(func.count(Reading.id))
        .where(Reading.form_instance_id == form_instance.id)
    )
    sequence = (count_result.scalar_one() or 0) + 1

    reading = Reading(
        form_instance_id=form_instance.id,
        sequence=sequence,
        captured_at=_parse_captured_at(captured_at),
        operator_identifier=operator_identifier,
        payload=payload,
    )
    db.add(reading)

    if form_instance.status == FormStatus.SUBMITTED:
        form_instance.status = FormStatus.EDITED_SINCE_SUBMIT
    elif form_instance.status == FormStatus.NOT_STARTED:
        form_instance.status = FormStatus.IN_PROGRESS
    form_instance.last_edited_at = datetime.utcnow()
    form_instance.last_edited_by = operator_identifier

    await db.commit()
    await db.refresh(reading)
    await db.refresh(form_instance)

    return form_instance, reading, sequence


async def _renumber_readings(db: AsyncSession, form_instance_id: uuid.UUID) -> None:
    result = await db.execute(
        select(Reading)
        .where(Reading.form_instance_id == form_instance_id)
        .order_by(Reading.sequence, Reading.created_at)
    )
    for index, reading in enumerate(result.scalars().all(), start=1):
        reading.sequence = index


async def delete_reading(
    db: AsyncSession,
    batch: Batch,
    form_type: str,
    reading_id: uuid.UUID,
    *,
    role: Role = "operator",
) -> tuple[FormInstance, int]:
    """Delete one reading and renumber the remaining entries."""
    assert_can_write_forms(batch, role)

    fi_result = await db.execute(
        select(FormInstance)
        .where(FormInstance.batch_id == batch.id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()
    if not form_instance:
        raise HTTPException(status_code=404, detail="Form not found")

    reading_result = await db.execute(
        select(Reading)
        .where(Reading.id == reading_id)
        .where(Reading.form_instance_id == form_instance.id)
    )
    reading = reading_result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Entry not found")

    await db.delete(reading)
    await db.flush()
    await _renumber_readings(db, form_instance.id)

    if form_instance.status == FormStatus.SUBMITTED:
        form_instance.status = FormStatus.EDITED_SINCE_SUBMIT
    form_instance.last_edited_at = datetime.utcnow()

    count_result = await db.execute(
        select(func.count(Reading.id))
        .where(Reading.form_instance_id == form_instance.id)
    )
    reading_count = count_result.scalar_one() or 0

    await db.commit()
    await db.refresh(form_instance)

    return form_instance, reading_count


async def submit_accrual_form(
    db: AsyncSession,
    batch_id: uuid.UUID,
    form_type: str,
    *,
    submitted_by: str | None = None,
    role: Role = "operator",
) -> FormInstance | None:
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_write_forms(batch, role)

    fi_result = await db.execute(
        select(FormInstance)
        .where(FormInstance.batch_id == batch_id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()

    if not form_instance:
        return None

    count_result = await db.execute(
        select(func.count(Reading.id))
        .where(Reading.form_instance_id == form_instance.id)
    )
    if (count_result.scalar_one() or 0) == 0:
        raise HTTPException(status_code=400, detail="Add at least one entry before submitting")

    if not (submitted_by or "").strip():
        latest_operator = await db.execute(
            select(Reading.operator_identifier)
            .where(Reading.form_instance_id == form_instance.id)
            .order_by(Reading.sequence.desc())
            .limit(1)
        )
        submitted_by = latest_operator.scalar_one_or_none() or form_instance.last_edited_by

    submitted_by = require_operator_identifier(submitted_by, field="submitted_by")

    form_instance.status = FormStatus.SUBMITTED
    form_instance.submitted_at = datetime.utcnow()
    form_instance.submitted_by = submitted_by
    form_instance.last_edited_by = submitted_by
    form_instance.last_edited_at = datetime.utcnow()

    if batch.status == BatchStatus.REOPENED:
        batch.status = BatchStatus.IN_PROGRESS

    await maybe_transition_to_awaiting_review(db, batch)
    await db.commit()
    await db.refresh(form_instance)

    return form_instance