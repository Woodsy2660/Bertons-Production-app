# 11 — Pallet Tag Printing

**Status:** Spec — build on `09` (extraction) and `10` (stored extract).
**Depends on:** working extraction of `run_number`, `stock_item`, `description`, `packing_unit`,
`run_quantity`, `cartons_per_pallet` (P000).
**Pending hardware confirmations (from `08` / .nxt):** printer make/model, whether network-attached,
whether the VM can reach it, and the physical tag size / A4 layout. These block the **print-dispatch
wiring** and the **final tag dimensions**, not the rest of the feature — see §7, §8.

---

## 1. Objective

From a batch's work order, calculate how many pallets the run needs, let the manager confirm/adjust,
generate pallet tags in the **exact EzyWine tag format**, and print them on the office printer.
Operators can print additional tags if more pallets are needed or the calculation was off.

## 2. Pallet-count calculation

```
pallets = ceil(run_quantity / cartons_per_pallet)
```

- `run_quantity` is in **cartons** (confirmed), `cartons_per_pallet` is detail code **P000**.
- **Ceiling** always: a partial pallet still gets a full tag.
- Worked checks: 15778 → 192 / 64 = 3 pallets. 15646 → 1800 / 84 = 21.4 → **22** pallets.
- Both inputs come from the stored extract (`10`). If either is missing, the calculation is not
  offered and the confirmation screen shows why (extract the missing field first).

This calc is exactly what the extraction-validation page (`09` §7) already surfaces, so it can be
sanity-checked on real orders before this feature ships.

## 3. Workflow

1. From a batch that **has a work order** (any lifecycle state — not gated to complete), the user
   opens **Print Pallet Tags**.
2. **Confirmation screen** shows the extracted inputs and the computed count:
   - Run number, stock code, product, size (the tag fields).
   - `run_quantity`, `cartons_per_pallet`, and computed `pallets`.
   - An editable **"tags to print"** number, defaulted to the computed `pallets`. The manager can
     override (miscalc, extra pallets, reprint).
3. User confirms → the app generates the tag PDF (§5) and dispatches to the printer (§6).
4. The print event is recorded (§4) for audit; the confirmation screen shows tags printed to date.
5. **Top-up:** returning to the same batch, an operator can print N more tags at any time; each print
   is recorded. Tags are identical blanks (§5), so top-ups need no numbering continuity — only the
   count is tracked.

## 4. Data model

`PalletTagPrint` — one row per print event (audit + count tracking):

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `batch_id` | uuid FK | |
| `pallets_calculated` | integer | `ceil(run_quantity / cartons_per_pallet)` at time of print |
| `tags_printed` | integer | what was actually sent (may differ via override / top-up) |
| `printed_by` | text | operator/manager identity |
| `printed_at` | timestamptz | |
| `dispatch_method` | text | `network` \| `browser` (§6) |
| `note` | text | e.g. "top-up, 2 extra" |

Sum of `tags_printed` per batch = total tags printed; compare against `pallets_calculated` for the
audit view ("calculated 22, printed 24").

## 5. Tag content & generation

**Fixed fields (from the stored extract):**

| Tag field | Source |
|-----------|--------|
| Run Number | `run_number` (e.g. 15778) |
| Stock Code | `stock_item` (e.g. F26PNOFSTAI1) |
| Product | `description` (e.g. Foundstone 2026 Pinot Noir AI) |
| Size | `packing_unit` size portion (e.g. 12 x 750ml Bottles) |

**Pre-filled at print time (system clock):**

| Tag field | Value |
|-----------|-------|
| Date | print date |
| Time | print time |

**Left BLANK for handwriting** (varies on export):

| Tag field | Value |
|-----------|-------|
| Pallet Quantity | blank |
| Pallet Number | blank |

**Format:** must match the **exact EzyWine pallet-tag layout** — same structure, field order and
look, since it's the standard. Obtain a **sample of the current EzyWine tag** (`08` D20) and
reproduce it as an HTML/CSS template rendered to PDF via WeasyPrint (same engine as the forms).

**Generation:** produce a PDF containing `tags to print` tags. Each tag is identical except the
(blank) handwritten fields; Date/Time is the print moment. Output is a single PDF sent to the
printer / offered for print.

