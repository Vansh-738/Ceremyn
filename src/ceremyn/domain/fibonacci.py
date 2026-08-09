"""Fibonacci retracement levels spanning the most recent confirmed swing leg.

Doesn't fit `Pattern` (no single-bar directional "fire") or a scalar `Feature`
(the output is several price levels, not one number) -- so it gets its own small
value object. See `ceremyn.patterns.fibonacci` for how it is computed.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.enums import PatternDirection
from ceremyn.domain.market_data import _require_aware


class FibonacciLevels(BaseModel):
    """`direction` is BULLISH when the leg ran from a swing low up to a swing
    high (levels are pullback *support* candidates below the high) and BEARISH
    when it ran from a swing high down to a swing low (levels are bounce
    *resistance* candidates above the low)."""

    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    as_of: datetime
    direction: PatternDirection
    swing_start: Decimal  # the leg's origin price -- 0% retracement
    swing_start_at: datetime
    swing_end: Decimal  # the leg's most recent extreme price -- 100% retracement
    swing_end_at: datetime
    level_23_6: Decimal
    level_38_2: Decimal
    level_50_0: Decimal
    level_61_8: Decimal
    level_78_6: Decimal
    # The 50%-61.8% zone -- the "Golden Pocket", statistically the most robust
    # region for a pulling-back move to bounce and resume its primary trend.
    golden_pocket_low: Decimal
    golden_pocket_high: Decimal

    _aware_as_of = field_validator("as_of")(_require_aware)
    _aware_start = field_validator("swing_start_at")(_require_aware)
    _aware_end = field_validator("swing_end_at")(_require_aware)
