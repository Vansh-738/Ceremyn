from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.domain import (
    EquityInstrument,
    Exchange,
    OptionContract,
    Order,
    OrderStatus,
    OrderTransitionError,
    OrderType,
    Side,
)


def make_order(nifty_call: OptionContract, **overrides: object) -> Order:
    defaults: dict[str, object] = {
        "contract": nifty_call,
        "side": Side.SELL,
        "quantity": 75,
        "order_type": OrderType.LIMIT,
        "limit_price": Decimal("150.5"),
    }
    defaults.update(overrides)
    return Order.model_validate(defaults)


class TestOrderInvariants:
    def test_valid_order(self, nifty_call: OptionContract) -> None:
        order = make_order(nifty_call)
        assert order.status is OrderStatus.CREATED
        assert order.lots == 1

    def test_quantity_must_be_lot_multiple(self, nifty_call: OptionContract) -> None:
        with pytest.raises(ValidationError, match="lot size"):
            make_order(nifty_call, quantity=100)  # lot size is 75

    def test_limit_order_requires_price(self, nifty_call: OptionContract) -> None:
        with pytest.raises(ValidationError, match="limit_price"):
            make_order(nifty_call, limit_price=None)

    def test_stop_orders_require_trigger(self, nifty_call: OptionContract) -> None:
        with pytest.raises(ValidationError, match="trigger_price"):
            make_order(nifty_call, order_type=OrderType.SL_MARKET, limit_price=None)

    def test_market_order_needs_no_prices(self, nifty_call: OptionContract) -> None:
        order = make_order(nifty_call, order_type=OrderType.MARKET, limit_price=None)
        assert order.limit_price is None

    def test_order_holds_a_non_option_instrument(self) -> None:
        equity = EquityInstrument(
            tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE"
        )
        order = Order(
            contract=equity,
            side=Side.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
        )
        assert order.lots == 10  # lot_size defaults to 1 for a cash equity


class TestOrderStateMachine:
    def test_happy_path(self, nifty_call: OptionContract) -> None:
        order = make_order(nifty_call)
        for status in (
            OrderStatus.VALIDATED,
            OrderStatus.SUBMITTED,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        ):
            order = order.transition_to(status)
        assert order.is_terminal

    def test_cannot_skip_risk_validation(self, nifty_call: OptionContract) -> None:
        # CREATED -> SUBMITTED would mean an order reached the broker without
        # passing the risk engine; the state machine forbids it.
        order = make_order(nifty_call)
        with pytest.raises(OrderTransitionError):
            order.transition_to(OrderStatus.SUBMITTED)

    def test_terminal_states_are_final(self, nifty_call: OptionContract) -> None:
        order = make_order(nifty_call).transition_to(
            OrderStatus.REJECTED, reason="max_loss_per_trade"
        )
        assert order.status_reason == "max_loss_per_trade"
        with pytest.raises(OrderTransitionError):
            order.transition_to(OrderStatus.VALIDATED)

    def test_transition_returns_new_instance(self, nifty_call: OptionContract) -> None:
        order = make_order(nifty_call)
        validated = order.transition_to(OrderStatus.VALIDATED)
        assert order.status is OrderStatus.CREATED  # original untouched
        assert validated.id == order.id
