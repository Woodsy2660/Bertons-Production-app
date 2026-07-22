# Berton Bottling Run Intake & Compilation App

Web app for **Berton Vineyards** bottling runs: operators capture station form data on tablets; managers compile a compliance PDF matching the existing 16-slot Berton document pack.

**Status:** Production-ready application (FastAPI + Postgres + Docker). Detailed specs live under [`Documentation/`](Documentation/).

---

## What it does

| Actor | Capabilities |
|--------|----------------|
| **Manager** | Create/edit runs, upload work order / EzyWine listing / label refs, monitor form status, compile PDF, reopen locked runs, print pallet tags, review in-app feedback |
| **Operator** | Open assigned station forms, enter readings (atomic / log / matrix), submit with identity; report bugs/suggestions via **Report issue** on any page |

**Feedback:** Any logged-in user can submit a bug, data-field change, or suggestion from the floating control (context and device captured automatically). Managers review at `/feedback` (read-only, newest first). Spec: [`Documentation/specs/12_Feedback_Reporting_System.md`](Documentation/specs/12_Feedback_Reporting_System.md).

**Compile model**

1. Each station form is rendered HTML → PDF (WeasyPrint in Docker; xhtml2pdf fallback on Windows).
2. Uploaded PDFs (EzyWine listing, work order, label references) are merged **as-is** (no logo overlay).
3. Station form PDFs get an **8–10mm Berton logo** on the **title page only**, top-right, aligned with the form title.
4. Pages are assembled in the fixed **16-slot** order into one file named like  
   `{run_number} {stock_item} {product}.pdf`.

---

## Stack

- **Python 3.12+**, **FastAPI**, **Jinja2** UI
- **PostgreSQL 16** (async SQLAlchemy + Alembic)
- **PDF:** WeasyPrint (preferred), xhtml2pdf fallback, pypdf merge, PyMuPDF for form title logo
- **Auth:** session cookies, manager / operator roles
- **Deploy:** Docker Compose on winery Azure host (`BV-AZ-DockerHost01`)

---

## Repository layout

```
app/                  # Application code (routes, services, forms, templates, static)
alembic/              # DB migrations
scripts/              # Deploy, seed, QA helpers
tests/                # Pytest suite (+ fixtures/work_orders/*.pdf for parser tests)
assets/brand/         # Official logo source pack (runtime uses app/static/img/)
samples/              # Non-runtime sample PDFs for manual checks
Documentation/        # All product/architecture/QA markdown
  specs/              # Extraction / pallet-tag addenda
  qa/                 # Test plans and execution reports
uploads/              # Runtime uploads only (gitignored contents)
compiled_output/      # Runtime compiled PDFs only (gitignored contents)
pallet_tags/          # Runtime pallet tag PDFs only (gitignored contents)
Dockerfile            # Production image (WeasyPrint system libs)
docker-compose.yml    # Postgres + optional full app stack
.env.example          # Config template (copy to .env)
```

**Build vs data**

| Needed to build/run the app | Not in source tree (runtime / docs only) |
|-----------------------------|------------------------------------------|
| `app/`, `alembic/`, `pyproject.toml`, Docker files | `uploads/*`, `compiled_output/*` PDFs |
| `app/static/img/berton_logo.png` | `assets/brand/` design sources |
| `tests/fixtures/` (for pytest) | `samples/`, all of `Documentation/` |

---

## Quick start (local development)

### Prerequisites

