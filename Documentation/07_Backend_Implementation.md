# Backend Implementation — Current State

**Audience:** AI assistants and developers working on this codebase.  
**Status:** As implemented in the repository (not the original prototype spec).  
**Entry point:** `app/main.py` → `app:app` (FastAPI ASGI application).

---

## 1. Stack and runtime

| Layer | Technology |
|-------|------------|
| Framework | FastAPI + Starlette |
| Templates | Jinja2 (`app/templates/`) |
| ORM | SQLAlchemy 2.x async |
| DB driver | `asyncpg` via `postgresql+asyncpg://` URLs |
| Migrations | Alembic (`alembic/`, `build.py` on deploy) |
| Sessions | `starlette.middleware.sessions.SessionMiddleware` (signed cookie) |
| PDF merge/render | `pypdf`, Jinja2 HTML→PDF templates, optional `weasyprint` for seeds |
| File storage | Local disk (dev) or Vercel Blob (production) |

**Local dev:**
```bash
docker compose up -d          # Postgres on localhost:5433
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

**Production (Vercel):**
- `pyproject.toml` → `[tool.vercel] entrypoint = "app.main:app"`
- `vercel.json` → `buildCommand: python build.py` (runs Alembic if DB URL present)
- Serverless functions; uploads use `/tmp` when `VERCEL` is set

---

## 2. Configuration (`app/config.py`)

Settings load from environment / `.env` via `pydantic-settings`. Cached singleton: `get_settings()`.

### Key environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres connection (also checks `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING`, `POSTGRES_PRISMA_URL`) |
| `SECRET_KEY` | Session cookie signing (required in production) |
| `MANAGER_USERNAME` / `MANAGER_PASSWORD` | Shared manager login |
| `OPERATOR_USERNAME` / `OPERATOR_PASSWORD` | Shared operator login |
| `STORAGE_BACKEND` | `local` or `blob` |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token (auto-enables blob on Vercel if set) |
| `UPLOAD_DIR` / `COMPILED_OUTPUT_DIR` | Local paths; overridden to `/tmp/...` on Vercel |

### URL normalization

`postgres://` and `postgresql://` URLs are converted to `postgresql+asyncpg://`.

Supabase transaction pooler (port `6543`): `app/database.py` sets `connect_args={"statement_cache_size": 0}` when the URL contains `supabase` and `:6543`.

### Production defaults

When `VERCEL` is set: `debug=False`, upload dirs → `/tmp`, storage backend → `blob` if blob token configured.

---

## 3. Application bootstrap (`app/main.py`)

### Middleware order (important)

Starlette reverses middleware registration order. Current setup:

1. **Register first:** `@app.middleware("http")` `auth_middleware` — checks session role; redirects HTML to `/login`, returns 401 JSON for `/api/*`.
2. **Register second:** `SessionMiddleware` — wraps auth on the outside so `request.session` is available inside auth.

Effective stack: `SessionMiddleware → auth_middleware → routes`.

Public paths (`app/auth/dependencies.py`): `/login`, `/health`, `/static/*`.

### Mounted resources

- `/static` → `app/static/`
- `/api` → `api_router` from `app/api/__init__.py`

### Dual routing pattern

The app uses **two parallel interfaces** to the same services:

| Interface | Location | Response style |
|-----------|----------|----------------|
| **HTML routes** | `app/main.py` | Jinja templates, form POST, 303 redirects |
| **JSON API** | `app/api/forms.py`, `app/api/batches.py` | Pydantic models, used by `form-save.js` |

Business logic lives in `app/services/*`; routes are thin wrappers.

---

## 4. Authentication and authorization

### Model

- **Not per-user accounts.** Two shared credentials (manager / operator) from env vars.
- `app/auth/credentials.py` → `verify_credentials()` returns `Role | None`.
- Role stored in session key `"role"` (`app/auth/session.py`).

### Role capabilities (`app/services/batch_lifecycle.py`)

