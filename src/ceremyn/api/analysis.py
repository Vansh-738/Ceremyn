"""Read-only per-symbol deep-dive analysis for the dashboard.

Reuses the opportunity scan's already-fetched, already-liquidity-filtered
candle history (see `ceremyn.api.opportunities`) so a lookup is instant -- no
new network fetch, no re-running the whole-market scan for one symbol. Every
pattern ever detected for the symbol is reported (see `analyze_symbol`'s own
docstring for why that's a deliberately wider net than the cross-market scan),
each labelled with whether it's active right now and whether it would clear
the scan's own quality bar. Strictly read-only market intelligence, same
guarantee as `ceremyn.patterns`/`ceremyn.api.opportunities`: no path to
execution/risk/OMS.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ceremyn.api import opportunities
from ceremyn.api.fundamentals import fundamental_view
from ceremyn.patterns import analyze_symbol, compute_fibonacci_levels

router = APIRouter()


class PatternTrackRecordView(BaseModel):
    pattern_name: str
    direction: str
    source: str
    active_now: bool
    occurrences: int
    hit_rate: float | None
    average_forward_return_pct: float | None
    forward_days: int
    is_opportunity_grade: bool


class FibonacciLevelsView(BaseModel):
    direction: str
    swing_start: float
    swing_start_at: str
    swing_end: float
    swing_end_at: str
    level_23_6: float
    level_38_2: float
    level_50_0: float
    level_61_8: float
    level_78_6: float
    golden_pocket_low: float
    golden_pocket_high: float


class SymbolAnalysis(BaseModel):
    tradingsymbol: str
    as_of: str
    latest_close: float
    latest_volume: int
    bars_analyzed: int
    last_scanned_at: str
    patterns: list[PatternTrackRecordView]
    fundamentals: dict[str, Any] | None = None
    fibonacci: FibonacciLevelsView | None


@router.get("/equity/{symbol}", response_model=SymbolAnalysis)
def analyze_equity(symbol: str) -> SymbolAnalysis:
    symbol = symbol.strip().upper()
    settings = opportunities.get_last_scan_settings()
    scanned_at = opportunities.get_last_scanned_at()
    if settings is None or scanned_at is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No opportunity scan has completed yet -- analysis needs at least "
                "one completed background scan (CEREMYN_OPPORTUNITIES__SCAN_ENABLED "
                "must be on)."
            ),
        )
    candles = opportunities.get_cached_candles(symbol)
    if not candles:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No analysis available for {symbol}. It may not be a valid NSE "
                "equity symbol, or it didn't clear the scan's liquidity floor "
                "(CEREMYN_OPPORTUNITIES__MIN_AVG_DAILY_TURNOVER)."
            ),
        )
    records = analyze_symbol(
        candles,
        forward_days=settings.forward_days,
        min_avg_forward_return_pct=settings.min_avg_forward_return_pct,
    )
    fib = compute_fibonacci_levels(candles, tradingsymbol=symbol)
    latest = candles[-1]
    return SymbolAnalysis(
        fundamentals=fundamental_view(symbol, latest.timestamp, latest.close),
        tradingsymbol=symbol,
        as_of=latest.timestamp.isoformat(),
        latest_close=float(latest.close),
        latest_volume=latest.volume,
        bars_analyzed=len(candles),
        last_scanned_at=scanned_at.isoformat(),
        patterns=[
            PatternTrackRecordView(
                pattern_name=r.pattern_name,
                direction=r.direction.value,
                source=r.source,
                active_now=r.active_now,
                occurrences=r.occurrences,
                hit_rate=r.hit_rate,
                average_forward_return_pct=r.average_forward_return_pct,
                forward_days=r.forward_days,
                is_opportunity_grade=r.is_opportunity_grade,
            )
            for r in records
        ],
        fibonacci=(
            FibonacciLevelsView(
                direction=fib.direction.value,
                swing_start=float(fib.swing_start),
                swing_start_at=fib.swing_start_at.isoformat(),
                swing_end=float(fib.swing_end),
                swing_end_at=fib.swing_end_at.isoformat(),
                level_23_6=float(fib.level_23_6),
                level_38_2=float(fib.level_38_2),
                level_50_0=float(fib.level_50_0),
                level_61_8=float(fib.level_61_8),
                level_78_6=float(fib.level_78_6),
                golden_pocket_low=float(fib.golden_pocket_low),
                golden_pocket_high=float(fib.golden_pocket_high),
            )
            if fib is not None
            else None
        ),
    )
