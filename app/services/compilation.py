import re
import shutil
from pathlib import Path
from datetime import datetime
from io import BytesIO

from jinja2 import Environment, FileSystemLoader
from pypdf import PdfWriter, PdfReader

from app.models import Batch, Compilation, FormInstance, UploadedDocument, DocumentSlot
from app.forms import FormType, FORM_TEMPLATES, get_form_template


# 16-slot compile template from spec
COMPILE_SLOTS = [
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
}


def sanitize_filename(name: str) -> str:
    """Remove filesystem-illegal characters."""
    return re.sub(r'[<>:"/\\|?*]', '', name)


def save_compiled_to_server_folder(
    source_path: Path,
    output_filename: str,
    compiled_output_dir: str,
) -> str:
    """Copy the compiled PDF to the local server folder for archival."""
    dest_dir = Path(compiled_output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / output_filename
    shutil.copy2(source_path, dest_path)
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
    env = Environment(loader=FileSystemLoader(str(templates_path)))

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

    for slot_def in COMPILE_SLOTS:
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
                    reader = PdfReader(doc.stored_path)
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
                    reader = PdfReader(doc.stored_path)
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

    # Write final PDF
    upload_path = Path(upload_dir)
    output_path = upload_path / f"compiled_{batch.id}.pdf"

    with open(output_path, "wb") as f:
        pdf_writer.write(f)

    server_path = None
    if compiled_output_dir:
        server_path = save_compiled_to_server_folder(
            output_path, output_filename, compiled_output_dir
        )

    # Create compilation record
    compilation = Compilation(
        batch_id=batch.id,
        output_filename=output_filename,
        stored_path=str(output_path),
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

    # Build context
    header = batch.header
    context = {
        "batch": batch,
        "header": header,
        "form_instance": form_instance,
        "form_template": form_template,
        "form_name": FORM_NAMES.get(form_template.form_type.value, form_template.form_type.value),
        "doc_number": form_template.doc_number,
        "readings": form_instance.readings if form_instance else [],
        "header_payload": form_instance.header_payload if form_instance else {},
        "orientation": orientation,
        "now": datetime.now(),
    }

    # Try to load specific template, fall back to generic
    template_name = f"{form_template.form_type.value}.html"
    try:
        template = env.get_template(template_name)
    except Exception:
        template = env.get_template("generic_form.html")

    html_content = template.render(**context)

    # CSS for orientation
    css_content = f"""
        @page {{
            size: A4 {orientation};
            margin: 1cm;
        }}
        body {{
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
        .header-box {{
            border: 2px solid #000;
            padding: 10px;
            margin-bottom: 15px;
        }}
        .form-title {{
            font-size: 14pt;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .doc-number {{
            font-size: 9pt;
            color: #666;
        }}
    """

    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css_content}</style></head>
<body>{html_content}</body></html>"""

    # Prefer WeasyPrint; fall back to xhtml2pdf (pure Python, works on Windows).
    try:
        from weasyprint import CSS, HTML

        html = HTML(string=full_html)
        css = CSS(string=css_content)
        return html.write_pdf(stylesheets=[css])
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
        raise RuntimeError("PDF rendering failed while generating a form page.")
    return buffer.getvalue()
