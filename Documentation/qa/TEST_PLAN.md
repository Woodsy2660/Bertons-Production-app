# Test Plan — Berton Vineyards Bottling App

Handoff document. Defines the testing strategy for pressure-testing the
application before and after go-live. Written to be actionable by a developer,
QA engineer, or coding agent picking this up cold.

**Guiding premise:** this is a **compliance and traceability system**, not a
consumer app. The failures that matter most are *silent*: incorrect data on a
compiled PDF, a lost form entry, or an unauthorised state change. Testing effort
is therefore **risk-weighted** (see §3), not spread evenly across categories.

---

## 1. System under test

FastAPI (async) + async SQLAlchemy + Alembic + PostgreSQL, Jinja2 server-rendered
UI, WeasyPrint (HTML→PDF), pypdf/pikepdf (PDF assembly), pdfplumber (work-order
extraction). Runs containerised (Docker Compose) on an Azure Linux VM; accessed
over HTTP LAN by mounted tablets.

**Critical flows** (these drive test priority):
- Nine station forms in two patterns — **atomic** (single submission) and
  **accrual** (accumulated over time). Different failure modes each.
- **16-slot PDF compilation** — assembling station outputs into one compliance PDF.
- **Lock-on-compile + manager reopen** — a state machine with role-gated transitions.
- **Work-order extraction** (pdfplumber) prefilling forms from uploaded work orders.
- **Shared logins** (manager / operator) with RBAC and record attribution.
- **Pallet-tag printing** (currently browser dispatch; network printer out of scope).

---

## 2. Test types

The seven requested, **plus eight more** this app needs. Each entry states what
it covers *for this app*, concrete targets, tooling, and where it runs.

### Requested

**2.1 Unit testing** — functions/modules in isolation.
Targets: accrual accumulation logic, form validation rules, the lock/reopen state
machine (allowed vs forbidden transitions), timezone/timestamp handling, PDF-slot
mapping logic, work-order field parsers, any calculation that lands on a
compliance record. Mock the DB and filesystem.
Tools: `pytest`, `pytest-asyncio`, `freezegun` (time), `hypothesis` (property-based
tests for parsers and numeric logic). Runs: every commit / pre-push.

**2.2 Integration testing** — modules + APIs + real dependencies.
Targets: FastAPI endpoints against a **real Postgres** (not mocked), Alembic
migrations applied to a fresh DB, async SQLAlchemy session/transaction behaviour,
WeasyPrint actually rendering a PDF, pikepdf actually merging slots. Test the
seams, not the units.
Tools: `httpx.AsyncClient` (ASGI transport), `testcontainers`/`pytest-postgresql`
for an ephemeral DB, `pytest`. Runs: every PR in CI.

**2.3 Functional & acceptance testing** — meets business requirements.
Targets: each station form's rules end-to-end; a full run: create run → complete
all stations → compile → download correct PDF; manager reopen → edit → recompile;
work-order upload → correct prefill. Written as user-facing scenarios with
explicit pass criteria tied to requirements (see §8 traceability).
Tools: `pytest` (API-level) + Playwright (UI-level, see 2.8). Runs: PR + pre-deploy.

**2.4 Smoke testing** — fast post-build sanity.
Targets: app boots, `/health` and `/ready` return OK, DB reachable + migrations
current, login works, one form renders, a trivial compile succeeds, a PDF is
produced. Must complete in well under a minute.
Tools: `pytest -m smoke`, a `deploy.sh` post-deploy curl script. Runs: after every
build and immediately after every VM deploy.

**2.5 Regression testing** — new code doesn't break old behaviour.
Approach: every fixed bug gets a test that reproduces it (regression corpus);
full suite runs on each PR; PDF outputs use **golden-file/snapshot** comparison so
subtle rendering or data-mapping drift is caught (this is high value here — a
one-cell shift in a compiled PDF is a compliance defect).
Tools: `pytest`, `syrupy`/snapshot fixtures, checksum/visual diff on generated PDFs.
Runs: every PR.

