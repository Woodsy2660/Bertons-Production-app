import base64
import re
import shutil
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from io import BytesIO

from jinja2 import Environment, FileSystemLoader
from pypdf import PdfWriter, PdfReader

from app.models import Batch, Compilation, FormInstance, UploadedDocument, DocumentSlot
from app.forms import FormType, FORM_TEMPLATES, get_form_template
from app.services.storage import build_compilation_path, read_bytes, save_bytes

_STATIC_IMG = Path(__file__).resolve().parent.parent / "static" / "img"
# Docker image may mount static under /app/static; prefer in-tree then container paths.
_LOGO_CANDIDATES: list[tuple[Path, str]] = [
    # Prefer dedicated print/PDF raster assets (PyMuPDF stamp on form title page).
    (_STATIC_IMG / "berton-logo-pdf.png", "image/png"),
    (_STATIC_IMG / "berton_logo.png", "image/png"),
    (Path("/app/static/img/berton-logo-pdf.png"), "image/png"),
    (Path("/app/static/img/berton_logo.png"), "image/png"),
    (Path("/app/static/berton_logo.png"), "image/png"),
    (_STATIC_IMG / "berton-logo-print.jpg", "image/jpeg"),
    (_STATIC_IMG / "berton-logo.jpg", "image/jpeg"),
    (_STATIC_IMG / "berton-logo-black.svg", "image/svg+xml"),
]


@lru_cache(maxsize=1)
def pdf_logo_path() -> Path | None:
    """Filesystem path to the preferred logo asset (PNG/SVG first)."""
    for path, _media in _LOGO_CANDIDATES:
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def pdf_logo_data_uri() -> str:
    """Base64 data URI for WeasyPrint form templates.

    Computed once (lru_cache) at first use / process lifetime — not per render —
    so the container has no relative-path dependency at HTML→PDF time.
    """
    for path, media_type in _LOGO_CANDIDATES:
        if path.is_file():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{media_type};base64,{encoded}"
    return ""


# Module-level constant for template context (`logo_src`).
_LOGO_SRC: str = pdf_logo_data_uri()


# Logo height in print millimetres (title page of each form only).
_LOGO_HEIGHT_MM = 10.0
# Distance from the physical page edges to the logo box.
_LOGO_TOP_MM = 5.0
_LOGO_RIGHT_MM = 8.0


def _logo_draw_size_pt() -> tuple[float, float]:
    """Return (width_pt, height_pt) for the brand logo at _LOGO_HEIGHT_MM."""
    mm = 72.0 / 25.4
    logo_h = _LOGO_HEIGHT_MM * mm
    logo = pdf_logo_path()
    aspect = 2.08
    if logo:
        try:
            from PIL import Image

            with Image.open(logo) as im:
                aspect = im.width / max(im.height, 1)
        except Exception:
            pass
    return logo_h * aspect, logo_h


def _title_aligned_logo_rect(page) -> "fitz.Rect":
    """Logo box (see _LOGO_HEIGHT_MM): page top-right, aligned with the form title."""
    import fitz

    mm = 72.0 / 25.4
    logo_w, logo_h = _logo_draw_size_pt()
    r = page.rect

    # Default: fixed inset from the physical top-right corner.
    y1 = r.y0 + (_LOGO_TOP_MM * mm)

    # Prefer vertical alignment with the first title line near the top of the page.
    try:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans") or []
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                bb = line.get("bbox")
                if not bb:
                    continue
                # Title band is in the upper content area (below page margin).
                if bb[1] < r.y0 + 90:
                    title_cy = (bb[1] + bb[3]) / 2.0
                    y1 = title_cy - (logo_h / 2.0)
                    break
            else:
                continue
            break
    except Exception:
        pass

    # Clamp so the logo stays fully on-page.
    y1 = max(r.y0 + (2.0 * mm), min(y1, r.y1 - logo_h - (2.0 * mm)))
    x2 = r.x1 - (_LOGO_RIGHT_MM * mm)
    x1 = x2 - logo_w
    y2 = y1 + logo_h
    return fitz.Rect(x1, y1, x2, y2)


