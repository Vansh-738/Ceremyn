"""Reproducible synthetic scenarios for an interview, never a performance claim."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ceremyn.backtest.events import BarEvent
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.config import Settings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import IST
from ceremyn.domain import (
    Candle,
    EquityInstrument,
    Exchange,
    Pattern,
    StrategyDefinition,
    TimeFrame,
)
from ceremyn.domain.enums import PatternDirection
from ceremyn.research.cross_validation import CrossValidator
from ceremyn.research.dataset import dataset_from_events
from ceremyn.research.experiment_manager import ExperimentManager
from ceremyn.research.experiment_store import JSONExperimentStore
from ceremyn.research.parameter_grid import ParameterGrid
from ceremyn.research.walkforward import WalkForwardLab
from ceremyn.risk import RiskEngine
from ceremyn.strategies import create
from ceremyn.strategies.bars import BarContext


def demo_events() -> tuple[BarEvent, ...]:
    instrument = EquityInstrument(tradingsymbol="DEMO", underlying="DEMO", exchange=Exchange.NSE)
    calendar = MarketCalendar()
    day = datetime(2026, 1, 5, tzinfo=IST).date()
    candles: list[Candle] = []
    events = []
    path = [100, 102, 108, 120, 119, 107, 100, 98, 94, 97, 100, 101]
    for i in range(120):
        while not calendar.is_trading_day(day):
            day += timedelta(days=1)
        at = datetime.combine(day, time(15, 30), tzinfo=IST)
        closing = Decimal(path[i % len(path)])
        opening = candles[-1].close if candles else closing
        candle = Candle(
            tradingsymbol="DEMO",
            timestamp=at,
            timeframe=TimeFrame.DAY,
            open=opening,
            high=max(opening, closing) + 1,
            low=min(opening, closing) - 1,
            close=closing,
            volume=10000,
        )
        candles.append(candle)
        patterns = (
            (
                Pattern(
                    name="synthetic_confirmation",
                    tradingsymbol="DEMO",
                    detected_at=at,
                    direction=PatternDirection.BULLISH,
                    source="explicit synthetic test event",
                ),
            )
            if i % 6 == 0
            else ()
        )
        context = BarContext(
            as_of=at, instrument=instrument, candles=tuple(candles), patterns=patterns
        )
        events.append(BarEvent(timestamp=at, context=context))
        day += timedelta(days=1)
    return tuple(events)


def demo_risk(*, blocked: bool = False) -> RiskEngine:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    # A single-symbol fixture cannot meet a diversified-portfolio concentration rule.
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    if blocked:
        settings.risk.position.max_lots_per_signal = 1
    return RiskEngine(settings)


def export_demo() -> dict[str, Any]:
    events = demo_events()
    cases = []
    for name, stop, blocked in [
        ("Base case", "0.05", False),
        ("Wider stop", "0.10", False),
        ("Risk rejection", "0.05", True),
    ]:
        definition = StrategyDefinition(
            id="interview_equity",
            strategy_type="equity_pattern",
            name=name,
            underlyings=("DEMO",),
            params={"stop_pct": stop},
        )
        runner = BacktestRunner(
            strategy=create(definition),
            definition=definition,
            risk_engine=demo_risk(blocked=blocked),
        )
        report = runner.run(events)
        cases.append(
            {
                "name": name,
                "stop_pct": stop,
                "blocked": blocked,
                "summary": report.performance_report,
                "statistics": report.statistics.model_dump(mode="json"),
                "final_portfolio": report.final_portfolio.model_dump(mode="json"),
                "trades": [
                    {
                        "entry": str(t.entry_price),
                        "exit": str(t.exit_price),
                        "quantity": t.quantity,
                        "gross_pnl": str(t.gross_pnl),
                        "costs": str(t.costs),
                        "opened_at": t.entry_at.isoformat(),
                        "closed_at": t.exit_at.isoformat(),
                    }
                    for t in report.trade_ledger
                ],
                "equity": [point.model_dump(mode="json") for point in report.equity_curve],
                "risk_decisions": len(runner.engine.risk_decisions),
                "risk_rejections": sum(
                    not decision.approved for decision in runner.engine.risk_decisions
                ),
            }
        )
    dataset = dataset_from_events("synthetic_equity_interview", events)
    definition = StrategyDefinition(
        id="validation_demo",
        strategy_type="equity_pattern",
        name="Equity validation",
        underlyings=("DEMO",),
    )
    with TemporaryDirectory() as root:
        manager = ExperimentManager(JSONExperimentStore(Path(root)))
        cv = CrossValidator(manager).rolling(
            definition=definition,
            dataset=dataset,
            risk_engine=demo_risk(),
            train_size=30,
            test_size=15,
        )
        walk = WalkForwardLab(manager).run(
            definition=definition,
            dataset=dataset,
            risk_engine=demo_risk(),
            grid=ParameterGrid(space={"stop_pct": ("0.05", "0.10")}),
            train_size=30,
            validate_size=15,
            test_size=15,
        )
    return {
        "data_kind": "synthetic",
        "instrument": "DEMO",
        "bars": len(events),
        "disclosure": (
            "Synthetic prices and explicit test pattern events. This validates the software "
            "workflow, not investment performance."
        ),
        "dataset_hash": dataset.market_data_version,
        "cases": cases,
        "validation": {
            "cv_folds": cv.fold_count,
            "cv_mean_score": cv.mean_score,
            "walk_forward_windows": len(walk.windows),
            "walk_forward_mean_test_score": walk.mean_test_score,
        },
    }
