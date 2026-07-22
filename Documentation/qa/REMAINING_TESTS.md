# Remaining Tests — Explicit Agent Instructions

Follow-up to `TEST_PLAN.md` and `QA_EXECUTION_REPORT.md`. The first QA pass
covered smoke, unit/integration, live authz, and concurrent-load survival. This
document specifies the tests **still required before floor go-live**, written as
explicit instructions for a coding agent to execute.

**Read this first — the rule the last pass got wrong:**
The concurrency check reported PASS yet QA-001 (duplicate accrual sequence
numbers) exists. That happened because the assertion was `0×5xx` — an
**HTTP-status** check. A duplicate sequence number returns a happy 200/303 and is
silently wrong. **For every test below, assert on the resulting data / database
state, not on the HTTP response code.** "Nothing 500'd" is never a pass criterion
for this app.

Priority order to execute: **§1 → §2 → §3 → §4**. Do not skip to lower sections
while a P0 item is open.

---

## §1 — Fix-and-regress: concurrency hardening (P0, blocks multi-tablet use)

QA-001 and QA-002 are the **same class of bug** (multiple writers, no guard) on
two paths. Fix both, then add regression tests with the assertions below.

### TEST-C1 — Accrual sequence integrity (regresses QA-001)
- **Setup:** one run, one accrual-pattern station form. Prepare N=15 independent
  authenticated sessions (mix ~70% operator / 30% manager, as in the load test).
- **Action:** all N sessions POST an accrual entry to the **same form**
  concurrently; repeat for 3 iterations.
- **Assert (data-level, all must hold):**
  - Sequence numbers on the resulting rows are **unique** (no duplicates).
  - Sequence numbers are **contiguous** with no gaps (1..M for M rows).
  - Row **count equals** the number of successful POSTs (nothing lost, nothing
    double-counted).
  - Ordering is deterministic and correct under re-read.
- **Pass:** all four hold across all iterations. A single duplicate or gap = FAIL.

### TEST-C2 — Single current compilation (regresses QA-002)
- **Setup:** one run ready to compile.
- **Action:** fire two (and separately, five) compile requests concurrently.
- **Assert (data-level):**
  - Exactly **one** current/active compilation exists afterward — not two.
  - No orphaned/partial compilation artifacts remain.
  - The losing request(s) resolve deterministically (rejected, or coalesced to the
    same single result) — define and assert which.
- **Pass:** exactly one current compilation, every time. Two = FAIL.

### TEST-C3 — Cross-path races
- **Action, each as a concurrent pair:** compile racing an in-flight accrual save;
  manager reopen racing an operator save; reopen racing a compile.
- **Assert:** final DB state is internally consistent (no half-applied edit, no
  edit lost against a lock, lock/compile state coherent with row data).
- **Pass:** consistent terminal state for every pairing.

> Implementation note for the fix (not a test): the durable guard is at the **DB
> layer** — a unique constraint / sequence allocation for accrual ordering, and a
> uniqueness guarantee or row-lock for "current compilation." Application-level
> checks alone will not survive true concurrency.

---

## §2 — Deferred P0 categories (block go-live)

These are the highest-risk categories from `TEST_PLAN.md` and were **not run** in
the first pass.

### TEST-P1 — Golden PDF output integrity (top priority; currently zero coverage)
The compiled PDF is the compliance artifact. Prove every entered value lands in
the correct place in the output — by reading the PDF back, not by inspection.
- **Setup:** a fixture run with **known values** across all nine station forms,
  covering all 16 compilation slots.
- **Action:** complete the run and compile.
- **Assert (read the produced PDF back with `pypdf`/`pdfplumber`):**
  - Every entered value appears in the output, **in its correct slot**, with
    correct units, dates, and batch/run identifiers.
  - All 16 slots assemble in the **correct order**.
  - **Missing/partial slots are handled explicitly** (documented placeholder or
    block) — never a silent blank that reads as "no data recorded."
  - Timestamps render in **Australia/Sydney**, not UTC (see TEST-P6).
  - After a manager **reopen → edit → recompile**, the output reflects the edit.
  - Extracted work-order prefill values match the source work order.
- **Golden baseline:** capture the known-good PDF as a snapshot; future runs diff
  against it (checksum on normalised text + field-level assertions). Store the
  baseline in the repo.
- **Pass:** every value correct and correctly placed; slot order correct; no silent
  blanks. Any value in the wrong slot = FAIL (Critical).

### TEST-P2 — Kill-DB / restart resilience (data-loss paths)
- **Actions, each a separate scenario:**
  1. Drop the Postgres connection mid-form-entry (`docker stop` the db container
     while a save is in flight), then restore it.
  2. `docker restart` the web container with a form part-entered.
  3. Reboot the VM (or restart the full stack) with data in the DB.
- **Assert:**
  - In-flight data either **persists or fails loudly** with a clear operator
    message — **never silent loss**.
  - After restore/restart the app returns to **healthy + ready** on its own
    (verifies `restart: unless-stopped` + healthcheck + migrate-on-boot ordering).
  - Committed data is intact after every scenario.
- **Pass:** no silent data loss in any scenario; app self-recovers.

### TEST-P3 — Backup & restore (DR) drill
- **Action:** run the `pg_dump` + uploads backup; then **restore into a clean
  environment**.
