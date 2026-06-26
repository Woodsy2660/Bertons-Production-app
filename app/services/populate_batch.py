"""
Populate an existing batch with example form data matching its work order.

Used for compile/append PDF testing on real runs.
"""

import re
import uuid
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Batch,
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
from app.services.batch_lifecycle import maybe_transition_to_awaiting_review
from app.services.work_order_parser import _extract_text, filter_label_lines

RUN_15785_BATCH_ID = uuid.UUID("9193383c-175b-44c6-88d5-299ea749c36c")

RUN_15785 = {
    "run_number": "15785",
    "product": "Precious Earth 2025 SSB",
    "stock_item": "F25SSBPREAU1",
    "tank": "W25SSBSEA-EG",
    "run_date": date(2026, 7, 29),
    "packing_unit": "C750 12 x 750ml Bottles",
    "packaging_line": "BERT",
    "run_quantity": 10500,
    "bottle_code": "BTNLGCFG7AMB",
    "bvs_code": "BVSPREGRE283",
    "carton_code": "CNPRESSB400",
    "label_code": "LFPRESSB25",
    "bottles_total": 126000,
    "wine_litres": 94500,
    "cartons_per_pallet": 80,
}

LABEL_PICK_LIST_LINES = [
    {
        "stock_item": "LFPRESSB25",
        "description": "Precious Earth 2025 SSB 1-piece label",
        "required": 126000,
        "supplied_qty": 126200,
        "returned_qty": 145,
    },
]


