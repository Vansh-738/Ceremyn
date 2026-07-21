"""Append-only OMS ledger."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware


class LedgerEntryKind(StrEnum):
    COMMAND = "command"
    EVENT = "event"
    FILL = "fill"
    RECONCILIATION = "reconciliation"


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LedgerEntryKind
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    _aware = field_validator("timestamp")(_require_aware)


class OMSLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def commands(self) -> tuple[LedgerEntry, ...]:
        return tuple(entry for entry in self._entries if entry.kind is LedgerEntryKind.COMMAND)

    def events(self) -> tuple[LedgerEntry, ...]:
        return tuple(entry for entry in self._entries if entry.kind is LedgerEntryKind.EVENT)

    def fills(self) -> tuple[LedgerEntry, ...]:
        return tuple(entry for entry in self._entries if entry.kind is LedgerEntryKind.FILL)
