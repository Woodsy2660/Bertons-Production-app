import math
import re
from io import BytesIO
from pathlib import Path

import pdfplumber

# Stock codes starting with L are label stock (e.g. LBRESCSA22)
LABEL_STOCK_RE = re.compile(r"^L[A-Z0-9]{3,14}$", re.IGNORECASE)
STOCK_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,14}(?:-[A-Z0-9]{1,8})?$")
DETAIL_CODE_RE = re.compile(r"^[A-Z]\d{3}$")

# False positives to skip when scanning bare tokens
_LABEL_SKIP = frozenset({"LABEL", "LINE", "LTR", "LIST", "LEFT"})

_BORDER_LINE_RE = re.compile(r"^[fad][a-k]{10,}[cde]$", re.IGNORECASE)
_BOX_GLYPH_RE = re.compile(r"^[a-k]{5,}$", re.IGNORECASE)

IMAGE_TEXT_THRESHOLD = 100

HEADER_LABEL_MAP: dict[str, str] = {
    "Run No./Ref.": "run_number",
    "Stock Item": "stock_item",
    "Stock Alias": "stock_alias",
    "Description": "description",
    "Packing Unit": "packing_unit",
    "Vessel/Batch": "vessel_batch",
    "Volume/Alloc.": "volume_alloc",
    "Run Status": "run_status",
    "Packaging Line": "packaging_line",
    "Start": "start_datetime",
    "Est. Finish": "est_finish",
    "Hourly Rate": "hourly_rate",
    "Est. Run Time": "est_run_time",
    "Run Quantity": "run_quantity",
    "Min. Operators": "min_operators",
    "Add. Operators": "add_operators",
    "Tot. Operators": "tot_operators",
}

DETAIL_CODE_MAP: dict[str, str] = {
    "G001": "carton_print_line1",
    "G002": "carton_print_line2",
    "G003": "carton_print_line3",
    "L007": "front_label_height",
    "L008": "label_barcode",
    "L010": "back_label_height",
    "L016": "other_label_height",
    "P000": "cartons_per_pallet",
    "P001": "cartons_per_layer",
    "P002": "pallet_layers",
    "P003": "pallet_layers",
    "P005": "pallet_type",
    "P006": "pallet_tag_flag",
    "P009": "pallet_stretch_wrap",
    "P010": "pallet_top_wrap",
    "P012": "pallet_slip_sheet",
}

HEADER_FIELD_SPECS: list[tuple[str, str]] = [
    ("run_number", "Run No./Ref."),
    ("stock_item", "Stock Item"),
    ("stock_alias", "Stock Alias"),
    ("description", "Description"),
    ("packing_unit", "Packing Unit"),
    ("vessel_batch", "Vessel/Batch"),
    ("volume_alloc", "Volume/Alloc."),
    ("run_status", "Run Status"),
    ("packaging_line", "Packaging Line"),
    ("start_datetime", "Start"),
    ("est_finish", "Est. Finish"),
    ("hourly_rate", "Hourly Rate"),
    ("est_run_time", "Est. Run Time"),
    ("run_quantity", "Run Quantity"),
    ("min_operators", "Min. Operators"),
    ("add_operators", "Add. Operators"),
    ("tot_operators", "Tot. Operators"),
]

IMAGE_PARSE_NOTE = (
    "Work order is image-based — fields could not be auto-extracted."
)


def _read_pdf_bytes(pdf_source: str | Path | bytes) -> bytes:
    if isinstance(pdf_source, bytes):
        return pdf_source
    return Path(pdf_source).read_bytes()


def _extract_layout_text(pdf_source: str | Path | bytes) -> str:
    pdf_bytes = _read_pdf_bytes(pdf_source)
    parts: list[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True)
            if text:
                parts.append(text)
    return "\n".join(parts)


def _extract_text(pdf_source: str | Path | bytes) -> str:
    """Backward-compatible text export used by populate_batch."""
    return _extract_layout_text(pdf_source)


def _is_noise_token(token: str) -> bool:
    token = token.strip()
    if not token:
        return True
    if _BORDER_LINE_RE.match(token):
        return True
    if _BOX_GLYPH_RE.match(token):
        return True
    if token.lower() in {"b", "d", "f"}:
        return True
    return False


def _split_border_fields(line: str) -> list[str]:
    return [
        part.strip()
        for part in line.split("b")
        if part.strip() and not _is_noise_token(part.strip())
    ]


