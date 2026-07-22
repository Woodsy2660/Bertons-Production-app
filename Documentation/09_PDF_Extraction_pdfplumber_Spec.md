# 09 — PDF Extraction Rewrite (pdfplumber) + Extraction Validation Page

**Status:** Spec — to build before the pallet-tag printer feature.
**Supersedes:** the pypdf + flatten-then-regex approach in `work_order_parser.py`.
**Depends on:** nothing new server-side beyond the `pdfplumber` dependency.
**Blocks:** the pallet-tag feature (which needs reliable `cartons_per_pallet` + `run_quantity`).

---

## 1. Objective

Replace the current `pypdf.extract_text()` + regex extraction with a **pdfplumber, layout-aware,
anchor-based** parser that reliably reads the EzyWine "Packaging Run Work Order" — and ship a
**standalone extraction-validation page** where a work order PDF can be dropped and *every* field
is shown with its extracted value, its source anchor, and a found/missing flag, so extraction can
be verified across many real work orders **before** the printer feature is built on top of it.

Two deliverables:

1. **Parser rewrite** — `work_order_parser.py` on pdfplumber, targeting the real EzyWine layout,
   backward-compatible output plus new fields.
2. **Validation page** — a dev/QA HTML tool (`/dev/work-order-parser`) that runs the parser on an
   uploaded PDF and renders full field-by-field results. No DB writes.

## 2. Why pdfplumber (recap)

MIT-licensed, pure-Python, installs into the existing container, runs in milliseconds on the CPU
VM. Critically it exposes **word/character coordinates** and **layout-preserving text**, which is
what makes anchor-based extraction on a fixed monospaced report reliable. OCR is **not** used —
these are native text PDFs from EzyWine's report engine; OCR stays a deferred fallback (§8). Do
**not** pull in ML/GPU document toolkits (PDF-Extract-Kit/MinerU) — wrong tool, wrong deployment,
AGPL licence.

## 3. The EzyWine work order structure (what we anchor to)

The report is a fixed-layout, monospaced ASCII-box document from one source system. **The table
borders are text glyphs, not vector lines** — pypdf renders them as noise (`faaaa…`, `b`, `daaaa…`,
`iaaa…kaaa…j`). This is the single most important fact for the rewrite:

- **Do NOT** use pdfplumber's line-based table detection (`vertical_strategy="lines"`) — there are
  no vector lines to find.
- **DO** use `page.extract_text(layout=True)` to preserve the monospaced column grid, then parse
  line-by-line anchored on known labels/codes. Optionally use `page.extract_words()` (with x/y
  coords) for positional value reads where a line is ambiguous.
- **Filter border noise** by content: ignore tokens that are pure box-glyph runs
  (e.g. `^[abcdefghijk]{3,}$` sequences, lone `b`/`d`/`f` column markers) — work from tokens with
  real content.

The document has three anchor regions:

### 3a. Header box (label : value pairs)
Real EzyWine labels (target these exact strings, not generic lowercase):

| Label in PDF | Field | Example (15646 / 15778) |
|--------------|-------|-------------------------|
| `Run No./Ref.` | `run_number` | 15646 / 15778 |
| `Stock Item` | `stock_item` | F22CSARESAI6 / F26PNOFSTAI1 |
| `Stock Alias` | `stock_alias` | RESERVE / FST |
| `Description` | `description` (= product) | Reserve 2022 Cab Sauvignon AI / Foundstone 2026 Pinot Noir AI |
| `Packing Unit` | `packing_unit` | 6750  6 x 750ml Bottles / C750  12 x 750ml Bottles |
| `Vessel/Batch` | `vessel_batch` | Z302 / (blank) |
| `Volume/Alloc.` | `volume_alloc` | 0 / 0 |
| `Run Status` | `run_status` | Wine & Packaging ready / Nothing ready |
| `Packaging Line` | `packaging_line` | BERT / BERT |
| `Start` | `start_datetime` | 05/06/26 0:00 / 14/07/26 0:00 |
| `Est. Finish` | `est_finish` | … |
| `Hourly Rate` | `hourly_rate` | 0 / 500 |
| `Est. Run Time` | `est_run_time` | 0.00 Hrs / 0.38 Hrs |
| `Run Quantity` | `run_quantity` | 1800 / 192 |
| `Min. Operators` | `min_operators` | 5 / 5 |
| `Add. Operators` | `add_operators` | 0 / 0 |
| `Tot. Operators` | `tot_operators` | 5 / 5 |

