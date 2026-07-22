# REMAINING_TESTS — Execution Report

**Source:** `REMAINING_TESTS.md`  
**Executed:** 2026-07-14  
**Target:** `http://127.0.0.1:8001` + Docker Postgres  

**Standing rule applied:** assertions use **database / data state**, not “no 5xx” alone.

---

## Summary

| ID | Status | Notes |
|----|--------|--------|
| **TEST-C1** Accrual sequence integrity | **PASS** | 15 sessions × 3 rounds; sequences unique + contiguous; count match |
| **TEST-C2** Single current compilation | **PASS*** | ≤1 `is_current` under concurrent compile; *successful* compile path needs ezywine-ready batch (got 400) |
| **TEST-C3** Cross-path races | **PASS** | Terminal states coherent; no half-applied corruption observed |
| **TEST-P1** Golden PDF integrity | **NOT RUN** | Still zero golden baseline; blocked by fixture effort this session |
| **TEST-P2** Kill-DB / restart | **PASS** | DB stop → ready 503; write fails loudly; recover ready + dashboard |
| **TEST-P3** Backup/restore drill | **NOT RUN** | No off-VM backup target |
| **TEST-E1** Playwright E2E | **NOT RUN** | No Playwright harness |
| **TEST-E2** Latency thresholds | **PARTIAL** | p50 OK, max OK, **p95 3098ms > 3000ms** (marginal FAIL) |
| **TEST-E3** Soak overnight | **NOT RUN** | Needs multi-hour window |
| **TEST-E4** Physical tablet | **NOT RUN** | Needs Tab A9+ on BV-Infra |
| **TEST-S1** PDF autoescape | **PASS** | `autoescape=True` in compile_batch; markup escaped |
| **TEST-S2** Dependency CVEs | **NOT RUN** | Bumps deferred (upgrade PR) |

**pytest:** 49 baseline tests green; new `tests/test_reading_sequence_concurrency.py` (20 concurrent writers, data asserts).

---

## §1 Fixes shipped

### QA-001 — Accrual sequence race
- Migration `d4e8f1a2b903`: **unique** `(form_instance_id, sequence)` on `readings`
- `add_reading`: transaction-scoped **`pg_advisory_xact_lock`** + `MAX(sequence)+1` + IntegrityError retries
- Pool size increased to 20 for concurrent tablets
- Renumber-on-delete is two-phase (avoids unique collisions)

### QA-002 — Double current compilation
- Partial unique index: **one `is_current=true` per batch**
- Compile route: `SELECT … FOR UPDATE` on batch; **409** if already `COMPLETE`

### TEST-S1
- PDF Jinja `Environment(..., autoescape=True)`

---

## Data-level results (C1)

```
15 concurrent sessions × 3 iterations = 45 successful POSTs
before=99 after=144 added=45
sequences: unique, contiguous 1..M, stable re-read
0 duplicate sequences
```

Live probe: 15/15 concurrent POSTs → 200 after fix (was ~50% 500 under race).

---

## Exit gate (REMAINING_TESTS)

| Gate | Met? |
|------|------|
| C1–C3 data-level | **Yes** (C2 compile-success path incomplete without ready batch) |
| P1 golden PDF | **No** |
| P2 resilience | **Yes** (local docker stop/start) |
| P3 restore | **No** |
| E1 double-submit UI | **No** |
| E2 latency bounds | **No** (p95 slightly over 3s) |
| S1 autoescape | **Yes** |
| S2 CVEs cleared | **No** |
| E3/E4 | **No** / risk-accept pending |

**Floor go-live:** still **NO-GO** until at least P1 golden PDF + P3 restore + E1 double-submit are closed (or risk-accepted in writing).

---

## Artifacts

| File | Purpose |
|------|---------|
| `REMAINING_TESTS.md` | Instructions (copied into repo) |
| `scripts/qa_remaining_c1_c2_c3.py` | Data-level C1–C3 runner |
| `scripts/qa_remaining_p2_s1_e2.py` | P2 / S1 / E2 runner |
| `qa_remaining_c1_c2_c3.txt` | C1–C3 log |
| `qa_remaining_p2_s1_e2.txt` | P2/S1/E2 log |
| `alembic/versions/d4e8f1a2b903_concurrency_guards.py` | DB guards |
| `tests/test_reading_sequence_concurrency.py` | Regression |

### Re-run

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling"
$env:PYTHONPATH = "."
python -m alembic upgrade head
python -m pytest tests/ -q
python scripts/qa_remaining_c1_c2_c3.py --sessions 15 --iterations 3
python scripts/qa_remaining_p2_s1_e2.py
```