def _clean_value(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"/mvlin\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _parse_number(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if cleaned.isdigit():
        return int(cleaned)
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_unit_qty(raw: str, unit: str) -> int | None:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return _parse_number(cleaned)
    if unit.upper() == "THOU":
        return int(number * 1000)
    if unit.upper() == "LTR":
        return int(number)
    return _parse_number(cleaned)


def _extract_header_pairs(part: str) -> list[tuple[str, str]]:
    part = part.strip()
    if not part:
        return []

    positions: list[tuple[int, str]] = []
    for label in HEADER_LABEL_MAP:
        idx = part.find(label)
        if idx >= 0:
            positions.append((idx, label))

    if not positions:
        return []

    positions.sort(key=lambda item: item[0])
    pairs: list[tuple[str, str]] = []
    for index, (start_idx, label) in enumerate(positions):
        value_start = start_idx + len(label)
        value_end = positions[index + 1][0] if index + 1 < len(positions) else len(part)
        raw_value = part[value_start:value_end]
        value = re.sub(r"^\s*:\s*", "", raw_value).strip()
        value = _clean_value(value)
        if value:
            pairs.append((label, value))
    return pairs


def _parse_header_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        for part in _split_border_fields(line):
            for label, value in _extract_header_pairs(part):
                key = HEADER_LABEL_MAP.get(label)
                if key:
                    values[key] = value
    return values


def _parse_stock_table_lines(lines: list[str]) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    in_section = False

    for line in lines:
        parts = _split_border_fields(line)
        if not parts:
            continue

        joined = " ".join(parts)
        if "Stock Item" in joined and "Description" in joined and "Unit" in joined:
            in_section = True
            continue
        if in_section and "Detail" in joined and "Name" in joined and "Value" in joined:
            break
        if not in_section:
            continue

        code = parts[0] if parts and STOCK_CODE_RE.match(parts[0]) else None
        if code:
            if current:
                rows.append(current)
            description_parts: list[str] = []
            unit = None
            required_total = None
            for idx, part in enumerate(parts[1:], start=1):
                upper = part.upper()
                if upper in {"THOU", "LTR"}:
                    unit = upper
                    if idx < len(parts) - 1:
                        required_total = _parse_unit_qty(parts[idx + 1], unit)
                    break
                description_parts.append(part)
            current = {
                "code": code.upper(),
                "description": " ".join(description_parts).strip(),
                "unit": unit,
                "required_total": required_total,
            }
            continue

        if current and parts:
            extra = parts[0]
            if extra and not STOCK_CODE_RE.match(extra):
                current["description"] = f"{current['description']} {extra}".strip()

    if current:
        rows.append(current)
    return rows


def _parse_detail_table(lines: list[str]) -> dict[str, str]:
    details: dict[str, str] = {}
    in_section = False

    for line in lines:
        parts = _split_border_fields(line)
        if not parts:
            continue

        joined = " ".join(parts)
        if "Detail" in joined and "Name" in joined and "Value" in joined:
            in_section = True
            continue
        if not in_section:
            continue
        if _BORDER_LINE_RE.match(joined.replace(" ", "")):
            break
        if parts[0] == "Comments":
            break

        code = parts[0]
        if not DETAIL_CODE_RE.match(code):
            continue
        value = _clean_value(parts[-1]) if len(parts) >= 3 else ""
        if value:
            details[code] = value

    return details


def _make_label_line(
    stock_item: str,
    description: str = "",
    required: int | None = None,
) -> dict:
    return {
        "stock_item": stock_item.strip().upper(),
        "description": description.strip(),
        "required": required,
        "supplied_qty": None,
        "returned_qty": None,
    }


def is_label_stock(stock_item: str) -> bool:
    """Label stock items start with L (e.g. LBRESCSA22)."""
    code = stock_item.strip().upper()
    return bool(LABEL_STOCK_RE.match(code)) and code not in _LABEL_SKIP


def filter_label_lines(lines: list[dict] | None) -> list[dict]:
    """Keep only label stock rows (Stock Item codes starting with L)."""
    if not lines:
        return []
    return [line for line in lines if is_label_stock(line.get("stock_item", ""))]


def _stock_rows_to_pick_list(stock_rows: list[dict]) -> list[dict]:
    lines: list[dict] = []
    seen: set[str] = set()
    for row in stock_rows:
        code = row["code"]
        if not is_label_stock(code) or code in seen:
            continue
        seen.add(code)
        lines.append(
            _make_label_line(
                code,
                row.get("description", ""),
                row.get("required_total"),
            )
        )
    return lines


def _extract_label_pick_list_lines(text: str) -> list[dict]:
    """
    Extract label stock lines from work order PDF text.

    Prefer layout stock-table parsing; fall back to regex for plain text.
    """
    if "Stock Item" in text and "Detail" in text:
        stock_rows = _parse_stock_table_lines(text.splitlines())
        lines = _stock_rows_to_pick_list(stock_rows)
        if lines:
            return lines

    lines: list[dict] = []
    seen: set[str] = set()

    stock_item_patterns = [
        re.compile(
            r"(?:stock\s*item|stock\s*code|item\s*code)\s*[:\-]?\s*"
            r"(L[A-Z0-9]{3,14})"
            r"(?:\s+([^\n]{3,80}?))?"
            r"(?:\s+(\d[\d,]*)\s*(?:THOU|thou|req(?:uired)?)?)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"Stock\s*Item[^\n]{0,120}?\b(L[A-Z0-9]{4,14})\b",
            re.IGNORECASE,
        ),
    ]

    for pattern in stock_item_patterns:
        for match in pattern.finditer(text):
            code = match.group(1).upper()
            if not is_label_stock(code) or code in seen:
                continue
            seen.add(code)
            description = ""
            required = None
            if match.lastindex and match.lastindex >= 2 and match.group(2):
                description = match.group(2).strip()
            if match.lastindex and match.lastindex >= 3 and match.group(3):
                required = _parse_number(match.group(3))
            lines.append(_make_label_line(code, description, required))

    row_pattern = re.compile(
        r"\b(L[A-Z0-9]{4,14})\s+([A-Za-z][^\n]{4,60}?)\s+(\d[\d,]*)\s*(?:THOU|thou)?",
        re.MULTILINE,
    )
    for match in row_pattern.finditer(text):
        code = match.group(1).upper()
        if not is_label_stock(code) or code in seen:
            continue
        seen.add(code)
        lines.append(
            _make_label_line(
                code,
                match.group(2).strip(),
                _parse_number(match.group(3)),
            )
        )

    if not lines:
        bare_pattern = re.compile(r"\b(L[A-Z0-9]{4,14})\b")
        for match in bare_pattern.finditer(text):
            code = match.group(1).upper()
            if not is_label_stock(code) or code in seen or len(code) < 5:
                continue
            seen.add(code)
            lines.append(_make_label_line(code))

    return lines


def _build_verbose_fields(
    header_values: dict[str, str],
    details: dict[str, str],
) -> list[dict]:
    fields: list[dict] = []
    for key, label in HEADER_FIELD_SPECS:
        value = header_values.get(key)
        fields.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "source": "header",
                "anchor": label,
                "found": value is not None and value != "",
            }
        )

    detail_labels = {
        "cartons_per_pallet": "Pallet - Cartons/Pallet",
        "cartons_per_layer": "Pallet - Cartons/Layer",
        "pallet_layers": "Pallet - N Layers",
        "pallet_type": "Pallet - Type",
        "pallet_tag_flag": "Pallet - Tag",
        "pallet_stretch_wrap": "Pallet - Stretch Wrap",
        "pallet_top_wrap": "Pallet - Top Wrap",
        "pallet_slip_sheet": "Pallet - Slip Sheet",
        "front_label_height": "Label - Front Label Height",
        "back_label_height": "Label - Back Label Height",
        "other_label_height": "Other Label Height",
        "label_barcode": "Label - Label Barcode",
        "carton_print_line1": "Carton Printing - Line one",
        "carton_print_line2": "Carton Printing - Line two",
        "carton_print_line3": "Ctn printing - Line continuing",
    }

    mapped_values: dict[str, str] = {}
    for code, value in details.items():
        field_key = DETAIL_CODE_MAP.get(code)
        if field_key:
            mapped_values[field_key] = value

    for key, label in detail_labels.items():
        value = mapped_values.get(key)
        source = "detail"
        anchor = ""
        for code, mapped_key in DETAIL_CODE_MAP.items():
            if mapped_key == key and code in details:
                anchor = code
                source = f"detail:{code}"
                break
        fields.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "source": source,
                "anchor": anchor,
                "found": value is not None and value != "",
            }
        )

    return fields