| Action | Manager | Operator |
|--------|---------|----------|
| Create run | ✓ | ✗ |
| Edit forms (in-progress run) | ✓ | ✓ |
| Edit forms (reopened run) | ✓ | ✗ |
| Edit forms (complete run) | ✗ | ✗ |
| Upload/delete documents | ✓ | ✗ |
| Compile PDF / mark complete | ✓ | ✗ |
| Reopen complete run | ✓ | ✗ |
| Dashboard: all runs | ✓ | Today + recent complete only |

FastAPI dependencies: `require_manager`, `require_operator_or_manager`, `require_auth` in `app/auth/dependencies.py`.

---

## 5. Database layer

### Engine (`app/database.py`)

```python
create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=2)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

Dependency injection: `get_db()` yields an `AsyncSession` per request.

### Schema (Postgres)

Managed by Alembic migration `alembic/versions/791a084d54ca_initial_schema.py`.

**Entities:**

```
Batch (batches)
├── BatchHeader (1:1) — product, tank, run_date, pick_list_lines JSONB, etc.
├── FormInstance (1:N, unique per form_type) — header_payload JSONB, status
│   └── Reading (1:N) — sequence, operator_identifier, payload JSONB
├── UploadedDocument (1:N) — slot: work_order | ezywine_listing | label_reference
└── Compilation (1:N) — compiled PDF metadata, is_current flag

