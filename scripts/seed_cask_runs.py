#!/usr/bin/env python3
"""Seed 4 cask-line runs with randomised partial form data + compile PDFs.

Usage (PowerShell):
  $env:DATABASE_URL = "postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling"
  python scripts/seed_cask_runs.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import async_session_maker
from app.services.seed_cask_runs import CASK_SEED_RUNS, compile_cask_seed_runs, create_cask_seed_runs


async def main() -> None:
    settings = get_settings()
    async with async_session_maker() as db:
        batches = await create_cask_seed_runs(db, settings.upload_dir)
        print(f"Created {len(batches)} cask seed run(s):")
        for b in batches:
            profile = next(
                (c["profile"] for c in CASK_SEED_RUNS if c["run_number"] == b.run_number),
                "?",
            )
            print(f"  - {b.run_number}  id={b.id}  status={b.status.value}  profile={profile}")

        print("\nCompiling PDFs (templates)…")
        outputs = await compile_cask_seed_runs(
            db, settings.upload_dir, settings.compiled_output_dir
        )
        for line in outputs:
            print(f"  PDF: {line}")

    print()
    print("Open runs:")
    print("  http://127.0.0.1:8001/  (or :8000)")
    print("  Search dashboard for CASK-SEED-01 … CASK-SEED-04")


if __name__ == "__main__":
    asyncio.run(main())