def _parse_layout_text(raw_layout_text: str) -> dict:
    lines = raw_layout_text.splitlines()
    header_values = _parse_header_values(lines)
    stock_rows = _parse_stock_table_lines(lines)
    details = _parse_detail_table(lines)
    pick_list_lines = _stock_rows_to_pick_list(stock_rows)

    stock_table_lines = [
        {
            **row,
            "is_label": is_label_stock(row["code"]),
        }
        for row in stock_rows
    ]

    warnings: list[str] = []
    parse_note = None
    if not pick_list_lines:
        parse_note = (
            "No label stock (Stock Item codes starting with L) found in work order text."
        )

    fields = _build_verbose_fields(header_values, details)

    return {
        "fields": fields,
        "header_values": header_values,
        "stock_table_lines": stock_table_lines,
        "details": details,
        "pick_list_lines": pick_list_lines,
        "raw_layout_text": raw_layout_text,
        "parse_note": parse_note,
        "warnings": warnings,
    }


def parse_work_order_pdf_verbose(pdf_source: str | Path | bytes) -> dict:
    """Return per-field provenance for dev/QA validation."""
    raw_layout_text = _extract_layout_text(pdf_source)
    if len(raw_layout_text.strip()) < IMAGE_TEXT_THRESHOLD:
        return {
            "fields": [
                {
                    "key": key,
                    "label": label,
                    "value": None,
                    "source": "header",
                    "anchor": label,
                    "found": False,
                }
                for key, label in HEADER_FIELD_SPECS
            ],
            "stock_table_lines": [],
            "details": {},
            "pick_list_lines": [],
            "raw_layout_text": raw_layout_text,
            "parse_note": IMAGE_PARSE_NOTE,
            "warnings": [],
        }

    return _parse_layout_text(raw_layout_text)


