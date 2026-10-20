"""Long-only daily pattern strategy. Stops/targets are checked at the close."""

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from ceremyn.domain import Side, Signal, SignalAction, SignalLeg
from ceremyn.domain.enums import PatternDirection
from ceremyn.strategies.bars import BarContext
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.registry import register


class EquityPatternParams(BaseModel):
    allocation: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    max_shares: int = Field(default=10, gt=0)
    stop_pct: Decimal = Field(default=Decimal("0.05"), gt=0, lt=1)
    target_pct: Decimal = Field(default=Decimal("0.15"), gt=0)
    require_fundamentals: bool = False


@register("equity_pattern")
class EquityPatternStrategy(Strategy[EquityPatternParams]):
    """Buy a confirmed bullish pattern; exit on a close-based stop or target."""

    params_model = EquityPatternParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        price = ctx.candles[-1].close
        if price <= 0 or ctx.portfolio is None:
            return []
        symbol = ctx.instrument.tradingsymbol
        positions = [
            p for p in ctx.positions if p.contract.tradingsymbol == symbol and p.quantity > 0
        ]
        if positions:
            position = positions[0]
            change = price / position.avg_price - 1
            if -self.params.stop_pct < change < self.params.target_pct:
                return []
            side, quantity, action = Side.SELL, position.quantity, SignalAction.EXIT
            reason = "close-based stop" if change <= -self.params.stop_pct else "close-based target"
        else:
            if not any(
                p.detected_at == ctx.as_of and p.direction is PatternDirection.BULLISH
                for p in ctx.patterns
            ):
                return []
            if self.params.require_fundamentals and (
                ctx.fundamentals is None
                or ctx.fundamentals.red_flags
                or ctx.fundamentals.checks_run < 6
                or len(ctx.fundamentals.checks_passed) < 4
            ):
                return []
            quantity = min(
                self.params.max_shares,
                int(ctx.portfolio.buying_power * self.params.allocation / price),
            )
            if quantity < 1:
                return []
            side, action, reason = Side.BUY, SignalAction.ENTER, "confirmed bullish pattern"
        return [
            Signal(
                signal_id=uuid5(
                    NAMESPACE_URL,
                    f"ceremyn:{self.definition.id}:{self.definition.version}:{symbol}:{ctx.as_of.isoformat()}:{action.value}",
                ),
                strategy_id=self.definition.id,
                strategy_version=self.definition.version,
                signal_type=action,
                created_at=ctx.as_of,
                market_timestamp=ctx.as_of,
                legs=(SignalLeg(contract=ctx.instrument, side=side, lots=quantity),),
                reason=reason,
                replay_id=f"{self.definition.id}:{symbol}:{ctx.as_of.isoformat()}:{action.value}",
                metadata={
                    "reference_prices": {symbol: str(price)},
                    "execution": {"products": {symbol: "CNC"}},
                },
            )
        ]
