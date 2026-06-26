import uuid
from pathlib import Path
from datetime import datetime, date
from typing import Annotated

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.auth.credentials import verify_credentials
from app.auth.dependencies import (
    PUBLIC_PATHS,
    Role,
    get_current_role,
    require_manager,
    require_operator_or_manager,
)
from app.auth.session import clear_session, get_role_from_session, set_role_in_session
from app.config import get_settings
from app.database import get_db
from app.api import api_router
from app.models import (
    Batch, BatchHeader, FormInstance, Reading, UploadedDocument,
    Compilation, BatchStatus, FormStatus, FormType as ModelFormType,
    AccrualMode as ModelAccrualMode, DocumentSlot
)
from app.forms import FormType, AccrualMode, FORM_TEMPLATES, get_form_template
from app.services.batch_lifecycle import (
    assert_can_compile,
    assert_can_reopen,
    assert_can_upload,
    assert_can_write_forms,
    can_compile,
    can_mark_ready,
    can_reopen,
    can_upload_documents,
    can_write_forms,
    is_greyed_out,
    list_batches_for_role,
    mark_complete,
    reopen_run,
)
from app.services.document_management import (
    clear_single_slot_documents,
    delete_uploaded_document,
    get_batch_document,
    refresh_header_from_work_order,
    replace_document_content,
    validate_pdf_upload,
)
from app.services.compilation import compile_batch
from app.services.form_persistence import (
    add_reading as persist_reading,
    build_pick_list_lines,
    save_atomic_form as persist_atomic_form,
    save_form_header as persist_form_header,
    submit_accrual_form,
)
from app.services.storage import build_upload_path, read_bytes, save_bytes
from app.services.work_order_parser import parse_work_order_pdf, filter_label_lines

settings = get_settings()

app = FastAPI(
    title="Berton Bottling Run Intake",
    description="Bottling Run Intake & Compilation App for Berton Vineyards",
    version="0.1.0",
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    role = get_role_from_session(request.session)
    if role is None:
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        next_path = path
        if request.url.query:
            next_path = f"{path}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_path}", status_code=303)
    return await call_next(request)


# Register after auth middleware so SessionMiddleware wraps it on the outside
# (Starlette reverses middleware order when building the ASGI app).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.is_production,
    same_site="lax",
)


# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))
templates.env.globals["debug"] = settings.debug
templates.env.globals["get_role"] = lambda request: get_role_from_session(request.session)

# Ensure upload directory exists
upload_path = Path(settings.upload_dir)
upload_path.mkdir(exist_ok=True)
Path(settings.compiled_output_dir).mkdir(parents=True, exist_ok=True)

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
    """Save an uploaded file and return the document record."""
    file_ext = Path(file.filename or "file.pdf").suffix or ".pdf"
    stored_filename = f"{batch_id}_{slot.value}_{sequence}{file_ext}"
    content = await file.read()
    storage_key = await build_upload_path(batch_id, slot.value, sequence, file_ext)
    stored_path = await save_bytes(storage_key, content)

    return UploadedDocument(
        batch_id=batch_id,
        slot=slot,
        sequence=sequence,
        original_filename=file.filename or stored_filename,
        stored_path=stored_path,
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


@app.get("/login")
async def login_page(request: Request, error: str | None = None):
    """Shared-role login."""
    if get_role_from_session(request.session):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": error, "next": request.query_params.get("next", "/")},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    role = verify_credentials(username, password, settings)
    if not role:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username or password", "next": next},
            status_code=401,
        )
    set_role_in_session(request.session, role)
    dest = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(url=dest, status_code=303)


@app.post("/logout")
async def logout(request: Request):
    clear_session(request.session)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/")
