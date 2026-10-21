from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from ceremyn.config import Settings
from ceremyn.core.exceptions import BrokerError
from ceremyn.domain import Order, Side
from ceremyn.domain.enums import OrderType
from ceremyn.execution import KiteBroker
from ceremyn.execution.kite_broker import _decimal_or_none, _parse_timestamp
from ceremyn.oms.broker import BrokerAdapter
from ceremyn.oms.exceptions import OMSNonRetryableBrokerError, OMSRetryableError
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand
from tests.unit.backtest.helpers import make_contract

T0 = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)
CONTRACT = make_contract()


class FakeKite:
    def __init__(self) -> None:
        self.place_order_kwargs: dict[str, Any] | None = None
        self.cancel_order_kwargs: dict[str, Any] | None = None
        self.modify_order_kwargs: dict[str, Any] | None = None
        self.fail_with: Exception | None = None

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def place_order(self, **kwargs: Any) -> str:
        self._maybe_fail()
        self.place_order_kwargs = kwargs
        return "KITE-1"

    def cancel_order(self, **kwargs: Any) -> str:
        self._maybe_fail()
        self.cancel_order_kwargs = kwargs
        return "KITE-1"

    def modify_order(self, **kwargs: Any) -> str:
        self._maybe_fail()
        self.modify_order_kwargs = kwargs
        return "KITE-1"

    def orders(self) -> list[dict[str, Any]]:
        self._maybe_fail()
        tag = (self.place_order_kwargs or {}).get("tag", "hash-1")
        return [
            {
                "order_id": "KITE-1",
                "status": "COMPLETE",
                "filled_quantity": 25,
                "pending_quantity": 0,
                "average_price": 121.5,
                "order_timestamp": datetime(2026, 7, 15, 9, 45),
                "tag": tag,
            }
        ]

    def trades(self) -> list[dict[str, Any]]:
        self._maybe_fail()
        return [
            {
                "order_id": "KITE-1",
                "trade_id": "T1",
                "quantity": 25,
                "average_price": 121.5,
                "fill_timestamp": datetime(2026, 7, 15, 9, 45),
            }
        ]

    def positions(self) -> dict[str, Any]:
        self._maybe_fail()
        return {
            "net": [
                {
                    "tradingsymbol": CONTRACT.tradingsymbol,
                    "quantity": 25,
                    "realised": 0,
                    "unrealised": 12.5,
                }
            ]
        }

    def margins(self, segment: str | None = None) -> dict[str, Any]:
        self._maybe_fail()
        return {"equity": {"available": {"live_balance": 998000.0}}}


def make_order() -> Order:
    return Order(
        contract=CONTRACT, side=Side.BUY, quantity=25, order_type=OrderType.MARKET, created_at=T0
    )


def make_submit_command() -> SubmitOrderCommand:
    return SubmitOrderCommand(
        oms_order_id=uuid4(),
        strategy_id="strategy-1",
        broker_name="kite",
        request_hash="hash-1",
        order=make_order(),
        requested_at=T0,
    )


def test_satisfies_broker_adapter_protocol() -> None:
    assert isinstance(KiteBroker(FakeKite()), BrokerAdapter)


def test_from_settings_requires_api_key() -> None:
    with pytest.raises(BrokerError):
        KiteBroker.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]


def test_from_settings_builds_client_with_api_key() -> None:
    settings = Settings(_env_file=None, kite={"api_key": "demo-key"})  # type: ignore[call-arg]
    broker = KiteBroker.from_settings(settings)
    assert broker.name == "kite"


def test_submit_maps_order_to_kite_call() -> None:
    kite = FakeKite()
    broker = KiteBroker(kite)
    result = broker.submit(make_submit_command())

    assert result.external_order_id == "KITE-1"
    assert kite.place_order_kwargs == {
        "variety": "regular",
        "exchange": "NFO",
        "tradingsymbol": CONTRACT.tradingsymbol,
        "transaction_type": "BUY",
        "quantity": 25,
        "product": "NRML",
        "order_type": "MARKET",
        "price": None,
        "trigger_price": None,
        "tag": "hash-1",
    }


def test_cancel_maps_to_kite_call() -> None:
    kite = FakeKite()
    broker = KiteBroker(kite)
    result = broker.cancel(
        CancelOrderCommand(
            oms_order_id=uuid4(), external_order_id="KITE-1", broker_name="kite", requested_at=T0
        )
    )
    assert result.accepted is True
    assert kite.cancel_order_kwargs == {"variety": "regular", "order_id": "KITE-1"}


def test_cancel_without_external_id_is_not_accepted() -> None:
    broker = KiteBroker(FakeKite())
    result = broker.cancel(
        CancelOrderCommand(oms_order_id=uuid4(), broker_name="kite", requested_at=T0)
    )
    assert result.accepted is False


def test_replace_maps_to_kite_call() -> None:
    from decimal import Decimal

    kite = FakeKite()
    broker = KiteBroker(kite)
    result = broker.replace(
        ReplaceOrderCommand(
            oms_order_id=uuid4(),
            external_order_id="KITE-1",
            broker_name="kite",
            requested_at=T0,
            new_limit_price=Decimal("125"),
        )
    )
    assert result.accepted is True
    assert kite.modify_order_kwargs is not None
    assert kite.modify_order_kwargs["price"] == 125.0


def test_replace_without_external_id_is_not_accepted() -> None:
    broker = KiteBroker(FakeKite())
    result = broker.replace(
        ReplaceOrderCommand(oms_order_id=uuid4(), broker_name="kite", requested_at=T0)
    )
    assert result.accepted is False


