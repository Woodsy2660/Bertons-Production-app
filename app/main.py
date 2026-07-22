import uuid
from pathlib import Path
from datetime import datetime, date
from typing import Annotated

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.auth.credentials import verify_credentials
from app.auth.dependencies import (
    PUBLIC_PATHS,
    Role,
    get_current_role,
    require_dev_tools,
    require_manager,
    require_operator_or_manager,
)
from app.auth.session import clear_session, get_role_from_session, set_role_in_session
from app.config import get_settings
from app.database import get_db
from app.db_health import check_db_connection, is_db_connection_error
from app.api import api_router
from app.models import (
    Batch, BatchHeader, FormInstance, Reading, UploadedDocument,
    Compilation, BatchStatus, FormStatus, FormType as ModelFormType,
    AccrualMode as ModelAccrualMode, DocumentSlot, PalletTagPrint,
    FeedbackReportType,
)
from app.services.feedback import (
    FeedbackValidationError,
    create_feedback_report,
    format_sydney,
    list_feedback_reports,
    parse_optional_batch_id,
    parse_report_type,
    safe_return_path,
    summarize_user_agent,
)
from app.forms import FormType, AccrualMode, FORM_TEMPLATES, get_form_template
from app.services.batch_lifecycle import (
    assert_can_compile,
    assert_can_reopen,
    assert_can_upload,
    assert_can_write_forms,
    can_compile,
    can_reopen,
    can_upload_documents,
    can_write_forms,
    is_greyed_out,
    list_batches_for_role,
    mark_complete,
    reopen_run,
    search_completed_runs,
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
    delete_reading,
    save_atomic_form as persist_atomic_form,
    save_form_header as persist_form_header,
    submit_accrual_form,
)
from app.services.storage import build_upload_path, read_bytes, save_bytes
from app.services.form_prefill import build_form_context, extract_packing_size
from app.services.pallet_tags import calculate_pallets, record_pallet_tag_print, total_tags_printed
from app.services.work_order_extraction import populate_header_from_work_order_pdf
from app.services.work_order_parser import (
    compute_pallet_count,
    filter_label_lines,
    parse_work_order_pdf,
    parse_work_order_pdf_verbose,
)

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
# cookie_https_only is False for LAN HTTP (Docker VM tablets); True on Vercel/TLS.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.cookie_https_only,
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
templates.env.globals["enable_dev_tools"] = settings.enable_dev_tools
templates.env.globals["get_role"] = lambda request: get_role_from_session(request.session)
templates.env.globals["format_sydney"] = format_sydney


def _database_unavailable_response(request: Request) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Database unavailable. Ensure Postgres is running (docker compose up -d).",
            },
        )
    return templates.TemplateResponse(
        request,
        "errors/database_unavailable.html",
        status_code=503,
    )


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def database_operational_error_handler(
    request: Request,
    exc: OperationalError | InterfaceError,
) -> Response:
    return _database_unavailable_response(request)


@app.exception_handler(OSError)
async def database_connection_os_error_handler(request: Request, exc: OSError) -> Response:
    if not is_db_connection_error(exc):
        raise exc
    return _database_unavailable_response(request)


# Ensure upload directory exists
upload_path = Path(settings.upload_dir)
upload_path.mkdir(exist_ok=True)
Path(settings.compiled_output_dir).mkdir(parents=True, exist_ok=True)

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/dev/work-order-parser")
async def dev_work_order_parser_page(
    request: Request,
    role: Annotated[Role, Depends(require_dev_tools)],
):
    """Dev/QA page to validate work order PDF extraction field-by-field."""
    return templates.TemplateResponse(
        request,
        "dev/work_order_parser.html",
        {"role": role},
    )


