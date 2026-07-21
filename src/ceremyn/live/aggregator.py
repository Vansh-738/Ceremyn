"""Tick aggregation into chains, candles, and immutable snapshots."""

from collections import defaultdict
from decimal import Decimal

from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import Candle, ChainEntry, OptionChainSnapshot, Quote, TimeFrame
from ceremyn.features.context import FeatureContext
from ceremyn.features.engine import FeatureEngine
from ceremyn.live.feed import InstrumentDescriptor
from ceremyn.live.market_hours import MarketHours
from ceremyn.live.snapshot import InstrumentKind, LiveTick, MarketSnapshot
from ceremyn.live.validator import TickValidator


class TickAggregator:
    def __init__(
        self,
        descriptors: tuple[InstrumentDescriptor, ...],
        analytics: ChainAnalyticsService,
        *,
        feature_engine: FeatureEngine | None = None,
        market_hours: MarketHours | None = None,
        validator: TickValidator | None = None,
        candle_history_limit: int = 120,
    ) -> None:
        self._analytics = analytics
        self._feature_engine = feature_engine
        self._market_hours = market_hours or MarketHours()
        self._validator = validator or TickValidator()
        self._descriptor_by_token = {
            descriptor.instrument_token: descriptor for descriptor in descriptors
        }
        self._option_descriptors = tuple(
            descriptor
            for descriptor in descriptors
            if descriptor.instrument_kind is InstrumentKind.OPTION
        )
        self._quotes: dict[int, Quote] = {}
        self._spot_by_underlying: dict[str, Decimal] = {}
        self._current_candle: dict[str, Candle] = {}
        self._candle_history: dict[str, list[Candle]] = defaultdict(list)
        self._previous_chain: dict[str, OptionChainSnapshot] = {}
        self._candle_history_limit = candle_history_limit

    def update(self, tick: LiveTick) -> MarketSnapshot | None:
        self._validator.validate_tick(tick)
        descriptor = self._descriptor_by_token.get(tick.instrument_token)
        if descriptor is None:
            return None
        if descriptor.instrument_kind is InstrumentKind.INDEX:
            self._spot_by_underlying[descriptor.underlying] = tick.last_price
            self._update_candles(descriptor.underlying, tick)
        else:
            self._quotes[tick.instrument_token] = self._to_quote(tick)
        return self._build_snapshot(descriptor.underlying, tick)

    def _build_snapshot(self, underlying: str, tick: LiveTick) -> MarketSnapshot | None:
        spot = self._spot_by_underlying.get(underlying)
        if spot is None:
            return None
        contracts = [
            descriptor
            for descriptor in self._option_descriptors
            if descriptor.underlying == underlying and descriptor.contract is not None
        ]
        expiries = sorted(
            {descriptor.expiry for descriptor in contracts if descriptor.expiry is not None}
        )
        if not expiries:
            return None
        expiry = expiries[0]
        entries = []
        for descriptor in contracts:
            if descriptor.expiry != expiry or descriptor.contract is None:
                continue
            quote = self._quotes.get(descriptor.instrument_token)
            entries.append(ChainEntry(contract=descriptor.contract, quote=quote))
        if not entries or any(entry.quote is None for entry in entries):
            return None
        chain = OptionChainSnapshot(
            underlying=underlying,
            expiry=expiry,
            spot=spot,
            timestamp=tick.event_timestamp,
            entries=tuple(entries),
        )
        enriched = self._analytics.enrich(chain)
        self._validator.validate_chain(enriched)
        previous = self._previous_chain.get(underlying)
        self._previous_chain[underlying] = enriched
        candles = tuple(self._candle_history.get(underlying, ()))
        feature_context = FeatureContext(
            as_of=tick.event_timestamp,
            underlying=underlying,
            chain=enriched,
            previous_chain=previous,
            iv_history=self._iv_history(previous, enriched),
            candles=candles,
        )
        features = (
            self._feature_engine.compute_all(feature_context) if self._feature_engine else None
        )
        return MarketSnapshot(
            underlying=underlying,
            timestamp=tick.event_timestamp,
            market_status=self._market_hours.status(tick.event_timestamp),
            spot=spot,
            option_chain=enriched,
            feature_context=feature_context,
            features=features,
            source_tick_count=len(entries),
            latency_ms=tick.latency_ms,
        )

    def _update_candles(self, underlying: str, tick: LiveTick) -> None:
        bucket = tick.event_timestamp.replace(second=0, microsecond=0)
        current = self._current_candle.get(underlying)
        if current is not None and current.timestamp == bucket:
            updated = Candle(
                tradingsymbol=underlying,
                timeframe=TimeFrame.MINUTE,
                timestamp=bucket,
                open=current.open,
                high=max(current.high, tick.last_price),
                low=min(current.low, tick.last_price),
                close=tick.last_price,
                volume=max(current.volume, tick.volume),
                open_interest=tick.open_interest,
            )
            self._current_candle[underlying] = updated
            if self._candle_history[underlying]:
                self._candle_history[underlying][-1] = updated
            return
        candle = Candle(
            tradingsymbol=underlying,
            timeframe=TimeFrame.MINUTE,
            timestamp=bucket,
            open=tick.last_price,
            high=tick.last_price,
            low=tick.last_price,
            close=tick.last_price,
            volume=tick.volume,
            open_interest=tick.open_interest,
        )
        self._current_candle[underlying] = candle
        history = self._candle_history[underlying]
        history.append(candle)
        if len(history) > self._candle_history_limit:
            del history[0]

    def _to_quote(self, tick: LiveTick) -> Quote:
        return Quote(
            tradingsymbol=tick.tradingsymbol,
            timestamp=tick.event_timestamp,
            last_price=tick.last_price,
            bid=tick.bid,
            ask=tick.ask,
            volume=tick.volume,
            open_interest=tick.open_interest,
        )

    def _iv_history(
        self,
        previous: OptionChainSnapshot | None,
        current: OptionChainSnapshot,
    ) -> tuple[float, ...]:
        history: list[float] = []
        if previous is not None:
            prior_atm = self._analytics.atm_iv(previous)
            if prior_atm is not None:
                history.append(prior_atm)
        current_atm = self._analytics.atm_iv(current)
        if current_atm is not None:
            history.append(current_atm)
        return tuple(history)
