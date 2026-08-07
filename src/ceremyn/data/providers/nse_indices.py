"""NSE index constituent lists (e.g. NIFTY 500) -- a free, public list of NSE's
established, index-vetted companies.

Used as the default opportunity-scan universe: NSE's own inclusion criteria
(minimum market cap, minimum trading frequency) already screen out the thin,
easily-manipulated micro-caps/penny stocks that a raw "every listed symbol"
scan would otherwise surface -- a real, defensible quality bar rather than an
invented heuristic.
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
