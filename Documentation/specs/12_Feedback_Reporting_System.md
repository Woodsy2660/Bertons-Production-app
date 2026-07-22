# Spec: In-App Feedback & Bug Reporting System

Build spec for a coding agent. Adds a simple in-app way for staff to report bugs,
request data-field changes, or suggest improvements, plus a manager-only view to
review them. Built into the existing stack (FastAPI, async SQLAlchemy, Alembic,
Jinja2 + Tailwind, Postgres) — no new services.

## Design principle
**Minimal effort to submit, maximum context captured automatically.** The person
reporting types as little as possible (a type + a description); the *system*
records everything useful for diagnosis (page, role, device, run, timestamp) in
the background. This keeps it frictionless for gloved floor operators while giving
the reviewer enough to act on each report without follow-up.

Reviewer = the developer (via the manager login). Read-only review this version.

---

## 1. Data model — new table `feedback_reports`

Alembic migration for a new table:

| Column | Type | Notes |
| ------ | ---- | ----- |
| `id` | UUID (PK) | |
| `report_type` | enum | `bug` \| `data_change` \| `suggestion` |
| `description` | text | the single free-text field the user types |
| `submitted_role` | text/enum | **auto** — the logged-in role (manager/operator), from the session server-side |
| `source_path` | text | **auto** — the page/route the report was submitted from (e.g. `/batches/{id}` or the form path) |
| `page_context` | text/JSON, nullable | **auto** — human-readable context, e.g. which form/screen |
| `run_id` / `batch_id` | UUID, nullable | **auto** — the run/batch in context at submission, if any |
| `user_agent` | text | **auto** — browser/device string (identifies iPad-Safari vs Android-Chrome vs desktop — critical for diagnosis) |
| `submitted_at` | timestamptz | **auto** — server time, rendered in **Australia/Sydney** |
| `status` | text/enum, default `new` | Include the column now (default `new`), even though the UI is read-only this version, so status tracking can be added later with **no migration**. Not surfaced in the UI yet. |

All `auto` fields are captured **server-side**, never trusted from client input
(especially `submitted_role` — take it from the session, not a form field).

---

## 2. Submit flow (all users — operator & manager)

**Entry point:** a "Report an issue" / feedback action available on **every page**
— place it in the **shared base template** (e.g. a small button in the header or a
fixed corner button) so it's reachable from any page/form, per the requirement to
report "across pages/forms."

**The form (keep it minimal — this is the whole operator-facing UI):**
1. **Type** — a tappable single-select: Bug / Data field change / Suggestion.
   Three large touch-friendly options.
2. **Description** — one text area ("Describe the issue or suggestion").
3. **Submit** button.

That's it — no other required fields for the person submitting. Everything else is
auto-captured.

**On submit (server-side):**
- Capture `submitted_role` from the session, `source_path` from the referring
  page/route the modal was opened on, `run_id`/`batch_id` if the current context
  has one, `user_agent` from the request headers, `submitted_at` = now.
- Store the row.
- Show a brief, clear confirmation ("Thanks — your report has been submitted.")
  and return the user to where they were. Do not lose their place in a form.

**UX:** follow `UI_UX_STANDARD.md` — large touch targets (≥48px, 56px primary),
legible text, works on the tablet. A modal/overlay is fine as long as it doesn't
disrupt an in-progress form (don't discard unsaved form data when opening it).

---

## 3. Review flow (MANAGER ONLY — read-only)

A manager-only page listing all reports for the reviewer to scan.

- **Route:** e.g. `/feedback` or `/admin/feedback`.
- **Access: manager role only.** Enforce at the **route/endpoint level**, not just
  by hiding the link — an operator hitting the URL directly must be blocked (403 /
  redirect), consistent with the app's existing RBAC. Operators must not see it.
- **List:** all reports, **newest first**. Each entry shows:
  - Report type (as a clear visual badge — colour + label + icon, greyscale-safe).
  - The description.
  - The auto-captured context: source page, role, device/browser (a readable
    summary of `user_agent` — e.g. "iPad Safari" / "Android Chrome" / "Desktop"),
    run/batch if present, and the timestamp (Australia/Sydney).
- Read-only — no editing/resolving this version. A simple, scannable list is the
  goal.
- **Optional (nice-to-have, not required):** a light filter by report type to make
  scanning easier. Default view is the plain reverse-chronological list.

---

## 4. Security / correctness (bake these in)

- **Manager-only review**, enforced at the endpoint (API-level), not just UI.
- **`submitted_role` and all auto fields come from the server/session**, never from
  client-supplied form values.
- **Description is user free-text** → escape/sanitise it properly wherever it's
  displayed (Jinja autoescaping on by default; confirm it's not disabled on the
  review page). Do not render it as raw HTML.
- Timestamps in **Australia/Sydney**, consistent with the rest of the app.
- Basic guard against empty submissions (require a non-empty description and a
  selected type) and against accidental double-submit.

---

## 5. Out of scope (do NOT build this version)

- No status workflow / resolving / assigning in the UI (the `status` column exists
  for later, but stays unused/`new` for now).
- No notifications or emails on new reports.
- No file/screenshot upload (keep it minimal; can be added later).
- No editing or deleting of reports by users.
- No operator access to the review page.

---

## 6. Acceptance criteria

- A new `feedback_reports` table is created via Alembic migration.
- From **any page**, a user can open the report form, pick a type, type a
  description, submit, and get a confirmation without losing their place.
- Each stored report has the auto-captured context populated: role, source page,
  device/user-agent, run/batch (if in context), and Sydney-time timestamp.
- The **manager-only** review page lists all reports newest-first with type,
  description, and context; an **operator cannot access it** (blocked at the
  endpoint, verified by hitting the URL directly as an operator).
- Description free-text is safely escaped on display.
- Works on the tablet (touch targets, layout) per `UI_UX_STANDARD.md`.
- No regression to existing pages (the shared-template entry point doesn't break
  other screens).

## 7. Do not
- Do not trust client-supplied values for role or any auto-captured field.
- Do not expose the review page to operators (enforce at the endpoint).
- Do not render report descriptions as raw HTML.
- Do not add status/notifications/uploads this version (keep scope minimal).
- Commit and push when done (VM deploys via `git pull` + `docker compose up -d
  --build`).
```