async def index(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Render the main dashboard."""
    batches, review_queue = await list_batches_for_role(db, role, settings)
    review_ids = {b.id for b in review_queue}
    active_batches = [
        b for b in batches
        if b.status != BatchStatus.COMPLETE and b.id not in review_ids
    ]
    complete_batches = [b for b in batches if b.status == BatchStatus.COMPLETE]

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_batches": active_batches,
            "complete_batches": complete_batches,
            "review_queue": review_queue,
            "role": role,
            "review_count": len(review_queue),
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ============== BATCH ROUTES ==============

@app.get("/batches/new")
async def new_batch_form(
    request: Request,
    role: Annotated[Role, Depends(require_manager)],
):
    """Show the new batch creation form."""
    return templates.TemplateResponse(
        request,
        "batches/new.html",
        {"role": role},
    )


@app.post("/batches/new")
async def create_batch(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
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

    batch = Batch(
        run_number=run_number,
        created_by="Manager",
        status=BatchStatus.IN_PROGRESS,
    )
    db.add(batch)
    await db.flush()

    work_order_doc = await save_uploaded_file(
        batch.id, DocumentSlot.WORK_ORDER, work_order
    )
    db.add(work_order_doc)

    parsed = parse_work_order_pdf(await read_bytes(work_order_doc.stored_path))
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
    role: Annotated[Role, Depends(require_operator_or_manager)],
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

    stale_compilation = next(
        (c for c in batch.compilations if not c.is_current),
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
            "stale_compilation": stale_compilation,
            "role": role,
            "is_greyed": is_greyed_out(batch),
            "can_edit_forms": can_write_forms(batch, role),
            "can_manage_documents": can_upload_documents(batch, role),
            "can_mark_ready": can_mark_ready(batch, role),
            "can_reopen": can_reopen(batch, role),
        },
    )


@app.post("/batches/{batch_id}/mark-ready")
async def mark_ready(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
):
    """Manager gate: proceed to the dedicated completion page."""
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not can_mark_ready(batch, role):
        raise HTTPException(status_code=400, detail="Run is not ready for review completion")

    return RedirectResponse(url=f"/batches/{batch_id}/complete", status_code=303)


@app.get("/batches/{batch_id}/complete")
async def completion_page(
    request: Request,
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
):
    """Dedicated completion page: upload listing + label refs, compile, save."""
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.compilations),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not can_compile(batch, role):
        raise HTTPException(status_code=400, detail="Completion is not available for this run")

    ezywine_listing = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.EZYWINE_LISTING),
        None,
    )
    label_references = sorted(
        [d for d in batch.uploaded_documents if d.slot == DocumentSlot.LABEL_REFERENCE],
        key=lambda d: d.sequence,
    )
    current_compilation = next((c for c in batch.compilations if c.is_current), None)

    compile_error = request.query_params.get("error")

    return templates.TemplateResponse(
        request,
        "batches/complete.html",
        {
            "batch": batch,
            "ezywine_listing": ezywine_listing,
            "label_references": label_references,
            "current_compilation": current_compilation,
            "role": role,
            "can_manage_documents": can_upload_documents(batch, role),
            "is_recompile": batch.status == BatchStatus.REOPENED,
            "compile_error": compile_error,
        },
    )


def _safe_redirect(redirect_to: str, batch_id: uuid.UUID) -> str:
    if redirect_to.startswith("/") and not redirect_to.startswith("//"):
        return redirect_to
    return f"/batches/{batch_id}"


@app.post("/batches/{batch_id}/upload")
async def upload_document(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    slot: str = Form(...),
    file: UploadFile = File(...),
    redirect_to: str = Form(""),
):
    """Upload or replace a document for a batch (manager only)."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_upload(batch, role)

    try:
        validate_pdf_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_slot = DocumentSlot(slot)
    sequence = 0

    if doc_slot in (DocumentSlot.WORK_ORDER, DocumentSlot.EZYWINE_LISTING):
        await clear_single_slot_documents(db, batch_id, doc_slot)
    elif doc_slot == DocumentSlot.LABEL_REFERENCE:
        count_result = await db.execute(
            select(func.count(UploadedDocument.id))
            .where(UploadedDocument.batch_id == batch_id)
            .where(UploadedDocument.slot == DocumentSlot.LABEL_REFERENCE)
        )
        sequence = count_result.scalar_one() or 0

    doc = await save_uploaded_file(
        batch_id, doc_slot, file, sequence=sequence
    )
    db.add(doc)

    if doc_slot == DocumentSlot.WORK_ORDER:
        await refresh_header_from_work_order(db, batch, doc.stored_path)

    await db.commit()

    return RedirectResponse(
        url=_safe_redirect(redirect_to, batch_id),
        status_code=303,
    )


@app.post("/batches/{batch_id}/documents/{doc_id}/delete")
async def delete_document_route(
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    redirect_to: str = Form(""),
):
    """Remove an uploaded document (manager only)."""
    try:
        batch, doc = await get_batch_document(db, batch_id, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    assert_can_upload(batch, role)
    await delete_uploaded_document(db, doc)
    await db.commit()

    return RedirectResponse(
        url=_safe_redirect(redirect_to, batch_id),
        status_code=303,
    )


@app.post("/batches/{batch_id}/documents/{doc_id}/replace")
async def replace_document_route(
    batch_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    file: UploadFile = File(...),
    redirect_to: str = Form(""),
):
    """Replace an uploaded document in place (manager only)."""
    try:
        batch, doc = await get_batch_document(db, batch_id, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    assert_can_upload(batch, role)

    try:
        await replace_document_content(doc, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if doc.slot == DocumentSlot.WORK_ORDER:
        await refresh_header_from_work_order(db, batch, doc.stored_path)

    await db.commit()

    return RedirectResponse(
        url=_safe_redirect(redirect_to, batch_id),
        status_code=303,
    )


# ============== FORM ROUTES ==============

@app.get("/batches/{batch_id}/forms/{form_type}")
async def form_view(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
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
            parsed = parse_work_order_pdf(await read_bytes(work_order_doc.stored_path))
            pick_list_lines = filter_label_lines(parsed.get("pick_list_lines") or [])

    form_readonly = not can_write_forms(batch, role)

    return templates.TemplateResponse(
        request,
        "batches/form.html",
        {
            "batch": batch,
            "form_template": form_template,
            "form_instance": form_instance,
            "readings": sorted(form_instance.readings, key=lambda r: r.sequence) if form_instance else [],
            "inherited_values": inherited_values,
            "form_defaults": form_defaults,
            "pick_list_lines": pick_list_lines,
            "now": datetime.now(),
            "role": role,
            "form_readonly": form_readonly,
        },
    )


@app.post("/batches/{batch_id}/forms/{form_type}")
async def save_atomic_form(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Save an atomic form."""
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_write_forms(batch, role)

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
        await persist_atomic_form(db, batch, form_type, payload, action=action, role=role)
    except HTTPException:
        raise
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
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Add a reading to an accrual form."""
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_write_forms(batch, role)

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
            operator_identifier=form_data.get("operator_identifier", ""),
            captured_at=form_data.get("captured_at", ""),
            payload=payload,
            role=role,
        )
    except HTTPException:
        raise
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
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Save header fields on an accrual form (e.g. manufacturer, bottle code)."""
    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_write_forms(batch, role)

    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    form_data = await request.form()
    payload = build_form_payload(form_data, exclude={"action"})

    try:
        await persist_form_header(db, batch, form_type, payload, role=role)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save header: {e}")

    return RedirectResponse(
        url=f"/batches/{batch_id}/forms/{form_type}",
        status_code=303,
    )


@app.post("/batches/{batch_id}/forms/{form_type}/submit")
async def submit_form(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
    submitted_by: str = Form(...),
):
    """Submit an accrual form."""
    try:
        await submit_accrual_form(
            db,
            batch_id,
            form_type,
            submitted_by=submitted_by,
            role=role,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit form: {e}")

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


# ============== COMPILE ROUTES ==============

@app.post("/batches/{batch_id}/compile")
async def compile_batch_route(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
):
    """Compile batch into PDF and mark run complete."""
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
    assert_can_compile(batch, role)

    ezywine = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.EZYWINE_LISTING),
        None,
    )
    if not ezywine:
        raise HTTPException(
            status_code=400,
            detail="Upload the EzyWine Bottling Run COMPLETE Listing before compiling",
        )

    for comp in batch.compilations:
        if comp.is_current:
            comp.is_current = False

    try:
        compilation = await compile_batch(
            batch,
            db,
            settings.upload_dir,
            compiled_output_dir=settings.compiled_output_dir,
            compiled_by="Manager",
        )
        db.add(compilation)
        mark_complete(batch)
        await db.commit()
    except Exception as e:
        await db.rollback()
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/batches/{batch_id}/complete?error={quote(str(e)[:500])}",
            status_code=303,
        )

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


@app.post("/batches/{batch_id}/reopen")
async def reopen_batch_route(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
):
    """Reopen a complete run for manager edits and recompile."""
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.compilations))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    assert_can_reopen(batch, role)

    await reopen_run(db, batch)
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

    content = await read_bytes(doc.stored_path)
    return Response(
        content=content,
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

    content = await read_bytes(doc.stored_path)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_filename}"'
        },
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

    content = await read_bytes(compilation.stored_path)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{compilation.output_filename}"'
        },
    )






