"""Multi-expiry chain tracking (M14): lets a strategy see other expiries' chains at the same
instant via StrategyContext.other_expiries — needed for calendar spreads. Verifies both the
low-level tracking in BacktestEngine and a full calendar-spread trade end to end.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from alphaquant.backtest.engine import BacktestConfig, BacktestEngine
from alphaquant.backtest.events import OptionChainEvent
from alphaquant.backtest.runner import BacktestRunner
from alphaquant.config import Settings
from alphaquant.domain import OptionChainSnapshot, Signal, StrategyDefinition
from alphaquant.risk import RiskEngine
from alphaquant.strategies import Strategy, StrategyContext, create
from alphaquant.strategies.registry import register
from tests.unit.strategies.conftest import EXPIRY, NOW, enriched_chain, make_definition

FAR_EXPIRY = date(2025, 8, 26)


class _CapturingParams(BaseModel):
    pass


@register("_capturing_test_strategy")
class _CapturingStrategy(Strategy[_CapturingParams]):
    params_model = _CapturingParams

    def __init__(self, definition: StrategyDefinition) -> None:
        super().__init__(definition)
        self.seen_other_expiries: list[Mapping[date, OptionChainSnapshot]] = []

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        self.seen_other_expiries.append(ctx.other_expiries)
        return []


def _permissive_risk_engine() -> RiskEngine:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 10
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    return RiskEngine(settings)


class TestLatestChainsTracking:
    def test_tracks_one_chain_per_expiry(self) -> None:
        definition = StrategyDefinition(
            id="capture",
            strategy_type="_capturing_test_strategy",
            name="capture",
            underlyings=("NIFTY",),
        )
        strategy = create(definition)
        engine = BacktestEngine(
            strategy=strategy, definition=definition, risk_engine=_permissive_risk_engine()
        )
        near = enriched_chain(expiry=EXPIRY, now=NOW)
        far = enriched_chain(expiry=FAR_EXPIRY, now=NOW)

        engine.process_event(OptionChainEvent(timestamp=NOW, chain=near))
        engine.process_event(OptionChainEvent(timestamp=NOW, chain=far))

        assert engine.latest_chains == {EXPIRY: near, FAR_EXPIRY: far}
        # unchanged single-chain tracking still reflects the most recent event
        assert engine.latest_chain == far

    def test_other_expiries_excludes_the_currently_arriving_chain(self) -> None:
        definition = StrategyDefinition(
            id="capture2",
            strategy_type="_capturing_test_strategy",
            name="capture2",
            underlyings=("NIFTY",),
        )
        strategy = create(definition)
        assert isinstance(strategy, _CapturingStrategy)
        engine = BacktestEngine(
            strategy=strategy, definition=definition, risk_engine=_permissive_risk_engine()
        )
        near = enriched_chain(expiry=EXPIRY, now=NOW)
        far = enriched_chain(expiry=FAR_EXPIRY, now=NOW)

        engine.process_event(OptionChainEvent(timestamp=NOW, chain=far))
        engine.process_event(OptionChainEvent(timestamp=NOW, chain=near))

        assert len(strategy.seen_other_expiries) == 2
        # first call (far arrives): nothing else known yet
        assert strategy.seen_other_expiries[0] == {}
        # second call (near arrives): far is now known, and near itself is excluded
        assert strategy.seen_other_expiries[1] == {FAR_EXPIRY: far}


def _with_distinct_tradingsymbols(chain: OptionChainSnapshot, suffix: str) -> OptionChainSnapshot:
    """`enriched_chain()`'s underlying contract builder (tests/unit/domain/conftest.py::
    make_contract) hardcodes one fixed tradingsymbol format regardless of the `expiry` it's
    given -- a pre-M14 simplification nothing needed until calendar spreads. Position/order
    tracking is keyed by tradingsymbol, so two same-strike different-expiry legs need visibly
    distinct symbols to be treated as separate instruments; rewritten locally here rather than
    touching the widely-shared helper."""
    new_entries = tuple(
        entry.model_copy(
            update={
                "contract": entry.contract.model_copy(
                    update={"tradingsymbol": f"{entry.contract.tradingsymbol}_{suffix}"}
                )
            }
        )
        for entry in chain.entries
    )
    return chain.model_copy(update={"entries": new_entries})


def test_calendar_spread_enters_through_a_full_backtest() -> None:
    """End-to-end: BacktestRunner drives a real CalendarSpread through two expiries' chain
    events (far arriving first, matching the ordering a real multi-expiry dataset would need)
    and the risk engine approves and fills both correlated single-leg orders."""
    near = enriched_chain(expiry=EXPIRY, now=NOW)
    far = _with_distinct_tradingsymbols(enriched_chain(expiry=FAR_EXPIRY, now=NOW), "FAR")
    definition = make_definition("calendar_spread", near_expiry_dte_max=10)
    strategy = create(definition)
    runner = BacktestRunner(
        strategy=strategy,
        definition=definition,
        risk_engine=_permissive_risk_engine(),
        config=BacktestConfig(),
    )

    report = runner.run(
        [
            OptionChainEvent(timestamp=NOW, chain=far),
            OptionChainEvent(timestamp=NOW, chain=near),
        ]
    )

    assert report.final_portfolio.positions  # the calendar spread's legs were actually filled
