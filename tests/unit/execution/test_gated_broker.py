from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphaquant.broker import NullBrokerAdapter, SimulatedBroker
from alphaquant.config import Settings, TradingMode
from alphaquant.domain import Order, Side
from alphaquant.domain.enums import OrderType
from alphaquant.execution import GatedBrokerAdapter, LiveTradingGate
from alphaquant.oms.broker import BrokerAdapter
from alphaquant.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand
from tests.unit.backtest.helpers import make_contract

T0 = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)
CONTRACT = make_contract()


def make_command() -> SubmitOrderCommand:
    order = Order(
        contract=CONTRACT, side=Side.BUY, quantity=25, order_type=OrderType.MARKET, created_at=T0
    )
    return SubmitOrderCommand(
        oms_order_id=uuid4(),
        strategy_id="strategy-1",
        broker_name="execution",
        request_hash="hash-1",
        order=order,
        requested_at=T0,
    )


def research_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def live_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, trading_mode=TradingMode.LIVE, live_trading_enabled=True
    )


class RecordingBroker:
    """A minimal BrokerAdapter that records whether it was ever touched."""

    def __init__(self, name: str) -> None:
        self.calls: list[str] = []
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self):  # type: ignore[no-untyped-def]
        from alphaquant.oms.broker import BrokerCapabilities

        return BrokerCapabilities()

    def submit(self, command):  # type: ignore[no-untyped-def]
        from alphaquant.oms.broker import BrokerSubmissionResult

        self.calls.append("submit")
        return BrokerSubmissionResult(external_order_id=f"{self._name}-1", broker_timestamp=T0)

    def cancel(self, command):  # type: ignore[no-untyped-def]
        from alphaquant.oms.broker import BrokerCancelResult

        self.calls.append("cancel")
        return BrokerCancelResult(broker_timestamp=T0)

    def replace(self, command):  # type: ignore[no-untyped-def]
        from alphaquant.oms.broker import BrokerReplaceResult

        self.calls.append("replace")
        return BrokerReplaceResult(broker_timestamp=T0)

    def lookup_order(self, command):  # type: ignore[no-untyped-def]
        self.calls.append("lookup_order")
        return None

    def fetch_orders(self):  # type: ignore[no-untyped-def]
        self.calls.append("fetch_orders")
        return ()

    def fetch_fills(self):  # type: ignore[no-untyped-def]
        self.calls.append("fetch_fills")
        return ()

    def fetch_positions(self):  # type: ignore[no-untyped-def]
        self.calls.append("fetch_positions")
        return ()

    def fetch_cash(self):  # type: ignore[no-untyped-def]
        from alphaquant.oms.broker import BrokerCashSnapshot

        self.calls.append("fetch_cash")
        return BrokerCashSnapshot(available_cash=Decimal("0"))


def make_adapter(*, settings: Settings, gate: LiveTradingGate | None = None):
    live = RecordingBroker("live")
    fallback = RecordingBroker("fallback")
    built: list[int] = []

    def live_factory() -> BrokerAdapter:
        built.append(1)
        return live

    adapter = GatedBrokerAdapter(
        live_factory=live_factory,
        fallback=fallback,
        gate=gate or LiveTradingGate(),
        settings=settings,
    )
    return adapter, live, fallback, built


def test_satisfies_broker_adapter_protocol() -> None:
    adapter, *_ = make_adapter(settings=research_settings())
    assert isinstance(adapter, BrokerAdapter)


def test_name_is_execution() -> None:
    adapter, *_ = make_adapter(settings=research_settings())
    assert adapter.name == "execution"


@pytest.mark.parametrize(
    "settings_factory,armed",
    [
        (research_settings, False),
        (research_settings, True),
        (live_settings, False),
    ],
)
def test_routes_to_fallback_when_any_gate_is_missing(settings_factory, armed: bool) -> None:
    settings = settings_factory()
    gate = LiveTradingGate()
    if armed and settings.trading_mode is TradingMode.LIVE and settings.live_trading_enabled:
        gate.arm(settings=settings, reason="ops")
    adapter, live, fallback, built = make_adapter(settings=settings, gate=gate)

    adapter.submit(make_command())

    assert fallback.calls == ["submit"]
    assert live.calls == []
    assert built == []  # the live broker was never constructed


def test_routes_to_live_only_when_all_three_gates_pass() -> None:
    settings = live_settings()
    gate = LiveTradingGate()
    gate.arm(settings=settings, reason="ops approved")
    adapter, live, fallback, built = make_adapter(settings=settings, gate=gate)

    adapter.submit(make_command())

    assert live.calls == ["submit"]
    assert fallback.calls == []
    assert built == [1]


def test_live_adapter_is_constructed_only_once() -> None:
    settings = live_settings()
    gate = LiveTradingGate()
    gate.arm(settings=settings, reason="ops approved")
    adapter, live, fallback, built = make_adapter(settings=settings, gate=gate)

    adapter.submit(make_command())
    adapter.fetch_orders()
    adapter.fetch_cash()

    assert built == [1]
    assert live.calls == ["submit", "fetch_orders", "fetch_cash"]


def test_capabilities_reflects_active_broker() -> None:
    settings = research_settings()
    adapter, *_ = make_adapter(settings=settings)
    assert adapter.capabilities is not None  # delegates to fallback without error


def test_routing_decisions_are_recorded() -> None:
    settings = live_settings()
    gate = LiveTradingGate()
    gate.arm(settings=settings, reason="ops approved")
    adapter, *_ = make_adapter(settings=settings, gate=gate)

    adapter.submit(make_command())

    kinds = [event.kind for event in gate.history()]
    assert kinds[-1] == "routed_live"


def test_all_read_and_write_methods_delegate_to_active_broker() -> None:
    settings = research_settings()
    adapter, live, fallback, built = make_adapter(settings=settings)

    command = make_command()
    adapter.submit(command)
    adapter.cancel(
        CancelOrderCommand(
            oms_order_id=command.oms_order_id, broker_name="execution", requested_at=T0
        )
    )
    adapter.replace(
        ReplaceOrderCommand(
            oms_order_id=command.oms_order_id, broker_name="execution", requested_at=T0
        )
    )
    adapter.lookup_order(command)
    adapter.fetch_orders()
    adapter.fetch_fills()
    adapter.fetch_positions()
    adapter.fetch_cash()

    assert fallback.calls == [
        "submit",
        "cancel",
        "replace",
        "lookup_order",
        "fetch_orders",
        "fetch_fills",
        "fetch_positions",
        "fetch_cash",
    ]
    assert live.calls == []
    assert built == []


def test_end_to_end_with_real_null_and_simulated_brokers() -> None:
    """Sanity: GatedBrokerAdapter composes cleanly with the real adapters, not just fakes."""
    settings = research_settings()
    gate = LiveTradingGate()
    adapter = GatedBrokerAdapter(
        live_factory=lambda: NullBrokerAdapter(),
        fallback=SimulatedBroker(),
        gate=gate,
        settings=settings,
    )
    result = adapter.submit(make_command())
    assert result.external_order_id.startswith("sim-")
