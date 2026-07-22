# QA Execution Report — Berton Bottling App

**Plan:** [`TEST_PLAN.md`](../TEST_PLAN.md)  
**Executed:** 2026-07-14  
**Target:** `http://127.0.0.1:8001` (local worktree + Docker Postgres)  
**Agents:** parallel (orchestrator + security subagent + concurrency subagent)

---

## 1. Executive summary

| Area | Result | Notes |
|------|--------|--------|
| **Smoke (§2.4)** | **PASS** | health/ready/login/dashboard &lt; 1s |
| **Unit + integration (§2.1–2.2)** | **PASS** | `49 passed` in 6.7s |
| **Authz / RBAC (§2.11)** | **PASS** | 7/7 live matrix checks |
| **Concurrency (§2.10)** | **PASS*** | 15 sessions, 0×5xx; *sequence race observed* |
| **Multi-user load (≥20)** | **PASS** | **20/20** and **30/30** sessions OK, 0×5xx |
| **Security light (§2.7 offline)** | **WARN** | Cookie/secrets OK; Bandit B701 + dep CVEs |
| **App survives load** | **PASS** | `/health` + `/ready` 200 after all runs |

**Go-live blockers found in this pass:** none that prevent continued local QA.  
**Must-fix before production:** accrual `sequence` race; dual-compile acceptance; dependency upgrades; PDF Jinja autoescape review.

---

## 2. Handoff checklist (TEST_PLAN §10)

| Item | Status |
|------|--------|
| Repo access + Compose Postgres | **Done** — `berton-postgres` healthy, app on `:8001` |
| Sample fixtures / work orders | **Partial** — fixtures under `tests/fixtures/work_orders/` |
| Golden PDF baselines | **Not done** this run |
| Acceptance criteria per form | **Not confirmed** with directors |
| Physical Tab A9+ on BV-Infra | **Out of scope** (local only) |
| CI secrets | **N/A** this run |
| Backup/restore drill | **Not done** |
| Plan in repo | **Done** — `TEST_PLAN.md` copied into worktree |

---

## 3. Results by plan category

### 2.1 / 2.2 Unit & integration — **PASS**

```text
python -m pytest tests/ -q
49 passed in 6.73s
```

Covers auth credentials, lifecycle state helpers, form persistence, storage, config, document management, work-order parser, prefill/pallet tags (as present in suite).

### 2.4 Smoke — **PASS**

Script: `scripts/qa_smoke_live.py`

| Check | Result |
|-------|--------|
| `/health` | 200 |
| `/ready` | 200 (DB connected) |
| `/login` | 200 |
| Manager login | 303 |
| Dashboard | 200 |
| Duration | 0.99s |

### 2.11 Authorization — **PASS**

Script: `scripts/qa_authz_live.py`

| Check | Result |
|-------|--------|
| Operator dashboard | 200 |
| Operator `/batches/new` | **403** (blocked) |
| Manager `/batches/new` | 200 |
| Anon `/api/batches` | **401** |
| Anon `/health` | 200 |
| Operator compile | **403** |
| Operator reopen | **403** |

### 2.10 Concurrency — **PASS** (with findings)

Script: `scripts/qa_concurrency_race.py`  
Detail: `qa_concurrency_results.md`

| Metric | Value |
|--------|--------|
| Sessions | 10 operator + 5 manager |
| Concurrent writes (same form) | 15/15 → 200 |
| HTTP 5xx | **0** |
| Postflight health/ready | 200/200 |
| Unique reading IDs | 15 (no lost rows) |
| **Duplicate sequences** | **Yes** (e.g. seq 2×5, 9×4) |
| Dual compile race | both **303**, no 5xx |

**Defect (Medium → High if PDF order depends on sequence):** concurrent accrual inserts can assign the same `sequence` number. Recommend DB unique constraint + atomic sequence allocation.

### 2.6 Multi-user performance / survival (≥20 users) — **PASS**

Script: `scripts/qa_multi_user_load.py`

#### Run A — 20 concurrent users × 3 iterations

| Metric | Value |
|--------|--------|
| Sessions OK | **20 / 20** (100%) |
| Wall clock | 22.1s |
| HTTP samples | 407 |
| Latency p50 / p95 / max | 504 / 1623 / 10353 ms |
| Status mix | 200×330, 303×20, 403×57 (expected RBAC denials) |
| 5xx | **0** |
| Postflight | healthy + ready |

