from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.domain import CorporateAction, CorporateActionType


def test_dividend_requires_amount() -> None:
    with pytest.raises(ValidationError, match="dividend_amount"):
        CorporateAction(
            tradingsymbol="RELIANCE",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2025, 8, 1),
        )


def test_dividend_rejects_ratio() -> None:
    with pytest.raises(ValidationError, match="ratio"):
        CorporateAction(
            tradingsymbol="RELIANCE",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2025, 8, 1),
            dividend_amount=Decimal("8.5"),
            ratio=Decimal("2"),
        )


def test_valid_dividend() -> None:
    action = CorporateAction(
        tradingsymbol="RELIANCE",
        action_type=CorporateActionType.DIVIDEND,
        ex_date=date(2025, 8, 1),
        dividend_amount=Decimal("8.5"),
    )
    assert action.dividend_amount == Decimal("8.5")
    assert action.ratio is None


@pytest.mark.parametrize("action_type", [CorporateActionType.SPLIT, CorporateActionType.BONUS])
def test_split_and_bonus_require_ratio(action_type: CorporateActionType) -> None:
    with pytest.raises(ValidationError, match="ratio"):
        CorporateAction(tradingsymbol="RELIANCE", action_type=action_type, ex_date=date(2025, 8, 1))


@pytest.mark.parametrize("action_type", [CorporateActionType.SPLIT, CorporateActionType.BONUS])
def test_split_and_bonus_reject_dividend_amount(action_type: CorporateActionType) -> None:
    with pytest.raises(ValidationError, match="dividend_amount"):
        CorporateAction(
            tradingsymbol="RELIANCE",
            action_type=action_type,
            ex_date=date(2025, 8, 1),
            ratio=Decimal("2"),
            dividend_amount=Decimal("1"),
        )


def test_valid_split() -> None:
    action = CorporateAction(
        tradingsymbol="RELIANCE",
        action_type=CorporateActionType.SPLIT,
        ex_date=date(2025, 8, 1),
        ratio=Decimal("2"),
    )
    assert action.ratio == Decimal("2")
    assert action.dividend_amount is None


def test_action_is_immutable() -> None:
    action = CorporateAction(
        tradingsymbol="RELIANCE",
        action_type=CorporateActionType.SPLIT,
        ex_date=date(2025, 8, 1),
        ratio=Decimal("2"),
    )
    with pytest.raises(ValidationError):
        action.ratio = Decimal("3")  # type: ignore[misc]