def _field_value(fields: list[dict], key: str) -> str | None:
    for field in fields:
        if field["key"] == key:
            value = field.get("value")
            if value is None or value == "":
                return None
            return str(value)
    return None


def _verbose_to_compatible(verbose: dict) -> dict:
    fields = verbose.get("fields", [])
    header_values = verbose.get("header_values") or {
        field["key"]: field.get("value")
        for field in fields
        if field.get("source") == "header"
    }
    details = verbose.get("details") or {}

    description = header_values.get("description")
    run_quantity = _parse_number(header_values.get("run_quantity"))
    cartons_raw = details.get("P000")
    cartons_per_pallet = None
    if cartons_raw:
        try:
            cartons_per_pallet = int(float(cartons_raw.replace(",", "")))
        except ValueError:
            cartons_per_pallet = _parse_number(cartons_raw)

    result = {
        "product": description,
        "stock_item": header_values.get("stock_item"),
        "tank": None,
        "run_date": None,
        "packing_unit": header_values.get("packing_unit"),
        "packaging_line": header_values.get("packaging_line"),
        "run_quantity": run_quantity,
        "pick_list_lines": verbose.get("pick_list_lines") or [],
        "parse_note": verbose.get("parse_note"),
        "run_number": header_values.get("run_number"),
        "stock_alias": header_values.get("stock_alias"),
        "description": description,
        "vessel_batch": header_values.get("vessel_batch"),
        "run_status": header_values.get("run_status"),
        "start_datetime": header_values.get("start_datetime"),
        "cartons_per_pallet": cartons_per_pallet,
        "cartons_per_layer": _parse_number(details.get("P001")),
        "pallet_layers": details.get("P002") or details.get("P003"),
        "pallet_type": details.get("P005"),
        "front_label_height": details.get("L007"),
        "back_label_height": details.get("L010"),
        "other_label_height": details.get("L016"),
        "label_barcode": details.get("L008"),
        "carton_print_line1": details.get("G001"),
        "carton_print_line2": details.get("G002"),
        "carton_print_line3": details.get("G003"),
        "stock_table_lines": verbose.get("stock_table_lines") or [],
        "details": details,
    }

    numeric_detail_keys = {"cartons_per_pallet", "cartons_per_layer"}
    for field in fields:
        if not field.get("source", "").startswith("detail:") or not field.get("found"):
            continue
        key = field["key"]
        if key in result and result[key] is not None:
            continue
        value = field.get("value")
        if key in numeric_detail_keys:
            result[key] = _parse_number(str(value)) if value is not None else None
        else:
            result[key] = value

    return result


def parse_work_order_pdf(pdf_source: str | Path | bytes) -> dict:
    """
    Extract batch header and label pick-list lines from a work order PDF.

    pick_list_lines contains only label stock (Stock Item codes starting with L).
    """
    verbose = parse_work_order_pdf_verbose(pdf_source)
    if verbose.get("parse_note") == IMAGE_PARSE_NOTE:
        return {
            "product": None,
            "stock_item": None,
            "tank": None,
            "run_date": None,
            "packing_unit": None,
            "packaging_line": None,
            "run_quantity": None,
            "pick_list_lines": [],
            "parse_note": IMAGE_PARSE_NOTE,
        }
    return _verbose_to_compatible(verbose)


def compute_pallet_count(run_quantity: int | None, cartons_per_pallet: int | None) -> int | None:
    if not run_quantity or not cartons_per_pallet:
        return None
    return math.ceil(run_quantity / cartons_per_pallet)