# Spec: Cask Line Run Type + Cask Forms

Build spec for a coding agent. Adds a second production line type — **Cask** —
alongside the existing **Bottling** line. The manager chooses the line type when
creating a run, and that choice determines which forms appear on the run page.

Built entirely in the existing stack (FastAPI, async SQLAlchemy, Alembic, Jinja2 +
Tailwind, WeasyPrint, pypdf/pikepdf, pdfplumber). **No new patterns are needed** —
the four cask forms map onto the atomic / accrual-log / accrual-matrix patterns the
app already implements for bottling.

---

## 1. Run type selection

- On **create run** (manager only), add a required **Line type** choice:
  **Bottling** or **Cask**.
- Store it on the run/batch record (new column, e.g. `line_type` enum
  `bottling` | `cask`, via Alembic migration). Default existing rows to
  `bottling` so current data is unaffected.
- The run page then shows **only the forms for that line type**. A cask run must
  not show bottling station forms, and vice versa.
- **Both line types keep the work order and label reference** exactly as now —
  upload, storage, viewing, and pdfplumber extraction are unchanged and shared.
- The compile / lock-on-compile / manager-reopen flow stays the same; only the set
  of forms differs.

---

## 2. The four cask forms

Source documents (uploaded Word forms) map to existing patterns as follows.
**Reuse the existing form patterns and components — do not invent new ones.**

### 2.1 FOR CA 001 — Cask Final Pallet Count
**Pattern: accrual (log)** — same as the existing bottling Final Pallet Count.

Header (prefill where possible): Date, Run number, Product.

Entries accrue as pallets are completed. The paper form is a fixed grid of pallets
**1–80**; digitally this should be a **log of entries**, each with:
- Pallet # (sequential, auto-suggested next number)
- Time
- Cases per pallet
- Operator initials (typed per entry, per existing convention)

Do not render 80 empty rows — operators add entries as they go, consistent with the
existing accrual-log forms.

### 2.2 FOR CA 002 — Cask Line Check Sheet
**Pattern: accrual (matrix)** — same as the existing Filler Line Check.

Header fields (prefill where possible): Date, Tank, Run number, Wine, Wine S.G.,
Empty bladder weight (g), Best Before Date.

Check items form the matrix rows; each **hourly check** adds a time column with
operator initials (dynamic columns, exactly like Filler Line Check):
- Bladder — match work order? (Y/N)
- Filler Vacuum
- Full bladder weight — **3 bags** (three readings per check, like the existing
  multi-reading rows)
- Inner
- Inner Inkjet Code
- Glue — dripping onto bladders? (Y/N)
- Inner flaps — glued together? (Y/N)
- Outer Inkjet Code
- Outer flaps
- Stacking
- Pallet Type
- Slip Sheet (Y/N)
- Checked By (initials) — per column

### 2.3 FOR CA 003 — Cask Line Production Waste
**Pattern: atomic** (single submission).

Header (prefill where possible): Product, Run No., Date.

Waste counts grouped by category, each with a total:
- **Casks:** Machine Jam, Printing, Other (record the problem — free text), Total
- **Bladders:** Split, Faulty Tap, Other, Total
- **Inners:** (counts as per form), Total
- **Outers:** (counts as per form), Total
- **Comments** (free text)
- Signature / initials + Date

Totals should be **calculated automatically** from the entered counts rather than
typed, to avoid arithmetic errors on a compliance record.

### 2.4 FOR CA 004 — Cask Line Tank Dip Sheet
**Pattern: atomic** (single submission).

Header (prefill where possible): Product, Run No., Date, Tank, Volume supplied.

Readings:
- **Starting dip:** cm and L, plus initials
- **Finishing dip:** cm and L, plus initials

---

## 3. Work-order prefill (pdfplumber extraction)

Prefill cask form headers from the extracted work order **wherever the data
exists**, using the existing extraction/prefill mechanism — do not build a second
extraction path.

Fields that should prefill from the work order / batch header where available:
**Date / Run date, Run number, Product, Tank**, and where present **Volume
supplied**, **Wine**, **Best Before Date**.

Rules:
- Prefilled fields must be **clearly marked as coming from the work order** (the
  existing UI convention, e.g. "(from work order)").
- If a value isn't present in the extraction, **leave the field blank and
  editable** — never guess, never silently insert a wrong value onto a compliance
  record.
- Prefilled values remain **editable** by the operator, as now.
- Reuse the existing extraction code and field-mapping approach; extend the mapping
  for any cask-specific fields rather than writing a parallel extractor.

---

## 4. PDF output & compilation

- Each cask form renders to PDF via **WeasyPrint** using the **same template
  structure, styling, header/logo treatment, and footer** as the existing bottling
  forms — the output must be visually consistent with the current compiled PDFs.
- Include the form code and title in the header exactly as the bottling forms do
  (e.g. "Cask Final Pallet Count" / "FOR CA 001").
- The **logo appears on the first page of each form only** (per the existing
  first-page-only rule — do not reintroduce a repeating logo).
- Cask forms compile into the run's PDF using the existing compilation flow.
  **Note:** the current compilation is a fixed 16-slot template built around the
  bottling forms. Determine and report how the cask run's compilation should be
  structured (a cask-specific slot manifest is likely needed, since there are four
  cask forms rather than nine bottling forms). **Flag this rather than forcing cask
  forms into bottling slots.**
- Submitted-by / submitted-at footer as per existing forms, timestamps in
  **Australia/Sydney**.

---

## 5. Constraints

- **Do not alter the existing bottling forms, their behaviour, or their output.**
  Existing runs must be unaffected.
- Reuse existing patterns, components, and UI: forms follow `UI_UX_STANDARD.md`
  (touch targets, spacing, status badges, save feedback, lock behaviour).
- Same RBAC as now: run creation and the line-type choice are **manager-only**;
  operators complete forms.
- Same lock-on-compile and manager-reopen semantics.
- Accrual forms must preserve **sequence integrity** under concurrent writes
  (unique, contiguous sequence numbers) — the same guarantee required of the
  existing accrual forms.
- Alembic migration for the new `line_type` column and any new form/table
  structures; existing data migrates cleanly to `bottling`.
- Commit and push when done (VM deploys via `git pull` + `docker compose up -d
  --build`).

---

## 6. Acceptance criteria

- Creating a run lets the manager choose **Bottling** or **Cask**; the choice is
  stored and shown on the run.
- A **cask run shows only the four cask forms**; a bottling run is **unchanged**
  and shows only its existing forms.
- Work order and label reference upload/view/extraction work identically on both
  run types.
- Each of the four cask forms can be completed and saved:
  - FOR CA 001 accrues pallet entries (log).
  - FOR CA 002 accrues hourly check columns (matrix), including the 3-bag readings.
  - FOR CA 003 and 004 submit atomically; FOR CA 003 totals calculate automatically.
- Header fields prefill from the work order where the data exists, are marked as
  work-order-sourced, remain editable, and are **blank (not guessed) when absent**.
- Cask forms render to PDF matching the existing visual style, logo on first page
  only, Sydney timestamps.
- A cask run compiles successfully; report the compilation/slot approach chosen.
- Existing bottling runs and their compiled output are unaffected (no regression).

## 7. Do not
- Do not modify existing bottling forms or their PDF output.
- Do not build a second work-order extraction path — extend the existing one.
- Do not prefill guessed values when extraction has no data.
- Do not show cask forms on bottling runs or vice versa.
- Do not force the four cask forms into the bottling 16-slot manifest without
  flagging the design decision first.
