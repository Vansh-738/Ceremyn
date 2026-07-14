"""Tick and snapshot validation."""

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from alphaquant.domain import OptionChainSnapshot
from alphaquant.live.exceptions import TickValidationError
from alphaquant.live.snapshot import InstrumentKind, LiveTick


class TickValidator:
    def __init__(self) -> None:
        self._last_seen: dict[int, tuple[datetime, str]] = {}

    def validate_tick(self, tick: LiveTick) -> None:
        if tick.last_price < 0:
            raise TickValidationError("negative price")
        if tick.bid is not None and tick.ask is not None and tick.bid > tick.ask:
            raise TickValidationError("bid exceeds ask")
        previous = self._last_seen.get(tick.instrument_token)
        digest = self._digest(tick)
        if previous is not None:
            last_timestamp, last_digest = previous
            if tick.event_timestamp < last_timestamp:
                raise TickValidationError("out-of-order tick")
            if tick.event_timestamp == last_timestamp and digest == last_digest:
                raise TickValidationError("duplicate tick")
        self._last_seen[tick.instrument_token] = (tick.event_timestamp, digest)

    def validate_chain(self, chain: OptionChainSnapshot) -> None:
        if chain.spot <= 0:
            raise TickValidationError("spot must be positive")
        strikes: dict[Decimal, set[str]] = {}
        for entry in chain.entries:
            if entry.contract.underlying != chain.underlying:
                raise TickValidationError("broken option chain underlying mismatch")
            if entry.contract.expiry != chain.expiry:
                raise TickValidationError("broken option chain expiry mismatch")
            strikes.setdefault(entry.contract.strike, set()).add(entry.contract.option_type.value)
        broken = [strike for strike, kinds in strikes.items() if kinds != {"CE", "PE"}]
        if broken:
            raise TickValidationError(f"broken option chain missing call/put pair at {broken[0]}")

    def option_ticks(self, ticks: Iterable[LiveTick]) -> tuple[LiveTick, ...]:
        return tuple(tick for tick in ticks if tick.instrument_kind is InstrumentKind.OPTION)

    def _digest(self, tick: LiveTick) -> str:
        return "|".join(
            [
                tick.event_timestamp.isoformat(),
                str(tick.last_price),
                str(tick.bid),
                str(tick.ask),
                str(tick.volume),
                str(tick.open_interest),
            ]
        )
