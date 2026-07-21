"""Live option-chain assembly and the periodic snapshot job.

Every run builds the current chain for each configured underlying's nearest
expiry from live Kite quotes, enriches it with IV/greeks, and persists it —
accumulating our own intraday chain history from day one (EOD bhavcopy is the
only free historical source; intraday history has to be self-built).
"""

from datetime import date

import structlog

from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import now_ist, now_utc
from ceremyn.data.providers.kite import KiteProvider
from ceremyn.data.repositories.chains import ChainSnapshotRepository
from ceremyn.data.repositories.instruments import InstrumentRepository
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import ChainEntry, OptionChainSnapshot, OptionContract

logger = structlog.get_logger(__name__)


class ChainService:
    """Builds live OptionChainSnapshots from stored contracts + Kite quotes."""

    def __init__(
        self,
        provider: KiteProvider,
        instruments: InstrumentRepository,
        analytics: ChainAnalyticsService,
    ) -> None:
        self._provider = provider
        self._instruments = instruments
        self._analytics = analytics

    async def build(self, underlying: str, expiry: date) -> OptionChainSnapshot:
        # `list_contracts` is asset-class-generic (any Instrument sharing this
        # underlying+expiry); an option chain is options only, so narrow here
        # rather than widen `ChainEntry.contract`, which is deliberately
        # options-only.
        contracts = [
            contract
            for contract in await self._instruments.list_contracts(underlying, expiry)
            if isinstance(contract, OptionContract)
        ]
        if not contracts:
            raise ValueError(
                f"no stored contracts for {underlying} {expiry}; run seed_instruments first"
            )
        symbols = [f"{c.exchange.value}:{c.tradingsymbol}" for c in contracts]
        quotes = await self._provider.quotes(symbols)
        spot = await self._provider.spot_price(underlying)
        entries = tuple(
            ChainEntry(
                contract=contract,
                quote=quotes.get(f"{contract.exchange.value}:{contract.tradingsymbol}"),
            )
            for contract in contracts
        )
        snapshot = OptionChainSnapshot(
            underlying=underlying,
            expiry=expiry,
            spot=spot,
            timestamp=now_utc(),
            entries=entries,
        )
        return self._analytics.enrich(snapshot)

    async def nearest_expiry(self, underlying: str) -> date | None:
        expiries = await self._instruments.expiries(underlying, now_ist().date())
        return expiries[0] if expiries else None


class ChainSnapshotJob:
    """One tick of the intraday snapshot loop (scheduled every N minutes)."""

    def __init__(
        self,
        chain_service: ChainService,
        repository: ChainSnapshotRepository,
        calendar: MarketCalendar,
        underlyings: tuple[str, ...],
    ) -> None:
        self._chains = chain_service
        self._repository = repository
        self._calendar = calendar
        self._underlyings = underlyings

    async def run_once(self) -> int:
        """Snapshot every configured underlying; returns rows persisted."""
        if not self._calendar.is_market_open(now_ist()):
            logger.debug("snapshot_skipped_market_closed")
            return 0
        total = 0
        for underlying in self._underlyings:
            expiry = await self._chains.nearest_expiry(underlying)
            if expiry is None:
                logger.warning("snapshot_no_expiries", underlying=underlying)
                continue
            snapshot = await self._chains.build(underlying, expiry)
            total += await self._repository.save(snapshot)
            logger.info(
                "chain_snapshot_saved",
                underlying=underlying,
                expiry=str(expiry),
                entries=len(snapshot.entries),
            )
        return total
