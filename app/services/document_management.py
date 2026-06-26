"""Manager document delete/replace for work orders, listings, and label references."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Batch, BatchHeader, DocumentSlot, UploadedDocument
from app.services.work_order_parser import filter_label_lines, parse_work_order_pdf

SINGLE_SLOT_TYPES = frozenset({DocumentSlot.WORK_ORDER, DocumentSlot.EZYWINE_LISTING})


def remove_file_from_disk(stored_path: str | Path) -> None:
    path = Path(stored_path)
    if path.is_file():
        path.unlink(missing_ok=True)


def apply_parsed_header(header: BatchHeader, parsed: dict) -> None:
    header.product = parsed.get("product")
    header.stock_item = parsed.get("stock_item")
    header.tank = parsed.get("tank")
    header.run_date = parsed.get("run_date")
    header.packing_unit = parsed.get("packing_unit")
    header.packaging_line = parsed.get("packaging_line")
    header.run_quantity = parsed.get("run_quantity")
    header.pick_list_lines = filter_label_lines(parsed.get("pick_list_lines"))
    if parsed.get("parse_note"):
        header.extra = {"parse_note": parsed["parse_note"]}
    elif header.extra and "parse_note" in header.extra:
        header.extra = None


async def resequence_label_references(db: AsyncSession, batch_id: uuid.UUID) -> None:
    result = await db.execute(
        select(UploadedDocument)
        .where(UploadedDocument.batch_id == batch_id)
        .where(UploadedDocument.slot == DocumentSlot.LABEL_REFERENCE)
        .order_by(UploadedDocument.sequence)
    )
    for sequence, doc in enumerate(result.scalars().all()):
        doc.sequence = sequence


async def get_batch_document(
    db: AsyncSession,
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
) -> tuple[Batch, UploadedDocument]:
    batch_result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise ValueError("Batch not found")

    doc_result = await db.execute(
        select(UploadedDocument).where(UploadedDocument.id == doc_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc or doc.batch_id != batch_id:
        raise ValueError("Document not found")

    return batch, doc


async def delete_uploaded_document(db: AsyncSession, doc: UploadedDocument) -> None:
    remove_file_from_disk(doc.stored_path)
    await db.delete(doc)
    if doc.slot == DocumentSlot.LABEL_REFERENCE:
        await resequence_label_references(db, doc.batch_id)


async def clear_single_slot_documents(
    db: AsyncSession,
    batch_id: uuid.UUID,
    slot: DocumentSlot,
) -> None:
    result = await db.execute(
        select(UploadedDocument)
        .where(UploadedDocument.batch_id == batch_id)
        .where(UploadedDocument.slot == slot)
    )
    for old in result.scalars().all():
        remove_file_from_disk(old.stored_path)
        await db.delete(old)


async def refresh_header_from_work_order(
    db: AsyncSession,
    batch: Batch,
    stored_path: str,
) -> None:
    if not batch.header:
        batch.header = BatchHeader(batch=batch)
        db.add(batch.header)
    parsed = parse_work_order_pdf(stored_path)
    apply_parsed_header(batch.header, parsed)


def validate_pdf_upload(file: UploadFile) -> None:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise ValueError("Please upload a PDF file.")


async def replace_document_content(doc: UploadedDocument, file: UploadFile) -> None:
    validate_pdf_upload(file)
    stored_path = Path(doc.stored_path)
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(stored_path, "wb") as handle:
        content = await file.read()
        await handle.write(content)
    doc.original_filename = file.filename or doc.original_filename
    doc.uploaded_at = datetime.utcnow()