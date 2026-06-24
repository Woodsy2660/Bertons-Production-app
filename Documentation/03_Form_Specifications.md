# 03 — Form Specifications

Field-level specification of the **nine app-generated forms**. Each maps to a `form_type`
(`02`) and a compile slot (`04`). Manager-uploaded pages (EzyWine listing, work order, label
references) are **not** here — see `04`.

## How to read these specs

For each form:

- **`form_type`** — the template key.
- **Accrual mode** — `atomic` (one-time), `log` (row per reading), `matrix` (column per
  reading). Drives data model (`02`) and render orientation (`04`).
- **Orientation** — page orientation for the rendered PDF.
- **Header fields** — non-repeating; live in `form_instance.header_payload`. Some are
  **inherited** from the batch header (don't re-ask the operator).
- **Reading fields** — repeating; one set per `reading`. `[×N]` marks a **multi-value cell**.
- **Identity** — where operator identity is captured.

Field `type` values: `text`, `number`, `time`, `date`, `bool` (Y/N), `enum(...)`,
`number[N]` / `text[N]` (multi-value, fixed length N).

---

## 1. Daily Production Sheet — `daily_production`

- **Accrual:** `atomic` · **Orientation:** portrait · **Doc #:** FOR PK 013
- **Identity:** single `initials` field (header_payload) + `submitted_by`.

**Body (all header_payload):**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `run_number` | Run Number | text | inherited |
| `product` | Product | text | inherited |
| `tank` | Tank | text | inherited |
| `start_time` | Start time | time | operator |
| `finish_time` | Finish time | time | operator |
| `cartons_produced` | Cartons produced (office) | number | operator |
| `wine_volume` | Wine volume (office) | text | operator |
| `dip_tanks` | Dip tank start/end (repeatable pair) | array of `{label, start, end}` | operator |
| `filler_room_breakages` | Any filler room bottle breakages? (Y/N) | bool | operator |
| `initials` | Initials | text | operator |

---

## 2. Filler Line Check — `filler_line_check`

- **Accrual:** `matrix` (each hourly reading = one **column**) · **Orientation:** landscape
- **Doc #:** FOR PK 017A
- **Identity:** per-reading `initial`.

**Header fields:**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `wine` | Wine | text | inherited (product) |
| `tank` | Tank | text | inherited |
| `run_number` | Run Number | text | inherited |
| `filters_used` | Filters used (circle) | text | operator |
| `check_filtration` | Check filtration on form FOR LB 003? | enum(Yes,No) | operator |

**Reading fields (the matrix rows; each reading supplies one value/array per item):**

| Field key | Label (row item) | Type | Notes |
|-----------|------------------|------|-------|
| `captured_at` | Time | time | the reading clock |
| `filler_vacuum` | Filler Vacuum | text | |
| `rinser_all_heads` | Rinser — all heads working | text | |
| `filler_temperature` | Filler Temperature (18–22°C) | number | |
| `fill_height` | Fill Height (record 4 bottles) | number[4] | **multi-value** |
| `dissolved_oxygen` | Dissolved Oxygen (3 bottles) | number[3] | **multi-value** |
| `redraw` | Redraw (1.3–1.7 mm) | number | |
| `torque_bridge` | Torque & Bridge (6 consecutive bottles from head 1) | number[6] | **multi-value** |
| `bridge_inspection` | Bridge Inspection (record 4 bottles) | text[4] | **multi-value** |
| `wad_imprint` | Wad Imprint Check | text | |
| `initial` | Initial | text | **per-reading identity** |

> Render: rows = the field items above; each `reading` becomes a column, ordered by `sequence`.
> Multi-value cells render their N sub-values stacked within the single cell (matching paper).

---

## 3. Bottle Sealing Usage Log — `bottle_sealing`

- **Accrual:** `log` (row per reading) · **Orientation:** landscape · **Doc #:** FOR PK 016A
- **Identity:** per-reading `initial`.

**Header fields:**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `run_number` | Run number | text | inherited |
| `manufacturer` | Manufacturer | text | operator |
| `part_number` | Part number | text | operator |

**Reading fields (one row each):**

| Field key | Label | Type |
|-----------|-------|------|
| `captured_at` | Time | time |
| `batch_number` | Batch number | text |
| `matches_work_order` | Does it match work order? (Y/N) | bool |
| `qty_used` | Qty Used | number |
| `initial` | Initial | text (per-reading identity) |

---

## 4. Label Usage Sheet — `label_usage`

- **Accrual:** `log` · **Orientation:** portrait · **Doc #:** FOR PK 023
- **Identity:** per-reading `initial` (each half/row).
- **Note:** the paper form has **three parallel logs** — Fronts, Backs, Other. Model each
  reading with a `section` discriminator so one table drives all three render regions.

**Header fields:**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `product` | Product | text | inherited |
| `run_number` | Run no. | text | inherited |

**Reading fields (one row each):**

| Field key | Label | Type | Notes |
|-----------|-------|------|-------|
| `section` | which log | enum(fronts,backs,other) | render region |
| `captured_at` | Time | time | |
| `counter` | Counter | number | |
| `gms` | gms | number | |
| `matches_work_order` | Match Work Order? Y/N | bool | |
| `po_no` | P.O. no. | text | |
| `initial` | Initial | text | per-reading identity |

> **Totals** (`Qty: 10800`, `Total: 10972 @ 11:13`) start as **operator-entered** fields in
> `header_payload` (`totals_note`). Auto-calculation is deferred (`06` §5).

---

## 5. Finished Product Line Check — `finished_product_line_check`

- **Accrual:** `matrix` (column per reading) · **Orientation:** landscape · **Doc #:** FOR PK 019
- **Identity:** per-reading `initials`.

**Header fields:** `date` (inherited).

**Reading fields (matrix rows):**

| Field key | Label (row item) | Type |
|-----------|------------------|------|
| `captured_at` | Time | time |
| `run_number` | Run number | text (inherited default) |
| `front_label_height` | Front label height | number |
| `back_label_height` | Back label height | number |
| `gap_between_labels` | Gap between labels | text |
| `other_label_height` | Other label height | number |
| `label_inkjet_lot` | Label Inkjet Print / Record Lot Number / Capsule PVA | text |
| `inkjet_match` | Does it match work order? / Is it shrunk correctly? | bool (pair) |
| `bvs_code_match` | BVS code — match work order? | bool |
| `carton_barcode_match` | Carton barcode number — match work order? | bool |
| `carton_print_match` | Carton print — match work order? | bool |
| `carton_sticker_match` | Carton Sticker — match work order? | bool |
| `bottles_scraped_clean` | Bottles Scraped — are they clean? | bool |
| `initials` | Initials | text (per-reading identity) |

---

## 6. Packaging Materials Pick List — `pick_list`

- **Accrual:** `atomic` (fixed rows, edited in place) · **Orientation:** portrait
- **Identity:** `submitted_by`.

**Header fields:** `run_number`, `stock_item`, `description`, `packing_unit`, `packaging_line`,
`run_date`, `run_quantity` — all **inherited**.

**Body — one row per stock item** (rows come from `batch_header.pick_list_lines`; operators
fill the right-hand columns). Stored as an array in `header_payload.lines`:

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `stock_item` | Stock Item | text | inherited |
| `description` | Description | text | inherited |
| `required` | Required (THOU) | number | inherited (**no EzyWine source — from batch header**) |
| `supplied_qty` | Supplied — Qty | number | operator |
| `supplied_haccp` | Supplied — HACCP | text | operator |
| `returned_qty` | Returned — Qty | number | operator |
| `returned_haccp` | Returned — HACCP | text | operator |
| `used` | Used | number | operator |
| `wastage` | Wastage | number | operator |

> The handwritten supplied/returned arithmetic (`2×5400`, `1×884`…) is captured as the
> operator's entered `supplied_qty`/`used` values; computed reconciliation is deferred.

---

## 7. Carton Usage and Quality Control — `carton_qc`

- **Accrual:** `log` — **two** row-accruing tables · **Orientation:** landscape · **Doc #:** FOR PK 018
- **Identity:** per-row `initials` in both tables.
- Model with a `table` discriminator (`carton_details` | `hourly_qc`).

**Header fields:** `date` (inherited).

**Table A — Carton details (`table=carton_details`), one row each:**

| Field key | Label | Type |
|-----------|-------|------|
| `carton_manufacturer` | Carton Manufacturer | text |
| `carton_code` | Carton code | text |
| `qty_on_pallet` | Quantity On Pallet | number |
| `carton_code_match` | Carton code match work order? (Y/N) | bool |
| `batch_number_pallet_tag` | Batch number on pallet tag | text |
| `dividers_match` | Dividers match work order? (Y/N/NA) | enum(Y,N,NA) |
| `stickers_match` | Do stickers match work order? (Y/N/NA) | enum(Y,N,NA) |
| `initials` | Initials | text (identity) |

Plus a header-level `carton_wastage` (number) and `divider_wastage` (number) in header_payload.

**Table B — Hourly QC Check (`table=hourly_qc`), one row each:**

| Field key | Label | Type |
|-----------|-------|------|
| `captured_at` | Date/Time | time |
| `cartons_formed_glued` | Cartons being formed & glued correctly? Y/N | bool |
| `check_6_cartons` | Check 6 consecutive cartons — belt full & weight working? Y/N | bool |
| `carton_print_match` | Carton Print to match work order? Y/N | bool |
| `record_carton_print` | Record Carton print | text |
| `glue_shots_ok` | Glue shots in correct place, no glue on bottles? Y/N | bool |
| `cartons_sealed_neatly` | Are cartons sealed properly and neatly? Y/N | bool |
| `initials` | Initials | text (identity) |

---

## 8. Final Pallet Count Sheet 1 — `final_pallet_count`

- **Accrual:** `log` (row per pallet/finished entry) · **Orientation:** portrait · **Doc #:** FOR PK 012A
- **Identity:** header `operator` + (optional) per-row.
- Two row-regions: **Bottles** and **Finished Product**; use a `region` discriminator.

**Header fields:**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `run_number` | Run # | text | inherited |
| `bottle_code` | Bottle Code | text | operator |
| `bottle_code_matches` | Bottle code matches work order? (Y/N) | bool | operator |
| `product` | Product | text | inherited |
| `operator` | Operator | text | operator (identity) |
| `manufacturer` | Manufacturer | text | operator |
| `pallet_tag_matches` | Pallet tag(s) matches work order? (Y/N) | bool | operator |
| `bottle_breakages` | Bottle Breakages | number | operator |
| `carton_breakages` | Carton Breakages | number | operator |
| `summary_note` | free totals note (e.g. "12 pallets + 2 layers") | text | operator |

**Reading fields — Bottles region (`region=bottles`):**

| Field key | Label | Type |
|-----------|-------|------|
| `seq_no` | # | number |
| `prn_date` | PRN date | date |
| `pallet_no` | Pallet # | text |
| `colour` | Colour | enum(AB,A,F) — Arctic Blue / Antique / French |
| `foreign_objects_checked` | Checked for foreign objects? | bool |
| `captured_at` | Time | time |

**Reading fields — Finished Product region (`region=finished`):**

| Field key | Label | Type |
|-----------|-------|------|
| `seq_no` | # | number |
| `high` | High | number |
| `captured_at` | Time | time |

---

## 9. Finished Product / Warehouse Pallet Count — `finished_product_pallet`

- **Accrual:** `log` (row per pallet) · **Orientation:** portrait · **Doc #:** FOR PK 020A
- **Identity:** header `operator`.

**Header fields:**

| Field key | Label | Type | Source |
|-----------|-------|------|--------|
| `date` | Date | date | inherited |
| `product` | Product | text | inherited |
| `run_number` | Run no. | text | inherited |
| `operator` | Operator | text | operator (identity) |
| `bottle_code` | Bottle code | text | operator |
| `bottle_code_matches` | Does bottle code match work order? (Y/N) | bool | operator |
| `pallet_type` | Pallet type | text | operator |
| `slip_sheet_required` | Slip sheet required? (Y/N) | bool | operator |
| `layer_config_matches` | Pallet layer configuration matches work order? (Y/N) | bool | operator |
| `stack_height_matches` | Pallet stack height matches work order? (Y/N) | bool | operator |
| `breakages` | Breakages | number | operator |
| `summary_note` | free totals note (e.g. "21×84, 1×53 = 1817") | text | operator |

**Reading fields (one row each):**

| Field key | Label | Type |
|-----------|-------|------|
| `seq_no` | # | number |
| `high` | High | number |
| `captured_at` | Time | time |

---

## Cross-cutting build notes

- **Inherited fields** are pre-filled from `batch_header` and shown read-only (or
  override-with-warning) so operators never re-key run identity.
- **Bool fields** render as Y/N (some forms use Y/N/NA — use the enum where shown).
- **Multi-value cells** (`[×N]`) must render exactly N inputs and validate length on save
  (`02` §6).
- **Per-reading identity** is mandatory on `reading` for every accrual form (`05` §4).
- **Totals/calculations** are operator-entered free fields in the prototype; mark them in the
  UI as "auto later" so the deferral is intentional (`06` §5).
