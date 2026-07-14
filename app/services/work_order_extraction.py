"""Store pdfplumber verbose extraction on batch headers."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.models import Batch, BatchHeader
from app.services.work_order_parser import (
    IMAGE_PARSE_NOTE,
    filter_label_lines,
    parse_work_order_pdf_verbose,
)


def parse_start_date(start_datetime: str | None) -> date | None:
    if not start_datetime:
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{2})", start_datetime)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    return date(2000 + year, month, day)


def derive_bottle_code(stock_table_lines: list[dict] | None) -> str | None:
    """First token of the BT-prefixed glass stock line description."""
    if not stock_table_lines:
        return None
    for row in stock_table_lines:
        code = (row.get("code") or "").upper()
        if not code.startswith("BT"):
            continue
        description = (row.get("description") or "").strip()
        if not description:
            continue
        token = description.split()[0]
        if token:
            return token
    return None


def build_work_order_extract_storage(verbose: dict) -> dict:
    """Persist verbose result without bloating raw_layout_text."""
    stored = {
        "fields": verbose.get("fields") or [],
        "header_values": verbose.get("header_values") or {},
        "stock_table_lines": verbose.get("stock_table_lines") or [],
        "details": verbose.get("details") or {},
        "parse_note": verbose.get("parse_note"),
        "warnings": verbose.get("warnings") or [],
    }
    raw = verbose.get("raw_layout_text") or ""
    if raw:
        stored["raw_layout_text_truncated"] = raw[:500]
    return stored


def _header_values_from_verbose(verbose: dict) -> dict[str, Any]:
    if verbose.get("header_values"):
        return verbose["header_values"]
    return {
        field["key"]: field.get("value")
        for field in verbose.get("fields", [])
        if field.get("source") == "header"
    }


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def apply_extraction_to_header(header: BatchHeader, verbose: dict) -> None:
    """Populate promoted columns and JSON blobs from verbose extraction."""
    header_values = _header_values_from_verbose(verbose)
    details = verbose.get("details") or {}
    stock_table_lines = verbose.get("stock_table_lines") or []

    description = header_values.get("description")
    header.product = description
    header.stock_item = header_values.get("stock_item")
    header.stock_alias = header_values.get("stock_alias")
    header.packing_unit = header_values.get("packing_unit")
    header.packaging_line = header_values.get("packaging_line")
    header.run_quantity = _int_or_none(header_values.get("run_quantity"))
    header.vessel_batch = header_values.get("vessel_batch")
    header.run_date = parse_start_date(header_values.get("start_datetime"))
    header.tank = None

    header.cartons_per_pallet = _int_or_none(details.get("P000"))
    header.cartons_per_layer = _int_or_none(details.get("P001"))
    header.pallet_layers = details.get("P002") or details.get("P003")
    header.pallet_type = details.get("P005")
    header.front_label_height = details.get("L007")
    header.back_label_height = details.get("L010")
    header.other_label_height = details.get("L016")
    header.label_barcode = details.get("L008")
    header.carton_print_line1 = details.get("G001")
    header.carton_print_line2 = details.get("G002")
    header.carton_print_line3 = details.get("G003")
    header.bottle_code = derive_bottle_code(stock_table_lines)

    header.pick_list_lines = filter_label_lines(verbose.get("pick_list_lines"))
    header.work_order_extract = build_work_order_extract_storage(verbose)

    parse_note = verbose.get("parse_note")
    if parse_note:
        header.extra = {"parse_note": parse_note}
    elif header.extra and "parse_note" in header.extra:
        header.extra = None


def extract_work_order_from_bytes(pdf_bytes: bytes) -> dict:
    return parse_work_order_pdf_verbose(pdf_bytes)


def populate_header_from_work_order_pdf(
    header: BatchHeader,
    pdf_bytes: bytes,
) -> dict:
    verbose = extract_work_order_from_bytes(pdf_bytes)
    apply_extraction_to_header(header, verbose)
    return verbose


def batch_has_work_order_extract(batch: Batch) -> bool:
    header = batch.header
    if not header or not header.work_order_extract:
        return False
    return header.work_order_extract.get("parse_note") != IMAGE_PARSE_NOTE