# 05 — Workflow & Lifecycle

## 1. Batch states

```
        create + header
   ─────────────────────────►  DRAFT
                                 │  first form data entered
                                 ▼
                            IN_PROGRESS  ◄───────────────┐
                                 │  all forms submitted   │ edit a form
                                 ▼                        │ (any submitted form)
                              READY                       │
                                 │  manager compiles      │
                                 ▼                        │
                            COMPILED (locked) ──reopen──► REOPENED ──► IN_PROGRESS
```

| State | Meaning | Edits allowed? |
|-------|---------|----------------|
| `draft` | Batch created, header captured, no form data yet. | Header + forms editable. |
| `in_progress` | At least one form has data; not all submitted. | Yes. |
| `ready` | All app-forms `submitted` (uploads may still be incomplete — see §2). | Yes (reverts to in_progress semantics on edit). |
| `compiled` | A current PDF exists; batch **locked**. | No (must reopen). |
| `reopened` | Manager unlocked a compiled batch to edit. | Yes; prior PDF marked stale. |

`ready` is a derived convenience state for the status board; the substantive gate is the
**readiness check** (§2), not the label.

## 2. Form status & readiness

**Per-form status** (`form_instance.status`, `02`):

| Status | When |
|--------|------|
| `not_started` | Instance exists (or implied) with no data. |
| `in_progress` | Has data; for accrual forms, readings are being added; not submitted. |
| `submitted` | Operator/manager marked the form complete. |
| `edited_since_submit` | A change occurred after submission (board shows this distinctly). |

> **Accrual nuance:** for log/matrix forms, `submitted` means "the operator considers the form
> done for this run" — it does **not** mean no more readings can be added. Reopening to add a
> late reading moves it to `edited_since_submit` (or back to `in_progress` if explicitly
> un-submitted). The board must therefore show *both* a status and a **last-updated time**, so
> the manager can tell a freshly-touched form from a stale one (important because there's no
> live sync — the manager's view is only as current as the last refresh).

**Readiness check (pre-compile).** Compilation is *gated* but **overridable**:

```
readiness(batch):
    forms_ok   = every app_form is `submitted` (or `edited_since_submit`)
    uploads    = note presence of ezywine_listing / work_order
                 (label_reference may legitimately be zero — 04 §3)
    return {
      can_compile_clean: forms_ok,
      warnings: [missing uploads, forms not submitted, ...],
    }
```

The manager may **compile with override** despite warnings (e.g. file a partial run). An
override is recorded on the `compilation`. Default UI: compile enabled cleanly when
`forms_ok`; otherwise enabled as "Compile anyway" with the warnings listed.

## 3. Lock-on-compile & staleness

- Compiling sets `batch.is_locked = true` and writes a `compilation` with `is_current = true`.
- While locked, the API **rejects all writes** to the batch's forms, readings, header, and
  uploads (enforce centrally — `02` §6).
- To change anything, the manager **reopens** the batch:
  - `is_locked → false`, state → `reopened`.
  - The current `compilation.is_current → false` (the filed PDF is now **stale**; the UI says
    so and a recompile is required to get a fresh document).
- Recompiling supersedes: new `compilation` becomes current, batch re-locks.

This is the resolution to the "edit after compile" gap: the system of record can never silently
diverge from a compiled document — either the batch is locked (they match) or it's reopened
(explicitly flagged stale).

## 4. Identity capture

No real authentication in the prototype, but identity is **first-class and per-entry**:

- **Accrual forms (log/matrix):** every `reading` carries `operator_identifier` (`02`). The UI
  prompts for the operator (pick-from-list of known operators, or initials entry) **before the
  reading is saved**. Different operators across a shift therefore attribute correctly — this
  preserves what the paper "Initial" column does.
- **Atomic forms:** `form_instance.submitted_by` is captured at submit; the form's own
  `initials` field (where the paper has one) is also stored.
- **Edits:** any post-submit edit sets `last_edited_by` **without overwriting** the original
  `submitted_by`/reading author, so "who entered" and "who changed" are both retained.

Operator list: seed a simple `operators` lookup (name + initials) so entry is a tap, not free
text — reduces typos in the accountability trail. (A future iteration swaps this for real auth
behind the same identity field.)

## 5. Status board (manager view)

Minimum viable board, per batch:

- **Forms grid:** the nine app-forms, each showing status chip (`not_started` / `in_progress` /
  `submitted` / `edited_since_submit`) and **last-updated time**. For accrual forms, show a
  reading count (e.g. "Filler Check · 7 readings · updated 11:09").
- **Uploads checklist:** EzyWine listing (present/absent), work order (present/absent), label
  references (count). Absent expected uploads shown as warnings, not errors.
- **Compile control:** "Compile" (clean) or "Compile anyway" (with the warnings list), plus,
  once compiled, the current PDF (download) and a **Reopen** action.
- **Lock indicator:** clear COMPILED/LOCKED vs REOPENED (PDF stale) state.

Refresh model: the board reads current state on load and on manual refresh / periodic poll (no
websockets). Always render the last-updated times so staleness is visible.

## 6. Operator view

- Pick the batch (by run number) → pick the station's form.
- **Atomic form:** fill, submit. Inherited header fields pre-filled read-only.
- **Accrual form:** add a reading (identity prompt → fields → save). Reopen the same form later
  to add the next reading. **Submit** when done. After submit, **edit** remains available
  (reopen form → amend/add → re-save), which flips the board status to `edited_since_submit`.
- Multi-value cells render the exact N inputs (`03`).

## 7. Permissions (prototype-simple)

- **Operators:** create/edit readings and submit forms on any open batch; cannot compile,
  reopen, upload, or edit the batch header.
- **Manager:** everything operators can do, plus create batches, edit header, upload PDFs,
  compile, reopen, download.
- Enforce via a simple role flag now; the identity/role layer is the natural seam for real auth
  later.
