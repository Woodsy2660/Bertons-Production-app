# 08 — Production Deployment Plan (Azure Docker VM)

**Audience:** developers, .nxt IT, coding agents.  
**Status:** Implementation plan (not yet executed).  
**Inputs:** `DEPLOYMENT_ENVIRONMENT.md`, `07_Backend_Implementation.md`, repo as of 2026-07-13.  
**Target host:** `BV-AZ-DockerHost01` (`10.0.0.4`), Ubuntu Azure VM, snap Docker.

---

## 1. Executive summary

The app is a **working FastAPI prototype** that today runs either:

| Mode | What exists | Fit for winery floor |
|------|-------------|----------------------|
| **Local dev** | `docker compose` = **Postgres only**; app via `uvicorn` on the laptop | Dev only |
| **Vercel** | Serverless entrypoint + optional Supabase/Neon + Vercel Blob | Not the winery target |
| **Winery VM** | Documented in `DEPLOYMENT_ENVIRONMENT.md`; **no app image / full compose yet** | **Required target** |

**Goal:** run the full stack as containers on `BV-AZ-DockerHost01`, reachable by tablets on `BV-Infra` at `http://10.0.0.4:<port>`, with a simple path to ship bugfixes and re-host new versions without hand-editing code on the VM.

**Recommended strategy (easiest that still works behind the jump box):**

1. **Containerise the app** (Dockerfile + production Compose: `web` + `db` + migrate).
2. **Local disk storage** on named/home volumes (no Vercel Blob).
3. **GitHub Actions** for test + image build → **GHCR**.
4. **One deploy script on the VM** (`git pull` of compose/env + `docker compose pull && up -d`) run over SSH from RDSH01 (or later a self-hosted runner).

Vercel can remain as a secondary demo host; **production floor is the Docker VM**.

---

## 2. Current state vs target

### 2.1 Stack (as built)

| Layer | Technology | Notes |
|-------|------------|--------|
| API / UI | FastAPI + Jinja2 + static JS | Dual HTML + JSON API |
| DB | PostgreSQL + SQLAlchemy async + Alembic | 3 migrations; enums + JSONB |
| PDF | WeasyPrint preferred, xhtml2pdf fallback; pypdf merge | System libs needed for WeasyPrint quality |
| Auth | Two shared logins (manager / operator), signed session cookie | Not SSO |
| Files | `STORAGE_BACKEND=local` or `blob` | Blob is Vercel-centric |
| Health | `GET /health` (liveness), `GET /ready` (DB) | Ready for compose healthchecks |
| CI | **None** (no `.github/workflows`) | |
| App container | **None** (no Dockerfile) | Compose only starts Postgres |

### 2.2 What the winery environment requires

From `DEPLOYMENT_ENVIRONMENT.md`:

| Constraint | Implication |
|------------|-------------|
| Snap Docker | Project + bind mounts under `/home/azureuser/…` only |
| Named volume for Postgres | Prefer `pgdata:` over host bind for DB data |
| Tablets: `10.110.77.0/24` → `10.0.0.4` | App must listen on **`0.0.0.0`**, published host port |
| Access is **HTTP over LAN** | Must **not** force secure cookies / HTTPS-only sessions |
| Admin path = RDP → RDSH01 → SSH | No public inbound to the Docker host today |
| BVPrintLAN not routed | Keep pallet-tag dispatch = **browser** (already default) |
| Outbound internet on host | Unconfirmed — required for first `docker pull` / build |

### 2.3 Gap list (must close for production-ready VM deploy)

