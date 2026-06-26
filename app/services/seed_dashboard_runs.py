"""
Seed dashboard mock runs for UI testing.

Creates:
  - 3 completed runs (all forms submitted, compiled)
  - 2 runs awaiting review (all forms submitted)
  - 1 in-progress run (partial forms)

Run via: python scripts/seed_dashboard_runs.py
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccrualMode as ModelAccrualMode,
    Batch,
    BatchHeader,
    BatchStatus,
    Compilation,
    DocumentSlot,
    FormInstance,
    FormStatus,
    FormType as ModelFormType,
    Operator,
    Reading,
    UploadedDocument,
)
from app.services.batch_lifecycle import mark_complete

MOCK_PRODUCTS = [
    {
        "run_number": "15801",
        "product": "Reserve 2022 Cab Sauvignon",
        "stock_item": "F22CSARESAI6",
        "tank": "B113",
        "run_quantity": 1800,
        "packing_unit": "6750 6 x 750ml Bottles",
        "status": BatchStatus.COMPLETE,
        "run_date_offset": -21,
        "compiled": True,
    },
    {
        "run_number": "15802",
        "product": "Precious Earth 2025 SSB",
        "stock_item": "F25SSBPREAU1",
        "tank": "W25SSBSEA-EG",
        "run_quantity": 10500,
        "packing_unit": "C750 12 x 750ml Bottles",
        "status": BatchStatus.COMPLETE,
        "run_date_offset": -14,
        "compiled": True,
    },
    {
        "run_number": "15803",
        "product": "Classic Shiraz 2024",
        "stock_item": "F24SHZCLAU6",
        "tank": "B208",
        "run_quantity": 2400,
        "packing_unit": "6750 6 x 750ml Bottles",
        "status": BatchStatus.COMPLETE,
        "run_date_offset": -7,
        "compiled": True,
    },
    {
        "run_number": "15804",
        "product": "Estate Chardonnay 2025",
        "stock_item": "F25CHWESTAU1",
        "tank": "B045",
        "run_quantity": 3200,
        "packing_unit": "C750 12 x 750ml Bottles",
        "status": BatchStatus.AWAITING_REVIEW,
        "run_date_offset": -2,
        "compiled": False,
    },
    {
        "run_number": "15805",
        "product": "Limited Release Merlot 2023",
        "stock_item": "F23MLTLRAU6",
        "tank": "B167",
        "run_quantity": 950,
        "packing_unit": "6750 6 x 750ml Bottles",
        "status": BatchStatus.AWAITING_REVIEW,
        "run_date_offset": -1,
        "compiled": False,
    },
    {
        "run_number": "15806",
        "product": "Golden Wattle Riesling 2026",
        "stock_item": "F26RIEGWAU1",
        "tank": "B022",
        "run_quantity": 4100,
        "packing_unit": "C750 12 x 750ml Bottles",
        "status": BatchStatus.IN_PROGRESS,
        "run_date_offset": 0,
        "compiled": False,
        "partial": True,
    },
]

LABEL_LINES = [
    {
        "stock_item": "LBL-FRT-MOCK",
        "description": "Mock front label",
        "required": 10800,
        "supplied_qty": 10850,
        "returned_qty": 38,
    },
    {
        "stock_item": "LBL-BCK-MOCK",
        "description": "Mock back label",
        "required": 10800,
        "supplied_qty": 10850,
        "returned_qty": 38,
    },
]


def _reading_time(run_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime(run_date.year, run_date.month, run_date.day, hour, minute)


def _form_instance(
    batch_id: uuid.UUID,
    form_type: ModelFormType,
    accrual_mode: ModelAccrualMode,
    header_payload: dict,
    *,
    status: FormStatus = FormStatus.SUBMITTED,
    submitted_by: str = "JS",
) -> FormInstance:
    submitted_at = datetime.utcnow() if status == FormStatus.SUBMITTED else None
    return FormInstance(
        batch_id=batch_id,
        form_type=form_type,
        accrual_mode=accrual_mode,
        status=status,
        header_payload=header_payload,
        submitted_by=submitted_by if status == FormStatus.SUBMITTED else None,
        submitted_at=submitted_at,
        last_edited_at=datetime.utcnow(),
        last_edited_by=submitted_by,
    )


def _reading(
    form_instance_id: uuid.UUID,
    sequence: int,
    captured_at: datetime,
    operator: str,
    payload: dict,
) -> Reading:
    return Reading(
        form_instance_id=form_instance_id,
        sequence=sequence,
        captured_at=captured_at,
        operator_identifier=operator,
        payload=payload,
    )


def _create_mock_listing_pdf(dest: Path, run_number: str, product: str) -> None:
    try:
        from weasyprint import HTML

        html = f"""
        <!DOCTYPE html>
        <html><body style="font-family: Arial; margin: 2cm;">
            <h1>Mock EzyWine Listing</h1>
            <p><strong>Run:</strong> {run_number}</p>
            <p><strong>Product:</strong> {product}</p>
            <p>Dashboard seed document — not a real listing.</p>
        </body></html>
        """
        HTML(string=html).write_pdf(str(dest))
    except Exception:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with open(dest, "wb") as f:
            writer.write(f)


async def _ensure_operators(db: AsyncSession) -> None:
    existing = await db.execute(select(Operator))
    if existing.scalars().first():
        return
    for name, initials in [
        ("John Smith", "JS"),
        ("Jane Doe", "JD"),
        ("Mike Brown", "MB"),
    ]:
        db.add(Operator(name=name, initials=initials))


async def _delete_existing_dashboard_runs(db: AsyncSession) -> None:
    result = await db.execute(
        select(Batch).where(
            Batch.run_number.in_([cfg["run_number"] for cfg in MOCK_PRODUCTS])
        )
    )
    for batch in result.scalars().all():
        await db.delete(batch)
    await db.commit()


async def _add_listing_document(
    db: AsyncSession,
    batch: Batch,
    upload_path: Path,
    product: str,
) -> Path:
    listing_dest = upload_path / f"{batch.id}_ezywine_listing_0.pdf"
    _create_mock_listing_pdf(listing_dest, batch.run_number, product)
    db.add(
        UploadedDocument(
            batch_id=batch.id,
            slot=DocumentSlot.EZYWINE_LISTING,
            sequence=0,
            original_filename=f"MOCK_Listing_{batch.run_number}.pdf",
            stored_path=str(listing_dest),
            uploaded_by="Dashboard Seed",
        )
    )
    return listing_dest


async def _populate_all_forms(
    db: AsyncSession,
    batch: Batch,
    cfg: dict,
    run_date: date,
) -> None:
    """Seed all nine forms as submitted."""
    run_no = cfg["run_number"]
    product = cfg["product"]
    stock = cfg["stock_item"]
    tank = cfg["tank"]
    run_date_iso = run_date.isoformat()
    today = date.today().isoformat()
    rt = lambda h, m=0: _reading_time(run_date, h, m)  # noqa: E731

    db.add(
        _form_instance(
            batch.id,
            ModelFormType.DAILY_PRODUCTION,
            ModelAccrualMode.ATOMIC,
            {
                "date": today,
                "run_number": run_no,
                "product": product,
                "tank": tank,
                "start_time": "06:30",
                "finish_time": "15:00",
                "cartons_produced": cfg["run_quantity"],
                "wine_volume": cfg["run_quantity"] * 6,
                "dip_tank_start": "06:15",
                "dip_tank_end": "14:45",
                "filler_room_breakages": "N",
                "initials": "JS",
            },
        )
    )

    fi_filler = _form_instance(
        batch.id,
        ModelFormType.FILLER_LINE_CHECK,
        ModelAccrualMode.MATRIX,
        {
            "date": run_date_iso,
            "wine": product,
            "tank": tank,
            "run_number": run_no,
            "filters_used": "45",
            "correct_filters": "Y",
            "check_filtration": "Yes",
        },
    )
    db.add(fi_filler)
    await db.flush()

    for i, (hour, op) in enumerate([(8, "JS"), (11, "MB"), (14, "JS")], 1):
        db.add(
            _reading(
                fi_filler.id,
                i,
                rt(hour),
                op,
                {
                    "filler_vacuum": "-0.44",
                    "rinser_all_heads": "Y",
                    "filler_temperature": "19.5",
                    "fill_height": ["62.0", "62.1", "61.9", "62.0"],
                    "dissolved_oxygen": ["0.7", "0.8", "0.7"],
                    "redraw": ["1.5", "1.5"],
                    "torque_bridge": ["18", "19", "18", "19", "18", "19"],
                    "bridge_inspection": ["OK", "OK", "OK", "OK"],
                    "wad_imprint": "OK",
                    "initial": op,
                },
            )
        )

    fi_sealing = _form_instance(
        batch.id,
        ModelFormType.BOTTLE_SEALING,
        ModelAccrualMode.LOG,
        {
            "date": run_date_iso,
            "run_number": run_no,
            "manufacturer": "Guala Closures",
            "part_number": "GC-29x21",
        },
    )
    db.add(fi_sealing)
    await db.flush()

    half = cfg["run_quantity"] * 3
    for i, (hour, op, batch_no, qty) in enumerate(
        [(9, "JS", f"BVS-{run_no}-A", half), (12, "MB", f"BVS-{run_no}-B", half)],
        1,
    ):
        db.add(
            _reading(
                fi_sealing.id,
                i,
                rt(hour),
                op,
                {
                    "batch_number": batch_no,
                    "matches_work_order": "Y",
                    "qty_used": qty,
                    "initial": op,
                },
            )
        )

    fi_label = _form_instance(
        batch.id,
        ModelFormType.LABEL_USAGE,
        ModelAccrualMode.LOG,
        {
            "date": run_date_iso,
            "product": product,
            "run_number": run_no,
            "totals_note": f"Qty: {cfg['run_quantity'] * 6}",
        },
    )
    db.add(fi_label)
    await db.flush()

    for i, (hour, op, section) in enumerate(
        [(10, "JS", "fronts"), (13, "MB", "backs"), (16, "JS", "other")],
        1,
    ):
        db.add(
            _reading(
                fi_label.id,
                i,
                rt(hour),
                op,
                {
                    "section": section,
                    "counter": 3600 * i,
                    "gms": 1200,
                    "matches_work_order": "Y",
                    "po_no": f"PO-{run_no}",
                    "initial": op,
                },
            )
        )

    fi_fp_line = _form_instance(
        batch.id,
        ModelFormType.FINISHED_PRODUCT_LINE_CHECK,
        ModelAccrualMode.MATRIX,
        {"date": run_date_iso},
    )
    db.add(fi_fp_line)
    await db.flush()

    for i, (hour, op) in enumerate([(10, "JS"), (15, "MB")], 1):
        db.add(
            _reading(
                fi_fp_line.id,
                i,
                rt(hour),
                op,
                {
                    "run_number": run_no,
                    "front_label_height": 85.0,
                    "back_label_height": 84.5,
                    "gap_between_labels": ["2.0", "2.1"],
                    "other_label_height": 0,
                    "label_inkjet_lot": stock,
                    "inkjet_match": "Y",
                    "bvs_code_match": "Y",
                    "carton_barcode_match": "Y",
                    "carton_print_match": "Y",
                    "carton_sticker_match": "Y",
                    "bottles_scraped_clean": "Y",
                    "initials": op,
                },
            )
        )

    db.add(
        _form_instance(
            batch.id,
            ModelFormType.PICK_LIST,
            ModelAccrualMode.ATOMIC,
            {
                "run_number": run_no,
                "packing_unit": cfg["packing_unit"],
                "packaging_line": "BERT",
                "run_date": run_date_iso,
                "run_quantity": cfg["run_quantity"],
                "lines": LABEL_LINES,
                "initials": "JS",
            },
        )
    )

    fi_carton = _form_instance(
        batch.id,
        ModelFormType.CARTON_QC,
        ModelAccrualMode.LOG,
        {"date": run_date_iso, "carton_wastage": 4, "divider_wastage": 1},
    )
    db.add(fi_carton)
    await db.flush()

    db.add(
        _reading(
            fi_carton.id,
            1,
            rt(8),
            "JS",
            {
                "table": "carton_details",
                "carton_manufacturer": "Visy",
                "carton_code": "CRT-MOCK",
                "qty_on_pallet": 84,
                "carton_code_match": "Y",
                "batch_number_pallet_tag": run_no,
                "dividers_match": "Y",
                "stickers_match": "Y",
                "initials": "JS",
            },
        )
    )
    for i, (hour, op) in enumerate([(10, "JS"), (14, "MB")], 2):
        db.add(
            _reading(
                fi_carton.id,
                i,
                rt(hour),
                op,
                {
                    "table": "hourly_qc",
                    "cartons_formed_glued": "Y",
                    "check_6_cartons": "Y",
                    "carton_print_match": "Y",
                    "record_carton_print": stock,
                    "glue_shots_ok": "Y",
                    "cartons_sealed_neatly": "Y",
                    "initials": op,
                },
            )
        )

    fi_pallet = _form_instance(
        batch.id,
        ModelFormType.FINAL_PALLET_COUNT,
        ModelAccrualMode.LOG,
        {
            "date": run_date_iso,
            "run_number": run_no,
            "bottle_code": "BTL-750-MOCK",
            "bottle_code_matches": "Y",
            "product": product,
            "operator": "JS",
            "manufacturer": "O-I Glass",
            "pallet_tag_matches": "Y",
            "bottle_breakages": 8,
            "carton_breakages": 2,
            "summary_note": "Mock pallet summary",
        },
    )
    db.add(fi_pallet)
    await db.flush()

    for i in range(1, 4):
        db.add(
            _reading(
                fi_pallet.id,
                i,
                rt(14, i * 10),
                "JS",
                {
                    "region": "finished",
                    "seq_no": i,
                    "high": 84 if i < 3 else 42,
                },
            )
        )

    fi_wh = _form_instance(
        batch.id,
        ModelFormType.FINISHED_PRODUCT_PALLET,
        ModelAccrualMode.LOG,
        {
            "date": run_date_iso,
            "product": product,
            "run_number": run_no,
            "operator": "MB",
            "bottle_code": "BTL-750-MOCK",
            "bottle_code_matches": "Y",
            "pallet_type": "CHEP",
            "slip_sheet_required": "Y",
            "layer_config_matches": "Y",
            "stack_height_matches": "Y",
            "breakages": 1,
            "summary_note": "Mock warehouse pallet log",
        },
    )
    db.add(fi_wh)
    await db.flush()

    for i, high in enumerate([84, 84, 84, 53], 1):
        db.add(
            _reading(
                fi_wh.id,
                i,
                rt(15, i * 5),
                "MB",
                {"seq_no": i, "high": high},
            )
        )


async def _populate_partial_forms(
    db: AsyncSession,
    batch: Batch,
    cfg: dict,
    run_date: date,
) -> None:
    """Seed an in-progress run with a mix of submitted and draft forms."""
    run_no = cfg["run_number"]
    product = cfg["product"]
    tank = cfg["tank"]
    run_date_iso = run_date.isoformat()
    today = date.today().isoformat()
    rt = lambda h, m=0: _reading_time(run_date, h, m)  # noqa: E731

    db.add(
        _form_instance(
            batch.id,
            ModelFormType.DAILY_PRODUCTION,
            ModelAccrualMode.ATOMIC,
            {
                "date": today,
                "run_number": run_no,
                "product": product,
                "tank": tank,
                "start_time": "07:15",
                "finish_time": "",
                "cartons_produced": 1200,
                "wine_volume": 7200,
                "dip_tank_start": "07:00",
                "dip_tank_end": "",
                "filler_room_breakages": "N",
                "initials": "JS",
            },
        )
    )

    fi_filler = _form_instance(
        batch.id,
        ModelFormType.FILLER_LINE_CHECK,
        ModelAccrualMode.MATRIX,
        {
            "date": run_date_iso,
            "wine": product,
            "tank": tank,
            "run_number": run_no,
            "filters_used": "45",
            "correct_filters": "Y",
            "check_filtration": "Yes",
        },
    )
    db.add(fi_filler)
    await db.flush()
    db.add(
        _reading(
            fi_filler.id,
            1,
            rt(9),
            "JS",
            {
                "filler_vacuum": "-0.43",
                "rinser_all_heads": "Y",
                "filler_temperature": "18.9",
                "fill_height": ["61.8", "62.0", "61.9", "62.1"],
                "dissolved_oxygen": ["0.6", "0.7", "0.6"],
                "redraw": ["1.4", "1.5"],
                "torque_bridge": ["17", "18", "17", "18", "17", "18"],
                "bridge_inspection": ["OK", "OK", "OK", "OK"],
                "wad_imprint": "OK",
                "initial": "JS",
            },
        )
    )

    fi_sealing = _form_instance(
        batch.id,
        ModelFormType.BOTTLE_SEALING,
        ModelAccrualMode.LOG,
        {
            "date": run_date_iso,
            "run_number": run_no,
            "manufacturer": "Guala Closures",
            "part_number": "GC-29x21",
        },
        status=FormStatus.IN_PROGRESS,
    )
    db.add(fi_sealing)
    await db.flush()
    db.add(
        _reading(
            fi_sealing.id,
            1,
            rt(10),
            "MB",
            {
                "batch_number": f"BVS-{run_no}-A",
                "matches_work_order": "Y",
                "qty_used": 2400,
                "initial": "MB",
            },
        )
    )

    db.add(
        _form_instance(
            batch.id,
            ModelFormType.LABEL_USAGE,
            ModelAccrualMode.LOG,
            {
                "date": run_date_iso,
                "product": product,
                "run_number": run_no,
                "totals_note": "",
            },
            status=FormStatus.IN_PROGRESS,
        )
    )


async def create_dashboard_mock_runs(
    db: AsyncSession,
    upload_dir: str,
) -> list[Batch]:
    """Create or replace all dashboard mock runs."""
    await _ensure_operators(db)
    await _delete_existing_dashboard_runs(db)

    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    today = date.today()
    created: list[Batch] = []

    for cfg in MOCK_PRODUCTS:
        run_date = today + timedelta(days=cfg["run_date_offset"])
        stamp = datetime.utcnow() + timedelta(days=cfg["run_date_offset"])

        batch = Batch(
            run_number=cfg["run_number"],
            created_by="Dashboard Seed",
            status=cfg["status"],
            is_locked=cfg["status"] == BatchStatus.COMPLETE,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(batch)
        await db.flush()

        db.add(
            BatchHeader(
                batch=batch,
                product=cfg["product"],
                stock_item=cfg["stock_item"],
                tank=cfg["tank"],
                run_date=run_date,
                packing_unit=cfg["packing_unit"],
                packaging_line="BERT",
                run_quantity=cfg["run_quantity"],
                pick_list_lines=LABEL_LINES,
            )
        )

        listing_path = await _add_listing_document(db, batch, upload_path, cfg["product"])

        if cfg.get("partial"):
            await _populate_partial_forms(db, batch, cfg, run_date)
        else:
            await _populate_all_forms(db, batch, cfg, run_date)

        if cfg["status"] == BatchStatus.COMPLETE:
            mark_complete(batch)
            if cfg.get("compiled"):
                db.add(
                    Compilation(
                        batch_id=batch.id,
                        output_filename=f"{cfg['run_number']}_Compiled.pdf",
                        stored_path=str(listing_path),
                        slot_manifest={"seed": True},
                        is_current=True,
                        compiled_by="Manager",
                        compiled_at=stamp + timedelta(hours=2),
                    )
                )
        elif cfg["status"] == BatchStatus.AWAITING_REVIEW:
            batch.is_locked = False

        created.append(batch)

    await db.commit()
    for batch in created:
        await db.refresh(batch)
    return created