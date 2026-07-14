import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from tests.unit.domain.conftest import make_contract


def test_leg_quantity_is_lots_times_lot_size() -> None:
    leg = SignalLeg(contract=make_contract(lot_size=75), side=Side.SELL, lots=2)
    assert leg.quantity == 150


def test_multi_leg_signal() -> None:
    # A short strangle: sell an OTM call and an OTM put.
    signal = Signal(
        strategy_id="short_strangle_v1",
        action=SignalAction.ENTER,
        legs=(
            SignalLeg(contract=make_contract(strike=24500), side=Side.SELL, lots=1),
            SignalLeg(
                contract=make_contract(strike=23500, option_type=OptionType.PUT),
                side=Side.SELL,
                lots=1,
            ),
        ),
        reason="IV rank 82 > threshold 70",
    )
    assert len(signal.legs) == 2
    assert signal.created_at.tzinfo is not None


def test_signal_requires_at_least_one_leg() -> None:
    with pytest.raises(ValidationError):
        Signal(strategy_id="s", action=SignalAction.EXIT, legs=())


def test_leg_lots_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SignalLeg(contract=make_contract(), side=Side.BUY, lots=0)
