#!/usr/bin/env python3
"""Populate Run #15785 with example form data. Usage: python scripts/populate_run_15785.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import async_session_maker
from app.services.populate_batch import populate_run_15785, RUN_15785_BATCH_ID


async def main() -> None:
    settings = get_settings()
    async with async_session_maker() as db:
        batch = await populate_run_15785(db, settings.upload_dir)
        print("Run #15785 populated successfully.")
        print(f"  Batch ID: {RUN_15785_BATCH_ID}")
        print(f"  Forms:    {len(batch.form_instances)} submitted")
        print(f"  Open:     http://localhost:8000/batches/{RUN_15785_BATCH_ID}")
        print("  Compile:  Manager Tools > Compile PDF on the batch page")


if __name__ == "__main__":
    asyncio.run(main())