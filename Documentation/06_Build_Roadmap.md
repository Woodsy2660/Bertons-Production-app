# 06 — Build Roadmap

A phased plan that gets to a usable prototype quickly while keeping the integration seams clean.
Each phase is independently demonstrable.

## Phase 0 — Foundations

**Goal:** the skeleton everything else hangs off.

- Stand up the application host, local **Postgres**, file store (`01`).
- Implement the schema + migrations (`02`): `batch`, `batch_header`, `form_instance`,
  `reading`, `uploaded_document`, `compilation`, `operators`.
- Implement the **form-template registry** in code (field defs, accrual mode, orientation,
  multi-value cells) keyed by `form_type` (`03`). This is config, not DB.
- Payload validation against templates (key/array-length checks, `02` §6).
- Define the **EzyWine stub interface** (`01` §6) with manual implementations.

**Done when:** a batch can be created via API with a header, and rows persist correctly.

## Phase 1 — Batch creation & uploads (manager)

**Goal:** the manager can set up a run.

- Batch-creation UI: run number + short header (only fields forms consume) +
  `pick_list_lines`.
- Labelled **upload slots**: `ezywine_listing` (0..1), `work_order` (0..1), `label_reference`
  (**0..N**, orderable) — per `04` §3. Validate PDFs at upload; cache `page_count`.
- Operator lookup seed (name + initials).

**Done when:** a batch exists with header + uploads, visible in a basic board.

## Phase 2 — Forms: atomic first

**Goal:** prove the simplest data path end to end.

- Build the two **atomic** forms: `daily_production`, `pick_list` (`03`).
- Inherited-field pre-fill from `batch_header`.
- Submit + edit lifecycle; `submitted_by`; status transitions (`05`).

**Done when:** atomic forms can be filled, submitted, edited; board reflects status.

## Phase 3 — Forms: accrual (log then matrix)

**Goal:** the hard part of the data model, proven.

- **Log** forms first: `bottle_sealing`, `label_usage` (3 sections), `carton_qc` (2 tables),
  `final_pallet_count` (2 regions), `finished_product_pallet`.
- **Matrix** forms: `filler_line_check`, `finished_product_line_check` — column-per-reading UI,
  **multi-value cells** (Fill Height ×4, DO ×3, Torque & Bridge ×6, Bridge Inspection ×4).
- **Per-reading identity** prompt before save (`05` §4).
- Reopen-to-add-reading; submit; edit-after-submit → `edited_since_submit`.

**Done when:** an operator can accrue hourly readings across a run, attributed per reading, and
the data round-trips.

## Phase 4 — Compilation

**Goal:** the deliverable.

- HTML/CSS **form templates** (one per `form_type`), sharing a header partial that carries the
  **client-supplied logo + document-control metadata** (`04` §5).
- Render engine (HTML→PDF, orientation per slot) + pagination for long runs.
- **16-slot merge** with the flexible label-references group (`04` §1–3).
- Output naming (`04` §4); `compilation` records + `slot_manifest`.
- **Lock-on-compile / reopen / stale** handling (`05` §3).

**Done when:** compiling run 15646 from entered data + uploads produces a correctly-ordered,
correctly-named PDF that visually matches the reference document closely enough for QA sign-off.

## Phase 5 — Status board & polish

**Goal:** make it usable on the floor.

- Full manager **status board** (`05` §5): forms grid with status + last-updated + reading
  counts, uploads checklist, compile/override, download, reopen, lock indicator.
- Tablet ergonomics: large targets, fast entry, sensible defaults for `captured_at`.
- Readiness warnings + override-compile.

**Done when:** a manager can run a real bottling run through the app start to finish.

---

## Suggested build order rationale

Atomic → log → matrix → compile is deliberate: each step adds exactly one hard thing (inherited
fields, then row-accrual + per-reading identity, then column/matrix + multi-value cells, then
fidelity rendering). Compilation comes after the data model is proven so the templates render
real data, not placeholders.

## Validation milestone: replay run 15646

The reference run (`15646`) is a full, real dataset. Use it as the acceptance test end to end:
enter its forms from the source PDFs, upload its EzyWine listing + label references, compile,
and diff the output against
`15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf` for order, naming, and per-form fidelity.

---

## 5. Open decisions log

None block starting. Confirm as you reach the relevant phase.

| # | Decision | Default if unconfirmed | Phase |
|---|----------|------------------------|-------|
| D1 | Exact fidelity bar per form (pixel-match vs clean equivalent) | Clean, legible equivalent accepted by QA | 4 |
| D2 | Final logo + document-control metadata (issue no/date, authoriser) | Placeholder until client provides | 4 |
| D3 | Auto-calculated totals (Label Usage total, Pick List arithmetic, pallet totals) | Operator-entered free fields for now | post-proto |
| D4 | Partial-compile policy (compile before all forms in?) | Allowed via explicit override, warnings shown | 4/5 |
| D5 | Wrong-run upload detection (listing/labels for a different run) | Not detected in prototype; known limitation | post-proto |
| D6 | Operator identity granularity (pick-list vs initials vs later real auth) | Seeded operator pick-list (name+initials) | 3 |
| D7 | Host co-location (work server vs separate VM) | Separate LAN host preferred for isolation | 0 |
| D8 | HTTPS timing (needed only when scanner ships) | Defer, but keep host proxy-ready | post-proto |
| D9 | Where the finished PDF goes | Manager downloads + files manually | 4 |

## Integration migration trigger (post-prototype)

Revisit the EzyWine stub (`01` §6) when **either**: real-time or bidirectional EzyWine data
becomes a hard requirement, **or** Berton adopts EzyWine PRO (whose API replaces the
CSV/Vin6-export path). At that point only the `RunDataProvider` implementation and the scanner
module change; the form, data, lifecycle, and compile layers are unaffected by design.
