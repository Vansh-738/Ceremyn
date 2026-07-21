"""Bear call spread: a name-enforcing preset over `vertical_spread.py`.

Sell a call nearer the money, buy a call further OTM (`short_delta > long_delta`) — a
defined-risk credit spread that profits while the underlying stays below the short strike.
Reuses `VerticalSpreadParams`'s leg/entry/exit/adjustment logic entirely; only fixes
`option_type=CALL` and enforces the credit-spread delta ordering the name promises.
"""

from pydantic import model_validator

from ceremyn.domain import OptionType, Signal
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.multi_leg import drive
from ceremyn.strategies.registry import register
from ceremyn.strategies.vertical_spread import VerticalSpreadParams


class BearCallSpreadParams(VerticalSpreadParams):
    option_type: OptionType = OptionType.CALL

    @model_validator(mode="after")
    def _fixed_call_credit_shape(self) -> "BearCallSpreadParams":
        if self.option_type is not OptionType.CALL:
            raise ValueError("bear call spread requires option_type=CALL")
        if self.short_delta <= self.long_delta:
            raise ValueError(
                "bear call spread requires short_delta > long_delta (credit spread: sell nearer "
                "the money, buy further OTM)"
            )
        return self


@register("bear_call_spread")
class BearCallSpread(Strategy[BearCallSpreadParams]):
    params_model = BearCallSpreadParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return drive(self, ctx, self.params)
