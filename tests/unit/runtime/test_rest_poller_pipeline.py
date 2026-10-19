"""Exercise polling through real risk, OMS, cache and simulated fills."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from ceremyn.broker.simulated import SimulatedBroker
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import Quote
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.oms.orders import OMSExecutionState
from ceremyn.paper.broker import PaperBrokerConfig
from ceremyn.risk import RiskEngine
from ceremyn.runtime.rest_poller import RestPricePoller
from tests.unit.oms.conftest import T0, FakeBroker, make_signal, permissive_settings


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> RestPricePoller:
    monkeypatch.setattr("ceremyn.runtime.rest_poller.now_utc", lambda: T0)
    monkeypatch.setattr("ceremyn.runtime.rest_poller.now_ist", lambda: T0)
    signal = make_signal()
    contract = signal.legs[0].contract
    kite = Mock()
    kite.spot_price = AsyncMock(return_value=Decimal("25000"))
    kite.fetch_option_contracts = AsyncMock(return_value=[contract])
    kite.quotes = AsyncMock(
        return_value={
            f"NFO:{contract.tradingsymbol}": Quote(
                tradingsymbol=contract.tradingsymbol,
                timestamp=T0,
                last_price=Decimal("150"),
                bid=Decimal("149"),
                ask=Decimal("151"),
            )
        }
    )
    strategy = Mock()
    strategy.definition.id = signal.strategy_id
    strategy.on_chain.return_value = [signal]
    cache = LiveDataCache()
    broker = SimulatedBroker(
        market_data=cache, clock=lambda: T0, config=PaperBrokerConfig(latency_seconds=0)
    )
    engine = OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={broker.name: broker},
        default_broker=broker.name,
    )
    return RestPricePoller(
        kite_provider=kite,
        oms_engine=engine,
        cache=cache,
        analytics=ChainAnalyticsService(risk_free_rate=0.065),
        strategies=[strategy],
    )


@pytest.mark.asyncio
async def test_poll_caches_quotes_fills_and_marks_portfolio(pipeline: RestPricePoller) -> None:
    await pipeline._poll_once()
    chain = pipeline._cache.latest_chain("NIFTY")
    assert chain is not None and chain.entries[0].quote is not None
    assert chain.entries[0].quote.last_price == Decimal("150")
    (order,) = pipeline._oms_engine.orders.values()
    assert order.filled_quantity == order.order.quantity
    assert len(pipeline._oms_engine.portfolio.snapshot().positions) == 1
    assert pipeline.orphaned_symbols == ()
    assert pipeline._iv_history
    ctx = pipeline._strategies[0].on_chain.call_args.args[0]
    assert ctx.chain == chain and ctx.positions == ()


@pytest.mark.asyncio
async def test_duplicate_signal_does_not_duplicate_orders_or_fills(
    pipeline: RestPricePoller,
) -> None:
    await pipeline._poll_once()
    positions = dict(pipeline._oms_engine.portfolio.positions)
    await pipeline._poll_once()
    assert len(pipeline._oms_engine.orders) == 1
    assert pipeline._oms_engine.portfolio.positions == positions
    assert pipeline._strategies[0].on_chain.call_args.args[0].positions


@pytest.mark.asyncio
async def test_risk_rejection_never_reaches_broker(pipeline: RestPricePoller) -> None:
    settings = permissive_settings()
    settings.risk.position.max_lots_per_signal = 1
    signal = make_signal()
    signal = signal.model_copy(update={"legs": (signal.legs[0].model_copy(update={"lots": 2}),)})
    pipeline._strategies[0].on_chain.return_value = [signal]
    broker = FakeBroker()
    pipeline._oms_engine = OrderManagementEngine(
        risk_engine=RiskEngine(settings), brokers={"fake": broker}, default_broker="fake"
    )
    await pipeline._poll_once()
    assert not broker.orders
    assert not pipeline._oms_engine.portfolio.positions


@pytest.mark.asyncio
async def test_broker_submission_failure_is_recorded(pipeline: RestPricePoller) -> None:
    symbol = make_signal().legs[0].contract.tradingsymbol
    broker = FakeBroker(reject_tradingsymbols=frozenset({symbol}))
    pipeline._oms_engine = OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"fake": broker},
        default_broker="fake",
    )
    await pipeline._poll_once()
    (order,) = pipeline._oms_engine.orders.values()
    assert order.execution_state is OMSExecutionState.FAILED
    assert not pipeline._oms_engine.portfolio.positions


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["expired access_token", "network unavailable"])
async def test_quote_failure_stops_before_strategy(pipeline: RestPricePoller, error: str) -> None:
    pipeline._kite.quotes.side_effect = RuntimeError(error)
    with pytest.raises(RuntimeError, match=error):
        await pipeline._poll_once()
    pipeline._strategies[0].on_chain.assert_not_called()
    assert pipeline._cache.latest_chain("NIFTY") is None
    assert not pipeline._oms_engine.orders


@pytest.mark.asyncio
async def test_missing_quotes_and_no_signals_leave_portfolio_empty(
    pipeline: RestPricePoller,
) -> None:
    pipeline._kite.quotes.return_value = {}
    pipeline._strategies[0].on_chain.return_value = []
    await pipeline._poll_once()
    assert pipeline._iv_history == []
    assert not pipeline._oms_engine.orders


@pytest.mark.asyncio
async def test_feature_and_strategy_failure_are_isolated(pipeline: RestPricePoller) -> None:
    features = Mock()
    features.compute_all.side_effect = RuntimeError("feature failed")
    pipeline._feature_engine = features
    broken = Mock()
    broken.definition.id = "broken"
    broken.on_chain.side_effect = RuntimeError("strategy failed")
    pipeline._strategies = (broken, *pipeline._strategies)
    await pipeline._poll_once()
    assert len(pipeline._oms_engine.orders) == 1
    assert pipeline.latest_features is None
    features.compute_all.side_effect = None
    await pipeline._poll_once()
    assert pipeline.latest_features is features.compute_all.return_value


@pytest.mark.asyncio
async def test_orphan_alert_and_bounded_iv_history(pipeline: RestPricePoller) -> None:
    await pipeline._poll_once()
    symbol = next(iter(pipeline._oms_engine.portfolio.positions))
    pipeline._strategies = ()
    pipeline._iv_history = [0.2] * 1000
    await pipeline._poll_once()
    assert pipeline.orphaned_symbols == (symbol,)
    assert len(pipeline._iv_history) == 1000


@pytest.mark.asyncio
async def test_contract_selection_filters_expiry_and_strikes_and_caches(
    pipeline: RestPricePoller,
) -> None:
    contract = make_signal().legs[0].contract
    pipeline._kite.fetch_option_contracts.return_value = [
        contract,
        contract.model_copy(update={"expiry": T0.date() - timedelta(days=1)}),
        contract.model_copy(update={"expiry": contract.expiry + timedelta(days=7)}),
        contract.model_copy(update={"strike": Decimal("50000")}),
    ]
    assert await pipeline._contracts_near(Decimal("25000")) == (contract,)
    assert await pipeline._contracts_near(Decimal("25000")) == (contract,)
    pipeline._kite.fetch_option_contracts.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_upcoming_contracts_skips_quotes_and_strategy(pipeline: RestPricePoller) -> None:
    pipeline._kite.fetch_option_contracts.return_value = []
    await pipeline._poll_once()
    pipeline._kite.quotes.assert_not_awaited()
    pipeline._strategies[0].on_chain.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("market_open,has_strategies", [(False, True), (True, False), (True, True)])
async def test_run_resets_failure_only_after_success(
    pipeline: RestPricePoller,
    monkeypatch: pytest.MonkeyPatch,
    market_open: bool,
    has_strategies: bool,
) -> None:
    pipeline._calendar = Mock()
    pipeline._calendar.is_market_open.return_value = market_open
    if not has_strategies:
        pipeline._strategies = ()
    pipeline._consecutive_failures = 2
    pipeline._last_error = "old failure"
    monkeypatch.setattr(
        "ceremyn.runtime.rest_poller.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await pipeline._run()
    succeeded = market_open and has_strategies
    assert pipeline.consecutive_failures == (0 if succeeded else 2)
    assert pipeline.last_error == ("" if succeeded else "old failure")
    assert pipeline.last_success_at == (T0 if succeeded else None)
    await pipeline.stop()
