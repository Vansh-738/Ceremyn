import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel

from ceremyn.core.events import EventBus
from ceremyn.domain import Side, Signal, SignalAction, SignalLeg, StrategyDefinition
from ceremyn.live.engine import LiveMarketDataEngine
from ceremyn.live.stream import StreamTickBatch
from ceremyn.oms.broker import BrokerExecutionReport, BrokerOrderStatus
from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.oms.journal import JSONJournalStore, OMSJournal
from ceremyn.oms.orders import PlanOrderRole
from ceremyn.risk import RiskDecision, RiskEngine
from ceremyn.runtime.orchestrator import RuntimeOrchestrator
from ceremyn.strategies.base import Strategy, StrategyContext
from tests.unit.live.conftest import BASE_TS, nifty_contracts
from tests.unit.live.conftest import tick_payload as _tick_payload
from tests.unit.oms.conftest import FakeBroker, permissive_settings

CALL_TOKEN = 101
PUT_TOKEN = 102
INDEX_TOKEN = 256265


class _NoParams(BaseModel):
    pass


class _AlwaysEnterStrategy(Strategy[_NoParams]):
    """Enters once (one leg from whatever the observed chain offers) and never again."""

    params_model = _NoParams
    strategy_type = "test_always_enter"

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position or not ctx.chain.entries:
            return []
        contract = ctx.chain.entries[0].contract
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=contract, side=Side.BUY, lots=1),),
                reason="test: always enter",
            )
        ]


class _SplitCorrelatedStrategy(Strategy[_NoParams]):
    """Calendar-Spread-shaped: two single-leg signals sharing one correlation_id."""

    params_model = _NoParams
    strategy_type = "test_split_correlated"

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position or len(ctx.chain.entries) < 2:
            return []
        correlation_id = uuid4()
        contracts = [entry.contract for entry in ctx.chain.entries[:2]]
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=contracts[0], side=Side.BUY, lots=1),),
                reason="near leg",
                correlation_id=correlation_id,
            ),
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=contracts[1], side=Side.BUY, lots=1),),
                reason="far leg",
                correlation_id=correlation_id,
            ),
        ]


def _definition(strategy_type: str) -> StrategyDefinition:
    return StrategyDefinition(
        id=f"{strategy_type}-1",
        strategy_type=strategy_type,
        name=strategy_type,
        underlyings=("NIFTY",),
    )


def _make_oms_engine(
    broker: FakeBroker, *, journal: OMSJournal | None = None
) -> OrderManagementEngine:
    kwargs: dict[str, OMSJournal] = {} if journal is None else {"journal": journal}
    return OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"fake": broker},
        default_broker="fake",
        **kwargs,
    )


async def _publish_full_chain_batch(orchestrator: RuntimeOrchestrator, *, as_of=BASE_TS) -> None:
    """Reproduces the same 3-tick sequence `tests/unit/live/test_engine.py` uses to
    get a non-None `MarketSnapshot` out of `LiveMarketDataEngine.on_raw_tick`: one
    index tick plus one tick per option contract."""
    for token, price in ((INDEX_TOKEN, "24010"), (CALL_TOKEN, "150"), (PUT_TOKEN, "145")):
        batch = StreamTickBatch(
            ticks=(_tick_payload(token, last_price=price, timestamp=as_of),),
            received_at=as_of,
        )
        await orchestrator.stream.publish(batch)


@pytest.fixture
def underlyings():
    from tests.unit.live.conftest import nifty_definition

    return (nifty_definition(),)


@pytest.fixture
def contracts():
    return nifty_contracts()


@pytest.fixture
def analytics():
    from ceremyn.data.services.chain_analytics import ChainAnalyticsService

    return ChainAnalyticsService(risk_free_rate=0.065)


@pytest.mark.asyncio
async def test_start_and_stop_are_clean_and_idempotent(underlyings, contracts, analytics) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine)

    await orchestrator.start()
    assert orchestrator._tick_task is not None
    assert not orchestrator._tick_task.done()
    assert orchestrator._maintenance_task is not None

    await orchestrator.stop()
    assert orchestrator._tick_task is None
    assert orchestrator._maintenance_task is None