@app.post("/dev/work-order-parser/parse")
async def dev_work_order_parser_parse(
    role: Annotated[Role, Depends(require_dev_tools)],
    work_order: UploadFile = File(...),
):
    """Parse an uploaded work order PDF and return verbose extraction JSON."""
    validate_pdf_upload(work_order)
    content = await work_order.read()
    result = parse_work_order_pdf_verbose(content)
    compatible = parse_work_order_pdf(content)
    result["compatible"] = compatible
    result["pallet_count"] = compute_pallet_count(
        compatible.get("run_quantity"),
        compatible.get("cartons_per_pallet"),
    )
    return JSONResponse(content=result)

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


# ---------------------------------------------------------------------------
# Feedback / bug reporting
# ---------------------------------------------------------------------------


@app.post("/feedback")
async def submit_feedback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
    report_type: str = Form(...),
    description: str = Form(...),
    source_path: str = Form(""),
    page_context: str = Form(""),
    batch_id: str = Form(""),
    return_to: str = Form(""),
):
    """Accept a feedback report from operator or manager. Role from session only."""
    from urllib.parse import urlparse

    dest = safe_return_path(return_to, fallback="")
    if not dest:
        ref = request.headers.get("referer") or ""
        parsed = urlparse(ref)
        dest = safe_return_path(
            parsed.path + (f"?{parsed.query}" if parsed.query else ""),
            fallback="/",
        )

    try:
        await create_feedback_report(
            db,
            report_type=report_type,
            description=description,
            submitted_role=role,  # session only — never form field
            source_path=source_path or dest,
            page_context=page_context or None,
            batch_id=parse_optional_batch_id(batch_id),
            user_agent=request.headers.get("user-agent", ""),
        )
    except FeedbackValidationError:
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(url=f"{dest}{sep}feedback=error", status_code=303)

    sep = "&" if "?" in dest else "?"
    return RedirectResponse(url=f"{dest}{sep}feedback=ok", status_code=303)


@app.get("/feedback")
async def feedback_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    type: str = "",
):
    """Manager-only read-only review of feedback reports (newest first)."""
    filter_type: FeedbackReportType | None = None
    if type and type.strip():
        try:
            filter_type = parse_report_type(type)
        except FeedbackValidationError:
            filter_type = None

    reports = await list_feedback_reports(db, report_type=filter_type)

    rows = []
    for r in reports:
        run_number = None
        if r.batch is not None:
            run_number = r.batch.run_number
        rows.append(
            {
                "id": r.id,
                "report_type": r.report_type,
                "report_type_label": r.report_type.value.replace("_", " ").title(),
                "description": r.description,
                "submitted_role": r.submitted_role,
                "source_path": r.source_path,
                "page_context": r.page_context,
                "batch_id": r.batch_id,
                "run_number": run_number,
                "device": summarize_user_agent(r.user_agent),
                "submitted_at_sydney": format_sydney(r.submitted_at),
            }
        )

    return templates.TemplateResponse(
        request,
        "feedback/list.html",
        {
            "role": role,
            "rows": rows,
            "filter_type": filter_type.value if filter_type else "",
            "type_options": [
                ("", "All types"),
                ("bug", "Bug"),
                ("data_change", "Data field change"),
                ("suggestion", "Suggestion"),
            ],
        },
    )


# How many completed runs to show on the home dashboard (managers).
DASHBOARD_COMPLETE_PREVIEW = 10


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
    # Leftmost first: in-progress before reopened, then earliest run_date;
    # missing run dates last. Stable tie-break by created_at.
    def _active_sort_key(b):
        status = b.status.value if b.status else ""
        # 0 = in progress (and other active), 1 = reopened
        status_rank = 1 if status == "reopened" else 0
        missing_date = b.header.run_date is None if b.header else True
        run_date = (
            b.header.run_date
            if b.header and b.header.run_date
            else date.max
        )
        return (status_rank, missing_date, run_date, b.created_at or datetime.min)

    active_batches.sort(key=_active_sort_key)
    # Review queue: same urgency ordering by run date
    review_queue = sorted(
        review_queue,
        key=lambda b: (
            b.header.run_date is None if b.header else True,
            b.header.run_date if b.header and b.header.run_date else date.max,
            b.created_at or datetime.min,
        ),
    )
    all_complete = [b for b in batches if b.status == BatchStatus.COMPLETE]
    # Managers: short preview + dedicated history search for the full archive.
    if role == "manager":
        complete_batches = all_complete[:DASHBOARD_COMPLETE_PREVIEW]
        complete_total = len(all_complete)
        # True total may exceed list limit; history page has full search.
        complete_has_more = complete_total >= DASHBOARD_COMPLETE_PREVIEW
    else:
        complete_batches = all_complete
        complete_total = len(all_complete)
        complete_has_more = False

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_batches": active_batches,
            "complete_batches": complete_batches,
            "complete_total": complete_total,
            "complete_has_more": complete_has_more,
            "review_queue": review_queue,
            "role": role,
            "review_count": len(review_queue),
        },
    )


