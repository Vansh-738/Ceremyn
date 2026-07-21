"""Shared fill-polling helper: both `RuntimeOrchestrator` and `RestPricePoller`
need to periodically ask a broker for new execution reports and apply them to the
OMS. `fetch_fills()` re-returns a broker's *entire* fill history on every call
(see `broker/simulated.py`, `execution/kite_broker.py`), so this tracks which
reports have already been applied rather than re-processing all of them.
"""

import structlog

from ceremyn.oms.broker import BrokerAdapter
from ceremyn.oms.engine import OrderManagementEngine

logger = structlog.get_logger(__name__)


class FillPoller:
    def __init__(self) -> None:
        self._processed_markers: set[str] = set()

    def poll(self, *, oms_engine: OrderManagementEngine, broker: BrokerAdapter) -> int:
        """Apply any not-yet-seen fills; returns how many were newly applied."""
        try:
            reports = broker.fetch_fills()
        except Exception:
            logger.error("fill_poll_failed", exc_info=True)
            return 0
        applied = 0
        for report in reports:
            marker = report.fill_id or f"{report.external_order_id}:{report.broker_timestamp}"
            if marker in self._processed_markers:
                continue
            self._processed_markers.add(marker)
            try:
                oms_engine.process_execution_report(report)
                applied += 1
            except KeyError:
                # The report references an order outside `external_index` — e.g.
                # right after a restart gap. Log and move on; reconciliation
                # (a periodic broker round-trip, unlike this local dedup) will
                # surface anything genuinely missing.
                logger.warning(
                    "fill_report_unknown_order", external_order_id=report.external_order_id
                )
        return applied