#### Run B — 30 concurrent users × 2 iterations (boundary)

| Metric | Value |
|--------|--------|
| Sessions OK | **30 / 30** (100%) |
| Wall clock | 19.5s |
| HTTP samples | 417 |
| Latency p50 / p95 / max | 480 / 3342 / 9230 ms |
| 5xx | **0** |
| Postflight | healthy + ready |

**Interpretation:** App and Postgres survive **≥20 concurrent shared-login sessions** with mixed operator/manager traffic (dashboard, batch detail, forms, accrual POSTs). Tail latency spikes under burst (max ~10s) — acceptable for LAN pilot but watch WeasyPrint/compile if many managers compile at once (not stressed equally in this script).

### 2.7 Security (offline slice) — **WARN**

Detail: `qa_security_results.md`

| Check | Result |
|-------|--------|
| Secrets in `app/` | PASS (dev defaults only; prod guards exist) |
| Cookie Secure / LAN HTTP | PASS (`cookie_https_only` correct) |
| Bandit | WARN — Jinja PDF env autoescape (B701) |
| pip-audit (project-ish) | WARN — upgrade starlette / pydantic-settings et al. |

### Not executed this session (explicit gaps)

| Category | Why skipped |
|----------|-------------|
| 2.8 Playwright E2E | No Playwright suite wired; timeboxed to API/session load |
| 2.9 Golden PDF integrity | No golden baseline process automated this pass |
| 2.12 Resilience (kill DB mid-flight) | Not run (would disrupt ongoing work) |
| 2.13 Backup/restore | No backup target configured |
| 2.14 Migration upgrade/downgrade matrix | Alembic head assumed current; no empty-DB rebuild |
| 2.15 Overnight soak | Needs overnight window |
| 2.16 Physical tablet / gloves UAT | Requires floor device |

---

## 4. Defect log (this run)

| ID | Sev | Area | Summary |
|----|-----|------|---------|
| QA-001 | **High** | Concurrency / data integrity | Concurrent accrual readings can share the same `sequence` (race on count+1). Rows not lost, but compliance ordering at risk. |
| QA-002 | **Medium** | Lifecycle | Simultaneous compile POSTs both returned 303 — confirm single current compilation / no double-lock side effects. |
| QA-003 | **Medium** | Security / deps | Known CVEs in starlette / pydantic-settings and related transitive packages. |
| QA-004 | **Medium** | Security / PDF | Bandit B701: PDF Jinja `Environment` without autoescape. |
| QA-005 | **Low** | Performance | Under 20–30 concurrent sessions, max latency ~9–10s on some requests (p95 still multi-second under burst). |

---

## 5. Multi-agent usage

| Agent | Role | Outcome |
|-------|------|---------|
| Orchestrator (this session) | Smoke, pytest, authz live, 20/30 user load, report | PASS |
| Security subagent | Bandit, pip-audit, secrets, cookie review | WARN report |
| Concurrency subagent | 15-session race + dual compile | PASS + QA-001/002 |

---

## 6. How to re-run

```powershell
# Ensure Postgres + app
docker start berton-postgres
$env:DATABASE_URL = "postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# Suite
python -m pytest tests/ -q
python scripts/qa_smoke_live.py
python scripts/qa_authz_live.py
python scripts/qa_concurrency_race.py
python scripts/qa_multi_user_load.py --users 20 --iterations 3
python scripts/qa_multi_user_load.py --users 30 --iterations 2
```

Artifacts:

- `qa_pytest_results.txt` (if captured)
- `qa_smoke_results.txt`
- `qa_authz_results.txt`
- `qa_load_20_results.txt`
- `qa_load_30_results.txt`
- `qa_concurrency_results.md`
- `qa_security_results.md`
- `scripts/qa_*.py`

---

## 7. Exit criteria vs TEST_PLAN §7 (this pass)

| Criterion | Status |
|-----------|--------|
| Critical flows have automated coverage | **Partial** — lifecycle/auth/forms unit; full compile golden incomplete |
| PDF integrity golden green | **Not run** |
| Full role×action matrix green | **Partial** — live subset PASS |
| Restore drill succeeded | **Not run** |
| Smoke on target env | **PASS** (local) |
| **≥20 concurrent users survive** | **PASS** (20 and 30) |

**Recommendation:** Treat local multi-user survival as **PASS** for pilot concurrency. Fix **QA-001** before floor go-live with many tablets writing the same accrual form. Schedule PDF golden suite + backup drill next.
