"""
Seed a fully-populated test bottling run for compile PDF testing.

Run via:  python scripts/seed_test_run.py
Or visit:  /dev/test-run  (DEBUG mode only)
"""

import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Batch,
    BatchHeader,
    BatchStatus,
    FormInstance,
    FormType,
    AccrualMode,
    FormStatus,
    Reading,
    UploadedDocument,
    DocumentSlot,
    Operator,
)

TEST_RUN_NUMBER = "15646-COMPILE-TEST"

RUN_HEADER = {
    "product": "Reserve 2022 Cab Sauvignon AI",
    "stock_item": "F22CSARESAI6",
    "tank": "B113",
    "run_date": date(2024, 3, 12),
    "packing_unit": "6750 6 x 750ml Bottles",
    "packaging_line": "BERT",
    "run_quantity": 1800,
}

LABEL_PICK_LIST_LINES = [
    {
        "stock_item": "LBRESCSA22",
        "description": "Reserve 2022 Cab Sauvignon AI Front Label",
        "required": 10800,
        "supplied_qty": 10850,
        "returned_qty": 38,
    },
    {
        "stock_item": "LBRESCSA22B",
        "description": "Reserve 2022 Cab Sauvignon AI Back Label",
        "required": 10800,
        "supplied_qty": 10850,
        "returned_qty": 38,
    },
    {
        "stock_item": "LOTHCS24",
        "description": "Other Label 750ml",
        "required": 10800,
        "supplied_qty": 10800,
        "returned_qty": 0,
    },
]

