from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.domain import ChainEntry, OptionChainSnapshot
from alphaquant.live.exceptions import TickValidationError
from alphaquant.live.snapshot import InstrumentKind, LiveTick
from alphaquant.live.validator import TickValidator
from tests.unit.domain.conftest import make_contract
from tests.unit.live.conftest import BASE_TS


def make_live_tick(*, price: str = "100", offset_seconds: int = 0) -> LiveTick:
    timestamp = BASE_TS + timedelta(seconds=offset_seconds)
    return LiveTick(
        instrument_token=1,
        tradingsymbol="NIFTY 50",
        underlying="NIFTY",
        instrument_kind=InstrumentKind.INDEX,
        timestamp=timestamp,
        last_price=Decimal(price),
        volume=100,
        open_interest=0,
        received_at=timestamp,
        sequence_id=f"1|{timestamp.isoformat()}|{price}",
    )


def test_duplicate_tick_rejected() -> None:
    validator = TickValidator()
    tick = make_live_tick()
    validator.validate_tick(tick)
    with pytest.raises(TickValidationError, match="duplicate"):
        validator.validate_tick(tick)


def test_out_of_order_tick_rejected() -> None:
    validator = TickValidator()
    validator.validate_tick(make_live_tick(offset_seconds=5))
    with pytest.raises(TickValidationError, match="out-of-order"):
        validator.validate_tick(make_live_tick(offset_seconds=0))


def test_live_tick_model_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        make_live_tick(price="-1")


def test_broken_chain_rejected() -> None:
    validator = TickValidator()
    call = make_contract(expiry=BASE_TS.date() + timedelta(days=14))
    snapshot = OptionChainSnapshot(
        underlying="NIFTY",
        expiry=call.expiry,
        spot=Decimal("24000"),
        timestamp=BASE_TS,
        entries=(ChainEntry(contract=call),),
    )
    with pytest.raises(TickValidationError, match="missing call/put pair"):
        validator.validate_chain(snapshot)


def test_bid_above_ask_rejected() -> None:
    validator = TickValidator()
    tick = make_live_tick()
    bad = tick.model_copy(update={"bid": Decimal("101"), "ask": Decimal("100")})
    with pytest.raises(TickValidationError, match="bid exceeds ask"):
        validator.validate_tick(bad)
