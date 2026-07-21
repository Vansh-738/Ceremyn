from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ceremyn.domain import Exchange, OptionContract, OptionType, Quote


def make_contract(
    strike: int = 24000,
    option_type: OptionType = OptionType.CALL,
    underlying: str = "NIFTY",
    lot_size: int = 75,
    expiry: date = date(2025, 7, 29),
) -> OptionContract:
    suffix = option_type.value
    return OptionContract(
        tradingsymbol=f"{underlying}25JUL{strike}{suffix}",
        exchange=Exchange.NFO,
        underlying=underlying,
        expiry=expiry,
        strike=Decimal(strike),
        option_type=option_type,
        lot_size=lot_size,
    )


def make_quote(
    tradingsymbol: str = "NIFTY25JUL24000CE",
    last_price: str = "150",
    bid: str | None = "149.5",
    ask: str | None = "150.5",
    open_interest: int = 0,
) -> Quote:
    return Quote(
        tradingsymbol=tradingsymbol,
        timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
        last_price=Decimal(last_price),
        bid=None if bid is None else Decimal(bid),
        ask=None if ask is None else Decimal(ask),
        open_interest=open_interest,
    )


@pytest.fixture
def nifty_call() -> OptionContract:
    return make_contract()


@pytest.fixture
def nifty_put() -> OptionContract:
    return make_contract(option_type=OptionType.PUT)
