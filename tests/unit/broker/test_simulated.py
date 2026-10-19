from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.broker import SimulatedBroker
from ceremyn.domain import EquityInstrument, Exchange, Order, Quote, Side
from ceremyn.domain.enums import OrderType, ProductType
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.broker import BrokerAdapter, BrokerOrderStatus
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand
from tests.unit.backtest.helpers import make_chain, make_contract

T0 = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)
CONTRACT = make_contract()


def make_order(*, quantity: int = 25) -> Order:
    return Order(
        contract=CONTRACT,
        side=Side.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
        created_at=T0,
    )


def make_command(order: Order, *, correlation_id: object = None) -> SubmitOrderCommand:
    return SubmitOrderCommand(
        oms_order_id=uuid4(),
        strategy_id="strategy-1",
        broker_name="execution",
        request_hash="hash-1",
        order=order,
        requested_at=T0,
        correlation_id=correlation_id,
    )


def test_satisfies_broker_adapter_protocol() -> None:
    assert isinstance(SimulatedBroker(), BrokerAdapter)


def test_capabilities_and_name() -> None:
    broker = SimulatedBroker(name="paper-safe")
    assert broker.name == "paper-safe"
    assert broker.capabilities.supports_brackets is True
    assert broker.capabilities.supports_replace is False


def test_submit_without_market_data_stays_open() -> None:
    broker = SimulatedBroker()
    command = make_command(make_order())
    result = broker.submit(command)

    assert result.external_order_id.startswith("sim-")
    orders = broker.fetch_orders()
    assert len(orders) == 1
    assert orders[0].status is BrokerOrderStatus.OPEN
    assert orders[0].filled_quantity == 0
    assert broker.fetch_fills() == ()
    assert broker.fetch_cash().available_cash == Decimal("1000000")


def test_submit_with_market_data_fills_realistically() -> None:
    cache = LiveDataCache()
    cache.set_chain(
        make_chain(timestamp=T0, last_price="120", bid="119", ask="121", contract=CONTRACT)
    )
    broker = SimulatedBroker(market_data=cache)

    order = make_order(quantity=25)
    broker.submit(make_command(order))

    orders = broker.fetch_orders()
    assert orders[0].status is BrokerOrderStatus.FILLED
    assert orders[0].filled_quantity == 25
    assert orders[0].remaining_quantity == 0

    fills = broker.fetch_fills()
    assert len(fills) == 1
    assert fills[0].last_fill_quantity == 25
    assert fills[0].fill_price is not None

    positions = broker.fetch_positions()
    assert len(positions) == 1
    assert positions[0].tradingsymbol == CONTRACT.tradingsymbol
    assert positions[0].quantity == 25

    cash = broker.fetch_cash()
    assert cash.available_cash < Decimal("1000000")


def test_equity_fills_only_from_an_explicit_cached_quote() -> None:
    equity = EquityInstrument(
        tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE"
    )
    order = Order(
        contract=equity,
        side=Side.BUY,
        quantity=10,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        created_at=T0,
    )
    cache = LiveDataCache()
    broker = SimulatedBroker(market_data=cache)

    broker.submit(make_command(order))
    assert broker.fetch_orders()[0].status is BrokerOrderStatus.OPEN

    cache.set_quote(
        Quote(
            tradingsymbol="RELIANCE",
            timestamp=T0,
            last_price=Decimal("1489.25"),
            bid=Decimal("1489.00"),
            ask=Decimal("1489.50"),
        )
    )
    orders = broker.fetch_orders()

    assert orders[0].status is BrokerOrderStatus.FILLED
    assert orders[0].average_price is not None


def test_lookup_order_matches_correlation_and_hash() -> None:
    broker = SimulatedBroker()
    correlation_id = uuid4()
    order = make_order()
    command = make_command(order, correlation_id=correlation_id)
    broker.submit(command)

    found = broker.lookup_order(command)
    assert found is not None
    assert found.external_order_id.startswith("sim-")

    unrelated = make_command(make_order(), correlation_id=uuid4())
    assert broker.lookup_order(unrelated) is None


def test_cancel_removes_resting_order() -> None:
    broker = SimulatedBroker()
    command = make_command(make_order())
    result = broker.submit(command)

    cancel = broker.cancel(
        CancelOrderCommand(
            oms_order_id=command.oms_order_id,
            external_order_id=result.external_order_id,
            broker_name="execution",
            requested_at=T0,
        )
    )
    assert cancel.accepted is True
    assert broker.fetch_orders()[0].status is BrokerOrderStatus.CANCELLED


def test_cancel_unknown_order_is_not_accepted() -> None:
    broker = SimulatedBroker()
    cancel = broker.cancel(
        CancelOrderCommand(
            oms_order_id=uuid4(),
            external_order_id="sim-does-not-exist",
            broker_name="execution",
            requested_at=T0,
        )
    )
    assert cancel.accepted is False


def test_replace_is_not_supported() -> None:
    broker = SimulatedBroker()
    with pytest.raises(NotImplementedError):
        broker.replace(
            ReplaceOrderCommand(
                oms_order_id=uuid4(),
                broker_name="execution",
                requested_at=T0,
            )
        )


def test_two_underlyings_only_the_one_with_data_fills() -> None:
    other_contract = make_contract(symbol="BANKNIFTY26JUL50000CE")
    other_contract = other_contract.model_copy(update={"underlying": "BANKNIFTY"})
    cache = LiveDataCache()
    cache.set_chain(
        make_chain(timestamp=T0, last_price="120", bid="119", ask="121", contract=CONTRACT)
    )
    broker = SimulatedBroker(market_data=cache, config=None, portfolio_config=PortfolioConfig())

    filled_order = make_order()
    unfilled_order = Order(
        contract=other_contract,
        side=Side.BUY,
        quantity=other_contract.lot_size,
        order_type=OrderType.MARKET,
        created_at=T0,
    )
    broker.submit(make_command(filled_order))
    broker.submit(make_command(unfilled_order))

    statuses = {o.filled_quantity > 0 for o in broker.fetch_orders()}
    assert statuses == {True, False}
