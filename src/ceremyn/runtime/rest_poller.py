"""Simple REST-polling paper-trading loop.

An alternative to the WebSocket-based `RuntimeOrchestrator` for anyone without a
database set up: every `poll_interval_seconds`, fetch current option quotes
directly from Kite's REST API (no Postgres, no instrument-master seeding, no
subscription plan), build an `OptionChainSnapshot`, and run it through the exact
same strategy -> risk engine -> OMS pipeline everything else in this platform
uses. Less real-time than tick-by-tick streaming, but needs nothing beyond a
working Kite session.

Reuses `OrderManagementEngine.submit_correlated_signals` (same compensation/
idempotency/persistence machinery as the streaming path) and
`ChainAnalyticsService.enrich` (same greeks/IV as backtesting) — nothing here is
a parallel implementation of either.
"""

import asyncio
import contextlib
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import now_ist, now_utc
from ceremyn.data.providers.kite import KiteProvider
from ceremyn.data.services.chain_analytics import (
    ChainAnalyticsService,
    chain_last_prices,
    iv_rank,
)
from ceremyn.domain import ChainEntry, OptionChainSnapshot, OptionContract, Position
from ceremyn.features.context import FeatureContext
from ceremyn.features.engine import FeatureEngine
from ceremyn.features.models import FeatureSet
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.runtime.fills import FillPoller
from ceremyn.strategies import Strategy, StrategyContext

logger = structlog.get_logger(__name__)

_STRIKE_WINDOW_PCT = Decimal("0.10")  # keep quote batches small: +/-10% around spot
_IV_HISTORY_MAXLEN = 1000  # ~16 hours of polling at the default 60s interval


def _strategy_positions(engine: OrderManagementEngine, strategy_id: str) -> tuple[Position, ...]:
    """This strategy's own open positions, replayed from its own filled orders only.

    `OMSPortfolio.positions` is the whole account's net position per symbol (correct
    for margin/cash accounting — a real broker doesn't know about "strategies"
    either), but `StrategyContext.positions` is documented as "the strategy's own
    open positions." Feeding a strategy the whole account's positions makes every
    strategy think it owns every other strategy's legs too: with `ctx.positions`
    always non-empty, every strategy always takes its exit branch and tries to
    flatten legs it never opened, every single tick.
    """
    orders = sorted(
        (
            order
            for order in engine.orders.values()
            if order.strategy_id == strategy_id and order.filled_quantity > 0
        ),
        key=lambda order: order.updated_at,
    )
    positions: dict[str, Position] = {}
    for order in orders:
        symbol = order.order.contract.tradingsymbol
        current = positions.get(symbol, Position(contract=order.order.contract))
        assert order.average_fill_price is not None  # filled_quantity > 0 guarantees this
        positions[symbol] = current.apply_fill(
            order.order.side, order.filled_quantity, order.average_fill_price
        )
    return tuple(position for position in positions.values() if not position.is_flat)


def _orphaned_symbols(
    engine: OrderManagementEngine, active_strategy_ids: Iterable[str]
) -> tuple[str, ...]:
    """Tradingsymbols with a real open position that none of `active_strategy_ids`
    claims -- e.g. a strategy was removed from the live roster (or its definition
    changed) while it still had a position open. Nothing will ever generate an exit
    signal for these again, so they just sit there decaying until someone notices
    and closes them manually -- exactly what happened to two `long_strangle` legs
    left open after it was pulled from live trading.
    """
    claimed = {
        position.contract.tradingsymbol
        for strategy_id in active_strategy_ids
        for position in _strategy_positions(engine, strategy_id)
    }
    return tuple(
        symbol
        for symbol, position in engine.portfolio.positions.items()
        if not position.is_flat and symbol not in claimed
    )


