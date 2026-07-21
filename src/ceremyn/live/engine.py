"""Production-grade live market-data engine."""

import time
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from ceremyn.core.events import EventBus
from ceremyn.core.timeutils import now_utc
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import OptionContract
from ceremyn.features.engine import FeatureEngine
from ceremyn.live.aggregator import TickAggregator
from ceremyn.live.cache import LiveDataCache
from ceremyn.live.events import (
    HeartbeatLost,
    HeartbeatRecovered,
    MarketClose,
    MarketOpen,
    ReconnectFailed,
    ReconnectStarted,
    ReconnectSucceeded,
    SnapshotBuilt,
    TickReceived,
)
from ceremyn.live.feed import SubscriptionManager, UnderlyingDefinition, build_subscription_plan
from ceremyn.live.heartbeat import HeartbeatMonitor
from ceremyn.live.kite import tick_timestamp
from ceremyn.live.market_hours import MarketHours, MarketStatus
from ceremyn.live.metrics import LiveMetrics, LiveMetricsSnapshot
from ceremyn.live.reconnect import ReconnectManager
from ceremyn.live.scheduler import MarketSessionScheduler
from ceremyn.live.snapshot import LiveTick, MarketSnapshot
from ceremyn.live.stream import StreamTickBatch
from ceremyn.live.validator import TickValidator
from ceremyn.paper import MarketTick