Operator (operators) — name/initials lookup table (seeded; API exists but router not mounted)
```

### Enums (Postgres native enums via `app/models/db_enums.py`)

- **BatchStatus:** `in_progress`, `awaiting_review`, `complete`, `reopened`
- **FormStatus:** `not_started`, `in_progress`, `submitted`, `edited_since_submit`
- **FormType:** nine form slugs (see §6)
- **AccrualMode:** `atomic`, `log`, `matrix`
- **DocumentSlot:** `work_order`, `ezywine_listing`, `label_reference`

---

## 6. Form system

### Definitions vs instances

| Concept | Location | Purpose |
|---------|----------|---------|
| **Form templates** | `app/forms/definitions/*.py` + `app/forms/registry.py` | Field schemas, accrual mode, doc numbers — code, not DB |
| **Form instances** | `form_instances` table | Per-batch saved state |
| **Readings** | `readings` table | Per-entry rows on accrual forms |

Nine forms (`app/forms/types.py`):

| Form | Accrual mode | Data shape |
|------|--------------|------------|
| daily_production | atomic | Single header_payload submit |
| pick_list | atomic | header_payload + lines array |
| filler_line_check | matrix | header + readings (multi-value cells per reading) |
| finished_product_line_check | matrix | header + readings |
| bottle_sealing | log | header + readings |
| label_usage | log | header + readings (section: fronts/backs/other) |
| carton_qc | log | header + readings (carton_details / hourly_qc tables) |
| final_pallet_count | log | header + readings (bottles / finished regions) |
| finished_product_pallet | log | header + readings |

`get_form_template(FormType)` returns `FormTemplate` with `header_fields` and `reading_fields`.

### Persistence (`app/services/form_persistence.py`)

| Function | Used for |
|----------|----------|
| `save_atomic_form` | Atomic forms — draft or submit |
| `save_form_header` | Accrual header auto-save |
| `add_reading` | Append one reading; auto-creates FormInstance |
| `delete_reading` | Delete entry, renumber sequences |
| `submit_accrual_form` | Mark accrual form submitted; derives submitter from readings |
| `build_form_payload_from_mapping` | Flatten HTML form / JSON body to JSONB |
| `serialize_reading` | API response shape for incremental UI |

After any form submit that completes all nine forms, `maybe_transition_to_awaiting_review()` sets batch status → `awaiting_review`.

---

## 7. Batch lifecycle state machine

Central logic: `app/services/batch_lifecycle.py`.

```
                    ┌─────────────────┐
     create run     │  IN_PROGRESS    │◄──── reopen (manager)
        ──────────► │                 │
                    └────────┬────────┘
                             │ all 9 forms submitted
                             ▼
                    ┌─────────────────┐
                    │ AWAITING_REVIEW │
                    └────────┬────────┘
                             │ compile PDF (+ EzyWine listing required)
                             ▼
                    ┌─────────────────┐
                    │    COMPLETE     │  is_locked = true
                    └────────┬────────┘
                             │ manager reopen
                             ▼
                    ┌─────────────────┐
                    │    REOPENED     │  operators locked out
                    └─────────────────┘
```

- **Compile** (`POST /batches/{id}/compile`): requires `awaiting_review` or `reopened`, EzyWine listing uploaded; calls `compile_batch()`, then `mark_complete()`.
- **Dashboard** (`GET /`): splits batches into active / review queue / complete via `list_batches_for_role()`.

---

## 8. Route map

### HTML routes (`app/main.py`)

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/` | both | Dashboard |
| GET/POST | `/login`, POST `/logout` | public | Auth |
| GET | `/health` | public | Health check (no DB probe) |
| GET/POST | `/batches/new` | manager | Create run + work order upload |
| GET | `/batches/{id}` | both | Run detail + form grid |
| GET | `/batches/{id}/forms/{form_type}` | both | Form editor page |
| GET | `/batches/{id}/forms/{form_type}/entries` | both | Full readings list |
| POST | `/batches/{id}/forms/.../readings/{id}/delete` | both | Delete entry (redirect) |
| POST | `/batches/{id}/forms/.../submit` | both | Mark accrual form complete |
| GET | `/batches/{id}/complete` | manager | Compile workflow page |
| POST | `/batches/{id}/compile` | manager | Build PDF + mark complete |
| POST | `/batches/{id}/reopen` | manager | Reopen complete run |
| POST | `/batches/{id}/upload` | manager | Document upload |
| GET | `/uploads/{doc_id}/view` | both* | Inline PDF (*session required via middleware) |

### JSON API (`/api/batches/...`)

| Module | Endpoints |
|--------|-----------|
| `app/api/batches.py` | CRUD list/get/create batch (JSON) |
| `app/api/forms.py` | `readings` POST, `readings/{id}/delete` POST/DELETE, `header` POST, `draft` POST, `submit` POST, `barcode-lookup` GET (stub) |

`app/api/operators.py` exists but is **not** included in `api_router` — dead code unless wired up.

### Frontend ↔ API wiring

`app/static/js/form-save.js`:
- Readings → `POST /api/batches/{id}/forms/{type}/readings`
- Header/draft auto-save → `/api/.../header`, `/api/.../draft`
- Mark form complete → `/api/.../submit`
- Entry delete → native HTML `POST` to `/batches/.../readings/{id}/delete` (not API)

---

## 9. File storage (`app/services/storage.py`)

Abstraction over local disk vs Vercel Blob:

| Operation | Local | Blob |
|-----------|-------|------|
| `save_bytes` | Write to `UPLOAD_DIR` | `vercel.blob.put_async` |
| `read_bytes` | `Path.read_bytes` | `vercel.blob.get_async` |
| `delete_stored_file` | `unlink` | `delete_async` |

`UploadedDocument.stored_path` holds either a filesystem path or a Blob HTTPS URL.

Document management: `app/services/document_management.py` (upload validation, replace, delete, work-order header refresh).

Work order parsing: `app/services/work_order_parser.py` — extracts header fields + pick list lines from PDF text on batch creation.

---

## 10. PDF compilation (`app/services/compilation.py`)

16-slot template (`COMPILE_SLOTS`) merges:

1. Uploaded PDFs (EzyWine listing, work order, label references)
2. Rendered app forms from Jinja templates in `app/templates/pdf/`

Output: `Compilation` row + PDF saved via `save_bytes()` (local or Blob). Previous compilations marked `is_current=False` on recompile.

Filename convention: derived from run number, stock item, product (`sanitize_filename`).

---

## 11. Typical request flows

### A. Manager creates a run

1. `POST /batches/new` — multipart: `run_number`, `work_order` PDF, optional `label_references[]`
2. Creates `Batch` + `BatchHeader` (parsed from work order) + `UploadedDocument`(s)
3. Redirect → `/batches/{id}`

### B. Operator adds an accrual entry (e.g. carton QC)

1. Browser: `form-save.js` intercepts reading form submit
2. `POST /api/batches/{id}/forms/carton_qc/readings` with JSON body
3. `add_reading()` → new `Reading` row, `FormInstance.status` → `in_progress`
4. Response includes `serialize_reading()` for DOM append

### C. Operator marks form complete

1. `POST /api/batches/{id}/forms/{type}/submit` (no initials in UI — derived server-side)
2. `submit_accrual_form()` → `FormInstance.status` = `submitted`
3. If all 9 submitted → batch → `awaiting_review`

### D. Manager compiles

1. Upload EzyWine listing on `/batches/{id}/complete`
2. `POST /batches/{id}/compile`
3. `compile_batch()` → PDF; `mark_complete()` → batch locked

---

## 12. Dev / seed utilities

| Script | Purpose |
|--------|---------|
| `scripts/seed_dashboard_runs.py` | Six mock runs (15801–15806) for dashboard UI testing |
| `scripts/seed_test_run.py` | One fully-populated compile test run |
| `scripts/populate_run_15785.py` | Populate existing batch from work order |
| `build.py` | Vercel build: `alembic upgrade head` |

---

## 13. Tests (`tests/`)

| File | Covers |
|------|--------|
| `test_auth.py` | Login session + middleware order |
| `test_config.py` | Database URL normalization |
| `test_storage.py` | Blob path detection |
| `test_form_persistence.py` | Form save logic |
| `test_batch_lifecycle.py` | State transitions |
| `test_document_management.py` | Document ops |

Run: `python -m pytest`

---

## 14. Directory reference

```
app/
├── main.py              # FastAPI app, HTML routes, middleware
├── config.py            # Settings, env, URL normalization
├── database.py          # Engine, session, get_db
├── api/
│   ├── batches.py       # JSON batch CRUD
│   └── forms.py         # JSON incremental saves
├── auth/
│   ├── credentials.py   # Two shared logins
│   ├── session.py       # Cookie session helpers
│   └── dependencies.py  # FastAPI Depends + PUBLIC_PATHS
├── models/              # SQLAlchemy ORM
├── forms/
│   ├── types.py         # FormType, AccrualMode, FieldDef
│   ├── registry.py      # FORM_TEMPLATES map
│   └── definitions/     # Per-form field specs
├── services/
│   ├── batch_lifecycle.py
│   ├── form_persistence.py
│   ├── compilation.py
│   ├── storage.py
│   ├── document_management.py
│   ├── work_order_parser.py
│   └── seed_*.py
├── schemas/             # Pydantic API models (batches)
├── templates/           # Jinja HTML + PDF templates
└── static/              # CSS, JS (form-save.js, barcode-scan.js)
```

---

## 15. Known gaps / stubs

- **Barcode lookup** (`/api/batches/{id}/barcode-lookup`): returns scanned code only; ERP hook not implemented.
- **EzyWine integration** (`app/services/ezywine_stub.py`): stub only.
- **Operators API**: defined in `app/api/operators.py` but not mounted on `api_router`.
- **Supabase Storage**: not used; Postgres only. Files use local disk or Vercel Blob.
- **`/health`**: does not verify database connectivity.

---

## 16. Relation to design docs

The `Documentation/00–06` suite describes the **prototype specification**. This document describes **what is actually built**. Where they diverge, trust the code paths above.

Primary cross-references:
- Data model → `02_Data_Model.md` (conceptual) vs `app/models/` (actual)
- Form fields → `03_Form_Specifications.md` vs `app/forms/definitions/`
- Lifecycle → `05_Workflow_and_Lifecycle.md` vs `app/services/batch_lifecycle.py`
- Compile slots → `04_PDF_Compilation_Spec.md` vs `COMPILE_SLOTS` in `compilation.py`