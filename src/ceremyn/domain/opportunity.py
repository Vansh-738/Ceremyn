"""A live pattern occurrence ranked by its own historical track record.

Still purely descriptive, still no path to the OMS -- see ARCHITECTURE_DECISIONS.md /
ROADMAP_V2.md §3.8: an Opportunity is "worth a human's or the LLM's attention," never
an obligation to trade. Distinct from `Pattern`: a `Pattern` is any historical
occurrence; an `Opportunity` is specifically a *live* (latest-bar) occurrence that
already cleared a minimum-evidence bar, carrying its own backtested hit rate.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.enums import AssetClass, PatternDirection
from ceremyn.domain.market_data import _require_aware


class Opportunity(BaseModel):
    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    asset_class: AssetClass
    pattern_name: str = Field(min_length=1)
    direction: PatternDirection
    detected_at: datetime
    source: str = Field(min_length=1)
    occurrences: int = Field(ge=0)
    hit_rate: float = Field(ge=0.0, le=1.0)
    average_forward_return_pct: float
    forward_days: int = Field(gt=0)

    _aware = field_validator("detected_at")(_require_aware)

    @property
    def edge_score(self) -> float:
        """Transparent ranking key: hit rate weighted by the size of the
        historical average move. Not a prediction -- a sort key, nothing more."""
        return self.hit_rate * abs(self.average_forward_return_pct)
