"""Read-only views over imported, publication-dated statements."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ceremyn.config import get_settings
from ceremyn.core.timeutils import now_utc
from ceremyn.fundamentals.provider import JSONFundamentalsStore
from ceremyn.fundamentals.scoring import known_as_of, score

router = APIRouter()


def fundamental_view(symbol: str, as_of: datetime, price: Decimal) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    symbol = symbol.strip().upper()
    history = JSONFundamentalsStore(Path(get_settings().fundamentals_path)).history(symbol)
    filings = known_as_of(history, symbol, as_of)
    result = score(history, symbol, as_of, price)
    return {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "price": str(price),
        "available": bool(filings),
        "score": result.model_dump(mode="json") if result else None,
        "filings": [row.model_dump(mode="json") for row in filings],
        "note": "Imported filings only; missing data is not a failed accounting check.",
    }


@router.get("/equity/{symbol}")
def get_fundamentals(
    symbol: str, price: Decimal = Query(gt=0), as_of: datetime | None = None
) -> dict[str, Any]:
    try:
        return fundamental_view(symbol, as_of or now_utc(), price)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
