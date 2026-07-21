from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.config import Settings
from ceremyn.domain import Order
from ceremyn.domain.enums import OrderType, Side
from ceremyn.paper.broker import PaperBrokerConfig
from ceremyn.paper.engine import PaperEngineConfig, PaperTradingEngine
from ceremyn.paper.events import MarketTick
from ceremyn.risk import RiskEngine
from ceremyn.strategies import Strategy
from tests.unit.backtest.helpers import (
    TestBacktestStrategy,
    make_chain,
    make_contract,
    make_strategy_definition,
)

# Ticks are 5 seconds apart; the market is open at this instant (Tue 2026-07-14 ~09:50 IST).
TICK_ZERO = datetime(2026, 7, 14, 4, 20, tzinfo=UTC)


def make_tick(index: int, price: str, *, volume: int = 1000) -> MarketTick:
    ts = TICK_ZERO + timedelta(seconds=5 * index)
    last = Decimal(price)
    chain = make_chain(
        timestamp=ts,
        last_price=price,
        bid=str(last - Decimal("0.5")),
        ask=str(last + Decimal("0.5")),
        volume=volume,
    )
    return MarketTick(as_of=ts, underlying="NIFTY", chain=chain)


def price_path_ticks(prices: Sequence[str]) -> list[MarketTick]:
    return [make_tick(i, price) for i, price in enumerate(prices)]


def make_market_order(*, side: Side = Side.BUY, quantity: int = 25) -> Order:
    from ceremyn.domain.enums import OrderStatus

    return Order(
        contract=make_contract(),
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        status=OrderStatus.VALIDATED,
        created_at=TICK_ZERO,
    )


def permissive_settings() -> Settings:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 100
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    return settings


@pytest.fixture
def risk_engine() -> RiskEngine:
    return RiskEngine(permissive_settings())


@pytest.fixture
def strategy() -> Strategy[object]:
    return TestBacktestStrategy(make_strategy_definition())


def make_engine(
    risk_engine: RiskEngine,
    strategy: Strategy[object],
    *,
    latency_seconds: float = 1.0,
    compute_features: bool = False,
    reconcile_each_tick: bool = True,
    initial_cash: str = "1000000",
) -> PaperTradingEngine:
    config = PaperEngineConfig(
        portfolio=PortfolioConfig(initial_cash=Decimal(initial_cash)),
        broker=PaperBrokerConfig(latency_seconds=latency_seconds),
        compute_features=compute_features,
        reconcile_each_tick=reconcile_each_tick,
    )
    return PaperTradingEngine(strategies=[strategy], risk_engine=risk_engine, config=config)


class ListFeed:
    def __init__(self, ticks: list[MarketTick]) -> None:
        self._ticks = ticks

    def stream(self) -> list[MarketTick]:
        return self._ticks
