#!/usr/bin/env python3
"""Seed a fully-populated compile test run. Usage: python scripts/seed_test_run.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import async_session_maker
from app.services.seed_test_run import TEST_RUN_NUMBER, create_compile_test_run


async def main() -> None:
    settings = get_settings()
    async with async_session_maker() as db:
        batch = await create_compile_test_run(db, settings.upload_dir)
        print(f"Test run created successfully.")
        print(f"  Run number: {TEST_RUN_NUMBER}")
        print(f"  Batch ID:   {batch.id}")
        print(f"  Open:       http://localhost:8000/batches/{batch.id}")
        print(f"  Compile:    Manager Tools > Compile PDF on the batch page")


if __name__ == "__main__":
    asyncio.run(main())