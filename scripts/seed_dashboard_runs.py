#!/usr/bin/env python3
"""Seed dashboard mock runs. Usage: python scripts/seed_dashboard_runs.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database import async_session_maker
from app.models import BatchStatus
from app.services.seed_dashboard_runs import create_dashboard_mock_runs


async def main() -> None:
    settings = get_settings()
    async with async_session_maker() as db:
        batches = await create_dashboard_mock_runs(db, settings.upload_dir)

    complete = [b for b in batches if b.status == BatchStatus.COMPLETE]
    review = [b for b in batches if b.status == BatchStatus.AWAITING_REVIEW]
    active = [b for b in batches if b.status == BatchStatus.IN_PROGRESS]

    print("Dashboard mock runs created:")
    print(f"  Completed:        {len(complete)}")
    for b in complete:
        print(f"    - {b.run_number} ({b.id})")
    print(f"  Awaiting review:  {len(review)}")
    for b in review:
        print(f"    - {b.run_number} ({b.id})")
    print(f"  In progress:      {len(active)}")
    for b in active:
        print(f"    - {b.run_number} ({b.id})")
    print()
    print("Open dashboard: http://127.0.0.1:8001/  (log in as manager)")


if __name__ == "__main__":
    asyncio.run(main())