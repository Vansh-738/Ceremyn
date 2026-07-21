from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ceremyn.backtest.commission import CostBreakdown
from ceremyn.domain import Fill, Order, PortfolioSnapshot, Side, Signal, SignalLeg
from ceremyn.domain.enums import OrderStatus, OrderType, SignalAction
from ceremyn.paper.events import OrderFilled, OrderRejected, RiskEvaluated
from ceremyn.paper.journal import (
    InMemoryJournalStore,
    JournalEntryKind,
    JournalStore,
    JSONJournalStore,
    PaperJournal,
)
from ceremyn.risk import RiskEngine
from tests.unit.backtest.helpers import make_contract
from tests.unit.paper.conftest import TICK_ZERO, permissive_settings


def a_signal() -> Signal:
    return Signal(
        strategy_id="s",
        signal_type=SignalAction.ENTER,
        created_at=TICK_ZERO,
        legs=(SignalLeg(contract=make_contract(), side=Side.BUY, lots=1),),
        reason="enter",
    )


def a_fill_event() -> OrderFilled:
    order = Order(
        contract=make_contract(),
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created_at=TICK_ZERO,
    )
    return OrderFilled(
        order=order,
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("100"), timestamp=TICK_ZERO),
        costs=CostBreakdown(),
        submitted_at=TICK_ZERO,
        strategy_id="s",
    )


class TestRecording:
    def test_records_all_kinds(self) -> None:
        journal = PaperJournal("sess")
        risk = RiskEngine(permissive_settings())
        signal = a_signal()
        decision = risk.evaluate(PortfolioSnapshot(), signal, evaluated_at=TICK_ZERO)

        journal.record_signal(signal)
        journal.record_risk(RiskEvaluated(signal=signal, decision=decision))
        journal.record_fill(a_fill_event())
        journal.record_position_snapshot(PortfolioSnapshot(), at=TICK_ZERO)
        journal.record_pnl(PortfolioSnapshot(), at=TICK_ZERO)

        assert len(journal.entries()) == 5
        assert len(journal.entries_of(JournalEntryKind.SIGNAL)) == 1
        assert len(journal.entries_of(JournalEntryKind.FILL)) == 1

    def test_rejection_recorded_as_risk_decision(self) -> None:
        journal = PaperJournal("sess")
        journal.record_rejection(OrderRejected(signal=a_signal(), reason="too big"), at=TICK_ZERO)
        entry = journal.entries_of(JournalEntryKind.RISK_DECISION)[0]
        assert entry.payload["approved"] is False
        assert entry.payload["reason"] == "too big"

    def test_fill_entry_has_latency(self) -> None:
        journal = PaperJournal("sess")
        journal.record_fill(a_fill_event())
        assert journal.entries_of(JournalEntryKind.FILL)[0].payload["latency_seconds"] == 0.0


class TestStores:
    def test_in_memory_store_roundtrip(self) -> None:
        store = InMemoryJournalStore()
        journal = PaperJournal("sess", store)
        journal.record_signal(a_signal())
        assert len(store.entries()) == 1
        assert isinstance(store, JournalStore)

    def test_json_store_persists_across_instances(self, tmp_path: Path) -> None:
        journal = PaperJournal("sess-1", JSONJournalStore("sess-1", tmp_path))
        journal.record_signal(a_signal())
        journal.record_fill(a_fill_event())
        # A fresh store over the same file sees the persisted entries.
        reopened = JSONJournalStore("sess-1", tmp_path)
        assert len(reopened.entries()) == 2
        assert isinstance(reopened, JournalStore)

    def test_json_store_empty_when_no_file(self, tmp_path: Path) -> None:
        assert JSONJournalStore("never-written", tmp_path).entries() == ()


def test_session_summary_uses_shared_metrics() -> None:
    journal = PaperJournal("sess")
    summary = journal.session_summary(
        equity_curve=(), closed_trades=(), initial_cash=Decimal("1000000")
    )
    assert summary.total_return == 0.0


def test_journal_default_store_is_in_memory() -> None:
    journal = PaperJournal("sess")
    assert isinstance(journal.store, InMemoryJournalStore)
    # sanity: recording works without a datetime import error
    journal.record_pnl(PortfolioSnapshot(), at=datetime(2026, 7, 14, tzinfo=UTC))
    assert len(journal.entries()) == 1
