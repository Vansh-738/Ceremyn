"""Runtime orchestrator: owns the application's trading lifecycle.

Wires the pipeline that was previously only ever exercised by tests: live market data
-> strategies -> risk engine -> OMS -> broker. Nothing here duplicates logic that
already exists elsewhere — it sequences existing engines exactly the way `paper/
engine.py::PaperTradingEngine` sequences its own components, but drives the M13
`OrderManagementEngine` + `GatedBrokerAdapter` stack instead, since that is the one
broker-agnostic path already built to route safely between simulated and live fills.

Ships inert by default: with no strategies configured and no streaming client wired,
`start()`/`stop()` are safe, well-tested no-ops around the live engine's own start/stop
(which is itself a no-op with no client). Enabling real strategies or a real Kite
streaming session is a separate configuration decision, not a side effect of this class
existing.
"""

import asyncio
import contextlib
from collections.abc import Sequence
from typing import Any

import structlog

from alphaquant.live.engine import LiveMarketDataEngine
from alphaquant.live.kite import KiteStreamingClient
from alphaquant.live.snapshot import MarketSnapshot
from alphaquant.live.stream import AsyncTickStream
from alphaquant.oms.engine import OrderManagementEngine
from alphaquant.paper.events import MarketTick
from alphaquant.paper.scheduler import PaperScheduler
from alphaquant.strategies import Strategy, StrategyContext

logger = structlog.get_logger(__name__)


class RuntimeOrchestrator:
    def __init__(
        self,
        *,
        live_engine: LiveMarketDataEngine,
        oms_engine: OrderManagementEngine,
        strategies: Sequence[Strategy[Any]] = (),
        scheduler: PaperScheduler | None = None,
        streaming_client: KiteStreamingClient | None = None,
        stream: AsyncTickStream | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._live_engine = live_engine
        self._oms_engine = oms_engine
        self._strategies = tuple(strategies)
        self._scheduler = scheduler or PaperScheduler()
        self._streaming_client = streaming_client
        self._stream = stream or AsyncTickStream()
        self._poll_interval_seconds = poll_interval_seconds
        self._processed_fill_markers: set[str] = set()
        self._tick_task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None

    @property
    def stream(self) -> AsyncTickStream:
        """The tick-data seam: bind a real streaming client's ticks to this."""
        return self._stream

    async def start(self) -> None:
        if self._streaming_client is not None:
            self._streaming_client.bind_stream(self._stream, engine=self._live_engine)
        self._live_engine.start()
        try:
            self._oms_engine.reconcile()
        except Exception:  # a startup broker round-trip must never block boot
            logger.warning("startup_reconciliation_failed", exc_info=True)
        self._tick_task = asyncio.create_task(self._consume_ticks())
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        for task in (self._tick_task, self._maintenance_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tick_task = None
        self._maintenance_task = None
        self._live_engine.stop()

    async def _consume_ticks(self) -> None:
        async for batch in self._stream.batches():
            snapshots = await self._live_engine.on_tick_batch(batch)
            for snapshot in snapshots:
                await self._on_snapshot(snapshot)

    async def _on_snapshot(self, snapshot: MarketSnapshot) -> None:
        tick = self._live_engine.as_paper_tick(snapshot)
        if not self._scheduler.is_open(tick.as_of):
            self._scheduler.ticks_skipped += 1
            return
        self._scheduler.ticks_processed += 1
        if not self._strategies:
            return
        for strategy in self._strategies:
            await self._run_strategy(strategy, tick)

    async def _run_strategy(self, strategy: Strategy[Any], tick: MarketTick) -> None:
        ctx = StrategyContext(
            chain=tick.chain,
            portfolio=self._oms_engine.portfolio.snapshot(),
            now=tick.as_of,
        )
        try:
            signals = strategy.on_chain(ctx)
        except Exception:
            logger.error(
                "strategy_on_chain_failed", strategy_id=strategy.definition.id, exc_info=True
            )
            return
        if not signals:
            return
        try:
            self._oms_engine.submit_correlated_signals(signals, now=tick.as_of)
        except Exception:
            # submit_correlated_signals already absorbs the expected per-signal OMS
            # rejections (risk/duplicate/kill-switch) internally; anything reaching
            # here is unexpected and must not take down the tick-consumer loop.
            logger.error(
                "signal_submission_failed", strategy_id=strategy.definition.id, exc_info=True
            )

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_seconds)
            await self._poll_fills()
            try:
                await self._live_engine.check_heartbeat()
            except Exception:
                logger.error("heartbeat_check_failed", exc_info=True)
            try:
                self._oms_engine.reconcile()
            except Exception:
                logger.error("periodic_reconciliation_failed", exc_info=True)

    async def _poll_fills(self) -> None:
        try:
            broker = self._oms_engine.router.brokers[0]
            reports = broker.fetch_fills()
        except Exception:
            logger.error("fill_poll_failed", exc_info=True)
            return
        for report in reports:
            marker = report.fill_id or f"{report.external_order_id}:{report.broker_timestamp}"
            if marker in self._processed_fill_markers:
                continue
            self._processed_fill_markers.add(marker)
            try:
                self._oms_engine.process_execution_report(report)
            except KeyError:
                # The report references an order outside `external_index` — e.g. right
                # after a restart gap. Log and move on; reconciliation will surface it.
                logger.warning(
                    "fill_report_unknown_order", external_order_id=report.external_order_id
                )
