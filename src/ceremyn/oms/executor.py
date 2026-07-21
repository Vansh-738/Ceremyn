"""Broker command execution with retry support."""

from datetime import datetime
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.oms.broker import (
    BrokerAdapter,
    BrokerCancelResult,
    BrokerReplaceResult,
    BrokerSubmissionResult,
)
from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.exceptions import OMSNonRetryableBrokerError
from ceremyn.oms.orders import (
    CancelOrderCommand,
    OMSOrder,
    ReplaceOrderCommand,
    SubmitOrderCommand,
)
from ceremyn.oms.retry import RetryPolicy


class ExecutorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[OMSEvent, ...] = ()
    submission: BrokerSubmissionResult | None = None
    cancel: BrokerCancelResult | None = None
    replace: BrokerReplaceResult | None = None
    attempts: int = Field(default=1, ge=1)
    elapsed_seconds: float = Field(default=0.0, ge=0)


class BrokerExecutor:
    def __init__(self, retry_policy: RetryPolicy) -> None:
        self._retry_policy = retry_policy

    def submit(
        self,
        broker: BrokerAdapter,
        oms_order: OMSOrder,
        command: SubmitOrderCommand,
    ) -> ExecutorResult:
        started = perf_counter()
        events = [
            OMSEvent(
                event_type=OMSEventType.SUBMIT_REQUESTED,
                oms_order_id=oms_order.oms_order_id,
                correlation_id=oms_order.correlation_id,
                occurred_at=command.requested_at,
            )
        ]
        attempt = 1
        while True:
            try:
                submission = broker.submit(command)
                if attempt > 1:
                    events.append(
                        OMSEvent(
                            event_type=OMSEventType.RETRY_SUCCEEDED,
                            oms_order_id=oms_order.oms_order_id,
                            correlation_id=oms_order.correlation_id,
                            occurred_at=submission.broker_timestamp,
                            payload={"attempt": attempt},
                        )
                    )
                events.append(
                    OMSEvent(
                        event_type=OMSEventType.ACKNOWLEDGED,
                        oms_order_id=oms_order.oms_order_id,
                        correlation_id=oms_order.correlation_id,
                        occurred_at=submission.broker_timestamp,
                        payload={
                            "external_order_id": submission.external_order_id,
                            "broker_name": broker.name,
                        },
                    )
                )
                return ExecutorResult(
                    events=tuple(events),
                    submission=submission,
                    attempts=attempt,
                    elapsed_seconds=perf_counter() - started,
                )
            except Exception as exc:
                lookup = broker.lookup_order(command)
                if lookup is not None:
                    synthetic = BrokerSubmissionResult(
                        external_order_id=lookup.external_order_id,
                        broker_timestamp=lookup.broker_timestamp,
                        status=lookup.status,
                        message=lookup.message,
                    )
                    events.append(
                        OMSEvent(
                            event_type=OMSEventType.ACKNOWLEDGED,
                            oms_order_id=oms_order.oms_order_id,
                            correlation_id=oms_order.correlation_id,
                            occurred_at=synthetic.broker_timestamp,
                            payload={
                                "external_order_id": synthetic.external_order_id,
                                "broker_name": broker.name,
                            },
                        )
                    )
                    return ExecutorResult(
                        events=tuple(events),
                        submission=synthetic,
                        attempts=attempt,
                        elapsed_seconds=perf_counter() - started,
                    )
                decision = self._retry_policy.decide(exc, attempt=attempt)
                if not decision.should_retry:
                    events.append(
                        OMSEvent(
                            event_type=OMSEventType.FAILED,
                            oms_order_id=oms_order.oms_order_id,
                            correlation_id=oms_order.correlation_id,
                            occurred_at=datetime.now(command.requested_at.tzinfo),
                            payload={"reason": decision.reason},
                        )
                    )
                    if isinstance(exc, OMSNonRetryableBrokerError):
                        raise
                    return ExecutorResult(
                        events=tuple(events),
                        attempts=attempt,
                        elapsed_seconds=perf_counter() - started,
                    )
                events.append(
                    OMSEvent(
                        event_type=OMSEventType.RETRY_SCHEDULED,
                        oms_order_id=oms_order.oms_order_id,
                        correlation_id=oms_order.correlation_id,
                        occurred_at=datetime.now(command.requested_at.tzinfo),
                        payload={"attempt": attempt, "reason": decision.reason},
                    )
                )
                attempt += 1

    def cancel(
        self,
        broker: BrokerAdapter,
        command: CancelOrderCommand,
        *,
        correlation_id: str | None = None,
    ) -> ExecutorResult:
        result = broker.cancel(command)
        return ExecutorResult(
            cancel=result,
            events=(
                OMSEvent(
                    event_type=OMSEventType.CANCEL_REQUESTED,
                    oms_order_id=command.oms_order_id,
                    occurred_at=command.requested_at,
                    payload={"reason": command.reason},
                ),
                OMSEvent(
                    event_type=OMSEventType.CANCELLED,
                    oms_order_id=command.oms_order_id,
                    occurred_at=result.broker_timestamp,
                    correlation_id=None,
                ),
            ),
        )

    def replace(self, broker: BrokerAdapter, command: ReplaceOrderCommand) -> ExecutorResult:
        result = broker.replace(command)
        return ExecutorResult(
            replace=result,
            events=(
                OMSEvent(
                    event_type=OMSEventType.REPLACED,
                    oms_order_id=command.oms_order_id,
                    occurred_at=result.broker_timestamp,
                ),
            ),
        )
