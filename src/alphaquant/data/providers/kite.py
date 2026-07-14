"""Zerodha Kite Connect adapter (market data only).

Order placement does NOT live here — that's the execution layer's KiteBroker
(M10), behind the live-trading gates. The kiteconnect SDK is synchronous, so
every call is pushed off the event loop with asyncio.to_thread.

The underlying client object is injected to keep this adapter fully testable;
`KiteProvider.from_settings` builds the real one.
"""

import asyncio
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from alphaquant.config import Settings
from alphaquant.core.exceptions import BrokerError
from alphaquant.core.timeutils import IST, now_utc
from alphaquant.domain import Candle, Exchange, OptionContract, OptionType, Quote, TimeFrame

logger = structlog.get_logger(__name__)

SPOT_SYMBOLS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}

_QUOTE_BATCH = 400  # Kite's quote endpoint caps around 500 symbols per call


class KiteProvider:
    def __init__(self, kite: Any) -> None:
        self._kite = kite

    @classmethod
    def from_settings(cls, settings: Settings) -> "KiteProvider":
        from kiteconnect import KiteConnect

        if not settings.kite.api_key:
            raise BrokerError("ALPHAQUANT_KITE__API_KEY is not configured")
        return cls(KiteConnect(api_key=settings.kite.api_key))

    # -- auth -------------------------------------------------------------

    def login_url(self) -> str:
        return str(self._kite.login_url())

    async def authenticate(self, request_token: str, api_secret: str) -> None:
        """Exchange the login redirect's request token for an access token."""
        try:
            session = await asyncio.to_thread(
                self._kite.generate_session, request_token, api_secret=api_secret
            )
            self._kite.set_access_token(session["access_token"])
        except Exception as exc:
            raise BrokerError(f"Kite session exchange failed: {exc}") from exc

    def set_access_token(self, access_token: str) -> None:
        self._kite.set_access_token(access_token)

    # -- instruments --------------------------------------------------------

    async def fetch_option_contracts(
        self, underlyings: Sequence[str]
    ) -> list[OptionContract]:
        """All NFO option contracts for the given index underlyings."""
        try:
            dump: list[dict[str, Any]] = await asyncio.to_thread(self._kite.instruments, "NFO")
        except Exception as exc:
            raise BrokerError(f"Kite instrument dump failed: {exc}") from exc
        wanted = set(underlyings)
        contracts = [
            _instrument_to_contract(entry)
            for entry in dump
            if entry.get("name") in wanted and entry.get("instrument_type") in ("CE", "PE")
        ]
        logger.info("kite_contracts_fetched", count=len(contracts))
        return contracts

    # -- quotes ---------------------------------------------------------------

    async def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """Full quotes keyed by 'EXCHANGE:TRADINGSYMBOL'."""
        result: dict[str, Quote] = {}
        for start in range(0, len(symbols), _QUOTE_BATCH):
            batch = list(symbols[start : start + _QUOTE_BATCH])
            try:
                raw: dict[str, Any] = await asyncio.to_thread(self._kite.quote, batch)
            except Exception as exc:
                raise BrokerError(f"Kite quote fetch failed: {exc}") from exc
            for key, payload in raw.items():
                result[key] = _payload_to_quote(key, payload)
        return result

    async def spot_price(self, underlying: str) -> Decimal:
        symbol = SPOT_SYMBOLS.get(underlying)
        if symbol is None:
            raise BrokerError(f"no spot symbol mapping for underlying {underlying!r}")
        try:
            raw: dict[str, Any] = await asyncio.to_thread(self._kite.ltp, [symbol])
        except Exception as exc:
            raise BrokerError(f"Kite LTP fetch failed: {exc}") from exc
        return Decimal(str(raw[symbol]["last_price"]))

    # -- history --------------------------------------------------------------

    async def historical_candles(
        self,
        broker_token: int,
        tradingsymbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
        with_oi: bool = True,
    ) -> list[Candle]:
        try:
            raw: list[dict[str, Any]] = await asyncio.to_thread(
                self._kite.historical_data,
                broker_token,
                start,
                end,
                timeframe.value,
                oi=with_oi,
            )
        except Exception as exc:
            raise BrokerError(f"Kite historical fetch failed: {exc}") from exc
        return [
            Candle(
                tradingsymbol=tradingsymbol,
                timeframe=timeframe,
                timestamp=_ensure_ist(bar["date"]),
                open=Decimal(str(bar["open"])),
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                close=Decimal(str(bar["close"])),
                volume=int(bar.get("volume", 0)),
                open_interest=int(bar.get("oi", 0)),
            )
            for bar in raw
        ]


def _instrument_to_contract(entry: dict[str, Any]) -> OptionContract:
    return OptionContract(
        tradingsymbol=str(entry["tradingsymbol"]),
        exchange=Exchange.NFO,
        tick_size=Decimal(str(entry.get("tick_size", "0.05"))),
        broker_token=int(entry["instrument_token"]),
        underlying=str(entry["name"]),
        expiry=_ensure_date(entry["expiry"]),
        strike=Decimal(str(entry["strike"])),
        option_type=OptionType(entry["instrument_type"]),
        lot_size=int(entry["lot_size"]),
    )


def _payload_to_quote(key: str, payload: dict[str, Any]) -> Quote:
    tradingsymbol = key.split(":", 1)[-1]
    depth = payload.get("depth") or {}
    bids = depth.get("buy") or []
    asks = depth.get("sell") or []
    bid = Decimal(str(bids[0]["price"])) if bids and bids[0]["price"] else None
    ask = Decimal(str(asks[0]["price"])) if asks and asks[0]["price"] else None
    raw_ts = payload.get("timestamp") or payload.get("last_trade_time")
    timestamp = _ensure_ist(raw_ts) if isinstance(raw_ts, datetime) else now_utc()
    return Quote(
        tradingsymbol=tradingsymbol,
        timestamp=timestamp,
        last_price=Decimal(str(payload.get("last_price", 0))),
        bid=bid,
        ask=ask,
        volume=int(payload.get("volume", 0) or 0),
        open_interest=int(payload.get("oi", 0) or 0),
    )


def _ensure_ist(value: datetime) -> datetime:
    """Kite returns naive IST datetimes; make them explicit."""
    return value.replace(tzinfo=IST) if value.tzinfo is None else value


def _ensure_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
