"""Financial statements dated by when they became public, including revisions."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.domain.market_data import _require_aware


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    period_type: Literal["annual", "quarter"]
    period_end: date
    published_at: datetime
    source: str = Field(min_length=1)
    revenue: Decimal | None = None
    net_income: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    total_assets: Decimal | None = Field(default=None, ge=0)
    total_debt: Decimal | None = Field(default=None, ge=0)
    current_assets: Decimal | None = Field(default=None, ge=0)
    current_liabilities: Decimal | None = Field(default=None, ge=0)
    shares_outstanding: Decimal | None = Field(default=None, gt=0)
    promoter_pledge_pct: Decimal | None = Field(default=None, ge=0, le=100)

    _aware = field_validator("published_at")(_require_aware)

    @model_validator(mode="after")
    def validate_publication(self) -> Self:
        if self.published_at.date() < self.period_end:
            raise ValueError("publication predates the reporting period")
        return self


class FundamentalScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: datetime
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    checks_missing: tuple[str, ...]
    earnings_yield: Decimal | None
    debt_to_assets: Decimal | None
    red_flags: tuple[str, ...]
    source: str

    _aware = field_validator("as_of")(_require_aware)

    @property
    def checks_run(self) -> int:
        return len(self.checks_passed) + len(self.checks_failed)
