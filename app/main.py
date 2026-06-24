import uuid
import aiofiles
from pathlib import Path
from datetime import datetime, date
from typing import Annotated

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.api import api_router
from app.models import (
    Batch, BatchHeader, FormInstance, Reading, UploadedDocument,
    Compilation, Operator, BatchStatus, FormStatus, FormType as ModelFormType,
    AccrualMode as ModelAccrualMode, DocumentSlot
)
from app.forms import FormType, AccrualMode, FORM_TEMPLATES, get_form_template
from app.services.compilation import compile_batch
from app.services.form_persistence import (
    add_reading as persist_reading,
    build_pick_list_lines,
    save_atomic_form as persist_atomic_form,
    save_form_header as persist_form_header,
    submit_accrual_form,
)
from app.services.work_order_parser import parse_work_order_pdf, filter_label_lines

settings = get_settings()

app = FastAPI(
    title="Berton Bottling Run Intake",
    description="Bottling Run Intake & Compilation App for Berton Vineyards",
    version="0.1.0",
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))
templates.env.globals["debug"] = settings.debug

# Ensure upload directory exists
upload_path = Path(settings.upload_dir)
upload_path.mkdir(exist_ok=True)

# Include API routes
app.include_router(api_router, prefix="/api")

def build_inherited_values(batch: Batch) -> dict:
    """Build inherited field values from batch header for form pre-fill."""
    header = batch.header
    return {
        "date": header.run_date.isoformat() if header and header.run_date else "",
        "run_number": batch.run_number,
        "product": (header.product if header else "") or "",
        "wine": (header.product if header else "") or "",
        "tank": (header.tank if header else "") or "",
        "stock_item": (header.stock_item if header else "") or "",
        "packing_unit": (header.packing_unit if header else "") or "",
        "packaging_line": (header.packaging_line if header else "") or "",
        "run_date": header.run_date.isoformat() if header and header.run_date else "",
        "run_quantity": header.run_quantity if header else "",
        "description": (header.product if header else "") or "",
    }


def build_form_defaults(form_type: str) -> dict:
    """Operator-entered defaults (e.g. today's date on daily production)."""
    if form_type == "daily_production":
        return {"date": date.today().isoformat()}
    return {}


def build_form_payload(form_data, exclude: set[str] | None = None) -> dict:
    """Build a JSON payload from form data, handling multi-value fields."""
    exclude = exclude or set()
    payload: dict = {}
    multi_value_fields: dict[str, list] = {}

    for key, value in form_data.items():
        if key in exclude:
            continue
        if key.endswith("[]"):
            field_key = key[:-2]
            if field_key not in multi_value_fields:
                multi_value_fields[field_key] = []
            if value is not None and str(value).strip():
                multi_value_fields[field_key].append(value)
        else:
            payload[key] = value if value else None

    for key, values in multi_value_fields.items():
        payload[key] = values if values else None

    return payload


