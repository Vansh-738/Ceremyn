"""Feature output value objects: FeatureValue and the immutable FeatureSet."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware

# A feature's value is a scalar: a number, a categorical label (e.g. market regime),
# or None when it is not computable for the given context.
FeatureScalar = float | int | str | None


class FeatureValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    value: FeatureScalar = None
    as_of: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware = field_validator("as_of")(_require_aware)

    @property
    def is_null(self) -> bool:
        return self.value is None

    def as_float(self) -> float | None:
        if isinstance(self.value, bool):  # guard: bool is an int subclass
            return float(self.value)
        if isinstance(self.value, int | float):
            return float(self.value)
        return None


class FeatureSet(BaseModel):
    """An immutable bundle of computed features for one context."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    underlying: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    context_fingerprint: str = Field(min_length=1)
    values: dict[str, FeatureValue] = Field(default_factory=dict)

    _aware = field_validator("as_of")(_require_aware)

    def get(self, name: str) -> FeatureValue | None:
        return self.values.get(name)

    def numeric(self, name: str) -> float | None:
        """The feature's numeric value, or None if absent/null/non-numeric."""
        found = self.values.get(name)
        return found.as_float() if found is not None else None

    def require(self, name: str) -> FeatureValue:
        """Fetch a feature, raising KeyError if it was not computed."""
        try:
            return self.values[name]
        except KeyError as exc:
            raise KeyError(f"feature {name!r} not in this FeatureSet") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))
