# Spec: Sterilising & Pre-Start Check — Standalone Form with Run Attachment

Build spec for a coding agent. Adds **FOR CA 005 — Cask Line Sterilising &
Pre-Start Check** as a **standalone form** that is completed independently of any
run, stored in a log, and later **attached to a run** when that run's paperwork is
being completed.

Built in the existing stack (FastAPI, async SQLAlchemy, Alembic, Jinja2 + Tailwind,
WeasyPrint, pypdf/pikepdf). Companion to `SPEC_cask_line_run_type.md`.

---

## 1. Why this form is different

Every other form belongs to a run from the moment it's created. This one doesn't.

**Sterilising is often performed before the job is posted for operators** — the
line is sterilised and pre-start checked, and only later is the run created and
assigned. So the form must be completable with **no run in existence**, then
**attached to the run afterwards**.

That means it is a **standalone entity with its own lifecycle**, not a run-scoped
form:

```
1. Operator/manager completes a sterilising check   →  saved to the log (unattached)
2. Later, a run is created and posted
3. While completing that run's forms, the user attaches an existing
   sterilising record from the log to the run
4. The attached record is included in the run's compiled PDF
```

---

## 2. ⚠ Design decision to confirm before building — attachment cardinality

The form contains **"Weekly Sterilising Checks"** and **"Daily Pre-Start Checks"**.
A weekly sterilising check will, by definition, often cover **more than one run in
that week**.

**Recommended model: one sterilising record can be attached to MANY runs**
(one-to-many, or a join table if a run could ever reference more than one record).
Do **not** build it as a strict one-run-one-record relationship — that would force
operators to re-enter the same weekly sterilising data for every run in the week,
which is duplicated effort and duplicated compliance data.

**Flag and confirm this with the developer before finalising the schema**, since it
determines the table structure. Default to the many-runs model unless told
otherwise.

---

## 3. Data model

New table, e.g. `sterilising_checks`, created via Alembic migration. Standalone —
**no mandatory run/batch foreign key**.

| Column | Notes |
| ------ | ----- |
| `id` | UUID PK |
| `operator_name` | "Sterilising Operators name" (free text) |
| `check_date` | Date |
| `check_time` | Time |
| `filters_integrity_tested` | Y/N — "Have the 0.65 and 0.45 filters been integrity tested as per SOP?" |
| *(wine/water filter readings)* | see §4 — store as structured rows/JSON |
| `lenticular_temp_c`, `lenticular_duration_mins` | lenticular housing & bypass line sterilisation |
| `line_temp_c`, `line_duration_mins` | 0.65 / 0.45 / filler & return line sterilisation |
| `filler_clean` | Y/N — daily pre-start |
| `carton_erector_clean` | Y/N — daily pre-start |
| `qc_sign_off` | Operator's QC sign-off (initials, typed per existing convention) |
| `created_by_role` | manager / operator (server-side, from session) |
| `created_at` | timestamptz, Australia/Sydney on display |

Plus the attachment relationship per §2 (recommended: a join table
`run_sterilising_checks` with `run_id` + `sterilising_check_id`, which supports one
record attached to many runs cleanly).

---

## 4. Form fields (from FOR CA 005)

**Header**
- Sterilising Operators name
- Date
- Time

**Weekly Sterilising Checks**
- Have the 0.65 and 0.45 filters been integrity tested as per SOP? — **Yes / No**
- Filter readings table — rows with **Pressure drop (mbar)** and **Pass? (Y/N)**:
  - Wine filter 0.45 µm
  - Wine filter 0.65 µm
  - Water filter 0.22 µm
- Temperature and duration of **lenticular housing and bypass line** sterilisation
  — `___ °C for ___ mins`
- Temperature and duration of **0.65, 0.45, filler and return line** sterilisation
  — `___ °C for ___ mins`

