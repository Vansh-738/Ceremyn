"""CSV imports and an atomic JSON archive; timestamps are supplied by the source."""

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ceremyn.domain.fundamentals import FundamentalSnapshot


class FundamentalsProvider(Protocol):
    def history(self, symbol: str) -> tuple[FundamentalSnapshot, ...]: ...


def read_csv(path: Path) -> tuple[FundamentalSnapshot, ...]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return tuple(
            FundamentalSnapshot.model_validate({k: v for k, v in row.items() if v != ""})
            for row in csv.DictReader(stream)
        )


class JSONFundamentalsStore:
    """Small single-writer archive. Conflicting values require a new publication time."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _all(self) -> tuple[FundamentalSnapshot, ...]:
        if not self.path.exists():
            return ()
        return tuple(
            FundamentalSnapshot.model_validate(row) for row in json.loads(self.path.read_text())
        )

    def history(self, symbol: str) -> tuple[FundamentalSnapshot, ...]:
        return tuple(row for row in self._all() if row.symbol == symbol.upper())

    def import_snapshots(self, rows: Sequence[FundamentalSnapshot]) -> int:
        combined = {self._key(row): row for row in self._all()}
        before = len(combined)
        for row in rows:
            key = self._key(row)
            if key in combined and combined[key] != row:
                raise ValueError(
                    "conflicting filing: give a restatement its actual publication time"
                )
            combined[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([r.model_dump(mode="json") for r in combined.values()], indent=2)
        )
        temporary.replace(self.path)
        return len(combined) - before

    @staticmethod
    def _key(row: FundamentalSnapshot) -> tuple[str, str, str, str]:
        return row.symbol, row.period_type, row.period_end.isoformat(), row.published_at.isoformat()


class CSVFundamentalsProvider:
    def __init__(self, path: Path) -> None:
        self._rows = read_csv(path)

    def history(self, symbol: str) -> tuple[FundamentalSnapshot, ...]:
        return tuple(row for row in self._rows if row.symbol == symbol.upper())
