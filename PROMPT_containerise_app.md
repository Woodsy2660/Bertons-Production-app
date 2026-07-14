# Task: Containerise the app — add a Dockerfile and a `web` service to docker-compose.yml

## Context
The app currently has a `docker-compose.yml` with **only** a Postgres `db`
service (shown below). There is no Dockerfile and no application container, so
`docker compose up` starts only Postgres and nothing serves the app. Add a
production-capable Dockerfile for the FastAPI app and a `web` service to compose
so the full stack (app + db) runs on the VM.

Stack: FastAPI + uvicorn, async SQLAlchemy (asyncpg), Alembic, Jinja2, WeasyPrint
(HTML→PDF), pypdf/pikepdf, pdfplumber. Dependencies are managed with **uv**
(`pyproject.toml` + `uv.lock` present). Runs containerised on a Linux VM, served
over HTTP to tablets on the LAN.

## Current docker-compose.yml (do not remove the db service; extend the file)
```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: berton-postgres
    environment:
      POSTGRES_USER: berton
      POSTGRES_PASSWORD: berton_dev
      POSTGRES_DB: berton_bottling
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U berton -d berton_bottling"]
      interval: 5s
      timeout: 5s
      retries: 5
volumes:
  postgres_data:
```

## 1. Create a Dockerfile (project root)
Requirements:
- Base: a slim Python image matching the project's Python version (check
  `pyproject.toml`).
- **Install WeasyPrint's system libraries** (WeasyPrint will not render without
  them): libpango-1.0-0, libpangocairo-1.0-0, libcairo2, libgdk-pixbuf-2.0-0,
  libffi-dev, and shared fonts (e.g. fonts-dejavu-core). **Also install `qpdf`**
  (pikepdf depends on it). Then clean apt lists to keep the image small.
- Install dependencies with **uv** using the committed lockfile for reproducible
  builds (`uv sync --frozen` or equivalent), not a bare `pip install`.
- Copy the application code.
- **Entrypoint runs migrations then serves:** `alembic upgrade head` and then
  `uvicorn` binding **`0.0.0.0:8000`**. Use an entrypoint script so migrations
  complete before uvicorn accepts traffic. The app must listen on `0.0.0.0` (NOT
  `127.0.0.1`) or tablets cannot reach it.
- Do not bake secrets into the image; config comes from the environment at runtime.

## 2. Add the `web` service to docker-compose.yml
- `build: .` (uses the new Dockerfile).
- `container_name: berton-web` (or similar).
- **`depends_on:` the db with `condition: service_healthy`** so web waits for
  Postgres to be ready (db already has a healthcheck — use it). This prevents the
  first-boot crash where web starts before Postgres accepts connections.
- **Ports:** publish `"0.0.0.0:8000:8000"`.
- **`restart: unless-stopped`** (so it survives VM reboots).
- Load configuration from `.env` (`env_file: .env`), including `DATABASE_URL`,
  `SECRET_KEY`, `SESSION_HTTPS_ONLY`, `DEBUG`, `TZ`, and the shared-login creds.
- Add container **log rotation** to prevent unbounded log growth filling the disk:
  ```yaml
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }
  ```

## 3. Database connection — critical detail
Inside the compose network the app reaches Postgres at the **service name and
INTERNAL port**: host `db`, port `5432` (NOT `localhost`, NOT the published
`5433`). The `DATABASE_URL` (async driver) must be:
```
postgresql+asyncpg://berton:berton_dev@db:5432/berton_bottling
```
Set this in `.env`, not hardcoded. (Credentials match the existing db service;
these should ideally also move to `.env` — see §5.)

## 4. First-run login
An empty database has schema but no users after migration. Confirm how the two
shared logins (manager / operator) are created — a seed step or env-var-driven
bootstrap. Ensure there is a working path to create/authenticate at least one
role on first boot, or testing cannot proceed past the login screen. State what
that path is.

## 5. Recommended hardening (do if straightforward)
- Move the db credentials out of the compose file into `.env` (referenced by both
  services) so they're not committed and are defined once.
- Flag that `berton_dev` is a weak password to replace before real/production data.
- Consider a non-root user in the container for the app process.

## Acceptance criteria
- `docker compose up -d --build` builds the image and starts **both** `web` and
  `db`; `docker compose ps` shows both up, web healthy, published on
  `0.0.0.0:8000`.
- `docker compose logs web` shows Alembic migrations applied and a clean uvicorn
  startup on `0.0.0.0:8000` — no crash-loop, no DB-connection-refused.
- `curl http://localhost:8000/health` and `/ready` on the VM return OK.
- WeasyPrint can render a PDF and pikepdf can assemble one (no missing-native-lib
  errors at runtime).
- The db service and its volume/healthcheck are unchanged and still work.

## Do not
- Do not remove or alter the existing `db` service behaviour or its volume.
- Do not bind the app to `127.0.0.1` — it must be `0.0.0.0:8000`.
- Do not point the app at `localhost:5433` — inside compose it's `db:5432`.
- Do not bake secrets into the image.
