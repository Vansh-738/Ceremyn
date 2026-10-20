from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

from ceremyn.config.settings import EquityBarSettings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.domain import StrategyDefinition
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.risk import RiskEngine
from ceremyn.runtime.bars import BarStrategyDriver
from ceremyn.runtime.equity_bars import EquityBarJob
from ceremyn.strategies import create
from tests.unit.backtest.test_equity_bars import START, context
from tests.unit.oms.conftest import FakeBroker, permissive_settings


def test_driver_uses_shared_strategy_and_oms_deduplicates_replay() -> None:
    definition = StrategyDefinition(
        id="equity", strategy_type="equity_pattern", name="Equity", underlyings=("TEST",)
    )
    broker = FakeBroker()
    oms = OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"fake": broker},
        default_broker="fake",
    )
    driver = BarStrategyDriver(create(definition), oms)
    ctx = context(0, 100, 100, bullish=True)
    orders = driver.on_bar(ctx, now=START + timedelta(days=1), reference_price=Decimal(101))
    assert len(orders) == 1 and len(broker.orders) == 1
    driver.on_bar(ctx, now=START + timedelta(days=1), reference_price=Decimal(101))
    assert len(broker.orders) == 1


async def test_bar_job_skips_closed_market_and_stale_quotes() -> None:
    driver = Mock()
    provider = AsyncMock()
    loader = AsyncMock(return_value={"TEST": context(0, 100, 100).candles})
    provider.quotes.return_value = {}
    clock = [START + timedelta(days=1)]
    job = EquityBarJob(
        settings=EquityBarSettings(enabled=True, symbols=("TEST",)),
        driver=driver,
        history_loader=loader,
        provider=provider,
        cache=LiveDataCache(),
        calendar=MarketCalendar(),
        clock=lambda: clock[0],
    )
    assert await job.run_once() == 0
    driver.on_bar.assert_not_called()
    clock[0] = clock[0].replace(hour=0)
    before = loader.await_count
    assert await job.run_once() == 0 and loader.await_count == before
    await job.start()
    await job.stop()