def _reading_time(run_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime(run_date.year, run_date.month, run_date.day, hour, minute)


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


def _create_mock_listing_pdf(dest: Path, run: dict) -> None:
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
            <p><strong>Run Number:</strong> {run['run_number']}</p>
            <p><strong>Product:</strong> {run['product']}</p>
            <p><strong>Stock Item:</strong> {run['stock_item']}</p>
            <p><strong>Run Date:</strong> {run['run_date']}</p>
            <p><strong>Quantity:</strong> {run['run_quantity']} cartons</p>
            <table>
                <tr><th>Component</th><th>Code</th><th>Required</th></tr>
                <tr><td>Wine</td><td>{run['tank']}</td><td>{run['wine_litres']} L</td></tr>
                <tr><td>Bottle</td><td>{run['bottle_code']}</td><td>{run['bottles_total']}</td></tr>
                <tr><td>Label</td><td>{run['label_code']}</td><td>{run['bottles_total']}</td></tr>
                <tr><td>BVS</td><td>{run['bvs_code']}</td><td>{run['bottles_total']}</td></tr>
                <tr><td>Carton 12x750</td><td>{run['carton_code']}</td><td>{run['run_quantity']}</td></tr>
            </table>
            <div style="page-break-before: always;"></div>
            <h1>EzyWine Listing — Page 2</h1>
            <p><strong>Packaging Line:</strong> {run['packaging_line']}</p>
            <p><strong>Packing Unit:</strong> {run['packing_unit']}</p>
            <p>Batch status: Approved for production</p>
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


async def _ensure_operators(db: AsyncSession) -> None:
    existing = await db.execute(select(Operator))
    if existing.scalars().first():
        return
    for name, initials in [("John Smith", "JS"), ("Jane Doe", "JD"), ("Mike Brown", "MB")]:
        db.add(Operator(name=name, initials=initials))


def _finished_pallet_highs(cartons: int, per_pallet: int) -> list[int]:
    full = cartons // per_pallet
    remainder = cartons % per_pallet
    highs = [per_pallet] * full
    if remainder:
        highs.append(remainder)
    return highs


def _clean_ezywine_text(text: str) -> str:
    text = re.sub(r"/mvlin", " ", text)
    text = re.sub(r"/m[a-z]{3,4}", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _parse_ezywine_run_date(text: str) -> date | None:
    match = re.search(r"Start\s+(\d{2})/(\d{2})/(\d{2})", text, re.IGNORECASE)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    return date(2000 + year, month, day)


def _parse_thou_qty(text: str, code: str) -> int | None:
    match = re.search(
        rf"\b{re.escape(code)}\b[^\n]{{0,120}}?THOU\s+([\d.]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return int(float(match.group(1)) * 1000)
    except ValueError:
        return None


def _parse_litres(text: str, code: str) -> int | None:
    match = re.search(
        rf"\b{re.escape(code)}\b[^\n]{{0,120}}?LTR\s+([\d.]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return int(float(match.group(1)))
    except ValueError:
        return None


def _parse_cartons_per_pallet(text: str) -> int:
    match = re.search(r"Cartons/Pallet\s+([\d.]+)", text, re.IGNORECASE)
    if match:
        try:
            return int(float(match.group(1)))
        except ValueError:
            pass
    return 80


def build_run_dict_from_work_order(batch: Batch, pdf_path: str | Path) -> tuple[dict, list[dict]]:
    """Derive populate payload from an EzyWine work order PDF."""
    raw = _extract_text(pdf_path)
    text = _clean_ezywine_text(raw)

    def field(pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    product = field(r"Description\s*:\s*([^:]+?)(?:\s+Hourly Rate|\s+Code\s+\d|$)")
    stock_item = field(r"Stock Item\s*:\s*([A-Z0-9]+)")
    packing_unit = field(r"Packing Unit\s*:\s*([^:]+?)(?:\s+Run Quantity|$)")
    packaging_line = field(r"Packaging Line\s*:\s*(\w+)")
    run_quantity = field(r"Run Quantity\s*:\s*([\d,]+)")
    run_date = _parse_ezywine_run_date(text) or date.today()

    bottle_code = field(r"\b(BTN[A-Z0-9]+)\b")
    bvs_code = field(r"\b(BVS[A-Z0-9]+)\b")
    carton_code = field(r"\b(CN[A-Z0-9]+)\b")
    label_match = re.search(r"\b(L[A-Z0-9]{4,14})\b[^\n]{0,80}?THOU", text, re.IGNORECASE)
    label_code = label_match.group(1).upper() if label_match else None
    tank_match = re.search(r"\b(W[A-Z0-9-]+)\b[^\n]{0,80}?LTR", text, re.IGNORECASE)
    tank = tank_match.group(1).upper() if tank_match else field(r"\b(W[A-Z0-9-]+)\b")

    bottles_total = (
        _parse_thou_qty(text, bottle_code) if bottle_code else None
    ) or (_parse_thou_qty(text, label_code) if label_code else None) or 126000
    wine_litres = (_parse_litres(text, tank) if tank else None) or int(bottles_total * 0.75)
    cartons_per_pallet = _parse_cartons_per_pallet(text)

    qty = int(run_quantity.replace(",", "")) if run_quantity else batch.header.run_quantity or 0

    label_lines = filter_label_lines([
        {
            "stock_item": label_code or "LFPRESSB25",
            "description": (product or "") + " 1-piece label",
            "required": bottles_total,
            "supplied_qty": bottles_total + 200,
            "returned_qty": 145,
        }
    ])

    run = {
        "run_number": batch.run_number,
        "product": product or (batch.header.product if batch.header else "") or "Unknown product",
        "stock_item": stock_item or (batch.header.stock_item if batch.header else "") or "",
        "tank": tank or (batch.header.tank if batch.header else "") or "",
        "run_date": run_date,
        "packing_unit": packing_unit or (batch.header.packing_unit if batch.header else "") or "",
        "packaging_line": packaging_line or (batch.header.packaging_line if batch.header else "") or "BERT",
        "run_quantity": qty,
        "bottle_code": bottle_code or "BTNLGCFG7AMB",
        "bvs_code": bvs_code or "BVSPREGRE283",
        "carton_code": carton_code or "CNPRESSB400",
        "label_code": label_code or "LFPRESSB25",
        "bottles_total": bottles_total,
        "wine_litres": wine_litres,
        "cartons_per_pallet": cartons_per_pallet,
    }
    return run, label_lines


async def populate_batch_from_work_order(
    db: AsyncSession,
    batch_id: uuid.UUID,
    upload_dir: str,
) -> Batch:
    """Populate all nine forms using data extracted from the batch work order PDF."""
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    work_order = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.WORK_ORDER),
        None,
    )
    if not work_order:
        raise ValueError("Batch has no work order PDF")

    run, label_lines = build_run_dict_from_work_order(batch, work_order.stored_path)
    batch = await populate_batch_forms(db, batch_id, upload_dir, run, label_lines)
    await maybe_transition_to_awaiting_review(db, batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def populate_run_15785(db: AsyncSession, upload_dir: str) -> Batch:
    """Fix header, add listing PDF, and seed all 9 forms for Run #15785."""
    return await populate_batch_forms(
        db, RUN_15785_BATCH_ID, upload_dir, RUN_15785, LABEL_PICK_LIST_LINES,
    )


async def populate_batch_forms(
    db: AsyncSession,
    batch_id: uuid.UUID,
    upload_dir: str,
    run: dict,
    label_lines: list[dict],
) -> Batch:
    await _ensure_operators(db)

    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.form_instances),
            selectinload(Batch.uploaded_documents),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    # Remove existing form data so we can re-seed cleanly
    if batch.form_instances:
        await db.execute(
            delete(FormInstance).where(FormInstance.batch_id == batch_id)
        )
        await db.flush()

    # Fix batch header from work order
    header = batch.header
    if header:
        header.product = run["product"]
        header.stock_item = run["stock_item"]
        header.tank = run.get("tank")
        header.run_date = run["run_date"]
        header.packing_unit = run["packing_unit"]
        header.packaging_line = run["packaging_line"]
        header.run_quantity = run["run_quantity"]
        header.pick_list_lines = label_lines

    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    has_listing = any(
        d.slot == DocumentSlot.EZYWINE_LISTING for d in batch.uploaded_documents
    )
    if not has_listing:
        listing_dest = upload_path / f"{batch.id}_ezywine_listing_0.pdf"
        _create_mock_listing_pdf(listing_dest, run)
        db.add(UploadedDocument(
            batch_id=batch.id,
            slot=DocumentSlot.EZYWINE_LISTING,
            sequence=0,
            original_filename=f"MOCK_EzyWine_Listing_{run['run_number']}.pdf",
            stored_path=str(listing_dest),
            uploaded_by="Populate Script",
        ))

    run_no = run["run_number"]
    product = run["product"]
    run_date = run["run_date"]
    run_date_iso = run_date.isoformat()
    today = date.today().isoformat()
    rt = lambda h, m=0: _reading_time(run_date, h, m)  # noqa: E731

    # 1. Daily Production
    db.add(_form_instance(
        batch.id, FormType.DAILY_PRODUCTION, AccrualMode.ATOMIC,
        {
            "date": today,
            "run_number": run_no,
            "product": product,
            "tank": run.get("tank", ""),
            "start_time": "07:00",
            "finish_time": "04:00",
            "cartons_produced": run["run_quantity"],
            "wine_volume": run["wine_litres"],
            "dip_tank_start": "06:45",
            "dip_tank_end": "03:45",
            "filler_room_breakages": "N",
            "initials": "JS",
        },
    ))

    # 2. Filler Line Check (3 readings)
    fi_filler = _form_instance(
        batch.id, FormType.FILLER_LINE_CHECK, AccrualMode.MATRIX,
        {
            "date": run_date_iso,
            "wine": product,
            "tank": run.get("tank", ""),
            "run_number": run_no,
            "filters_used": "45",
            "correct_filters": "Y",
            "check_filtration": "Yes",
        },
    )
    db.add(fi_filler)
    await db.flush()

    for i, payload in enumerate([
        {
            "filler_vacuum": "-0.42", "rinser_all_heads": "Y",
            "filler_temperature": "18.5",
            "fill_height": ["61.8", "61.9", "62.0", "61.7"],
            "dissolved_oxygen": ["0.6", "0.7", "0.6"],
            "redraw": ["1.4", "1.5"],
            "torque_bridge": ["17", "18", "17", "18", "17", "18"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "JS",
        },
        {
            "filler_vacuum": "-0.43", "rinser_all_heads": "Y",
            "filler_temperature": "19.0",
            "fill_height": ["62.0", "61.8", "61.9", "62.1"],
            "dissolved_oxygen": ["0.7", "0.6", "0.7"],
            "redraw": ["1.5", "1.4"],
            "torque_bridge": ["18", "17", "18", "17", "18", "17"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "MB",
        },
        {
            "filler_vacuum": "-0.41", "rinser_all_heads": "Y",
            "filler_temperature": "18.8",
            "fill_height": ["61.9", "62.0", "61.8", "61.9"],
            "dissolved_oxygen": ["0.6", "0.6", "0.7"],
            "redraw": ["1.5", "1.5"],
            "torque_bridge": ["17", "18", "17", "18", "17", "18"],
            "bridge_inspection": ["OK", "OK", "OK", "OK"],
            "wad_imprint": "OK", "initial": "JS",
        },
    ], 1):
        db.add(_reading(fi_filler.id, i, rt(8 + i), payload["initial"], payload))

    # 3. Bottle Sealing (BVS Precious Earth Grn)
    fi_sealing = _form_instance(
        batch.id, FormType.BOTTLE_SEALING, AccrualMode.LOG,
        {
            "date": run_date_iso,
            "run_number": run_no,
            "manufacturer": "Guala Closures",
            "part_number": run["bvs_code"],
        },
    )
    db.add(fi_sealing)
    await db.flush()

    half = run["bottles_total"] // 2
    for i, (time_h, op, batch_no, qty) in enumerate([
        (9, "JS", "BVS-2026-0729-A", half),
        (18, "MB", "BVS-2026-0729-B", half),
    ], 1):
        db.add(_reading(
            fi_sealing.id, i, rt(time_h), op,
            {
                "batch_number": batch_no,
                "matches_work_order": "Y",
                "qty_used": qty,
                "initial": op,
            },
        ))

    # 4. Label Usage (1-piece label — fronts only)
    fi_label = _form_instance(
        batch.id, FormType.LABEL_USAGE, AccrualMode.LOG,
        {
            "date": run_date_iso,
            "product": product,
            "run_number": run_no,
            "totals_note": f"Qty: {run['bottles_total']}, Total: 126055 @ 22:30",
        },
    )
    db.add(fi_label)
    await db.flush()

    for i, (hour, op, counter, gms) in enumerate([
        (10, "JS", 42000, 1800),
        (16, "MB", 84000, 3600),
        (22, "JS", run["bottles_total"], 5400),
    ], 1):
        db.add(_reading(
            fi_label.id, i, rt(hour), op,
            {
                "section": "fronts",
                "counter": counter,
                "gms": gms,
                "matches_work_order": "Y",
                "po_no": "PO-15785",
                "initial": op,
            },
        ))

    # 5. Finished Product Line Check (2 readings)
    fi_fp_line = _form_instance(
        batch.id, FormType.FINISHED_PRODUCT_LINE_CHECK, AccrualMode.MATRIX,
        {"date": run_date_iso},
    )
    db.add(fi_fp_line)
    await db.flush()

    for i, (hour, op) in enumerate([(11, "JS"), (20, "MB")], 1):
        db.add(_reading(
            fi_fp_line.id, i, rt(hour), op,
            {
                "run_number": run_no,
                "front_label_height": 80.0,
                "back_label_height": 0,
                "gap_between_labels": ["0", "0"],
                "other_label_height": 0,
                "label_inkjet_lot": "F25SSBPREAU1",
                "inkjet_match": "Y",
                "bvs_code_match": "Y",
                "carton_barcode_match": "Y",
                "carton_print_match": "Y",
                "carton_sticker_match": "Y",
                "bottles_scraped_clean": "Y",
                "initials": op,
            },
        ))

    # 6. Label Pick List
    db.add(_form_instance(
        batch.id, FormType.PICK_LIST, AccrualMode.ATOMIC,
        {
            "run_number": run_no,
            "packing_unit": run["packing_unit"],
            "packaging_line": run["packaging_line"],
            "run_date": run_date_iso,
            "run_quantity": run["run_quantity"],
            "lines": label_lines,
            "initials": "JS",
        },
    ))

    # 7. Carton QC
    fi_carton = _form_instance(
        batch.id, FormType.CARTON_QC, AccrualMode.LOG,
        {
            "date": run_date_iso,
            "carton_wastage": 8,
            "divider_wastage": 2,
        },
    )
    db.add(fi_carton)
    await db.flush()

    db.add(_reading(
        fi_carton.id, 1, rt(8), "JS",
        {
            "table": "carton_details",
            "carton_manufacturer": "Visy",
            "carton_code": run["carton_code"],
            "qty_on_pallet": run["cartons_per_pallet"],
            "carton_code_match": "Y",
            "batch_number_pallet_tag": run_no,
            "dividers_match": "Y",
            "stickers_match": "Y",
            "initials": "JS",
        },
    ))
    for i, (hour, op) in enumerate([(10, "JS"), (15, "MB"), (21, "JS")], 2):
        db.add(_reading(
            fi_carton.id, i, rt(hour), op,
            {
                "table": "hourly_qc",
                "cartons_formed_glued": "Y",
                "check_6_cartons": "Y",
                "carton_print_match": "Y",
                "record_carton_print": "2025 F25SSBPREAU1",
                "glue_shots_ok": "Y",
                "cartons_sealed_neatly": "Y",
                "initials": op,
            },
        ))

    # 8. Final Pallet Count
    fi_pallet = _form_instance(
        batch.id, FormType.FINAL_PALLET_COUNT, AccrualMode.LOG,
        {
            "date": run_date_iso,
            "run_number": run_no,
            "bottle_code": run["bottle_code"],
            "bottle_code_matches": "Y",
            "product": product,
            "operator": "JS",
            "manufacturer": "O-I Glass",
            "pallet_tag_matches": "Y",
            "bottle_breakages": 24,
            "carton_breakages": 8,
            "summary_note": "10 bottle pallets + 132 finished pallets",
        },
    )
    db.add(fi_pallet)
    await db.flush()

    for i in range(1, 11):
        db.add(_reading(
            fi_pallet.id, i, rt(3, (i - 1) * 5), "JS",
            {
                "region": "bottles",
                "seq_no": i,
                "prn_date": run_date_iso,
                "pallet_no": f"B-{i:03d}",
                "colour": "AB",
                "foreign_objects_checked": "Y",
            },
        ))

    finished_highs = _finished_pallet_highs(run["run_quantity"], run["cartons_per_pallet"])
    for i, high in enumerate(finished_highs, 11):
        db.add(_reading(
            fi_pallet.id, i, rt(4), "MB",
            {"region": "finished", "seq_no": i - 10, "high": high},
        ))

    # 9. Finished Product Pallet
    fi_wh = _form_instance(
        batch.id, FormType.FINISHED_PRODUCT_PALLET, AccrualMode.LOG,
        {
            "date": run_date_iso,
            "product": product,
            "run_number": run_no,
            "operator": "MB",
            "bottle_code": run["bottle_code"],
            "bottle_code_matches": "Y",
            "pallet_type": "Loscam",
            "slip_sheet_required": "N",
            "layer_config_matches": "Y",
            "stack_height_matches": "Y",
            "breakages": 3,
            "summary_note": f"{len(finished_highs)} pallets = {run['run_quantity']} cartons",
        },
    )
    db.add(fi_wh)
    await db.flush()

    for i, high in enumerate(finished_highs, 1):
        db.add(_reading(
            fi_wh.id, i, rt(4, i % 60), "MB",
            {"seq_no": i, "high": high},
        ))

    await db.commit()
    await db.refresh(batch)
    return batch