| # | Gap | Severity | Action |
|---|-----|----------|--------|
| G1 | No Dockerfile / app service in Compose | **Blocker** | Add multi-stage image + `web` service |
| G2 | Migrations only via Vercel `build.py` | **Blocker** | Entrypoint or one-shot migrate container |
| G3 | `SessionMiddleware(https_only=settings.is_production)` | **Blocker for HTTP LAN** | When `DEBUG=false`, cookies become Secure → tablets on `http://10.0.0.4` **cannot stay logged in** |
| G4 | `is_production` ≈ “not debug / Vercel” | High | Split “production” from “TLS terminated” |
| G5 | Default secrets / passwords in code & `.env.example` | High | Host `.env` with strong values; refuse weak secrets in prod |
| G6 | Error copy assumes “Docker Desktop” | Low | Soften messages for VM ops |
| G7 | Vercel Blob as prod storage mental model | Medium | Force `STORAGE_BACKEND=local` + durable volume |
| G8 | WeasyPrint native deps not pinned in an image | Medium | Install in Dockerfile; prefer WeasyPrint in Linux |
| G9 | No backup/restore story for `pgdata` + uploads | Medium | Document dump + volume backup |
| G10 | No CI/CD | Medium | Minimal Actions + deploy script |
| G11 | Dev tools / seed routes | Low | Ensure `ENABLE_DEV_TOOLS=false` on host |
| G12 | Host outbound / docker group confirmations | Ops | Checklist with .nxt IT before first deploy |

---

## 3. Target architecture on the VM

```
BV-Infra tablets (10.110.77.x)
        │  HTTP
        ▼
BV-AZ-DockerHost01 (10.0.0.4)
  ┌─────────────────────────────────────────────┐
  │  /home/azureuser/bottling-app/              │
  │                                             │
  │  docker compose (project)                   │
  │    ┌──────────────┐    ┌─────────────────┐  │
  │    │ web :8000    │───▶│ db :5432        │  │
  │    │ FastAPI      │    │ postgres:16     │  │
  │    │ uvicorn      │    │ volume: pgdata  │  │
  │    └──────┬───────┘    └─────────────────┘  │
  │           │                                 │
  │    volume: app_data  (uploads + compiled)   │
  │    env_file: .env (secrets, not in git)     │
  └─────────────────────────────────────────────┘
```

**Recommended URL for tablets:** `http://10.0.0.4:8000`  
(Pick one published port; document it; keep firewall/Azure NSG open from tablet subnet only if .nxt requires.)

**Project layout on host (snap-safe):**

```
/home/azureuser/bottling-app/
  docker-compose.yml          # or docker-compose.prod.yml
  .env                        # secrets — mode 600, never commit
  deploy.sh                   # pull + migrate + up
  (optional) docker-compose.override.yml  # not used in prod
```

App image either:

- **Built on host** from a git checkout, or  
- **Pulled from GHCR** (preferred once CI exists): `ghcr.io/<org>/berton-bottling-app:<tag>`

---

## 4. Application / config changes required

These are code and repo changes before first production cutover. Order is intentional.

### 4.1 P0 — Session cookies on HTTP LAN (auth will fail without this)

**Problem:** In `app/main.py`:

```python
SessionMiddleware(..., https_only=settings.is_production, ...)
```

and `is_production` is true whenever `DEBUG=false`. Tablets use plain HTTP → browsers drop Secure cookies → login appears broken.

**Fix options (pick one; recommend A):**

| Option | Approach |
|--------|----------|
| **A (recommended)** | Add `SESSION_HTTPS_ONLY` / `COOKIE_SECURE` env (default `false`). Set `true` only when TLS is in front. Keep `DEBUG=false` in prod. |
| B | Derive from `FORCE_HTTPS` or presence of reverse proxy headers. |
| C | Terminate TLS on Nginx Proxy Manager (or similar) on the VM and keep Secure cookies. More moving parts; HTTPS not required for MVP. |

Also set session cookie `same_site="lax"` (already) and document that tablets must use the host IP URL consistently (no mixed hostname/IP).

### 4.2 P0 — Production Compose + Dockerfile

**Dockerfile (outline):**

