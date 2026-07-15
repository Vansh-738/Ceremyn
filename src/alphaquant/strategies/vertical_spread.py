"""Vertical spread: a generic, configurable 2-leg credit or debit spread on one option type.

Selling the nearer-the-money leg and buying the further-OTM leg (`short_delta > long_delta`)
produces a credit spread — bull put when `option_type=PUT`, bear call when `option_type=CALL`.
Reversing the deltas produces the debit-spread mirror (bull call / bear put) using the same
math; the shared exit evaluator (`rules.evaluate_exit`) is P&L-sign-safe for both.
`bull_put_spread.py`/`bear_call_spread.py` are thin, name-enforcing presets over this class.
"""

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.domain import OptionType, Side, Signal
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.legs import LegSpec
from alphaquant.strategies.multi_leg import drive
from alphaquant.strategies.registry import register
from alphaquant.strategies.rules import AdjustmentRule, EntryFilter, ExitRule


class VerticalSpreadParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_type: OptionType = OptionType.PUT
    short_delta: float = Field(default=0.30, gt=0, lt=0.5)
    long_delta: float = Field(default=0.15, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    min_iv_rank: float | None = Field(default=None, ge=0, le=100)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=45, ge=0)
    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=100.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)
    adjustment_enabled: bool = False
    adjustment_breach_delta: float = Field(default=0.35, gt=0, lt=1.0)
    adjustment_roll_to_delta: float = Field(default=0.20, gt=0, lt=0.5)

    @property
    def legs(self) -> tuple[LegSpec, ...]:
        return (
            LegSpec(
                option_type=self.option_type,
                side=Side.SELL,
                selection="delta",
                target_delta=self.short_delta,
            ),
            LegSpec(
                option_type=self.option_type,
                side=Side.BUY,
                selection="delta",
                target_delta=self.long_delta,
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


@register("vertical_spread")
class VerticalSpread(Strategy[VerticalSpreadParams]):
    params_model = VerticalSpreadParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        return drive(self, ctx, self.params)
