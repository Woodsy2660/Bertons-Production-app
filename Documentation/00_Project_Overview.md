# 00 — Project Overview

## 1. Purpose

Berton Vineyards runs bottling ("packaging") runs on a production line. Today, each run
produces a stack of **handwritten compliance forms** (filler checks, label usage, pallet
counts, etc.) which are later collated, partially re-keyed into EzyWine, and filed as a single
appended PDF per run in the company's documentation folders.

This project replaces the **handwriting and manual collation** with a local web application:

- Operators fill the forms digitally on tablets/phones at each station.
- The production manager tracks completion and compiles the final document.
- The app generates a single PDF per run that matches the existing documentation format.

The result reduces transcription error, makes in-flight runs visible, and produces a
consistent, legible, audit-ready document.

## 2. What this prototype is (and is not)

| In scope (prototype) | Out of scope (later iterations) |
|----------------------|---------------------------------|
| Manual operator data entry on tablets | Auto-population from EzyWine |
| Manager-created batches keyed by run number | Reading run/label data from the local server |
| Manual upload of work order, EzyWine listing, label refs | Auto-pull from the `labels` network folder |
| Submit / edit form lifecycle | Real-time multi-device sync |
| PDF compilation in fixed order, styled to match forms | Auto-filing to company folders (manager downloads & files) |
| Per-entry operator identity (name/initials field) | SSO / hardened authentication |
| QR/barcode field present but **stubbed** | QR lookup against EzyWine |

The integration features are **deliberately deferred, not designed out.** Architecture choices
(see `01`) keep their seams clean so later iterations update a module rather than re-implement.

## 3. Actors

- **Production Manager** — creates batches, uploads reference PDFs, monitors the status board,
  compiles the final document, downloads it for filing. May also edit any form.
- **Operator** — a line worker at a station (filler, labelling, palletising, etc.). Opens the
  form(s) for their station, enters data (once or accruing over the run), attaches their
  identity, submits. May reopen and edit their own forms.

Operators share tablets and rotate across a shift, so identity is **per entry**, never assumed
from the device.

## 4. The run, end to end (happy path)

1. Manager creates a **batch**, types the **run number**, fills the small batch header,
   uploads the **work order** PDF (operator reference) and any **label references**. The
   **EzyWine listing** PDF is uploaded whenever the manager has exported it.
2. Operators open their station's form. Atomic forms are filled and submitted once. Accrual
   forms are added to across the run (e.g. an hourly filler reading), reopened to add the next
   reading, and submitted when the run is done. Each entry carries the operator's identity.
3. Submitted/updated forms surface on the manager's **status board** with a last-updated time.
4. When the run is complete and forms are in, the manager **compiles**. The app renders each
   form to a styled PDF page and assembles all pages with the uploaded PDFs in the fixed
   16-slot order, producing the final named document.
5. Compiling **locks** the batch. The manager **downloads** the PDF and files it manually. If a
   correction is needed, the manager **reopens** the batch (invalidating the prior PDF), edits,
   and recompiles.

## 5. The forms (and their nature)

Nine forms are **app-generated**; the rest of the final document comes from **manager uploads**.
Full field-level detail is in `03`. Summary:

| Form | Doc # | Accrual mode | Orientation |
|------|-------|--------------|-------------|
| Daily Production Sheet | FOR PK 013 | Atomic | Portrait |
| Filler Line Check | FOR PK 017A | **Matrix** (column per reading) | Landscape |
| Bottle Sealing Usage Log | FOR PK 016A | **Log** (row per reading) | Landscape |
| Label Usage Sheet | FOR PK 023 | **Log** (row per reading) | Portrait |
| Finished Product Line Check | FOR PK 019 | **Matrix** (column per reading) | Landscape |
| Packaging Materials Pick List | — | Atomic (fixed rows) | Portrait |
| Carton Usage & Quality Control | FOR PK 018 | **Log** (two row-accruing tables) | Landscape |
| Final Pallet Count Sheet 1 | FOR PK 012A | **Log** (row per pallet) | Portrait |
| Finished Product / Warehouse Pallet Count | FOR PK 020A | **Log** (row per pallet) | Portrait |

## 6. Glossary

- **Batch / Run** — one bottling run, identified by a **run number** (e.g. `15646`). The unit
  the whole app is organised around.
- **Batch header** — the small set of run-level fields the manager enters at creation (run no,
  product, tank, date, packing unit, and the pick-list required quantities). Inherited by all
  forms so operators don't re-enter them.
- **Form instance** — one form for one batch (e.g. "Filler Line Check for run 15646").
- **Reading** — a single timestamped entry by one operator within an accrual form. Renders as a
  **row** (log forms) or a **column** (matrix forms).
- **Atomic form** — filled and submitted as a unit (e.g. Daily Production Sheet).
- **Accrual form** — built up from multiple readings over the run.
- **Multi-value cell** — a single field holding a fixed number of sub-values (e.g. Fill Height
  records 4 bottles → 4 numbers).
- **Compile slot** — one of the 16 fixed positions in the final document (`04`). A slot's
  content is either an app-generated form or a manager upload.
- **Label references** — zero-or-more distributor label proof / print PDFs uploaded by the
  manager; appended as a **flexible-length** group (`04` §3).
- **Lock-on-compile** — compiling freezes the batch against edits until explicitly reopened.

## 7. The authoritative reference for output

The file `15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf` (the completed run 15646
document) is the **single source of truth** for the final document's page order and form
layouts. Where any other note disagrees, that file wins. The 16-slot template in `04` is
derived directly from it.
