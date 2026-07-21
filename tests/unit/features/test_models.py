from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ceremyn.features.models import FeatureSet, FeatureValue

AS_OF = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)


def fv(name: str, value: object) -> FeatureValue:
    return FeatureValue(name=name, version="1", value=value, as_of=AS_OF)  # type: ignore[arg-type]


class TestFeatureValue:
    def test_as_float_for_numbers(self) -> None:
        assert fv("x", 5).as_float() == 5.0
        assert fv("x", 2.5).as_float() == 2.5

    def test_as_float_none_for_strings_and_null(self) -> None:
        assert fv("regime", "trending").as_float() is None
        assert fv("x", None).as_float() is None

    def test_bool_not_treated_as_plain_int(self) -> None:
        # bool is an int subclass; as_float still returns a float, is_null stays False.
        assert fv("flag", True).as_float() == 1.0

    def test_is_null(self) -> None:
        assert fv("x", None).is_null is True
        assert fv("x", 0).is_null is False

    def test_naive_as_of_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeatureValue(name="x", version="1", value=1, as_of=datetime(2026, 7, 14, 6, 0))


class TestFeatureSet:
    def _set(self) -> FeatureSet:
        return FeatureSet(
            as_of=AS_OF,
            underlying="NIFTY",
            feature_set_version="v1",
            context_fingerprint="fp",
            values={"pcr": fv("pcr", 1.2), "regime": fv("regime", "trending")},
        )

    def test_get_and_numeric(self) -> None:
        fs = self._set()
        assert fs.get("pcr") is not None
        assert fs.numeric("pcr") == 1.2
        assert fs.numeric("regime") is None  # non-numeric
        assert fs.numeric("absent") is None

    def test_require_raises_for_missing(self) -> None:
        with pytest.raises(KeyError, match="absent"):
            self._set().require("absent")

    def test_names_sorted(self) -> None:
        assert self._set().names == ("pcr", "regime")
