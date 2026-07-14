from datetime import UTC, datetime
from uuid import UUID

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
        strategy_version="3",
        market_timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
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
    assert signal.market_timestamp.tzinfo is not None
    assert signal.underlying == "NIFTY"
    assert signal.signal_type is SignalAction.ENTER
    assert signal.action is SignalAction.ENTER


def test_signal_backwards_compatible_id_and_action_aliases() -> None:
    signal = Signal(
        id=UUID("2e48812a-a2e5-4f24-9d63-2859d8dcd2f2"),
        strategy_id="short_strangle_v1",
        action=SignalAction.EXIT,
        strategy_version="1",
        market_timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
        legs=(SignalLeg(contract=make_contract(), side=Side.BUY, lots=1),),
    )

    assert signal.signal_id == UUID("2e48812a-a2e5-4f24-9d63-2859d8dcd2f2")
    assert signal.id == signal.signal_id
    assert signal.action is SignalAction.EXIT


def test_signal_infers_scope_from_legs() -> None:
    signal = Signal(
        strategy_id="short_strangle_v1",
        action=SignalAction.ENTER,
        strategy_version="1",
        market_timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
        legs=(SignalLeg(contract=make_contract(underlying="BANKNIFTY"), side=Side.SELL, lots=1),),
    )

    assert signal.underlying == "BANKNIFTY"
    assert signal.expiry == make_contract(underlying="BANKNIFTY").expiry


def test_signal_requires_at_least_one_leg() -> None:
    with pytest.raises(ValidationError):
        Signal(strategy_id="s", action=SignalAction.EXIT, legs=())


def test_leg_lots_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SignalLeg(contract=make_contract(), side=Side.BUY, lots=0)
