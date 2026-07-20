from decimal import Decimal

import pytest

from alphaquant.domain import EquityInstrument, Exchange, OptionContract, Position, Side
from tests.unit.domain.conftest import make_contract


@pytest.fixture
def flat(nifty_call: OptionContract) -> Position:
    return Position(contract=nifty_call)


def test_position_holds_a_non_option_instrument() -> None:
    equity = EquityInstrument(
        tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE"
    )
    pos = Position(contract=equity).apply_fill(Side.BUY, 10, Decimal("2500"))
    assert pos.quantity == 10
    assert pos.unrealized_pnl(Decimal("2550")) == Decimal(500)


class TestLongLifecycle:
    def test_open_long(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.BUY, 75, Decimal(100))
        assert pos.quantity == 75
        assert pos.avg_price == Decimal(100)
        assert pos.is_long

    def test_extend_long_weighted_average(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.BUY, 75, Decimal(100)).apply_fill(Side.BUY, 75, Decimal(110))
        assert pos.quantity == 150
        assert pos.avg_price == Decimal(105)

    def test_partial_close_books_realized_pnl(self, flat: Position) -> None:
        pos = (
            flat.apply_fill(Side.BUY, 75, Decimal(100))
            .apply_fill(Side.BUY, 75, Decimal(110))
            .apply_fill(Side.SELL, 75, Decimal(120))
        )
        assert pos.quantity == 75
        assert pos.avg_price == Decimal(105)  # unchanged on reduction
        assert pos.realized_pnl == Decimal(1125)  # (120-105)*75

    def test_full_close_resets_avg_price(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.BUY, 75, Decimal(100)).apply_fill(Side.SELL, 75, Decimal(95))
        assert pos.is_flat
        assert pos.avg_price == Decimal(0)
        assert pos.realized_pnl == Decimal(-375)  # (95-100)*75


class TestShortLifecycle:
    def test_open_short(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.SELL, 75, Decimal(100))
        assert pos.quantity == -75
        assert pos.is_short

    def test_buyback_profit(self, flat: Position) -> None:
        # Sold premium at 100, bought back at 80: profit for the short.
        pos = flat.apply_fill(Side.SELL, 75, Decimal(100)).apply_fill(Side.BUY, 75, Decimal(80))
        assert pos.is_flat
        assert pos.realized_pnl == Decimal(1500)  # (100-80)*75

    def test_unrealized_pnl_short(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.SELL, 75, Decimal(100))
        assert pos.unrealized_pnl(Decimal(90)) == Decimal(750)
        assert pos.unrealized_pnl(Decimal(120)) == Decimal(-1500)


class TestFlip:
    def test_flip_long_to_short(self, flat: Position) -> None:
        pos = flat.apply_fill(Side.BUY, 75, Decimal(100)).apply_fill(Side.SELL, 150, Decimal(90))
        assert pos.quantity == -75
        assert pos.avg_price == Decimal(90)  # remainder priced at the flipping fill
        assert pos.realized_pnl == Decimal(-750)  # (90-100)*75 on the closed long


class TestValidation:
    def test_zero_quantity_rejected(self, flat: Position) -> None:
        with pytest.raises(ValueError, match="quantity"):
            flat.apply_fill(Side.BUY, 0, Decimal(100))

    def test_non_positive_price_rejected(self, flat: Position) -> None:
        with pytest.raises(ValueError, match="price"):
            flat.apply_fill(Side.BUY, 75, Decimal(0))


def test_positions_reference_their_contract() -> None:
    contract = make_contract(strike=48000, underlying="BANKNIFTY", lot_size=30)
    pos = Position(contract=contract).apply_fill(Side.BUY, 30, Decimal(500))
    assert pos.contract.underlying == "BANKNIFTY"
    assert pos.quantity == 30
