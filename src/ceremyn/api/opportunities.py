"""Read-only opportunity discovery surface for the dashboard's Markets page.

Wraps `ceremyn.patterns.find_opportunities` -- a real scan (a bhavcopy network
fetch per trading day in the lookback window), so results are cached in-process
for `CACHE_TTL_SECONDS` to keep the dashboard responsive on repeat loads without
hammering NSE. Still strictly read-only market intelligence: this router has no
path to execution/risk/OMS, the same guarantee `ceremyn.patterns` itself already
gives (see its own docstring) -- it only ranks what's worth a look.
"""

import time
from datetime import timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ceremyn.core.timeutils import now_utc, to_ist
from ceremyn.data.services.equity_history import fetch_all_equity_candles
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns import find_opportunities

# A small, liquid, known-good watchlist rather than the whole equity universe --
# a full-universe scan is what scripts/find_opportunities.py --all-equities is
# for; the dashboard needs to stay fast on every page load, not exhaustive.
WATCHLIST = frozenset(
    {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATAMOTORS", "LT"}
)
LOOKBACK_DAYS = 400  # enough history for every detector family, incl. Cup-and-Handle
DEFAULT_LIMIT = 9
CACHE_TTL_SECONDS = 20 * 60

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
    edge_score: float


_cache: tuple[float, tuple[OpportunityView, ...]] | None = None


async def _scan() -> tuple[OpportunityView, ...]:
    end = to_ist(now_utc()).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    candles_by_symbol = await fetch_all_equity_candles(start, end, symbols=set(WATCHLIST))
    asset_class_by_symbol = dict.fromkeys(WATCHLIST, AssetClass.EQUITY)
    opportunities = find_opportunities(candles_by_symbol, asset_class_by_symbol)
    return tuple(
        OpportunityView(
            tradingsymbol=o.tradingsymbol,
            asset_class=o.asset_class.value,
            pattern_name=o.pattern_name,
            direction=o.direction.value,
            detected_at=o.detected_at.isoformat(),
            occurrences=o.occurrences,
            hit_rate=o.hit_rate,
            average_forward_return_pct=o.average_forward_return_pct,
            edge_score=o.edge_score,
        )
        for o in opportunities
    )


@router.get("/equity", response_model=list[OpportunityView])
async def list_equity_opportunities(
    limit: int = Query(default=DEFAULT_LIMIT, gt=0, le=50),
) -> list[OpportunityView]:
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > CACHE_TTL_SECONDS:
        _cache = (now, await _scan())
    return list(_cache[1][:limit])