def test_fetch_orders_maps_kite_response() -> None:
    broker = KiteBroker(FakeKite())
    snapshots = broker.fetch_orders()
    assert len(snapshots) == 1
    assert snapshots[0].external_order_id == "KITE-1"
    assert snapshots[0].filled_quantity == 25


def test_fetch_fills_maps_kite_response() -> None:
    broker = KiteBroker(FakeKite())
    reports = broker.fetch_fills()
    assert len(reports) == 1
    assert reports[0].fill_id == "T1"
    assert reports[0].last_fill_quantity == 25


def test_fetch_positions_maps_kite_response() -> None:
    broker = KiteBroker(FakeKite())
    positions = broker.fetch_positions()
    assert len(positions) == 1
    assert positions[0].tradingsymbol == CONTRACT.tradingsymbol
    assert positions[0].quantity == 25


def test_fetch_cash_maps_kite_response() -> None:
    from decimal import Decimal

    broker = KiteBroker(FakeKite())
    cash = broker.fetch_cash()
    assert cash.available_cash == Decimal("998000.0")


def test_lookup_order_matches_previously_submitted_request() -> None:
    broker = KiteBroker(FakeKite())
    command = make_submit_command()
    broker.submit(command)

    found = broker.lookup_order(command)
    assert found is not None
    assert found.external_order_id == "KITE-1"


def test_lookup_order_no_match_returns_none() -> None:
    broker = KiteBroker(FakeKite())
    broker.submit(make_submit_command())

    unrelated = make_submit_command().model_copy(update={"request_hash": "other-hash"})
    assert broker.lookup_order(unrelated) is None


def test_lookup_recovers_full_length_hash_from_short_broker_tag() -> None:
    command = make_submit_command().model_copy(update={"request_hash": "a1b2c3d4" * 8})
    kite = FakeKite()
    KiteBroker(kite).submit(command)
    assert kite.place_order_kwargs is not None
    assert len(kite.place_order_kwargs["tag"]) == 20
    # A fresh adapter has no local knowledge of the accepted submission.
    found = KiteBroker(kite).lookup_order(command)
    assert found is not None
    assert found.external_order_id == "KITE-1"
    unrelated = command.model_copy(update={"request_hash": "f" * 64})
    assert KiteBroker(kite).lookup_order(unrelated) is None


def test_input_exception_maps_to_non_retryable() -> None:
    from kiteconnect.exceptions import InputException

    kite = FakeKite()
    kite.fail_with = InputException("bad input")
    broker = KiteBroker(kite)
    with pytest.raises(OMSNonRetryableBrokerError):
        broker.submit(make_submit_command())


def test_network_exception_maps_to_retryable() -> None:
    from kiteconnect.exceptions import NetworkException

    kite = FakeKite()
    kite.fail_with = NetworkException("timeout")
    broker = KiteBroker(kite)
    with pytest.raises(OMSRetryableError):
        broker.submit(make_submit_command())


def test_capabilities() -> None:
    capabilities = KiteBroker(FakeKite()).capabilities
    assert capabilities.supports_replace is True
    assert capabilities.supports_brackets is False
    assert capabilities.supports_tags is True


def test_lookup_order_finds_matching_request_hash() -> None:
    broker = KiteBroker(FakeKite())
    command = make_submit_command()
    snapshots = broker.fetch_orders()
    matching = snapshots[0].model_copy(update={"request_hash": command.request_hash})
    broker.fetch_orders = lambda: (matching,)  # type: ignore[method-assign]
    assert broker.lookup_order(command) is matching


def test_lookup_order_recovers_from_kite_tag_without_local_state() -> None:
    """The exact regression this fix targets: a submission whose response was lost
    (so this process never locally recorded anything) must still be found, because
    the idempotency key travels in Kite's own `tag` field, not local memory."""
    command = make_submit_command()

    class KiteAlreadyHoldingTheOrder(FakeKite):
        def orders(self) -> list[dict[str, Any]]:
            entries = super().orders()
            entries[0]["tag"] = command.request_hash
            return entries

    fresh_broker = KiteBroker(KiteAlreadyHoldingTheOrder())  # never called .submit()
    found = fresh_broker.lookup_order(command)
    assert found is not None
    assert found.external_order_id == "KITE-1"
    assert found.request_hash == command.request_hash


class TestParseTimestamp:
    def test_naive_datetime_gets_ist(self) -> None:
        result = _parse_timestamp(datetime(2026, 7, 15, 9, 45))
        assert result.tzinfo is not None

    def test_aware_datetime_passthrough(self) -> None:
        result = _parse_timestamp(T0)
        assert result == T0

    def test_iso_string_parsed(self) -> None:
        result = _parse_timestamp("2026-07-15T09:45:00")
        assert result.tzinfo is not None

    def test_aware_iso_string_passthrough(self) -> None:
        result = _parse_timestamp("2026-07-15T09:45:00+00:00")
        assert result.tzinfo is not None

    def test_invalid_string_falls_back_to_now(self) -> None:
        result = _parse_timestamp("not-a-timestamp")
        assert result.tzinfo is not None

    def test_missing_value_falls_back_to_now(self) -> None:
        assert _parse_timestamp(None).tzinfo is not None


class TestDecimalOrNone:
    def test_none_is_none(self) -> None:
        assert _decimal_or_none(None) is None

    def test_zero_is_none(self) -> None:
        assert _decimal_or_none(0) is None

    def test_empty_string_is_none(self) -> None:
        assert _decimal_or_none("") is None

    def test_value_converts(self) -> None:
        from decimal import Decimal

        assert _decimal_or_none("121.5") == Decimal("121.5")
