from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel

from alphaquant.domain import (
    ChainEntry,
    Exchange,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Quote,
    Side,
    Signal,
    SignalLeg,
    StrategyDefinition,
)
from alphaquant.domain.enums import SignalAction
from alphaquant.strategies import Strategy, StrategyContext
from alphaquant.strategies.registry import register


class TestStrategyParams(BaseModel):
    lots: int = 1


@register("test_backtest_strategy")
class TestBacktestStrategy(Strategy[TestStrategyParams]):
    __test__ = False
    params_model = TestStrategyParams
    strategy_type = "test_backtest_strategy"

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        contract = ctx.chain.entries[0].contract
        if not ctx.has_open_position:
            return [
                self.emit(
                    ctx,
                    signal_type=SignalAction.ENTER,
                    legs=(SignalLeg(contract=contract, side=Side.BUY, lots=self.params.lots),),
                    reason="enter long",
                )
            ]
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.EXIT,
                legs=(SignalLeg(contract=contract, side=Side.SELL, lots=self.params.lots),),
                reason="exit long",
            )
        ]


def make_contract(
    *,
    symbol: str = "NIFTY26JUL25000CE",
    expiry: date | None = None,
    strike: str = "25000",
) -> OptionContract:
    return OptionContract(
        tradingsymbol=symbol,
        exchange=Exchange.NFO,
        underlying="NIFTY",
        expiry=expiry or date(2026, 7, 30),
        strike=Decimal(strike),
        option_type=OptionType.CALL,
        lot_size=25,
    )


def make_chain(
    *,
    timestamp: datetime,
    last_price: str,
    bid: str,
    ask: str,
    volume: int = 100,
    contract: OptionContract | None = None,
) -> OptionChainSnapshot:
    option = contract or make_contract()
    quote = Quote(
        tradingsymbol=option.tradingsymbol,
        timestamp=timestamp,
        last_price=Decimal(last_price),
        bid=Decimal(bid),
        ask=Decimal(ask),
        volume=volume,
        open_interest=500,
    )
    return OptionChainSnapshot(
        underlying=option.underlying,
        expiry=option.expiry,
        spot=Decimal("25000"),
        timestamp=timestamp,
        entries=(ChainEntry(contract=option, quote=quote),),
    )


def make_strategy_definition() -> StrategyDefinition:
    return StrategyDefinition(
        id="test_backtest_strategy",
        strategy_type="test_backtest_strategy",
        name="Test Backtest Strategy",
        version="1",
        underlyings=("NIFTY",),
        params={"lots": 1},
    )


def make_timestamp_one() -> datetime:
    return datetime(2026, 7, 14, 4, 20, tzinfo=UTC)


def make_timestamp_two() -> datetime:
    return datetime(2026, 7, 14, 5, 20, tzinfo=UTC)
