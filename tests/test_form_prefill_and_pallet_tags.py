import math
import uuid
from datetime import date
from pathlib import Path

from app.models import (
    AccrualMode,
    Batch,
    BatchHeader,
    BatchStatus,
    FormInstance,
    FormStatus,
    FormType,
)
from app.services.form_prefill import (
    build_direct_prefill,
    build_form_context,
    build_reference_values,
    resolve_prefill_value,
)
from app.services.pallet_tag_generation import build_tag_context, generate_pallet_tag_pdf
from app.services.pallet_tags import calculate_pallets
from app.services.work_order_extraction import (
    apply_extraction_to_header,
    derive_bottle_code,
    populate_header_from_work_order_pdf,
)
from app.services.work_order_parser import _parse_layout_text, parse_work_order_pdf_verbose
from app.services.work_order_parser import compute_pallet_count

FIXTURES = Path(__file__).parent / "fixtures" / "work_orders"


def _batch_with_header(**header_kwargs) -> Batch:
    batch = Batch(
        id=uuid.uuid4(),
        run_number="15778",
        created_by="test",
        status=BatchStatus.IN_PROGRESS,
    )
    header = BatchHeader(batch=batch, **header_kwargs)
    batch.header = header
    return batch


def test_extraction_storage_pbo04():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    verbose = parse_work_order_pdf_verbose(pdf_bytes)
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    apply_extraction_to_header(header, verbose)

    assert header.run_quantity == 192
    assert header.cartons_per_pallet == 64
    assert header.bottle_code == "9-086"
    assert header.pallet_type == "Loscam"
    assert header.label_barcode == "9335966006737"
    assert header.front_label_height == "25mm"
    assert header.work_order_extract["details"]["P000"] == "64.0000"
    assert len(header.work_order_extract["stock_table_lines"]) >= 5
    assert "raw_layout_text" not in header.work_order_extract


def test_extraction_15646_layout_guardrails():
    layout = (FIXTURES / "run_15646_layout.txt").read_text(encoding="utf-8")
    verbose = _parse_layout_text(layout)
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15646", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    apply_extraction_to_header(header, verbose)

    assert header.cartons_per_pallet == 84
    assert header.bottle_code == "3-027"
    assert header.pallet_type == "Loscam"
    assert header.vessel_batch == "Z302"
    assert compute_pallet_count(1800, 84) == math.ceil(1800 / 84)


def test_tank_not_prefilled():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    populate_header_from_work_order_pdf(header, pdf_bytes)
    prefill = build_direct_prefill(
        _batch_with_header(
            product=header.product,
            vessel_batch=header.vessel_batch,
            work_order_extract=header.work_order_extract,
            run_date=header.run_date,
        ),
        "daily_production",
    )
    assert "tank" not in prefill
    assert header.tank is None


def test_reference_values_15778():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    populate_header_from_work_order_pdf(header, pdf_bytes)
    batch = Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    batch.header = header
    refs = build_reference_values(batch, "finished_product_line_check")
    assert refs["front_label_height"] == "25mm"
    assert refs["carton_barcode_match"] == "9335966006737"
    assert "BVS" in refs["bvs_code_match"]


def test_override_preservation():
    batch = _batch_with_header(product="Saved Product", run_date=date(2026, 7, 14))
    form_instance = FormInstance(
        batch=batch,
        form_type=FormType.DAILY_PRODUCTION,
        accrual_mode=AccrualMode.ATOMIC,
        status=FormStatus.IN_PROGRESS,
        header_payload={"product": "Operator Override"},
    )
    ctx = build_form_context(batch, "daily_production", form_instance)
    assert ctx["prefill_values"]["product"] == "Operator Override"
    assert ctx["prefill_flags"]["product"] is False


def test_pick_list_prefill_label_subset():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    populate_header_from_work_order_pdf(header, pdf_bytes)
    codes = {line["stock_item"] for line in header.pick_list_lines}
    assert codes == {"LBFSTPNO26AI", "LFFSTPNONV"}
    assert "F26PNOFSTAI1" not in codes


def test_pallet_calc_cases():
    batch = _batch_with_header(run_quantity=192, cartons_per_pallet=64)
    calc = calculate_pallets(batch)
    assert calc.pallets == 3
    assert calc.withheld is False

    batch = _batch_with_header(run_quantity=1800, cartons_per_pallet=84)
    assert calculate_pallets(batch).pallets == 22

    batch = _batch_with_header(run_quantity=100, cartons_per_pallet=10)
    assert calculate_pallets(batch).pallets == 10

    batch = _batch_with_header(run_quantity=100, cartons_per_pallet=None)
    withheld = calculate_pallets(batch)
    assert withheld.withheld is True
    assert "cartons_per_pallet" in (withheld.reason or "")


def test_pallet_tag_content_blank_handwrite_fields():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    header = BatchHeader(
        batch=Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    )
    populate_header_from_work_order_pdf(header, pdf_bytes)
    batch = Batch(id=uuid.uuid4(), run_number="15778", created_by="t", status=BatchStatus.IN_PROGRESS)
    batch.header = header

    ctx = build_tag_context(batch)
    assert ctx["run_number"] == "15778"
    assert ctx["stock_code"] == "F26PNOFSTAI1"
    assert "Pinot Noir" in ctx["product"]
    assert "750ml" in ctx["size"]
    assert ctx["print_date"]
    assert ctx["print_time"]

    pdf = generate_pallet_tag_pdf(batch, 2)
    assert pdf.startswith(b"%PDF")
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2
    combined = "".join((page.extract_text() or "") for page in reader.pages)
    assert "15778" in combined
    assert "F26PNOFSTAI1" in combined
    assert "Pallet Quantity" in combined
    assert "Pallet Number" in combined