def apply_form_title_logo(pdf_bytes: bytes) -> bytes:
    """Place a Berton logo top-right on page 1 only of a station-form PDF.

    Only used for app form renders — never for uploaded/imported PDFs.
    Size is ``_LOGO_HEIGHT_MM``. Strips embedded images then stamps page 0 only.
    """
    import logging

    log = logging.getLogger(__name__)
    logo = pdf_logo_path()
    if not logo or not pdf_bytes:
        if not logo:
            log.warning("Form title logo skipped: no logo file found under static/img")
        return pdf_bytes

    try:
        import fitz  # PyMuPDF — required for exact mm placement (not in CSS)
    except ImportError:
        log.error(
            "Form title logo skipped: PyMuPDF (fitz) is not installed. "
            "Install pymupdf so station forms get the top-right brand mark."
        )
        return pdf_bytes

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        # Remove engine-embedded logos from every page (prevents page-2 bleed).
        for page in doc:
            xrefs = {img[0] for img in page.get_images(full=True)}
            for xref in xrefs:
                try:
                    page.delete_image(xref)
                except Exception:
                    pass
            leftovers = []
            try:
                for info in page.get_image_info():
                    bbox = info.get("bbox")
                    if bbox:
                        leftovers.append(fitz.Rect(bbox))
            except Exception:
                pass
            if leftovers:
                for rect in leftovers:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

        page0 = doc[0]
        page0.insert_image(
            _title_aligned_logo_rect(page0),
            filename=str(logo),
            keep_proportion=False,
            overlay=True,
        )
        return doc.tobytes(deflate=True, garbage=3)
    except Exception:
        log.exception("Form title logo stamp failed")
        return pdf_bytes
    finally:
        doc.close()


# Pallet tags only — do not use for uploaded compile slots.
def stamp_berton_logo_on_pdf(pdf_bytes: bytes) -> bytes:
    """Stamp logo on page 1 only (pallet tags / non-compile helpers)."""
    return apply_form_title_logo(pdf_bytes)







# Bottling: fixed 16-slot-style pack (existing). Unchanged for bottling runs.
BOTTLING_COMPILE_SLOTS = [
    {"slot": 1, "source": "upload", "ref": "ezywine_listing", "orientation": "portrait"},
    {"slot": 2, "source": "app_form", "form_type": "daily_production", "orientation": "portrait"},
    {"slot": 3, "source": "app_form", "form_type": "filler_line_check", "orientation": "landscape"},
    {"slot": 4, "source": "app_form", "form_type": "bottle_sealing", "orientation": "landscape"},
    {"slot": 5, "source": "upload", "ref": "work_order", "orientation": "portrait"},
    {"slot": 6, "source": "app_form", "form_type": "label_usage", "orientation": "portrait"},
    {"slot": 7, "source": "app_form", "form_type": "finished_product_line_check", "orientation": "landscape"},
    {"slot": 8, "source": "app_form", "form_type": "pick_list", "orientation": "portrait"},
    {"slot": 9, "source": "upload_group", "ref": "label_reference", "orientation": "as_uploaded"},
    {"slot": 10, "source": "app_form", "form_type": "carton_qc", "orientation": "landscape"},
    {"slot": 11, "source": "app_form", "form_type": "final_pallet_count", "orientation": "portrait"},
    {"slot": 12, "source": "app_form", "form_type": "finished_product_pallet", "orientation": "portrait"},
]

