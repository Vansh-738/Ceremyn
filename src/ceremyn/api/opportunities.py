"""Read-only opportunity discovery surface for the dashboard's Markets page.

Wraps `ceremyn.patterns.find_opportunities` -- a real scan (a bhavcopy network
fetch per trading day in the lookback window, plus CPU-bound pattern detection
across every symbol), so it runs as a periodic background task
(`run_periodic_scan`, started from `api/app.py`'s lifespan) rather than on each
request. The endpoint just serves whatever the last completed scan found. Still
strictly read-only market intelligence: this router has no path to
execution/risk/OMS, the same guarantee `ceremyn.patterns` itself already gives
(see its own docstring) -- it only ranks what's worth a look.
"""

import asyncio
from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

from ceremyn.config import OpportunitiesSettings
from ceremyn.core.timeutils import now_utc, to_ist
from ceremyn.data.providers.nse_indices import fetch_index_constituents
from ceremyn.data.services.equity_history import (
    fetch_all_equity_candles,
    filter_by_min_avg_turnover,
)
from ceremyn.domain import Opportunity
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns import find_opportunities

logger = structlog.get_logger(__name__)

# A small, liquid, known-good watchlist -- only used when universe="watchlist".
WATCHLIST = frozenset(
    {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATAMOTORS", "LT"}
)
DEFAULT_LIMIT = 9

router = APIRouter()


class OpportunityView(BaseModel):
    tradingsymbol: str
    asset_class: str
    pattern_name: str
    direction: str
    detected_at: str
    occurrences: int
    hit_rate: float
    average_forward_return_pct: float
    forward_days: int
    edge_score: float


class ScanState(BaseModel):
    scanning: bool
    last_scanned_at: str | None
    symbols_scanned: int
    opportunities: list[OpportunityView]


_last_scan: tuple[datetime, tuple[OpportunityView, ...], int] | None = None
_scanning = False


def _to_view(o: Opportunity) -> OpportunityView:
    return OpportunityView(
        tradingsymbol=o.tradingsymbol,
        asset_class=o.asset_class.value,
        pattern_name=o.pattern_name,
        direction=o.direction.value,
        detected_at=o.detected_at.isoformat(),
        occurrences=o.occurrences,
        hit_rate=o.hit_rate,
        average_forward_return_pct=o.average_forward_return_pct,
        forward_days=o.forward_days,
        edge_score=o.edge_score,
    )


async def _scan_universe(settings: OpportunitiesSettings) -> set[str] | None:
    """Which symbols to fetch, per `settings.universe`. None means "every listed
    symbol" (only for the explicit "all_equities" opt-in)."""
    if settings.universe == "watchlist":
        return set(WATCHLIST)
    if settings.universe == "nifty500":
        return set(await fetch_index_constituents("nifty500"))
    return None


async def run_scan_once(settings: OpportunitiesSettings) -> None:
    """One full scan, storing its result for the endpoint to serve. Errors are
    logged and swallowed -- a failed scan must not crash the background loop or
    the app; the endpoint just keeps serving the previous result until the next
    attempt succeeds."""
    global _last_scan, _scanning
    _scanning = True
    try:
        end = to_ist(now_utc()).date()
        start = end - timedelta(days=settings.lookback_days)
        symbols = await _scan_universe(settings)
        candles_by_symbol = await fetch_all_equity_candles(start, end, symbols=symbols)
        # A liquidity floor within the chosen universe -- thin daily turnover is
        # what makes a stock cheap to move, even one that's index-vetted.
        candles_by_symbol = filter_by_min_avg_turnover(
            candles_by_symbol, settings.min_avg_daily_turnover
        )
        asset_class_by_symbol = dict.fromkeys(candles_by_symbol, AssetClass.EQUITY)
        # find_opportunities is CPU-bound (no I/O) -- run it off the event loop so
        # a whole-universe scan doesn't freeze every other request for minutes.
        opportunities = await asyncio.to_thread(
            find_opportunities, candles_by_symbol, asset_class_by_symbol
        )
        views = tuple(_to_view(o) for o in opportunities)
        _last_scan = (to_ist(now_utc()), views, len(candles_by_symbol))
        logger.info("opportunity_scan_completed", symbols=len(candles_by_symbol), found=len(views))
    except Exception:
        logger.exception("opportunity_scan_failed")
    finally:
        _scanning = False


async def run_periodic_scan(settings: OpportunitiesSettings) -> None:
    """Background task: scan once immediately, then every `scan_interval_hours`
    -- bhavcopy data only changes once per trading day, so more frequent
    rescans wouldn't find anything new anyway."""
    interval_seconds = settings.scan_interval_hours * 3600
    while True:
        await run_scan_once(settings)
        await asyncio.sleep(interval_seconds)


@router.get("/equity", response_model=ScanState)
async def list_equity_opportunities(
    limit: int = Query(default=DEFAULT_LIMIT, gt=0, le=200),
) -> ScanState:
    if _last_scan is None:
        return ScanState(
            scanning=_scanning, last_scanned_at=None, symbols_scanned=0, opportunities=[]
        )
    scanned_at, views, symbol_count = _last_scan
    return ScanState(
        scanning=_scanning,
        last_scanned_at=scanned_at.isoformat(),
        symbols_scanned=symbol_count,
        opportunities=list(views[:limit]),
    )
