"""Corporate actions: dividends, splits, and bonus issues on an equity/ETF.

Pure record of an announced action against a tradingsymbol -- consumers (e.g. a
future price-adjustment pass over stored candles) decide what to do with it.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CorporateActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    BONUS = "BONUS"


class CorporateAction(BaseModel):
    """One announced corporate action on a single tradingsymbol.

    `ratio` is `new units / old units` (e.g. `2` for a 2-for-1 split, `1.5` for
    a 3:2 bonus) -- required for SPLIT/BONUS, absent for DIVIDEND.
    `dividend_amount` is the per-share cash amount -- required for DIVIDEND,
    absent for SPLIT/BONUS.
    """

    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    action_type: CorporateActionType
    ex_date: date
    ratio: Decimal | None = Field(default=None, gt=0)
    dividend_amount: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_fields_match_type(self) -> "CorporateAction":
        if self.action_type is CorporateActionType.DIVIDEND:
            if self.dividend_amount is None:
                raise ValueError("DIVIDEND requires dividend_amount")
            if self.ratio is not None:
                raise ValueError("DIVIDEND must not set ratio")
        else:
            if self.ratio is None:
                raise ValueError(f"{self.action_type} requires ratio")
            if self.dividend_amount is not None:
                raise ValueError(f"{self.action_type} must not set dividend_amount")
        return self
