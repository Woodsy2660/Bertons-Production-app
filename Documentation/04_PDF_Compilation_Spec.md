# 04 — PDF Compilation Specification

How the final document is assembled. Derived directly from the authoritative output file
`15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf`. Where any other note disagrees with
that file, **the file wins**.

## 1. The 16-slot template

The final document is a fixed ordered sequence of **slots**. Each slot's content comes from one
of three sources:

- `upload` — a single manager-uploaded PDF for a named slot.
- `upload_group` — a **flexible-length** group of manager uploads (0..N files), appended in
  `sequence` order.
- `app_form` — an app-generated form (`03`), rendered to PDF at compile time.

| Slot | Pages (ref) | Source | Ref / `form_type` | Orientation |
|------|-------------|--------|-------------------|-------------|
| 1 | 1–2 | `upload` | `ezywine_listing` | portrait |
| 2 | 3 | `app_form` | `daily_production` | portrait |
| 3 | 4 | `app_form` | `filler_line_check` | landscape |
| 4 | 5 | `app_form` | `bottle_sealing` | landscape |
| 5 | 6 | `upload` | `work_order` | portrait |
| 6 | 7 | `app_form` | `label_usage` | portrait |
| 7 | 8 | `app_form` | `finished_product_line_check` | landscape |
| 8 | 9 | `app_form` | `pick_list` | portrait |
| 9 | 10–13 | `upload_group` | `label_reference` (**0..N**) | as-uploaded |
| 10 | 14 | `app_form` | `carton_qc` | landscape |
| 11 | 15 | `app_form` | `final_pallet_count` | portrait |
| 12 | 16 | `app_form` | `finished_product_pallet` | portrait |

> "Pages (ref)" are the page numbers in the reference PDF. Slot 1 is two pages because the
> EzyWine listing is two pages; slot 9 is variable (see §3). Everything else is one page in the
> reference but app forms may overflow to multiple pages if a run has many readings (§5).

**The order is interleaved, not grouped.** Manager uploads (slots 1, 5, 9) sit *between*
app-generated forms. The compile engine must walk this template positionally — it is **not**
"all forms then all attachments." Build it as an ordered list of slot descriptors, not two
concatenated lists.

## 2. Compile algorithm

```
def compile(batch):
    assert batch.is_ready_or_overridden()          # see 05 §2
    pages = []
    for slot in COMPILE_TEMPLATE:                  # the 16-slot ordered list
        if slot.source == "app_form":
            html = render_template(slot.form_type, batch)   # 03 + data
            pdf  = html_to_pdf(html, orientation=slot.orientation)
            pages.append(pdf)
        elif slot.source == "upload":
            doc = batch.upload_for(slot.ref)        # 0..1
            if doc: pages.append(load_pdf(doc))
            # absent optional upload → skip slot (see §3)
        elif slot.source == "upload_group":
            for doc in batch.uploads_for(slot.ref, ordered=True):  # 0..N
                pages.append(load_pdf(doc))
    final = merge(pages)
    path  = write(final, name=output_filename(batch))   # §4
    record_compilation(batch, path, slot_manifest)      # 02 compilation
    lock(batch)                                         # 05 §3
    return path
```

## 3. The flexible label-references slot (slot 9)

Per the confirmed requirement: the manager uploads label references for the distributor — it
may be **just one** of the proof/print pages, **several, or all**. This slot is therefore an
`upload_group` of **0..N** files:

- Accepts any number of `label_reference` uploads (including zero).
- Appends them in `sequence` order (manager-orderable in the UI).
- Each uploaded file may itself be multi-page; all pages flow in.
- If zero label references are uploaded, the slot contributes nothing and compilation
  continues (no error).

The other two upload slots (`ezywine_listing`, `work_order`) are expected to be 0..1. Treat a
**missing** upload as a soft condition: skip and continue, but surface it in the pre-compile
readiness check (`05` §2) so the manager isn't surprised by an absent EzyWine listing.

## 4. Output file naming

Match the company convention exactly, as seen on the reference file:

```
{run_number} {stock_item} {product}.pdf
e.g.  15646 F22CSARESAI6 Reserve 2022 Cab Sauvignon AI.pdf
```

Build from `batch.run_number`, `batch_header.stock_item`, `batch_header.product`. Sanitise for
filesystem-illegal characters only; otherwise preserve spacing/casing to match existing files.

## 5. Form rendering fidelity

App forms are rendered from **HTML/CSS templates** (one per `form_type`) via the render engine
(`01` §3, WeasyPrint recommended). Targets:

- **Layout match:** reproduce the existing Berton form structure — the document-control header
  box (title, **document number** e.g. `FOR PK 013`, page number, issue number/date,
  authorised-by/bottling-manager), the section tables, and the field grid. The aim is a clean,
  legible equivalent that QA and an auditor accept as the same form — not necessarily
  pixel-identical.
- **Branding:** the client will provide an **updated Berton logo and document-control
  information** to place in each form's header. Template the header as a shared partial so the
  logo/issue metadata is defined once and reused across all nine forms.
- **Orientation:** set per slot via CSS `@page { size: A4 landscape | portrait }`. Four forms
  are landscape (filler check, bottle sealing, finished-product line check, carton QC).
- **Overflow:** a long run can produce more readings than one page holds (e.g. many filler
  columns or pallet rows). Templates must **paginate** — repeat the header row/column labels on
  each continuation page. A form is therefore **one-or-more** pages; the reference file shows
  the single-page case.
- **Multi-value cells:** render N stacked sub-values within the single cell (`03`).
- **Matrix forms:** fixed field items as the left-hand rows; one column per `reading` in
  `sequence` order; continuation pages add more columns.

## 6. Determinism & audit

- Persist the **resolved slot manifest** used for each compile in `compilation.slot_manifest`
  (`02`) — which upload filled each upload slot, how many label references, form instance
  versions — so a filed PDF can be explained later.
- Compilation is **idempotent** given the same data; recompiling after edits supersedes the
  prior `compilation` (mark old `is_current=false`) (`05` §3).

## 7. Edge cases to handle

| Case | Behaviour |
|------|-----------|
| Missing EzyWine listing | Skip slot 1; flag in readiness check; allow override-compile. |
| Zero label references | Skip slot 9 silently (valid per requirement). |
| Form not submitted | Blocked by readiness unless manager overrides; if overridden, render whatever data exists (clearly partial). |
| Upload is not a valid PDF | Reject at upload time; never at compile time. |
| Run with > 1 page of readings | Paginate that form; continuation pages repeat labels. |
| Wrong-run upload (e.g. EzyWine listing for another run) | Out of scope to auto-detect in prototype; note as a known limitation (`06` §5). |
