from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType
from tests.unit.domain.conftest import make_contract


def test_valid_contract_roundtrip() -> None:
    contract = make_contract(strike=24500, option_type=OptionType.PUT)
    assert contract.strike == Decimal(24500)
    assert contract.is_put and not contract.is_call
    assert contract.lot_size == 75


@pytest.mark.parametrize("bad_strike", [0, -100])
def test_strike_must_be_positive(bad_strike: int) -> None:
    with pytest.raises(ValidationError):
        make_contract(strike=bad_strike)


def test_lot_size_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_contract(lot_size=0)


def test_contracts_are_immutable() -> None:
    contract = make_contract()
    with pytest.raises(ValidationError):
        contract.strike = Decimal(25000)  # type: ignore[misc]
