"""Vercel build hook: run database migrations when DATABASE_URL is available."""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set; skipping Alembic migrations.")
        return

    print("Running Alembic migrations...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )
    print("Migrations complete.")


if __name__ == "__main__":
    main()