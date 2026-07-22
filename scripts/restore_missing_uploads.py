"""Restore missing upload PDF files referenced by the database.

When `uploads/` is wiped (e.g. repo cleanup) but `uploaded_documents` rows remain,
work-order / label / listing viewers 404. This recreates placeholder PDFs (or
copies sample work orders) at each stored_path that is missing on disk.

Usage (from repo root):
  set DATABASE_URL=postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling
  python scripts/restore_missing_uploads.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select

# Ensure repo root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import async_session_maker  # noqa: E402
from app.models import DocumentSlot, UploadedDocument  # noqa: E402

SAMPLE_WORK_ORDER = ROOT / "samples" / "work_orders" / "pbo04_run_15778.pdf"
TEST_FIXTURE = ROOT / "tests" / "fixtures" / "work_orders" / "pbo04_run_15778.pdf"


def _minimal_pdf(dest: Path, title: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from weasyprint import HTML

        HTML(
            string=f"""<!DOCTYPE html>
<html><body style="font-family: Arial; margin: 2cm;">
  <h1>{title}</h1>
  <p>Placeholder document restored after missing file on disk.</p>
  <p>Re-upload the real PDF from the batch page if required.</p>
</body></html>"""
        ).write_pdf(str(dest))
        return
    except Exception:
        pass
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with open(dest, "wb") as handle:
        writer.write(handle)


def _restore_one(doc: UploadedDocument) -> str:
    path = Path(doc.stored_path)
    if path.is_file() and path.stat().st_size > 0:
        return "ok"

    slot = doc.slot.value if hasattr(doc.slot, "value") else str(doc.slot)
    title = doc.original_filename or f"{slot} document"

    # Prefer real sample for work orders when available
    if slot == DocumentSlot.WORK_ORDER.value or slot == "work_order":
        for candidate in (SAMPLE_WORK_ORDER, TEST_FIXTURE):
            if candidate.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(candidate.read_bytes())
                return f"copied work-order sample -> {path}"

    _minimal_pdf(path, title)
    return f"placeholder -> {path}"


async def main() -> None:
    restored = 0
    skipped = 0
    async with async_session_maker() as db:
        docs = (await db.execute(select(UploadedDocument))).scalars().all()
        print(f"Found {len(docs)} uploaded_documents row(s)")
        for doc in docs:
            msg = _restore_one(doc)
            if msg == "ok":
                skipped += 1
            else:
                restored += 1
                print(f"  [{doc.slot}] {doc.original_filename}: {msg}")
    print(f"Done. restored={restored} already_present={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