SOURCE_FILES = {
    "work_order": [
        "uploads/9193383c-175b-44c6-88d5-299ea749c36c_work_order_0.pdf",
        "uploads/9554a804-2573-4a30-83e4-fd6e291e71fe_work_order_0.pdf",
    ],
    "label_reference": [
        "uploads/9193383c-175b-44c6-88d5-299ea749c36c_label_reference_0.pdf",
        "15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf",
    ],
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _resolve_source(candidates: list[str]) -> Path | None:
    root = _project_root()
    for rel in candidates:
        path = root / rel
        if path.exists():
            return path
    return None


def _create_mock_listing_pdf(dest: Path) -> None:
    """Generate a 2-page mock EzyWine listing PDF."""
    try:
        from weasyprint import HTML

        html = f"""
        <!DOCTYPE html>
        <html>
        <head><style>
            body {{ font-family: Arial, sans-serif; margin: 2cm; font-size: 11pt; }}
            h1 {{ color: #3d1f2b; border-bottom: 2px solid #b8956a; padding-bottom: 8px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
            th {{ background: #f3ede6; }}
            .mock-banner {{
                background: #fff3cd; border: 2px solid #b8956a;
                padding: 10px; margin-bottom: 20px; font-weight: bold;
            }}
        </style></head>
        <body>
            <div class="mock-banner">MOCK DOCUMENT — For compile testing only</div>
            <h1>EzyWine Bottling Listing</h1>
            <p><strong>Run Number:</strong> {TEST_RUN_NUMBER}</p>
            <p><strong>Product:</strong> {RUN_HEADER['product']}</p>
            <p><strong>Stock Item:</strong> {RUN_HEADER['stock_item']}</p>
            <p><strong>Tank:</strong> {RUN_HEADER['tank']}</p>
            <p><strong>Run Date:</strong> {RUN_HEADER['run_date']}</p>
            <p><strong>Quantity:</strong> {RUN_HEADER['run_quantity']} cartons</p>
            <table>
                <tr><th>Component</th><th>Code</th><th>Required</th></tr>
                <tr><td>Wine</td><td>{RUN_HEADER['stock_item']}</td><td>{RUN_HEADER['run_quantity']}</td></tr>
                <tr><td>Bottle</td><td>BTL-750-AI</td><td>10800</td></tr>
                <tr><td>Front Label</td><td>LBL-FRT-750</td><td>10800</td></tr>
                <tr><td>Back Label</td><td>LBL-BCK-750</td><td>10800</td></tr>
                <tr><td>Carton 6x750</td><td>CRT-6x750</td><td>1800</td></tr>
            </table>
            <div style="page-break-before: always;"></div>
            <h1>EzyWine Listing — Page 2</h1>
            <p><strong>Packaging Line:</strong> {RUN_HEADER['packaging_line']}</p>
            <p><strong>Packing Unit:</strong> {RUN_HEADER['packing_unit']}</p>
            <p>Batch status: Approved for production</p>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </body>
        </html>
        """
        HTML(string=html).write_pdf(str(dest))
    except Exception:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with open(dest, "wb") as f:
            writer.write(f)


def _copy_pdf(source: Path, dest: Path) -> None:
    shutil.copy2(source, dest)


def _reading_time(hour: int, minute: int = 0) -> datetime:
    d = RUN_HEADER["run_date"]
    return datetime(d.year, d.month, d.day, hour, minute)


async def _ensure_operators(db: AsyncSession) -> None:
    existing = await db.execute(select(Operator))
    if existing.scalars().first():
        return
    for name, initials in [("John Smith", "JS"), ("Jane Doe", "JD"), ("Mike Brown", "MB")]:
        db.add(Operator(name=name, initials=initials))


async def _delete_existing_test_run(db: AsyncSession) -> None:
    result = await db.execute(
        select(Batch).where(Batch.run_number == TEST_RUN_NUMBER)
    )
    batch = result.scalar_one_or_none()
    if batch:
        await db.delete(batch)
        await db.commit()


def _attach_document(
    batch_id: uuid.UUID,
    slot: DocumentSlot,
    sequence: int,
    stored_path: Path,
    original_filename: str,
) -> UploadedDocument:
    return UploadedDocument(
        batch_id=batch_id,
        slot=slot,
        sequence=sequence,
        original_filename=original_filename,
        stored_path=str(stored_path),
        uploaded_by="Test Seed",
    )


def _form_instance(
    batch_id: uuid.UUID,
    form_type: FormType,
    accrual_mode: AccrualMode,
    header_payload: dict,
    submitted_by: str = "JS",
) -> FormInstance:
    return FormInstance(
        batch_id=batch_id,
        form_type=form_type,
        accrual_mode=accrual_mode,
        status=FormStatus.SUBMITTED,
        header_payload=header_payload,
        submitted_by=submitted_by,
        submitted_at=datetime.utcnow(),
        last_edited_at=datetime.utcnow(),
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


async def create_compile_test_run(db: AsyncSession, upload_dir: str) -> Batch:
    """Create (or replace) a fully-populated test run ready for compile."""
    await _ensure_operators(db)
    await _delete_existing_test_run(db)

    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    batch = Batch(
        run_number=TEST_RUN_NUMBER,
        created_by="Test Seed",
        status=BatchStatus.IN_PROGRESS,
        is_locked=False,
    )
    db.add(batch)
    await db.flush()

    header = BatchHeader(
        batch=batch,
        pick_list_lines=LABEL_PICK_LIST_LINES,
        **RUN_HEADER,
    )
    db.add(header)

    # --- Uploads ---
    wo_src = _resolve_source(SOURCE_FILES["work_order"])
    if wo_src:
        wo_dest = upload_path / f"{batch.id}_work_order_0.pdf"
        _copy_pdf(wo_src, wo_dest)
        db.add(_attach_document(
            batch.id, DocumentSlot.WORK_ORDER, 0, wo_dest, wo_src.name,
        ))

    listing_dest = upload_path / f"{batch.id}_ezywine_listing_0.pdf"
    _create_mock_listing_pdf(listing_dest)
    db.add(_attach_document(
        batch.id, DocumentSlot.EZYWINE_LISTING, 0, listing_dest,
        f"MOCK_EzyWine_Listing_{TEST_RUN_NUMBER}.pdf",
    ))

    for seq, candidates in enumerate(SOURCE_FILES["label_reference"]):
        src = _resolve_source([candidates])
        if src:
            dest = upload_path / f"{batch.id}_label_reference_{seq}.pdf"
            _copy_pdf(src, dest)
            db.add(_attach_document(
                batch.id, DocumentSlot.LABEL_REFERENCE, seq, dest, src.name,
            ))

    run = TEST_RUN_NUMBER
    product = RUN_HEADER["product"]
    stock = RUN_HEADER["stock_item"]
    tank = RUN_HEADER["tank"]
    run_date = RUN_HEADER["run_date"].isoformat()
    today = date.today().isoformat()

    # --- 1. Daily Production (atomic) ---
    fi_daily = _form_instance(
        batch.id, FormType.DAILY_PRODUCTION, AccrualMode.ATOMIC,
        {
            "date": today,
            "run_number": run,
            "product": product,
            "tank": tank,
            "start_time": "06:30",
            "finish_time": "14:45",
            "cartons_produced": 1800,
            "wine_volume": 10800,
            "dip_tank_start": "06:15",
            "dip_tank_end": "14:30",
            "filler_room_breakages": "N",
            "initials": "JS",
        },
    )
    db.add(fi_daily)

    # --- 2. Filler Line Check (matrix, 3 readings) ---
    fi_filler = _form_instance(
        batch.id, FormType.FILLER_LINE_CHECK, AccrualMode.MATRIX,
        {
            "date": run_date,
            "wine": product,
            "tank": tank,
            "run_number": run,
            "filters_used": "45",
            "correct_filters": "Y",
            "check_filtration": "Yes",
        },
    )
    db.add(fi_filler)
    await db.flush()

    filler_readings = [
        {
            "filler_vacuum": "-0.45", "rinser_all_heads": "Y",
            "filler_temperature": "19.5",
            "fill_height": ["62.1", "62.0", "61.9", "62.2"],
            "dissolved_oxygen": ["0.8", "0.7", "0.9"],
            "redraw": ["1.5", "1.6"],
            "torque_bridge": ["18", "19", "18", "19", "18", "19"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "JS",
        },
        {
            "filler_vacuum": "-0.44", "rinser_all_heads": "Y",
            "filler_temperature": "20.1",
            "fill_height": ["62.0", "62.1", "62.0", "61.8"],
            "dissolved_oxygen": ["0.7", "0.8", "0.8"],
            "redraw": ["1.5", "1.5"],
            "torque_bridge": ["19", "18", "19", "18", "19", "18"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "MB",
        },
        {
            "filler_vacuum": "-0.46", "rinser_all_heads": "Y",
            "filler_temperature": "19.8",
            "fill_height": ["62.2", "62.0", "62.1", "62.0"],
            "dissolved_oxygen": ["0.8", "0.7", "0.7"],
            "redraw": ["1.6", "1.5"],
            "torque_bridge": ["18", "19", "18", "19", "18", "19"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "JS",
        },
    ]
    for i, payload in enumerate(filler_readings, 1):
        db.add(_reading(
            fi_filler.id, i, _reading_time(7 + i), payload["initial"], payload,
        ))

    # --- 3. Bottle Sealing (log, 2 readings) ---
    fi_sealing = _form_instance(
        batch.id, FormType.BOTTLE_SEALING, AccrualMode.LOG,
        {
            "date": run_date,
            "run_number": run,
            "manufacturer": "Guala Closures",
            "part_number": "GC-29x21-CS",
        },
    )
    db.add(fi_sealing)
    await db.flush()

    for i, (time_h, op, batch_no, qty) in enumerate([
        (8, "JS", "BS-2024-0312-A", 5400),
        (11, "MB", "BS-2024-0312-B", 5400),
    ], 1):
        db.add(_reading(
            fi_sealing.id, i, _reading_time(time_h), op,
            {
                "batch_number": batch_no,
                "matches_work_order": "Y",
                "qty_used": qty,
                "initial": op,
            },
        ))

    # --- 4. Label Usage (log, 3 sections) ---
    fi_label = _form_instance(
        batch.id, FormType.LABEL_USAGE, AccrualMode.LOG,
        {
            "date": run_date,
            "product": product,
            "run_number": run,
            "totals_note": "Qty: 10800, Total: 10972 @ 14:30",
        },
    )
    db.add(fi_label)
    await db.flush()

    label_entries = [
        ("fronts", 9, "JS", 3600, 1250),
        ("backs", 9, "MB", 3600, 1250),
        ("other", 10, "JS", 3600, 1250),
    ]
    for i, (section, hour, op, counter, gms) in enumerate(label_entries, 1):
        db.add(_reading(
            fi_label.id, i, _reading_time(hour), op,
            {
                "section": section,
                "counter": counter,
                "gms": gms,
                "matches_work_order": "Y",
                "po_no": "PO-88421",
                "initial": op,
            },
        ))

    # --- 5. Finished Product Line Check (matrix, 2 readings) ---
    fi_fp_line = _form_instance(
        batch.id, FormType.FINISHED_PRODUCT_LINE_CHECK, AccrualMode.MATRIX,
        {"date": run_date},
    )
    db.add(fi_fp_line)
    await db.flush()

    for i, (hour, op) in enumerate([(10, "JS"), (13, "MB")], 1):
        db.add(_reading(
            fi_fp_line.id, i, _reading_time(hour), op,
            {
                "run_number": run,
                "front_label_height": 85.0 + i,
                "back_label_height": 84.5 + i,
                "gap_between_labels": ["2.0", "2.1"],
                "other_label_height": 0,
                "label_inkjet_lot": "IJ-2024-0312",
                "inkjet_match": "Y",
                "bvs_code_match": "Y",
                "carton_barcode_match": "Y",
                "carton_print_match": "Y",
                "carton_sticker_match": "Y",
                "bottles_scraped_clean": "Y",
                "initials": op,
            },
        ))

    # --- 6. Label Pick List (atomic) ---
    fi_pick = _form_instance(
        batch.id, FormType.PICK_LIST, AccrualMode.ATOMIC,
        {
            "run_number": run,
            "packing_unit": RUN_HEADER["packing_unit"],
            "packaging_line": RUN_HEADER["packaging_line"],
            "run_date": run_date,
            "run_quantity": RUN_HEADER["run_quantity"],
            "lines": LABEL_PICK_LIST_LINES,
            "initials": "JS",
        },
    )
    db.add(fi_pick)

    # --- 7. Carton QC (log, carton + hourly) ---
    fi_carton = _form_instance(
        batch.id, FormType.CARTON_QC, AccrualMode.LOG,
        {
            "date": run_date,
            "carton_wastage": 3,
            "divider_wastage": 1,
        },
    )
    db.add(fi_carton)
    await db.flush()

    db.add(_reading(
        fi_carton.id, 1, _reading_time(8), "JS",
        {
            "table": "carton_details",
            "carton_manufacturer": "Visy",
            "carton_code": "CRT-6x750-CS24",
            "qty_on_pallet": 84,
            "carton_code_match": "Y",
            "batch_number_pallet_tag": run,
            "dividers_match": "Y",
            "stickers_match": "Y",
            "initials": "JS",
        },
    ))
    for i, (hour, op) in enumerate([(9, "JS"), (12, "MB")], 2):
        db.add(_reading(
            fi_carton.id, i, _reading_time(hour), op,
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
        ))

    # --- 8. Final Pallet Count (log, bottles + finished) ---
    fi_pallet = _form_instance(
        batch.id, FormType.FINAL_PALLET_COUNT, AccrualMode.LOG,
        {
            "date": run_date,
            "run_number": run,
            "bottle_code": "BTL-750-AI",
            "bottle_code_matches": "Y",
            "product": product,
            "operator": "JS",
            "manufacturer": "O-I Glass",
            "pallet_tag_matches": "Y",
            "bottle_breakages": 12,
            "carton_breakages": 3,
            "summary_note": "12 pallets + 2 layers",
        },
    )
    db.add(fi_pallet)
    await db.flush()

    db.add(_reading(
        fi_pallet.id, 1, _reading_time(14), "JS",
        {
            "region": "bottles",
            "seq_no": 1,
            "prn_date": run_date,
            "pallet_no": "P-001",
            "colour": "AB",
            "foreign_objects_checked": "Y",
        },
    ))
    db.add(_reading(
        fi_pallet.id, 2, _reading_time(14, 30), "JS",
        {
            "region": "bottles",
            "seq_no": 2,
            "prn_date": run_date,
            "pallet_no": "P-002",
            "colour": "A",
            "foreign_objects_checked": "Y",
        },
    ))
    for i, (seq, high) in enumerate([(1, 84), (2, 84), (3, 53)], 3):
        db.add(_reading(
            fi_pallet.id, i, _reading_time(15), "MB",
            {"region": "finished", "seq_no": seq, "high": high},
        ))

    # --- 9. Finished Product Pallet (log) ---
    fi_wh = _form_instance(
        batch.id, FormType.FINISHED_PRODUCT_PALLET, AccrualMode.LOG,
        {
            "date": run_date,
            "product": product,
            "run_number": run,
            "operator": "MB",
            "bottle_code": "BTL-750-AI",
            "bottle_code_matches": "Y",
            "pallet_type": "CHEP",
            "slip_sheet_required": "Y",
            "layer_config_matches": "Y",
            "stack_height_matches": "Y",
            "breakages": 2,
            "summary_note": "21×84, 1×53 = 1817",
        },
    )
    db.add(fi_wh)
    await db.flush()

    for i, high in enumerate([84, 84, 84, 84, 84, 84, 84, 84, 84, 84,
                              84, 84, 84, 84, 84, 84, 84, 84, 84, 84, 53], 1):
        db.add(_reading(
            fi_wh.id, i, _reading_time(15, i % 60), "MB",
            {"seq_no": i, "high": high},
        ))

    await db.commit()
    await db.refresh(batch)
    return batch