- Python 3.12+
- Docker (for Postgres)
- Optional: [uv](https://github.com/astral-sh/uv) or pip

### 1. Install dependencies

```bash
pip install -e ".[pdf]"
# or: uv sync  && uv pip install weasyprint  # Linux/macOS with WeasyPrint system deps
```

On **Windows**, WeasyPrint system libraries may be missing; the app falls back to **xhtml2pdf** for form PDFs. Production Docker images include WeasyPrint.

### 2. Environment

```bash
cp .env.example .env
# Edit SECRET_KEY, passwords, DATABASE_URL as needed
```

Default local DB URL (matches Compose port publish):

```text
DATABASE_URL=postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling
```

### 3. Start Postgres

```bash
docker compose up -d db
```

### 4. Migrate

```bash
alembic upgrade head
```

### 5. Run the app

```bash
# PowerShell
$env:DATABASE_URL = "postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Open **http://127.0.0.1:8001**

| Role | Default login (change in production) |
|------|--------------------------------------|
| Manager | `manager` / `manager` |
| Operator | `operator` / `operator` |

Optional seed data:

```bash
python scripts/seed_dashboard_runs.py
python scripts/seed_test_run.py
```

---

## Production (Docker)

See also: [`Documentation/08_Production_Deployment_Plan.md`](Documentation/08_Production_Deployment_Plan.md) and [`Documentation/DEPLOYMENT_ENVIRONMENT.md`](Documentation/DEPLOYMENT_ENVIRONMENT.md).

```bash
cp .env.example .env
# Set strong SECRET_KEY, manager/operator passwords, DEBUG=false
# SESSION_HTTPS_ONLY=true only when TLS terminates at the app with HTTPS cookies

docker compose --profile full up -d --build
# or: bash scripts/deploy.sh
```

- App: container `berton-web` (see compose ports / reverse proxy)
- DB: Postgres volume `postgres_data`
- Uploads and compiled PDFs: bind mounts or volumes under `uploads/` and `compiled_output/`

**After code changes that affect PDFs** (logo, forms, compile slots), managers must **recompile** each run (or **Reopen** then compile if status is COMPLETE). Existing PDFs are not retroactively rewritten.

---

## Configuration highlights

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Async Postgres URL (`postgresql+asyncpg://…`) |
| `SECRET_KEY` | Session signing (required non-default in production) |
| `DEBUG` | Verbose mode; keep `false` in production |
| `SESSION_HTTPS_ONLY` | Secure cookies; `false` on plain HTTP LAN |
| `UPLOAD_DIR` / `COMPILED_OUTPUT_DIR` | Local storage paths |
| `MANAGER_*` / `OPERATOR_*` | Basic role credentials |
| `ENABLE_DEV_TOOLS` | Dev/test UI routes |

Full list: [`.env.example`](.env.example).

---

## PDF logo behaviour (forms)

Implemented in `app/services/compilation.py`:

- Logo is applied **after** HTML→PDF for **station forms only**.
- **Height:** `10mm` (`_LOGO_HEIGHT_MM`), top-right, vertically aligned with the form title.
- **First page of each form only** — not on multi-page form continuations.
- **Not** applied to uploaded PDFs (EzyWine listing, work order, label refs).

Asset: `app/static/img/berton_logo.png` (PNG with transparency preferred).

---

## Tests

```bash
pytest
# Live/QA helpers under scripts/qa_*.py (need a running server + DB)
```

Plans and reports: [`Documentation/qa/`](Documentation/qa/).

---

## Documentation index

| Area | Location |
|------|----------|
| Overview & architecture | [`Documentation/00_Project_Overview.md`](Documentation/00_Project_Overview.md), [`01_System_Architecture.md`](Documentation/01_System_Architecture.md) |
| Data model & forms | [`02_Data_Model.md`](Documentation/02_Data_Model.md), [`03_Form_Specifications.md`](Documentation/03_Form_Specifications.md) |
| PDF compile slots | [`04_PDF_Compilation_Spec.md`](Documentation/04_PDF_Compilation_Spec.md) |
| Workflow | [`05_Workflow_and_Lifecycle.md`](Documentation/05_Workflow_and_Lifecycle.md) |
| As-built backend | [`07_Backend_Implementation.md`](Documentation/07_Backend_Implementation.md) |
| Deploy | [`08_Production_Deployment_Plan.md`](Documentation/08_Production_Deployment_Plan.md), [`DEPLOYMENT_ENVIRONMENT.md`](Documentation/DEPLOYMENT_ENVIRONMENT.md) |
| Extraction / pallet tags / feedback | [`Documentation/specs/`](Documentation/specs/) (incl. `12_Feedback_Reporting_System.md`) |
| QA | [`Documentation/qa/`](Documentation/qa/) |

---

## Mobile / LAN testing

```bash
# Linux/macOS
./start-mobile-test.sh
# Windows
start-mobile-test.bat
```

Binds the app for tablet access on the local network (use with care; prefer HTTPS or trusted LAN).

---

## License / ownership

Internal application for **Berton Vineyards**. Not published as open source unless otherwise agreed.
