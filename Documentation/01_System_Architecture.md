# 01 — System Architecture

## 1. Topology

A single **application host** on the Berton LAN serves a browser-based app to operator tablets
and the manager's machine. All state lives in a **local Postgres** instance. Nothing in the
prototype reaches EzyWine or the file-server shares.

```
   ┌─────────────────────────────────────────────────────────┐
   │                    Berton LAN (Wi-Fi)                     │
   │                                                           │
   │   Operator tablets         Manager PC / tablet            │
   │   (browser, thin client)   (browser, thin client)        │
   │        │   │   │                  │                       │
   │        └───┴───┴────────┬─────────┘                       │
   │                         │  HTTP(S) over LAN               │
   │              ┌──────────▼───────────┐                     │
   │              │   Application host    │                     │
   │              │  ┌────────────────┐   │                     │
   │              │  │ Web/API server │   │                     │
   │              │  ├────────────────┤   │                     │
   │              │  │ PDF render +   │   │                     │
   │              │  │ merge engine   │   │                     │
   │              │  ├────────────────┤   │                     │
   │              │  │ EzyWine stub   │ ◄─── swappable later     │
   │              │  └───────┬────────┘   │                     │
   │              │          │            │                     │
   │              │   ┌──────▼───────┐    │                     │
   │              │   │  Postgres    │    │                     │
   │              │   │  (local)     │    │                     │
   │              │   └──────────────┘    │                     │
   │              │   file store (uploads │                     │
   │              │   + generated PDFs)   │                     │
   │              └───────────────────────┘                     │
   └─────────────────────────────────────────────────────────┘
```

The host can be the existing work server or — preferred — a **separate machine/VM on the same
LAN**, so prototype code never sits on the production ERP box. This is a prototype-isolation
choice; nothing in the app depends on co-location.

## 2. Components

| Component | Responsibility |
|-----------|----------------|
| **Web/API server** | Serves the UI; exposes the REST API for batches, forms, readings, uploads, compile. Holds the form-template definitions (`03`) and the compile template (`04`). |
| **Postgres** | Single source of truth for in-flight runs: batches, headers, form instances, readings, upload metadata, compile records. Schema in `02`. |
| **File store** | On-disk location for uploaded PDFs and generated output PDFs. Referenced from Postgres by path; **not** the company network folders. |
| **PDF render + merge engine** | Renders each app form to a styled PDF page (HTML/CSS → PDF), then merges rendered pages with uploaded PDFs in slot order. Detail in `04`. |
| **EzyWine stub** | A module with the *shape* of the future integration (resolve run → header data, resolve barcode → run) but a no-op / manual implementation now. See §6. |

## 3. Recommended stack

Stack-neutral where possible, but a concrete, low-friction recommendation:

- **Backend:** Python + **FastAPI** (async REST), **SQLAlchemy** + **Alembic** (schema
  migrations). Python is already in use at Berton (existing extraction scripts) and pairs well
  with the PDF tooling below. *(Streamlit is explicitly unsuitable — single-user, rerun model.)*
- **Datastore:** **PostgreSQL** (local), JSONB used for form/reading payloads (`02`).
- **Frontend:** a responsive browser app (tablet-first). Either a light SPA (React/Svelte) or
  server-rendered templates with progressive enhancement. Forms are data-dense, so prioritise
  large touch targets and fast keyboard entry over visual flourish.
- **PDF form rendering:** **WeasyPrint** (HTML + CSS, including `@page` landscape/portrait and
  precise table layout) — the best fit for reproducing the Berton form layouts from templates.
- **PDF merge:** **pypdf** or **pikepdf** to concatenate rendered pages with uploaded PDFs in
  slot order and write the final named file.
- **Barcode/QR (later):** a browser scanner library (e.g. ZXing/`html5-qrcode`). Stubbed now
  (§6). Note the HTTPS dependency in §5.

> The render-from-HTML/CSS approach is deliberate: matching the existing paper forms is a
> layout problem, and HTML/CSS templates are the most maintainable way to hit the fidelity bar
> form-by-form. See `04` §5.

## 4. Request/data flow (compile example)

1. Manager hits **Compile** for batch `15646`.
2. API checks batch readiness (`05` §2) and gathers: all submitted form instances + their
   readings, and all uploaded documents with their slot assignments.
3. For each app-generated slot, the render engine builds an HTML document from the form
   template + data and renders it to a PDF (correct orientation).
4. The merge engine walks the **16-slot template** (`04`), inserting rendered pages and
   uploaded PDFs (expanding the flexible label-references group) in order.
5. The final PDF is written to the file store, named to convention; a `compilation` record is
   saved; the batch is **locked** (`05` §3).
6. Manager downloads the PDF.

## 5. HTTPS / secure context

The QR scanner needs a **secure context** (HTTPS) because browser camera APIs are blocked on
plain `http://` to an IP. The scanner is stubbed in the prototype, so HTTPS is **not required
to start** — but do **not** architect the host in a way that makes adding TLS painful later
(keep the server behind a reverse proxy, or ready to sit behind one, so an internal certificate
can be introduced without re-plumbing). See `06` §4.

## 6. The EzyWine integration seam (stub now, swap later)

Define a single interface the rest of the app depends on, with a manual/no-op implementation
for the prototype. Later, only this module changes.

```
interface RunDataProvider:
    resolve_run_header(run_number) -> BatchHeader | None
        # Prototype: returns None → manager enters header manually.
        # Later: reads run header from EzyWine (CSV/Vin6 export or API).

    resolve_barcode(scanned_code) -> run_number | None
        # Prototype: not called (scanner stubbed), or echoes a typed code.
        # Later: maps a scanned pallet barcode/QR to a run number.
```

Design rules that keep the seam clean:

- The app **never** assumes header data exists — manual entry is always a valid path, so the
  later auto-fill is purely additive.
- The barcode field on batch creation is a normal input now; the scanner is a swappable
  front-end module that, when enabled, calls `resolve_barcode` and pre-fills the same field.
- No EzyWine schema, table names, or file paths leak outside this module.

See `06` for the migration trigger (when real-time/bidirectional integration becomes a hard
requirement, or when the EzyWine PRO API is adopted).

## 7. Non-goals for the prototype

- No auto-filing to company folders — manager downloads and files.
- No authentication beyond a per-entry identity field (`05` §4).
- No real-time push — refresh-based status board.
- No calculated-total enforcement — totals start as operator-entered fields (`03` notes).