def _parse_optional_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        return None


@app.get("/runs/history")
async def completed_runs_history(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    q: str = "",
    product: str = "",
    stock_item: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    """Manager archive: search and browse all COMPLETE runs."""
    page_size = 25
    page = max(1, page)
    offset = (page - 1) * page_size
    run_date_from = _parse_optional_date(date_from)
    run_date_to = _parse_optional_date(date_to)

    batches, total = await search_completed_runs(
        db,
        q=q or None,
        product=product or None,
        stock_item=stock_item or None,
        run_date_from=run_date_from,
        run_date_to=run_date_to,
        limit=page_size,
        offset=offset,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    from urllib.parse import urlencode

    filter_params = {
        "q": q or "",
        "product": product or "",
        "stock_item": stock_item or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
    }
    # Drop empty filters for cleaner pagination URLs
    filter_params = {k: v for k, v in filter_params.items() if v}

    def page_url(p: int) -> str:
        params = {**filter_params, "page": str(p)}
        return "/runs/history?" + urlencode(params)

    return templates.TemplateResponse(
        request,
        "runs/history.html",
        {
            "role": role,
            "batches": batches,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "q": q or "",
            "product": product or "",
            "stock_item": stock_item or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < total_pages else "",
        },
    )


@app.get("/health")
async def health_check():
    """Liveness probe — process is up (does not check the database)."""
    return {
        "status": "healthy",
        "version": settings.app_version,
    }


@app.get("/ready")
async def readiness_check():
    """Readiness probe — confirms PostgreSQL is reachable."""
    if await check_db_connection():
        return {
            "status": "ready",
            "database": "connected",
            "version": settings.app_version,
        }
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "database": "unavailable",
            "hint": "Ensure the database service is running and DATABASE_URL is correct.",
        },
    )


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

    header = BatchHeader(batch=batch)
    populate_header_from_work_order_pdf(
        header,
        await read_bytes(work_order_doc.stored_path),
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


async def _batch_documents(
    db: AsyncSession,
    batch_id: uuid.UUID,
) -> tuple[Batch, UploadedDocument | None, list[UploadedDocument]]:
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    work_order = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.WORK_ORDER),
        None,
    )
    label_references = sorted(
        [d for d in batch.uploaded_documents if d.slot == DocumentSlot.LABEL_REFERENCE],
        key=lambda d: d.sequence,
    )
    return batch, work_order, label_references


@app.get("/batches/{batch_id}/edit")
async def edit_batch_form(
    request: Request,
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
):
    """Manager page to review and update run documents."""
    batch, work_order, label_references = await _batch_documents(db, batch_id)
    assert_can_upload(batch, role)
    return templates.TemplateResponse(
        request,
        "batches/edit.html",
        {
            "batch": batch,
            "work_order": work_order,
            "label_references": label_references,
            "role": role,
        },
    )