class LiveMarketDataEngine:
    def __init__(
        self,
        *,
        underlyings: Iterable[UnderlyingDefinition],
        contracts: Iterable[OptionContract],
        analytics: ChainAnalyticsService,
        client: Any | None = None,
        event_bus: EventBus | None = None,
        feature_engine: FeatureEngine | None = None,
        cache: LiveDataCache | None = None,
        metrics: LiveMetrics | None = None,
        market_hours: MarketHours | None = None,
        heartbeat: HeartbeatMonitor | None = None,
        reconnect: ReconnectManager | None = None,
        validator: TickValidator | None = None,
    ) -> None:
        self._plan = build_subscription_plan(
            underlyings=tuple(underlyings),
            contracts=tuple(contracts),
        )
        self._event_bus = event_bus or EventBus()
        self._metrics = metrics or LiveMetrics()
        self._cache = cache or LiveDataCache()
        self._market_hours = market_hours or MarketHours()
        self._heartbeat = heartbeat or HeartbeatMonitor()
        self._reconnect = reconnect or ReconnectManager()
        self._validator = validator or TickValidator()
        self._aggregator = TickAggregator(
            self._plan.instruments,
            analytics,
            feature_engine=feature_engine,
            market_hours=self._market_hours,
            validator=self._validator,
        )
        self._scheduler = MarketSessionScheduler(self._market_hours)
        self._subscriptions = SubscriptionManager(client) if client is not None else None

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def cache(self) -> LiveDataCache:
        return self._cache

    @property
    def metrics(self) -> LiveMetrics:
        return self._metrics

    def start(self) -> None:
        if self._subscriptions is not None:
            self._subscriptions.connect()
            self._subscriptions.apply(self._plan)

    def stop(self) -> None:
        if self._subscriptions is not None:
            self._subscriptions.close()

    def restore_subscriptions(self) -> None:
        if self._subscriptions is not None:
            self._subscriptions.restore()

    async def on_tick_batch(self, batch: StreamTickBatch) -> tuple[MarketSnapshot, ...]:
        self._heartbeat.record(batch.received_at)
        snapshots: list[MarketSnapshot] = []
        for payload in batch.ticks:
            snapshot = await self.on_raw_tick(payload, received_at=batch.received_at)
            if snapshot is not None:
                snapshots.append(snapshot)
        return tuple(snapshots)

    async def on_raw_tick(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime | None = None,
    ) -> MarketSnapshot | None:
        received = received_at or now_utc()
        self._heartbeat.record(received)
        started = time.perf_counter()
        tick = self._normalize_tick(payload, received_at=received)
        try:
            snapshot = self._aggregator.update(tick)
        except Exception:
            self._metrics.record_drop()
            raise
        self._metrics.record_tick(received, latency_ms=tick.latency_ms)
        self._metrics.record_processing_time((time.perf_counter() - started) * 1000)
        await self._event_bus.publish(TickReceived(occurred_at=received, tick=tick))
        if snapshot is None:
            return None
        self._cache.set_snapshot(snapshot)
        await self._publish_market_status(snapshot)
        await self._event_bus.publish(SnapshotBuilt(occurred_at=received, snapshot=snapshot))
        return snapshot

    async def check_heartbeat(self, *, now: datetime | None = None) -> None:
        moment = now or now_utc()
        state = self._heartbeat.check(moment)
        self._metrics.record_heartbeat_delay(state.delay_seconds)
        if not state.is_healthy and state.last_seen_at is not None:
            await self._event_bus.publish(
                HeartbeatLost(occurred_at=moment, last_seen_at=state.last_seen_at)
            )
            reconnect_state = self._reconnect.begin()
            self._metrics.record_reconnect()
            await self._event_bus.publish(
                ReconnectStarted(
                    occurred_at=moment,
                    reason="heartbeat timeout",
                    attempt=reconnect_state.attempts,
                )
            )

    async def on_reconnect_succeeded(self, *, when: datetime | None = None) -> None:
        moment = when or now_utc()
        previous_state = self._reconnect.state
        self._reconnect.succeed()
        await self._event_bus.publish(
            ReconnectSucceeded(
                occurred_at=moment,
                attempt=max(1, previous_state.attempts),
            )
        )
        heartbeat_state = self._heartbeat.record(moment)
        await self._event_bus.publish(
            HeartbeatRecovered(
                occurred_at=moment,
                delay_seconds=heartbeat_state.delay_seconds,
            )
        )
        self.restore_subscriptions()

    async def on_reconnect_failed(self, reason: str, *, when: datetime | None = None) -> None:
        moment = when or now_utc()
        state = self._reconnect.state
        await self._event_bus.publish(
            ReconnectFailed(
                occurred_at=moment,
                attempt=max(1, state.attempts),
                reason=reason,
            )
        )

    def latest_snapshot(self, underlying: str) -> MarketSnapshot | None:
        return self._cache.latest_snapshot(underlying)

    def latest_metrics(self, *, now: datetime | None = None) -> LiveMetricsSnapshot:
        return self._metrics.snapshot(now or now_utc())

    def as_paper_tick(self, snapshot: MarketSnapshot) -> MarketTick:
        return MarketTick(
            as_of=snapshot.timestamp,
            underlying=snapshot.underlying,
            chain=snapshot.option_chain,
            candles=snapshot.feature_context.candles,
            iv_history=snapshot.feature_context.iv_history,
        )

    def _normalize_tick(self, payload: dict[str, Any], *, received_at: datetime) -> LiveTick:
        instrument_token = int(payload["instrument_token"])
        descriptor = next(
            instrument
            for instrument in self._plan.instruments
            if instrument.instrument_token == instrument_token
        )
        event_timestamp = tick_timestamp(payload, fallback=received_at)
        bid = _depth_price(payload, side="buy")
        ask = _depth_price(payload, side="sell")
        return LiveTick(
            instrument_token=instrument_token,
            tradingsymbol=descriptor.tradingsymbol,
            underlying=descriptor.underlying,
            instrument_kind=descriptor.instrument_kind,
            timestamp=event_timestamp,
            last_price=Decimal(str(payload.get("last_price", 0))),
            bid=bid,
            ask=ask,
            volume=int(payload.get("volume_traded") or payload.get("volume") or 0),
            open_interest=int(payload.get("oi") or 0),
            exchange_timestamp=payload.get("exchange_timestamp"),
            received_at=received_at,
            sequence_id=_sequence_id(payload, event_timestamp),
        )

    async def _publish_market_status(self, snapshot: MarketSnapshot) -> None:
        previous, current = self._scheduler.transition(snapshot.underlying, snapshot.timestamp)
        if previous == current:
            return
        if current is MarketStatus.OPEN:
            await self._event_bus.publish(
                MarketOpen(occurred_at=snapshot.timestamp, underlying=snapshot.underlying)
            )
            return
        if previous is MarketStatus.OPEN:
            await self._event_bus.publish(
                MarketClose(occurred_at=snapshot.timestamp, underlying=snapshot.underlying)
            )


def _depth_price(payload: dict[str, Any], *, side: str) -> Decimal | None:
    depth = payload.get("depth") or {}
    levels = depth.get(side) or []
    if not levels:
        return None
    price = levels[0].get("price")
    return Decimal(str(price)) if price is not None else None


def _sequence_id(payload: dict[str, Any], timestamp: datetime) -> str:
    parts = [
        str(payload.get("instrument_token", "")),
        timestamp.isoformat(),
        str(payload.get("last_price", "")),
        str(payload.get("volume_traded", payload.get("volume", ""))),
        str(payload.get("oi", "")),
    ]
    return "|".join(parts)
