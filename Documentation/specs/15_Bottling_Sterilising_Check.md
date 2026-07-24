# Spec: Bottling Weekly Sterilising Check (FOR PK 026)

Build spec for a coding agent. Adds **FOR PK 026 — Weekly Sterilising Check** for
the **bottling** line, as a standalone form that is completed independently of a
run and later attached to one.

**This is the bottling counterpart to FOR CA 005 (cask).** It uses the **same
standalone-log-and-attach mechanism** specified in
`SPEC_sterilising_prestart_check.md`.

> **Build order note:** if the cask sterilising spec (FOR CA 005) has already been
> implemented, **reuse that mechanism** — the standalone entity, the log view, the
> attach/detach flow, the multi-run attachment model, and the compilation handling.
> Do **not** build a second parallel system. This spec covers only what differs.
> If FOR CA 005 has not been built yet, build the shared mechanism once so both
> forms use it.

---

## 1. What's shared with FOR CA 005 (do not rebuild)

All of the following behaves exactly as specified in
`SPEC_sterilising_prestart_check.md`:

- **Standalone lifecycle** — completable with **no run in existence** (sterilising
  often happens before the job is posted), then attached to a run afterwards.
- **Created by either operators or managers** — not manager-only.
- **Log view** — completed records listed newest-first, showing date, time,
  operator, and attachment status; easy to find recent unattached records.
- **Attach / detach from a run** — attach from the run's forms page via a picker;
  detach possible while the run is unlocked; after compile/lock the normal
  lock/manager-reopen rules apply.
- **One record can be attached to multiple runs** (a weekly check covers several
  runs in that week — do not force one-record-per-run).
- **Server-side** `created_by_role` and timestamps (Australia/Sydney on display).
- **PDF output** in the existing style — form code and title in the header, logo on
  **first page only**, submitted-by/at footer.
- **Compiled output** — attached record(s) included in the run's compiled PDF; a
  run compiled with no record attached must produce a clear, explicit state, never
  a silently blank page that could read as "checks not performed."

---

## 2. ⚠ Key difference — line type separation

There are now **two sterilising forms**: FOR CA 005 (cask) and FOR PK 026
(bottling). They are **not interchangeable** — different fields, different lines.

Requirements:
- Each sterilising record must record **which line type it belongs to**
  (`bottling` | `cask`) — e.g. a `line_type` column on the sterilising table, or
  separate tables if the field differences justify it (agent's call, but the record
  must be unambiguously attributable to one line).
- **The attach picker must filter by the run's line type.** A **bottling run** must
  only offer **bottling (PK 026)** sterilising records; a **cask run** only **cask
  (CA 005)** records. Attaching a cask sterilising record to a bottling run (or
  vice versa) must not be possible — it would put the wrong compliance evidence on
  a run.
- The log view should make the line type visible, and ideally filterable.

This ties into the `line_type` on runs introduced in `SPEC_cask_line_run_type.md`.

---

## 3. Form fields (FOR PK 026 — note the differences from CA 005)

**Header**
- Sterilising Operator's name
- Date
- Time
- **Which system is being sterilised? — System 1 / System 2** ← **NEW, not present
  on the cask form.** A required single-select.

**Filter integrity**
- Have the **0.65 µm and 0.45 µm** filters been integrity tested as per SOP? —
  **Yes / No**

**Wine filter readings** — each row with **Pressure drop (mbar)** and **Pass? (Y/N)**:
- 0.45
- 0.65

**Water filter readings** — each row with **Pressure drop (mbar)** and **Pass? (Y/N)**:
- 0.45  ← **note: the bottling form has TWO water filter rows (0.45 and 0.22);
  the cask form has only 0.22. Do not copy the cask structure here.**
- 0.22

**Weekly Sterilising Checks**
- Temperature and duration of **lenticular housing, bypass line and return line**
  sterilisation — `___ °C for ___ mins`
- Temperature and duration of **0.65 µm, 0.45 µm and filler** sterilisation —
  `___ °C for ___ mins`

**Not present on this form** (unlike FOR CA 005 — do not add them):
- No "Daily Pre-Start Checks" section
- No "Is the Filler and surroundings clean…" / "Is the Carton Erector…" questions
- No separate Operators QC Sign Off row (sign-off is via the operator name; confirm
  against the source document if in doubt)

Keep the section headings as they appear on the paper form
("Weekly Pre-Start Checks" header, "Weekly Sterilising Checks" section) in both the
screen layout and the PDF.

---

## 4. Constraints

- Reuse the shared standalone/log/attach mechanism — **one implementation, two form
  types**, not two parallel systems.
- Do not modify existing bottling or cask run forms; this is additive.
- Follow `UI_UX_STANDARD.md` (touch targets, spacing, badges, save feedback).
- Alembic migration for any new columns/tables; existing sterilising records (if CA
  005 already shipped) must migrate cleanly with the correct `line_type`.
- Commit and push when done (VM deploys via `git pull` + `docker compose up -d
  --build`).

---

## 5. Acceptance criteria

- A bottling sterilising check (PK 026) can be created by **either role**, with
  **no run selected**.
- It captures **System 1 / System 2**, both wine filter rows (0.45, 0.65), **both
  water filter rows (0.45 and 0.22)**, and both temperature/duration lines.
- Records appear in the log with line type visible, newest first.
- A **bottling run's** attach picker offers **only bottling** sterilising records;
  a **cask run's** offers **only cask** records. Cross-line attachment is not
  possible.
- One record can be attached to multiple runs without re-entry.
- Detach works while the run is unlocked; lock/reopen behaves consistently.
- Renders to PDF in the existing style (logo first page only, Sydney timestamps)
  and is included in the run's compiled output when attached.
- A run compiled with no sterilising record attached produces a clear, explicit
  result.
- No regression to FOR CA 005, existing bottling forms, or cask forms.

## 6. Do not
- Do not build a second standalone/log/attach system — reuse the CA 005 mechanism.
- Do not allow a cask sterilising record to attach to a bottling run, or vice versa.
- Do not copy the cask form's field set — this form has System 1/2 and two water
  filter rows, and has no Daily Pre-Start Checks section.
- Do not require a run to create the record, or restrict creation to managers.
- Do not silently blank the section in a compiled PDF when nothing is attached.