@app.post("/batches/{batch_id}/edit")
async def edit_batch_submit(
    request: Request,
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_manager)],
    work_order: UploadFile | None = File(default=None),
    label_references: list[UploadFile] = File(default=[]),
    remove_labels: list[str] = Form(default=[]),
):
    """Replace work order and/or update label references for an existing run."""
    batch, existing_work_order, _ = await _batch_documents(db, batch_id)
    assert_can_upload(batch, role)

    for raw_id in remove_labels:
        try:
            doc_id = uuid.UUID(raw_id)
        except ValueError:
            continue
        try:
            _, doc = await get_batch_document(db, batch_id, doc_id)
        except ValueError:
            continue
        if doc.slot != DocumentSlot.LABEL_REFERENCE:
            continue
        await delete_uploaded_document(db, doc)

    if work_order and work_order.filename:
        try:
            validate_pdf_upload(work_order)
        except ValueError as exc:
            _, _, label_references = await _batch_documents(db, batch_id)
            return templates.TemplateResponse(
                request,
                "batches/edit.html",
                {
                    "batch": batch,
                    "work_order": existing_work_order,
                    "label_references": label_references,
                    "role": role,
                    "error": str(exc),
                },
                status_code=400,
            )
        await clear_single_slot_documents(db, batch_id, DocumentSlot.WORK_ORDER)
        doc = await save_uploaded_file(batch_id, DocumentSlot.WORK_ORDER, work_order)
        db.add(doc)
        await refresh_header_from_work_order(db, batch, doc.stored_path)

    count_result = await db.execute(
        select(func.count(UploadedDocument.id))
        .where(UploadedDocument.batch_id == batch_id)
        .where(UploadedDocument.slot == DocumentSlot.LABEL_REFERENCE)
    )
    next_label_sequence = count_result.scalar_one() or 0
    for label_file in label_references:
        if not label_file.filename:
            continue
        if not label_file.filename.lower().endswith(".pdf"):
            continue
        label_doc = await save_uploaded_file(
            batch_id,
            DocumentSlot.LABEL_REFERENCE,
            label_file,
            sequence=next_label_sequence,
        )
        db.add(label_doc)
        next_label_sequence += 1

    refreshed_batch, work_order_after, _ = await _batch_documents(db, batch_id)
    if not work_order_after:
        _, _, label_references = await _batch_documents(db, batch_id)
        return templates.TemplateResponse(
            request,
            "batches/edit.html",
            {
                "batch": refreshed_batch,
                "work_order": None,
                "label_references": label_references,
                "role": role,
                "error": "A work order PDF is required for every run.",
            },
            status_code=400,
        )

    await db.commit()
    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


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
            selectinload(Batch.pallet_tag_prints),
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

    pending_forms = [
        info["label"]
        for info in form_status.values()
        if info["status"] != "submitted"
    ]

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
            "can_reopen": can_reopen(batch, role),
            "can_print_pallet_tags": work_order is not None,
            "pallet_calc": calculate_pallets(batch),
            "tags_printed_total": sum(p.tags_printed for p in batch.pallet_tag_prints),
            "pending_forms": pending_forms,
        },
    )


@app.get("/batches/{batch_id}/pallet-tags")
async def pallet_tags_page(
    request: Request,
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.pallet_tag_prints),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    work_order = next(
        (d for d in batch.uploaded_documents if d.slot == DocumentSlot.WORK_ORDER),
        None,
    )
    if not work_order:
        raise HTTPException(status_code=400, detail="Upload a work order before printing pallet tags.")

    calc = calculate_pallets(batch)
    tags_printed_total = await total_tags_printed(db, batch.id)
    header = batch.header
    return templates.TemplateResponse(
        request,
        "batches/pallet_tags.html",
        {
            "batch": batch,
            "role": role,
            "calc": calc,
            "tags_printed_total": tags_printed_total,
            "size": extract_packing_size(header.packing_unit if header else None),
            "print_history": sorted(batch.pallet_tag_prints, key=lambda p: p.printed_at, reverse=True),
        },
    )


