"""NSE index constituent lists (e.g. NIFTY 500) -- a free, public list of NSE's
established, index-vetted companies.

NSE's own inclusion criteria (minimum market cap, minimum trading frequency)
screen out the thinnest, easily-manipulated micro-caps/penny stocks -- a real,
defensible quality bar rather than an invented heuristic. But this endpoint
only ever returns the CURRENT constituent list, and `ceremyn.api.opportunities`
applies that one list across a multi-year lookback. That embeds a real
reconstitution/survivorship bias into any backtest run against it: a stock
that grew into the index recently gets its pre-inclusion history scanned too,
and a stock that fell out of the index (often after underperforming) is
excluded even from periods when it genuinely was a member. There is no free
historical NIFTY 500 membership feed to fix this properly, so treat the
`nifty500` universe option as a today's-universe convenience filter, not an
unbiased historical study -- prefer `all_equities` plus the turnover floor
(`ceremyn.data.services.equity_history.filter_by_min_avg_turnover`) for
backtesting integrity, since that filter is computed point-in-time per symbol
rather than from a single current membership snapshot.
"""

import csv
import io

import httpx
import structlog

from ceremyn.core.exceptions import DataError

logger = structlog.get_logger(__name__)

_HEADERS = {
    # Same archives host as bhavcopy; rejects default bot agents.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

INDEX_URLS = {
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
}


class IndexConstituentClient:
    """Downloads NSE's published constituent list for a named index."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    async def download(self, index: str) -> bytes:
        url = INDEX_URLS.get(index)
        if url is None:
            raise DataError(f"unknown index {index!r} -- no constituent list URL configured")
        async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise DataError(
                f"index constituent download failed for {index}: HTTP {response.status_code}"
            )
        return response.content


def parse_index_constituents(csv_bytes: bytes) -> frozenset[str]:
    """Extract trading symbols from an NSE index constituent CSV (columns:
    Company Name, Industry, Symbol, Series, ISIN Code)."""
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    symbols = {row["Symbol"].strip() for row in reader if row.get("Symbol", "").strip()}
    if not symbols:
        raise DataError("index constituent CSV parsed to zero symbols -- format may have changed")
    return frozenset(symbols)


async def fetch_index_constituents(index: str = "nifty500") -> frozenset[str]:
    """Fetch and parse `index`'s current constituent list (e.g. the real ~500
    NIFTY 500 member symbols)."""
    client = IndexConstituentClient()
    payload = await client.download(index)
    symbols = parse_index_constituents(payload)
    logger.info("index_constituents_fetched", index=index, count=len(symbols))
    return symbols