# Cask: dedicated slot manifest (not forced into bottling 16-slot layout).
# Order: EzyWine listing → work order → label refs → four cask station forms.
CASK_COMPILE_SLOTS = [
    {"slot": 1, "source": "upload", "ref": "ezywine_listing", "orientation": "portrait"},
    {"slot": 2, "source": "upload", "ref": "work_order", "orientation": "portrait"},
    {"slot": 3, "source": "upload_group", "ref": "label_reference", "orientation": "as_uploaded"},
    {"slot": 4, "source": "app_form", "form_type": "cask_final_pallet_count", "orientation": "portrait"},
    {"slot": 5, "source": "app_form", "form_type": "cask_line_check", "orientation": "landscape"},
    {"slot": 6, "source": "app_form", "form_type": "cask_production_waste", "orientation": "portrait"},
    {"slot": 7, "source": "app_form", "form_type": "cask_tank_dip", "orientation": "portrait"},
]

# Back-compat alias
COMPILE_SLOTS = BOTTLING_COMPILE_SLOTS


def compile_slots_for_batch(batch) -> list[dict]:
    line = getattr(batch, "line_type", None)
    line_val = line.value if hasattr(line, "value") else (line or "bottling")
    if str(line_val).lower() == "cask":
        return CASK_COMPILE_SLOTS
    return BOTTLING_COMPILE_SLOTS


# Form display names
FORM_NAMES = {
    "daily_production": "Daily Production Sheet",
    "filler_line_check": "Filler Line Check",
    "bottle_sealing": "Bottle Sealing Usage Log",
    "label_usage": "Label Usage Sheet",
    "finished_product_line_check": "Finished Product Line Check",
    "pick_list": "Label Pick List",
    "carton_qc": "Carton Usage & Quality Control",
    "final_pallet_count": "Final Pallet Count Sheet",
    "finished_product_pallet": "Finished Product / Warehouse Pallet Count",
    "cask_final_pallet_count": "Cask Final Pallet Count",
    "cask_line_check": "Cask Line Check Sheet",
    "cask_production_waste": "Cask Line Production Waste",
    "cask_tank_dip": "Cask Line Tank Dip Sheet",
}


def sanitize_filename(name: str) -> str:
    """Remove filesystem-illegal characters."""
    return re.sub(r'[<>:"/\\|?*]', '', name)