- Base: `python:3.12-slim-bookworm` (or equivalent).
- Install WeasyPrint system packages: `libpango-1.0-0`, `libpangocairo-1.0-0`, `libcairo2`, `libgdk-pixbuf-2.0-0`, fonts (`fonts-dejavu-core`).
- Install app with `uv` or `pip` from `pyproject.toml` (+ lock if using uv).
- Optional: install WeasyPrint Python package as primary (optional-deps `pdf`).
- Non-root user if practical; writable dirs for `/data/uploads`, `/data/compiled`.
- `CMD`: wait-for-db → `alembic upgrade head` → `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`  
  **or** separate migrate one-shot service then web without migrate in CMD.

**`docker-compose.yml` (production-oriented, can replace or add `docker-compose.prod.yml`):**

```yaml
# Conceptual — implement in repo
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck: ...
    # Do NOT publish 5432 to the LAN in production unless needed for admin.
    # Dev may keep "5433:5432"; prod: no ports: or 127.0.0.1:5432:5432

  web:
    image: ghcr.io/.../berton-bottling-app:${APP_TAG:-latest}
    # or build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      STORAGE_BACKEND: local
      UPLOAD_DIR: /data/uploads
      COMPILED_OUTPUT_DIR: /data/compiled
      DEBUG: "false"
      SESSION_HTTPS_ONLY: "false"   # after 4.1
    ports:
      - "8000:8000"                 # host 0.0.0.0 implied
    volumes:
      - app_data:/data
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/ready"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  pgdata:
  app_data:
```

**Dev vs prod:** Keep current “Postgres-only + host uvicorn” for developer laptops via compose profiles or separate files:

- `docker-compose.yml` — full stack (prod-capable default).  
- `docker-compose.dev.yml` or profile `dev` — publish DB on 5433, optional bind-mount source for live reload.

### 4.3 P0 — Env contract for the VM

Extend `.env.example` with a **production LAN** section:

| Variable | Production value |
|----------|------------------|
| `DEBUG` | `false` |
| `SECRET_KEY` | long random (e.g. `openssl rand -hex 32`) |
| `MANAGER_*` / `OPERATOR_*` | strong passwords; change from defaults |
| `DATABASE_URL` | in-compose service hostname `db` |
| `STORAGE_BACKEND` | `local` |
| `UPLOAD_DIR` / `COMPILED_OUTPUT_DIR` | `/data/...` |
| `SESSION_HTTPS_ONLY` | `false` (until TLS) |
| `ENABLE_DEV_TOOLS` | `false` |
| `PALLET_TAG_DISPATCH` | `browser` |
| `VERCEL` | **unset** |

Optional guard: if `DEBUG=false` and `SECRET_KEY` is still the default, refuse to start (fail fast).

### 4.4 P1 — Production defaults without Vercel

Today many “production” behaviours key off `VERCEL`. For the VM:

- Treat `DEBUG=false` as production logging (`echo=False` already via debug).
- Do **not** redirect uploads to `/tmp` unless ephemeral (Vercel only).
- Keep blob backend available but unused on the winery host.

### 4.5 P1 — Migrations strategy

| Approach | Pros | Cons |
|----------|------|------|
| **Entrypoint script** (migrate then exec uvicorn) | Simple single service | Parallel replicas would race (N/A for single VM) |
| **One-shot `migrate` service** in compose | Clear separation | Extra compose service |

**Recommend entrypoint for single-host MVP.** Reuse logic from `build.py` (`alembic upgrade head`).

### 4.6 P1 — PDF rendering on Linux

- Image installs WeasyPrint deps → prefer WeasyPrint on the VM (better layout fidelity).
- xhtml2pdf remains fallback.
- Smoke-test compile on first deploy with a seed or real run.

### 4.7 P2 — Operational polish

- Soften `/ready` and 503 messages (“database unavailable” without Docker Desktop wording).
- Log structured startup: app version / git SHA env `APP_VERSION`.
- Consider `restart: unless-stopped` and log rotation (`json-file` max-size).
- Do not expose Postgres on the tablet LAN.
- Confirm OpenAPI/docs: leave `/docs` off or protect when not debug (optional).

### 4.8 Explicit non-goals for first VM cutover

