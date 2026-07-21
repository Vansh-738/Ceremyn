"""Idempotency support for OMS submissions."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_hash: str = Field(min_length=1)
    oms_order_id: UUID
    duplicates: int = Field(default=0, ge=0)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._duplicate_counts: defaultdict[str, int] = defaultdict(int)

    def reserve(self, request_hash: str, oms_order_id: UUID) -> UUID | None:
        existing = self._records.get(request_hash)
        if existing is not None:
            self._duplicate_counts[request_hash] += 1
            return existing.oms_order_id
        self._records[request_hash] = IdempotencyRecord(
            request_hash=request_hash,
            oms_order_id=oms_order_id,
        )
        return None

    def duplicate_count(self, request_hash: str) -> int:
        return self._duplicate_counts[request_hash]

    def seed(self, records: Iterable[tuple[str, UUID]]) -> None:
        """Pre-populate reservations from restored state (e.g. after a restart).

        Never overwrites an existing reservation — restoring is additive, not
        authoritative over anything already reserved in this process.
        """
        for request_hash, oms_order_id in records:
            self._records.setdefault(
                request_hash,
                IdempotencyRecord(request_hash=request_hash, oms_order_id=oms_order_id),
            )