> **Note on `tank`:** the work order has **no "Tank" field** — it has `Vessel/Batch` (Z302), which
> is **not** the filler tank the operator records on the Daily Production Sheet (B113). The current
> parser's `tank:` regex therefore never matches a real work order. Extract `vessel_batch`; leave
> `tank` as operator-entered. Flag this mapping in the header (don't silently map vessel→tank).

### 3b. Stock-item table
Columns: `Stock Item | Description | Unit | Required Total | Usage | Ref.`
Each row → `{code, description, unit, required_total}`. Label stock = codes matching the L-prefix
rule (§5). Wine (`F…`, `W…`), cartons (`C…`), closures (`DV…`, `BV…`, `BT…`) are non-label.

### 3c. Detail / Value table (the stable code anchors)
Columns: `Detail | Name | Value`. The detail **codes are the most reliable anchors in the whole
document** — stable keys regardless of spacing:

| Code | Name | Field | Feeds |
|------|------|-------|-------|
| `G001` | Carton Printing – Line one | `carton_print_line1` | pallet tag / carton QC |
| `G002` | Carton Printing – Line two | `carton_print_line2` | |
| `G003` | Ctn printing – Line continuing | `carton_print_line3` | |
| `L007` | Front Label Height | `front_label_height` | line checks |
| `L008` | Label Barcode | `label_barcode` | (present in 15778: 9335966006737) |
| `L010` | Back Label Height | `back_label_height` | |
| `L016` | Other Label Height | `other_label_height` | |
| **`P000`** | **Pallet – Cartons/Pallet** | **`cartons_per_pallet`** | **← PALLET-TAG FEATURE** |
| `P001` | Pallet – Cartons/Layer | `cartons_per_layer` | |
| `P002`/`P003` | Pallet – N Layers | `pallet_layers` | |
| `P005` | Pallet – Type | `pallet_type` | |
| `P006` | Pallet – Tag | `pallet_tag_flag` | |
| `P009` | Pallet – Stretch Wrap | `pallet_stretch_wrap` | |
| `P010` | Pallet – Top Wrap | `pallet_top_wrap` | |
| `P012` | Pallet – Slip Sheet | `pallet_slip_sheet` | |

Anchor regex on layout-preserved lines (illustrative):
```python
DETAIL_ROW_RE = re.compile(r"^\s*([A-Z]\d{3})\s+(.+?)\s{2,}(.+?)\s*$")
# group1 = code (P000), group2 = name, group3 = value (64.0000)
```
`P000` → `cartons_per_pallet` is the field the pallet-tag feature divides Run Quantity by, so it is
a **first-class, must-extract** field, surfaced prominently on the validation page (§7).

## 4. Parser API (backward-compatible)

Keep the existing entry point and output keys so callers (`main.py`, `document_management.py`,
Pick List form) don't break; **add** new keys.

```python
def parse_work_order_pdf(pdf_bytes: bytes) -> dict:
    """Backward-compatible: returns the existing keys plus the new ones below."""
```

**Existing keys (unchanged shape):** `product`, `stock_item`, `packing_unit`, `packaging_line`,
`run_quantity`, `pick_list_lines`, `parse_note`. (`tank` retained but now sourced as
`vessel_batch`; see §3a note — recommend returning `vessel_batch` and keeping `tank=None`.)

**New keys:** `run_number`, `stock_alias`, `description`, `run_status`, `start_datetime`,
`cartons_per_pallet`, `cartons_per_layer`, `pallet_layers`, `pallet_type`, `front_label_height`,
`back_label_height`, `other_label_height`, `label_barcode`, `carton_print_line1/2/3`,
`stock_table_lines` (all rows, not just label), `details` (dict of code→value).

**`pick_list_lines` shape unchanged** (so the Pick List form keeps working):
```json
{ "stock_item": "LBRESCSA22AI", "description": "...", "required": 10800,
  "supplied_qty": null, "returned_qty": null }
```
`filter_label_lines()` and `is_label_stock()` keep their current contracts.

### 4a. Verbose variant for validation/provenance
Add a sibling that returns per-field provenance for the validation page (and useful for debugging):
```python
def parse_work_order_pdf_verbose(pdf_bytes: bytes) -> dict:
    """
    Returns:
    {
      "fields": [
        {"key": "run_number", "label": "Run No./Ref.", "value": "15778",
         "source": "header", "anchor": "Run No./Ref.", "found": true},
        {"key": "cartons_per_pallet", "label": "Pallet - Cartons/Pallet",
         "value": "64.0000", "source": "detail:P000", "found": true},
        ...
      ],
      "stock_table_lines": [ {code, description, unit, required_total, is_label} ],
      "details": { "P000": "64.0000", "L007": "25mm", ... },
      "raw_layout_text": "...",         # extract_text(layout=True), for eyeballing
      "parse_note": null,
      "warnings": [ ... ]
    }
    """
```
`parse_work_order_pdf()` becomes a thin adapter over the verbose result (maps `fields` → the flat
compatible dict), so there is **one** extraction implementation, two views.

## 5. Label-stock rule (unchanged)
```python
LABEL_STOCK_RE = re.compile(r"^L[A-Z0-9]{3,14}$", re.IGNORECASE)
```
Keep the L-prefix filter and the `LABEL`/`LINE`/`LTR` false-positive skips. The rewrite improves
*how rows are found* (real table columns via layout), not the label classification.

## 6. Extraction strategy (implementation notes)

1. `pdfplumber.open(BytesIO(pdf_bytes))`; iterate pages.
2. `text = page.extract_text(layout=True)` → preserves the monospaced grid. This alone fixes most
   current fragility (the old flatten collapsed the columns).
3. **Header region:** for each label in §3a, find its line, take the text after the label token
   within the same visual row; for the right-column labels (Packaging Line, Run Quantity, …) that
   share a line with left-column labels, split on column x-position using `extract_words()` coords
   or a fixed column split derived from the label positions.
4. **Detail table:** apply `DETAIL_ROW_RE` per line; build `details = {code: value}`; map codes →
   named fields via a static `DETAIL_CODE_MAP`.
5. **Stock table:** locate the header row (`Stock Item … Description … Unit … Required`), then read
   subsequent rows by the column x-ranges (from `extract_words()`), producing `stock_table_lines`;
   derive `pick_list_lines` by filtering to label stock.
6. **Noise filter:** drop pure box-glyph tokens before parsing.
7. Assemble the verbose result; adapt to the compatible dict.

Keep everything in `work_order_parser.py`. `pypdf` remains only for PDF **merging** in
`compilation.py` — not for parsing.

## 7. Deliverable 2 — Extraction Validation Page

A standalone dev/QA tool to verify extraction on real work orders before the printer feature.

### 7a. Routes
- `GET /dev/work-order-parser` → renders the page (drop zone + empty results).
- `POST /dev/work-order-parser/parse` → accepts a single PDF (multipart), runs
  `parse_work_order_pdf_verbose()`, returns JSON (page renders client-side) **or** re-renders the
  template server-side with results. Either is fine; JSON keeps it simple.
- **No database writes. No batch creation.** Pure extraction preview.

### 7b. Gating
Dev/QA only. Gate behind **both**: manager role **and** an env flag `ENABLE_DEV_TOOLS=true`
(default false in production). Not linked from the operator UI. This keeps a raw parser-preview
tool out of the production floor surface.

### 7c. What the page shows
On drop/upload, render:

1. **Pallet-feature inputs (top, highlighted callout)** — the two fields the printer feature
   depends on, shown first so they're easy to verify:
   - `run_quantity` (Run Quantity)
   - `cartons_per_pallet` (P000)
   - computed `pallets = ceil(run_quantity / cartons_per_pallet)` — shown for eyeball validation
     against the operator's expectation for that run. Flag clearly if either input is missing.
2. **Header fields table** — columns: *Field · Label in PDF · Extracted value · Source/anchor ·
   Found?* One row per §3a field. Missing fields highlighted.
3. **Detail codes table** — every `code → name → value` found (§3c), P000 highlighted.
4. **Stock-item table** — every row with an `is_label` flag column; label rows highlighted so you
   can confirm the L-prefix filter caught the right lines and nothing else.
5. **Parse notes / warnings** — `parse_note`, any per-field warnings, and an explicit banner if the
   PDF was image-based (empty text layer).
6. **Raw layout text (collapsible)** — `extract_text(layout=True)` output, monospaced, for
   side-by-side eyeballing against the source PDF.

### 7d. Purpose
Lets you run 10–20 real work orders through and confirm, before building the printer feature, that:
`run_number`, `run_quantity`, `cartons_per_pallet`, the label stock lines, and the tag fields all
extract correctly across the range of real documents — and see immediately where any layout variant
breaks a field.

## 8. Image-based fallback (deferred)
Detect empty/low text (`len(text.strip()) < threshold`) → set
`parse_note = "Work order is image-based — fields could not be auto-extracted."` and return empties
(current behaviour, preserved). OCR (local Tesseract + rasterise) is **not built now**; it's a
future branch triggered only by this detection. The validation page shows the image-based banner so
the case is visible.

## 9. Tests
Update/extend `tests/test_work_order_parser.py`:

- Keep existing `is_label_stock()` / `filter_label_lines()` tests.
- Add **fixture-based tests** using the real work orders (15646, 15778) as committed sample PDFs:
  - `run_number`, `stock_item`, `run_quantity`, `packing_unit`, `packaging_line` extract exactly.
  - `cartons_per_pallet` == 84 (15646) and 64 (15778) — the pallet-feature guardrail.
  - `pick_list_lines` contains exactly the L-prefixed rows (3 for 15646), with correct
    `required` values, and **excludes** wine/carton/closure rows.
  - `details["P000"]` present; `vessel_batch` extracted; `tank` is None (not mapped from vessel).
  - Image-based input → correct `parse_note`, no crash.
- Add a test that `parse_work_order_pdf()` (compatible view) and `parse_work_order_pdf_verbose()`
  agree on shared fields.

## 10. Migration / rollout
1. Add `pdfplumber` to dependencies; keep `pypdf` (used by compilation merge only).
2. Implement the verbose parser + compatible adapter in `work_order_parser.py`.
3. Wire the validation page (routes + template + `ENABLE_DEV_TOOLS` gate).
4. Run the fixtures + a batch of real work orders through the validation page; tune anchors.
5. Only once extraction is verified: unblock and start the pallet-tag printer feature.
6. Callers (`main.py` create flow, `document_management.refresh_header_from_work_order`, Pick List
   re-parse) need **no changes** — the compatible output keys are preserved.

## 11. Acceptance criteria
- All existing callers work unchanged; `pick_list_lines` shape identical.
- On the two real sample work orders, the validation page shows correct values for: run number,
  stock item, run quantity, packing unit, packaging line, `cartons_per_pallet` (P000), and the
  label pick-list lines — with no non-label rows leaking in.
- `pallets = ceil(run_quantity / cartons_per_pallet)` computes correctly on both samples.
- Image-based PDFs are detected and reported, not silently empty.
- Validation page is inaccessible in production (flag off) and to operators.
- Unit tests (incl. the P000 == 84/64 guardrail) pass.

## 12. Out of scope (this spec)
- The pallet-tag calculation UI, tag template, and printer integration (next spec, `10`).
- OCR implementation.
- Any change to the label-stock classification rule.
- Structured PDF-table-object parsing (not needed — layout text + anchors suffices).