def save_compiled_to_server_folder(
    source_path: Path,
    output_filename: str,
    compiled_output_dir: str,
) -> str:
    """Copy the compiled PDF to the local server folder for archival.

    Uses content-only copy (not copy2). Docker Desktop Windows bind mounts
    often reject utime/chmod from copy2 with PermissionError [Errno 1]
    Operation not permitted, which previously failed the whole compile.
    """
    dest_dir = Path(compiled_output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / output_filename
    # copyfile = data only; avoids copystat (timestamps/mode) on restricted mounts
    try:
        shutil.copyfile(source_path, dest_path)
    except OSError:
        dest_path.write_bytes(source_path.read_bytes())
    return str(dest_path)


async def compile_batch(
    batch: Batch,
    db,
    upload_dir: str,
    *,
    compiled_output_dir: str | None = None,
    compiled_by: str = "Manager",
) -> Compilation:
    """
    Compile a batch into a single PDF document.

    Walks the 16-slot template, rendering app forms and merging with uploads.
    """
    templates_path = Path(__file__).parent.parent / "templates" / "pdf"
    # Autoescape HTML so operator/extracted text is literal in PDF templates (TEST-S1).
    env = Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=True,
    )

    # Build form instances map
    form_instances_map = {fi.form_type.value: fi for fi in batch.form_instances}

    # Build uploads map
    uploads_map = {}
    for doc in batch.uploaded_documents:
        slot_key = doc.slot.value
        if slot_key not in uploads_map:
            uploads_map[slot_key] = []
        uploads_map[slot_key].append(doc)

    # Sort label references by sequence
    if "label_reference" in uploads_map:
        uploads_map["label_reference"].sort(key=lambda x: x.sequence)

    # Build slot manifest for audit
    slot_manifest = {}

    # Collect all PDF pages
    pdf_writer = PdfWriter()

    for slot_def in compile_slots_for_batch(batch):
        slot_num = slot_def["slot"]
        source = slot_def["source"]

        if source == "app_form":
            form_type = slot_def["form_type"]
            orientation = slot_def["orientation"]

            # Render form to PDF
            form_instance = form_instances_map.get(form_type)
            form_template = get_form_template(FormType(form_type))

            pdf_bytes = render_form_to_pdf(
                env, batch, form_instance, form_template, orientation
            )

            # Add to writer
            if pdf_bytes:
                reader = PdfReader(BytesIO(pdf_bytes))
                for page in reader.pages:
                    pdf_writer.add_page(page)
                slot_manifest[f"slot_{slot_num}"] = {
                    "type": "app_form",
                    "form_type": form_type,
                    "pages": len(reader.pages),
                }
            else:
                slot_manifest[f"slot_{slot_num}"] = {"type": "app_form", "form_type": form_type, "empty": True}

        elif source == "upload":
            ref = slot_def["ref"]
            docs = uploads_map.get(ref, [])

            if docs:
                doc = docs[0]  # Single upload slot
                try:
                    # Uploaded PDFs are included as-is — no Berton logo overlay.
                    raw = await read_bytes(doc.stored_path)
                    reader = PdfReader(BytesIO(raw))
                    for page in reader.pages:
                        pdf_writer.add_page(page)
                    slot_manifest[f"slot_{slot_num}"] = {
                        "type": "upload",
                        "ref": ref,
                        "filename": doc.original_filename,
                        "pages": len(reader.pages),
                    }
                except Exception as e:
                    slot_manifest[f"slot_{slot_num}"] = {"type": "upload", "ref": ref, "error": str(e)}
            else:
                slot_manifest[f"slot_{slot_num}"] = {"type": "upload", "ref": ref, "missing": True}

        elif source == "upload_group":
            ref = slot_def["ref"]
            docs = uploads_map.get(ref, [])

            total_pages = 0
            filenames = []
            for doc in docs:
                try:
                    # Uploaded PDFs are included as-is — no Berton logo overlay.
                    raw = await read_bytes(doc.stored_path)
                    reader = PdfReader(BytesIO(raw))
                    for page in reader.pages:
                        pdf_writer.add_page(page)
                    total_pages += len(reader.pages)
                    filenames.append(doc.original_filename)
                except Exception:
                    pass

            slot_manifest[f"slot_{slot_num}"] = {
                "type": "upload_group",
                "ref": ref,
                "count": len(docs),
                "pages": total_pages,
                "filenames": filenames,
            }

    # Generate output filename
    header = batch.header
    stock_item = header.stock_item if header else ""
    product = header.product if header else ""
    output_filename = sanitize_filename(f"{batch.run_number} {stock_item} {product}.pdf")

    output_buffer = BytesIO()
    pdf_writer.write(output_buffer)
    output_bytes = output_buffer.getvalue()

    output_key = await build_compilation_path(batch.id)
    stored_path = await save_bytes(output_key, output_bytes)

    server_path = None
    if compiled_output_dir:
        temp_path = Path(compiled_output_dir) / f"compiled_{batch.id}.pdf"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(output_bytes)
        server_path = save_compiled_to_server_folder(
            temp_path, output_filename, compiled_output_dir
        )

    # Create compilation record
    compilation = Compilation(
        batch_id=batch.id,
        output_filename=output_filename,
        stored_path=stored_path,
        slot_manifest={
            **slot_manifest,
            "server_folder_path": server_path,
        },
        is_current=True,
        compiled_by=compiled_by,
        compiled_at=datetime.utcnow(),
    )

    return compilation


