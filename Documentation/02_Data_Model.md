# 02 — Data Model

## 1. Design principles

1. **The batch is the root.** Everything hangs off one bottling run.
2. **Form *templates* are configuration, not data.** The fields, accrual mode, orientation and
   multi-value cells of each form are defined in code/config (see `03`), keyed by `form_type`.
   The database stores *instances* and *values*, not field definitions. This means adding or
   tweaking a form is a template change, not a migration.
3. **One abstraction covers atomic, log, and matrix forms.** A `form_instance` holds
   non-repeating data; a `reading` holds one timestamped, operator-attributed entry. Whether a
   reading renders as a **row** (log) or a **column** (matrix) is decided by the template at
   render time, not stored differently.
4. **Payloads are JSONB, metadata is columns.** Field values live in JSONB (flexible per form,
   supports multi-value arrays). The things we filter/sort/audit on — batch, form, operator,
   timestamp, status — are real columns.

## 2. Entity overview

```
batch ──┬── batch_header (1:1, or embedded)
        ├── uploaded_document (1:N)   ── compile slot + ordering
        ├── form_instance (1:N)       ── one per form_type
        │       └── reading (1:N)     ── accrual entries (log/matrix)
        └── compilation (1:N)         ── each compile attempt / output PDF
```

## 3. The reading abstraction (the spine)

The crux of the model. Worked through all nine forms:

- A **reading** = one timestamped observation by one operator.
- **Log forms** (Bottle Sealing, Label Usage, Carton tables, both Pallet Counts): each reading
  is **one row**. Add a reading → add a row.
- **Matrix forms** (Filler Line Check, Finished Product Line Check): the check-items are a fixed
  list (the rows); each reading is **one time-column** across them. Add a reading → add a column.
- **Atomic forms** (Daily Production Sheet, Pick List): no time-accrual; data sits in the form
  instance's `header_payload` (Pick List's per-stock-item lines are a fixed array there).

In all cases a reading carries a **payload** keyed by the template's field keys. A field's
value may be a scalar or a **fixed-length array** (multi-value cells — e.g. Filler Line Check
Fill Height = 4 values). Orientation never changes the storage — only the render.

## 4. Tables

### `batch`
The run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `run_number` | text, unique | e.g. `15646`. Manager-entered. |
| `status` | text enum | `draft` \| `in_progress` \| `ready` \| `compiled` \| `reopened`. See `05` §1. |
| `is_locked` | boolean | True when compiled and not reopened. |
| `created_by` | text | Manager identity. |
| `created_at` / `updated_at` | timestamptz | |

### `batch_header`
Run-level fields inherited by all forms. 1:1 with batch (can be embedded as JSONB on `batch`;
shown separate for clarity). Sourced manually in the prototype (EzyWine stub returns none).

| Column | Type | Notes |
|--------|------|-------|
| `batch_id` | uuid FK | |
| `product` | text | e.g. `Reserve 2022 Cab Sauvignon AI`. |
| `stock_item` | text | e.g. `F22CSARESAI6`. |
| `tank` | text | e.g. `B113` / `Z302`. |
| `run_date` | date | |
| `packing_unit` | text | e.g. `6750  6 x 750ml Bottles`. |
| `packaging_line` | text | e.g. `BERT`. |
| `run_quantity` | integer | e.g. `1800`. |
| `pick_list_lines` | jsonb | Array of `{stock_item, description, required_qty, unit}` — feeds the Pick List "Required" column, which has no source once EzyWine is out of scope. See `03` Pick List. |
| `extra` | jsonb | Any other header values forms reference. |

> **Gap #6 resolution:** the Pick List Required quantities and per-form header data have no
> automated source in the prototype, so they are captured here at batch creation and inherited
> downstream. Keep the creation form short; only ask for what forms actually consume.

### `uploaded_document`
Manager-uploaded PDFs destined for compile slots.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `batch_id` | uuid FK | |
| `slot` | text enum | `ezywine_listing` \| `work_order` \| `label_reference`. Drives placement in `04`. |
| `sequence` | integer | Order **within** a slot (matters for `label_reference`, which is flexible-length). |
| `original_filename` | text | |
| `stored_path` | text | Path in the file store (not a network folder). |
| `page_count` | integer | Cached after upload; used for compile sanity checks. |
| `uploaded_by` | text | |
| `uploaded_at` | timestamptz | |

> **Gap #2 resolution (label references):** the `label_reference` slot accepts **0..N** files.
> The manager may upload one, several, or all of the distributor label proofs/print sheets.
> They append in `sequence` order into the single label-references position in the final
> document. `ezywine_listing` and `work_order` are expected to be 0..1 each.

