"""Vercel build hook: run database migrations when DATABASE_URL is available."""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    from app.config import resolve_database_url_from_env

    if not resolve_database_url_from_env():
        print(
            "No database URL found (DATABASE_URL / POSTGRES_URL); "
            "skipping Alembic migrations."
        )
        return

    print("Running Alembic migrations...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )
    print("Migrations complete.")


if __name__ == "__main__":
    main()