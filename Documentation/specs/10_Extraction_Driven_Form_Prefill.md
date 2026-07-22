# 10 — Extraction-Driven Form Prefill (all stations) + Pick List Update

**Status:** Spec — build on the working pdfplumber extraction (`09`).
**Depends on:** `09` (pdfplumber parser + `parse_work_order_pdf_verbose`).
**Companion:** `11_Pallet_Tag_Printing.md` (built on the same stored extraction).

---

## 1. Objective

Every new batch already requires a work order upload. This spec makes that upload do real work:
**on every batch, the work order is parsed once, the full extracted field set is stored, and every
station form pre-fills the fields it can from that extraction.** It also:

- **Updates the Label Pick List** to source its lines from the new pdfplumber method (`09`).
- **Stores the complete extraction** (not just label lines) for current prefill *and* future use.

Prefill is **best-effort and non-blocking**: a missing or unparsed field leaves the form field empty
and editable; nothing about a form ever breaks because extraction was incomplete.

## 2. Principles

1. **Parse once, store, reuse.** Extraction runs at batch creation (work order upload) and on work
   order replace. Forms read from the **stored** extract — they do not re-parse per view (the one
   existing exception: re-parse fallback if the header has no lines but a work order PDF exists).
2. **Store everything.** The full verbose result is persisted, so fields not consumed today are
   available for future features without re-parsing historical work orders.
3. **Prefilled ≠ locked.** Every prefilled value is editable and visually flagged "from work order,"
   so operators can override (values sometimes differ from the order — see §5 caveats).
4. **Two kinds of prefill:**
   - **Direct prefill** — the field *is* the work-order value (run number, product, required qty…).
   - **Reference display** — the work-order value is shown *beside* a "matches work order? Y/N" check
     as the expected value, without filling the operator's measured reading.
5. **Never block.** Extraction failure → empty fields + the existing `parse_note`; the form works.

## 3. Storage model

Extend `batch_header` (and `batch`) so common fields are queryable columns, and keep the **entire**
extraction in a JSONB blob for completeness and future use.

**Promote to columns** (consumed by prefill below):
`run_number` (on `batch`), `product`/`description`, `stock_item`, `stock_alias`, `packing_unit`,
`packaging_line`, `run_quantity`, `vessel_batch`, `cartons_per_pallet`, `cartons_per_layer`,
`pallet_layers`, `pallet_type`, `front_label_height`, `back_label_height`, `other_label_height`,
`label_barcode`, `carton_print_line1/2/3`, and the derived `bottle_code` (§3a).