- **Assert:**
  - Restored environment reproduces **full state** (rows + uploaded files +
    generated artifacts).
  - A compile in the restored environment produces a correct PDF (chain with
    TEST-P1 assertions).
  - Documented RPO/RTO are actually met; backup destination is **off the app VM**.
- **Pass:** clean-environment restore reproduces state and a valid compile.
  An untested backup does not count as done.

---

## §3 — P1/P2 remainder (before go-live, after §1–§2)

### TEST-E1 — Playwright E2E, including double-submit-under-latency
The load test showed p95 multi-second and **max ~10s under burst**. On a mounted
tablet a 10s wait after a tap invites a second tap → double submit. Load testing
does not catch this; drive the real UI.
- **Actions (landscape tablet viewport, Chrome engine):**
  - Full journey: login → dashboard → batch → complete all stations → compile →
    download correct PDF.
  - **Double-submit:** tap a primary action (Save, Compile & lock) twice rapidly,
    and again while an artificial ~10s server delay is injected.
  - Offline mid-form then back online.
  - Lock banner appears and disables fields after compile.
  - Manager-only controls are absent **and** blocked for operators (confirm at the
    endpoint, not just the hidden button).
- **Assert:**
  - Double-tap / tap-under-latency produces **exactly one** record (chain to
    TEST-C1/C2 data assertions) — the guard holds.
  - Lock/authz UI states match server state.
- **Pass:** no double-writes; UI state faithful to server state.

### TEST-E2 — Latency thresholds (turn "didn't crash" into a real bound)
- **Action:** re-run the multi-user load (20 and 30 users) from the first pass.
- **Assert against explicit thresholds** (set these with the team; suggested
  starting bounds): p50 ≤ 1s, p95 ≤ 3s, **hard max ≤ 8s** for form save/load.
  PDF compile may have its own higher bound — define it, don't leave it unbounded.
- **Pass:** thresholds met; any request over the hard max is a finding, even with
  no 5xx.

### TEST-E3 — Soak / endurance
- **Action:** steady load for several hours / overnight.
- **Assert:** no memory growth trend (watch **WeasyPrint** and async sessions), no
  container-log growth filling disk, no connection-pool or file-descriptor
  exhaustion. App still healthy + ready at the end.
- **Pass:** flat resource profile; no degradation over the window.

### TEST-E4 — Physical Galaxy Tab A9+ pass (a11y / timezone / usability)
Emulators find layout bugs; the mounted physical tablet finds the real ones.
- **On the actual Tab A9+ on `BV-Infra`, landscape and portrait:**
  - **Accessibility:** touch targets ≥48px (56 primary), contrast AA+, status
    never colour-only (verify greyscale-usable), visible focus — per
    `UI_UX_STANDARD.md`. Run `axe`/playwright-axe plus a manual greyscale check.
  - **TEST-P6 Timezone:** confirm on-screen and on-PDF timestamps are
    Australia/Sydney, not UTC.
  - **Usability:** short unscripted sessions with a real operator **wearing
    gloves** under production lighting/glare. Log mis-taps, unreadable-under-glare
    elements, confusing copy.
- **Pass:** a11y rules met; timezone correct; no gloved-use blockers.

---

## §4 — Security follow-ups (from QA WARNs)

### TEST-S1 — QA-004 autoescape (re-triage before accepting as Medium)
Jinja autoescape being off in the PDF pipeline is only cosmetic **if no untrusted
text reaches that template**. But **operator-entered form values and
pdfplumber-extracted work-order data both flow into the compiled PDF.**
- **Action:** trace whether user-entered and extracted data reach the PDF Jinja
  env. Then inject markup/special characters (e.g. `<`, `>`, `{{ }}`, long/odd
  strings) via a form field and via a crafted work order.
- **Assert:** the compiled PDF renders the input as **literal text**, is not
  broken by it, and no markup/template injection occurs.
- **If untrusted data does reach the env:** re-classify above Medium and enable
  autoescape (or explicitly escape) — this is a compliance-document integrity
  issue, not cosmetic.

### TEST-S2 — QA-003 dependency CVEs
- **Action:** bump starlette, pydantic-settings, and the other flagged packages;
  re-run `pip-audit`/`Safety`.
- **Assert:** no known-high CVEs remain; full test suite still green after bumps.

---

## Exit gate (go / no-go for floor deployment)

All must be true:
- [ ] TEST-C1, C2, C3 pass with **data-level** assertions (QA-001, QA-002 fixed).
- [ ] TEST-P1 golden PDF integrity green; golden baseline committed.
- [ ] TEST-P2 resilience: no silent data loss; app self-recovers.
- [ ] TEST-P3 restore drill succeeded in a clean environment.
- [ ] TEST-E1 double-submit guard holds under latency.
- [ ] TEST-E2 latency thresholds met.
- [ ] TEST-S1 resolved (autoescape safe or fixed); TEST-S2 CVEs cleared.
- [ ] TEST-E3 soak and TEST-E4 physical-tablet pass complete (or explicitly
      risk-accepted by the team with a date to close).
- [ ] Every fixed defect has a regression test in the suite.

**Standing rule for every test above: assert on data and state, not on HTTP
status.** For this app, correct-and-silent-failure is the danger, and only
data-level assertions catch it.
