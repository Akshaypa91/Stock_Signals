#!/usr/bin/env python3
"""
migrations/run_migration.py
===========================
Run from backend/ directory:

    python migrations/run_migration.py

Reads DATABASE_URL from environment (or .env file) and applies
001_add_sl_label_timeframe.sql safely.
"""

import asyncio
import os
import pathlib
import sys

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

SQL_FILE = pathlib.Path(__file__).parent / "001_add_sl_label_timeframe.sql"


async def run():
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        print("ERROR: DATABASE_URL not set in environment or .env")
        sys.exit(1)

    # asyncpg uses plain postgresql:// (not +asyncpg)
    url = raw_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres+asyncpg://", "postgresql://")

    sql = SQL_FILE.read_text()

    print(f"Connecting to database...")
    conn = await asyncpg.connect(url)
    try:
        print(f"Running {SQL_FILE.name}...")
        await conn.execute(sql)
        print("Migration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