async def save_uploaded_file(
    batch_id: uuid.UUID,
    slot: DocumentSlot,
    file: UploadFile,
    sequence: int = 0,
    uploaded_by: str = "Manager",
) -> UploadedDocument:
    """Save an uploaded file to disk and return the document record."""
    file_ext = Path(file.filename or "file.pdf").suffix or ".pdf"
    stored_filename = f"{batch_id}_{slot.value}_{sequence}{file_ext}"
    stored_path = upload_path / stored_filename

    async with aiofiles.open(stored_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    return UploadedDocument(
        batch_id=batch_id,
        slot=slot,
        sequence=sequence,
        original_filename=file.filename or stored_filename,
        stored_path=str(stored_path),
        uploaded_by=uploaded_by,
    )


# Form type display names
FORM_DISPLAY_NAMES = {
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


@app.get("/")
async def index(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the main dashboard."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .order_by(Batch.created_at.desc())
        .limit(100)
    )
    batches = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "batches": batches,
            "total": len(batches),
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ============== BATCH ROUTES ==============

@app.get("/batches/new")
async def new_batch_form(request: Request):
    """Show the new batch creation form."""
    return templates.TemplateResponse(
        request,
        "batches/new.html",
    )


@app.post("/batches/new")
async def create_batch(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    run_number: str = Form(...),
    work_order: UploadFile = File(...),
    label_references: list[UploadFile] = File(default=[]),
):
    """Create a new batch from work order upload and optional label references."""
    run_number = run_number.strip()
    if not run_number:
        return templates.TemplateResponse(
            request,
            "batches/new.html",
            {"error": "Please enter a run number."},
            status_code=400,
        )

    if not work_order.filename or not work_order.filename.lower().endswith(".pdf"):
        return templates.TemplateResponse(
            request,
            "batches/new.html",
            {"error": "Please upload a PDF work order."},
            status_code=400,
        )

    existing = await db.execute(
        select(Batch).where(Batch.run_number == run_number)
    )
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request,
            "batches/new.html",
            {"error": f"Run {run_number} already exists. Open it from the dashboard."},
            status_code=400,
        )

    batch = Batch(run_number=run_number, created_by="Manager")
    db.add(batch)
    await db.flush()

    work_order_doc = await save_uploaded_file(
        batch.id, DocumentSlot.WORK_ORDER, work_order
    )
    db.add(work_order_doc)

    parsed = parse_work_order_pdf(work_order_doc.stored_path)
    header = BatchHeader(
        batch=batch,
        product=parsed.get("product"),
        stock_item=parsed.get("stock_item"),
        tank=parsed.get("tank"),
        run_date=parsed.get("run_date"),
        packing_unit=parsed.get("packing_unit"),
        packaging_line=parsed.get("packaging_line"),
        run_quantity=parsed.get("run_quantity"),
        pick_list_lines=filter_label_lines(parsed.get("pick_list_lines")),
        extra={"parse_note": parsed.get("parse_note")} if parsed.get("parse_note") else None,
    )
    db.add(header)

    for sequence, label_file in enumerate(label_references):
        if not label_file.filename:
            continue
        if not label_file.filename.lower().endswith(".pdf"):
            continue
        label_doc = await save_uploaded_file(
            batch.id, DocumentSlot.LABEL_REFERENCE, label_file, sequence=sequence
        )
        db.add(label_doc)

    await db.commit()

    return RedirectResponse(url=f"/batches/{batch.id}", status_code=303)


@app.get("/batches/{batch_id}")
async def batch_detail(
    request: Request,
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Show batch detail page."""
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.form_instances).selectinload(FormInstance.readings),
            selectinload(Batch.compilations),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Build form status
    form_status = {}
    form_instances_map = {fi.form_type.value: fi for fi in batch.form_instances}

    for form_type in FormType:
        template = get_form_template(form_type)
        fi = form_instances_map.get(form_type.value)
        form_status[form_type.value] = {
            "label": FORM_DISPLAY_NAMES.get(form_type.value, form_type.value),
            "doc_number": template.doc_number,
            "status": fi.status.value if fi else "not_started",
            "reading_count": len(fi.readings) if fi else 0,
        }

    current_compilation = next(
        (c for c in batch.compilations if c.is_current), None
    )

    work_order = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.WORK_ORDER),
        None,
    )
    label_references = sorted(
        [d for d in batch.uploaded_documents if d.slot == DocumentSlot.LABEL_REFERENCE],
        key=lambda d: d.sequence,
    )
    ezywine_listing = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.EZYWINE_LISTING),
        None,
    )

    return templates.TemplateResponse(
        request,
        "batches/detail.html",
        {
            "batch": batch,
            "uploads": batch.uploaded_documents,
            "work_order": work_order,
            "label_references": label_references,
            "ezywine_listing": ezywine_listing,
            "form_status": form_status,
            "current_compilation": current_compilation,
        },
    )


@app.post("/batches/{batch_id}/upload")
async def upload_document(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    slot: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a document for a batch."""
    # Get batch
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.is_locked:
        raise HTTPException(status_code=400, detail="Batch is locked")

    # Determine sequence for label references
    sequence = 0
    if slot == "label_reference":
        count_result = await db.execute(
            select(func.count(UploadedDocument.id))
            .where(UploadedDocument.batch_id == batch_id)
            .where(UploadedDocument.slot == DocumentSlot.LABEL_REFERENCE)
        )
        sequence = count_result.scalar_one() or 0

    doc = await save_uploaded_file(
        batch_id, DocumentSlot(slot), file, sequence=sequence
    )
    db.add(doc)
    await db.commit()

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


# ============== FORM ROUTES ==============

@app.get("/batches/{batch_id}/forms/{form_type}")
async def form_view(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """View/edit a form for a batch."""
    # Get batch with form instance
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get form template
    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    # Get or create form instance
    fi_result = await db.execute(
        select(FormInstance)
        .options(selectinload(FormInstance.readings))
        .where(FormInstance.batch_id == batch_id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()

    # Get operators for accrual forms
    op_result = await db.execute(select(Operator).order_by(Operator.name))
    operators = op_result.scalars().all()

    inherited_values = build_inherited_values(batch)
    form_defaults = build_form_defaults(form_type)

    pick_list_lines: list = []
    if form_instance and form_instance.header_payload and form_instance.header_payload.get("lines"):
        pick_list_lines = filter_label_lines(form_instance.header_payload["lines"])
    elif batch.header and batch.header.pick_list_lines:
        pick_list_lines = filter_label_lines(batch.header.pick_list_lines)
    elif form_type == "pick_list":
        wo_result = await db.execute(
            select(UploadedDocument)
            .where(UploadedDocument.batch_id == batch_id)
            .where(UploadedDocument.slot == DocumentSlot.WORK_ORDER)
        )
        work_order_doc = wo_result.scalar_one_or_none()
        if work_order_doc:
            parsed = parse_work_order_pdf(work_order_doc.stored_path)
            pick_list_lines = filter_label_lines(parsed.get("pick_list_lines") or [])

    return templates.TemplateResponse(
        request,
        "batches/form.html",
        {
            "batch": batch,
            "form_template": form_template,
            "form_instance": form_instance,
            "readings": sorted(form_instance.readings, key=lambda r: r.sequence) if form_instance else [],
            "operators": operators,
            "inherited_values": inherited_values,
            "form_defaults": form_defaults,
            "pick_list_lines": pick_list_lines,
            "now": datetime.now(),
        },
    )


@app.post("/batches/{batch_id}/forms/{form_type}")
async def save_atomic_form(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Save an atomic form."""
    # Get batch
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.is_locked:
        raise HTTPException(status_code=400, detail="Batch is locked")

    form_data = await request.form()
    action = form_data.get("action", "save")

    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    payload = build_form_payload(form_data, exclude={"action"})

    if form_type == "pick_list":
        lines = build_pick_list_lines(dict(form_data))
        if lines:
            payload["lines"] = lines

    try:
        await persist_atomic_form(db, batch, form_type, payload, action=action)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save form: {e}")

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


@app.post("/batches/{batch_id}/forms/{form_type}/readings")
async def add_reading(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a reading to an accrual form."""
    # Get batch
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.is_locked:
        raise HTTPException(status_code=400, detail="Batch is locked")

    # Get form template
    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    form_data = await request.form()
    payload = build_form_payload(
        form_data,
        exclude={"operator_identifier", "captured_at", "action"},
    )

    try:
        await persist_reading(
            db,
            batch,
            form_type,
            operator_identifier=form_data.get("operator_identifier", "Unknown"),
            captured_at=form_data.get("captured_at", ""),
            payload=payload,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add reading: {e}")

    return RedirectResponse(
        url=f"/batches/{batch_id}/forms/{form_type}",
        status_code=303,
    )


@app.post("/batches/{batch_id}/forms/{form_type}/header")
async def save_form_header(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Save header fields on an accrual form (e.g. manufacturer, bottle code)."""
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.is_locked:
        raise HTTPException(status_code=400, detail="Batch is locked")

    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    form_data = await request.form()
    payload = build_form_payload(form_data, exclude={"action"})

    try:
        await persist_form_header(db, batch, form_type, payload)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save header: {e}")

    return RedirectResponse(
        url=f"/batches/{batch_id}/forms/{form_type}",
        status_code=303,
    )


@app.post("/batches/{batch_id}/forms/{form_type}/submit")
async def submit_form(
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Submit an accrual form."""
    try:
        await submit_accrual_form(db, batch_id, form_type)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit form: {e}")

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


# ============== COMPILE ROUTES ==============

@app.post("/batches/{batch_id}/compile")
async def compile_batch_route(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Compile batch into PDF."""
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.form_instances).selectinload(FormInstance.readings),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.is_locked:
        raise HTTPException(status_code=400, detail="Batch is already compiled")

    # Compile
    try:
        compilation = await compile_batch(batch, db, settings.upload_dir)
        db.add(compilation)

        # Lock batch
        batch.is_locked = True
        batch.status = BatchStatus.COMPILED

        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


@app.post("/batches/{batch_id}/reopen")
async def reopen_batch(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reopen a compiled batch."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.compilations))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Mark current compilation as not current
    for comp in batch.compilations:
        if comp.is_current:
            comp.is_current = False

    # Unlock batch
    batch.is_locked = False
    batch.status = BatchStatus.REOPENED

    await db.commit()

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


@app.get("/uploads/{doc_id}/view")
async def view_upload(
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """View an uploaded PDF inline (for embedding in the page)."""
    result = await db.execute(
        select(UploadedDocument).where(UploadedDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return FileResponse(
        doc.stored_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"'},
    )


@app.get("/api/uploads/{doc_id}/download")
async def download_upload(
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download an uploaded document."""
    result = await db.execute(
        select(UploadedDocument).where(UploadedDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return FileResponse(
        doc.stored_path,
        filename=doc.original_filename,
        media_type="application/pdf",
    )


@app.get("/api/compilations/{compilation_id}/download")
async def download_compilation(
    compilation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download a compiled PDF."""
    result = await db.execute(
        select(Compilation).where(Compilation.id == compilation_id)
    )
    compilation = result.scalar_one_or_none()
    if not compilation:
        raise HTTPException(status_code=404, detail="Compilation not found")

    return FileResponse(
        compilation.stored_path,
        filename=compilation.output_filename,
        media_type="application/pdf",
    )


# ============== DEV: COMPILE TEST RUN ==============

if settings.debug:
    from app.services.seed_test_run import TEST_RUN_NUMBER, create_compile_test_run

    @app.get("/dev/test-run")
    async def dev_test_run_page(
        request: Request,
        db: Annotated[AsyncSession, Depends(get_db)],
    ):
        """Test page with a fully-populated run for compile testing."""
        result = await db.execute(
            select(Batch).where(Batch.run_number == TEST_RUN_NUMBER)
        )
        batch = result.scalar_one_or_none()
        message = None
        if request.query_params.get("created"):
            message = "Test run created successfully. Open it below and use Manager Tools to compile."

        return templates.TemplateResponse(
            request,
            "dev/test_run.html",
            {
                "batch": batch,
                "test_run_number": TEST_RUN_NUMBER,
                "message": message,
                "error": None,
            },
        )

    @app.post("/dev/test-run/seed")
    async def dev_test_run_seed(
        db: Annotated[AsyncSession, Depends(get_db)],
    ):
        """Create or replace the compile test run."""
        try:
            await create_compile_test_run(db, settings.upload_dir)
        except Exception as e:
            return RedirectResponse(
                url=f"/dev/test-run?error={e}",
                status_code=303,
            )
        return RedirectResponse(url="/dev/test-run?created=1", status_code=303)


# ============== OPERATOR ROUTES ==============

@app.get("/operators")
async def operators_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Show operators management page."""
    result = await db.execute(select(Operator).order_by(Operator.name))
    operators = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "operators/index.html",
        {"operators": operators},
    )


@app.post("/operators")
async def create_operator(
    db: Annotated[AsyncSession, Depends(get_db)],
    name: str = Form(...),
    initials: str = Form(...),
):
    """Create a new operator."""
    operator = Operator(name=name, initials=initials.upper())
    db.add(operator)
    await db.commit()

    return RedirectResponse(url="/operators", status_code=303)
