import math
from pathlib import Path

from app.services.work_order_parser import (
    IMAGE_PARSE_NOTE,
    _extract_label_pick_list_lines,
    _parse_layout_text,
    compute_pallet_count,
    filter_label_lines,
    is_label_stock,
    parse_work_order_pdf,
    parse_work_order_pdf_verbose,
)

FIXTURES = Path(__file__).parent / "fixtures" / "work_orders"


def test_is_label_stock():
    assert is_label_stock("LBRESCSA22")
    assert is_label_stock("lbrescs22")
    assert not is_label_stock("F22CSARESAI6")
    assert not is_label_stock("CRT-6x750")
    assert not is_label_stock("LABEL")


def test_extract_label_stock_from_stock_item_keyword():
    text = """
    Work Order Run 15646
    Stock Item: LBRESCSA22  Reserve Front Label  10800 THOU
    Stock Item: LBRESCSA22B Back Label 10800
    Stock Item: F22CSARESAI6  Wine product 1800
    Stock Item: CRT6x750 Carton 310
    """
    lines = _extract_label_pick_list_lines(text)
    codes = [line["stock_item"] for line in lines]
    assert "LBRESCSA22" in codes
    assert "LBRESCSA22B" in codes
    assert "F22CSARESAI6" not in codes
    assert "CRT6X750" not in codes


def test_filter_label_lines():
    mixed = [
        {"stock_item": "LBRESCSA22", "description": "Front"},
        {"stock_item": "F22CSARESAI6", "description": "Wine"},
    ]
    filtered = filter_label_lines(mixed)
    assert len(filtered) == 1
    assert filtered[0]["stock_item"] == "LBRESCSA22"


def test_parse_pbo04_run_15778_fixture():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    parsed = parse_work_order_pdf(pdf_bytes)

    assert parsed["run_number"] == "15778"
    assert parsed["stock_item"] == "F26PNOFSTAI1"
    assert parsed["product"] == "Foundstone 2026 Pinot Noir AI"
    assert parsed["packing_unit"] == "C750 12 x 750ml Bottles"
    assert parsed["packaging_line"] == "BERT"
    assert parsed["run_quantity"] == 192
    assert parsed["cartons_per_pallet"] == 64
    assert parsed["tank"] is None
    assert parsed["vessel_batch"] in (None, "")

    label_codes = {line["stock_item"] for line in parsed["pick_list_lines"]}
    assert label_codes == {"LBFSTPNO26AI", "LFFSTPNONV"}
    assert "F26PNOFSTAI1" not in label_codes
    assert "BTPUBUFG7AMB" not in label_codes

    assert parsed["details"]["P000"] == "64.0000"
    assert parsed["label_barcode"] == "9335966006737"
    assert compute_pallet_count(192, 64) == 3


def test_parse_15646_layout_text_guardrails():
    layout_text = (FIXTURES / "run_15646_layout.txt").read_text(encoding="utf-8")
    verbose = _parse_layout_text(layout_text)
    header = verbose["header_values"]

    assert header["run_number"] == "15646"
    assert header["stock_item"] == "F22CSARESAI6"
    assert header["run_quantity"] == "1800"
    assert header["packing_unit"] == "6750 6 x 750ml Bottles"
    assert header["packaging_line"] == "BERT"
    assert header["vessel_batch"] == "Z302"
    assert int(float(verbose["details"]["P000"])) == 84

    label_codes = {line["stock_item"] for line in verbose["pick_list_lines"]}
    assert label_codes == {"LBRESCSA22", "LBRESCSA22B", "LOTHCS24"}
    assert all(line["required"] == 10800 for line in verbose["pick_list_lines"])
    assert compute_pallet_count(1800, 84) == math.ceil(1800 / 84)


def test_image_based_work_order_returns_parse_note():
    pdf_bytes = (FIXTURES / "run_15646_image.pdf").read_bytes()
    parsed = parse_work_order_pdf(pdf_bytes)

    assert parsed["parse_note"] == IMAGE_PARSE_NOTE
    assert parsed["pick_list_lines"] == []
    assert parsed["run_quantity"] is None
    assert parsed["stock_item"] is None


def test_verbose_and_compatible_agree_on_shared_fields():
    pdf_bytes = (FIXTURES / "pbo04_run_15778.pdf").read_bytes()
    verbose = parse_work_order_pdf_verbose(pdf_bytes)
    compatible = parse_work_order_pdf(pdf_bytes)

    header_values = verbose.get("header_values") or {}
    assert compatible["run_number"] == header_values.get("run_number")
    assert compatible["stock_item"] == header_values.get("stock_item")
    assert compatible["run_quantity"] == int(header_values.get("run_quantity", 0))
    assert compatible["packing_unit"] == header_values.get("packing_unit")
    assert compatible["packaging_line"] == header_values.get("packaging_line")
    assert compatible["cartons_per_pallet"] == int(float(verbose["details"]["P000"]))
    assert compatible["pick_list_lines"] == verbose["pick_list_lines"]