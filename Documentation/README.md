# Berton Bottling Run Intake & Compilation App — Documentation Suite

**Project:** Digitising the manual bottling-run work-order forms at Berton Vineyards into a
local web intake portal, with PDF compilation matching existing compliance documentation.

**Status:** Prototype specification (pre-build).

**Scope of this prototype:** Deliberately *excludes* live integration with EzyWine and the
local file-server folders. Data enters by manual operator input; the EzyWine "Bottling Run
COMPLETE Listing" and label references enter by manual upload; the finished compiled PDF is
downloaded by the manager for manual filing. Integration is stubbed for later iterations
(see `01_System_Architecture.md` §6).

---

## How to read this suite

Read in order on first pass. On build, each document maps to a part of the system:

| # | Document | Covers | Primary reader |
|---|----------|--------|----------------|
| 00 | [`00_Project_Overview.md`](00_Project_Overview.md) | Scope, goals, actors, glossary, prototype boundaries | Everyone |
| 01 | [`01_System_Architecture.md`](01_System_Architecture.md) | Hosting model, stack, components, EzyWine stub boundary | Architect / lead |
| 02 | [`02_Data_Model.md`](02_Data_Model.md) | Postgres schema, the reading abstraction, entities | Backend dev |
| 03 | [`03_Form_Specifications.md`](03_Form_Specifications.md) | All 9 app-generated forms: fields, accrual mode, multi-value cells, identity | Full-stack dev |
| 04 | [`04_PDF_Compilation_Spec.md`](04_PDF_Compilation_Spec.md) | The 16-slot compile template, sources, orientation, flexible label section | Backend dev |
| 05 | [`05_Workflow_and_Lifecycle.md`](05_Workflow_and_Lifecycle.md) | Batch states, submit/edit/lock, status board, identity capture | Full-stack dev |
| 06 | [`06_Build_Roadmap.md`](06_Build_Roadmap.md) | Phased delivery plan, milestones, open decisions log | Lead / PM |

---

## The one-paragraph summary of the system

A **production manager** creates a **batch** for a bottling run by entering a small header
(run number + a handful of fields) and uploading reference PDFs (the work order, the EzyWine
listing when ready, and zero-or-more label references). **Operators** at each production
station open the relevant **form** on a tablet, enter data — some forms once, some
accruing hourly readings over the run — attach their identity to each entry, and submit.
Submitted forms appear on the manager's **status board**. The manager can compile the run at
any point: the app renders each digital form as a PDF page styled to match the existing
Berton forms, then assembles those pages together with the uploaded PDFs in a fixed 16-slot
order, producing one document named to the company convention
(`15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf`). Compiling locks the batch; the
manager can reopen it, which invalidates the prior PDF.

---

## Key design decisions already locked

These are settled and underpin the specs below. Changing them ripples through the suite.

1. **Local Postgres** is the backend datastore and single source of truth for in-flight runs.
2. **No real-time sync.** Forms use a **submit / edit** model; the manager sees current state
   on load/refresh.
3. **No EzyWine or file-server integration in the prototype.** The QR/barcode lookup is a
   stubbed, swappable module (`01` §6).
4. **Manager uploads** the work order as operator reference (types the run number manually),
   plus the EzyWine listing and label references for compilation.
5. **Identity is captured per entry** — per reading on accrual forms, per submission on atomic
   forms (`05` §4).
6. **Accrual forms are supported** in two shapes — *log* (row-per-reading) and *matrix*
   (column-per-reading) (`02` §3, `03`).
7. **Compile order is fixed** to the 16-slot template derived from the authoritative output
   PDF (`04`).
8. **Lock-on-compile** with explicit manager reopen (`05` §3).

## Open decisions still to confirm

Tracked live in `06_Build_Roadmap.md` §5. None block starting the build.