- TLS / reverse proxy (proxy-ready later; D8 in roadmap).
- Direct network printing (BVPrintLAN closed).
- EzyWine live integration.
- Per-user SSO.
- Multi-host HA / scaling.
- Moving off shared manager/operator passwords (acceptable for LAN prototype).

---

## 5. Host setup checklist (first deploy)

Run as `azureuser` on `BV-AZ-DockerHost01` via RDSH01 SSH.

### 5.1 Prerequisites (.nxt / ops)

- [ ] `sudo docker pull hello-world` succeeds (outbound internet).
- [ ] `id` shows `docker` group; `docker ps` works without sudo.
- [ ] Disk space for images + Postgres + PDF uploads (plan ≥ 20–40 GB free).
- [ ] Tablet on `BV-Infra` can open `http://10.0.0.4:8000/health` after publish.
- [ ] Confirm Azure NSG / pfSense does not block 8000 from `10.110.77.0/24`.

### 5.2 First-time install (build-on-host path — simplest day-one)

```bash
# On BV-AZ-DockerHost01
mkdir -p /home/azureuser/bottling-app
cd /home/azureuser/bottling-app

# Clone (deploy key or HTTPS PAT with read access)
git clone https://github.com/Woodsy2660/Bertons-Production-app.git .

# Create secrets
cp .env.example .env
# edit .env: SECRET_KEY, passwords, DEBUG=false, SESSION_HTTPS_ONLY=false, etc.
chmod 600 .env

# Build and start
docker compose up -d --build

# Verify
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/ready
docker compose logs -f web   # watch migrations + boot
```

From a tablet on `BV-Infra`: open `http://10.0.0.4:8000`, log in as manager, create a test run, upload a work order, compile smoke path.

### 5.3 Data durability

| Data | Location | Backup |
|------|----------|--------|
| Postgres | named volume `pgdata` | nightly `pg_dump` to `/home/azureuser/backups/` (or Azure backup) |
| Uploads + compiled PDFs | named volume `app_data` | rsync/tar same backup dir |
| Secrets | `/home/azureuser/bottling-app/.env` | store copy in Hudu (with .nxt), not git |

Backup sketch (cron on host):

```bash
# conceptual
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > ~/backups/berton-$(date +%F).sql.gz
```

---

## 6. How to fix bugs and re-host after go-live

### 6.1 Golden rule

**Never edit application source on the VM as the primary workflow.**  
Fix in git → ship a new image/tag → redeploy. VM holds only: compose file, `.env`, volumes, deploy script.

### 6.2 Developer fix loop (day-to-day)

```
1. Reproduce locally (docker compose + pytest)
2. Branch → fix → tests
3. PR → merge to main (or release branch)
4. CI builds image :main or :vX.Y.Z  →  GHCR
5. On VM: ./deploy.sh vX.Y.Z   (or latest)
6. Verify /health /ready + smoke login on tablet
```

### 6.3 Deploy script behaviour (`deploy.sh`)

Idempotent operations:

1. `cd` project root under home.
2. Optionally `git pull` (if compose/env templates live in repo).
3. `export APP_TAG=$1` (default `latest` or previous pin).
4. `docker compose pull` (if using registry images).
5. `docker compose up -d` (recreate web; db stays up).
6. Migrations run via entrypoint on new web container.
7. `curl` health/ready; print recent logs on failure.

**Rollback:**

```bash
./deploy.sh <previous-good-tag>
```

Postgres migrations must stay **forward-compatible** or you document a restore-from-dump path for breaking changes. Prefer expand/contract migrations (additive columns first).

### 6.4 Hotfix when CI is down (escape hatch)

Only if registry/CI unavailable:

```bash
cd /home/azureuser/bottling-app
git fetch && git checkout <commit>
docker compose up -d --build
```

Still no hand-editing of Python on the host.

### 6.5 Config-only changes

Passwords, feature flags, tag dispatch:

1. Edit `.env` on host.
2. `docker compose up -d` (recreate web to pick up env).
3. No image rebuild.

### 6.6 Database / data issues