**2.6 Performance testing** — speed, scalability, stability.
Targets & realistic scale: this is a small-team LAN app (a handful of concurrent
tablets, not thousands), so tune expectations accordingly. Measure: form
save/load latency on the tablet path; **PDF compile time** under concurrent
compiles (WeasyPrint is CPU/memory heavy — the real bottleneck); DB under
concurrent accrual writes; memory/CPU headroom on the single VM.
Tools: `Locust` or `k6` (load), `pytest-benchmark` (hot paths), host `docker stats`
during runs. Include a **soak test** (2.15). Runs: nightly / pre-deploy, not per-PR.

**2.7 Security testing** — SAST + DAST.
SAST: static scan of code and dependencies. DAST: exercise the running app for
injection, auth bypass, session issues, CSRF, insecure headers. **Explicitly test
the HTTP-only cookie decision** (session must survive over plain HTTP on the LAN
without weakening beyond the accepted risk) and confirm no secrets in the image or
git. Pair with Authorization testing (2.11).
Tools: `Bandit` (Python SAST), `pip-audit`/`Safety` (dependency CVEs), `Semgrep`
(rules), `OWASP ZAP` (DAST), `gitleaks`/`trufflehog` (secret scan), `trivy`
(container image scan). Runs: SAST + dep + secret + image scan every PR; ZAP
nightly against staging.

### Additional (recommended — your list is missing these)

