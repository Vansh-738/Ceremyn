"""Backfill NSE F&O EOD option chains into Postgres.

Usage:
    .venv/bin/python scripts/ingest_bhavcopy.py --start 2025-01-01 --end 2025-07-11

Requires Postgres running (docker compose up -d postgres) and migrations
applied (.venv/bin/alembic upgrade head).
"""

import argparse
import asyncio
from datetime import date

from alphaquant.config import get_settings
from alphaquant.core.container import Container
from alphaquant.core.logging import configure_logging


async def main(start: date, end: date) -> None:
    settings = get_settings()
    configure_logging(settings)
    container = Container(settings)
    try:
        results = await container.bhavcopy_ingest.ingest_range(start, end)
        total = sum(results.values())
        print(f"Ingested {total} rows across {len(results)} trading day(s).")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))
