from decimal import Decimal

from ceremyn.config import Settings
from ceremyn.features.engine import FeatureEngine
from ceremyn.paper.journal import JournalEntryKind
from ceremyn.risk import RiskEngine
from ceremyn.strategies import Strategy
from tests.unit.paper.conftest import (
    ListFeed,
    make_engine,
    make_tick,
    price_path_ticks,
)


class TestEndToEnd:
    def test_signal_becomes_order_then_fills_after_latency(
        self, risk_engine: RiskEngine, strategy: Strategy[object]
    ) -> None:
        engine = make_engine(risk_engine, strategy, latency_seconds=1.0)
        r0 = engine.on_tick(make_tick(0, "100"))
        # Tick 0: strategy enters -> order submitted, not yet filled (latency).
        assert r0.fills == ()
        assert engine.monitor.snapshot().submitted == 1

        r1 = engine.on_tick(make_tick(1, "110"))
        # Tick 1 (5s later): the tick-0 order fills.
        assert len(r1.fills) == 1
        assert engine.monitor.snapshot().filled == 1
        assert r1.reconciliation is not None and r1.reconciliation.reconciled

    def test_full_session_produces_pnl_and_journal(
        self, risk_engine: RiskEngine, strategy: Strategy[object]
    ) -> None:
        engine = make_engine(risk_engine, strategy)
        results = engine.run(ListFeed(price_path_ticks(["100", "110", "105", "120"])))
        assert len(results) == 4

        # A round-trip closed at least one trade with booked PnL.
        assert len(engine.portfolio.closed_trades) >= 1
        journal = engine.journal
        assert len(journal.entries_of(JournalEntryKind.SIGNAL)) >= 1
        assert len(journal.entries_of(JournalEntryKind.FILL)) >= 1
        assert len(journal.entries_of(JournalEntryKind.EXIT)) >= 1
        assert len(journal.entries_of(JournalEntryKind.PNL)) == 4

        monitor = engine.monitor.snapshot()
        assert monitor.filled >= 1
        assert 0.0 < monitor.fill_rate <= 1.0
        assert monitor.avg_latency_seconds > 0.0

    def test_reconciliation_can_be_disabled(
        self, risk_engine: RiskEngine, strategy: Strategy[object]
    ) -> None:
        engine = make_engine(risk_engine, strategy, reconcile_each_tick=False)
        result = engine.on_tick(make_tick(0, "100"))
        assert result.reconciliation is None


class TestFeatures:
    def test_features_computed_when_engine_supplied(
        self, risk_engine: RiskEngine, strategy: Strategy[object]
    ) -> None:
        engine = make_engine(risk_engine, strategy, compute_features=True)
        engine.feature_engine = FeatureEngine()
        result = engine.on_tick(make_tick(0, "100"))
        assert result.features is not None
        assert result.features.numeric("pcr") is not None
        assert engine.latest_features is not None

    def test_features_skipped_without_engine(
        self, risk_engine: RiskEngine, strategy: Strategy[object]
    ) -> None:
        engine = make_engine(risk_engine, strategy, compute_features=True)
        # compute_features=True but no FeatureEngine provided -> skipped safely.
        assert engine.on_tick(make_tick(0, "100")).features is None


class TestRiskRejection:
    def test_signal_rejected_when_risk_blocks(self, strategy: Strategy[object]) -> None:
        # Default (restrictive) settings reject the large-notional test order.
        strict_risk = RiskEngine(Settings(_env_file=None))  # type: ignore[call-arg]
        engine = make_engine(strict_risk, strategy)
        result = engine.on_tick(make_tick(0, "100"))
        assert len(result.rejections) == 1
        assert engine.monitor.snapshot().rejected == 1
        assert engine.monitor.snapshot().submitted == 0
        # A rejection is journaled and no order was queued.
        assert engine.broker.open_orders == ()


def test_last_prices_marks_positions(risk_engine: RiskEngine, strategy: Strategy[object]) -> None:
    engine = make_engine(risk_engine, strategy)
    snapshot = engine.on_tick(make_tick(0, "100")).snapshot
    # First tick has no fills yet, so equity equals starting cash.
    assert snapshot.daily_pnl == Decimal("0")