@app.post("/batches/{batch_id}/pallet-tags/print")
async def pallet_tags_print(
    batch_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
    tags_to_print: int = Form(...),
    note: str = Form(""),
):
    result = await db.execute(
        select(Batch)
        .options(selectinload(Batch.header), selectinload(Batch.uploaded_documents))
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if tags_to_print < 1:
        raise HTTPException(status_code=400, detail="Tags to print must be at least 1.")

    print_row, _, print_result = await record_pallet_tag_print(
        db,
        batch,
        tags_to_print=tags_to_print,
        printed_by=role.title(),
        dispatch_method="browser",
        note=note or None,
    )
    await db.commit()
    return RedirectResponse(
        url=f"/batches/{batch_id}/pallet-tags/pdf/{print_row.id}?autoprint=1",
        status_code=303,
    )


@app.get("/batches/{batch_id}/pallet-tags/pdf/{print_id}")
async def pallet_tags_pdf(
    batch_id: uuid.UUID,
    print_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    result = await db.execute(
        select(PalletTagPrint)
        .where(PalletTagPrint.id == print_id)
        .where(PalletTagPrint.batch_id == batch_id)
    )
    print_row = result.scalar_one_or_none()
    if not print_row or not print_row.stored_path:
        raise HTTPException(status_code=404, detail="Tag PDF not found")
    content = await read_bytes(print_row.stored_path)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="pallet_tags.pdf"'},
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
    if not can_compile(batch, role):
        raise HTTPException(status_code=400, detail="Completion is not available for this run")

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
            selectinload(Batch.form_instances),
        )
        .where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if not can_compile(batch, role):
        raise HTTPException(status_code=400, detail="Completion is not available for this run")

    pending_forms = [
        FORM_DISPLAY_NAMES.get(fi.form_type.value, fi.form_type.value)
        for fi in batch.form_instances
        if fi.status != FormStatus.SUBMITTED
    ]
    missing_forms = [
        FORM_DISPLAY_NAMES.get(ft.value, ft.value)
        for ft in FormType
        if ft.value not in {fi.form_type.value for fi in batch.form_instances}
    ]
    pending_forms = sorted(set(pending_forms + missing_forms))

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
            "pending_forms": pending_forms,
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

    form_context = build_form_context(batch, form_type, form_instance)
    inherited_values = form_context["prefill_values"]
    prefill_flags = form_context["prefill_flags"]
    reference_values = form_context["reference_values"]
    form_defaults = build_form_defaults(form_type)

    pick_list_lines: list = []
    if form_instance and form_instance.header_payload and form_instance.header_payload.get("lines"):
        pick_list_lines = filter_label_lines(form_instance.header_payload["lines"])
    elif batch.header and batch.header.pick_list_lines:
        pick_list_lines = filter_label_lines(batch.header.pick_list_lines)

    form_readonly = not can_write_forms(batch, role)
    delete_error = request.query_params.get("error")

    return templates.TemplateResponse(
        request,
        "batches/form.html",
        {
            "batch": batch,
            "form_template": form_template,
            "form_instance": form_instance,
            "readings": sorted(form_instance.readings, key=lambda r: r.sequence) if form_instance else [],
            "inherited_values": inherited_values,
            "prefill_flags": prefill_flags,
            "reference_values": reference_values,
            "form_defaults": form_defaults,
            "pick_list_lines": pick_list_lines,
            "now": datetime.now(),
            "role": role,
            "form_readonly": form_readonly,
            "delete_error": delete_error,
        },
    )


@app.get("/batches/{batch_id}/forms/{form_type}/entries")
async def form_entries_list(
    request: Request,
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Full scrollable list of accrual form entries."""
    result = await db.execute(
        select(Batch).where(Batch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    try:
        ft = FormType(form_type)
        form_template = get_form_template(ft)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown form type")

    if form_template.accrual_mode.value == "atomic":
        raise HTTPException(status_code=404, detail="This form has no entry log")

    fi_result = await db.execute(
        select(FormInstance)
        .options(selectinload(FormInstance.readings))
        .where(FormInstance.batch_id == batch_id)
        .where(FormInstance.form_type == ModelFormType(form_type))
    )
    form_instance = fi_result.scalar_one_or_none()
    form_readonly = not can_write_forms(batch, role)
    delete_error = request.query_params.get("error")

    return templates.TemplateResponse(
        request,
        "batches/entries.html",
        {
            "batch": batch,
            "form_template": form_template,
            "form_instance": form_instance,
            "readings": sorted(form_instance.readings, key=lambda r: r.sequence) if form_instance else [],
            "role": role,
            "form_readonly": form_readonly,
            "delete_error": delete_error,
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

    payload = build_form_payload(
        form_data, exclude={"action", "stock_codes_checked"}
    )

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


@app.post("/batches/{batch_id}/forms/{form_type}/readings/{reading_id}/delete")
async def delete_reading_route(
    batch_id: uuid.UUID,
    form_type: str,
    reading_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
    redirect_to: str = Form(""),
):
    """Delete one accrual entry and return to the form."""
    from urllib.parse import quote

    dest = _safe_redirect(
        redirect_to or f"/batches/{batch_id}/forms/{form_type}",
        batch_id,
    )

    result = await db.execute(select(Batch).where(Batch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        return RedirectResponse(
            url=f"{dest}?error={quote('Batch not found')}",
            status_code=303,
        )

    try:
        await delete_reading(db, batch, form_type, reading_id, role=role)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Could not delete entry"
        return RedirectResponse(
            url=f"{dest}?error={quote(detail)}",
            status_code=303,
        )
    except Exception as e:
        await db.rollback()
        return RedirectResponse(
            url=f"{dest}?error={quote(f'Failed to delete entry: {e}')}",
            status_code=303,
        )

    return RedirectResponse(url=dest, status_code=303)


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
    batch_id: uuid.UUID,
    form_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[Role, Depends(require_operator_or_manager)],
):
    """Submit an accrual form."""
    try:
        await submit_accrual_form(
            db,
            batch_id,
            form_type,
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
    """Compile batch into PDF and mark run complete.

    Serialises compile per batch (FOR UPDATE) so concurrent compiles cannot
    create two is_current=true rows (TEST-C2 / QA-002).
    """
    # Lock the batch row first so concurrent compile attempts queue.
    lock_result = await db.execute(
        select(Batch).where(Batch.id == batch_id).with_for_update()
    )
    locked = lock_result.scalar_one_or_none()
    if not locked:
        raise HTTPException(status_code=404, detail="Batch not found")

    if locked.status == BatchStatus.COMPLETE:
        raise HTTPException(
            status_code=409,
            detail="This run is already complete and has a current compilation",
        )

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
    batch = result.scalar_one()
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
    await db.flush()

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

        # Unique-index violation on concurrent current compilation → clean 409
        msg = str(e)
        if "uq_compilations_one_current_per_batch" in msg or "UniqueViolation" in type(e).__name__:
            raise HTTPException(
                status_code=409,
                detail="Another compile finished first for this run",
            ) from e

        return RedirectResponse(
            url=f"/batches/{batch_id}/complete?error={quote(msg[:500])}",
            status_code=303,
        )

    return RedirectResponse(url=f"/batches/{batch_id}#run-completion", status_code=303)


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

    try:
        content = await read_bytes(doc.stored_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "PDF file is missing on disk (database still has the upload record). "
                "Re-upload the document, or run: python scripts/restore_missing_uploads.py"
            ),
        ) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"'},
    )


@app.get("/uploads/{doc_id}/page")
async def view_upload_page(
    request: Request,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Standalone full-page PDF viewer (no app chrome)."""
    result = await db.execute(
        select(UploadedDocument).where(UploadedDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return templates.TemplateResponse(
        request,
        "documents/standalone.html",
        {
            "doc": doc,
            "title": doc.original_filename,
        },
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

    try:
        content = await read_bytes(doc.stored_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "PDF file is missing on disk (database still has the upload record). "
                "Re-upload the document, or run: python scripts/restore_missing_uploads.py"
            ),
        ) from exc
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






