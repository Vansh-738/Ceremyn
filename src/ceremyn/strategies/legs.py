"""Declarative leg selection: a strategy describes *what* leg it wants, not how to find it.

Shared by the multi-leg engine (`multi_leg.py`) so new strategies configure leg shape instead
of re-implementing chain lookups.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ceremyn.domain import ChainEntry, OptionChainSnapshot, OptionType, Side, SignalLeg
from ceremyn.strategies.common import find_atm, find_by_delta


class LegSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_type: OptionType
    side: Side
    selection: Literal["delta", "atm"]
    target_delta: float | None = Field(default=None, gt=0, lt=0.5)
    lots_multiplier: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def _delta_required_for_delta_selection(self) -> "LegSpec":
        if self.selection == "delta" and self.target_delta is None:
            raise ValueError("target_delta is required when selection == 'delta'")
        return self


def resolve_leg(chain: OptionChainSnapshot, spec: LegSpec) -> ChainEntry | None:
    """The chain entry `spec` describes, or None if it can't be found."""
    if spec.selection == "delta":
        assert spec.target_delta is not None  # enforced by the validator above
        return find_by_delta(chain, spec.option_type, spec.target_delta)
    return find_atm(chain, spec.option_type)


def resolve_legs(
    chain: OptionChainSnapshot, specs: tuple[LegSpec, ...], lots: int
) -> tuple[SignalLeg, ...] | None:
    """Every leg `specs` describes, scaled by `lots`; None if any leg can't be found
    (a degenerate chain — the caller skips entry rather than trading a partial structure)."""
    resolved: list[SignalLeg] = []
    for spec in specs:
        entry = resolve_leg(chain, spec)
        if entry is None:
            return None
        resolved.append(
            SignalLeg(contract=entry.contract, side=spec.side, lots=lots * spec.lots_multiplier)
        )
    return tuple(resolved)
