"""Jade lizard: a short put plus a call credit spread.

Sized so the combined credit typically exceeds the call spread's width, the structure is
designed to have no upside risk at all (a large rally costs nothing beyond the capped call
spread) -- the trade-off is that the put leg stays naked, so downside risk is uncapped exactly
like short_strangle/short_straddle. Built on the shared declarative multi-leg engine
(`legs.py` + `rules.py` + `multi_leg.py`).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ceremyn.domain import OptionType, Side, Signal
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.legs import LegSpec
from ceremyn.strategies.multi_leg import drive
from ceremyn.strategies.registry import register
from ceremyn.strategies.rules import AdjustmentRule, EntryFilter, ExitRule


class JadeLizardParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    put_delta: float = Field(default=0.25, gt=0, lt=0.5)  # short put -- naked, uncapped downside
    call_short_delta: float = Field(default=0.25, gt=0, lt=0.5)  # short leg of the call spread
    call_long_delta: float = Field(default=0.10, gt=0, lt=0.5)  # long leg, further OTM
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
    def _call_wing_further_out(self) -> "JadeLizardParams":
        if self.call_long_delta >= self.call_short_delta:
            raise ValueError(
                "call_long_delta must be below call_short_delta (long wing further OTM: "
                "credit spread, not a debit spread)"
            )
        return self

    @property
    def legs(self) -> tuple[LegSpec, ...]:
        return (
            LegSpec(
                option_type=OptionType.PUT,
                side=Side.SELL,
                selection="delta",
                target_delta=self.put_delta,
            ),
            LegSpec(
                option_type=OptionType.CALL,
                side=Side.SELL,
                selection="delta",
                target_delta=self.call_short_delta,
            ),
            LegSpec(
                option_type=OptionType.CALL,
                side=Side.BUY,
                selection="delta",
                target_delta=self.call_long_delta,
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


@register("jade_lizard")
class JadeLizard(Strategy[JadeLizardParams]):
    params_model = JadeLizardParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return drive(self, ctx, self.params)