@pytest.mark.asyncio
async def test_tick_drives_strategy_through_to_a_real_order(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    broker = FakeBroker()
    oms_engine = _make_oms_engine(broker)
    strategy = _AlwaysEnterStrategy(_definition("test_always_enter"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, strategies=(strategy,)
    )

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)  # let the background consumer task run
    finally:
        await orchestrator.stop()

    assert len(oms_engine.orders) == 1
    (order,) = oms_engine.orders.values()
    assert order.role is PlanOrderRole.ENTRY
    assert order.external_order_id is not None


@pytest.mark.asyncio
async def test_maintenance_loop_polls_fills_exactly_once_per_report(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    broker = FakeBroker()
    oms_engine = _make_oms_engine(broker)
    strategy = _AlwaysEnterStrategy(_definition("test_always_enter"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine,
        oms_engine=oms_engine,
        strategies=(strategy,),
        poll_interval_seconds=1000,  # never fires on its own; call the fill poller directly
    )

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)
        (order,) = oms_engine.orders.values()
        assert order.external_order_id is not None

        broker.reports.append(
            BrokerExecutionReport(
                external_order_id=order.external_order_id,
                status=BrokerOrderStatus.FILLED,
                broker_timestamp=BASE_TS + timedelta(seconds=1),
                fill_id="fill-1",
                last_fill_quantity=order.order.quantity,
                fill_price=order.order.limit_price or Decimal("150"),
                remaining_quantity=0,
            )
        )
        poll = orchestrator._fill_poller.poll
        poll(oms_engine=oms_engine, broker=broker)
        poll(oms_engine=oms_engine, broker=broker)  # fetch_fills() re-returns the same report
    finally:
        await orchestrator.stop()

    updated = oms_engine.orders[order.oms_order_id]
    assert updated.filled_quantity == order.order.quantity  # applied once, not twice


@pytest.mark.asyncio
async def test_split_correlated_signals_compensate_through_the_orchestrators_own_dispatch(
    underlyings, contracts, analytics
) -> None:
    """The Calendar-Spread shape, driven end-to-end through the orchestrator (not just
    the OMS primitive directly): one leg is risk-rejected after the other is already
    live, and the orchestrator's normal tick -> submit_correlated_signals path must
    still leave the surviving leg compensated, not naked."""

    class RejectSecondSignal(RiskEngine):
        def __init__(self, settings) -> None:
            super().__init__(settings)
            self.calls = 0

        def validate(self, portfolio, signal, *, evaluated_at=None):
            self.calls += 1
            if self.calls == 2:
                return RiskDecision(
                    approved=False,
                    risk_score=0.0,
                    violations=["test: reject far leg"],
                    timestamp=evaluated_at or BASE_TS,
                )
            return super().validate(portfolio, signal, evaluated_at=evaluated_at)

    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    broker = FakeBroker()
    oms_engine = OrderManagementEngine(
        risk_engine=RejectSecondSignal(permissive_settings()),
        brokers={"fake": broker},
        default_broker="fake",
    )
    strategy = _SplitCorrelatedStrategy(_definition("test_split_correlated"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, strategies=(strategy,)
    )

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)
    finally:
        await orchestrator.stop()

    entries = [o for o in oms_engine.orders.values() if o.role is PlanOrderRole.ENTRY]
    assert len(entries) == 1  # the far leg was rejected before it ever became an order
    # The near leg was still resting (unfilled) when the rejection landed, so
    # compensation cancelled it outright rather than leaving it naked.
    assert oms_engine.orders[entries[0].oms_order_id].execution_state.value == "cancelled"


@pytest.mark.asyncio
async def test_restart_restores_orders_before_any_new_tick(
    tmp_path, underlyings, contracts, analytics
) -> None:
    session_id = "restart-test"
    call_contract, _put_contract = contracts

    def build_signal() -> Signal:
        return Signal(
            strategy_id="s",
            signal_type=SignalAction.ENTER,
            created_at=BASE_TS,
            market_timestamp=BASE_TS,
            legs=(SignalLeg(contract=call_contract, side=Side.BUY, lots=1),),
            reason="pre-restart entry",
        )

    broker_a = FakeBroker()
    journal_a = OMSJournal(session_id, store=JSONJournalStore(session_id, root=tmp_path))
    oms_engine_a = _make_oms_engine(broker_a, journal=journal_a)
    (order,) = oms_engine_a.submit_signal(build_signal(), now=BASE_TS)

    # A fresh process: new engine, new orchestrator, pointed at the same journal path.
    journal_b = OMSJournal(session_id, store=JSONJournalStore(session_id, root=tmp_path))
    oms_engine_b = OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"fake": FakeBroker()},
        default_broker="fake",
        journal=journal_b,
    )
    oms_engine_b.restore_from_journal()
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine_b)

    # The restored order is already visible through the orchestrator's own engine
    # reference before `start()` is even called — no tick is needed to see it.
    assert order.oms_order_id in orchestrator._oms_engine.orders
    assert orchestrator._oms_engine.orders[order.oms_order_id].request_hash == order.request_hash