| Issue | Action |
|-------|--------|
| Bad migration | Fix migration in git; if already applied, write a new migration — avoid `downgrade` on prod without backup |
| Corrupt upload | Replace file in volume or re-upload via UI |
| Need reset (dev only) | `docker compose down -v` **destroys data** — never on live floor without approval |
| Restore | Stop web → restore dump into db → start web |

### 6.7 Who can deploy

| Role | Access |
|------|--------|
| Developer | GitHub push; may not have Azure SSH yet |
| Ops / lead | RDSH01 RDP + SSH to `10.0.0.4` |
| Future | Self-hosted runner on Docker host runs `deploy.sh` on green main |

Until SSH keys leave RDSH01, **a human (or scheduled job on RDSH01/host) must run deploy**. Design CI so that “merge to main” only *publishes* an image; “go live” is one command.

---

## 7. CI/CD plan — easiest path that fits this network

### 7.1 Constraint

GitHub-hosted runners **cannot** reach `10.0.0.4` (private Azure + jump box).  
Therefore **auto-SSH deploy from GitHub.com is not available** until either:

- a **self-hosted runner** on the Docker host (or RDSH01), or  
- a **direct VPN/SSH route** + deploy key from CI.

Do not block first production on that. Ship **build in CI + pull on host**.

### 7.2 Recommended pipeline (minimal)

```
┌──────────── dev workstation ────────────┐
│  push branch → PR                        │
└─────────────────┬───────────────────────┘
                  ▼
┌──────────── GitHub Actions ─────────────┐
│  1. checkout                            │
│  2. uv/pip install + pytest             │
│  3. docker build                        │
│  4. push ghcr.io/.../app:$sha and :main │
└─────────────────┬───────────────────────┘
                  ▼
┌──────────── BV-AZ-DockerHost01 ─────────┐
│  deploy.sh pulls tag + compose up -d    │
│  (manual SSH from RDSH01, or later      │
│   self-hosted runner / cron)            │
└─────────────────────────────────────────┘
```

### 7.3 Workflow files to add

**`.github/workflows/ci.yml`**

- Trigger: PR + push to `main`
- Job: Python 3.12, Postgres service, `alembic upgrade head`, `pytest`
- Optional: Node not required (only small mjs test — can skip or run separately)

**`.github/workflows/image.yml`**

- Trigger: push to `main` + tags `v*`
- `docker/build-push-action` → `ghcr.io/Woodsy2660/bertons-production-app`
- Tags: `sha`, `main`, semver
- Permissions: `packages: write`

### 7.4 Host authentication to GHCR

One-time on VM:

```bash
echo $GHCR_TOKEN | docker login ghcr.io -u USER --password-stdin
```

Token stored in `~/.docker/config.json` under `azureuser` home (snap-friendly). Prefer a fine-grained PAT or GitHub App with `read:packages` only for pull.

### 7.5 Upgrade path (when ops want hands-free deploys)

| Stage | What | Effort |
|-------|------|--------|
| **0 (day one)** | Build on host from git | Lowest |
| **1 (recommended soon)** | CI image + manual `deploy.sh` | Low |
| **2** | Self-hosted Actions runner on Docker host; on `main` → deploy | Medium; needs .nxt buy-in (runner = code exec on prod host) |
| **3** | TLS reverse proxy + optional hostname DNS on LAN | Later |

**Avoid for this environment:**

- Complex Kubernetes / Swarm.
- Deploying *from* Vercel to the VM.
- Requiring developer laptops to open inbound ports.
- Storing production `.env` in the GitHub repo.

### 7.6 Branch / release policy (keep simple)

| Branch / tag | Meaning |
|--------------|---------|
| `main` | Always deployable; CI green required |
| `v1.2.3` tags | Optional production pins for rollback |
| feature branches | PR only; no host deploy |

Floor deploys should pin a **tag or SHA**, not floating `latest`, once live runs matter — update `APP_TAG` in `.env` or pass to `deploy.sh`.

---

## 8. Merge / implementation work breakdown

Treat as a short stack of PRs (can be one PR if small team).

### PR1 — Production config safety (app)

