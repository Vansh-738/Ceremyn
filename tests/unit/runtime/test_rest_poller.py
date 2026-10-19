import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import Side, Signal, SignalAction, SignalLeg
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.broker import BrokerExecutionReport, BrokerOrderStatus
from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.risk import RiskEngine
from ceremyn.runtime.rest_poller import RestPricePoller, _orphaned_symbols, _strategy_positions
from ceremyn.strategies.base import Strategy, StrategyContext
from tests.unit.backtest.helpers import make_contract
from tests.unit.oms.conftest import EXPIRY, T0, FakeBroker, permissive_settings


class _AlwaysOpenCalendar:
    def is_market_open(self, timestamp: datetime) -> bool:
        return True


class _FailingKiteProvider:
    """`spot_price` always raises -- simulates an expired Kite access token."""

    async def spot_price(self, underlying: str) -> Decimal:
        raise RuntimeError("Kite LTP fetch failed: Incorrect `api_key` or `access_token`.")


class _NoopStrategy(Strategy[Any]):
    strategy_type = "test_noop"

    def on_chain(self, ctx: StrategyContext) -> list:  # type: ignore[type-arg]
        return []


def _make_poller() -> RestPricePoller:
    from ceremyn.domain import StrategyDefinition

    definition = StrategyDefinition(
        id="noop", strategy_type="test_noop", name="noop", underlyings=("NIFTY",)
    )
    strategy = _NoopStrategy.__new__(_NoopStrategy)
    strategy.definition = definition
    strategy.params = None
    return RestPricePoller(
        kite_provider=_FailingKiteProvider(),  # type: ignore[arg-type]
        oms_engine=None,  # type: ignore[arg-type]
        analytics=ChainAnalyticsService(risk_free_rate=0.065),
        cache=LiveDataCache(),
        strategies=(strategy,),
        underlying="NIFTY",
        poll_interval_seconds=0.01,
        calendar=_AlwaysOpenCalendar(),  # type: ignore[arg-type]
    )


class TestFailureTracking:
    def test_starts_with_no_failures(self) -> None:
        poller = _make_poller()
        assert poller.consecutive_failures == 0
        assert poller.last_error == ""
        assert poller.last_success_at is None

    @pytest.mark.asyncio
    async def test_repeated_tick_failures_increment_the_counter(self) -> None:
        poller = _make_poller()
        await poller.start()
        try:
            # Coverage / CI instrumentation can make a 10ms task wake late. Wait for
            # the observable condition rather than relying on a fixed wall-clock sleep.
            for _ in range(20):
                if poller.consecutive_failures >= 2:
                    break
                await asyncio.sleep(0.01)
        finally:
            await poller.stop()
        assert poller.consecutive_failures >= 2
        assert "access_token" in poller.last_error
        assert poller.last_success_at is None


def _fill(
    engine: OrderManagementEngine, *, strategy_id: str, side: Side, symbol_strike: str
) -> None:
    """Submit and fill one signal under `strategy_id`, isolated to `symbol_strike`."""
    contract = make_contract(
        symbol=f"NIFTY26JUL{symbol_strike}CE", expiry=EXPIRY, strike=symbol_strike
    )
    signal = Signal(
        strategy_id=strategy_id,
        signal_type=SignalAction.ENTER,
        created_at=T0,
        market_timestamp=T0,
        legs=(SignalLeg(contract=contract, side=side, lots=1),),
        reason="test fill",
    )
    (order,) = engine.submit_signal(signal, now=T0)
    assert order.external_order_id is not None
    engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=order.external_order_id,
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0,
            fill_id=f"fill-{strategy_id}-{symbol_strike}-{side.value}",
            last_fill_quantity=order.order.quantity,
            fill_price=Decimal("100"),
            remaining_quantity=0,
        )
    )


class TestStrategyPositions:
    """Regression coverage for the whole-portfolio position leak: every strategy the
    poller ran used to see every other strategy's positions as its own, since
    `StrategyContext.positions` was populated from the whole account rather than each
    strategy's own fill history."""

    def test_scopes_positions_to_the_strategy_that_actually_opened_them(self) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )
        _fill(engine, strategy_id="strat_a", side=Side.BUY, symbol_strike="25000")

        # strat_b never opened anything -- selling the SAME symbol strat_a holds is
        # exactly what happened in production: every strategy saw the whole account's
        # position, thought it was its own, and tried to "exit" it.
        _fill(engine, strategy_id="strat_b", side=Side.SELL, symbol_strike="25000")

        strat_a_positions = _strategy_positions(engine, "strat_a")
        strat_b_positions = _strategy_positions(engine, "strat_b")

        assert len(strat_a_positions) == 1
        assert strat_a_positions[0].quantity > 0  # strat_a's own BUY, untouched
        assert len(strat_b_positions) == 1
        assert strat_b_positions[0].quantity < 0  # strat_b's own (bare) SELL

    def test_flat_strategy_sees_no_positions_even_when_the_account_is_not_flat(
        self,
    ) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )
        _fill(engine, strategy_id="strat_a", side=Side.BUY, symbol_strike="25100")

        assert _strategy_positions(engine, "strat_b") == ()

    def test_closed_position_nets_to_flat_and_is_excluded(self) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )
        _fill(engine, strategy_id="strat_a", side=Side.BUY, symbol_strike="25200")
        _fill(engine, strategy_id="strat_a", side=Side.SELL, symbol_strike="25200")

        assert _strategy_positions(engine, "strat_a") == ()


class TestOrphanedSymbols:
    """A position left open by a strategy that's no longer in the active roster
    (removed from live trading, or its definition/id changed) must be flagged, not
    silently ignored -- nothing else will ever generate an exit signal for it."""

    def test_position_owned_by_an_inactive_strategy_is_orphaned(self) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )
        _fill(engine, strategy_id="removed_strategy", side=Side.BUY, symbol_strike="25300")

        orphaned = _orphaned_symbols(engine, active_strategy_ids=("still_running",))

        assert orphaned == ("NIFTY26JUL25300CE",)

    def test_position_owned_by_an_active_strategy_is_not_orphaned(self) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )
        _fill(engine, strategy_id="strat_a", side=Side.BUY, symbol_strike="25400")

        orphaned = _orphaned_symbols(engine, active_strategy_ids=("strat_a",))

        assert orphaned == ()

    def test_no_open_positions_means_nothing_is_orphaned(self) -> None:
        engine = OrderManagementEngine(
            risk_engine=RiskEngine(permissive_settings()),
            brokers={"fake": FakeBroker()},
            default_broker="fake",
        )

        assert _orphaned_symbols(engine, active_strategy_ids=()) == ()
