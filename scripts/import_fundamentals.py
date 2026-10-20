"""Import a dated CSV export: python scripts/import_fundamentals.py filings.csv."""

import argparse
from pathlib import Path

import structlog

from ceremyn.config import get_settings
from ceremyn.fundamentals.provider import JSONFundamentalsStore, read_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    count = JSONFundamentalsStore(Path(get_settings().fundamentals_path)).import_snapshots(
        read_csv(args.csv)
    )
    structlog.get_logger(__name__).info("fundamentals_imported", new_filings=count)


if __name__ == "__main__":
    main()
