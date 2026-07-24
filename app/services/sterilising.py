"""Standalone sterilising checks — FOR CA 005 (cask) + FOR PK 026 (bottling)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.session import Role
from app.models import Batch, LineType
from app.models.sterilising_check import RunSterilisingCheck, SterilisingCheck
from app.services.batch_lifecycle import can_write_forms
from app.services.compilation import apply_form_title_logo

LineKey = Literal["cask", "bottling"]

# Paper form filter rows — both lines use wine 0.45/0.65 and water 0.45/0.22 (PK 026 / CA 005 paper).
DEFAULT_FILTER_ROWS: list[dict[str, str]] = [
    {"key": "wine_0_45", "label": "Wine filter 0.45 µm", "pressure_mbar": "", "pass_yn": ""},
    {"key": "wine_0_65", "label": "Wine filter 0.65 µm", "pressure_mbar": "", "pass_yn": ""},
    {"key": "water_0_45", "label": "Water filter 0.45 µm", "pressure_mbar": "", "pass_yn": ""},
    {"key": "water_0_22", "label": "Water filter 0.22 µm", "pressure_mbar": "", "pass_yn": ""},
]

FORM_META = {
    "cask": {
        "doc_number": "FOR CA 005",
        "form_title": "Cask Line Sterilising & Pre-Start Check",
        "line_type": LineType.CASK,
        "template": "sterilising_prestart.html",
        "lenticular_label": "Lenticular housing and bypass line sterilisation",
        "line_label": "0.65 / 0.45 / filler and return line sterilisation",
    },
    "bottling": {
        "doc_number": "FOR PK 026",
        "form_title": "Weekly Sterilising Check",
        "line_type": LineType.BOTTLING,
        "template": "sterilising_bottling.html",
        "lenticular_label": "Lenticular housing, bypass line and return line sterilisation",
        "line_label": "0.65 µm, 0.45 µm and filler sterilisation",
    },
}


def empty_filter_readings() -> list[dict[str, str]]:
    return [dict(row) for row in DEFAULT_FILTER_ROWS]


def parse_line_key(raw: str | None, *, default: LineKey = "cask") -> LineKey:
    v = (raw or default).strip().lower()
    if v in ("cask", "bottling"):
        return v  # type: ignore[return-value]
    raise HTTPException(status_code=400, detail="Line type must be cask or bottling")


def line_type_from_batch(batch: Batch) -> LineType:
    line = getattr(batch, "line_type", None)
    if line is None:
        return LineType.BOTTLING
    if isinstance(line, LineType):
        return line
    val = getattr(line, "value", line)
    return LineType.CASK if str(val).lower() == "cask" else LineType.BOTTLING


def line_key_from_batch(batch: Batch) -> LineKey:
    return "cask" if line_type_from_batch(batch) == LineType.CASK else "bottling"


def _yn(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().upper()
    if v in ("Y", "YES"):
        return "Y"
    if v in ("N", "NO"):
        return "N"
    if v == "":
        return None
    return v[:1]


def _parse_date(raw: str | None) -> date:
    if not raw or not str(raw).strip():
        raise HTTPException(status_code=400, detail="Date is required")
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date is invalid") from exc


def _parse_time(raw: str | None) -> time | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Time is invalid")


def build_filter_readings_from_form(form: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for template in DEFAULT_FILTER_ROWS:
        key = template["key"]
        pressure = str(form.get(f"filter_{key}_pressure", "") or "").strip()
        pass_yn = _yn(form.get(f"filter_{key}_pass")) or ""
        rows.append(
            {
                "key": key,
                "label": template["label"],
                "pressure_mbar": pressure,
                "pass_yn": pass_yn,
            }
        )
    return rows


def payload_from_form(form: dict[str, Any], *, line_key: LineKey) -> dict[str, Any]:
    operator_name = str(form.get("operator_name", "") or "").strip()
    if not operator_name:
        raise HTTPException(status_code=400, detail="Sterilising operator name is required")

    meta = FORM_META[line_key]
    data: dict[str, Any] = {
        "line_type": meta["line_type"],
        "operator_name": operator_name,
        "check_date": _parse_date(form.get("check_date")),
        "check_time": _parse_time(form.get("check_time")),
        "filters_integrity_tested": _yn(form.get("filters_integrity_tested")),
        "filter_readings": build_filter_readings_from_form(form),
        "lenticular_temp_c": str(form.get("lenticular_temp_c", "") or "").strip() or None,
        "lenticular_duration_mins": str(form.get("lenticular_duration_mins", "") or "").strip()
        or None,
        "line_temp_c": str(form.get("line_temp_c", "") or "").strip() or None,
        "line_duration_mins": str(form.get("line_duration_mins", "") or "").strip() or None,
        "notes": str(form.get("notes", "") or "").strip() or None,
        "system_id": None,
        "filler_clean": None,
        "carton_erector_clean": None,
        "qc_sign_off": "",
    }

    if line_key == "bottling":
        system = str(form.get("system_id", "") or "").strip().lower()
        if system not in ("system_1", "system_2"):
            raise HTTPException(
                status_code=400,
                detail="Which system is being sterilised is required (System 1 or System 2)",
            )
        data["system_id"] = system
        # PK 026 has no separate QC row — operator name is the sign-off
        data["qc_sign_off"] = operator_name
    else:
        qc = str(form.get("qc_sign_off", "") or "").strip()
        if not qc:
            raise HTTPException(status_code=400, detail="QC sign-off is required")
        data["qc_sign_off"] = qc
        data["filler_clean"] = _yn(form.get("filler_clean"))
        data["carton_erector_clean"] = _yn(form.get("carton_erector_clean"))

    return data


async def create_sterilising_check(
    db: AsyncSession,
    form: dict[str, Any],
    *,
    role: Role,
    line_key: LineKey = "cask",
) -> SterilisingCheck:
    data = payload_from_form(form, line_key=line_key)
    row = SterilisingCheck(
        **data,
        created_by_role=role,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_sterilising_checks(
    db: AsyncSession,
    *,
    limit: int = 100,
    line_type: LineType | None = None,
) -> list[SterilisingCheck]:
    q = (
        select(SterilisingCheck)
        .options(selectinload(SterilisingCheck.attachments).selectinload(RunSterilisingCheck.batch))
        .order_by(SterilisingCheck.check_date.desc(), SterilisingCheck.created_at.desc())
        .limit(limit)
    )
    if line_type is not None:
        q = q.where(SterilisingCheck.line_type == line_type)
    result = await db.execute(q)
    return list(result.scalars().unique().all())


async def get_sterilising_check(
    db: AsyncSession, check_id: uuid.UUID
) -> SterilisingCheck:
    result = await db.execute(
        select(SterilisingCheck)
        .options(selectinload(SterilisingCheck.attachments).selectinload(RunSterilisingCheck.batch))
        .where(SterilisingCheck.id == check_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Sterilising check not found")
    return row


async def list_checks_for_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[SterilisingCheck]:
    result = await db.execute(
        select(SterilisingCheck)
        .join(RunSterilisingCheck, RunSterilisingCheck.sterilising_check_id == SterilisingCheck.id)
        .where(RunSterilisingCheck.batch_id == batch_id)
        .order_by(SterilisingCheck.check_date.desc(), SterilisingCheck.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def attach_to_batch(
    db: AsyncSession,
    batch: Batch,
    check_id: uuid.UUID,
    *,
    role: Role,
) -> RunSterilisingCheck:
    if not can_write_forms(batch, role):
        raise HTTPException(status_code=403, detail="This run is locked")

    check = await get_sterilising_check(db, check_id)
    batch_line = line_type_from_batch(batch)
    if check.line_type != batch_line:
        raise HTTPException(
            status_code=400,
            detail="Sterilising check line type must match the run (cask vs bottling)",
        )

    existing = await db.execute(
        select(RunSterilisingCheck)
        .where(RunSterilisingCheck.batch_id == batch.id)
        .where(RunSterilisingCheck.sterilising_check_id == check.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This check is already attached to this run")

    link = RunSterilisingCheck(
        batch_id=batch.id,
        sterilising_check_id=check.id,
        attached_by_role=role,
        attached_at=datetime.utcnow(),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def detach_from_batch(
    db: AsyncSession,
    batch: Batch,
    check_id: uuid.UUID,
    *,
    role: Role,
) -> None:
    if not can_write_forms(batch, role):
        raise HTTPException(status_code=403, detail="This run is locked")

    result = await db.execute(
        select(RunSterilisingCheck)
        .where(RunSterilisingCheck.batch_id == batch.id)
        .where(RunSterilisingCheck.sterilising_check_id == check_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await db.delete(link)
    await db.commit()


def sterilising_context(check: SterilisingCheck) -> dict[str, Any]:
    line_key: LineKey = "cask" if check.line_type == LineType.CASK else "bottling"
    meta = FORM_META[line_key]
    return {
        "check": check,
        "doc_number": check.doc_number,
        "form_name": check.form_title,
        "filter_readings": check.filter_readings or empty_filter_readings(),
        "lenticular_label": meta["lenticular_label"],
        "line_label": meta["line_label"],
        "line_key": line_key,
        "now": datetime.now(),
    }


def render_sterilising_pdf(check: SterilisingCheck) -> bytes:
    """Render sterilising check to PDF (WeasyPrint preferred, xhtml2pdf fallback)."""
    line_key: LineKey = "cask" if check.line_type == LineType.CASK else "bottling"
    template_name = FORM_META[line_key]["template"]

    templates_path = Path(__file__).parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(templates_path)), autoescape=True)
    template = env.get_template(template_name)
    html_content = template.render(**sterilising_context(check))

    css_content = """
        @page { size: A4 portrait; margin: 1cm; }
        html, body { font-family: Arial, sans-serif; font-size: 10pt; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border: 1px solid #333; padding: 4px 6px; text-align: left; }
        th { background-color: #f0f0f0; }
        .header-box, .pdf-page-header {
            border: none;
            border-bottom: 1.5pt solid #000;
            padding: 2px 0 8px 0;
            margin: 0 0 12px 0;
            padding-right: 32mm;
            min-height: 12mm;
        }
        .form-title {
            font-size: 13pt;
            font-weight: bold;
            margin: 0 0 2px 0;
            color: #000;
            line-height: 1.2;
        }
        .doc-number {
            font-size: 9pt;
            color: #444;
            margin: 0;
        }
        .pdf-brand-table {
            width: 100%;
            border: none !important;
            border-collapse: collapse;
        }
        .pdf-brand-table td {
            border: none !important;
            padding: 0 !important;
            background: transparent !important;
        }
        .pdf-brand-title-cell {
            width: 100%;
            vertical-align: top;
            text-align: left;
        }
        h3 { margin: 12px 0 6px; font-size: 11pt; }
        .page-logo, img.page-logo { display: none !important; }
    """
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css_content}</style></head>
<body>{html_content}</body></html>"""

    pdf_bytes: bytes | None = None
    try:
        from weasyprint import CSS, HTML

        pdf_bytes = HTML(string=full_html).write_pdf(stylesheets=[CSS(string=css_content)])
    except (ImportError, OSError):
        pdf_bytes = None

    if pdf_bytes is None:
        try:
            from xhtml2pdf import pisa
        except ImportError as exc:
            raise RuntimeError("PDF rendering unavailable") from exc
        buffer = BytesIO()
        if pisa.CreatePDF(full_html, dest=buffer).err:
            raise RuntimeError("PDF rendering failed for sterilising check")
        pdf_bytes = buffer.getvalue()

    return apply_form_title_logo(pdf_bytes)
