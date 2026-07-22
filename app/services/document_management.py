"""Manager document delete/replace for work orders, listings, and label references."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Batch, BatchHeader, DocumentSlot, UploadedDocument
from app.services.storage import delete_stored_file, read_bytes, save_bytes
from app.services.work_order_extraction import (
    apply_extraction_to_header,
    extract_work_order_from_bytes,
)


SINGLE_SLOT_TYPES = frozenset({DocumentSlot.WORK_ORDER, DocumentSlot.EZYWINE_LISTING})


async def remove_file_from_disk(stored_path: str | Path) -> None:
    await delete_stored_file(str(stored_path))


def apply_parsed_header(header: BatchHeader, verbose: dict) -> None:
    """Refresh stored extract and promoted columns; does not touch form instances."""
    apply_extraction_to_header(header, verbose)


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
    await remove_file_from_disk(doc.stored_path)
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
        await remove_file_from_disk(old.stored_path)
        await db.delete(old)


async def refresh_header_from_work_order(
    db: AsyncSession,
    batch: Batch,
    stored_path: str,
) -> None:
    if not batch.header:
        batch.header = BatchHeader(batch=batch)
        db.add(batch.header)
    content = await read_bytes(stored_path)
    verbose = extract_work_order_from_bytes(content)
    apply_parsed_header(batch.header, verbose)


def validate_pdf_upload(file: UploadFile) -> None:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise ValueError("Please upload a PDF file.")


async def replace_document_content(doc: UploadedDocument, file: UploadFile) -> None:
    validate_pdf_upload(file)
    content = await file.read()
    doc.stored_path = await save_bytes(str(doc.stored_path), content)
    doc.original_filename = file.filename or doc.original_filename
    doc.uploaded_at = datetime.utcnow()