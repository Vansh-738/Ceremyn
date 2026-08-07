from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.domain import (
    AssetClass,
    CommodityContract,
    EquityInstrument,
    ETFInstrument,
    Exchange,
    FutureContract,
    OptionType,
)
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


def test_option_contract_asset_class() -> None:
    assert make_contract().asset_class is AssetClass.OPTION


def test_equity_instrument() -> None:
    equity = EquityInstrument(
        tradingsymbol="RELIANCE",
        exchange=Exchange.NSE,
        underlying="RELIANCE",
        isin="INE002A01018",
    )
    assert equity.asset_class is AssetClass.EQUITY
    assert equity.lot_size == 1  # cash equity default
    assert equity.expiry is None


def test_etf_instrument() -> None:
    etf = ETFInstrument(tradingsymbol="NIFTYBEES", exchange=Exchange.NSE, underlying="NIFTYBEES")
    assert etf.asset_class is AssetClass.ETF
    assert etf.lot_size == 1
    assert etf.isin is None


def test_future_contract_requires_expiry_and_lot_size() -> None:
    future = FutureContract(
        tradingsymbol="NIFTY25JULFUT",
        exchange=Exchange.NFO,
        underlying="NIFTY",
        expiry=make_contract().expiry,
        lot_size=75,
    )
    assert future.asset_class is AssetClass.FUTURES
    with pytest.raises(ValidationError):
        FutureContract(
            tradingsymbol="NIFTY25JULFUT",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            lot_size=75,
        )  # type: ignore[call-arg]  # missing required expiry


def test_equity_lot_size_defaults_but_can_be_overridden() -> None:
    equity = EquityInstrument(
        tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE", lot_size=1
    )
    assert equity.lot_size == 1


def test_commodity_contract_requires_expiry_and_lot_size() -> None:
    commodity = CommodityContract(
        tradingsymbol="CRUDEOIL26AUGFUT",
        exchange=Exchange.MCX,
        underlying="CRUDEOIL",
        expiry=make_contract().expiry,
        lot_size=100,
    )
    assert commodity.asset_class is AssetClass.COMMODITY
    assert commodity.exchange is Exchange.MCX
    with pytest.raises(ValidationError):
        CommodityContract(
            tradingsymbol="CRUDEOIL26AUGFUT",
            exchange=Exchange.MCX,
            underlying="CRUDEOIL",
            lot_size=100,
        )  # type: ignore[call-arg]  # missing required expiry
