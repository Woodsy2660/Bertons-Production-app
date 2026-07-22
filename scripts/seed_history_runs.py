#!/usr/bin/env python3
"""Seed 10 older completed runs for manager history search.

Does not wipe existing dashboard seeds. Skips run numbers that already exist.

Usage:
  set DATABASE_URL=postgresql+asyncpg://berton:berton_dev@localhost:5433/berton_bottling
  python scripts/seed_history_runs.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import async_session_maker
from app.services.seed_dashboard_runs import create_history_completed_runs


async def main() -> None:
    settings = get_settings()
    async with async_session_maker() as db:
        batches = await create_history_completed_runs(db, settings.upload_dir)

    if not batches:
        print("No new history runs created (all 15750–15759 already present).")
        return

    print(f"Created {len(batches)} completed history run(s):")
    for b in batches:
        print(f"  - {b.run_number} ({b.id})")
    print()
    print("Manager history: http://127.0.0.1:8001/runs/history")


if __name__ == "__main__":
    asyncio.run(main())
