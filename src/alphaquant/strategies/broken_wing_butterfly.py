"""Broken wing butterfly: a butterfly with unequal wing widths, expressed here as three
independent delta targets rather than fixed point widths.

Unlike short_strangle/short_straddle/jade_lizard, every leg is defined-risk (no naked leg at
all) -- the near wing and far wing bracket the short body on both sides, so the maximum loss
is capped by construction rather than by an exit rule catching up after a large move. Built on
the shared declarative multi-leg engine (`legs.py` + `rules.py` + `multi_leg.py`).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaquant.domain import OptionType, Side, Signal
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.legs import LegSpec
from alphaquant.strategies.multi_leg import drive
from alphaquant.strategies.registry import register
from alphaquant.strategies.rules import AdjustmentRule, EntryFilter, ExitRule


class BrokenWingButterflyParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_type: OptionType = OptionType.PUT
    # |delta| rises monotonically toward spot for both option types, so these three
    # targets place the wings correctly regardless of option_type: the near wing (closer
    # to spot, more expensive) partially funds the far wing (further OTM, cheaper),
    # and making the two widths unequal (rather than a symmetric butterfly) is what
    # produces the "broken wing" shape and usually a net credit.
    near_wing_delta: float = Field(default=0.35, gt=0, lt=0.5)
    body_delta: float = Field(default=0.20, gt=0, lt=0.5)
    far_wing_delta: float = Field(default=0.08, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    min_iv_rank: float = Field(default=50.0, ge=0, le=100)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=15, ge=0)
    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=100.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)
    adjustment_enabled: bool = False
    adjustment_breach_delta: float = Field(default=0.35, gt=0, lt=1.0)
    adjustment_roll_to_delta: float = Field(default=0.20, gt=0, lt=0.5)

    @model_validator(mode="after")
    def _wings_bracket_the_body(self) -> "BrokenWingButterflyParams":
        if not (self.far_wing_delta < self.body_delta < self.near_wing_delta):
            raise ValueError(
                "requires far_wing_delta < body_delta < near_wing_delta (both long wings "
                "must sit on opposite sides of the short body, further from spot than it)"
            )
        return self

    @property
    def legs(self) -> tuple[LegSpec, ...]:
        return (
            LegSpec(
                option_type=self.option_type,
                side=Side.BUY,
                selection="delta",
                target_delta=self.near_wing_delta,
            ),
            LegSpec(
                option_type=self.option_type,
                side=Side.SELL,
                selection="delta",
                target_delta=self.body_delta,
                lots_multiplier=2,
            ),
            LegSpec(
                option_type=self.option_type,
                side=Side.BUY,
                selection="delta",
                target_delta=self.far_wing_delta,
            ),
        )

    @property
    def entry(self) -> EntryFilter:
        return EntryFilter(
            min_iv_rank=self.min_iv_rank,
            entry_dte_min=self.entry_dte_min,
            entry_dte_max=self.entry_dte_max,
        )

    @property
    def exit_rule(self) -> ExitRule:
        return ExitRule(
            profit_target_pct=self.profit_target_pct,
            stop_loss_pct=self.stop_loss_pct,
            exit_dte=self.exit_dte,
        )

    @property
    def adjustment(self) -> AdjustmentRule:
        return AdjustmentRule(
            enabled=self.adjustment_enabled,
            breach_delta=self.adjustment_breach_delta,
            roll_to_delta=self.adjustment_roll_to_delta,
        )


@register("broken_wing_butterfly")
class BrokenWingButterfly(Strategy[BrokenWingButterflyParams]):
    params_model = BrokenWingButterflyParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return drive(self, ctx, self.params)
