"""Order management engine."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from ceremyn.backtest.commission import IndianCostModel
from ceremyn.core.timeutils import now_utc
from ceremyn.domain import Signal
from ceremyn.oms.broker import BrokerAdapter, BrokerExecutionReport
from ceremyn.oms.compensation import compensate_siblings as _compensate_siblings_impl
from ceremyn.oms.compensation import (
    mark_submission_failed,
    needs_compensation,
)
from ceremyn.oms.compensation import submit_correlated_signals as _submit_correlated_impl
from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.exceptions import (
    OMSDuplicateRequestError,
    OMSKillSwitchActiveError,
    OMSNonRetryableBrokerError,
    OMSRiskRejectedError,
)
from ceremyn.oms.executor import BrokerExecutor
from ceremyn.oms.fills import FillProcessor
from ceremyn.oms.idempotency import InMemoryIdempotencyStore
from ceremyn.oms.journal import OMSJournal
from ceremyn.oms.ledger import LedgerEntry, LedgerEntryKind, OMSLedger
from ceremyn.oms.metrics import OMSMetrics, OMSMetricsSnapshot
from ceremyn.oms.orders import (
    CancelOrderCommand,
    OMSExecutionState,
    OMSOrder,
    OrderPlan,
    OrderPlanner,
    PlannedOrder,
    ReplaceOrderCommand,
    SubmitOrderCommand,
)
from ceremyn.oms.positions import OMSPortfolio
from ceremyn.oms.reconciliation import OMSReconciler, ReconciliationReport
from ceremyn.oms.restore import rebuild_oms_state, rebuild_portfolio_fills
from ceremyn.oms.retry import RetryPolicy
from ceremyn.oms.router import BrokerRouter
from ceremyn.oms.validators import OMSValidator
from ceremyn.risk import RiskEngine


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
                self._persist_order(suppressed, at=timestamp)
                self.metrics.record_duplicate()
                raise OMSDuplicateRequestError(existing.request_hash)
            self._persist_order(oms_order, at=timestamp)
            if oms_order.parent_order_id is not None:
                self._children.setdefault(oms_order.parent_order_id, []).append(
                    oms_order.oms_order_id
                )
            if planned_order.submit_immediately:
                try:
                    oms_order = self._submit_existing_order(oms_order.oms_order_id, at=timestamp)
                except OMSNonRetryableBrokerError as exc:
                    # The broker itself rejected this specific leg (bad margin, invalid
                    # instrument, ...) — record it as a failed leg rather than letting the
                    # exception abort the remaining legs of a multi-leg plan; compensation
                    # below decides what happens to any siblings already live/filled.
                    oms_order = mark_submission_failed(
                        self, oms_order.oms_order_id, reason=str(exc), at=timestamp
                    )
            orders.append(self.orders[oms_order.oms_order_id])

        if needs_compensation(orders):
            _compensate_siblings_impl(self, orders, at=timestamp)
        return tuple(orders)

    def submit_correlated_signals(
        self,
        signals: Sequence[Signal],
        *,
        now: datetime | None = None,
    ) -> tuple[OMSOrder, ...]:
        """Submit every signal from one strategy tick as a cohesive group.

        See `oms.compensation.submit_correlated_signals` for the full rationale —
        kept as a thin delegate here so callers keep using `engine.submit_correlated_
        signals(...)` while the implementation lives alongside the rest of the
        compensation logic.
        """
        return _submit_correlated_impl(self, signals, now=now)

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
        self._persist_order(order, at=command.requested_at)
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
        self._persist_order(order, at=command.requested_at)
        return order

    def process_execution_report(self, report: BrokerExecutionReport) -> OMSOrder:
        oms_order_id = self.external_index[report.external_order_id]
        order = self.orders[oms_order_id]
        updated, fill, duplicate = self.fill_processor.process(order, report)
        self._persist_order(updated, at=report.broker_timestamp)
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

    def _submit_existing_order(
        self, oms_order_id: UUID, *, at: datetime, bypass_kill_switch: bool = False
    ) -> OMSOrder:
        kill_switch_armed = self.kill_switch.armed and not bypass_kill_switch
        if kill_switch_armed:
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
            kill_switch_armed=kill_switch_armed,
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
        self._persist_order(order, at=at)
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
                    self._persist_order(failed, at=at)
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

    def _persist_order(self, order: OMSOrder, *, at: datetime) -> None:
        self.orders[order.oms_order_id] = order
        self.journal.record_order_snapshot(order, at=at)

    def restore_from_journal(self) -> None:
        """Rebuild `orders`/`external_index`/`_children`/idempotency AND portfolio
        cash/positions/realized_pnl from the journal.

        Pure local-disk state rebuild — never touches a broker. Call once after
        construction (e.g. at the composition root); intentionally not automatic in
        `__init__` so bare-constructed engines (tests) never do file I/O by surprise.

        Replaying fills here matters as much as restoring order metadata: without it, a
        restart doesn't just forget bookkeeping, it silently resets a real trading
        account's cash/positions/P&L back to its starting balance, discarding every
        fill's consequence even though the fills themselves were durably journaled.
        """
        state = rebuild_oms_state(self.journal.store)
        self.orders = dict(state.orders)
        self.external_index = dict(state.external_index)
        self._children = {parent: list(child_ids) for parent, child_ids in state.children.items()}
        self.idempotency.seed(state.idempotency_seed)
        for replay in rebuild_portfolio_fills(self.journal.store, self.orders):
            costs = self.commission_model.calculate(
                side=replay.order.side,
                quantity=replay.fill.quantity,
                price=replay.fill.price,
            )
            self.portfolio.apply_fill(
                fill=replay.fill,
                order=replay.order,
                strategy_id=replay.strategy_id,
                signal_id=None,
                costs=costs.total,
            )
        # `OMSPortfolio.snapshot()` returns whatever `mark()` last cached, not a live
        # read of cash/positions/realized_pnl -- `apply_fill` above updates the
        # underlying state correctly, but without a `mark()` call here, `snapshot()`
        # keeps returning the empty-account default from construction until the next
        # live tick happens to call it. Mark at each position's own average price
        # (unrealized_pnl honestly reads 0 until the next real quote arrives) so
        # anything that reads `snapshot()` between restart and the first live tick —
        # the dashboard, a diagnostic script — sees the real restored state.
        self.portfolio.mark(
            timestamp=now_utc(),
            last_prices={
                position.contract.tradingsymbol: position.avg_price
                for position in self.portfolio.positions.values()
            },
        )
