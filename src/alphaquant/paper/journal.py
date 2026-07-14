"""PaperJournal: durably record everything that happens in a session.

Records signals, risk decisions, fills, position snapshots, exits (closed trades), and
PnL marks as append-only journal entries. Persistence follows the M6 store pattern: a
`JournalStore` protocol with a JSON-file implementation (so nothing is lost) and an
in-memory implementation for tests. Session statistics reuse the shared backtest metrics.
"""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.backtest.ledger import ClosedTrade
from alphaquant.backtest.metrics import compute_statistics
from alphaquant.backtest.statistics import BacktestStatistics, EquityPoint
from alphaquant.core.timeutils import now_utc
from alphaquant.domain import Fill, PortfolioSnapshot, Signal
from alphaquant.domain.market_data import _require_aware
from alphaquant.paper.events import OrderFilled, OrderRejected, RiskEvaluated


class JournalEntryKind(StrEnum):
    SIGNAL = "signal"
    RISK_DECISION = "risk_decision"
    FILL = "fill"
    POSITION = "position"
    EXIT = "exit"
    PNL = "pnl"


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
    """Append-only JSON-lines store: one file per session under a root directory."""

    DEFAULT_ROOT = Path("data/paper/journal")

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


class PaperJournal:
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
            {
                "signal_id": str(signal.signal_id),
                "strategy_id": signal.strategy_id,
                "action": signal.signal_type.value,
                "reason": signal.reason,
                "legs": len(signal.legs),
            },
            at=at or signal.market_timestamp or now_utc(),
        )

    def record_risk(self, event: RiskEvaluated, *, at: datetime | None = None) -> None:
        self._record(
            JournalEntryKind.RISK_DECISION,
            {
                "signal_id": str(event.signal.signal_id),
                "approved": event.decision.approved,
                "risk_score": event.decision.risk_score,
                "violations": list(event.decision.violations),
            },
            at=at or event.decision.timestamp,
        )

    def record_rejection(self, event: OrderRejected, *, at: datetime) -> None:
        self._record(
            JournalEntryKind.RISK_DECISION,
            {"signal_id": str(event.signal.signal_id), "approved": False, "reason": event.reason},
            at=at,
        )

    def record_fill(self, event: OrderFilled) -> None:
        fill: Fill = event.fill
        self._record(
            JournalEntryKind.FILL,
            {
                "order_id": str(event.order.id),
                "tradingsymbol": event.order.contract.tradingsymbol,
                "side": event.order.side.value,
                "quantity": fill.quantity,
                "price": str(fill.price),
                "costs": str(event.costs.total),
                "latency_seconds": event.latency_seconds,
            },
            at=fill.timestamp,
        )

    def record_position_snapshot(self, snapshot: PortfolioSnapshot, *, at: datetime) -> None:
        self._record(
            JournalEntryKind.POSITION,
            {
                "open_positions": len(snapshot.positions),
                "margin_used": str(snapshot.margin_used),
                "buying_power": str(snapshot.buying_power),
            },
            at=at,
        )

    def record_exit(self, trade: ClosedTrade) -> None:
        self._record(
            JournalEntryKind.EXIT,
            {
                "tradingsymbol": trade.contract.tradingsymbol,
                "strategy_id": trade.strategy_id,
                "quantity": trade.quantity,
                "entry_price": str(trade.entry_price),
                "exit_price": str(trade.exit_price),
                "net_pnl": str(trade.net_pnl),
            },
            at=trade.exit_at,
        )

    def record_pnl(self, snapshot: PortfolioSnapshot, *, at: datetime) -> None:
        self._record(
            JournalEntryKind.PNL,
            {
                "realized_pnl": str(snapshot.realized_pnl),
                "unrealized_pnl": str(snapshot.unrealized_pnl),
                "daily_pnl": str(snapshot.daily_pnl),
                "drawdown": str(snapshot.drawdown),
            },
            at=at,
        )

    def entries(self) -> tuple[JournalEntry, ...]:
        return self.store.entries()

    def entries_of(self, kind: JournalEntryKind) -> tuple[JournalEntry, ...]:
        return tuple(entry for entry in self.entries() if entry.kind is kind)

    def session_summary(
        self,
        *,
        equity_curve: tuple[EquityPoint, ...],
        closed_trades: tuple[ClosedTrade, ...],
        initial_cash: Any,
    ) -> BacktestStatistics:
        return compute_statistics(
            equity_curve=equity_curve,
            closed_trades=closed_trades,
            initial_cash=initial_cash,
        )