@pytest.mark.asyncio
async def test_start_binds_a_configured_streaming_client(underlyings, contracts, analytics) -> None:
    class FakeStreamingClient:
        def __init__(self) -> None:
            self.bound_with: object | None = None

        def bind_stream(self, stream, *, engine) -> None:
            self.bound_with = (stream, engine)

    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())
    client = FakeStreamingClient()
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, streaming_client=client
    )

    await orchestrator.start()
    try:
        assert client.bound_with == (orchestrator.stream, live_engine)
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_start_survives_a_failing_startup_reconciliation(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())

    def _boom(*, now=None):
        raise RuntimeError("broker unreachable")

    oms_engine.reconcile = _boom  # type: ignore[method-assign]
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine)

    await orchestrator.start()  # must not raise
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_tick_outside_market_hours_is_skipped(underlyings, contracts, analytics) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())
    strategy = _AlwaysEnterStrategy(_definition("test_always_enter"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, strategies=(strategy,)
    )
    after_close = BASE_TS + timedelta(hours=8)  # 09:50 IST -> 17:50 IST, past the 15:30 close

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator, as_of=after_close)
        await asyncio.sleep(0.05)
    finally:
        await orchestrator.stop()

    assert oms_engine.orders == {}
    assert orchestrator._scheduler.ticks_skipped >= 1


@pytest.mark.asyncio
async def test_tick_with_no_strategies_configured_is_a_safe_no_op(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine)

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)
    finally:
        await orchestrator.stop()

    assert oms_engine.orders == {}
    assert orchestrator._scheduler.ticks_processed >= 1


@pytest.mark.asyncio
async def test_strategy_on_chain_exception_does_not_crash_the_consumer(
    underlyings, contracts, analytics
) -> None:
    class _BrokenStrategy(Strategy[_NoParams]):
        params_model = _NoParams
        strategy_type = "test_broken"

        def on_chain(self, ctx: StrategyContext) -> list[Signal]:
            raise ValueError("boom")

    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())
    strategy = _BrokenStrategy(_definition("test_broken"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, strategies=(strategy,)
    )

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)  # must not raise / kill the consumer task
    finally:
        await orchestrator.stop()

    assert orchestrator._tick_task is None  # stop() still completed cleanly
    assert oms_engine.orders == {}


@pytest.mark.asyncio
async def test_unexpected_signal_submission_error_does_not_crash_the_consumer(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())

    def _boom(signals, *, now=None):
        raise RuntimeError("unexpected OMS failure")

    oms_engine.submit_correlated_signals = _boom  # type: ignore[method-assign]
    strategy = _AlwaysEnterStrategy(_definition("test_always_enter"))
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, strategies=(strategy,)
    )

    await orchestrator.start()
    try:
        await _publish_full_chain_batch(orchestrator)
        await asyncio.sleep(0.05)
    finally:
        await orchestrator.stop()  # must complete cleanly despite the failure above


@pytest.mark.asyncio
async def test_maintenance_loop_runs_and_survives_heartbeat_and_reconcile_failures(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    oms_engine = _make_oms_engine(FakeBroker())

    async def _boom_heartbeat(*, now=None):
        raise RuntimeError("heartbeat check failed")

    def _boom_reconcile(*, now=None):
        raise RuntimeError("reconcile failed")

    live_engine.check_heartbeat = _boom_heartbeat  # type: ignore[method-assign]
    orchestrator = RuntimeOrchestrator(
        live_engine=live_engine, oms_engine=oms_engine, poll_interval_seconds=0.01
    )
    # The first reconcile (inside start()) must succeed so poll_interval_seconds is what
    # actually drives the maintenance loop's own reconcile call below.
    await orchestrator.start()
    oms_engine.reconcile = _boom_reconcile  # type: ignore[method-assign]
    try:
        await asyncio.sleep(0.05)  # let the maintenance loop tick at least once
    finally:
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_poll_fills_survives_a_broker_failure(underlyings, contracts, analytics) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    broker = FakeBroker()
    oms_engine = _make_oms_engine(broker)
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine)

    def _boom():
        raise RuntimeError("fetch_fills failed")

    broker.fetch_fills = _boom  # type: ignore[method-assign]
    orchestrator._fill_poller.poll(oms_engine=oms_engine, broker=broker)  # must not raise


@pytest.mark.asyncio
async def test_poll_fills_logs_and_skips_a_report_for_an_unknown_order(
    underlyings, contracts, analytics
) -> None:
    live_engine = LiveMarketDataEngine(
        underlyings=underlyings, contracts=contracts, analytics=analytics, event_bus=EventBus()
    )
    broker = FakeBroker()
    oms_engine = _make_oms_engine(broker)
    orchestrator = RuntimeOrchestrator(live_engine=live_engine, oms_engine=oms_engine)

    broker.reports.append(
        BrokerExecutionReport(
            external_order_id="ext-does-not-exist",
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=BASE_TS,
            fill_id="fill-orphan",
            last_fill_quantity=25,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )

    orchestrator._fill_poller.poll(oms_engine=oms_engine, broker=broker)  # must not raise; skipped
