from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.domain import ChainEntry, OptionChainSnapshot, OptionType
from tests.unit.domain.conftest import make_contract, make_quote


def entry(strike: int, option_type: OptionType, oi: int) -> ChainEntry:
    contract = make_contract(strike=strike, option_type=option_type)
    return ChainEntry(
        contract=contract, quote=make_quote(tradingsymbol=contract.tradingsymbol, open_interest=oi)
    )


def make_chain(entries: tuple[ChainEntry, ...], spot: int = 24010) -> OptionChainSnapshot:
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=date(2025, 7, 29),
        spot=Decimal(spot),
        timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
        entries=entries,
    )


@pytest.fixture
def chain() -> OptionChainSnapshot:
    return make_chain(
        (
            entry(24000, OptionType.CALL, oi=1_000_000),
            entry(24000, OptionType.PUT, oi=1_500_000),
            entry(24100, OptionType.CALL, oi=500_000),
            entry(24100, OptionType.PUT, oi=300_000),
        )
    )


def test_strikes_sorted_unique(chain: OptionChainSnapshot) -> None:
    assert chain.strikes == (Decimal(24000), Decimal(24100))


def test_atm_strike(chain: OptionChainSnapshot) -> None:
    assert chain.atm_strike == Decimal(24000)  # spot 24010 is nearer 24000


def test_pcr(chain: OptionChainSnapshot) -> None:
    assert chain.total_put_oi == 1_800_000
    assert chain.total_call_oi == 1_500_000
    assert chain.pcr == pytest.approx(1.2)


def test_pcr_none_when_no_call_oi() -> None:
    chain = make_chain((entry(24000, OptionType.PUT, oi=100),))
    assert chain.pcr is None


def test_get_entry(chain: OptionChainSnapshot) -> None:
    found = chain.get(Decimal(24100), OptionType.PUT)
    assert found is not None
    assert found.open_interest == 300_000
    assert chain.get(Decimal(99999), OptionType.CALL) is None


def test_empty_chain_rejected() -> None:
    with pytest.raises(ValidationError):
        make_chain(())
