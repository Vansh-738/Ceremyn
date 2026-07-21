from datetime import datetime

from pydantic import BaseModel

from alphaquant.backtest.engine import BacktestEngine
from alphaquant.backtest.events import OptionChainEvent
from alphaquant.domain import Greeks, Signal, StrategyDefinition
from alphaquant.risk import RiskEngine
from alphaquant.strategies import Strategy, StrategyContext
from tests.unit.backtest.helpers import make_chain


class _IVRankSpyParams(BaseModel):
    pass


class _IVRankSpy(Strategy[_IVRankSpyParams]):
    __test__ = False
    strategy_type = "iv_rank_spy"
    params_model = _IVRankSpyParams

    def __init__(self, definition: StrategyDefinition) -> None:
        super().__init__(definition)
        self.seen_iv_ranks: list[float | None] = []

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        self.seen_iv_ranks.append(ctx.iv_rank)
        return []


def _chain_with_atm_iv(*, timestamp: datetime, iv: float):
    chain = make_chain(timestamp=timestamp, last_price="100", bid="99", ask="101")
    entry = chain.entries[0].model_copy(
        update={
            "greeks": Greeks(delta=0.5, gamma=0.01, theta=-1.0, vega=1.0, rho=0.0, iv=iv),
        }
    )
    return chain.model_copy(update={"entries": (entry,)})


def test_iv_rank_is_none_until_enough_history(
    risk_engine: RiskEngine,
    timestamp_one: datetime,
) -> None:
    definition = StrategyDefinition(
        id="iv_rank_spy",
        strategy_type="iv_rank_spy",
        name="IV Rank Spy",
        version="1",
        underlyings=("NIFTY",),
        params={},
    )
    strategy = _IVRankSpy(definition=definition)
    engine = BacktestEngine(strategy=strategy, definition=definition, risk_engine=risk_engine)

    chain = _chain_with_atm_iv(timestamp=timestamp_one, iv=0.20)
    engine.process_event(OptionChainEvent(timestamp=timestamp_one, chain=chain))

    assert strategy.seen_iv_ranks == [None]


def test_iv_rank_reflects_real_history_once_available(
    risk_engine: RiskEngine,
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
    definition = StrategyDefinition(
        id="iv_rank_spy",
        strategy_type="iv_rank_spy",
        name="IV Rank Spy",
        version="1",
        underlyings=("NIFTY",),
        params={},
    )
    strategy = _IVRankSpy(definition=definition)
    engine = BacktestEngine(strategy=strategy, definition=definition, risk_engine=risk_engine)

    # `iv_rank()` needs >=2 prior observations, so the rank only becomes real on
    # the third chain -- exactly mirroring `RestPricePoller`'s own gating.
    low_iv_chain = _chain_with_atm_iv(timestamp=timestamp_one, iv=0.10)
    mid_iv_chain = _chain_with_atm_iv(timestamp=timestamp_two, iv=0.20)
    high_iv_chain = _chain_with_atm_iv(timestamp=timestamp_two, iv=0.30)
    engine.process_event(OptionChainEvent(timestamp=timestamp_one, chain=low_iv_chain))
    engine.process_event(OptionChainEvent(timestamp=timestamp_two, chain=mid_iv_chain))
    engine.process_event(OptionChainEvent(timestamp=timestamp_two, chain=high_iv_chain))

    assert strategy.seen_iv_ranks[0] is None
    assert strategy.seen_iv_ranks[1] is None
    assert strategy.seen_iv_ranks[2] == 100.0
