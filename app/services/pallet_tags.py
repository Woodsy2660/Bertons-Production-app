"""Pallet count calculation and print orchestration (spec 11)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Batch, PalletTagPrint
from app.services.pallet_tag_generation import generate_pallet_tag_pdf
from app.services.storage import save_bytes
from app.services.tag_printer import BrowserTagPrinter, PrintResult
from app.services.work_order_parser import compute_pallet_count


@dataclass
class PalletCalcResult:
    pallets: int | None
    run_quantity: int | None
    cartons_per_pallet: int | None
    withheld: bool
    reason: str | None = None


def calculate_pallets(batch: Batch) -> PalletCalcResult:
    header = batch.header
    if not header:
        return PalletCalcResult(None, None, None, True, "No work order extraction stored.")

    run_quantity = header.run_quantity
    cartons_per_pallet = header.cartons_per_pallet
    missing = []
    if run_quantity is None:
        missing.append("run_quantity")
    if cartons_per_pallet is None:
        missing.append("cartons_per_pallet (P000)")
    if missing:
        return PalletCalcResult(
            None,
            run_quantity,
            cartons_per_pallet,
            True,
            f"Missing extracted field(s): {', '.join(missing)}",
        )

    return PalletCalcResult(
        compute_pallet_count(run_quantity, cartons_per_pallet),
        run_quantity,
        cartons_per_pallet,
        False,
    )


async def total_tags_printed(db: AsyncSession, batch_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(PalletTagPrint.tags_printed), 0)).where(
            PalletTagPrint.batch_id == batch_id
        )
    )
    return int(result.scalar_one())


async def record_pallet_tag_print(
    db: AsyncSession,
    batch: Batch,
    *,
    tags_to_print: int,
    printed_by: str,
    dispatch_method: str,
    note: str | None = None,
) -> tuple[PalletTagPrint, bytes, PrintResult]:
    calc = calculate_pallets(batch)
    pdf_bytes = generate_pallet_tag_pdf(batch, tags_to_print)
    storage_key = f"pallet_tags/{batch.id}/{uuid.uuid4()}.pdf"
    stored_path = await save_bytes(storage_key, pdf_bytes)

    print_row = PalletTagPrint(
        batch_id=batch.id,
        pallets_calculated=calc.pallets,
        tags_printed=tags_to_print,
        printed_by=printed_by,
        printed_at=datetime.utcnow(),
        dispatch_method=dispatch_method,
        stored_path=stored_path,
        note=note,
    )
    db.add(print_row)
    await db.flush()

    pdf_url = f"/batches/{batch.id}/pallet-tags/pdf/{print_row.id}"
    printer = BrowserTagPrinter(pdf_url)
    result = printer.print_pdf(pdf_bytes, tags_to_print)
    return print_row, pdf_bytes, result