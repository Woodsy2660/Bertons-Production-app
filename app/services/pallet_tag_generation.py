"""Generate EzyWine-format pallet tag PDFs (spec 11 §5)."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.models import Batch
from app.services.compilation import stamp_berton_logo_on_pdf
from app.services.form_prefill import extract_packing_size

# TODO: plug confirmed EzyWine tag dimensions / tags-per-sheet once D19 sample is available.
DEFAULT_TAGS_PER_SHEET = 1


def _render_html_to_pdf(html: str, css: str) -> bytes:
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body>{html}</body></html>"""
    try:
        from weasyprint import CSS, HTML

        return HTML(string=full_html).write_pdf(stylesheets=[CSS(string=css)])
    except (ImportError, OSError):
        pass
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError(
            "PDF rendering unavailable. Install xhtml2pdf or WeasyPrint system libraries."
        ) from exc
    buffer = BytesIO()
    if pisa.CreatePDF(full_html, dest=buffer).err:
        raise RuntimeError("Pallet tag PDF rendering failed.")
    return buffer.getvalue()


def build_tag_context(batch: Batch, printed_at: datetime | None = None) -> dict:
    header = batch.header
    printed_at = printed_at or datetime.now()
    return {
        "run_number": batch.run_number,
        "stock_code": header.stock_item if header else "",
        "product": header.product if header else "",
        "size": extract_packing_size(header.packing_unit if header else None),
        "print_date": printed_at.strftime("%d/%m/%y"),
        "print_time": printed_at.strftime("%H:%M"),
    }


def generate_pallet_tag_pdf(
    batch: Batch,
    tag_count: int,
    *,
    printed_at: datetime | None = None,
    tags_per_sheet: int | None = None,
) -> bytes:
    settings = get_settings()
    tags_per_sheet = tags_per_sheet or settings.pallet_tags_per_sheet
    printed_at = printed_at or datetime.now()
    tag_context = build_tag_context(batch, printed_at)
    tags = [tag_context for _ in range(max(tag_count, 0))]

    templates_path = Path(__file__).parent.parent / "templates" / "pdf"
    env = Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("pallet_tag.html")
    html = template.render(
        tags=tags,
        tags_per_sheet=tags_per_sheet,
    )

    css = """
    @page { size: A4 portrait; margin: 12mm; }
    body { font-family: Arial, sans-serif; font-size: 11pt; color: #111; }
    .tag-page { page-break-after: always; border: 2px solid #000; padding: 16px; min-height: 240mm; }
    .tag-page:last-child { page-break-after: auto; }
    .tag-header { display: table; width: 100%; margin-bottom: 12px; }
    .tag-header-left { display: table-cell; vertical-align: middle; }
    .tag-header-right { display: table-cell; text-align: right; vertical-align: middle; }
    .tag-title { font-size: 16pt; font-weight: bold; margin: 0; }
    .pdf-brand-logo { max-width: 140px; max-height: 48px; width: auto; height: auto; }
    .tag-grid { width: 100%; border-collapse: collapse; }
    .tag-grid th, .tag-grid td { border: 1px solid #333; padding: 8px 10px; text-align: left; vertical-align: top; }
    .tag-grid th { width: 34%; background: #f4f4f4; }
    .blank-field { min-height: 28px; }
    """
    return stamp_berton_logo_on_pdf(_render_html_to_pdf(html, css))