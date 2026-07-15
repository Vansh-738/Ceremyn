from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from alphaquant.config import Settings
from alphaquant.domain import Side, Signal, SignalAction, SignalLeg
from alphaquant.oms import (
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPositionSnapshot,
    BrokerSubmissionResult,
    OMSRetryableError,
)
from alphaquant.oms.broker import BrokerCancelResult, BrokerReplaceResult
from alphaquant.oms.exceptions import OMSNonRetryableBrokerError
from alphaquant.risk import RiskEngine
from tests.unit.backtest.helpers import make_contract

T0 = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)
EXPIRY = date(2026, 7, 29)


def permissive_settings() -> Settings:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 100
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    return settings


def make_signal(*, style: str = "market", correlation_id: UUID | None = None) -> Signal:
    metadata: dict[str, Any] = {"execution": {"style": style}}
    if style == "bracket":
        metadata["execution"]["bracket"] = {
            "take_profit_limit": "160",
            "stop_trigger": "140",
        }
    return Signal(
        strategy_id="strategy-1",
        signal_type=SignalAction.ENTER,
        created_at=T0,
        market_timestamp=T0,
        correlation_id=correlation_id,
        metadata=metadata,
        legs=(SignalLeg(contract=make_contract(expiry=EXPIRY), side=Side.BUY, lots=1),),
        reason="enter",
    )


def make_multi_leg_signal(*, legs: int = 4, correlation_id: UUID | None = None) -> Signal:
    """An Iron-Condor-shaped signal: several distinct-strike legs in one Signal."""
    return Signal(
        strategy_id="strategy-1",
        signal_type=SignalAction.ENTER,
        created_at=T0,
        market_timestamp=T0,
        correlation_id=correlation_id,
        metadata={"execution": {"style": "market"}},
        legs=tuple(
            SignalLeg(
                contract=make_contract(
                    symbol=f"NIFTY26JUL{25000 + index * 100}CE",
                    expiry=EXPIRY,
                    strike=str(25000 + index * 100),
                ),
                side=Side.BUY,
                lots=1,
            )
            for index in range(legs)
        ),
        reason="enter",
    )


class FakeBroker:
    def __init__(
        self,
        *,
        name: str = "fake",
        capabilities: BrokerCapabilities | None = None,
        fail_first_submit: bool = False,
        reject_tradingsymbols: frozenset[str] = frozenset(),
    ) -> None:
        self._name = name
        self._capabilities = capabilities or BrokerCapabilities(supports_replace=True)
        self._fail_first_submit = fail_first_submit
        self._submit_attempts = 0
        self._reject_tradingsymbols = reject_tradingsymbols
        self.orders: dict[str, BrokerOrderSnapshot] = {}
        self.reports: list[BrokerExecutionReport] = []
        self.positions: dict[str, int] = {}
        self.cash = Decimal("1000000")
        self.realized_pnl = Decimal("0")

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self._capabilities

    def submit(self, command: Any) -> BrokerSubmissionResult:
        self._submit_attempts += 1
        if self._fail_first_submit and self._submit_attempts == 1:
            raise OMSRetryableError("temporary timeout")
        if command.order.contract.tradingsymbol in self._reject_tradingsymbols:
            raise OMSNonRetryableBrokerError("broker rejected this leg")
        external_order_id = f"ext-{command.oms_order_id}"
        snapshot = BrokerOrderSnapshot(
            external_order_id=external_order_id,
            status=BrokerOrderStatus.ACKNOWLEDGED,
            broker_timestamp=command.requested_at,
            filled_quantity=0,
            remaining_quantity=command.order.quantity,
            correlation_id=str(command.correlation_id) if command.correlation_id else None,
            request_hash=command.request_hash,
        )
        self.orders[external_order_id] = snapshot
        return BrokerSubmissionResult(
            external_order_id=external_order_id,
            broker_timestamp=command.requested_at,
            broker_latency_seconds=0.05,
        )

    def cancel(self, command: Any) -> BrokerCancelResult:
        if command.external_order_id is not None and command.external_order_id in self.orders:
            snapshot = self.orders[command.external_order_id]
            self.orders[command.external_order_id] = snapshot.model_copy(
                update={"status": BrokerOrderStatus.CANCELLED}
            )
        return BrokerCancelResult(
            broker_timestamp=command.requested_at,
            broker_latency_seconds=0.02,
        )

    def replace(self, command: Any) -> BrokerReplaceResult:
        return BrokerReplaceResult(
            broker_timestamp=command.requested_at,
            broker_latency_seconds=0.01,
        )

    def lookup_order(self, command: Any) -> BrokerOrderSnapshot | None:
        expected = str(command.correlation_id) if command.correlation_id else None
        for snapshot in self.orders.values():
            if (
                snapshot.correlation_id == expected
                and snapshot.request_hash == command.request_hash
            ):
                return snapshot
        return None

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]:
        return tuple(self.orders.values())

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]:
        return tuple(self.reports)

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]:
        return tuple(
            BrokerPositionSnapshot(tradingsymbol=symbol, quantity=quantity)
            for symbol, quantity in self.positions.items()
        )

    def fetch_cash(self) -> BrokerCashSnapshot:
        return BrokerCashSnapshot(
            available_cash=self.cash,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=Decimal("0"),
        )


@pytest.fixture
def risk_engine() -> RiskEngine:
    return RiskEngine(permissive_settings())