**2.8 End-to-end / UI automation** — the real tablet journeys in a browser.
Distinct from functional API tests: drives the actual Jinja UI as an operator
would. Targets: complete-a-run journey, offline/again-online mid-form, lock banner
appears and disables fields, manager-only controls hidden/blocked for operators,
double-tap doesn't double-submit. Run against the tablet viewport (landscape) and
Chrome (the tablet's browser engine).
Tools: `Playwright`. Runs: PR (headless) + pre-deploy.

**2.9 Data integrity & PDF output validation** — *the top-priority category.*
The compiled PDF is the compliance artifact; it must be **correct**, not just
present. Targets: every value entered maps to the correct slot/field in the
output; all 16 slots assemble in the right order; missing/partial slots are
handled explicitly (never silently blank); numbers, units, dates, and batch/run
identifiers render exactly as entered; recompile after reopen reflects the edit;
extracted work-order data matches source. Verify by extracting text/values back
out of the produced PDF and asserting against the input — not by eyeballing.
Tools: `pypdf`/`pdfplumber` to read back the output, golden-file snapshots,
field-level assertions. Runs: PR + pre-deploy. **Highest coverage target.**

**2.10 Concurrency & race-condition testing** — accrual + shared logins.
Accrual forms accumulate over time and may be touched by more than one session;
shared logins make concurrent use likely. Targets: two sessions writing the same
accrual form (no lost updates, no double-count), simultaneous compile attempts,
compile racing an in-flight edit, reopen racing a save. Assert DB-level
consistency and correct locking/optimistic-concurrency behaviour.
Tools: `pytest` with concurrent async clients, DB isolation-level tests. Runs: PR.

**2.11 Authorization / RBAC testing** — role boundaries are a hard requirement.
Targets: operator cannot reopen a locked form, cannot access manager-only views or
endpoints (test at the **API level**, not just hidden UI — hidden ≠ protected);
manager actions are attributed (who/when recorded); every state transition is
gated by the correct role. Enumerate the full role × action matrix and assert
each cell.
Tools: `pytest` parametrised over roles. Runs: PR. Treat failures as blockers.

**2.12 Resilience / fault-injection / recovery** — the floor is hostile.
Targets: **Wi-Fi drop mid-entry** (does in-progress data survive or fail safely,
with a clear message — never silent loss?), DB connection lost and restored,
container restart / VM reboot brings the app back with data intact, WeasyPrint
crash on a bad input doesn't take the app down. Verify the `restart:
unless-stopped` + healthcheck behaviour from the deployment plan.
Tools: manual + scripted fault injection (kill DB container, drop network,
`docker restart`), chaos-style checks. Runs: pre-deploy + after infra changes.

**2.13 Backup & restore (DR) testing** — a backup you haven't restored isn't one.
Targets: `pg_dump` + uploads backup completes; **restore into a clean
environment** reproduces full state; documented RPO/RTO are actually met; backup
destination is off the app VM (BVNASLAN candidate — route dependent). This is a
drill, run on a schedule, not a one-off.
Tools: the backup script + a scripted restore drill. Runs: pre-go-live, then
scheduled.

**2.14 Database migration testing** — Alembic up *and* down.
Targets: `alembic upgrade head` on a fresh DB and on a populated DB; downgrade
paths where supported; migrate-on-boot ordering (web waits for DB ready); a Postgres
**major-version pin** so the data volume stays readable. Guards the "migrate then
serve" entrypoint.
Tools: `pytest` + `testcontainers`, migration-specific fixtures. Runs: PR + pre-deploy.

**2.15 Soak / endurance testing** — long-running-container stability.
Targets: run under steady load for hours/overnight; watch for memory leaks
(WeasyPrint/async sessions are the usual suspects), unbounded container-log growth
filling the disk, connection-pool exhaustion, file-descriptor leaks from PDF
generation. Complements 2.6.
Tools: `Locust`/`k6` sustained, host resource monitoring. Runs: nightly / pre-go-live.

**2.16 Accessibility, compatibility, usability, timezone** — grouped; each small
but real for a floor tablet:
- **Accessibility:** touch targets ≥48px (56 primary), contrast AA+, status never
  colour-only (greyscale-usable), visible focus — per the UI/UX Standard. Tools:
  `axe-core`/Playwright-axe, manual greyscale check.
- **Compatibility / device:** the actual Samsung Galaxy Tab A9+, its Chrome
  version, landscape *and* portrait, on the `BV-Infra` network. Emulators find
  layout bugs; the physical mounted tablet finds the real ones.
- **Usability:** short sessions with real operators **wearing gloves** on the
  floor. Unscripted. Finds mis-taps, unreadable-under-glare, and confusing copy
  that no automated test will.
- **Timezone/timestamp correctness:** records and PDF timestamps render in
  Australia/Sydney, not container-default UTC — a compliance-visible defect if
  wrong. Assert explicitly.

Also fold in **exploratory testing** (unscripted, curiosity-driven — catches what
scripted suites miss) and a formal **UAT sign-off** with the directors/managers
against acceptance criteria before go-live.

---

## 3. Risk-weighted priority

Not all categories get equal effort. Weighting for a compliance app:

| Priority | Categories | Rationale |
| -------- | ---------- | --------- |
| **P0 — must be exhaustive** | 2.9 Data/PDF integrity · 2.11 Authorization · 2.12 Resilience (data-loss paths) · 2.13 Backup/restore | Silent corruption, unauthorised state change, and lost/unrecoverable data are the failures with real compliance and traceability consequences. |
| **P1 — thorough** | 2.1 Unit · 2.2 Integration · 2.3 Functional/acceptance · 2.10 Concurrency · 2.14 Migrations · 2.7 Security | Core correctness and the seams where this stack breaks. |
| **P2 — solid coverage** | 2.4 Smoke · 2.5 Regression · 2.8 E2E · 2.16 a11y/compat/tz | Guard rails and the tablet reality. |
| **P3 — right-sized** | 2.6 Performance · 2.15 Soak · usability · exploratory · UAT | Real but scaled to a small-team LAN app; don't over-engineer load for a handful of tablets. |

---

## 4. Environments & test data

- **Local:** full stack via Docker Compose; ephemeral Postgres per test run.
- **CI:** GitHub Actions with a Postgres service / testcontainers.
- **Staging = the VM:** deploy candidate build to `BV-AZ-DockerHost01`, run smoke +
  E2E + resilience against it before promoting.
- **Test data:** a fixture set of representative runs, all nine station forms
  (atomic + accrual), and **real sample work orders** for extraction tests
  (sanitised). Golden PDFs stored as regression baselines. Never test against
  production compliance data.

---

## 5. CI/CD integration (when each runs)

| Stage | Runs |
| ----- | ---- |
| Pre-commit / pre-push | lint, unit (2.1), smoke subset |
| Every PR | unit, integration, functional, concurrency, authz, migrations, regression, E2E (headless), SAST + dep + secret + image scan, a11y |
| Nightly | DAST (ZAP), performance, soak, full E2E matrix |
| Pre-deploy (to VM) | smoke, PDF-integrity, resilience, migration-on-populated-DB, backup/restore drill |
| Post-deploy (on VM) | smoke curl script against `/health`, `/ready`, one live compile |

Note from the deployment plan: GitHub-hosted runners can't reach `10.0.0.4`, so
on-VM stages run via the manual/`deploy.sh` path (or a future self-hosted runner),
not auto-SSH from CI.

---

## 6. Tooling summary

| Purpose | Tool |
| ------- | ---- |
| Test runner / async | pytest, pytest-asyncio |
| API/integration | httpx AsyncClient, testcontainers / pytest-postgresql |
| Property-based / fuzz | hypothesis, schemathesis (API schema fuzzing) |
| Time control | freezegun |
| UI / E2E | Playwright (+ playwright-axe) |
| PDF validation | pypdf, pdfplumber, snapshot/golden files |
| Load / soak | Locust or k6, pytest-benchmark |
| SAST / deps / secrets | Bandit, Semgrep, pip-audit/Safety, gitleaks |
| DAST | OWASP ZAP |
| Container/image | Trivy |
| Coverage | coverage.py / pytest-cov |

---

## 7. Coverage targets & exit criteria

- **P0 logic** (PDF assembly, slot mapping, accrual math, lock/reopen state
  machine, authz gates): target **≥95%** line+branch, and every branch of the
  state machine and role-matrix explicitly asserted.
- Overall unit+integration line coverage: **≥85%**.
- **Exit criteria to go live:** zero open P0/P1 defects; every critical flow
  (§1) has a passing acceptance test; PDF-integrity golden tests green; full
  role×action matrix green; a **restore drill has succeeded**; smoke passes on the
  VM; UAT signed off.

---

## 8. Requirements traceability

Maintain a matrix mapping each business requirement / critical flow (§1) → the
test(s) that verify it → status. No requirement ships without at least one
acceptance test tracing to it. Keep it in the repo alongside this plan so coverage
gaps are visible at a glance.

---

## 9. Defect severity

| Severity | Definition | Examples |
| -------- | ---------- | -------- |
| **Critical** | Data loss/corruption, authz bypass, compliance PDF wrong | Value maps to wrong slot; operator reopens a locked form; entry lost on Wi-Fi drop |
| **High** | Core flow broken, no safe workaround | Compile fails; migration breaks on populated DB |
| **Medium** | Feature impaired, workaround exists | Prefill misses a field; slow compile under load |
| **Low** | Cosmetic / minor UX | Copy inconsistency, spacing on portrait |

Critical and High block release. Every fixed defect gains a regression test (2.5).

---

## 10. Handoff checklist (to start testing)

- [ ] Repo access + local Compose stack running
- [ ] Sample fixture data + **real sanitised work orders** for extraction tests
- [ ] Golden/baseline PDFs captured for regression
- [ ] Confirmed acceptance criteria per station form (from directors / .nxt where relevant)
- [ ] Physical Galaxy Tab A9+ on `BV-Infra` for device/usability passes
- [ ] CI secrets configured (GHCR, scanners)
- [ ] Backup destination + restore target available for the DR drill
- [ ] This plan and the requirements matrix (§8) in the repo as living docs
