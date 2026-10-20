from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.backtest.commission import IndianCostModel
from ceremyn.backtest.engine import BacktestEngine
from ceremyn.backtest.events import BarEvent
from ceremyn.domain import (
    Candle,
    EquityInstrument,
    Exchange,
    Pattern,
    StrategyDefinition,
    TimeFrame,
)
from ceremyn.domain.enums import PatternDirection, Side
from ceremyn.risk import RiskEngine
from ceremyn.strategies import create
from ceremyn.strategies.bars import BarContext
from tests.unit.oms.conftest import permissive_settings

START = datetime(2026, 7, 13, 9, 59, tzinfo=UTC)
INSTRUMENT = EquityInstrument(tradingsymbol="TEST", underlying="TEST", exchange=Exchange.NSE)


def context(day: int, open_price: int, close: int, *, bullish: bool = False) -> BarContext:
    at = START + timedelta(days=day)
    return BarContext(
        as_of=at,
        instrument=INSTRUMENT,
        candles=(
            Candle(
                tradingsymbol="TEST",
                timestamp=at,
                timeframe=TimeFrame.DAY,
                open=Decimal(open_price),
                close=Decimal(close),
                high=Decimal(max(open_price, close)),
                low=Decimal(min(open_price, close)),
                volume=10000,
            ),
        ),
        patterns=(
            Pattern(
                name="test",
                source="fixture",
                tradingsymbol="TEST",
                detected_at=at,
                direction=PatternDirection.BULLISH,
            ),
        )
        if bullish
        else (),
    )


def engine() -> BacktestEngine:
    definition = StrategyDefinition(
        id="equity", strategy_type="equity_pattern", name="Equity", underlyings=("TEST",)
    )
    return BacktestEngine(
        strategy=create(definition),
        definition=definition,
        risk_engine=RiskEngine(permissive_settings()),
    )


def test_close_signal_waits_for_next_open_and_target_exits_next_bar() -> None:
    runner = engine()
    for day, opening, closing, bullish in [(0, 100, 100, True), (1, 102, 120, False)]:
        ctx = context(day, opening, closing, bullish=bullish)
        runner.process_event(BarEvent(timestamp=ctx.as_of, context=ctx))
        if day == 0:
            assert not runner.portfolio.snapshot().positions
            assert runner.pending_orders["equity"]
    assert runner.portfolio.snapshot().positions[0].avg_price > 102
    ctx = context(2, 118, 120)
    runner.process_event(BarEvent(timestamp=ctx.as_of, context=ctx))
    assert len(runner.portfolio.closed_trades) == 1
    trade = runner.portfolio.closed_trades[0]
    assert trade.exit_price < 118
    assert trade.costs > 15
    assert len(runner.risk_decisions) == 2


def test_risk_rejection_and_bearish_pattern_cannot_open_short() -> None:
    runner = engine()
    ctx = context(0, 100, 100, bullish=True)
    bearish = ctx.patterns[0].model_copy(update={"direction": PatternDirection.BEARISH})
    ctx = ctx.model_copy(update={"patterns": (bearish,)})
    runner.process_event(BarEvent(timestamp=ctx.as_of, context=ctx))
    assert not runner.pending_orders
    settings = permissive_settings()
    settings.risk.position.max_lots_per_signal = 1
    runner.risk_engine = RiskEngine(settings)
    ctx = context(1, 100, 100, bullish=True)
    runner.process_event(BarEvent(timestamp=ctx.as_of, context=ctx))
    assert not runner.risk_decisions[-1].approved
    assert not runner.pending_orders


def test_context_rejects_future_evidence() -> None:
    ctx = context(0, 100, 100, bullish=True)
    data = ctx.model_dump()
    data["patterns"][0]["detected_at"] = START + timedelta(days=1)
    with pytest.raises(ValidationError, match="future"):
        BarContext.model_validate(data)


def test_delivery_costs_and_dp_once_per_symbol_day() -> None:
    costs = IndianCostModel()
    buy = costs.calculate_for(
        instrument=INSTRUMENT, timestamp=START, side=Side.BUY, quantity=100, price=Decimal(1000)
    )
    sell = costs.calculate_for(
        instrument=INSTRUMENT, timestamp=START, side=Side.SELL, quantity=100, price=Decimal(1000)
    )
    again = costs.calculate_for(
        instrument=INSTRUMENT, timestamp=START, side=Side.SELL, quantity=1, price=Decimal(1000)
    )
    assert buy.stt == 100 and buy.stamp_duty == 15 and buy.brokerage == 0
    assert sell.depository == Decimal("15.34") and again.depository == 0
    assert buy.total == Decimal("118.74")
