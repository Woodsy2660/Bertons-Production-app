# Spec: GS1-128 Barcode Scan Inspector (diagnostic test page)

Build spec for a coding agent. Creates a **standalone diagnostic page** that
captures a barcode/QR scan and shows **exactly** what the scanner returns — the raw
data and a parsed breakdown of every GS1 Application Identifier (AI) — so the
developer can see how each field decodes before wiring barcode auto-fill into the
Final Pallet Count form.

This is a **throwaway diagnostic tool**, not a production feature. It must be
self-contained and easily removable, and must not touch any existing form or data.

---

## 1. Purpose

Before building barcode-driven prefill on the Final Pallet Count page, we need to
know empirically what the scanner actually returns for real pallet labels — field
by field — and match that against the form fields we want to populate. This page
is the instrument for that: scan a label, see every extracted field and how it
comes out.

---

## 2. The key technical reality this page must expose

The human-readable text printed on the label —
`(02)09331288015587(11)260501(10)6121(37)504(90)16211646` — is **NOT** what the
scanner returns as raw data. The raw GS1-128 scan is:

- the AIs and values **concatenated with no parentheses**, and
- **separated by an FNC1 / GS control character (ASCII 29, "group separator")**
  after each **variable-length** field.

So the same label may come off the scanner as something like:
`0209331288015587112605011061 21<GS>37504<GS>9016211646`
(where `<GS>` is a non-printable ASCII 29).

**This is the whole point of the page:** show the raw output faithfully, including
the normally-invisible separators, so we can see the real structure rather than
assume the pretty printed version. **Do not strip, "clean up," or normalise the raw
value before displaying it** — show it verbatim first, then parse.

---

## 3. What the page does

1. **Scan input** — reuse the existing (now working) barcode/QR scanner/camera
   component. Provide a "Scan" action, and also a **manual paste/type field** so a
   raw string can be entered for testing without a camera (useful for debugging).
2. **Show the RAW result, verbatim and fully visible:**
   - The raw string exactly as returned.
   - A **character/hex view** that renders non-printable characters explicitly
     (e.g. show `<GS>` / `<FNC1>` / `\x1d` where ASCII 29 appears, and flag any
     other control chars). This is essential — the separators are invisible
     otherwise.
   - The total length in characters.
   - Which **symbology** the scanner reported, if the scanner library exposes it
     (GS1-128 vs GS1 DataBar vs plain Code-128 vs QR), since this label has
     multiple barcodes.
3. **Parse into GS1 AIs and list every field** in a table:
   | AI | AI name | Raw value | Interpreted value | Notes |
   Where "Interpreted value" applies known formatting (e.g. AI (11)/(17) date
   `YYMMDD` → `2026-05-01`; counts as integers).
4. **Flag anything not recognised or not parsed** — unknown AIs, leftover
   characters, a field that didn't terminate as expected. Don't hide parse
   failures; surface them clearly (they're the interesting cases).
5. **Scan history / log** — keep a running list of scans in the session so multiple
   different labels can be scanned and their outputs compared side by side. (In
   memory is fine; no persistence needed for a diagnostic tool. If persistence is
   trivial it's a bonus but not required.)

---

## 4. GS1 AI reference (seed the parser with at least these)

Parse using standard GS1 AI definitions. At minimum handle the AIs present on the
Berton/Orora pallet labels, with correct fixed vs variable length handling:

| AI | Meaning | Length | Format |
| -- | ------- | ------ | ------ |
| (00) | SSCC (serial shipping container code) | fixed 18 | numeric |
| (01) | GTIN | fixed 14 | numeric |
| (02) | GTIN of contained trade items | fixed 14 | numeric |
| (10) | Batch / lot number | **variable** (FNC1-terminated) | alphanumeric |
| (11) | Production date | fixed 6 | YYMMDD |
| (17) | Expiry date | fixed 6 | YYMMDD |
| (37) | Count of trade items | **variable** (FNC1-terminated) | numeric |
| (90) | Internal / mutually agreed | **variable** (FNC1-terminated) | alphanumeric |

Correct **fixed vs variable-length** handling is the crux of parsing: fixed-length
AIs consume a known number of characters; variable-length AIs run until the next
FNC1/GS separator or end of string. Getting this wrong is the usual failure, so the
page should make it obvious when it happens (e.g. show where each field started and
ended). Use a maintained GS1 AI table so unlisted AIs are still recognised where
possible, and clearly marked "unknown AI" where not.

---

## 5. Access & placement

- **Manager-only** (or developer-only) route, e.g. `/debug/scan-inspector` — not
  linked from the operator UI. Enforce access at the endpoint, not just a hidden
  link.
- Entirely standalone — its own page/template. It must **not** modify, read from,
  or write to any existing form, run, or table.
- Built so it can be **removed cleanly** later (a single route + template + its JS),
  once the real auto-fill feature is built from what we learn here.

---

## 6. Constraints

- Reuse the existing scanner/camera component — do not build a second scanner.
- Display the raw scan **verbatim**; never sanitise before showing it.
- Client-side parsing/display is fine (fastest for a diagnostic), but if the real
  feature will parse server-side, mirroring that is acceptable — either way, the
  raw value must be shown before any parsing.
- No changes to existing forms/data. Purely additive and isolated.
- Follow `UI_UX_STANDARD.md` for basic layout/touch targets (it'll be used on the
  tablet), but polish is not important here — clarity of the raw + parsed output
  is.
- Commit and push when done (VM deploys via `git pull` + `docker compose up -d
  --build`).

---

## 7. Acceptance criteria

- A route (manager/dev-only) exists where a barcode can be scanned **or** a raw
  string pasted in.
- After a scan, the page shows: the **raw string verbatim**, a view that makes
  **FNC1/GS and other non-printable characters visible**, the length, and the
  reported symbology (if available).
- The parsed output lists **every AI** found with its code, standard name, raw
  value, and interpreted value (dates formatted, counts as integers).
- Unknown AIs, leftover characters, and parse failures are **clearly flagged**, not
  hidden.
- Multiple scans can be captured and compared within the session.
- Scanning the sample Orora pallet label yields recognisable values for pallet/
  internal (90), batch (10 = 6121), count (37 = 504), production date (11 =
  2026-05-01), and GTIN (02) — matching the label's printed values.
- Operators cannot reach the page (endpoint-enforced).
- Nothing in the existing app is altered.

## 8. Do not
- Do not sanitise/normalise the raw scan before displaying it.
- Do not wire this into the Final Pallet Count form or any real data (this is
  diagnostic only — the real auto-fill is a later, separate task informed by what
  this reveals).
- Do not build a second scanner component.
- Do not expose the page to operators.
