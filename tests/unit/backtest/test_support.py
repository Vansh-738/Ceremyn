from datetime import UTC, datetime
from decimal import Decimal

from alphaquant.backtest.engine import BacktestConfig, BacktestEngine
from alphaquant.backtest.events import CandleEvent, MarketSignalEvent, QuoteEvent
from alphaquant.backtest.fills import ExecutionContext, terminal_status
from alphaquant.backtest.metrics import compute_statistics
from alphaquant.backtest.montecarlo import MonteCarloSimulator
from alphaquant.backtest.slippage import FixedBpsSlippageModel, NoSlippageModel
from alphaquant.backtest.statistics import EquityPoint
from alphaquant.domain import Candle, Quote, StrategyDefinition
from alphaquant.domain.enums import OrderStatus, Side, TimeFrame
from alphaquant.risk import RiskEngine
from tests.unit.backtest.helpers import TestBacktestStrategy, make_chain, make_contract


def test_engine_processes_quote_candle_and_market_signal_events(
    risk_engine: RiskEngine,
    strategy_definition: StrategyDefinition,
    strategy: TestBacktestStrategy,
) -> None:
    engine = BacktestEngine(
        strategy=strategy,
        definition=strategy_definition,
        risk_engine=risk_engine,
        config=BacktestConfig(),
    )
    timestamp = datetime(2026, 7, 14, 4, 30, tzinfo=UTC)
    contract = make_contract()
    quote = Quote(
        tradingsymbol=contract.tradingsymbol,
        timestamp=timestamp,
        last_price=Decimal("100"),
        bid=Decimal("99"),
        ask=Decimal("101"),
        volume=10,
    )
    candle = Candle(
        tradingsymbol=contract.tradingsymbol,
        timeframe=TimeFrame.MINUTE,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=10,
    )

    engine.process_event(QuoteEvent(timestamp=timestamp, quote=quote))
    engine.process_event(CandleEvent(timestamp=timestamp, candle=candle))
    engine.process_event(MarketSignalEvent(timestamp=timestamp, name="note"))

    assert engine.quotes[contract.tradingsymbol].last_price == Decimal("100")
    assert engine.candles[contract.tradingsymbol].close == Decimal("100")


def test_execution_context_and_terminal_status_fallbacks(timestamp_one: datetime) -> None:
    contract = make_contract()
    chain = make_chain(
        timestamp=timestamp_one,
        last_price="100",
        bid="99",
        ask="101",
        contract=contract,
    )
    context = ExecutionContext(timestamp=timestamp_one, chain=chain)

    assert context.quote_for(contract.tradingsymbol) is not None
    assert context.quote_for("UNKNOWN") is None
    assert context.candle_for(contract.tradingsymbol) is None
    assert terminal_status(0) is OrderStatus.FILLED
    assert terminal_status(1) is OrderStatus.PARTIALLY_FILLED


def test_slippage_models_apply_expected_prices() -> None:
    fixed = FixedBpsSlippageModel(Decimal("10"))
    no_slippage = NoSlippageModel()

    assert no_slippage.apply(side=Side.BUY, reference_price=Decimal("100")) == Decimal("100")
    assert fixed.apply(side=Side.BUY, reference_price=Decimal("100")) == Decimal("100.10")
    assert fixed.apply(side=Side.SELL, reference_price=Decimal("100")) < Decimal("100")


def test_metrics_and_montecarlo_cover_empty_and_nonempty_paths() -> None:
    empty_stats = compute_statistics(
        equity_curve=(),
        closed_trades=(),
        initial_cash=Decimal("100000"),
    )
    assert empty_stats.total_return == 0.0

    points = (
        EquityPoint(
            timestamp=datetime(2026, 7, 14, 4, 20, tzinfo=UTC),
            cash=Decimal("100000"),
            equity=Decimal("100000"),
            drawdown=Decimal("0"),
        ),
    )
    single_stats = compute_statistics(
        equity_curve=points,
        closed_trades=(),
        initial_cash=Decimal("100000"),
    )
    assert single_stats.sharpe == 0.0
    assert single_stats.average_holding_time_hours == 0.0

    empty_mc = MonteCarloSimulator().run(equity_curve=points)
    assert empty_mc.simulations == ()

    richer_points = (
        *points,
        EquityPoint(
            timestamp=datetime(2026, 7, 15, 4, 20, tzinfo=UTC),
            cash=Decimal("100000"),
            equity=Decimal("90000"),
            drawdown=Decimal("10000"),
        ),
        EquityPoint(
            timestamp=datetime(2026, 7, 16, 4, 20, tzinfo=UTC),
            cash=Decimal("100000"),
            equity=Decimal("95000"),
            drawdown=Decimal("5000"),
        ),
    )
    monte_carlo = MonteCarloSimulator().run(
        equity_curve=richer_points,
        iterations=25,
        ruin_threshold=Decimal("95000"),
        seed=5,
    )

    assert len(monte_carlo.simulations) == 25
    assert monte_carlo.probability_of_ruin >= 0.0
