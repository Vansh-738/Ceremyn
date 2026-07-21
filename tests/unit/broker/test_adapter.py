from decimal import Decimal
from typing import cast

import pytest

from ceremyn.broker import NullBrokerAdapter
from ceremyn.oms.broker import BrokerAdapter
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand


def test_satisfies_broker_adapter_protocol() -> None:
    assert isinstance(NullBrokerAdapter(), BrokerAdapter)


def test_name_and_capabilities() -> None:
    adapter = NullBrokerAdapter()
    assert adapter.name == "none"
    assert adapter.capabilities is not None


def test_read_methods_are_empty() -> None:
    adapter = NullBrokerAdapter()
    assert adapter.fetch_orders() == ()
    assert adapter.fetch_fills() == ()
    assert adapter.fetch_positions() == ()
    assert adapter.fetch_cash().available_cash == Decimal("0")
    assert adapter.lookup_order(cast(SubmitOrderCommand, None)) is None


def test_submit_raises() -> None:
    with pytest.raises(NotImplementedError):
        NullBrokerAdapter().submit(cast(SubmitOrderCommand, None))


def test_cancel_raises() -> None:
    with pytest.raises(NotImplementedError):
        NullBrokerAdapter().cancel(cast(CancelOrderCommand, None))


def test_replace_raises() -> None:
    with pytest.raises(NotImplementedError):
        NullBrokerAdapter().replace(cast(ReplaceOrderCommand, None))
