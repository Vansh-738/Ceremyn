"""Order management engine."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.commission import IndianCostModel
from alphaquant.core.timeutils import now_utc
from alphaquant.domain import Signal
from alphaquant.oms.broker import BrokerAdapter, BrokerExecutionReport
from alphaquant.oms.events import OMSEvent, OMSEventType
from alphaquant.oms.exceptions import (
    OMSDuplicateRequestError,
    OMSKillSwitchActiveError,
    OMSRiskRejectedError,
)
from alphaquant.oms.executor import BrokerExecutor
from alphaquant.oms.fills import FillProcessor
from alphaquant.oms.idempotency import InMemoryIdempotencyStore
from alphaquant.oms.journal import OMSJournal
from alphaquant.oms.ledger import LedgerEntry, LedgerEntryKind, OMSLedger
from alphaquant.oms.metrics import OMSMetrics, OMSMetricsSnapshot
from alphaquant.oms.orders import (
    CancelOrderCommand,
    OMSExecutionState,
    OMSOrder,
    OrderPlan,
    OrderPlanner,
    PlannedOrder,
    ReplaceOrderCommand,
    SubmitOrderCommand,
)
from alphaquant.oms.positions import OMSPortfolio
from alphaquant.oms.reconciliation import OMSReconciler, ReconciliationReport
from alphaquant.oms.retry import RetryPolicy
from alphaquant.oms.router import BrokerRouter
from alphaquant.oms.validators import OMSValidator
from alphaquant.risk import RiskEngine


class OMSKillSwitch(BaseModel):
    model_config = ConfigDict(frozen=True)

    armed: bool = False
    reason: str = ""
    armed_at: datetime | None = None


class OrderManagementEngine:
    def __init__(
        self,
        *,
        risk_engine: RiskEngine,
        brokers: dict[str, BrokerAdapter],
        default_broker: str,
        portfolio: OMSPortfolio | None = None,
        journal: OMSJournal | None = None,
        ledger: OMSLedger | None = None,
        metrics: OMSMetrics | None = None,
        idempotency: InMemoryIdempotencyStore | None = None,
        retry_policy: RetryPolicy | None = None,
        validator: OMSValidator | None = None,
        commission_model: IndianCostModel | None = None,
    ) -> None:
        self.risk_engine = risk_engine
        self.router = BrokerRouter(brokers, default_broker=default_broker)
        self.portfolio = portfolio or OMSPortfolio()
        self.journal = journal or OMSJournal(session_id=f"oms-{uuid4()}")
        self.ledger = ledger or OMSLedger()
        self.metrics = metrics or OMSMetrics()
        self.idempotency = idempotency or InMemoryIdempotencyStore()
        self.retry_policy = retry_policy or RetryPolicy()
        self.validator = validator or OMSValidator()
        self.planner = OrderPlanner()
        self.executor = BrokerExecutor(self.retry_policy)
        self.fill_processor = FillProcessor()
        self.reconciler = OMSReconciler()
        self.commission_model = commission_model or IndianCostModel()
        self.orders: dict[UUID, OMSOrder] = {}
        self.external_index: dict[str, UUID] = {}
        self._children: dict[UUID, list[UUID]] = {}
        self.kill_switch = OMSKillSwitch()

    def arm_kill_switch(self, reason: str, *, at: datetime | None = None) -> None:
        moment = at or now_utc()
        self.kill_switch = OMSKillSwitch(armed=True, reason=reason, armed_at=moment)
        self.journal.record_kill_switch(armed=True, reason=reason, at=moment)

    def disarm_kill_switch(self, *, at: datetime | None = None) -> None:
        moment = at or now_utc()
        self.kill_switch = OMSKillSwitch()
        self.journal.record_kill_switch(armed=False, reason="", at=moment)

    def submit_signal(
        self,
        signal: Signal,
        *,
        now: datetime | None = None,
    ) -> tuple[OMSOrder, ...]:
        timestamp = now or signal.market_timestamp or signal.created_at
        self.journal.record_signal(signal, at=timestamp)
        decision = self.risk_engine.validate(
            self.portfolio.snapshot(),
            signal,
            evaluated_at=timestamp,
        )
        self.journal.record_risk(decision, signal)
        if not decision.approved:
            raise OMSRiskRejectedError("; ".join(decision.violations) or "risk rejected")

        intent = self.planner.intent_from_signal(signal, now=timestamp)
        self.validator.validate_intent(intent)
        plan = self.planner.plan(intent, now=timestamp)
        self.validator.validate_plan(plan)
        orders: list[OMSOrder] = []
        for planned_order in plan.orders:
            oms_order = self._build_oms_order(plan, planned_order, at=timestamp)
            duplicate = self.idempotency.reserve(oms_order.request_hash, oms_order.oms_order_id)
            if duplicate is not None:
                existing = self.orders[duplicate]
                suppressed = existing.with_event(
                    OMSEvent(
                        event_type=OMSEventType.DUPLICATE_SUPPRESSED,
                        oms_order_id=existing.oms_order_id,
                        correlation_id=existing.correlation_id,
                        occurred_at=timestamp,
                        payload={"request_hash": existing.request_hash},
                    )
                )
                self.orders[duplicate] = suppressed
                self.metrics.record_duplicate()
                raise OMSDuplicateRequestError(existing.request_hash)
            self.orders[oms_order.oms_order_id] = oms_order
            if oms_order.parent_order_id is not None:
                self._children.setdefault(oms_order.parent_order_id, []).append(
                    oms_order.oms_order_id
                )
            if planned_order.submit_immediately:
                oms_order = self._submit_existing_order(oms_order.oms_order_id, at=timestamp)
            orders.append(self.orders[oms_order.oms_order_id])
        return tuple(orders)

    def cancel_order(
        self,
        oms_order_id: UUID,
        *,
        reason: str = "",
        now: datetime | None = None,
    ) -> OMSOrder:
        order = self.orders[oms_order_id]
        broker = self.router.route(order)
        command = CancelOrderCommand(
            oms_order_id=oms_order_id,
            external_order_id=order.external_order_id,
            broker_name=broker.name,
            requested_at=now or now_utc(),
            reason=reason,
        )
        self.journal.record_command(command)
        self.ledger.append(
            LedgerEntry(
                kind=LedgerEntryKind.COMMAND,
                timestamp=command.requested_at,
                payload=command.model_dump(mode="json"),
            )
        )
        result = self.executor.cancel(broker, command)
        for event in result.events:
            order = order.with_event(event)
            self._record_event(event)
        self.orders[oms_order_id] = order
        return order

    def replace_order(
        self,
        oms_order_id: UUID,
        *,
        new_limit_price: Decimal | None = None,
        new_trigger_price: Decimal | None = None,
        reason: str = "",
        now: datetime | None = None,
    ) -> OMSOrder:
        order = self.orders[oms_order_id]
        broker = self.router.route(order)
        command = ReplaceOrderCommand(
            oms_order_id=oms_order_id,
            external_order_id=order.external_order_id,
            broker_name=broker.name,
            requested_at=now or now_utc(),
            new_limit_price=new_limit_price,
            new_trigger_price=new_trigger_price,
            reason=reason,
        )
        self.validator.validate_replace(
            command,
            broker.capabilities,
            kill_switch_armed=self.kill_switch.armed,
        )
        self.journal.record_command(command)
        result = self.executor.replace(broker, command)
        for event in result.events:
            order = order.with_event(event)
            self._record_event(event)
        self.orders[oms_order_id] = order
        return order

    def process_execution_report(self, report: BrokerExecutionReport) -> OMSOrder:
        oms_order_id = self.external_index[report.external_order_id]
        order = self.orders[oms_order_id]
        updated, fill, duplicate = self.fill_processor.process(order, report)
        self.orders[oms_order_id] = updated
        if duplicate:
            self.metrics.record_duplicate()
        self.metrics.record_broker_health(success=True)
        if fill is not None:
            costs = self.commission_model.calculate(
                side=updated.order.side,
                quantity=fill.quantity,
                price=fill.price,
            )
            self.portfolio.apply_fill(
                fill=fill,
                order=updated.order,
                strategy_id=updated.strategy_id,
                signal_id=updated.signal_id,
                costs=costs.total,
            )
            partial = updated.execution_state is OMSExecutionState.PARTIALLY_FILLED
            self.metrics.record_fill(partial=partial)
            self.journal.record_fill(
                fill,
                strategy_id=updated.strategy_id,
                side=updated.order.side.value,
                tradingsymbol=updated.order.contract.tradingsymbol,
            )
            self.ledger.append(
                LedgerEntry(
                    kind=LedgerEntryKind.FILL,
                    timestamp=fill.timestamp,
                    payload={
                        "oms_order_id": str(updated.oms_order_id),
                        "order_id": str(updated.order.id),
                        "tradingsymbol": updated.order.contract.tradingsymbol,
                        "side": updated.order.side.value,
                        "quantity": fill.quantity,
                        "price": str(fill.price),
                    },
                )
            )
        latest_event = updated.event_log[-1]
        self._record_event(latest_event)
        if updated.external_order_id is not None:
            self.external_index[updated.external_order_id] = updated.oms_order_id
        if updated.execution_state is OMSExecutionState.FILLED:
            self._activate_children(updated.order.id, at=report.broker_timestamp)
        self.journal.record_position_snapshot(
            self.portfolio.snapshot(),
            at=report.broker_timestamp,
        )
        return updated

    def reconcile(self, *, now: datetime | None = None) -> ReconciliationReport:
        broker = self.router.brokers[0]
        report = self.reconciler.reconcile(
            orders=tuple(self.orders.values()),
            broker=broker,
            ledger=self.ledger,
            portfolio=self.portfolio,
        )
        timestamp = now or now_utc()
        self.ledger.append(
            LedgerEntry(
                kind=LedgerEntryKind.RECONCILIATION,
                timestamp=timestamp,
                payload=report.model_dump(mode="json"),
            )
        )
        self.journal.record_reconciliation(report.model_dump(mode="json"), at=timestamp)
        return report

    def metrics_snapshot(self, *, now: datetime | None = None) -> OMSMetricsSnapshot:
        return self.metrics.snapshot(now or now_utc())

    def _build_oms_order(
        self,
        plan: OrderPlan,
        planned_order: "PlannedOrder",
        *,
        at: datetime,
    ) -> OMSOrder:
        request_hash = self.planner.request_hash(plan, planned_order)
        order = OMSOrder(
            plan_id=plan.plan_id,
            intent_id=plan.intent_id,
            parent_order_id=planned_order.parent_order_id,
            role=planned_order.role,
            request_hash=request_hash,
            strategy_id=plan.strategy_id,
            signal_id=plan.signal_id,
            correlation_id=plan.correlation_id,
            order=planned_order.order,
            created_at=at,
            updated_at=at,
        )
        for event_type in (
            OMSEventType.ORDER_VALIDATED,
            OMSEventType.ORDER_ROUTED,
        ):
            order = order.with_event(
                OMSEvent(
                    event_type=event_type,
                    oms_order_id=order.oms_order_id,
                    correlation_id=order.correlation_id,
                    occurred_at=at,
                )
            )
            self._record_event(order.event_log[-1])
        return order

    def _submit_existing_order(self, oms_order_id: UUID, *, at: datetime) -> OMSOrder:
        if self.kill_switch.armed:
            raise OMSKillSwitchActiveError(self.kill_switch.reason or "OMS kill switch is armed")
        order = self.orders[oms_order_id]
        broker = self.router.route(order)
        command = SubmitOrderCommand(
            oms_order_id=order.oms_order_id,
            correlation_id=order.correlation_id,
            signal_id=order.signal_id,
            strategy_id=order.strategy_id,
            broker_name=broker.name,
            request_hash=order.request_hash,
            order=order.order,
            requested_at=at,
        )
        self.validator.validate_submit(
            command,
            broker.capabilities,
            kill_switch_armed=self.kill_switch.armed,
        )
        self.journal.record_command(command)
        self.ledger.append(
            LedgerEntry(
                kind=LedgerEntryKind.COMMAND,
                timestamp=command.requested_at,
                payload=command.model_dump(mode="json"),
            )
        )
        result = self.executor.submit(broker, order, command)
        self.metrics.record_submission(
            result.elapsed_seconds,
            broker_latency_seconds=(
                result.submission.broker_latency_seconds if result.submission else 0.0
            ),
        )
        self.metrics.record_broker_health(success=result.submission is not None)
        if any(event.event_type is OMSEventType.RETRY_SCHEDULED for event in result.events):
            self.metrics.record_retry(
                success=any(
                    event.event_type is OMSEventType.RETRY_SUCCEEDED for event in result.events
                )
            )
        for event in result.events:
            order = order.with_event(event)
            self._record_event(event)
        if order.execution_state is OMSExecutionState.REJECTED:
            self.metrics.record_rejection()
        if order.external_order_id is not None:
            self.external_index[order.external_order_id] = order.oms_order_id
        self.orders[oms_order_id] = order
        return order

    def _activate_children(self, parent_order_id: UUID, *, at: datetime) -> None:
        for child_id in self._children.get(parent_order_id, []):
            child = self.orders[child_id]
            if child.execution_state in {OMSExecutionState.ROUTED, OMSExecutionState.VALIDATED}:
                if self.kill_switch.armed:
                    failed = child.with_event(
                        OMSEvent(
                            event_type=OMSEventType.FAILED,
                            oms_order_id=child.oms_order_id,
                            correlation_id=child.correlation_id,
                            occurred_at=at,
                            payload={
                                "reason": self.kill_switch.reason or "OMS kill switch is armed"
                            },
                        )
                    )
                    self.orders[child_id] = failed
                    self._record_event(failed.event_log[-1])
                    continue
                self._submit_existing_order(child_id, at=at)

    def _record_event(self, event: OMSEvent) -> None:
        self.journal.record_event(event)
        self.ledger.append(
            LedgerEntry(
                kind=LedgerEntryKind.EVENT,
                timestamp=event.occurred_at,
                payload=event.model_dump(mode="json"),
            )
        )