**Keep as JSONB:**
- `pick_list_lines` — label-stock subset (unchanged shape, §6).
- `work_order_extract` — the **full** verbose result: all `fields` (with provenance), the `details`
  code→value dict, `stock_table_lines` (all rows, not just labels), `parse_note`, `warnings`.
  This is the "future use" store. (Omit `raw_layout_text` or truncate it — don't bloat the row.)

### 3a. Derived field: `bottle_code`
The Final/Warehouse pallet-count forms record a **Bottle Code** (e.g. `3-027`, `9-086`) that isn't a
labelled field on the work order — it's the leading token of the **glass** stock line's description
(`BTSPCLAG7AMB → "3-027 Super Prem Ant Grn BVS…"`, `BTPUBUFG7AMB → "9-086 Punted Burg BVS…"`).
Derive at store time: `bottle_code = first token of the BT-prefixed stock line description`. Mark it
**heuristic** in provenance so the validation page (`09` §7) can flag it for confirmation.

## 4. When extraction runs (unchanged triggers, new consumption)

| Trigger | Action |
|---------|--------|
| New batch (`POST /batches/new`) | Save work order → `parse_work_order_pdf_verbose()` → populate promoted columns + `work_order_extract` + `pick_list_lines`. |
| Work order replace (`refresh_header_from_work_order`) | Re-parse → refresh the same fields. Preserve any operator-overridden form values already entered (do not silently clobber submitted form data). |

> **Override-preservation rule:** on work-order replace, refresh the *stored extract* and the
> *unedited* prefill defaults, but never overwrite a value an operator has already entered/submitted
> on a form. Prefill seeds a field; once touched, it's the operator's.

## 5. Prefill map — per station form

Legend: **D** = direct prefill (editable), **R** = reference value shown beside a match-check.
Source keys are from the extraction (`09`). Anything not listed is operator/office-entered.

### Daily Production Sheet (`daily_production`)
| Field | Type | Source |
|-------|------|--------|
| date | D | work order Start date |
| run_number | D | `run_number` |
| product | D | `description` |
| tank | — | **Not prefilled** — work order has `Vessel/Batch` (Z302), which is *not* the filler tank (B113). Operator-entered. |

### Filler Line Check (`filler_line_check`)
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| wine | D | `description` |
| run_number | D | `run_number` |
| tank | — | operator-entered (see above) |

### Bottle Sealing Usage Log (`bottle_sealing`)
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| run_number | D | `run_number` |
| (manufacturer, part_number) | — | operator; closure codes (`CN…`,`DV…`) available in `work_order_extract` for a *future* prefill |

### Label Usage Sheet (`label_usage`)
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| product | D | `description` |
| run_number | D | `run_number` |
| (front/back/other section labels) | future | label lines classify by prefix (`LF…`=front, `LB…`=back, `LMED…`=other) — available for a future section-labelling enhancement |

### Finished Product Line Check (`finished_product_line_check`) — rich reference prefill
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| run_number | D | `run_number` |
| front label height | R | `front_label_height` (L007) — expected value beside the measured reading |
| back label height | R | `back_label_height` (L010) |
| other label height | R | `other_label_height` (L016) |
| carton print (match check) | R | `carton_print_line1/2/3` (G001/2/3) — expected print text |
| carton barcode (match check) | R | `label_barcode` (L008) |
| BVS code (match check) | R | BVS stock line (`BVS…`) description |

### Packaging Materials / Label Pick List (`pick_list`) — see §6
| Field | Type | Source |
|-------|------|--------|
| run_number, stock_item, description, packing_unit, packaging_line | D | header extract |
| run_date | D | Start date |
| line: stock_item, description, required | D | `pick_list_lines` (label stock, new method) |
| line: supplied/returned/used/wastage | — | operator |

### Carton Usage & QC (`carton_qc`)
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| carton code (match check) | R | carton stock line (`CN…`) code/description |
| record carton print / print match | R | `carton_print_line1/2/3` (G001/2/3) |

### Final Pallet Count Sheet 1 (`final_pallet_count`)
| Field | Type | Source |
|-------|------|--------|
| date | D | Start date |
| run_number | D | `run_number` |
| product | D | `description` |
| bottle_code | D | derived `bottle_code` (§3a) — enables the "bottle code matches work order?" check |
| pallet_type | D (override) | `pallet_type` (P005) — default, operator may override |

### Finished Product / Warehouse Pallet Count (`finished_product_pallet`)
| Field | Type | Source |
|-------|------|--------|
| date, product, run_number | D | header extract |
| bottle_code | D | derived `bottle_code` |
| pallet_type | D (override) | `pallet_type` (P005) |
| slip_sheet_required | D (override) | P012 |
| layer config / stack height (match checks) | R | `cartons_per_layer` (P001), `pallet_layers` (P002/P003) |

> **Caveat surfaced by real data:** work-order `pallet_type` (Loscam) and operator-recorded value
> (Chep) can differ; `vessel_batch` (Z302) ≠ filler `tank` (B113). These are why pallet_type is a
> *default-with-override* and tank is *not* prefilled. Prefill assists; it never asserts.

## 6. Pick List update (the explicit ask)

The Label Pick List must now source from the pdfplumber method:

1. Its lines come from `pick_list_lines` produced by `parse_work_order_pdf_verbose()` (`09`) — same
   JSON shape as before (`stock_item`, `description`, `required`, `supplied_qty`, `returned_qty`),
   so the form and any callers are unchanged.
2. The create flow and the re-parse-on-view fallback both use the **new** parser (remove the old
   pypdf/regex passes).
3. Header fields on the form prefill from the promoted columns.
4. Keep `filter_label_lines()` / `is_label_stock()` contracts (L-prefix rule).

> **Future-use note (not this spec):** the new parser already returns `stock_table_lines` — *all*
> materials (glass, closures, dividers, wine), not just labels. Expanding the digital pick list from
> label-only to a full-materials pick list (matching the paper form) becomes a small change later,
> because the data is already captured. Flagged here so the storage design supports it.

## 7. Prefill mechanics (UI/behaviour)

- On form open, prefill fields render populated from the stored extract, each with a subtle
  "from work order" marker; the field stays editable.
- Reference (R) values render as read-only expected values adjacent to the relevant match-check
  (e.g. "Expected front label height: 25mm" next to the measured input and the Y/N).
- If a source field is missing from the extract, the form field is simply empty — no error.
- Overriding a prefilled value is a normal edit; it does not re-trigger extraction.

## 8. Tests
- Fixture tests (15646, 15778): assert each **direct** prefill field resolves to the expected value
  (run_number, product, packing_unit, required quantities, `cartons_per_pallet`, derived
  `bottle_code` = `3-027` / `9-086`, `pallet_type` = Loscam).
- Assert **reference** values populate (label heights, carton print, barcode) where present in the
  work order (e.g. 15778 `label_barcode` = 9335966006737, `front_label_height` = 25mm).
- Assert `tank` is **not** prefilled from `vessel_batch`.
- Assert `work_order_extract` persists the full field set + `details` + `stock_table_lines`.
- Assert override-preservation: replacing the work order does not clobber an entered form value.
- Pick List: lines equal the label subset via the new parser; header prefills; non-label rows absent.

## 9. Acceptance criteria
- Creating a batch stores the full extraction; every form in §5 shows its prefilled/reference values
  on the two sample work orders.
- Pick List sources from the pdfplumber method; shape and callers unchanged.
- Missing/failed extraction never blocks a form.
- Work-order replace refreshes defaults without overwriting entered data.
- Full extract retained in `work_order_extract` for future use.

## 10. Out of scope
- Pallet-tag calculation/printing → `11`.
- Full-materials (non-label) pick list expansion (future; data already captured).
- Closure/manufacturer prefill for Bottle Sealing (future; codes captured).
- Auto-calculated totals (still operator-entered).
