"""Option greeks value object.

Floats by design: greeks come out of the numerical kernel (NumPy/SciPy) and are
analytics, never money. Monetary amounts elsewhere in the domain use Decimal.
"""

from pydantic import BaseModel, ConfigDict, Field


class Greeks(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta: float = Field(ge=-1.0, le=1.0)
    gamma: float = Field(ge=0)
    theta: float  # typically negative for long options (per calendar day)
    vega: float = Field(ge=0)  # per 1 vol point
    rho: float
    iv: float | None = Field(default=None, gt=0, lt=5.0)  # annualized, e.g. 0.14 = 14%
