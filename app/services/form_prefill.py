"""Extraction-driven form prefill and reference values (spec 10 §5)."""

from __future__ import annotations

import re
from typing import Any

from app.models import Batch, FormInstance


def _header(batch: Batch):
    return batch.header


def _stock_lines(batch: Batch) -> list[dict]:
    header = _header(batch)
    if not header or not header.work_order_extract:
        return []
    return header.work_order_extract.get("stock_table_lines") or []


def find_stock_line(batch: Batch, prefix: str) -> dict | None:
    prefix = prefix.upper()
    for row in _stock_lines(batch):
        code = (row.get("code") or "").upper()
        if code.startswith(prefix):
            return row
    return None


def extract_packing_size(packing_unit: str | None) -> str:
    if not packing_unit:
        return ""
    match = re.search(r"(\d+\s*x\s*\d+\s*ml\s*Bottles?)", packing_unit, re.IGNORECASE)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    parts = packing_unit.split()
    if len(parts) >= 4:
        return " ".join(parts[-4:])
    return packing_unit.strip()


def yes_no_to_bool_field(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1"}:
        return "Y"
    if normalized in {"no", "n", "false", "0"}:
        return "N"
    return value


def carton_print_reference(batch: Batch) -> str:
    header = _header(batch)
    if not header:
        return ""
    parts = [
        header.carton_print_line1,
        header.carton_print_line2,
        header.carton_print_line3,
    ]
    return " / ".join(part for part in parts if part)


def _saved_value(form_instance: FormInstance | None, key: str) -> Any:
    if not form_instance or not form_instance.header_payload:
        return None
    value = form_instance.header_payload.get(key)
    if value in (None, "", []):
        return None
    return value


def resolve_prefill_value(
    form_instance: FormInstance | None,
    key: str,
    prefill_value: Any,
) -> tuple[Any, bool]:
    """Return display value and whether it is a work-order prefill default."""
    saved = _saved_value(form_instance, key)
    if saved is not None:
        return saved, False
    if prefill_value in (None, "", []):
        return "", False
    return prefill_value, True


def build_direct_prefill(batch: Batch, form_type: str) -> dict[str, Any]:
    header = _header(batch)
    if not header:
        return {}

    start_date = header.run_date.isoformat() if header.run_date else ""
    common = {
        "date": start_date,
        "run_date": start_date,
        "run_number": batch.run_number,
        "product": header.product or "",
        "wine": header.product or "",
        "description": header.product or "",
        "stock_item": header.stock_item or "",
        "packing_unit": header.packing_unit or "",
        "packaging_line": header.packaging_line or "",
        "run_quantity": header.run_quantity if header.run_quantity is not None else "",
        "bottle_code": header.bottle_code or "",
        "pallet_type": header.pallet_type or "",
        "slip_sheet_required": yes_no_to_bool_field(
            (header.work_order_extract or {}).get("details", {}).get("P012")
            if header.work_order_extract
            else None
        ),
    }

    mapping: dict[str, dict[str, Any]] = {
        "daily_production": {
            "date": common["date"],
            "run_number": common["run_number"],
            "product": common["product"],
        },
        "filler_line_check": {
            "date": common["date"],
            "wine": common["wine"],
            "run_number": common["run_number"],
        },
        "bottle_sealing": {
            "date": common["date"],
            "run_number": common["run_number"],
        },
        "label_usage": {
            "date": common["date"],
            "product": common["product"],
            "run_number": common["run_number"],
        },
        "finished_product_line_check": {
            "date": common["date"],
            "run_number": common["run_number"],
        },
        "pick_list": {
            "run_number": common["run_number"],
            "packing_unit": common["packing_unit"],
            "packaging_line": common["packaging_line"],
            "run_date": common["run_date"],
            "run_quantity": common["run_quantity"],
        },
        "carton_qc": {"date": common["date"]},
        "final_pallet_count": {
            "date": common["date"],
            "run_number": common["run_number"],
            "product": common["product"],
            "bottle_code": common["bottle_code"],
            "pallet_type": common["pallet_type"],
        },
        "finished_product_pallet": {
            "date": common["date"],
            "product": common["product"],
            "run_number": common["run_number"],
            "bottle_code": common["bottle_code"],
            "pallet_type": common["pallet_type"],
            "slip_sheet_required": common["slip_sheet_required"],
        },
        "cask_final_pallet_count": {
            "date": common["date"],
            "run_number": common["run_number"],
            "product": common["product"],
        },
        "cask_line_check": {
            "date": common["date"],
            "tank": header.tank or "",
            "run_number": common["run_number"],
            "wine": common["wine"],
        },
        "cask_production_waste": {
            "product": common["product"],
            "run_number": common["run_number"],
            "date": common["date"],
        },
        "cask_tank_dip": {
            "product": common["product"],
            "run_number": common["run_number"],
            "date": common["date"],
            "tank": header.tank or "",
            "volume_supplied": (
                str(header.run_quantity) if header.run_quantity is not None else ""
            ),
        },
    }
    return mapping.get(form_type, {})


def build_reference_values(batch: Batch, form_type: str) -> dict[str, str]:
    header = _header(batch)
    if not header:
        return {}

    bvs = find_stock_line(batch, "BVS")
    carton = find_stock_line(batch, "CN")
    bvs_text = ""
    if bvs:
        bvs_text = f"{bvs.get('code', '')} — {bvs.get('description', '')}".strip(" —")

    carton_text = ""
    if carton:
        carton_text = f"{carton.get('code', '')} — {carton.get('description', '')}".strip(" —")

    carton_print = carton_print_reference(batch)
    layer_ref = ""
    if header.cartons_per_layer is not None:
        layer_ref = f"{header.cartons_per_layer} cartons/layer"
    if header.pallet_layers:
        layer_ref = f"{layer_ref} — {header.pallet_layers}".strip(" —")

    refs: dict[str, dict[str, str]] = {
        "finished_product_line_check": {
            "front_label_height": header.front_label_height or "",
            "back_label_height": header.back_label_height or "",
            "other_label_height": header.other_label_height or "",
            "carton_print_match": carton_print,
            "carton_barcode_match": header.label_barcode or "",
            "bvs_code_match": bvs_text,
        },
        "carton_qc": {
            "carton_code_match": carton_text,
            "carton_print_match": carton_print,
            "record_carton_print": carton_print,
        },
        "finished_product_pallet": {
            "layer_config_matches": layer_ref,
            "stack_height_matches": layer_ref,
        },
    }
    return refs.get(form_type, {})


def build_form_context(
    batch: Batch,
    form_type: str,
    form_instance: FormInstance | None = None,
) -> dict[str, Any]:
    """Prefill + reference values for templates, respecting saved operator data."""
    direct = build_direct_prefill(batch, form_type)
    prefill_values: dict[str, Any] = {}
    prefill_flags: dict[str, bool] = {}

    for key, value in direct.items():
        display, is_prefill = resolve_prefill_value(form_instance, key, value)
        prefill_values[key] = display
        prefill_flags[key] = is_prefill

    return {
        "prefill_values": prefill_values,
        "prefill_flags": prefill_flags,
        "reference_values": build_reference_values(batch, form_type),
    }


def build_inherited_values(batch: Batch, form_type: str, form_instance: FormInstance | None = None) -> dict:
    """Backward-compatible alias used by routes."""
    return build_form_context(batch, form_type, form_instance)["prefill_values"]