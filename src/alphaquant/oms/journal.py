"""Durable OMS journal."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.core.timeutils import now_utc
from alphaquant.domain import Fill, PortfolioSnapshot, Signal
from alphaquant.domain.market_data import _require_aware
from alphaquant.oms.events import OMSEvent
from alphaquant.oms.orders import (
    CancelOrderCommand,
    OMSOrder,
    ReplaceOrderCommand,
    SubmitOrderCommand,
)
from alphaquant.risk import RiskDecision


class JournalEntryKind(StrEnum):
    SIGNAL = "signal"
    RISK_DECISION = "risk_decision"
    COMMAND = "command"
    EVENT = "event"
    FILL = "fill"
    POSITION = "position"
    RECONCILIATION = "reconciliation"
    KILL_SWITCH = "kill_switch"
    ORDER_SNAPSHOT = "order_snapshot"


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: JournalEntryKind
    timestamp: datetime
    session_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    _aware = field_validator("timestamp")(_require_aware)


@runtime_checkable
class JournalStore(Protocol):
    def append(self, entry: JournalEntry) -> None: ...

    def entries(self) -> tuple[JournalEntry, ...]: ...


class InMemoryJournalStore:
    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def append(self, entry: JournalEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)


class JSONJournalStore:
    DEFAULT_ROOT = Path("data/oms/journal")

    def __init__(self, session_id: str, root: Path | str = DEFAULT_ROOT) -> None:
        self.session_id = session_id
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / f"{session_id}.jsonl"

    def append(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")

    def entries(self) -> tuple[JournalEntry, ...]:
        if not self.path.exists():
            return ()
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return tuple(JournalEntry.model_validate_json(line) for line in lines if line.strip())


class OMSJournal:
    def __init__(self, session_id: str, store: JournalStore | None = None) -> None:
        self.session_id = session_id
        self.store = store if store is not None else InMemoryJournalStore()

    def _record(self, kind: JournalEntryKind, payload: dict[str, Any], *, at: datetime) -> None:
        self.store.append(
            JournalEntry(kind=kind, timestamp=at, session_id=self.session_id, payload=payload)
        )

    def record_signal(self, signal: Signal, *, at: datetime | None = None) -> None:
        self._record(
            JournalEntryKind.SIGNAL,
            {"signal_id": str(signal.signal_id), "strategy_id": signal.strategy_id},
            at=at or signal.market_timestamp or now_utc(),
        )

    def record_risk(self, decision: RiskDecision, signal: Signal) -> None:
        self._record(
            JournalEntryKind.RISK_DECISION,
            {
                "signal_id": str(signal.signal_id),
                "approved": decision.approved,
                "violations": list(decision.violations),
            },
            at=decision.timestamp,
        )

    def record_command(
        self,
        command: SubmitOrderCommand | CancelOrderCommand | ReplaceOrderCommand,
    ) -> None:
        self._record(
            JournalEntryKind.COMMAND,
            command.model_dump(mode="json"),
            at=command.requested_at,
        )

    def record_event(self, event: OMSEvent) -> None:
        self._record(JournalEntryKind.EVENT, event.model_dump(mode="json"), at=event.occurred_at)

    def record_fill(self, fill: Fill, *, strategy_id: str, side: str, tradingsymbol: str) -> None:
        self._record(
            JournalEntryKind.FILL,
            {
                "order_id": str(fill.order_id),
                "quantity": fill.quantity,
                "price": str(fill.price),
                "strategy_id": strategy_id,
                "side": side,
                "tradingsymbol": tradingsymbol,
            },
            at=fill.timestamp,
        )

    def record_position_snapshot(self, snapshot: PortfolioSnapshot, *, at: datetime) -> None:
        self._record(
            JournalEntryKind.POSITION,
            {"open_positions": len(snapshot.positions), "cash": str(snapshot.buying_power)},
            at=at,
        )

    def record_reconciliation(self, payload: dict[str, Any], *, at: datetime) -> None:
        self._record(JournalEntryKind.RECONCILIATION, payload, at=at)

    def record_kill_switch(self, *, armed: bool, reason: str, at: datetime) -> None:
        self._record(
            JournalEntryKind.KILL_SWITCH,
            {"armed": armed, "reason": reason},
            at=at,
        )

    def record_order_snapshot(self, order: OMSOrder, *, at: datetime) -> None:
        """Append the order's full current state — the source restart-recovery reads."""
        self._record(JournalEntryKind.ORDER_SNAPSHOT, order.model_dump(mode="json"), at=at)
