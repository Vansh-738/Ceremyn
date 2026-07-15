"""Bull put spread: a name-enforcing preset over `vertical_spread.py`.

Sell a put nearer the money, buy a put further OTM (`short_delta > long_delta`) — a defined-risk
credit spread that profits while the underlying stays above the short strike. Reuses
`VerticalSpreadParams`'s leg/entry/exit/adjustment logic entirely; only fixes `option_type=PUT`
and enforces the credit-spread delta ordering the name promises.
"""

from pydantic import model_validator

from alphaquant.domain import OptionType, Signal
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.multi_leg import drive
from alphaquant.strategies.registry import register
from alphaquant.strategies.vertical_spread import VerticalSpreadParams


class BullPutSpreadParams(VerticalSpreadParams):
    option_type: OptionType = OptionType.PUT

    @model_validator(mode="after")
    def _fixed_put_credit_shape(self) -> "BullPutSpreadParams":
        if self.option_type is not OptionType.PUT:
            raise ValueError("bull put spread requires option_type=PUT")
        if self.short_delta <= self.long_delta:
            raise ValueError(
                "bull put spread requires short_delta > long_delta (credit spread: sell nearer "
                "the money, buy further OTM)"
            )
        return self


@register("bull_put_spread")
class BullPutSpread(Strategy[BullPutSpreadParams]):
    params_model = BullPutSpreadParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return drive(self, ctx, self.params)