def render_form_to_pdf(
    env: Environment,
    batch: Batch,
    form_instance: FormInstance | None,
    form_template,
    orientation: str,
) -> bytes | None:
    """Render a form to PDF using WeasyPrint."""

    # Build context — never pass None for dicts templates call .get() on.
    # Partial runs often have FormInstance rows with header_payload NULL.
    header = batch.header
    raw_header = (form_instance.header_payload if form_instance else None) or {}
    if not isinstance(raw_header, dict):
        raw_header = {}
    readings = list(form_instance.readings) if form_instance else []
    # Guard reading payloads for templates that call payload.get(...)
    for reading in readings:
        if getattr(reading, "payload", None) is None:
            reading.payload = {}

    form_name = FORM_NAMES.get(
        form_template.form_type.value, form_template.form_type.value
    )
    # logo_src is a data URI computed once at module load (no path at render time).
    context = {
        "batch": batch,
        "header": header,
        "form_instance": form_instance,
        "form_template": form_template,
        "form_name": form_name,
        "doc_number": form_template.doc_number or "",
        "readings": readings,
        "header_payload": raw_header,
        "orientation": orientation,
        "logo_src": _LOGO_SRC,
        "logo_data_uri": _LOGO_SRC,
        "now": datetime.now(),
    }

    # Try to load specific template, fall back to generic
    template_name = f"{form_template.form_type.value}.html"
    try:
        template = env.get_template(template_name)
    except Exception:
        template = env.get_template("generic_form.html")

    html_content = template.render(**context)

    # Form HTML has no logo image. Engines ignore/mis-size CSS height and
    # position:fixed paints over readings on page 2+. Logo is applied after
    # render via apply_form_title_logo: page 1 only, exact mm height, top-right.
    # Each form is its own PDF then merged — page 1 of that PDF = section title page.
    css_content = f"""
        @page {{
            size: A4 {orientation};
            margin: 1cm;
        }}
        html, body {{
            font-family: Arial, sans-serif;
            font-size: 10pt;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            border: 1px solid #333;
            padding: 4px 6px;
            text-align: left;
        }}
        th {{
            background-color: #f0f0f0;
        }}
        .header-box, .pdf-page-header {{
            border: none;
            border-bottom: 1.5pt solid #000;
            padding: 2px 0 8px 0;
            margin: 0 0 12px 0;
            /* Leave clear top-right band for the page-1 logo stamp */
            padding-right: 32mm;
            min-height: 12mm;
        }}
        .form-title {{
            font-size: 13pt;
            font-weight: bold;
            margin: 0 0 2px 0;
            color: #000;
            line-height: 1.2;
        }}
        .doc-number {{
            font-size: 9pt;
            color: #444;
            margin: 0;
        }}
        .pdf-brand-table {{
            width: 100%;
            border: none !important;
            border-collapse: collapse;
        }}
        .pdf-brand-table td {{
            border: none !important;
            padding: 0 !important;
            background: transparent !important;
        }}
        .pdf-brand-title-cell {{
            width: 100%;
            vertical-align: top;
            text-align: left;
        }}
        /* Never emit a logo from HTML — size/placement is post-render only */
        .page-logo, img.page-logo {{
            display: none !important;
        }}
    """

    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css_content}</style></head>
<body>
{html_content}
</body></html>"""

    pdf_bytes: bytes | None = None
    try:
        from weasyprint import CSS, HTML

        html = HTML(string=full_html)
        css = CSS(string=css_content)
        pdf_bytes = html.write_pdf(stylesheets=[css])
    except (ImportError, OSError):
        pdf_bytes = None

    if pdf_bytes is None:
        try:
            from xhtml2pdf import pisa
        except ImportError as exc:
            raise RuntimeError(
                "PDF rendering unavailable. Install xhtml2pdf or WeasyPrint system libraries."
            ) from exc

        buffer = BytesIO()
        if pisa.CreatePDF(full_html, dest=buffer).err:
            raise RuntimeError("PDF rendering failed while generating a form page.")
        pdf_bytes = buffer.getvalue()

    # Exact 10mm logo, top-right, title page only — never on continuation pages.
    return apply_form_title_logo(pdf_bytes)