### `form_instance`
One form for one batch.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `batch_id` | uuid FK | |
| `form_type` | text enum | `daily_production` \| `filler_line_check` \| `bottle_sealing` \| `label_usage` \| `finished_product_line_check` \| `pick_list` \| `carton_qc` \| `final_pallet_count` \| `finished_product_pallet`. Maps to a template in `03`. |
| `accrual_mode` | text enum | `atomic` \| `log` \| `matrix`. Denormalised from the template for query convenience. |
| `status` | text enum | `not_started` \| `in_progress` \| `submitted` \| `edited_since_submit`. See `05` §2. |
| `header_payload` | jsonb | Form-level header fields; for **atomic** forms, the entire body lives here. |
| `submitted_by` | text | Identity for atomic-form submission. |
| `submitted_at` | timestamptz | |
| `last_edited_by` | text | Set on any post-submit edit (preserves `submitted_by`). |
| `last_edited_at` | timestamptz | Drives the status board's "edited since" + freshness. |

Unique constraint: `(batch_id, form_type)` — one instance per form per batch.

### `reading`
Accrual entries for log/matrix forms.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `form_instance_id` | uuid FK | |
| `sequence` | integer | Stable order of entries (column order / row order). |
| `captured_at` | timestamptz | The reading's own timestamp (the form's "Time" value); defaults to entry time, editable to match the run clock. |
| `operator_identifier` | text | **Per-reading identity** (Gap #5). Who entered this reading. |
| `payload` | jsonb | `{field_key: value | value[]}`. Multi-value cells store arrays. |
| `created_at` / `updated_at` | timestamptz | |

> **Gaps #3 & #4 resolution:** `reading` covers both accrual shapes (row vs column is a
> template/render decision, not a schema difference), and `payload` permits a field to hold a
> fixed-length **array** for multi-value cells (Fill Height ×4, DO ×3, Torque & Bridge ×6,
> Bridge Inspection ×4).

### `compilation`
Each compile attempt / generated document.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `batch_id` | uuid FK | |
| `output_filename` | text | e.g. `15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf` (`04` §4). |
| `stored_path` | text | |
| `slot_manifest` | jsonb | The resolved 16-slot → source mapping actually used (audit). |
| `is_current` | boolean | False once the batch is reopened/edited after this compile (`05` §3). |
| `compiled_by` | text | |
| `compiled_at` | timestamptz | |

## 5. Worked payload examples

**Matrix reading — Filler Line Check** (one hourly column; multi-value cells as arrays):

```json
{
  "sequence": 3,
  "captured_at": "2026-06-05T09:10:00+10:00",
  "operator_identifier": "AHS",
  "payload": {
    "filler_vacuum": "-6",
    "rinser_all_heads": "yes",
    "filler_temperature": "15.5",
    "fill_height": ["32", "32", "31", "32"],
    "dissolved_oxygen": ["1.09", "1.07", "0.91"],
    "redraw": "1.41",
    "torque_bridge": ["20", "12", "19", "16", "20", "13"],
    "bridge_inspection": ["y", "y", "y", "y"],
    "wad_imprint": "y"
  }
}
```

**Log reading — Bottle Sealing Usage** (one row):

```json
{
  "sequence": 1,
  "captured_at": "2026-06-05T08:10:00+10:00",
  "operator_identifier": "AHS",
  "payload": {
    "batch_number": "M10-0414155-176425",
    "matches_work_order": "Y",
    "qty_used": "1700"
  }
}
```

**Atomic form — Daily Production Sheet** (all in `form_instance.header_payload`):

```json
{
  "date": "2026-06-05",
  "run_number": "15646",
  "product": "Reserve 2022 Cab Sauvignon AI",
  "tank": "B113",
  "start_time": "8:35",
  "finish_time": "11:10",
  "cartons_produced": "1817",
  "wine_volume": "8319L",
  "dip_tanks": [{"start": "1.64", "end": "empty"}],
  "filler_room_breakages": "N",
  "initials": "AHS"
}
```

## 6. Indexing & integrity notes

- Index `reading(form_instance_id, sequence)` and `form_instance(batch_id, form_type)`.
- Enforce `uploaded_document(batch_id, slot, sequence)` ordering for deterministic compiles.
- Validate `payload` against the template on write (correct keys, array lengths for
  multi-value cells) so a malformed reading fails loudly rather than corrupting a compile.
- `batch.is_locked` gates all writes to child rows (`05` §3) — enforce in the API layer.