**Daily Pre-Start Checks**
- Is the Filler and surroundings clean, free of wine and debris? — Y/N
- Is the Carton Erector and surroundings clean, free of wine and debris? — Y/N

**Sign-off**
- Operators QC Sign Off (initials)

Keep the two sections (**Weekly Sterilising Checks** / **Daily Pre-Start Checks**)
visually distinct on screen and in the PDF, as they are on the paper form.

---

## 5. Access & flow

**Who can create:** **both operators and managers.** This is not manager-only —
sterilising is done by whoever is on the line, often before a run exists.

**Entry point:** reachable independently of any run — e.g. a "Sterilising checks"
item in the main navigation, available to both roles. It must be possible to open
and complete it with **no run selected**.

**The log view:**
- Lists completed sterilising records, **newest first**.
- Each entry shows: date, time, operator name, and **attachment status** — whether
  it's currently attached to any run(s), and which.
- Should make it easy to find recent **unattached** records, since those are what
  a user is usually looking for when attaching to a new run.
- Both roles can view the log.

**Attaching to a run:**
- From the run's forms page, an "Attach sterilising check" action opens a picker
  listing recent sterilising records (most recent first, clearly showing date/time
  and operator so the right one is obvious).
- Selecting one attaches it to the run.
- Attached records are shown on the run page alongside the other forms.
- **Detach must be possible while the run is unlocked** (in case the wrong record
  is attached) — after compile/lock, the normal lock rules apply and it can only be
  changed via manager reopen, consistent with existing behaviour.
- Attaching a record to a run must **not** prevent it being attached to other runs
  (per §2).

---

## 6. PDF output & compilation

- Renders to PDF via **WeasyPrint** in the **same visual style** as all other forms
  (header/title with the form code "FOR CA 005", logo on **first page only**,
  footer with submitted-by/at, Australia/Sydney timestamps).
- When a run is compiled, any **attached** sterilising record(s) are included in the
  run's compiled PDF.
- **Flag for the developer:** how attached sterilising records fit the compilation
  slot manifest (this interacts with the cask compilation question already raised
  in `SPEC_cask_line_run_type.md`). Report the approach rather than forcing it into
  an existing bottling slot.
- If a run is compiled with **no** sterilising record attached, handle it
  explicitly — either omit the section cleanly or show a clear "none attached"
  state. **Never render a silently blank page** that could read as "checks not
  performed" on a compliance document.

---

## 7. Constraints

- The form must be creatable and savable **with no run in context** — do not make
  run/batch a required relationship.
- Reuse existing form components, styling, save/toast feedback, and validation
  patterns; follow `UI_UX_STANDARD.md` (touch targets, spacing, badges).
- `created_by_role` and timestamps come from the **server/session**, never client
  input.
- Do not modify existing bottling or cask run forms — this is additive.
- Alembic migration for the new table(s).
- Commit and push when done (VM deploys via `git pull` + `docker compose up -d
  --build`).

---

## 8. Acceptance criteria

- A sterilising check can be completed and saved by **either an operator or a
  manager**, with **no run selected** and none required.
- Completed records appear in a **log**, newest first, showing date/time, operator,
  and attachment status.
- From a run, a user can **attach** an existing sterilising record from the log; it
  then appears on the run page.
- A single sterilising record can be attached to **multiple runs** (per §2) without
  re-entry.
- A record can be **detached** while the run is unlocked; lock/reopen rules behave
  consistently with existing forms.
- The record renders to PDF in the existing style and is included in the run's
  compiled output when attached.
- A run compiled with no sterilising record attached produces a clear, unambiguous
  result (not a silently blank page).
- No regression to existing bottling or cask forms.

## 9. Do not
- Do not require a run to create a sterilising check.
- Do not restrict creation to managers.
- Do not build a strict one-record-per-run relationship without confirming §2.
- Do not silently blank the section in a compiled PDF when nothing is attached.
- Do not trust client-supplied role or timestamp values.