> **Pending — tag size / A4 layout (`08` D19):** confirm whether each tag is a **full A4 page** or
> **multiple tags laid out per A4 sheet** (e.g. 2-up / 4-up). This sets the template page geometry.
> Build the template behind a small layout config (tags-per-sheet, tag dimensions) so the confirmed
> size is a config change, not a rewrite. Until confirmed, default to **one tag per A4 page**.

## 6. Print dispatch (pluggable — resolves once printer is confirmed)

The app runs on the **on-prem VM**, so server-side printing to a network printer is the target path.
Implement dispatch behind one interface so the confirmed printer decides the implementation:

```
interface TagPrinter:
    print_pdf(pdf_bytes, copies) -> PrintResult
```

Two implementations:

- **`network` (preferred, unattended):** the VM sends the tag PDF/stream directly to a
  network-attached printer (raw TCP/IP port 9100, IPP, or a system print queue on the VM).
  Requires: printer has a LAN IP, and the VM can reach it (`08` D16–D18). This is the clean model —
  confirm and print, no operator babysitting.
- **`browser` (fallback):** the app serves the tag PDF; the operator's device opens the OS print
  dialog and prints to a reachable printer. Manual, per-device, but works with zero printer
  integration if the network path isn't available.

> **Pending — printer (`08` D16–D18):** make/model, network-attached (IP) vs USB-tethered, and VM
> reachability determine which implementation is wired and how. Tag **generation** (§5) is fully
> buildable now; only the **dispatch** implementation waits on these answers. Ship `browser` first
> if the network details lag, then add `network`.

## 7. Lifecycle & permissions

- **Availability:** pallet-tag printing is available for any batch that has a work order with the
  required extracted fields. It is **not** gated to a lifecycle state (you print tags to build
  pallets during the run, well before "complete").
- **Who prints:** the manager prints the initial set at/after batch creation; **operators can print
  top-ups** on the floor ("need one more pallet tag"). Both roles may print tags; only the print
  action is permitted — no other manager-only capability is exposed by this screen.
- Recorded against the batch regardless of who prints (§4).

## 8. Build order

1. **Tag template + generation** (§5) — buildable now; validate the layout against a real EzyWine
   tag sample. Default one-tag-per-A4 until size confirmed.
2. **Calculation + confirmation screen** (§2, §3) — buildable now on the stored extract.
3. **`PalletTagPrint` model + audit view** (§4) — buildable now.
4. **Dispatch** (§6) — `browser` implementation now; `network` once `08` D16–D18 return.
5. Wire availability + RBAC (§7).

## 9. Tests
- `pallets = ceil(run_quantity / cartons_per_pallet)`: 192/64 = 3; 1800/84 = 22; exact-division and
  remainder cases; missing input → calculation withheld with reason.
- Tag content maps correctly from the extract (run number, stock code, product, size); Date/Time
  stamped at print; Pallet Quantity/Number blank.
- Override: "tags to print" can differ from calculated; recorded in `tags_printed`.
- Top-up: second print event recorded; batch total = sum of events.
- Generation produces the correct number of tags for the requested count.
- Dispatch interface: `browser` returns a served PDF; `network` (when wired) targets the printer.

## 10. Acceptance criteria
- For a batch with a valid work order, the confirmation screen shows correct inputs and the correct
  computed pallet count (verified on 15646 → 22, 15778 → 3).
- Generated tags match the EzyWine format (against the supplied sample), with Date/Time filled and
  Pallet Quantity/Number blank.
- Manager can print the initial set; operators can print top-ups; every print is audited.
- Feature works for created jobs with a work order, independent of lifecycle state.
- Print dispatch works via at least the `browser` path; `network` path enabled once the printer is
  confirmed reachable from the VM.

## 11. Open items (tracked in `08` for the .nxt meeting)
- **D16–D18:** printer make/model, network-attached, VM reachability → decides `network` dispatch.
- **D19:** tag physical size / tags-per-A4 → sets template geometry.
- **D20:** sample of the current EzyWine pallet tag → the format to reproduce exactly.
