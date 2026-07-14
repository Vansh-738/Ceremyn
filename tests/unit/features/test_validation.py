from datetime import UTC, datetime

import pytest

from alphaquant.features.models import FeatureValue
from alphaquant.features.validation import (
    Bounds,
    Categorical,
    FeatureValidationError,
    FeatureValidator,
)

AS_OF = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)


def fv(name: str, value: object) -> FeatureValue:
    return FeatureValue(name=name, version="1", value=value, as_of=AS_OF)  # type: ignore[arg-type]


class TestBounds:
    def test_within_bounds_ok(self) -> None:
        Bounds(0.0, 100.0).check("rsi", 50.0)

    def test_below_minimum_raises(self) -> None:
        with pytest.raises(FeatureValidationError, match="below minimum"):
            Bounds(0.0, 100.0).check("rsi", -1.0)

    def test_above_maximum_raises(self) -> None:
        with pytest.raises(FeatureValidationError, match="above maximum"):
            Bounds(0.0, 100.0).check("rsi", 101.0)

    def test_non_number_raises(self) -> None:
        with pytest.raises(FeatureValidationError, match="expected a number"):
            Bounds(0.0).check("x", "not a number")

    def test_bool_rejected_as_number(self) -> None:
        with pytest.raises(FeatureValidationError, match="expected a number"):
            Bounds(0.0).check("x", True)


class TestCategorical:
    def test_allowed_value_ok(self) -> None:
        Categorical(["a", "b"]).check("regime", "a")

    def test_disallowed_raises(self) -> None:
        with pytest.raises(FeatureValidationError, match="not in allowed set"):
            Categorical(["a", "b"]).check("regime", "c")


class TestValidator:
    def test_validates_registered_constraint(self) -> None:
        validator = FeatureValidator()
        validator.set_constraint("rsi_14", Bounds(0.0, 100.0))
        assert validator.has_constraint("rsi_14")
        with pytest.raises(FeatureValidationError):
            validator.validate(fv("rsi_14", 200.0))

    def test_null_always_passes(self) -> None:
        validator = FeatureValidator()
        validator.set_constraint("rsi_14", Bounds(0.0, 100.0))
        assert validator.validate(fv("rsi_14", None)).is_null

    def test_unconstrained_feature_passes(self) -> None:
        validator = FeatureValidator()
        assert validator.validate(fv("anything", 999.0)).value == 999.0
