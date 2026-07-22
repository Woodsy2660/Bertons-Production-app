# Berton Bottling App — Documentation Suite

**Project:** Digitising bottling-run work-order forms at Berton Vineyards into a local web intake portal, with PDF compilation matching existing compliance documentation.

**Status:** Application is **built and production-deployable**. These documents are the product/architecture specs plus as-built and ops notes. Day-to-day setup starts at the repo root [`README.md`](../README.md).

**Related non-doc folders**

- [`assets/brand/`](../assets/brand/) — official logo source files (app runtime uses `app/static/img/`)
- [`samples/`](../samples/) — sample work-order PDFs for manual testing
- Runtime PDF data lives in `uploads/`, `compiled_output/`, `pallet_tags/` (gitignored; empty in a clean clone)

---

## How to read this suite

| # | Document | Covers |
|---|----------|--------|
| 00 | [`00_Project_Overview.md`](00_Project_Overview.md) | Scope, goals, actors, glossary |
| 01 | [`01_System_Architecture.md`](01_System_Architecture.md) | Hosting model, stack, components |
| 02 | [`02_Data_Model.md`](02_Data_Model.md) | Postgres schema, readings abstraction |
| 03 | [`03_Form_Specifications.md`](03_Form_Specifications.md) | Nine station forms |
| 04 | [`04_PDF_Compilation_Spec.md`](04_PDF_Compilation_Spec.md) | 16-slot compile template |
| 05 | [`05_Workflow_and_Lifecycle.md`](05_Workflow_and_Lifecycle.md) | Batch states, submit/edit/lock |
| 06 | [`06_Build_Roadmap.md`](06_Build_Roadmap.md) | Phased delivery history |
| 07 | [`07_Backend_Implementation.md`](07_Backend_Implementation.md) | As-built backend |
| 08 | [`08_Production_Deployment_Plan.md`](08_Production_Deployment_Plan.md) | Production VM / Docker plan |
| — | [`DEPLOYMENT_ENVIRONMENT.md`](DEPLOYMENT_ENVIRONMENT.md) | Winery Azure host / network |

### Specs (addenda)

| Document | Topic |
|----------|--------|
| [`specs/09_PDF_Extraction_pdfplumber_Spec.md`](specs/09_PDF_Extraction_pdfplumber_Spec.md) | Work-order PDF extraction |
| [`specs/10_Extraction_Driven_Form_Prefill.md`](specs/10_Extraction_Driven_Form_Prefill.md) | Form prefill from extraction |
| [`specs/11_Pallet_Tag_Printing.md`](specs/11_Pallet_Tag_Printing.md) | Pallet tag printing |

### QA

| Document | Topic |
|----------|--------|
| [`qa/TEST_PLAN.md`](qa/TEST_PLAN.md) | Full test plan |
| [`qa/REMAINING_TESTS.md`](qa/REMAINING_TESTS.md) | Follow-up tests |
| [`qa/QA_EXECUTION_REPORT.md`](qa/QA_EXECUTION_REPORT.md) | Execution report |
| [`qa/REMAINING_TESTS_EXECUTION_REPORT.md`](qa/REMAINING_TESTS_EXECUTION_REPORT.md) | Remaining-tests report |

---

## Compile & PDF logo (as-built summary)

- Forms are rendered **one HTML→PDF each**, then merged with pypdf.
- **Uploads** (EzyWine, work order, label refs) are merged **without** branding.
- **Form title page** only: Berton logo ~10mm, top-right, title-aligned (`app/services/compilation.py`).
- Changing logo size/placement requires a **recompile** of each run to refresh stored PDFs.
