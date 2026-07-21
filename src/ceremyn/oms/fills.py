"""Fill normalization and duplicate suppression."""

from decimal import Decimal

from ceremyn.domain import Fill
from ceremyn.oms.broker import BrokerExecutionReport, BrokerOrderStatus
from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.orders import OMSOrder


class FillProcessor:
    def __init__(self) -> None:
        self._seen_fill_ids: set[str] = set()

    def process(
        self,
        oms_order: OMSOrder,
        report: BrokerExecutionReport,
    ) -> tuple[OMSOrder, Fill | None, bool]:
        if report.fill_id is not None and report.fill_id in self._seen_fill_ids:
            duplicate = OMSEvent(
                event_type=OMSEventType.DUPLICATE_SUPPRESSED,
                oms_order_id=oms_order.oms_order_id,
                correlation_id=oms_order.correlation_id,
                payload={"fill_id": report.fill_id},
            )
            return oms_order.with_event(duplicate), None, True

        updated = oms_order
        fill: Fill | None = None
        if report.status is BrokerOrderStatus.ACKNOWLEDGED and oms_order.external_order_id is None:
            updated = updated.with_event(
                OMSEvent(
                    event_type=OMSEventType.ACKNOWLEDGED,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                    payload={
                        "external_order_id": report.external_order_id,
                        "broker_name": oms_order.broker_name or "",
                    },
                )
            )
        if report.last_fill_quantity > 0 and report.fill_price is not None:
            fill = Fill(
                order_id=oms_order.order.id,
                quantity=report.last_fill_quantity,
                price=Decimal(str(report.fill_price)),
                timestamp=report.broker_timestamp,
            )
            marker = report.fill_id or f"{report.external_order_id}:{report.broker_timestamp}"
            self._seen_fill_ids.add(marker)
            event_type = (
                OMSEventType.FILL_RECORDED
                if report.status is BrokerOrderStatus.FILLED or report.remaining_quantity == 0
                else OMSEventType.PARTIAL_FILL_RECORDED
            )
            updated = updated.with_event(
                OMSEvent(
                    event_type=event_type,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                    payload={
                        "quantity": report.last_fill_quantity,
                        "price": str(report.fill_price),
                        "fill_id": report.fill_id or "",
                    },
                )
            )
        elif report.status is BrokerOrderStatus.CANCELLED:
            updated = updated.with_event(
                OMSEvent(
                    event_type=OMSEventType.CANCELLED,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                )
            )
        elif report.status is BrokerOrderStatus.REJECTED:
            updated = updated.with_event(
                OMSEvent(
                    event_type=OMSEventType.REJECTED,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                    payload={"reason": report.message},
                )
            )
        elif report.status is BrokerOrderStatus.FAILED:
            updated = updated.with_event(
                OMSEvent(
                    event_type=OMSEventType.FAILED,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                    payload={"reason": report.message},
                )
            )
        elif report.status is BrokerOrderStatus.EXPIRED:
            updated = updated.with_event(
                OMSEvent(
                    event_type=OMSEventType.EXPIRED,
                    oms_order_id=oms_order.oms_order_id,
                    correlation_id=oms_order.correlation_id,
                    occurred_at=report.broker_timestamp,
                )
            )
        return updated, fill, False