class RestPricePoller:
    def __init__(
        self,
        *,
        kite_provider: KiteProvider,
        oms_engine: OrderManagementEngine,
        analytics: ChainAnalyticsService,
        cache: LiveDataCache,
        strategies: Sequence[Strategy[Any]] = (),
        underlying: str = "NIFTY",
        poll_interval_seconds: float = 60.0,
        calendar: MarketCalendar | None = None,
        feature_engine: FeatureEngine | None = None,
    ) -> None:
        self._kite = kite_provider
        self._oms_engine = oms_engine
        self._analytics = analytics
        self._cache = cache
        self._strategies = tuple(strategies)
        self._feature_engine = feature_engine
        # Surfaced to the dashboard's Feature Store page (`api/runtime.py::
        # _FeatureSourceAdapter`) — without this, that page reads from the older,
        # unused `PaperTradingEngine` stack and shows nothing forever, regardless of
        # how much real feature computation actually happens here.
        self._latest_features: FeatureSet | None = None
        self._underlying = underlying
        self._poll_interval_seconds = poll_interval_seconds
        self._calendar = calendar or MarketCalendar()
        self._contracts: tuple[OptionContract, ...] = ()
        self._expiry: date | None = None
        self._task: asyncio.Task[None] | None = None
        self._fill_poller = FillPoller()
        # Real IV rank needs real history — this platform never fabricates one, so it
        # accumulates from scratch as the poller runs and stays None (strategies that
        # need it correctly stay inactive) until there's enough of it to be meaningful.
        self._iv_history: list[float] = []
        # Surfaced to the dashboard (`api/runtime.py::_DataFeedSourceAdapter`) so a
        # broken feed (e.g. an expired Kite access token) shows up as a visible alert
        # instead of only ever appearing in the logs.
        self._consecutive_failures = 0
        self._last_error = ""
        self._last_success_at: datetime | None = None
        # Surfaced to the dashboard the same way (`api/runtime.py::
        # _DataFeedSourceAdapter`) -- a position left open by a strategy that's no
        # longer in `self._strategies` (e.g. removed from the live roster) will
        # never get an exit signal from anyone again. Silence here is exactly how
        # today's tangled long_strangle legs sat decaying toward expiry unnoticed;
        # this must be a loud, persistent alert instead.
        self._orphaned_symbols: tuple[str, ...] = ()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_success_at(self) -> datetime | None:
        return self._last_success_at

    @property
    def latest_features(self) -> FeatureSet | None:
        return self._latest_features

    @property
    def orphaned_symbols(self) -> tuple[str, ...]:
        return self._orphaned_symbols

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                if self._calendar.is_market_open(now_utc()) and self._strategies:
                    await self._poll_once()
                    self._consecutive_failures = 0
                    self._last_error = ""
                    self._last_success_at = now_utc()
            except Exception as exc:
                self._consecutive_failures += 1
                self._last_error = str(exc)
                logger.error("rest_poller_tick_failed", exc_info=True)
            await asyncio.sleep(self._poll_interval_seconds)

    async def _poll_once(self) -> None:
        spot = await self._kite.spot_price(self._underlying)
        contracts = await self._contracts_near(spot)
        if not contracts:
            return
        symbols = [f"{c.exchange.value}:{c.tradingsymbol}" for c in contracts]
        quotes = await self._kite.quotes(symbols)
        entries = tuple(
            ChainEntry(
                contract=contract,
                quote=quotes.get(f"{contract.exchange.value}:{contract.tradingsymbol}"),
            )
            for contract in contracts
        )
        snapshot = self._analytics.enrich(
            OptionChainSnapshot(
                underlying=self._underlying,
                expiry=contracts[0].expiry,
                spot=spot,
                timestamp=now_utc(),
                entries=entries,
            )
        )
        # The simulated broker fills against whatever quotes this cache holds
        # (`SimulatedBroker(market_data=...)` in `container.py`) — without this, any
        # order the strategy submits below would sit unfilled forever.
        self._cache.set_chain(snapshot)
        # `OMSPortfolio.snapshot()` returns whatever `mark()` last computed, not a live
        # read of `positions`/`cash` — nothing else in this loop ever calls it, so
        # without this the dashboard would show position_count=0 and pnl=0 forever,
        # regardless of how many orders actually fill.
        self._oms_engine.portfolio.mark(
            timestamp=now_utc(), last_prices=chain_last_prices(snapshot)
        )
        current_iv = self._analytics.atm_iv(snapshot)
        rank = iv_rank(current_iv, self._iv_history) if current_iv is not None else None
        if current_iv is not None:
            self._iv_history.append(current_iv)
            del self._iv_history[:-_IV_HISTORY_MAXLEN]
        if self._feature_engine is not None:
            try:
                self._latest_features = self._feature_engine.compute_all(
                    FeatureContext(
                        as_of=now_utc(),
                        underlying=self._underlying,
                        chain=snapshot,
                        iv_history=tuple(self._iv_history),
                    )
                )
            except Exception:
                logger.error("rest_poller_feature_computation_failed", exc_info=True)
        portfolio_snapshot = self._oms_engine.portfolio.snapshot()
        total_signals = 0
        days_to_expiry = (snapshot.expiry - now_ist().date()).days
        for strategy in self._strategies:
            ctx = StrategyContext(
                chain=snapshot,
                positions=_strategy_positions(self._oms_engine, strategy.definition.id),
                portfolio=portfolio_snapshot,
                iv_rank=rank,
                now=now_utc(),
            )
            try:
                signals = strategy.on_chain(ctx)
            except Exception:
                logger.error(
                    "rest_poller_strategy_failed", strategy_id=strategy.definition.id, exc_info=True
                )
                continue
            if signals:
                total_signals += len(signals)
                self._oms_engine.submit_correlated_signals(signals, now=now_utc())
        self._orphaned_symbols = _orphaned_symbols(
            self._oms_engine, (strategy.definition.id for strategy in self._strategies)
        )
        if self._orphaned_symbols:
            logger.error(
                "rest_poller_orphaned_positions",
                symbols=self._orphaned_symbols,
                reason="no currently-active strategy claims these open positions",
            )
        applied = self._fill_poller.poll(
            oms_engine=self._oms_engine, broker=self._oms_engine.router.brokers[0]
        )
        if applied:
            # Re-mark so position_count/margin/pnl reflect this tick's fills
            # immediately, instead of waiting for the next poll cycle's mark().
            self._oms_engine.portfolio.mark(
                timestamp=now_utc(), last_prices=chain_last_prices(snapshot)
            )
        logger.info(
            "rest_poller_tick",
            underlying=self._underlying,
            spot=str(spot),
            expiry=str(self._expiry),
            contracts_watched=len(contracts),
            days_to_expiry=days_to_expiry,
            atm_iv=current_iv,
            iv_rank=rank,
            iv_history_size=len(self._iv_history),
            signals_emitted=total_signals,
        )

    async def _contracts_near(self, spot: Decimal) -> tuple[OptionContract, ...]:
        if not self._contracts:
            all_contracts = await self._kite.fetch_option_contracts([self._underlying])
            today = now_ist().date()
            upcoming = sorted({c.expiry for c in all_contracts if c.expiry >= today})
            if not upcoming:
                return ()
            self._expiry = upcoming[0]
            self._contracts = tuple(c for c in all_contracts if c.expiry == self._expiry)
        low, high = spot * (1 - _STRIKE_WINDOW_PCT), spot * (1 + _STRIKE_WINDOW_PCT)
        return tuple(c for c in self._contracts if low <= c.strike <= high)