- [ ] `SESSION_HTTPS_ONLY` (or equivalent) wired to `SessionMiddleware`
- [ ] Clarify `is_production` vs cookie secure vs Vercel
- [ ] Startup check for default `SECRET_KEY` when `DEBUG=false`
- [ ] `.env.example` production LAN section
- [ ] Tests for config / cookie flag

### PR2 — Containerisation

- [ ] `Dockerfile` (+ `.dockerignore`)
- [ ] `docker-compose.yml` full stack; keep easy local DB port for dev (profile or override)
- [ ] Entrypoint: migrate → uvicorn `0.0.0.0:8000`
- [ ] Named volumes `pgdata`, `app_data`
- [ ] `deploy.sh` + short `Documentation` runbook section (or this doc §5–6)
- [ ] Healthcheck using `/ready`

### PR3 — CI/CD

- [ ] `.github/workflows/ci.yml` (pytest + Postgres)
- [ ] `.github/workflows/image.yml` (GHCR)
- [ ] Document GHCR login + `APP_TAG` on host

### PR4 — Ops soft landing (optional same sprint)

- [ ] Neutral 503 / ready hints
- [ ] `APP_VERSION` env from image label
- [ ] Backup script under `scripts/backup-prod.sh`

### Cutover (not a PR)

- [ ] .nxt checklist (internet, routes, docker group)
- [ ] First deploy on VM
- [ ] Tablet E2E: login → create run → form entry → compile → download
- [ ] Credentials handed to managers via Hudu
- [ ] Disable or ignore Vercel as system-of-record for floor data

---

## 9. Risk register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Secure cookies on HTTP | Login broken on all tablets | §4.1 — ship before go-live |
| Snap bind-mount outside home | Containers fail mysteriously | Only home paths + named volumes |
| No host outbound | Cannot pull base images | Confirm with .nxt; pre-load images if needed |
| Data loss on `compose down -v` | Production runs gone | Document; backups; never `-v` in runbooks |
| Breaking Alembic migration | App won't start | CI runs migrations; backups before deploy |
| Image registry auth expiry | Deploy fails | Calendar reminder; pull-only token |
| Single VM | Host down = app down | Accept for MVP; Azure VM backup |
| Shared passwords | Credential sharing | LAN-only + change defaults; later SSO |
| Concurrent deploys | Partial state | One deployer; compose recreate single web |

---

## 10. Success criteria (production-ready)

1. `docker compose ps` shows `db` + `web` healthy on `BV-AZ-DockerHost01`.
2. `curl http://127.0.0.1:8000/ready` → `database: connected`.
3. Tablet on `BV-Infra` reaches login at `http://10.0.0.4:8000` and **session sticks** after login.
4. Manager creates a run, operators edit forms, manager compiles PDF, download works.
5. Redeploy of a new image/tag completes in &lt; 5 minutes without data loss (existing batches remain).
6. Rollback to previous tag works.
7. Secrets not in git; `ENABLE_DEV_TOOLS=false`.
8. Documented backup taken at least once successfully.

---

## 11. Relation to existing docs

| Doc | Role after this plan |
|-----|----------------------|
| `00`–`06` | Product/spec prototype scope |
| `07` | As-built app behaviour |
| `DEPLOYMENT_ENVIRONMENT.md` | Network / host facts (source of truth for topology) |
| **This file (`08`)** | How we containerise, secure config, ship, and operate on that host |

Update `Documentation/README.md` index to include `08` when this plan is accepted.

---

## 12. Suggested immediate next steps

1. **Implement PR1 cookie/config fix** — without it, production `DEBUG=false` on HTTP will look “broken”.
2. **Implement PR2 Dockerfile + prod compose** and prove on a local Docker Desktop full-stack up.
3. **Verify .nxt open items** (outbound pull, tablet curl to host).
4. **First host deploy** with build-on-host if GHCR not ready.
5. **Add CI + GHCR**, switch host to `pull` + `deploy.sh`.
6. Only then consider self-hosted runner automation.
