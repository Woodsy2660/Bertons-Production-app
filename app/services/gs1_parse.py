"""Server-side GS1 Application Identifier parsing.

Primary path: Knox Capture **Parse GS1** keyboard-wedge output — a bracketed
human-readable AI string, e.g.::

    (02)09331288015587(11)260501(10)6121(37)504(90)16211644

Never invent values: missing AIs stay blank and are flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Bracketed AI tokens: (nn) or (nnn)/(nnnn) then value until next "(" or end.
# Work-order matching is intentionally NOT applied — operators verify scan results.
_BRACKETED_AI_RE = re.compile(r"\((\d{2,4})\)([^(]*)")

# AIs we map for Final Pallet Count prefill / validation.
AI_PALLET_NO = "90"
AI_QUANTITY = "37"
AI_BATCH = "10"
AI_PROD_DATE = "11"
AI_GTIN_CONTAINED = "02"

# Prefill-critical AIs — missing → blank field + flag (never guess).
EXPECTED_PREFILL_AIS: dict[str, str] = {
    AI_PALLET_NO: "pallet_no",
    AI_QUANTITY: "quantity",
}

# Nice-to-have AIs — filled when present; no hard failure if absent.
OPTIONAL_FIELD_AIS: dict[str, str] = {
    AI_BATCH: "batch",
    AI_PROD_DATE: "prn_date",
    AI_GTIN_CONTAINED: "gtin",
}


@dataclass
class Gs1Flag:
    level: str  # "info" | "warn" | "error"
    code: str
    message: str
    ai: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }
        if self.ai is not None:
            d["ai"] = self.ai
        return d


@dataclass
class Gs1ParseResult:
    raw: str
    ais: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str | None] = field(default_factory=dict)
    prefill: dict[str, str] = field(default_factory=dict)
    flags: list[Gs1Flag] = field(default_factory=list)
    ok: bool = True
    format: str = "bracketed"  # bracketed | element_string | unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "raw": self.raw,
            "format": self.format,
            "ais": dict(self.ais),
            "fields": dict(self.fields),
            "prefill": dict(self.prefill),
            "flags": [f.to_dict() for f in self.flags],
            "missing": [
                f.ai
                for f in self.flags
                if f.code == "missing_ai" and f.ai is not None
            ],
        }


def parse_bracketed_gs1(raw: str) -> dict[str, str]:
    """Extract ``(AI)value`` pairs. Order-independent; extra AIs kept as-is.

    Values are stripped of surrounding whitespace. Empty values are stored as
    empty strings so callers can distinguish "present but empty" from absent.
    """
    text = (raw or "").strip()
    result: dict[str, str] = {}
    for match in _BRACKETED_AI_RE.finditer(text):
        ai = match.group(1)
        value = match.group(2).strip()
        # Strip trailing GS / control chars if a wedge ever injects them mid-value
        value = value.rstrip("\x1d\x1e\x04")
        result[ai] = value
    return result


def looks_bracketed_gs1(raw: str) -> bool:
    return bool(_BRACKETED_AI_RE.search(raw or ""))


def format_gs1_date_yymmdd(value: str | None) -> str | None:
    """Convert GS1 date AI (YYMMDD) → ``YYYY-MM-DD``. 2-digit year → 20xx.

    Returns None when the value is missing, wrong length, or not a valid calendar
    date — never returns a guessed date.
    """
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) != 6:
        return None
    try:
        yy = int(digits[0:2])
        mm = int(digits[2:4])
        dd = int(digits[4:6])
    except ValueError:
        return None
    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return None
    year = 2000 + yy
    # Light calendar check via datetime
    try:
        from datetime import date

        date(year, mm, dd)
    except ValueError:
        return None
    return f"{year:04d}-{mm:02d}-{dd:02d}"


def map_final_pallet_fields(ais: dict[str, str]) -> tuple[dict[str, str | None], list[Gs1Flag]]:
    """Map AIs → Final Pallet Count logical fields; flag missing expected AIs."""
    fields: dict[str, str | None] = {
        "pallet_no": None,
        "quantity": None,
        "high": None,  # form field alias for quantity (Finished Product "High")
        "batch": None,
        "prn_date": None,
        "gtin": None,
    }
    flags: list[Gs1Flag] = []

    # Prefill-critical
    for ai, field_key in EXPECTED_PREFILL_AIS.items():
        if ai in ais and ais[ai] != "":
            fields[field_key] = ais[ai]
        else:
            fields[field_key] = None
            label = "pallet number" if field_key == "pallet_no" else "quantity"
            flags.append(
                Gs1Flag(
                    level="warn",
                    code="missing_ai",
                    ai=ai,
                    message=f"Scan is missing AI ({ai}) for {label} — left blank",
                )
            )

    # Quantity also drives the Finished Product `high` form field
    if fields["quantity"]:
        fields["high"] = fields["quantity"]

    # Optional
    if AI_BATCH in ais and ais[AI_BATCH] != "":
        fields["batch"] = ais[AI_BATCH]

    if AI_GTIN_CONTAINED in ais and ais[AI_GTIN_CONTAINED] != "":
        fields["gtin"] = ais[AI_GTIN_CONTAINED]

    if AI_PROD_DATE in ais and ais[AI_PROD_DATE] != "":
        formatted = format_gs1_date_yymmdd(ais[AI_PROD_DATE])
        if formatted:
            fields["prn_date"] = formatted
        else:
            flags.append(
                Gs1Flag(
                    level="warn",
                    code="invalid_date",
                    ai=AI_PROD_DATE,
                    message=(
                        f"Production date AI (11) value '{ais[AI_PROD_DATE]}' "
                        "could not be parsed — left blank"
                    ),
                )
            )

    return fields, flags


def build_prefill_map(fields: dict[str, str | None]) -> dict[str, str]:
    """Only include keys with concrete values for form inputs."""
    # Form-facing keys (batch/gtin remain in fields for status summary only)
    form_keys = ("pallet_no", "high", "prn_date", "quantity")
    out: dict[str, str] = {}
    for key in form_keys:
        val = fields.get(key)
        if val:
            # quantity is logical; high is the finished-product form field.
            # Prefer high for the form; still expose quantity for status UI.
            if key == "quantity":
                out["quantity"] = val
                continue
            out[key] = val
    return out


def parse_final_pallet_gs1(raw: str) -> Gs1ParseResult:
    """Parse Knox bracketed GS1 and map to Final Pallet Count fields.

    Fills form fields from whatever AIs are present. Does not compare against
    work-order values — operators check results. If the scan has no bracketed
    AIs, return ``ok=False`` with a clear error — do not invent values.
    """
    text = (raw or "").strip()
    result = Gs1ParseResult(raw=text)

    if not text:
        result.ok = False
        result.format = "unknown"
        result.flags.append(
            Gs1Flag(
                level="error",
                code="empty",
                message="No scan data received — try again",
            )
        )
        result.fields = {
            "pallet_no": None,
            "quantity": None,
            "high": None,
            "batch": None,
            "prn_date": None,
            "gtin": None,
        }
        return result

    if not looks_bracketed_gs1(text):
        result.ok = False
        result.format = "unknown"
        result.flags.append(
            Gs1Flag(
                level="error",
                code="not_bracketed",
                message=(
                    "Scan is not in GS1 Parse format (expected AIs like (90)…(37)…). "
                    "Enable Parse GS1 on the scanner profile and try again"
                ),
            )
        )
        result.fields = {
            "pallet_no": None,
            "quantity": None,
            "high": None,
            "batch": None,
            "prn_date": None,
            "gtin": None,
        }
        return result

    ais = parse_bracketed_gs1(text)
    result.ais = ais
    result.format = "bracketed"

    fields, flags = map_final_pallet_fields(ais)
    result.fields = fields
    result.flags.extend(flags)
    result.prefill = build_prefill_map(fields)

    # ok stays True if we parsed bracketed AIs — partial scans still return
    # structured blanks + flags rather than failing hard.
    return result
