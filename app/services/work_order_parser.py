import re
from pathlib import Path

from pypdf import PdfReader

# Stock codes starting with L are label stock (e.g. LBRESCSA22)
LABEL_STOCK_RE = re.compile(r"^L[A-Z0-9]{3,14}$", re.IGNORECASE)

# False positives to skip when scanning bare tokens
_LABEL_SKIP = frozenset({"LABEL", "LINE", "LTR", "LIST", "LEFT"})


def _extract_text(pdf_path: str | Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_number(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _extract_field(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def is_label_stock(stock_item: str) -> bool:
    """Label stock items start with L (e.g. LBRESCSA22)."""
    code = stock_item.strip().upper()
    return bool(LABEL_STOCK_RE.match(code)) and code not in _LABEL_SKIP


def filter_label_lines(lines: list[dict] | None) -> list[dict]:
    """Keep only label stock rows (Stock Item codes starting with L)."""
    if not lines:
        return []
    return [line for line in lines if is_label_stock(line.get("stock_item", ""))]


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


def _extract_label_pick_list_lines(text: str) -> list[dict]:
    """
    Extract label stock lines from work order PDF text.

    Searches for Stock Item / Stock Code fields where the code starts with L.
    Non-label stock is excluded — operators only track label supplied/returned qty.
    """
    lines: list[dict] = []
    seen: set[str] = set()

    # Primary: explicit "Stock Item" (or Stock Code) keyword with L-prefix code
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

    # Secondary: table rows — L-code, description fragment, required qty
    row_pattern = re.compile(
        r"\b(L[A-Z0-9]{4,14})\s+([A-Za-z][^\n]{4,60}?)\s+(\d[\d,]*)\s*(?:THOU|thou)?",
        re.MULTILINE,
    )
    for match in row_pattern.finditer(text):
        code = match.group(1).upper()
        if not is_label_stock(code) or code in seen:
            continue
        seen.add(code)
        lines.append(_make_label_line(
            code,
            match.group(2).strip(),
            _parse_number(match.group(3)),
        ))

    # Tertiary: bare L-prefix tokens (min 5 chars) when no structured matches
    if not lines:
        bare_pattern = re.compile(r"\b(L[A-Z0-9]{4,14})\b")
        for match in bare_pattern.finditer(text):
            code = match.group(1).upper()
            if not is_label_stock(code) or code in seen or len(code) < 5:
                continue
            seen.add(code)
            lines.append(_make_label_line(code))

    return lines


def parse_work_order_pdf(pdf_path: str | Path) -> dict:
    """
    Extract batch header and label pick-list lines from a work order PDF.

    pick_list_lines contains only label stock (Stock Item codes starting with L).
    """
    text = _extract_text(pdf_path)

    if not text.strip():
        return {
            "product": None,
            "stock_item": None,
            "tank": None,
            "run_date": None,
            "packing_unit": None,
            "packaging_line": None,
            "run_quantity": None,
            "pick_list_lines": [],
            "parse_note": (
                "Work order is image-based — label stock could not be auto-extracted. "
                "Label codes start with L (e.g. LBRESCSA22)."
            ),
        }

    product = _extract_field([
        r"product[:\s]+(.+)",
        r"wine[:\s]+(.+)",
        r"description[:\s]+(.+)",
    ], text)

    stock_item = _extract_field([
        r"stock\s*item[:\s]+([A-Z0-9]+)",
        r"item\s*code[:\s]+([A-Z0-9]+)",
    ], text)

    tank = _extract_field([r"tank[:\s#]+([A-Z0-9]+)"], text)

    packing_unit = _extract_field([r"packing\s*unit[:\s]+(.+)"], text)
    packaging_line = _extract_field([r"packag(?:e|ing)\s*line[:\s]+(\w+)"], text)

    run_qty_str = _extract_field([
        r"run\s*quantity[:\s]+(\d[\d,]*)",
        r"quantity[:\s]+(\d[\d,]*)",
    ], text)

    label_lines = _extract_label_pick_list_lines(text)

    parse_note = None
    if not label_lines:
        parse_note = (
            "No label stock (Stock Item codes starting with L) found in work order text."
        )

    return {
        "product": product,
        "stock_item": stock_item,
        "tank": tank,
        "run_date": None,
        "packing_unit": packing_unit,
        "packaging_line": packaging_line,
        "run_quantity": _parse_number(run_qty_str) if run_qty_str else None,
        "pick_list_lines": label_lines,
        "parse_note": parse_note,
    }